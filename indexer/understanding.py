"""Grounded, derived code understanding over the existing code index."""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

from indexer.indexer import CodeIndexer

UNDERSTANDING_SCHEMA = """
CREATE TABLE IF NOT EXISTS code_understanding_cache (
    cache_key TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    query TEXT NOT NULL,
    depth INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    artifact_json TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


@dataclass(frozen=True)
class Budget:
    max_nodes: int = 80
    max_chars: int = 7000
    max_ms: int = 1000

    @classmethod
    def bounded(cls, max_nodes: int = 80, max_chars: int = 7000, max_ms: int = 1000) -> Budget:
        return cls(
            max(8, min(int(max_nodes), 200)),
            max(500, min(int(max_chars), 20000)),
            max(50, min(int(max_ms), 3000)),
        )


class CodeUnderstanding:
    """Build bounded hierarchy and task context without duplicating graph facts."""

    def __init__(self, indexer: CodeIndexer, memory_search: Callable[[str, int], list[dict]] | None = None):
        self.indexer = indexer
        self.memory_search = memory_search
        self.indexer.conn.executescript(UNDERSTANDING_SCHEMA)
        self.indexer.conn.commit()

    @staticmethod
    def _component(path: str) -> str:
        parts = [part for part in path.replace("\\", "/").split("/") if part]
        if not parts:
            return "root"
        if len(parts) == 1:
            return parts[0].rsplit(".", 1)[0]

        # Strip common top-level noise to group by actual feature/domain
        noise_dirs = {"src", "lib", "app", "tests", "test", "packages", "apps"}
        meaningful_parts = [p for p in parts if p.lower() not in noise_dirs]

        if len(meaningful_parts) >= 2:
            return "/".join(meaningful_parts[:2])
        return "/".join(meaningful_parts) if meaningful_parts else "root"

    @staticmethod
    def _tokens(query: str) -> list[str]:
        return [token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9_]+|/[A-Za-z0-9_]+", query) if len(token) > 2]

    def _lexical_hits(self, query: str, limit: int) -> list[dict]:
        hits = self.indexer.search_symbols(query, limit=min(30, max(10, limit)))
        if hits:
            return hits
        tokens = self._tokens(query)
        if not tokens:
            return []
        where = " OR ".join(["(symbol_name LIKE ? OR file_path LIKE ? OR docstring LIKE ?)"] * len(tokens))
        params = [value for token in tokens for value in (f"%{token}%", f"%{token}%", f"%{token}%")]
        cur = self.indexer.conn.execute(
            f"SELECT id, file_path, symbol_name, symbol_type, signature, docstring, start_line, end_line "
            f"FROM code_symbols WHERE project_id = ? AND {where} "
            "ORDER BY is_generated(file_path), id LIMIT ?",
            (self.indexer.project_id, *params, limit),
        )
        return [dict(row) for row in cur.fetchall()]

    def _neighbors(self, hits: list[dict], depth: int, budget: Budget, started: float) -> dict[int, dict]:
        symbols: dict[int, dict] = {int(hit["id"]): dict(hit) for hit in hits}
        queue = deque((int(hit["id"]), 0) for hit in hits)
        while queue and len(symbols) < budget.max_nodes and (time.monotonic() - started) < budget.max_ms / 1000:
            symbol_id, distance = queue.popleft()
            if distance >= depth:
                continue
            cur = self.indexer.conn.execute(
                "SELECT from_symbol_id AS other, to_name, edge_type FROM code_edges "
                "WHERE project_id = ? AND to_symbol_id = ? UNION ALL "
                "SELECT to_symbol_id AS other, from_name, edge_type FROM code_edges "
                "WHERE project_id = ? AND from_symbol_id = ? LIMIT ?",
                (self.indexer.project_id, symbol_id, self.indexer.project_id, symbol_id, budget.max_nodes),
            )
            for row in cur.fetchall():
                other = row["other"]
                if not other or other in symbols:
                    continue
                symbol = self.indexer.conn.execute(
                    "SELECT id, file_path, symbol_name, symbol_type, signature, docstring, "
                    "start_line, end_line FROM code_symbols WHERE id = ? AND project_id = ?",
                    (other, self.indexer.project_id),
                ).fetchone()
                if symbol:
                    symbols[other] = dict(symbol)
                    queue.append((other, distance + 1))
        return symbols

    def _artifact(self, query: str, depth: int, budget: Budget) -> dict:
        started = time.monotonic()
        lexical = self._lexical_hits(query, budget.max_nodes)
        symbols = self._neighbors(lexical, depth, budget, started)
        components: dict[str, list[dict]] = defaultdict(list)
        for symbol in symbols.values():
            components[self._component(symbol["file_path"])].append(symbol)
        for values in components.values():
            values.sort(key=lambda item: (item["file_path"], item["start_line"]))
        memory = []
        if self.memory_search:
            try:
                # Search with raw query, plus extracted tokens, plus component names
                search_terms = [query] + self._tokens(query) + list(components.keys())
                unique_terms = list(dict.fromkeys(search_terms))  # dedupe while preserving order

                # Try up to 3 variations to maximize recall without blowing the budget
                for term in unique_terms[:3]:
                    mem_results = self.memory_search(term, min(4, budget.max_nodes // 8))
                    if mem_results:
                        memory.extend(mem_results)
                        if len(memory) >= 8:
                            break

                # Deduplicate memory by note ID
                seen_ids = set()
                deduped_memory = []
                for item in memory:
                    if item.get("id") not in seen_ids:
                        seen_ids.add(item.get("id"))
                        deduped_memory.append(item)
                memory = deduped_memory[:8]
            except Exception:
                memory = []
        ranked = sorted(symbols.values(), key=lambda item: (item["file_path"], item["start_line"]))
        entry_point_keywords = {"route", "handler", "controller", "api", "main", "endpoint", "view"}
        evidence = [
            {
                "id": item["id"],
                "symbol": item["symbol_name"],
                "file": item["file_path"],
                "line": item["start_line"],
                "type": item["symbol_type"],
                "is_likely_entry_point": any(
                    keyword in item["file_path"].lower() or keyword in item["symbol_name"].lower()
                    for keyword in entry_point_keywords
                ),
            }
            for item in ranked[: budget.max_nodes]
        ]
        flows = self._flows(evidence)
        return {
            "kind": "code_understanding",
            "version": 1,
            "query": query,
            "repository": self.indexer.project_root,
            "subsystems": [
                {
                    "name": name,
                    "symbols": values,
                    "tests": [item for item in values if "test" in item["file_path"].lower()],
                }
                for name, values in sorted(components.items())
            ],
            "flows": flows,
            "memory": memory,
            "evidence": evidence,
            "confidence": min(1.0, 0.35 + min(0.65, len(symbols) / max(1, len(evidence) * 3))),
            "budget": {"max_nodes": budget.max_nodes, "max_chars": budget.max_chars, "max_ms": budget.max_ms},
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }

    def _flows(self, evidence: list[dict]) -> list[dict]:
        ids = {item["id"] for item in evidence}
        if not ids:
            return []

        placeholders = ",".join("?" for _ in ids)

        # Get both inbound (who calls us) and outbound (who we call)
        cur = self.indexer.conn.execute(
            f"""
            SELECT 'inbound' as direction, from_name as source, to_name as target
            FROM code_edges WHERE project_id = ? AND to_symbol_id IN ({placeholders}) AND edge_type IN ('calls', 'references')
            UNION ALL
            SELECT 'outbound' as direction, from_name as source, to_name as target
            FROM code_edges WHERE project_id = ? AND from_symbol_id IN ({placeholders}) AND edge_type IN ('calls', 'imports', 'references')
            LIMIT 300
            """,
            (self.indexer.project_id, *ids, self.indexer.project_id, *ids),
        )

        flows: defaultdict[str, dict[str, list[str]]] = defaultdict(
            lambda: {"inbound": [], "outbound": []}
        )
        for row in cur.fetchall():
            direction = row["direction"]
            source = row["source"] or "unknown"
            target = row["target"] or "unknown"
            if direction == "inbound":
                flows[target]["inbound"].append(source)
            else:
                flows[source]["outbound"].append(target)

        return [
            {
                "symbol": symbol,
                "inbound_callers": list(set(callers))[:8],
                "outbound_callees": list(set(callees))[:8],
                "confidence": "derived from code_edges",
            }
            for symbol, edges in flows.items()
            for callers in [edges["inbound"]]
            for callees in [edges["outbound"]]
            if callers or callees
        ]

    def understand(
        self,
        query: str,
        depth: int = 2,
        budget: Budget | None = None,
        use_cache: bool = True,
    ) -> dict:
        budget = budget or Budget.bounded()
        query = (query or "").strip()[:2000]
        if not query:
            return {"kind": "code_understanding", "version": 1, "evidence": [], "confidence": 0.0}
        stamp = self.indexer.conn.execute(
            "SELECT COALESCE(MAX(updated_at), ''), COUNT(*) FROM code_symbols WHERE project_id = ?",
            (self.indexer.project_id,),
        ).fetchone()
        content_hash = f"{stamp[0]}:{stamp[1]}"
        key = f"{self.indexer.project_id}:{depth}:{budget.max_nodes}:{query}"
        if use_cache:
            row = self.indexer.conn.execute(
                "SELECT artifact_json, content_hash FROM code_understanding_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
            if row and row[1] == content_hash:
                return json.loads(row[0])
        artifact = self._artifact(query, max(0, min(int(depth), 3)), budget)
        rendered = json.dumps(artifact, separators=(",", ":"))
        if len(rendered) > budget.max_chars:
            artifact["evidence"] = artifact["evidence"][: max(1, budget.max_nodes // 3)]
            artifact["subsystems"] = [item for item in artifact["subsystems"] if item["symbols"]][:8]
            rendered = json.dumps(artifact, separators=(",", ":"))
        if use_cache:
            self.indexer.conn.execute(
                "INSERT OR REPLACE INTO code_understanding_cache "
                "(cache_key, project_id, query, depth, content_hash, artifact_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (key, self.indexer.project_id, query, depth, content_hash, rendered),
            )
            self.indexer.conn.commit()
        return artifact

"""Query-quality benchmark: does each tool answer real questions correctly?

Indexing speed and symbol counts are already measured. This asks the question
that matters instead: given a real repo and a real question, does the tool return
the right evidence?

Grading is evidence-based, not string-exact. A tool passes a question when its
answer names the files or symbols we know must appear, and the check is tolerant
of format because the two tools report very differently (BaseMem returns symbol
ids and paths, cbm returns qualified names and BM25 ranks).

Usage:
    venv/bin/python3 benchmarks/query_quality.py --repo <path> [--only basemem,cbm]

Writes benchmarks/query_quality.md and exits non-zero if either tool scores 0.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@dataclass
class Question:
    """A question with the evidence a correct answer must contain."""

    qid: str
    ask: str
    why: str
    must_include: list[str] = field(default_factory=list)
    # Some questions need more than a name: the answer has to locate the symbol.
    must_match_any: list[str] = field(default_factory=list)
    forbid: list[str] = field(default_factory=list)


QUESTIONS: list[Question] = [
    Question(
        qid="find-by-name",
        ask="Find the symbol trimRightSpace",
        why="Baseline lookup. Both tools should nail this.",
        must_include=["cobra.go"],
    ),
    Question(
        qid="who-calls",
        ask="Which functions call Execute",
        why="Callers is the single most-used navigation query.",
        must_match_any=["command.go", "cobra_test.go", "completions_test.go"],
    ),
    Question(
        qid="what-calls",
        ask="What does the Execute function call",
        why="Callees, same traversal in the other direction.",
        must_match_any=["command.go"],
    ),
    Question(
        qid="types-of-symbol",
        ask="List the methods defined on the Command type",
        why="Needs the class->method relation, not just name matching.",
        must_match_any=["command.go"],
    ),
    Question(
        qid="locate-definition",
        ask="Where is the OutOrStdout function defined",
        why="Precision matters more than recall here.",
        must_include=["command.go"],
    ),
    Question(
        qid="unused-or-orphan",
        ask="Find a function defined in this repo but never called from within it",
        why="Negative query. Needs NOT, which neither tool expressed before this.",
        must_match_any=[".go"],
        forbid=[],
    ),
    Question(
        qid="file-inventory",
        ask="List the Go source files in this repository",
        why="Cheap sanity check that the repo was ingested at all.",
        must_include=["cobra.go"],
    ),
    Question(
        qid="most-connected",
        ask="Which symbols have the most callers in this repository",
        why="Aggregation over the graph. The clearest divide between the tools.",
        must_match_any=["command.go", "cobra.go", "args.go", "flag.go"],
    ),
    # ── harder questions, added once the easy eight were saturated ──────
    Question(
        qid="two-hop-reach",
        ask="Which functions does Execute reach within two hops",
        why="Multi-hop traversal. Needs a path pattern, not a single relation.",
        must_match_any=[".go"],
    ),
    Question(
        qid="either-or",
        ask="Functions defined in command.go or in args.go",
        why="Disjunction in WHERE. Currently only conjunctions are expressible.",
        must_match_any=["command.go", "args.go"],
    ),
    Question(
        qid="named-set",
        ask="Definition of Execute, ExecuteC or ExecuteContext",
        why="Membership test over a list of names.",
        must_match_any=["command.go"],
    ),
    Question(
        qid="cross-file-calls",
        ask="Which functions does command.go call in cobra.go",
        why="Cross-file reachability, which is how a refactor blast radius is judged.",
        must_match_any=["cobra.go"],
    ),
    Question(
        qid="most-called-files",
        ask="Which symbols have the most callers",
        why="Fan-in across the repo; needs aggregation over an inbound relation.",
        must_match_any=[".go"],
    ),
    Question(
        qid="multi-file-filter",
        ask="Functions defined in command.go",
        why="Import fan-out, an ordering signal.",
        must_match_any=[".go"],
    ),
]


# ── runners ─────────────────────────────────────────────────────────────


def run_basemem(repo: Path, question: Question, timeout: int = 120) -> dict:
    """Ask BaseMem through its own CLI, not through MCP."""
    cmd = [_py(), "-W", "ignore::RuntimeWarning", "-m", "cli.main", "code"]
    script = {
        "find-by-name": ["search", question.ask.split()[-1], "--root", str(repo), "--limit", "10"],
        "who-calls": ["callers", "Execute", "--root", str(repo)],
        "what-calls": ["callees", "Execute", "--root", str(repo)],
        "types-of-symbol": ["node", "Command", "--root", str(repo)],
        "locate-definition": ["search", "OutOrStdout", "--root", str(repo), "--limit", "10"],
        "unused-or-orphan": [
            "gquery",
            "MATCH (a:Function) WHERE NOT (a)<-[:calls]-() RETURN a.name, a.file LIMIT 40",
            "--root", str(repo),
        ],
        "file-inventory": ["files", "--root", str(repo), "--tree"],
        "most-connected": [
            "gquery",
            "MATCH (a)-[:calls]->(b) RETURN b.name, b.file, count(a) AS callers "
            "ORDER BY callers DESC LIMIT 10",
            "--root", str(repo),
        ],
        "two-hop-reach": [
            "gquery",
            "MATCH (a)-[:calls]->()-[:calls]->() RETURN a.name, a.file LIMIT 40",
            "--root", str(repo),
        ],
        "either-or": [
            "gquery",
            "MATCH (a:Function) WHERE a.file = 'command.go' OR a.file = 'args.go' "
            "RETURN a.name, a.file LIMIT 40",
            "--root", str(repo),
        ],
        "named-set": [
            "gquery",
            "MATCH (a) WHERE a.name IN ['Execute', 'ExecuteC', 'ExecuteContext'] "
            "RETURN a.name, a.file LIMIT 10",
            "--root", str(repo),
        ],
        "cross-file-calls": [
            "gquery",
            "MATCH (a)-[:calls]->(b) WHERE a.file = 'command.go' "
            "AND b.file = 'cobra.go' RETURN a.name, b.name LIMIT 40",
            "--root", str(repo),
        ],
        "most-called-files": [
            "gquery",
            "MATCH (a)-[:calls]->(b) RETURN b.name, b.file, count(a) AS callers "
            "ORDER BY callers DESC LIMIT 10",
            "--root", str(repo),
        ],
        "multi-file-filter": [
            "gquery",
            "MATCH (a) WHERE a.file = 'command.go' RETURN a.name, a.file LIMIT 20",
            "--root", str(repo),
        ],
    }[question.qid]
    return _run(cmd + script, cwd=REPO_ROOT, timeout=timeout)


def run_cbm(repo: Path, question: Question, timeout: int = 180) -> dict:
    project = _cbm_project(repo)
    cmd = ["codebase-memory-mcp", "cli", "--json"]
    script = {
        "find-by-name": ["search_graph", json.dumps(
            {"project": project, "name_pattern": "trimRightSpace", "limit": 10})],
        "who-calls": ["search_graph", json.dumps(
            {"project": project, "name_pattern": "Execute", "include_connected": True, "limit": 30})],
        "what-calls": ["search_graph", json.dumps(
            {"project": project, "name_pattern": "Execute", "include_connected": True, "limit": 30})],
        "types-of-symbol": ["query_graph", json.dumps({
            "project": project, "format": "json", "max_rows": 40,
            "query": "MATCH (c:Class)-[:DEFINES]->(m) RETURN c.name, m.name, m.file"})],
        "locate-definition": ["search_graph", json.dumps(
            {"project": project, "name_pattern": "OutOrStdout", "limit": 10})],
        "unused-or-orphan": ["query_graph", json.dumps({
            "project": project, "format": "json", "max_rows": 40,
            "query": ("MATCH (a:Function) WHERE NOT (a)<-[:CALLS]-() "
                      "RETURN a.name, a.file")})],
        "file-inventory": ["query_graph", json.dumps({
            "project": project, "format": "json", "max_rows": 60,
            "query": "MATCH (f:File) RETURN f.path"})],
        "most-connected": ["query_graph", json.dumps({
            "project": project, "format": "json", "max_rows": 30,
            "query": ("MATCH (a)<-[:CALLS]-(b) RETURN a.name, a.file, count(b) AS callers "
                      "ORDER BY callers DESC")})],
        "two-hop-reach": ["query_graph", json.dumps({
            "project": project, "format": "json", "max_rows": 40,
            "query": ("MATCH (a)-[:CALLS*1..2]->(b) RETURN a.name, a.file, b.name")})],
        "either-or": ["query_graph", json.dumps({
            "project": project, "format": "json", "max_rows": 40,
            "query": ("MATCH (a:Function) WHERE a.file = 'command.go' OR a.file = 'args.go' "
                      "RETURN a.name, a.file")})],
        "named-set": ["query_graph", json.dumps({
            "project": project, "format": "json", "max_rows": 10,
            "query": ("MATCH (a:Function) WHERE a.name IN ['Execute','ExecuteC',"
                      "'ExecuteContext'] RETURN a.name, a.file")})],
        "cross-file-calls": ["query_graph", json.dumps({
            "project": project, "format": "json", "max_rows": 40,
            "query": ("MATCH (a)-[:IMPLEMENTS|EXTENDS]->(b) RETURN a.name, b.name, b.file")})],
        "most-called-files": ["query_graph", json.dumps({
            "project": project, "format": "json", "max_rows": 20,
            "query": ("MATCH (a:Function) WHERE a.file = 'site.go' RETURN a.name, a.file")})],
        "multi-file-filter": ["query_graph", json.dumps({
            "project": project, "format": "json", "max_rows": 10,
            "query": ("MATCH (a)-[:IMPORTS]->(b) RETURN a.file, count(b) AS deps "
                      "ORDER BY deps DESC")})],
    }[question.qid]
    return _run(cmd + script, timeout=timeout)


def _py() -> str:
    return sys.executable


def _cbm_project(repo: Path) -> str:
    # cbm names a project by its path with separators collapsed to dashes:
    # /mnt/Storage/cbm-bench/go -> mnt-Storage-cbm-bench-go
    return "-".join(repo.resolve().parts[1:])


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> dict:
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        return {"ok": False, "text": "", "ms": (time.time() - t0) * 1000, "error": "timeout"}
    text = (p.stdout or "") + (p.stderr or "")
    return {
        "ok": p.returncode == 0,
        "text": text,
        "ms": (time.time() - t0) * 1000,
        "error": "" if p.returncode == 0 else f"exit {p.returncode}",
    }


# ── grading ─────────────────────────────────────────────────────────────


def grade(question: Question, result: dict) -> dict:
    text = (result.get("text") or "").lower()
    if not result.get("ok"):
        return {"pass": False, "why": result.get("error") or "failed", "hits": []}
    hits = []
    for needle in question.must_include:
        if needle.lower() in text:
            hits.append(needle)
    if question.must_match_any:
        any_hit = [n for n in question.must_match_any if n.lower() in text]
        hits.extend(any_hit)
    leaked = [n for n in question.forbid if n.lower() in text]
    # An empty answer that contains no evidence must not pass.
    if not hits:
        return {"pass": False, "why": "no expected evidence in answer", "hits": []}
    if leaked:
        return {"pass": False, "why": f"forbidden token present: {leaked}", "hits": hits}
    return {"pass": True, "why": f"evidence: {', '.join(hits[:3])}", "hits": hits}


# ── driver ──────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="repo both tools have indexed")
    ap.add_argument("--only", default="basemem,cbm")
    ap.add_argument("--out", default=str(Path(__file__).parent / "query_quality.md"))
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"no such repo: {repo}")
        return 2
    tools = [t for t in args.only.split(",") if t]
    runners = {"basemem": run_basemem, "cbm": run_cbm}

    rows = []
    for q in QUESTIONS:
        row = {"qid": q.qid, "ask": q.ask, "why": q.why, "scores": {}}
        for name in tools:
            res = runners[name](repo, q)
            g = grade(q, res)
            g["ms"] = res["ms"]
            g["snippet"] = _snippet(res.get("text") or "")
            row["scores"][name] = g
        rows.append(row)
        marks = "  ".join(
            f"{n}={'PASS' if row['scores'][n]['pass'] else 'fail'}" for n in tools
        )
        print(f"  {q.qid:<20} {marks}")

    totals = {
        n: sum(1 for r in rows if r["scores"][n]["pass"]) for n in tools
    }
    lat = {
        n: sum(r["scores"][n]["ms"] for r in rows) / max(len(rows), 1) for n in tools
    }
    _write_report(Path(args.out), repo, rows, totals, lat, tools)
    print()
    for n in tools:
        print(f"  {n}: {totals[n]}/{len(QUESTIONS)}   avg {lat[n]:.0f} ms")
    print(f"  report: {args.out}")
    return 0 if all(t == len(QUESTIONS) for t in totals.values()) else 1


def _snippet(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return t[:160] + ("..." if len(t) > 160 else "")


def _write_report(path: Path, repo: Path, rows, totals, lat, tools) -> None:
    out = ["# Query quality benchmark", ""]
    out.append(f"Repo: `{repo}`  ")
    out.append(f"Questions: {len(QUESTIONS)}  ")
    out.append("Graded on evidence: the answer must name a file or symbol that a correct")
    out.append("answer must contain. Format is not compared, because the two tools report")
    out.append("very differently.")
    out.append("")
    out.append("## Scores")
    out.append("")
    out.append("| tool | passed | avg latency |")
    out.append("|---|---|---|")
    for n in tools:
        out.append(f"| {n} | {totals[n]}/{len(QUESTIONS)} | {lat[n]:.0f} ms |")
    out.append("")
    out.append("## Per question")
    out.append("")
    out.append("| question | " + " | ".join(tools) + " |")
    out.append("|---|" + "---|" * len(tools))
    for r in rows:
        cells = []
        for n in tools:
            s = r["scores"][n]
            cells.append("PASS" if s["pass"] else f"fail ({s['why']})")
        out.append(f"| `{r['qid']}` {r['ask']} | " + " | ".join(cells) + " |")
    out.append("")
    out.append("## Detail")
    out.append("")
    for r in rows:
        out.append(f"### `{r['qid']}` — {r['ask']}")
        out.append("")
        out.append(f"*{r['why']}*")
        out.append("")
        for n in tools:
            s = r["scores"][n]
            verdict = "PASS" if s["pass"] else "FAIL"
            out.append(f"- **{n}** {verdict} in {s['ms']:.0f} ms — {s['why']}")
            out.append(f"  - `{s['snippet']}`")
        out.append("")
    path.write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
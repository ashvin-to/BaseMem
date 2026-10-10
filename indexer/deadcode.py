"""Unreferenced symbols: no caller anywhere in this repository.

What this can honestly claim is "nothing here calls this by name". It cannot
claim "dead": entry points are invoked by a runtime or a framework, exported
library API is called by consumers outside the repo, and reflection defeats
static analysis entirely. The output says so rather than implying otherwise.

The first corpus run made the need concrete - 17 of 35 repos hit the query's
limit, and go reported 307 "orphans" of which 292 were test functions called by
a reflection-based runner.
"""

from __future__ import annotations

from .entrypoints import is_entry_point, is_standalone_path, is_test_path


def unreferenced(indexer, limit: int = 200, include_tests: bool = False,
                include_entry_points: bool = False,
                include_standalone: bool = False) -> dict:
    """Symbols with no inbound call edge, with the known false positives removed.

    Returns counts, a sample, and a `confidence` note, because a static answer
    here is a lead rather than a verdict.
    """
    from .query_execute import run

    rows = run(indexer,
               "MATCH (a:Function) WHERE NOT (a)<-[:calls]-() "
               f"RETURN a.name, a.file, a.type LIMIT {limit}")

    name_key = file_key = type_key = None
    if rows:
        name_key = next((k for k in rows[0] if k.endswith("symbol_name")), None)
        file_key = next((k for k in rows[0] if k.endswith("file_path")), None)
        type_key = next((k for k in rows[0] if k.endswith("symbol_type")), None)

    skipped_test = skipped_entry = skipped_standalone = 0
    kept = []
    for r in rows:
        path, name = r.get(file_key) or "", r.get(name_key) or ""
        if not include_tests and is_test_path(path):
            skipped_test += 1
            continue
        if not include_standalone and is_standalone_path(path):
            skipped_standalone += 1
            continue
        if not include_entry_points and is_entry_point(name, r.get(type_key) or ""):
            skipped_entry += 1
            continue
        kept.append(r)

    capped = len(rows) >= limit
    return {
        "candidates_scanned": len(rows),
        "kept": len(kept),
        "skipped_test_paths": skipped_test,
        "skipped_standalone_paths": skipped_standalone,
        "skipped_entry_points": skipped_entry,
        "capped": capped,
        "sample": [f"{r[name_key]} ({r[file_key]})" for r in kept[:10]],
        "confidence": (
            "LOW — the query hit its limit, so more exist than are shown"
            if capped else
            "MEDIUM — no static caller found. Exported API and reflection are "
            "invisible to this check; confirm before deleting anything."
        ),
    }
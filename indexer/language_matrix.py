"""Per-language coverage matrix for the code index.

The indexer resolves a file's language from its extension using
``tree_sitter_language_pack``, which ships a few hundred grammars, but only a
handful have a hand-written extraction query in ``LANGUAGE_QUERIES``. Everything
else falls back to the generic extractor, which finds declarations for some
languages and nothing for others.

This module is the fixture that makes that measurable. Each entry is a real
filename plus a minimal, valid program that declares a function or class, so
coverage can be measured by *running the indexer* rather than by guessing from
grammar metadata. It backs ``code_status`` and the coverage test.
"""

from __future__ import annotations

# (language, filename, source) — source must be valid for that language and must
# declare at least one function or class, otherwise the check is meaningless.
FIXTURES: list[tuple[str, str, str]] = [
    ("python", "m.py", "def alpha():\n    return 1\n\n\nclass Beta:\n    def gamma(self):\n        return 2\n"),
    ("javascript", "m.js", "export function alpha() { return 1 }\nexport class Beta { gamma() { return 2 } }\n"),
    ("typescript", "m.ts", "export function alpha(): number { return 1 }\nexport class Beta { gamma(): number { return 2 } }\n"),
    ("tsx", "m.tsx", "export function Alpha(): number { return 1 }\nexport class Beta { gamma(): number { return 2 } }\n"),
    ("go", "m.go", "package m\n\nfunc Alpha() int { return 1 }\n\ntype Beta struct{}\n\nfunc (b Beta) Gamma() int { return 2 }\n"),
    ("go_call", "m2.go", "package m\n\ntype Beta struct{}\n\nfunc (b Beta) Gamma() int { return 2 }\n\nfunc Delta(b Beta) int { return b.Gamma() }\n"),
    ("rust", "m.rs", "pub fn alpha() -> i32 { 1 }\n\npub struct Beta;\n\nimpl Beta { pub fn gamma(&self) -> i32 { 2 } }\n"),
    ("java", "M.java", "public class M {\n  public int alpha() { return 1; }\n  static class Beta { int gamma() { return 2; } }\n}\n"),
    ("c", "m.c", "int alpha(void) { return 1; }\n"),
    ("cpp", "m.cpp", "int alpha() { return 1; }\nclass Beta { public: int gamma() { return 2; } };\n"),
    ("ruby", "m.rb", "def alpha\n  1\nend\n\nclass Beta\n  def gamma\n    2\n  end\nend\n"),
    ("php", "m.php", "<?php\nfunction alpha() { return 1; }\nclass Beta { function gamma() { return 2; } }\n"),
    ("swift", "m.swift", "func alpha() -> Int { return 1 }\nclass Beta { func gamma() -> Int { return 2 } }\n"),
    # NOTE: this kotlin grammar rejects block bodies, so expression bodies only.
    ("kotlin", "m.kt", "fun beta(): Int = 1\nfun alpha(): Int = beta()\n\nclass Beta {\n    fun gamma(): Int = beta()\n}\n"),
    ("scala", "m.scala", "object Alpha { def a: Int = 1 }\nclass Beta { def gamma: Int = 2 }\n"),
    ("csharp", "m.cs", "class M { int Alpha() { return 1; } class Beta { int Gamma() { return 2; } } }\n"),
    ("dart", "m.dart", "int alpha() { return 1; }\nclass Beta { int gamma() { return 2; } }\n"),
    ("lua", "m.lua", "function alpha() return 1 end\nfunction Beta.gamma() return 2 end\n"),
    ("shell", "m.sh", "alpha() { echo 1; }\ngamma() { echo 2; }\n"),
    ("elixir", "m.ex", "defmodule M do\n  def alpha, do: 1\n  defmodule Beta do\n    def gamma, do: 2\n  end\nend\n"),
    ("solidity", "m.sol", "pragma solidity ^0.8.0;\ncontract M { function alpha() public pure returns (uint) { return 1; } }\n"),
    ("haskell", "Hs.hs", "module M where\nalpha :: Int\nalpha = 1\ndata Beta = Beta\n"),
    ("clojure", "m.clj", "(ns m)\n(defn alpha [] 1)\n(defrecord Beta [x])\n"),
    ("julia", "m.jl", "alpha() = 1\nstruct Beta end\n"),
    ("perl", "m.pl", "sub alpha { return 1; }\nsub Beta::gamma { return 2; }\n"),
    ("r", "m.r", "alpha <- function() 1\n"),
    # this zig grammar only accepts void fns and decls at the top level
    ("zig", "m.zig", "fn alpha() void {}\nfn beta() void {}\nconst S = struct {\n    fn gamma(self: *S) void {}\n};\n"),
    ("ocaml", "m.ml", "let alpha = 1\nlet beta_gamma = 2\n"),
    ("nim", "m.nim", "proc alpha(): int = 1\ntype Beta = object\n"),
    ("erlang", "m.erl", "-module(m).\n-export([alpha/0]).\nalpha() -> 1.\n"),

    ("fsharp", "m.fs", "module M\nlet alpha = 1\ntype Beta = { x: int }\n"),
    ("sql", "m.sql", "CREATE TABLE alpha (id INT);\n"),
    ("graphql", "m.graphql", "type Beta { gamma: Int }\n"),
    ("terraform", "m.tf", "resource \"null_resource\" \"alpha\" {}\n"),
    ("dockerfile", "Dockerfile", "FROM alpine\nRUN echo 1\n"),
    ("yaml", "m.yaml", "alpha: 1\n"),
    ("toml", "m.toml", "alpha = 1\n"),
    ("vue", "m.vue", "<template><div/></template>\n<script>\nexport default { name: 'Alpha' }\n</script>\n"),
    ("svelte", "m.svelte", "<script>\n  function alpha() { return 1; }\n</script>\n<h1>hi</h1>\n"),
]

# Blocked, and why. Both are grammar/query-contract limits, not missing effort.
#   clojure — a defn is a list_lit whose head symbol must literally be `defn`.
#              tree-sitter queries cannot compare a captured string, so this needs
#              a predicate the current query contract does not support.
#   groovy  — the bundled .groovy grammar parses Groovy source as a shell script
#              (command/unit/block/end_command), so nothing about it is trustworthy.
# Languages whose query file yields symbols but no call edges, and why.
#   perl    — the callee is an anonymous `function` token; tree-sitter drops the
#             capture for anonymous nodes, so no callee name is available.
#   haskell — applications are `prefixexp`/`apply` shapes that did not yield a
#             stable callee capture worth shipping as a query.
# Query files added on this branch. Call extraction for these is verified in
# test_language_call_queries.py, because the bare-declaration fixtures in FIXTURES
# contain no calls and cannot measure it.
NEW_QUERY_LANGUAGES = {"kotlin", "julia", "erlang", "ocaml", "nim", "zig", "fsharp", "perl", "go", "go_call"}

# Of NEW_QUERY_LANGUAGES, these yield symbols but no call edges.
NO_CALL_GRAPH = {
    "perl": "callee is an anonymous `function` token; tree-sitter drops its capture",
}
# haskell has a query file too but is not part of the call-graph set.
SYMBOLS_ONLY_LANGUAGES = {**NO_CALL_GRAPH, "haskell": "no stable callee capture for applications"}

BLOCKED = {
    "clojure": "needs a head-symbol predicate; queries cannot compare captured text",
    "groovy": "bundled grammar parses Groovy as shell (command/unit/block)",
}

# Extensions the bundled language pack does not map. These are now covered by
# EXTRA_EXTENSION_LANGUAGES in indexer/parser.py, so the list should stay empty —
# a non-empty set means the pack changed and the matrix needs revisiting.
UNMAPPED_EXTS: set[str] = set()

# Mapped here rather than by the pack, so they are watched explicitly.
LOCAL_MAPPED_EXTS = {".sql", ".graphql", ".gql", ".yaml", ".yml", ".toml",
                     "Dockerfile", ".tf", ".tfvars"}

# Config/infra formats where a "function" is the wrong unit: cbm models these as
# resource nodes with cross-references rather than callables.
RESOURCE_LANGUAGES = {"yaml", "toml", "terraform", "dockerfile", "vue", "svelte", "graphql", "sql"}

# Languages the indexer is expected to handle well: a hand-written query exists.
# Adding a language here without a LANGUAGE_QUERIES entry is a deliberate choice,
# not an accident, so the coverage test can flag drift.
CURATED = {"python", "javascript", "typescript", "tsx", "rust", "java", "c", "cpp"}


def coverage() -> list[dict]:
    """Index each fixture in a scratch project and report what was found.

    Returns one row per language: whether a hand-written query exists, whether the
    generic extractor found anything, and how many symbols landed.
    """
    import shutil
    import tempfile
    from pathlib import Path

    from tree_sitter_language_pack import get_parser

    from indexer.parser import LANGUAGE_QUERIES, CodeParser

    rows: list[dict] = []
    tmp = Path(tempfile.mkdtemp(prefix="bm-langcov-"))
    try:
        for language, filename, source in FIXTURES:
            target = tmp / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
            parser = CodeParser.for_file(str(target))
            ext = Path(filename).suffix or filename
            resolved = parser.language if parser else language
            if parser is None:
                rows.append(
                    {"language": language, "ext": ext, "query": resolved in LANGUAGE_QUERIES,
                     "parsed": False, "parse_error": False, "symbols": 0, "calls": 0}
                )
                continue
            # self.parser only exists on the query path, so go to the pack directly
            # so the parse-error check works for both paths.
            tree = get_parser(parser.language).parse(source.encode("utf-8"))
            # A fixture that does not cleanly parse makes every downstream number
            # meaningless, and looks identical to "the query found nothing".
            parse_error = bool(tree.root_node.has_error)
            try:
                symbols, edge_list = parser.parse(source.encode("utf-8"), filename)
            except Exception:
                symbols, edge_list = [], []
            calls = sum(1 for e in edge_list if "call" in e["edge_type"])
            rows.append(
                {"language": language, "ext": ext, "query": resolved in LANGUAGE_QUERIES,
                 "parsed": True, "parse_error": parse_error, "symbols": len(symbols),
                 "calls": calls}
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return rows


def summary(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["symbols"] > 0]
    generic_ok = [r for r in ok if not r["query"]]
    needs_query = [r for r in rows if r["symbols"] == 0]
    unmapped = [r for r in rows if not r["parsed"]]
    bad_fixture = [r["language"] for r in rows if r.get("parse_error")]
    needs_query = [r for r in needs_query if r["language"] not in RESOURCE_LANGUAGES]
    # NB: no "symbols only" count here. The fixtures are bare declarations with no
    # calls in them, so that number would measure the fixtures, not the code.
    # Call extraction is measured in test_language_call_queries.py.
    return {
        "languages": len(rows),
        "extracting": len(ok),
        "via_generic_fallback": len(generic_ok),
        "needs_query": len(needs_query),
        "needs_query_langs": [r["language"] for r in needs_query],
        "unmapped_ext": [r["language"] for r in unmapped],
        "bad_fixture": bad_fixture,
        "resource_formats": sorted(
            r["language"] for r in rows if r["language"] in RESOURCE_LANGUAGES
        ),
    }

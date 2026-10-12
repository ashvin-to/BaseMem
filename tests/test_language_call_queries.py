"""Call-edge extraction for the query files added on this branch.

The language matrix deliberately uses bare declarations, so it cannot measure
call extraction. These fixtures actually call something, and every one is checked
for a clean parse first — an unparseable fixture would otherwise look like a
missing query.

Languages listed in NO_CALL_GRAPH are expected to produce symbols but no edges,
with a recorded reason.
"""

import pytest

pytest.importorskip("tree_sitter_language_pack")

from indexer.language_matrix import NEW_QUERY_LANGUAGES, NO_CALL_GRAPH  # noqa: E402

# (language, filename, source) — must parse cleanly and contain a call.
CALL_FIXTURES = [
    ("kotlin", "m.kt", "fun beta(): Int = 1\nfun alpha(): Int = beta()\n"),
    ("julia", "m.jl", "beta() = 2\nfunction alpha()\n  beta()\nend\n"),
    ("erlang", "m.erl", "-module(m).\nbeta() -> 1.\nalpha() -> beta().\n"),
    ("ocaml", "m.ml", "let beta = 1\nlet alpha x = f x\n"),
    ("nim", "m.nim", "proc beta(): int = 1\nproc alpha(): int = beta()\n"),
    ("zig", "m.zig", "fn alpha() void { beta(); }\n"),
    ("fsharp", "m.fs", "let beta = 1\nlet alpha x = f x\n"),
    ("perl", "m.pl", "sub alpha { my $x = beta(); }\n"),
]


def _parse(tmp_path, language, filename, source):
    from indexer.parser import CodeParser
    from tree_sitter_language_pack import get_parser

    path = tmp_path / filename
    path.write_bytes(source.encode("utf-8"))
    assert not get_parser(language).parse(source.encode("utf-8")).root_node.has_error, (
        f"{language} fixture does not parse cleanly; fix the fixture, not the query"
    )
    parser = CodeParser.for_file(str(path))
    assert parser is not None, f"no parser for {language}"
    return parser.parse(source.encode("utf-8"), filename)


@pytest.mark.parametrize(
    "language,filename,source", CALL_FIXTURES, ids=[c[0] for c in CALL_FIXTURES]
)
def test_call_edges_are_extracted(tmp_path, language, filename, source):
    assert language in NEW_QUERY_LANGUAGES
    symbols, edges = _parse(tmp_path, language, filename, source)
    assert symbols, f"{language} extracted no symbols"
    calls = [e for e in edges if "call" in e["edge_type"]]
    if language in NO_CALL_GRAPH:
        assert not calls, f"{language} is documented as having no call graph but produced one"
    else:
        assert calls, f"{language} produced no call edges for a fixture that calls a function"
        assert calls[0]["target_name"], f"{language} call edge has no target name"

"""Language coverage: which languages the index can actually extract from.

The pack ships a few hundred grammars but only a handful have hand-written
extraction queries, so the generic fallback carries the rest. This measures what
really works instead of inferring it from grammar metadata, and guards the
curated languages against silent regression.
"""

import pytest

from indexer.language_matrix import (
    BLOCKED,
    CURATED,
    FIXTURES,
    NEW_QUERY_LANGUAGES,
    SYMBOLS_ONLY_LANGUAGES,
    RESOURCE_LANGUAGES,
    UNMAPPED_EXTS,
    coverage,
    summary,
)

@pytest.fixture(scope="module")
def rows():
    return coverage()


def test_unmapped_extensions_are_known(rows):
    """Extensions the pack does not map are a known, tracked set.

    If a new one appears it means the pack changed and the matrix needs updating.
    """
    unparsed = {r["language"] for r in rows if not r["parsed"]}
    assert unparsed == {r["language"] for r in rows if r["ext"] in UNMAPPED_EXTS}


def test_curated_languages_always_extract(rows):
    by_lang = {r["language"]: r for r in rows}
    missing = [lang for lang in CURATED if by_lang[lang]["symbols"] == 0]
    assert not missing, f"curated languages stopped extracting symbols: {missing}"


def test_known_programming_languages_extract(rows):
    """Languages with a published fixture should not silently drop to zero."""
    by_lang = {r["language"]: r for r in rows}
    regressed = [
        lang
        for lang in ("go", "ruby", "php", "swift", "lua", "scala", "elixir", "shell", "solidity", "kotlin", "dart")
        if lang in by_lang and by_lang[lang]["symbols"] == 0
    ]
    assert not regressed, f"generic fallback regressed for: {regressed}"


def test_summary_is_coherent(rows):
    s = summary(rows)
    assert s["languages"] == len(FIXTURES) == len(rows)
    # The zero-symbol languages are partitioned into real gaps, unmapped
    # extensions, and resource formats — nothing may fall through unclassified.
    assert s["extracting"] + len(s["needs_query_langs"]) + len(s["unmapped_ext"]) <= s["languages"]
    # Every zero-symbol language is a real gap, a resource format, or unmapped.
    explained = set(s["needs_query_langs"]) | set(s["unmapped_ext"]) | RESOURCE_LANGUAGES
    unexplained = [r["language"] for r in rows if r["symbols"] == 0 and r["language"] not in explained]
    assert not unexplained, f"unclassified gaps: {unexplained}"


def test_no_fixture_fails_to_parse(rows):
    """A fixture that does not parse makes every other number meaningless."""
    bad = [r["language"] for r in rows if r.get("parse_error")]
    assert not bad, f"fixtures do not parse cleanly: {bad}"


def test_every_new_query_language_extracts_symbols(rows):
    """A language we ship queries for must either yield a call graph or say why not.

    Only meaningful for the query languages this branch added: the fixtures in
    FIXTURES are bare declarations with no calls, so call extraction for the
    curated languages is covered by test_edge_resolution instead.
    """
    by_lang = {r["language"]: r for r in rows}
    for lang in NEW_QUERY_LANGUAGES:
        assert lang in by_lang, f"NEW_QUERY_LANGUAGES names a language with no fixture: {lang}"
        row = by_lang[lang]
        assert row["symbols"], f"{lang} has a query file but extracts no symbols"
    for lang in SYMBOLS_ONLY_LANGUAGES:
        assert lang in by_lang, f"SYMBOLS_ONLY_LANGUAGES names a language with no fixture: {lang}"


def test_blocked_languages_have_reasons():
    for lang, reason in BLOCKED.items():
        assert reason and len(reason) > 20, f"{lang} needs a real explanation"

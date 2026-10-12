"""gitignore semantics: last match wins.

The loader used to split patterns into "ignore" and "negate" lists and test the
negations first. That gets `lib/` + `!bin/lib/` right by accident, but it is not
git's rule, and it silently deletes whole source trees.

nimterop ships:

    *          # ignore all files wo extension
    !/**/      # re-include all directories
    !*.*       # re-include all files with extensions

Tested as "any negation first", `!/**/` could not match the dotless directory
`nimterop`, so the bare `*` won, the directory was pruned during os.walk, and
all 40 of its .nim files were dropped -- 95.5% of the repository, leaving only
two YAML files indexed.
"""

import pytest


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "Proj"
    p.mkdir()
    return p


def _idx(project):
    from indexer.indexer import CodeIndexer

    return CodeIndexer(str(project))


def test_nimterop_style_ignore_keeps_source(tmp_path):
    """The regression: `*` then `!/**/` then `!*.*` must not prune the tree."""
    root = tmp_path / "nimterop"
    (root / "nimterop").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / ".gitignore").write_text(
        "## ignore all files wo extension\n"
        "*\n"
        "!/**/\n"
        "!*.*\n"
        "\n"
        "/build\n"
        "nimcache\n"
        "*.exe\n"
    )
    (root / "nimterop" / "private.nim").write_text("proc a() = 1\n")
    (root / "tests" / "tmath.nim").write_text("proc b() = 2\n")
    (root / "tests" / "prog.exe").write_text("binary\n")
    (root / "build" ).mkdir()
    (root / "build" / "out.nim").write_text("proc c() = 3\n")

    ix = _idx(root)
    try:
        assert ix._is_skipped(str(root / "nimterop")) is False, "source dir was pruned"
        assert ix._is_skipped(str(root / "nimterop" / "private.nim")) is False
        assert ix._is_skipped(str(root / "tests" / "tmath.nim")) is False
        # the specific ignores must still apply
        assert ix._is_skipped(str(root / "tests" / "prog.exe")) is True
        assert ix._is_skipped(str(root / "build")) is True

        found = {p.name for p in ix._discover_files(root)}
        assert {"private.nim", "tmath.nim"} <= found, f"discovered {sorted(found)}"
    finally:
        ix.close()


def test_negation_reinstates_after_a_broader_ignore(project):
    (project / ".gitignore").write_text("*\n!src/\n!src/**\n")
    (project / "src").mkdir()
    (project / "src" / "a.py").write_text("x = 1\n")
    (project / "other").mkdir()
    (project / "other" / "b.py").write_text("y = 2\n")

    ix = _idx(project)
    try:
        assert ix._is_skipped(str(project / "src" / "a.py")) is False
        assert ix._is_skipped(str(project / "other" / "b.py")) is True
    finally:
        ix.close()


def test_order_matters_not_just_negation_presence(project):
    """`!a` then `b` ignores b; the reverse order keeps it."""
    (project / ".gitignore").write_text("!keep.py\n*.tmp\n")
    (project / "keep.py").write_text("x = 1\n")
    (project / "drop.tmp").write_text("y = 2\n")

    ix = _idx(project)
    try:
        assert ix._is_skipped(str(project / "keep.py")) is False
        assert ix._is_skipped(str(project / "drop.tmp")) is True
    finally:
        ix.close()


def test_rules_keep_source_order(project):
    (project / ".gitignore").write_text("lib\n!bin/lib\n/build\n")
    ix = _idx(project)
    try:
        # A trailing slash is stripped (it only means "directory"), but a leading
        # one is kept, because the matcher uses it to anchor to the root.
        assert ix._ignore_rules == [
            (False, "lib"), (True, "bin/lib"), (False, "/build")
        ], "rules must retain file order for last-match-wins"
    finally:
        ix.close()


@pytest.mark.parametrize(
    "pattern,path,expected",
    [
        ("*", "nimterop", True),
        ("**", "nimterop", True),
        ("*.*", "nimterop", False),
        ("*.*", "nimterop/foo.nim", True),
        ("/build", "build", True),
        ("/build", "sub/build", False),
        ("*.exe", "x/y/prog.exe", True),
        ("*.exe", "x/y/prog.c", False),
        ("lib", "bin/lib/thing.js", True),
        ("bin/lib", "bin/lib/thing.js", True),
        ("bin/lib", "lib/vendor.js", False),
        ("a/**/b", "a/x/y/b", True),
        ("a/**/b", "a/b", True),
        ("**/logs", "x/y/logs", True),
    ],
)
def test_pattern_matching(pattern, path, expected):
    from indexer.indexer import _match_gitignore_pattern

    assert _match_gitignore_pattern(pattern, path) is expected

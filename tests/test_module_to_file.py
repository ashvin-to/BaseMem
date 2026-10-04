"""_module_to_file must not rescan every known file per lookup."""

from indexer.indexer import CodeIndexer


def _ix(tmp_path):
    return CodeIndexer(str(tmp_path))


def _reference(module, known):
    """The original implementation, kept here to prove the fast path matches it."""
    from pathlib import Path

    if not module:
        return ""
    rel = module.replace(".", "/")
    for candidate in (
        f"{rel}.py", f"{rel}.js", f"{rel}.ts", f"{rel}.tsx", f"{rel}.rs",
        f"{rel}.go", f"{rel}.java", f"{rel}.rb", f"{rel}.php", f"{rel}.c", f"{rel}.cpp",
        f"{rel}/index.js", f"{rel}/index.ts", f"{rel}/mod.rs", f"{rel}/__init__.py",
    ):
        if candidate in known:
            return candidate
    stem = rel.rsplit("/", 1)[-1]
    for f in known:
        if Path(f).stem == stem and "/" + stem in ("/" + f, f):
            return f
        if Path(f).stem == stem:
            return f
    return ""


def test_matches_the_original_implementation(tmp_path):
    ix = _ix(tmp_path)
    known = {
        "a/b.py", "a/b/mod.rs", "other/b.ts", "deep/nested/thing.rs", "unrelated.py",
        "pkg/index.js", "pkg/__init__.py", "top.rs", "x/y/z/deep.rs",
    }
    modules = [
        "a.b", "a.b.c", "nothing.here", "deep.thing", "pkg", "top", "x.y.z.deep",
        "unrelated", "", "a.b.mod.rust", "pkg.index",
    ]
    for m in modules:
        assert ix._module_to_file(m, known) == _reference(m, known), m
    ix.close()


def test_direct_candidates_win_over_stem_fallback(tmp_path):
    ix = _ix(tmp_path)
    known = {"a/b.py", "a/b/mod.rs", "other/b.ts"}
    assert ix._module_to_file("a.b", known) == "a/b.py"
    assert ix._module_to_file("a.b.mod", known) == "a/b/mod.rs"
    ix.close()


def test_stem_fallback_finds_an_unconventional_layout(tmp_path):
    """a module path with no matching candidate still resolves by basename."""
    ix = _ix(tmp_path)
    known = {"deep/nested/thing.rs", "unrelated.py"}
    assert ix._module_to_file("nowhere.thing", known) == "deep/nested/thing.rs"
    ix.close()


def test_unknown_module_returns_empty(tmp_path):
    ix = _ix(tmp_path)
    assert ix._module_to_file("nothing.here", {"a.py", "b.go"}) == ""
    assert ix._module_to_file("", {"a.py"}) == ""
    ix.close()


def test_stem_index_is_reused_across_lookups(tmp_path):
    """The cache is keyed on the known_files set, so a new set rebuilds it."""
    ix = _ix(tmp_path)
    first = {"pkg/mod.py"}
    assert ix._module_to_file("pkg.mod", first) == "pkg/mod.py"
    # a stale cache would still answer from `first`
    second = {"other/mod.py"}
    assert ix._module_to_file("other.mod", second) == "other/mod.py"
    assert ix._module_to_file("pkg.mod", first) == "pkg/mod.py"
    ix.close()


def test_repeated_lookups_do_not_rebuild_the_index(tmp_path):
    ix = _ix(tmp_path)
    known = {f"pkg{i}/file{i}.py" for i in range(200)}
    assert ix._files_by_stem(known) is ix._files_by_stem(known)
    ix.close()

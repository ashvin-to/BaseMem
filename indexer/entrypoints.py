"""Conventional entry points, which have no static caller by design.

A symbol like `main` or `init` is called by the runtime or the framework, not by
anything in the repo, so a static "has no callers" query flags every one of them.
These are the names to exclude, per language.

This is a heuristic and the output says so. The honest claim a static query can
make is "nothing in this repository calls this by name", not "this is dead".
"""

from __future__ import annotations

# Names that are entry points in essentially any language.
UNIVERSAL = {
    "main", "__main__", "init", "__init__", "setup", "teardown", "cleanup",
    "new", "build", "run", "start", "stop", "close", "open",
}

PER_LANGUAGE: dict[str, set[str]] = {
    "go": {"init", "TestMain", "BenchmarkMain", "FuzzMain", "ExampleMain"},
    "python": {
        "setUp", "tearDown", "setUpClass", "tearDownClass", "setUpModule",
        "tearDownModule", "__repr__", "__str__", "__eq__", "__hash__",
        "__lt__", "__le__", "__gt__", "__ge__", "__len__", "__getitem__",
        "__setitem__", "__delitem__", "__iter__", "__next__", "__call__",
        "__enter__", "__exit__", "__aenter__", "__aexit__", "__bool__",
        "__contains__", "__getattr__", "__setattr__", "delattr",
        "pytest_configure", "pytest_addoption", "pytest_collection_modifyitems",
    },
    "java": {"main", "toString", "equals", "hashCode", "compareTo", "clone",
             "finalize", "readObject", "writeObject", "readResolve",
             "readObjectNoData", "run", "call", "get", "set", "accept",
             "apply", "test", "setup", "teardown"},
    "kotlin": {"main", "toString", "equals", "hashCode", "compareTo", "invoke",
               "getValue", "setValue", "provideDelegate", "component1"},
    "ruby": {"initialize", "to_s", "inspect", "==", "eql?", "hash", "each",
             "call", "method_missing", "respond_to_missing?", "to_json",
             "self.inherited", "included", "extended", "prepended"},
    "php": {"__construct", "__destruct", "__toString", "__invoke", "__get",
            "__set", "__call", "__callStatic", "__clone", "main"},
    "javascript": {"constructor", "toString", "valueOf", "render", "componentDidMount",
                   "componentWillUnmount", "getDerivedStateFromProps", "shouldComponentUpdate"},
    "typescript": {"constructor", "toString", "valueOf", "render"},
    "rust": {"new", "default", "drop", "clone", "fmt", "from", "into", "main"},
    "c": {"main", "init", "fini", "print", "setup", "teardown"},
    "cpp": {"main", "init", "fini"},
    "csharp": {"Main", "ToString", "Equals", "GetHashCode", "Dispose",
               "Initialize", "OnStart", "OnStop"},
    "swift": {"main", "application", "init", "deinit", "copy"},
    "scala": {"main", "toString", "equals", "hashCode", "apply", "unapply"},
    "elixir": {"init", "start", "child_spec", "handle_call", "handle_info",
               "handle_cast", "terminate"},
    "erlang": {"init", "start", "start_link", "loop", "handle_call", "handle_info"},
    "haskell": {"main"},
    "lua": {"init", "new"},
    "dart": {"main", "initState", "dispose", "build", "toString", "=="},
    "r": {"main", "print", "summary"},
    "perl": {"new", "DESTROY", "AUTOLOAD"},
}

# Test entry points, regardless of the naming convention in use.
TEST_NAME_PREFIXES = ("test", "Test", "spec", "Spec", "bench", "Benchmark",
                      "example", "Example", "fuzz", "Fuzz")


def is_entry_point(name: str, language: str = "") -> bool:
    """Whether a name is an entry point by convention rather than by call."""
    if not name:
        return False
    if name in UNIVERSAL:
        return True
    if name.startswith("_test") or name.startswith("test_"):
        return True
    for prefix in TEST_NAME_PREFIXES:
        if not name.startswith(prefix) or len(name) <= len(prefix):
            continue
        rest = name[len(prefix)]
        # testFoo, TestFoo and test_foo count. `testing`, `specify` and
        # `benchmarker` do not: a test prefix must be a word boundary.
        if rest.isupper() or rest == "_":
            return True
    return name in PER_LANGUAGE.get(language, ())


# Directories whose contents are run or read standalone rather than imported.
STANDALONE_DIRS = ("/samples/", "/sample/", "/examples/", "/example/", "/demo/",
                   "/demos/", "/fixtures/", "/testdata/", "/vendor/", "/third_party/")


def is_test_path(path: str) -> bool:
    p = path.replace("\\", "/")
    # match on a path segment, so `tests/foo.php` counts but `contests/foo.py`
    # does not, and the repo root itself is covered.
    segs = ("/" + p.lstrip("/"))
    for marker in ("/test/", "/tests/", "/spec/", "/specs/", "/__tests__/",
                   "/testing/", "/unittests/"):
        if marker in segs:
            return True
    return any(p.endswith(sfx) or sfx in p for sfx in
               ("_test.", "test_", ".test.", ".spec.")) or p.endswith(
        ("Test.java", "Tests.cs", "_test.go", "_test.py"))


def is_standalone_path(path: str) -> bool:
    p = "/" + path.replace("\\", "/").lstrip("/")
    return any(d in p for d in STANDALONE_DIRS)
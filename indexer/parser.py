"""Tree-sitter based code parser. Extracts symbols and edges from source files.

Supported languages:
  - Custom queries: python, javascript, typescript, tsx, rust (richer extraction)
  - All others: uses tree-sitter-language-pack's process() for basic symbols
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .languages import LANGUAGE_QUERIES as _LANGUAGE_QUERIES

try:
    from tree_sitter import Language, Node, Parser, Query, QueryCursor
    from tree_sitter_language_pack import ProcessConfig, detect_language_from_extension, process
except ImportError:  # tree-sitter not installed: indexing is unavailable, but DB reads still work
    Language = Node = Parser = Query = QueryCursor = None  # type: ignore[misc,assignment]
    ProcessConfig = None  # type: ignore[misc,assignment]

    def detect_language_from_extension(*_args: object, **_kwargs: object) -> str | None:  # type: ignore[misc]
        return None

    def process(*_args: object, **_kwargs: object):  # type: ignore[misc]
        raise RuntimeError("tree-sitter is not installed; code indexing is unavailable")

# ── Language grammars ────────────────────────────────────────────────

_GRAMMAR_CACHE: dict = {}

# The bundled language pack does not map these extensions, so a file with one was
# never even considered for indexing. Filling them in is a mapping change, not a
# query: each language still needs a query to extract declarations.
EXTRA_EXTENSION_LANGUAGES = {
    ".sql": "sql",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    "dockerfile": "dockerfile",
    ".tf": "hcl",
    ".tfvars": "hcl",
}

_EXTENSION_OVERRIDES = {
    **{k: v for k, v in EXTRA_EXTENSION_LANGUAGES.items() if k.startswith(".")},
    "dockerfile": "dockerfile",
}


def detect_language_for_file(file_path) -> str | None:
    """Extension -> language, preferring our own map over the pack's."""
    p = Path(file_path)
    name = p.name.lower()
    if name in _EXTENSION_OVERRIDES or name.startswith("dockerfile"):
        return "dockerfile"
    ext = p.suffix.lower()
    if ext in _EXTENSION_OVERRIDES:
        return _EXTENSION_OVERRIDES[ext]
    if not ext or ext in _SKIP_EXTENSIONS:
        return None
    return detect_language_from_extension(ext.lstrip("."))

# Map our language names to the bundled .so filename and C export function.
_LANGUAGE_SO = {
    "python":     ("libtree_sitter_python.so",     "tree_sitter_python"),
    "javascript": ("libtree_sitter_javascript.so", "tree_sitter_javascript"),
    "typescript": ("libtree_sitter_typescript.so", "tree_sitter_typescript"),
    "tsx":        ("libtree_sitter_tsx.so",        "tree_sitter_tsx"),
    "rust":       ("libtree_sitter_rust.so",       "tree_sitter_rust"),
    "java":       ("libtree_sitter_java.so",       "tree_sitter_java"),
    "c":          ("libtree_sitter_c.so",          "tree_sitter_c"),
    "cpp":        ("libtree_sitter_cpp.so",        "tree_sitter_cpp"),
}


def _get_grammar(lang: str) -> Language | None:
    if lang in _GRAMMAR_CACHE:
        return _GRAMMAR_CACHE[lang]
    try:
        from tree_sitter_language_pack import get_language
        lang_obj = get_language(lang)
        if lang_obj is not None:
            _GRAMMAR_CACHE[lang] = lang_obj
            return lang_obj
    except Exception:
        pass
    return None


def ensure_grammars():
    """Download any missing tree-sitter grammar .so files for languages in _LANGUAGE_SO."""
    from tree_sitter_language_pack import downloaded_languages
    downloaded = set(downloaded_languages())
    needed = [lang for lang in _LANGUAGE_SO if lang not in downloaded]
    if not needed:
        return
    from tree_sitter_language_pack import download
    download(needed)


# Trained models and binary data blobs. The language pack maps almost none of
# these, so they were skipped by accident; `.pkl` and `.pbtxt` are mapped, and a
# repository's `models/` directory would otherwise have every checkpoint read
# into memory on each index. Listed explicitly so a future pack version that maps
# more of them does not silently reintroduce the cost.
_MODEL_ARTIFACT_EXTENSIONS = frozenset({
    ".pkl", ".pickle", ".pbtxt", ".keras", ".h5", ".hdf5", ".ckpt",
    ".pt", ".pth", ".onnx", ".safetensors", ".tflite", ".engine",
    ".mlmodel", ".caffemodel", ".params", ".gguf", ".ggml", ".pb",
    ".npy", ".npz", ".parquet", ".feather", ".arrow", ".msgpack",
    ".db", ".mdb", ".lmdb", ".rdb", ".bin", ".dat",
})


# .yaml/.toml/.graphql/.sql used to sit here and were never opened. They now have
# real extraction (see languages/iaccfg.py) and are indexed as resources, the way
# cbm treats Dockerfile/K8s nodes. The rest are still noise.
_SKIP_EXTENSIONS = frozenset({
    ".md", ".markdown", ".rst", ".txt", ".tex",
    ".json", ".jsonc", ".json5",
    ".ini", ".cfg", ".conf",
    ".css", ".scss", ".less", ".sass",
    ".html", ".htm", ".xhtml",
    ".xml", ".svg", ".proto",
    ".db", ".sqlite",
    ".csv", ".tsv",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp",
    ".woff", ".woff2", ".ttf", ".eot",
    ".pdf", ".doc", ".docx",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
})

# ── Queries per language ─────────────────────────────────────────────

PYTHON_QUERIES = {
    "function": """
        (function_definition
            name: (identifier) @name
            parameters: (parameters) @params
            body: (block) @body) @symbol
    """,
    "class": """
        (class_definition
            name: (identifier) @name
            body: (block) @body) @symbol
    """,
    "call": """
        (call function: (identifier) @func) @call
    """,
    "method_call": """
        (call function: (attribute attribute: (identifier) @method) @attr) @call
    """,
    "import": """
        (import_statement
            name: (dotted_name) @name) @import
    """,
    "import_from": """
        (import_from_statement
            module_name: (_) @module
            name: (_) @name) @import_from
    """,
    "relative_import": """
        (import_from_statement
            name: (relative_import) @name) @import_from
    """,
    "decorator": """
        (decorator (identifier) @name) @decorator
    """,
}

JS_QUERIES = {
    "function": """
        (function_declaration
            name: (identifier) @name
            body: (statement_block) @body) @symbol
    """,
    "arrow": """
        (variable_declarator
            name: (identifier) @name
            value: (arrow_function) @body) @symbol
    """,
    "class": """
        (class_declaration
            name: (identifier) @name
            body: (class_body) @body) @symbol
    """,
    "method": """
        (method_definition
            name: (property_identifier) @name
            body: (statement_block) @body) @symbol
    """,
    "call": """
        (call_expression
            function: (identifier) @func) @call
    """,
    "method_call": """
        (call_expression
            function: (member_expression
                property: (property_identifier) @method)) @call
    """,
    "optional_call": """
        (optional_call_expression
            function: (member_expression
                property: (property_identifier) @method)) @call
    """,
    "new": """
        (new_expression constructor: (identifier) @func) @call
    """,
    "import": """
        (import_statement
            source: (string) @source) @import
    """,
    "require": """
        (call_expression
            function: (identifier) @func
            arguments: (arguments (string) @source)) @require
    """,
    "export": """
        (export_statement) @export
    """,
}

TS_QUERIES = {
    "function": """
        (function_declaration
            name: (identifier) @name
            body: (statement_block) @body) @symbol
    """,
    "arrow": """
        (variable_declarator
            name: (identifier) @name
            value: (arrow_function) @body) @symbol
    """,
    "class": """
        (class_declaration
            name: (type_identifier) @name
            body: (class_body) @body) @symbol
    """,
    "method": """
        (method_definition
            name: (property_identifier) @name
            body: (statement_block) @body) @symbol
    """,
    "method_signature": """
        (method_signature
            name: (property_identifier) @name) @symbol
    """,
    "interface": """
        (interface_declaration
            name: (type_identifier) @name
            body: (interface_body) @body) @symbol
    """,
    "type_alias": """
        (type_alias_declaration
            name: (type_identifier) @name
            value: (_) @body) @symbol
    """,
    "enum": """
        (enum_declaration
            name: (identifier) @name
            body: (enum_body) @body) @symbol
    """,
    "call": """
        (call_expression
            function: (identifier) @func) @call
    """,
    "method_call": """
        (call_expression
            function: (member_expression
                property: (property_identifier) @method)) @call
    """,
    "optional_call": """
        (optional_call_expression
            function: (member_expression
                property: (property_identifier) @method)) @call
    """,
    "new": """
        (new_expression constructor: (identifier) @func) @call
    """,
    "import": """
        (import_statement
            source: (string) @source) @import
    """,
    "export": """
        (export_statement) @export
    """,
}

RUST_QUERIES = {
    "function": """
        (function_item
            name: (identifier) @name
            body: (block) @body) @symbol
    """,
    "struct": """
        (struct_item
            name: (type_identifier) @name
            body: (field_declaration_list) @body) @symbol
    """,
    "enum": """
        (enum_item
            name: (type_identifier) @name
            body: (enum_variant_list) @body) @symbol
    """,
    "trait": """
        (trait_item
            name: (type_identifier) @name
            body: (declaration_list) @body) @symbol
    """,
    "impl": """
        (impl_item
            type: (type_identifier) @type) @symbol
    """,
    "call": """
        (call_expression
            function: (identifier) @func) @call
    """,
    "scoped_call": """
        (call_expression
            function: (scoped_identifier) @func) @call
    """,
    "method_call": """
        (call_expression
            function: (field_expression
                field: (field_identifier) @method)) @call
    """,
    "import": """
        (use_declaration
            argument: (scoped_identifier) @path) @import
    """,
    "macro": """
        (macro_invocation
            macro: (identifier) @name) @macro
    """,
}

LANGUAGE_QUERIES = {
    "python": PYTHON_QUERIES,
    "javascript": JS_QUERIES,
    "typescript": TS_QUERIES,
    "tsx": TS_QUERIES,
    "rust": RUST_QUERIES,
}

LANGUAGE_QUERIES = _LANGUAGE_QUERIES


# ── Process-based structure kind mapping ─────────────────────────────

_PROCESS_KIND_MAP = {
    "Function": "function",
    "Method": "method",
    "Class": "class",
    "Type": "class",
    "Interface": "interface",
    "Struct": "struct",
    "Enum": "enum",
    "Trait": "trait",
    "Module": "module",
}


# Parsers are expensive to build (grammar load + query compilation) and
# hold no per-parse state, so one per language is reused for the process.
_PARSER_CACHE: dict = {}


class CodeParser:
    """Parses source code into symbols and edges using tree-sitter.

    Uses custom .scm queries for python/js/ts/tsx/rust (richer extraction
    with call edges, method context, etc.), and falls back to the
    language-pack's process() for all other recognized languages.
    """

    def __init__(self, language: str):
        self.language = language
        self.queries = LANGUAGE_QUERIES.get(language, {})
        self._has_queries = bool(self.queries)
        self._grammar_ok = False
        self._compiled_queries: dict = {}
        if self._has_queries:
            grammar = _get_grammar(language)
            if grammar is not None:
                self.grammar = grammar
                self.parser = Parser()
                self.parser.language = self.grammar
                self._compiled_queries = {}
                self._grammar_ok = True

    @classmethod
    def for_file(cls, file_path: str) -> CodeParser | None:
        lang = detect_language_for_file(file_path)
        if not lang:
            return None
        # One parser per language, reused across files. Compiling a tree-sitter
        # Query costs milliseconds, and a fresh instance recompiles every query
        # for every file -- that alone was ~90% of total indexing time. A
        # tree-sitter Parser holds no per-parse state, so sharing is safe.
        cached = _PARSER_CACHE.get(lang)
        if cached is not None:
            return cached
        parser = cls(lang)
        _PARSER_CACHE[lang] = parser
        return parser

    @classmethod
    def reset_cache(cls):
        """Drop the per-language parser cache.

        Used by worker processes so each one owns its parsers rather than
        inheriting a parent's across fork.
        """
        _PARSER_CACHE.clear()

    @classmethod
    def supported_extension(cls, ext: str) -> bool:
        if not ext or ext in _SKIP_EXTENSIONS or ext in _MODEL_ARTIFACT_EXTENSIONS:
            return False
        if ext in _EXTENSION_OVERRIDES:
            return True
        return detect_language_from_extension(ext.lstrip(".")) is not None

    def _get_query(self, name: str):
        if name not in self._compiled_queries:
            source = self.queries.get(name, "")
            if not source:
                return None
            try:
                self._compiled_queries[name] = Query(self.grammar, source)
            except Exception:
                return None
        return self._compiled_queries[name]

    def parse(self, source_bytes: bytes, file_path: str = ""):
        """Parse source code and extract symbols and edges.

        Returns: (symbols, edges) as lists of dicts.
        Falls back from query-based to process-based parsing if
        the tree-sitter grammar is not available.
        """
        if self._has_queries and self._grammar_ok:
            return self._parse_with_queries(source_bytes, file_path)
        return self._parse_with_process(source_bytes, file_path)

    # ── Query-based parsing (python/js/ts/tsx/rust) ───────────────────

    def _parse_with_queries(self, source_bytes: bytes, file_path: str = ""):
        tree = self.parser.parse(source_bytes)
        root = tree.root_node
        symbols: list[dict] = []
        edges: list[dict] = []
        _seen_ranges = set()

        if root is None:
            return symbols, edges
        # tree-sitter is error-tolerant: one unrecognised token does not spoil
        # the rest of the file, it just makes that region opaque to queries.
        # Bailing on has_error therefore threw away whole files over a single
        # unknown token -- in zlib, `#define local static` alone cost 50% of the
        # repository, including all 83KB of deflate.c.
        if root.has_error and _too_broken_to_index(root):
            return symbols, edges

        text_lines = source_bytes.decode("utf-8", errors="replace").split("\n")

        # Extract definitions
        for kind, query_name in [
            ("function", "function"),
            ("class", "class"),
            # Config and IaC keys are structure, not code. Filing them under
            # `class` or `struct` put a CI workflow's top-level keys into class
            # search, where they outnumbered the real symbols beside them: in
            # ansible, .yml files produced 23,850 symbols against 12,888 from
            # 1,843 Python files.
            #
            # Order matters. Several languages have two queries that capture the
            # same @symbol node, and the parser keeps the first match by byte
            # range, so this must stay ahead of type_alias or HCL starts
            # reporting the block keyword instead of the resource name.
            ("resource", "resource"),
            # A query name ending in `_toplevel` matches only when the declared
            # node has no ancestor of the same type, i.e. it is not shadowed by
            # another declaration of the same kind. OCaml nests a `let` inside
            # another `let` for every local binding, and matching all of them put
            # 8,620 symbols in one types.ml -- including locals and C enum
            # constants. Opt-in rather than a blanket rule, which would wrongly
            # drop Java inner classes.
            ("function", "function_toplevel"),
            ("type_alias", "type_alias_toplevel"),
            ("method", "method"),
            # `obj.method = function () {}` / `= () => {}`. This is the dominant
            # idiom in CommonJS and prototype-style JS, and without it a whole
            # codebase's methods are invisible to the index.
            ("method", "assigned_method"),
            ("method", "assigned_method_literal"),
            ("method_signature", "method_signature"),
            ("interface", "interface"),
            ("type_alias", "type_alias"),
            ("enum", "enum"),
            ("struct", "struct"),
            ("trait", "trait"),
            ("impl", "impl"),
            ("constructor", "constructor"),
            ("namespace", "namespace"),
            ("arrow", "arrow"),
        ]:
            if query_name not in self.queries:
                continue
            q = self._get_query(query_name)
            if q is None:
                continue
            cursor = QueryCursor(q)
            for _p_idx, captures in cursor.matches(root):
                cap_map = {name: nodes for name, nodes in captures.items()}
                sym_node = _first_node(cap_map.get("symbol"))
                name_node = _first_node(cap_map.get("name"))
                if sym_node is None or name_node is None:
                    continue
                if query_name.endswith("_toplevel") and _is_shadowed(sym_node):
                    continue
                range_key = (sym_node.start_byte, sym_node.end_byte)
                if range_key in _seen_ranges:
                    continue
                _seen_ranges.add(range_key)

                sym_name = _node_text(name_node, source_bytes)
                kind_val = kind

                # For Python, detect async and method context
                if self.language == "python" and kind == "function":
                    is_async = sym_node.children and sym_node.children[0].type == "async"
                    is_method = _is_python_method(root, sym_node)
                    if is_async and is_method:
                        kind_val = "async_method"
                    elif is_async:
                        kind_val = "async_function"
                    elif is_method:
                        kind_val = "method"

                # For JavaScript, detect getter/setter
                if self.language in ("javascript", "typescript") and kind == "method":
                    kind_node = _first_node(cap_map.get("kind"))
                    if kind_node:
                        kt = _node_text(kind_node, source_bytes)
                        if kt in ("get", "set"):
                            kind_val = f"{kt}_{kind}"

                rust_parent = None
                if self.language == "rust" and kind == "function":
                    rust_parent = _find_parent_class(root, sym_node)
                    if rust_parent is not None and rust_parent.type == "impl_item":
                        kind_val = "method"

                signature = ""
                if "params" in cap_map:
                    params_node = _first_node(cap_map["params"])
                    if params_node:
                        signature = _node_text(params_node, source_bytes)

                docstring = _extract_docstring(self.language, sym_node, source_bytes, text_lines)
                parent_id = None

                # Determine parent for methods
                if kind_val in ("method", "async_method", "method_signature"):
                    parent = rust_parent or _find_parent_class(root, sym_node)
                    if parent:
                        parent_name_node = _find_named_child(parent, self.language)
                        if parent_name_node:
                            parent_id = _node_text(parent_name_node, source_bytes)

                symbol = {
                    "file_path": file_path,
                    "symbol_name": sym_name,
                    "symbol_type": kind_val,
                    "language": self.language,
                    "kind": "",
                    "start_line": sym_node.start_point[0] + 1,
                    "end_line": sym_node.end_point[0] + 1,
                    "start_col": sym_node.start_point[1] + 1,
                    "end_col": sym_node.end_point[1] + 1,
                    "signature": signature,
                    "docstring": docstring,
                    "parent_id": parent_id,
                    "content_hash": _content_hash(source_bytes, sym_node),
                    "body_hash": _body_hash(source_bytes, sym_node, sym_name),
                }
                symbols.append(symbol)

        # Extract calls
        calls = self._extract_calls(root, source_bytes, file_path)
        edges.extend(calls)

        # Extract imports
        imports = self._extract_imports(root, source_bytes, file_path)
        edges.extend(imports)

        edges.extend(self._extract_instantiations(root, source_bytes, file_path))
        edges.extend(self._extract_inheritance(root, source_bytes, file_path))

        return symbols, edges

    def _extract_calls(self, root: Node, source_bytes: bytes, file_path: str):
        edges = []
        q_call = self._get_query("call")
        q_mcall = self._get_query("method_call")

        if q_call:
            cursor = QueryCursor(q_call)
            for _p_idx, captures in cursor.matches(root):
                call_node = _first_node(captures.get("call"))
                func_node = _first_node(captures.get("func"))
                if call_node and func_node:
                    caller = _find_enclosing_func(source_bytes, call_node, self.language)
                    callee = _node_text(func_node, source_bytes)
                    edges.append({
                        "edge_type": "calls",
                        "from_name": caller or "",
                        "target_name": callee,
                        "file_path": file_path,
                        "line_number": func_node.start_point[0] + 1,
                    })

        if q_mcall:
            cursor = QueryCursor(q_mcall)
            for _p_idx, captures in cursor.matches(root):
                call_node = _first_node(captures.get("call"))
                method_node = _first_node(captures.get("method"))
                if call_node and method_node:
                    caller = _find_enclosing_func(source_bytes, call_node, self.language)
                    callee = _node_text(method_node, source_bytes)
                    receiver_node = (
                        _first_node(captures.get("obj"))
                        or _first_node(captures.get("object"))
                        or _first_node(captures.get("attr"))
                    )
                    receiver = _node_text(receiver_node, source_bytes) if receiver_node else ""
                    # A method call is not a call to a global named `join`; keeping
                    # it as `calls` made every `path.join(...)` look like an
                    # unresolvable free function and wrecked the unresolved rate.
                    edges.append({
                        "edge_type": "member_calls",
                        "from_name": caller or "",
                        "target_name": callee,
                        "target_receiver": receiver,
                        "file_path": file_path,
                        "line_number": method_node.start_point[0] + 1,
                    })

        for query_name, capture_name in (
            ("optional_call", "method"),
            ("new", "func"),
            ("scoped_call", "func"),
        ):
            query = self._get_query(query_name)
            if query is None:
                continue
            cursor = QueryCursor(query)
            for _p_idx, captures in cursor.matches(root):
                call_node = _first_node(captures.get("call"))
                callee_node = _first_node(captures.get(capture_name))
                if call_node and callee_node:
                    caller = _find_enclosing_func(source_bytes, call_node, self.language)
                    raw_target = _node_text(callee_node, source_bytes)
                    # A path-qualified call is stored under the symbol's own name.
                    # `crate::app::build_ui` is the symbol `build_ui`, and keeping
                    # the full path means it never matches and get_callers is empty.
                    target = raw_target
                    receiver = ""
                    if "::" in raw_target:
                        segments = [s for s in raw_target.split("::") if s]
                        target = segments[-1] if segments else raw_target
                        if len(segments) == 2:
                            receiver = segments[0]
                    edges.append({
                        "edge_type": "calls",
                        "from_name": caller or "",
                        "target_name": target,
                        "target_receiver": receiver,
                        "file_path": file_path,
                        "line_number": callee_node.start_point[0] + 1,
                    })

        # Several languages need two patterns for the same call form -- php
        # matches a `variable_name` receiver by its bare name and anything else
        # by its whole text -- and both can match one node. Without this the
        # same call is stored twice and the counts are inflated.
        unique: list[dict] = []
        seen: set[tuple] = set()
        for edge in edges:
            key = (
                edge["edge_type"],
                edge.get("from_name", ""),
                edge.get("target_name", ""),
                edge.get("target_receiver", ""),
                edge.get("line_number", 0),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(edge)
        return unique

    def _extract_inheritance(self, root: Node, source_bytes: bytes, file_path: str):
        """Record `class D(B)` as an inherits edge, subclass -> base.

        Without this a method defined on a base class can never be resolved from
        a subclass instance, so the call graph breaks at every inheritance boundary.
        """
        query = self._get_query("inherits")
        if query is None:
            return []
        edges: list[dict] = []
        for _p_idx, captures in QueryCursor(query).matches(root):
            name_node = _first_node(captures.get("name"))
            base_node = _first_node(captures.get("base"))
            if not (name_node and base_node):
                continue
            subclass = _node_text(name_node, source_bytes)
            base = _node_text(base_node, source_bytes)
            if not subclass or not base or subclass == base:
                continue
            edges.append({
                "edge_type": "inherits",
                "from_name": subclass,
                "target_name": base,
                "target_receiver": "",
                "file_path": file_path,
                "line_number": name_node.start_point[0] + 1,
            })
        return edges

    def _extract_instantiations(self, root: Node, source_bytes: bytes, file_path: str):
        """Record `x = Foo(...)` / `x = new Foo()` so `x.method()` can be typed.

        Without this a receiver like `indexer` in `indexer.close()` has nothing to
        resolve against: it is a local variable, not a class, so a method lookup
        has no key. The variable rides in to_receiver because from_name already
        holds the enclosing function.
        """
        edges: list[dict] = []
        # Parameters and receivers are typed at their declaration, which is what
        # lets a call on a parameter or a method receiver resolve.
        for query_name in ("param", "param_value", "param_signature", "param_method",
                            "param_abstract", "self_type"):
            query = self._get_query(query_name)
            if query is None:
                continue
            for _p_idx, captures in QueryCursor(query).matches(root):
                # `assign` is the inner node (the declaration itself), so prefer it:
                # `symbol` is often the enclosing impl or type, which has no name.
                anchor = _first_node(captures.get("assign")) or _first_node(captures.get("symbol"))
                name_node = _first_node(captures.get("name"))
                type_node = _first_node(captures.get("func"))
                if not (anchor and name_node and type_node):
                    continue
                # A `self_type` match supplies the enclosing method's name as the
                # subject; the receiver it types is always `self`.
                param = "self" if query_name == "self_type" else _node_text(name_node, source_bytes)
                declared = _normalize_type(_node_text(type_node, source_bytes))
                if not param or not declared or param == declared:
                    continue
                edges.append({
                    "edge_type": "param_type",
                    "from_name": _find_enclosing_func(
                        source_bytes, anchor, self.language, include_self=True
                    ) or "",
                    "target_name": declared,
                    "target_receiver": param,
                    "file_path": file_path,
                    "line_number": anchor.start_point[0] + 1,
                })

        for query_name in ("instantiate", "instantiate_call", "annotate"):
            query = self._get_query(query_name)
            if query is None:
                continue
            for _p_idx, captures in QueryCursor(query).matches(root):
                assign_node = _first_node(captures.get("assign"))
                name_node = _first_node(captures.get("name"))
                func_node = _first_node(captures.get("func"))
                if not (assign_node and name_node and func_node):
                    continue
                variable = _node_text(name_node, source_bytes)
                constructor = _node_text(func_node, source_bytes)
                if not variable or not constructor or variable == constructor:
                    continue
                edges.append({
                    "edge_type": "instantiates",
                    "from_name": _find_enclosing_func(source_bytes, assign_node, self.language) or "",
                    "target_name": constructor,
                    "target_receiver": variable,
                    "file_path": file_path,
                    "line_number": assign_node.start_point[0] + 1,
                })
        return edges

    def _extract_imports(self, root: Node, source_bytes: bytes, file_path: str):
        edges = []
        q_import = self._get_query("import")
        q_from = self._get_query("import_from")

        if q_import:
            cursor = QueryCursor(q_import)
            for _p_idx, captures in cursor.matches(root):
                source_node = _first_node(captures.get("source"))
                name_node = _first_node(captures.get("name"))
                if source_node:
                    src = _node_text(source_node, source_bytes).strip("'\"")
                    edges.append({
                        "edge_type": "imports",
                        "from_name": src,
                        "target_name": None,
                        "file_path": file_path,
                        "line_number": source_node.start_point[0] + 1,
                    })
                elif name_node:
                    name = _node_text(name_node, source_bytes)
                    edges.append({
                        "edge_type": "imports",
                        "from_name": name,
                        "target_name": None,
                        "file_path": file_path,
                        "line_number": name_node.start_point[0] + 1,
                    })

        for import_query in (q_from, self._get_query("relative_import")):
            if import_query is None:
                continue
            cursor = QueryCursor(import_query)
            for _p_idx, captures in cursor.matches(root):
                module_node = _first_node(captures.get("module"))
                name_node = _first_node(captures.get("name"))
                if module_node:
                    module = _node_text(module_node, source_bytes)
                    name = _node_text(name_node, source_bytes) if name_node else "*"
                    import_name = f"{module}.{name}"
                elif name_node:
                    import_name = _node_text(name_node, source_bytes)
                else:
                    continue
                anchor = module_node or name_node
                edges.append({
                    "edge_type": "imports",
                    "from_name": import_name,
                    "target_name": None,
                    "file_path": file_path,
                    "line_number": anchor.start_point[0] + 1,
                })

        return edges


    # ── Process-based fallback (any language without custom queries) ──

    def _parse_with_process(self, source_bytes: bytes, file_path: str = ""):
        source_str = source_bytes.decode("utf-8", errors="replace")
        config = ProcessConfig(
            language=self.language,
            structure=True,
            imports=True,
            symbols=False,
            comments=False,
            docstrings=False,
        )
        result = process(source_str, config)

        symbols = []
        edges = []
        _seen_ranges = set()

        for item in result.structure:
            name = item.name
            if not name or str(name).strip() == "":
                continue
            s = item.span
            if s is None:
                continue
            range_key = (s.start_byte, s.end_byte)
            if range_key in _seen_ranges:
                continue
            _seen_ranges.add(range_key)

            kind_str = str(item.kind)
            sym_type = _PROCESS_KIND_MAP.get(kind_str, kind_str.lower())

            signature = ""
            if item.signature and str(item.signature) != "None":
                signature = str(item.signature)

            docstring = ""
            if item.doc_comment:
                docstring = str(item.doc_comment)

            symbol = {
                "file_path": file_path,
                "symbol_name": str(name),
                "symbol_type": sym_type,
                "language": self.language,
                "kind": kind_str.lower(),
                "start_line": s.start_line + 1,
                "end_line": s.end_line + 1,
                "start_col": s.start_column + 1,
                "end_col": s.end_column + 1,
                "signature": signature,
                "docstring": docstring,
                "parent_id": None,
                "content_hash": hashlib.sha256(
                    source_bytes[s.start_byte:s.end_byte]
                ).hexdigest()[:16],
                "body_hash": _body_hash(source_bytes, s.node, s.name)
                if getattr(s, "node", None) is not None
                else "",
            }
            symbols.append(symbol)

        for imp in result.imports:
            src = str(imp.source) if imp.source else ""
            edges.append({
                "edge_type": "imports",
                "from_name": src.strip("'\""),
                "target_name": None,
                "file_path": file_path,
                "line_number": imp.span.start_line + 1 if imp.span else 0,
            })

        return symbols, edges


# ── Helpers ──────────────────────────────────────────────────────────

def _node_text(node, source_bytes):
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


_TYPE_QUALIFIER = re.compile(r"\b(?:mut|ref|dyn|const|static|unsafe|extern)\b\s*")
_TYPE_LIFETIME = re.compile(r"'[A-Za-z_][A-Za-z0-9_]*\b\s*")
_TYPE_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Transparent wrappers: the methods a caller reaches through them belong to the
# inner type, so unwrap to it. Collections are deliberately absent -- `v.push()`
# on a Vec really is a Vec method, and unwrapping to the element type would lose it.
_TYPE_WRAPPERS = frozenset(
    {"box", "rc", "arc", "refcell", "refmut", "mutex", "rwlock", "option", "cow", "pin",
     "cell", "lockresult"}
)


def _normalize_type(declared):
    """Reduce a declared type to the bare name a symbol is stored under.

    `&mut Widget`, `&'a Widget`, `*const Widget` and `Box<Widget>` all name the
    same underlying type, so storing them verbatim makes every lookup miss.
    """
    if not declared:
        return ""
    text = _TYPE_QUALIFIER.sub("", _TYPE_LIFETIME.sub("", declared)).strip()
    text = text.lstrip("&*").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()  # a slice `[T]` is the type T for lookup purposes
    if "::" in text:
        text = text.rpartition("::")[2]  # `std::sync::Arc` is stored as `Arc`
    names = _TYPE_IDENT.findall(text)
    if not names:
        return ""
    # Walk through any stack of transparent wrappers: `Rc<RefCell<AppState>>` is
    # `AppState`. A collection stops the walk, because `v.push()` really is a
    # method on the Vec rather than on its element type.
    for name in names[:-1]:
        if name.lower() not in _TYPE_WRAPPERS:
            return name
    return names[-1]


def _first_node(nodes):
    if not nodes:
        return None
    return nodes[0]


def _content_hash(source_bytes, node):
    return hashlib.sha256(source_bytes[node.start_byte:node.end_byte]).hexdigest()[:16]


_IDENT_RE = re.compile(rb"[A-Za-z_$][A-Za-z0-9_$]*")


def _body_hash(source_bytes, node, name: str = "") -> str:
    """Rename-invariant hash of a symbol's body.

    _content_hash covers the whole declaration, so renaming a function changes it
    and a memory note would lose its symbol. Here every identifier is normalized to
    a placeholder, leaving literals and structure intact. Two symbols with the same
    shape and the same literals therefore hash equal, so a rename or a move keeps
    the link. This is deliberately coarser than content_hash: it is a fallback for
    matching, not an identity.
    """
    body = source_bytes[node.start_byte:node.end_byte]
    return hashlib.sha256(_IDENT_RE.sub(b"ID", body)).hexdigest()[:16]


def _is_python_method(_root, func_node):
    """Check if a function_definition is inside a class."""
    parent = func_node.parent
    while parent is not None and parent.type != "module":
        if parent.type == "class_definition":
            return True
        parent = parent.parent
    return False


def _extract_docstring(language, sym_node, source_bytes, text_lines):
    """Extract docstring / comment text."""
    if language == "python":
        body = _find_child_of_type(sym_node, "block")
        if body and body.children:
            first = body.children[0]
            if first.type == "expression_statement" and first.children:
                maybe_str = first.children[0]
                if maybe_str.type == "string":
                    return _node_text(maybe_str, source_bytes).strip("\"'")
            elif first.type == "string":
                return _node_text(first, source_bytes).strip("\"'")
    elif language in ("javascript", "typescript"):
        start_line = sym_node.start_point[0]
        comment_lines = []
        for i in range(start_line - 1, max(start_line - 5, -1), -1):
            line = text_lines[i].strip() if i < len(text_lines) else ""
            if line.startswith("//"):
                comment_lines.insert(0, line[2:].strip())
            elif line.startswith("/*") or line.startswith("*"):
                comment_lines.insert(0, line.strip().strip("/*").strip("*").strip())
            elif line.startswith("/**"):
                comment_lines.insert(0, line.strip().lstrip("/*").rstrip("*/").strip())
            else:
                break
        if comment_lines:
            return " ".join(comment_lines)
    elif language == "rust":
        start_line = sym_node.start_point[0]
        comments = []
        for i in range(start_line - 1, max(start_line - 5, -1), -1):
            line = text_lines[i].strip() if i < len(text_lines) else ""
            if line.startswith("///") or line.startswith("//!"):
                comments.insert(0, line[3:].strip())
            elif line.startswith("/*") or line.startswith("*"):
                comments.insert(0, line.strip().strip("/*").strip("*").strip())
            else:
                break
        if comments:
            return " ".join(comments)
    return ""


def _find_child_of_type(node, type_name):
    for c in node.children:
        if c.type == type_name:
            return c
    return None


def _is_shadowed(node) -> bool:
    """Whether a declaration is nested inside another of the same kind."""
    cur = node.parent
    while cur is not None:
        if cur.type == node.type:
            return True
        cur = cur.parent
    return False


def _too_broken_to_index(root) -> bool:
    """Whether a file is too damaged to be worth extracting anything from.

    Measured by counting errored *top-level* children rather than bytes. Once
    tree-sitter loses sync it swallows a large span into one ERROR node, so a
    byte share badly understates what is still recoverable: zlib's deflate.c has
    one ERROR child out of fifty, and that error covers 70% of the file's bytes
    while the other 49 top-level declarations parse perfectly.
    """
    if root.type == "ERROR":
        return True
    children = root.children
    if not children:
        return False
    bad = sum(1 for c in children if c.type == "ERROR" or c.is_missing)
    return bad * 2 > len(children)


# Grammars disagree on what a file is called and what a class is called, so both
# lists are shared rather than hardcoded per grammar.
_ROOT_NODE_TYPES = frozenset(
    {"module", "program", "source_file", "compilation_unit", "file", "haskell", "chunk"}
)
_CLASS_NODE_TYPES = frozenset(
    {
        "class_definition", "class_declaration", "impl_item", "object_declaration",
        "interface_declaration", "trait_item", "class", "struct_item", "class_specifier",
    }
)
# Declaration nodes that can enclose a call, used to attribute an edge to a caller.
_FUNCTION_NODE_TYPES = frozenset(
    {
        "function_definition", "function_declaration", "function_item", "method_definition",
        "async_function_definition", "async_method_definition", "arrow_function",
        "function_signature", "fun_decl", "routine", "value_definition",
        "function_declaration_left", "bind",
        # Go keeps methods in their own node rather than nesting them under a
        # class, so omitting it left every Go caller unattributed.
        "method_declaration",
    }
)


def _find_parent_class(_root, method_node):
    cursor = method_node.walk()
    parent = cursor.node.parent
    while parent is not None and parent.type not in _ROOT_NODE_TYPES:
        if parent.type in _CLASS_NODE_TYPES:
            return parent
        parent = parent.parent
    return None


def _find_enclosing_func(source_bytes, node, language, include_self=False):
    """Walk up to find the enclosing function/method name, as text.

    Returns the name string (not the node) because callers store it directly on
    the edge's from_name. `include_self` matters when the anchor already *is* the
    declaration, as it is for a parameter or a method's own `self`.
    """
    if include_self and node is not None and node.type in _FUNCTION_NODE_TYPES:
        name_node = _find_named_child(node, language)
        if name_node is not None:
            return _node_text(name_node, source_bytes)
    cur = node.parent
    while cur is not None and cur.type not in _ROOT_NODE_TYPES:
        if cur.type in _FUNCTION_NODE_TYPES:
            name_node = _find_named_child(cur, language)
            return _node_text(name_node, source_bytes) if name_node is not None else None
        cur = cur.parent
    return None


# The child node type that holds a declaration's name, per grammar. Tried in
# order; a shared fallback chain covers grammars that use a generic identifier.
_NAME_NODE_TYPES = {
    "python": ("identifier",),
    "javascript": ("identifier", "type_identifier"),
    "typescript": ("identifier", "type_identifier"),
    "tsx": ("identifier", "type_identifier"),
    "rust": ("type_identifier", "identifier"),
    "kotlin": ("simple_identifier", "type_identifier", "identifier"),
    "julia": ("identifier",),
    "perl": ("bareword", "identifier"),
    "erlang": ("atom", "variable"),
    "ocaml": ("value_name", "type_constructor", "constructor_name", "identifier"),
    "nim": ("ident", "identifier"),
    "fsharp": ("identifier", "long_identifier"),
    "haskell": ("variable", "name", "constructor"),
    "zig": ("IDENTIFIER", "identifier"),
    "go": ("identifier", "field_identifier", "type_identifier"),
}
_NAME_FALLBACKS = ("identifier", "simple_identifier", "IDENTIFIER", "atom", "name", "value_name", "bareword")


def _find_declarator_name(node, depth=0):
    """C and C++ bury a declared name under a chain of declarators.

    `function_definition -> declarator -> function_declarator -> declarator ->
    identifier`, so a direct-child search never finds it and every edge from a C
    or C++ file ended up with an empty from_name.
    """
    if node is None or depth > 4:
        return None
    for c in node.children:
        if c.type in _NAME_FALLBACKS or c.type in ("type_identifier", "field_identifier"):
            return c
    for c in node.children:
        if "declarator" in c.type or c.type in ("qualified_identifier", "init_declarator"):
            found = _find_declarator_name(c, depth + 1)
            if found is not None:
                return found
    return None


def _find_named_child(node, language):
    for candidate in _NAME_NODE_TYPES.get(language, ()) + _NAME_FALLBACKS:
        found = _find_child_of_type(node, candidate)
        if found is not None:
            return found
    # Only reached when the direct search found nothing, so languages whose
    # names are direct children keep their existing behaviour.
    return _find_declarator_name(node)

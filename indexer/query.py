"""A small read-only query language over the code graph.

Today every question needs a bespoke tool, so a novel question means new code.
This collapses the common shapes into one composable primitive:

    MATCH (a:Function) RETURN a.name, a.file LIMIT 20
    MATCH (a)-[:CALLS]->(b) WHERE a.name =~ '.*Handler.*' RETURN a, b
    MATCH (a:Class)-[:INHERITS]->(b) RETURN a.name, b.name

It is deliberately a subset, not Cypher. No writes, no arbitrary SQL: the parser
extracts the pieces and the indexer builds its own parameterised statements, so
input can never reach the SQL string verbatim.
"""

from __future__ import annotations

import re

# Labels a pattern node may carry, mapped to symbol_type values in the graph.
LABELS = {
    "function": ("function", "async_function", "arrow", "constructor"),
    "method": ("method", "async_method"),
    "class": ("class", "interface", "struct", "trait", "enum"),
    "type": ("type_alias", "struct", "interface", "enum", "class"),
    "symbol": None,  # any
}

# Relationships a pattern may traverse.
EDGES = ("calls", "member_calls", "imports", "instantiates", "inherits")

_TOKEN = re.compile(
    r"""
    \s+
    | (?P<lparen>\()
    | (?P<rparen>\))
    | (?P<lbrack>\[)
    | (?P<rbrack>\])
    | (?P<lbrace>\{)
    | (?P<rbrace>\})
    | (?P<arrow>->)
    | (?P<dash>--)
    | (?P<dash1>-)
    | (?P<comma>,)
    | (?P<op>:=~|=~|!=|>=|<=|=|>|<|~)
    | (?P<colon>:)
    | (?P<dot>\.)
    | (?P<semi>;)
    | (?P<star>\*)
    | (?P<str>'[^']*'|"[^"]*")
    | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<num>\d+)
    """,
    re.VERBOSE,
)


class QueryError(ValueError):
    """The query is outside the supported subset, or is malformed."""


def _tokenize(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise QueryError(f"unexpected character at offset {pos}: {text[pos]!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind is None:
            continue
        out.append((kind, m.group()))
    return out


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.t = tokens
        self.i = 0

    def peek(self) -> tuple[str, str] | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def next(self) -> tuple[str, str]:
        tok = self.peek()
        if tok is None:
            raise QueryError("unexpected end of query")
        self.i += 1
        return tok

    def accept_word(self, word: str) -> bool:
        tok = self.peek()
        if tok and tok[0] == "word" and tok[1].upper() == word.upper():
            self.i += 1
            return True
        return False

    def accept_kind(self, kind: str) -> bool:
        tok = self.peek()
        if tok and tok[0] == kind:
            self.i += 1
            return True
        return False

    def expect_kind(self, kind: str) -> str:
        tok = self.next()
        if tok[0] != kind:
            raise QueryError(f"expected {kind}, got {tok[1]!r}")
        return tok[1]

    # ── pattern ────────────────────────────────────────────────────
    def parse_pattern(self) -> dict:
        self.expect_kind("lparen")
        a = self._node()
        self.expect_kind("rparen")
        node: dict = {"a": a}

        tok = self.peek()
        if not (tok and tok[0] in ("arrow", "dash", "dash1")):
            return node

        self.next()  # the tokenizer already matched the whole '--' where present
        self.expect_kind("lbrack")
        self.accept_kind("colon")  # both [:REL] and [REL] are written in practice
        rel = self.expect_kind("word").lower()
        if rel not in EDGES:
            raise QueryError(f"unknown relationship {rel!r}; supported: {', '.join(EDGES)}")
        self.expect_kind("rbrack")
        self.expect_kind("arrow")
        self.expect_kind("lparen")
        b = self._node()
        self.expect_kind("rparen")
        node["rel"] = rel
        node["b"] = b
        return node

    def _node(self) -> dict:
        ident = self.expect_kind("word")
        node: dict = {"ident": ident}
        if self.accept_kind("colon"):
            label = self.expect_kind("word").lower()
            if label not in LABELS:
                raise QueryError(
                    f"unknown label {label!r}; supported: {', '.join(LABELS)}"
                )
            node["label"] = label
        if self.accept_kind("dot"):
            node["prop"] = self.expect_kind("word")
        return node

    # ── where ──────────────────────────────────────────────────────
    def parse_where(self, default_ident: str) -> dict | None:
        if not self.accept_word("WHERE"):
            return None
        ident = self.expect_kind("word")
        if self.accept_kind("dot"):
            field = self.expect_kind("word")
        else:
            # `WHERE name = 'x'` with a bare field means the pattern's own node
            ident, field = default_ident, ident
        tok = self.next()
        if tok[0] == "op" and tok[1] == ":=":
            tok = self.next()
            if tok[0] != "word":
                raise QueryError(":= expects a property name")
            prop, op, value = field, ":=", tok[1]
        else:
            if tok[0] not in ("eq", "op"):
                raise QueryError(f"expected a comparison, got {tok[1]!r}")
            prop, op = field, tok[1]
        if op == ":=":
            return {"ident": ident, "prop": prop, "op": op, "value": self._literal()}
        if op in ("=~", "!="):
            v = self.next()
            if v[0] != "str":
                raise QueryError(f"{op} expects a quoted string")
            return {"ident": ident, "prop": prop, "op": op, "value": v[1][1:-1]}
        # = and ~ compare against a string
        v = self.next()
        if v[0] not in ("str", "word", "num"):
            raise QueryError(f"expected a value, got {v[1]!r}")
        value = v[1][1:-1] if v[0] == "str" else v[1]
        return {"ident": ident, "prop": prop, "op": "~" if op == "~" else "=", "value": value}

    def _literal(self) -> str:
        v = self.next()
        if v[0] not in ("str", "word", "num"):
            raise QueryError("expected a value after :=")
        return v[1][1:-1] if v[0] == "str" else v[1]

    # ── return ─────────────────────────────────────────────────────
    def parse_return(self) -> tuple[list[dict], int, tuple[str, str] | None]:
        if not self.accept_word("RETURN"):
            raise QueryError("RETURN is required")
        items: list[dict] = []
        while True:
            item = self._return_item()
            items.append(item)
            if not self.accept_kind("comma"):
                break
        order = self.parse_order_by()
        limit = 50
        if self.accept_word("LIMIT"):
            n = self.next()
            if n[0] != "num":
                raise QueryError("LIMIT expects a number")
            limit = max(1, min(int(n[1]), 1000))
        return items, limit, order

    def _return_item(self) -> dict:
        """One RETURN term: a field, or an aggregate over a node."""
        if self.accept_word("count"):
            if not self.accept_kind("lparen"):
                raise QueryError("count expects (a) or (b)")
            if self.accept_kind("star"):
                target = "*"
            else:
                target = self.expect_kind("word")
            if not self.accept_kind("rparen"):
                raise QueryError("count(...) is missing its closing parenthesis")
            prop = self.expect_kind("word") if self.accept_kind("dot") else "count"
            if not self.accept_word("AS"):
                raise QueryError(f"count(...) needs an alias: AS name")
            alias = self.expect_kind("word")
            return {"ident": target, "prop": prop, "agg": "count", "alias": alias}
        ident = self.expect_kind("word")
        if self.accept_kind("dot"):
            prop = self.expect_kind("word")
        else:
            prop = "name" if ident in ("a", "b") else ident
        alias = None
        if self.accept_word("AS"):
            alias = self.expect_kind("word")
        return {"ident": ident, "prop": prop, "agg": None, "alias": alias}

    def parse_order_by(self) -> tuple[str, str] | None:
        """`ORDER BY name [ASC|DESC]`, naming a returned column or an alias."""
        if not self.accept_word("ORDER"):
            return None
        if not self.accept_word("BY"):
            raise QueryError("ORDER must be followed by BY")
        col = self.next()
        if col[0] != "word":
            raise QueryError("ORDER BY expects a column name or alias")
        direction = "ASC"
        if self.accept_word("DESC"):
            direction = "DESC"
        elif self.accept_word("ASC"):
            direction = "ASC"
        return col[1], direction


def parse(query: str) -> dict:
    """Parse the supported subset into a plan, or raise QueryError."""
    text = (query or "").strip()
    if not text:
        raise QueryError("empty query")
    p = _Parser(_tokenize(text))
    if not p.accept_word("MATCH"):
        raise QueryError("query must start with MATCH")
    pattern = p.parse_pattern()
    where_a = p.parse_where("a")
    where_b = p.parse_where("b") if "b" in pattern else None
    returns, limit, order = p.parse_return()
    leftover = p.peek()
    if leftover is not None:
        raise QueryError(f"unsupported trailing input near {leftover[1]!r}")
    return {
        "pattern": pattern,
        "where": [w for w in (where_a, where_b) if w],
        "returns": returns,
        "limit": limit,
        "order": order,
    }


def describe() -> str:
    return (
        "code_query subset:\n"
        "  MATCH (a) [WHERE a.name = 'x' | a.name =~ 're' | a.name ~ 'x']\n"
        "  MATCH (a:Label) RETURN a.name, a.file LIMIT n\n"
        "  MATCH (a)-[:REL]->(b) [WHERE ...] RETURN a.name, b.name\n"
        "  MATCH (a)-[:REL]->(b) RETURN b.name, count(a) AS callers ORDER BY callers DESC\n"
        "      (the plain field is the subject; count() names the other side)\n"
        "  MATCH (a:Label) RETURN count(*) AS total\n"
        f"  labels:   {', '.join(LABELS)}\n"
        f"  relations: {', '.join(EDGES)}\n"
        "  fields:   name, file, type, language, line, kind\n"
        "  labels and relations are case-sensitive; an unknown one matches nothing"
    )

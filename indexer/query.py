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
    | (?P<leftarrow><-)
    | (?P<arrow>->)
    | (?P<dash>--)
    | (?P<dash1>-)
    | (?P<comma>,)
    | (?P<pipe>\|)
    | (?P<op>:=~|=~|!~|!=|>=|<=|=|>|<|~)
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
        if not (tok and tok[0] in ("arrow", "dash", "dash1", "leftarrow")):
            return node

        # A chain: (a)-[:calls]->(b)-[:calls]->(c). A node may be anonymous, `()`,
        # in which case it gets a synthetic name so RETURN can still address it.
        hops: list[dict] = []
        while True:
            self.next()
            self.expect_kind("lbrack")
            self.accept_kind("colon")  # both [:REL] and [REL] are written in practice
            rel = self.expect_kind("word").lower()
            if rel not in EDGES:
                raise QueryError(
                    f"unknown relationship {rel!r}; supported: {', '.join(EDGES)}")
            # `[:calls|member_calls]` — a real call chain alternates between the
            # two, so pinning one relation per hop usually finds nothing.
            while self.accept_kind("pipe"):
                nxt = self.next()
                if nxt[0] == "rbrack":
                    raise QueryError("a trailing '|' has no relationship after it")
                if nxt[0] != "word" or nxt[1].lower() not in EDGES:
                    got = nxt[1] if nxt[0] == "word" else nxt[0]
                    raise QueryError(
                        f"unknown relationship {got!r}; supported: {', '.join(EDGES)}")
                rel = f"{rel}|{nxt[1].lower()}"
            self.expect_kind("rbrack")
            if not (self.accept_kind("arrow") or self.accept_kind("dash")
                    or self.accept_kind("dash1") or self.accept_kind("leftarrow")):
                raise QueryError(
                    "a relationship needs an arrow, as in -[:calls]->()")
            self.expect_kind("lparen")
            target = self._node()
            self.expect_kind("rparen")
            hops.append({"rel": rel, "node": target})
            if not target["ident"]:
                target["ident"] = f"h{len(hops)}"
                target["anon"] = True
            nxt = self.peek()
            if nxt and nxt[0] in ("arrow", "dash", "dash1", "leftarrow"):
                continue
            break

        node["hops"] = hops
        node["rel"] = hops[0]["rel"]
        for h in hops:
            h["rels"] = h["rel"].split("|")
        node["b"] = hops[-1]["node"]
        node["nodes"] = {"a": a}
        for i, h in enumerate(hops):
            node["nodes"][h["node"]["ident"]] = h["node"]
        return node

    def _node(self) -> dict:
        """A pattern node: `(name)`, `(name:Label)`, or the anonymous `()`."""
        tok = self.peek()
        if tok is None:
            raise QueryError("unexpected end of query")
        if tok[0] == "rparen":
            return {"ident": None, "anon": True}
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
    def parse_where(self, default_ident: str) -> tuple[list[dict], str] | None:
        """`WHERE a AND b OR c` into (clauses, joiner).

        Only one joiner may appear. Mixing them needs parentheses, which this
        subset does not have, so it is rejected rather than resolved by a
        precedence the author did not intend.
        """
        if not self.accept_word("WHERE"):
            return None
        clauses = [self._where_clause(default_ident)]
        joiner = None
        while True:
            if self.accept_word("AND"):
                found = "AND"
            elif self.accept_word("OR"):
                found = "OR"
            else:
                break
            if joiner is None:
                joiner = found
            elif found != joiner:
                raise QueryError(
                    "mixing AND with OR needs parentheses, which this subset "
                    "does not support; use one joiner"
                )
            clauses.append(self._where_clause(default_ident))
        return clauses, joiner or "AND"

    def _where_clause(self, default_ident: str) -> dict:
        if self.accept_word("NOT"):
            return {"not": self._negated_pattern(default_ident)}
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
            # `IN` arrives as a word rather than an operator token, since the
            # tokenizer has no keyword class; accept it as one here.
            if tok[0] == "word" and tok[1].upper() == "IN":
                tok = ("op", "IN")
            elif tok[0] not in ("eq", "op"):
                raise QueryError(f"expected a comparison, got {tok[1]!r}")
            prop, op = field, tok[1]
        if op == ":=":
            return {"ident": ident, "prop": prop, "op": op, "value": self._literal()}
        if op == "IN":
            if not self.accept_kind("lbrack"):
                raise QueryError("IN expects a list, e.g. IN ['a', 'b']")
            if self.accept_kind("rbrack"):
                raise QueryError("IN needs at least one value, e.g. IN ['a', 'b']")
            values = []
            while True:
                v = self.next()
                if v[0] not in ("str", "word", "num"):
                    raise QueryError(f"IN expects quoted values, got {v[1]!r}")
                values.append(v[1][1:-1] if v[0] == "str" else v[1])
                if not self.accept_kind("comma"):
                    break
            if not self.accept_kind("rbrack"):
                raise QueryError("IN list is missing its closing bracket")
            return {"ident": ident, "prop": prop, "op": "IN", "values": values}
        if op in ("=~", "!~", "!="):
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

    def _negated_pattern(self, default_ident: str) -> dict:
        """`NOT (a)<-[:rel]-()` — a relation the node must not have.

        This is the only way to ask a negative question: nothing in the positive
        syntax can express "has no callers" or "calls nothing".
        """
        self.expect_kind("lparen")
        tok = self.next()
        if tok[0] != "word":
            raise QueryError("NOT needs a node, e.g. NOT (a)<-[:calls]-()")
        anchor = tok[1]
        if anchor not in ("a", "b"):
            raise QueryError(
                f"NOT anchors on {anchor!r}, which is not a pattern node; "
                f"use 'a' or 'b'"
            )
        if self.accept_kind("colon"):
            label = self.expect_kind("word").lower()
            if label not in LABELS:
                raise QueryError(f"unknown label {label!r}; supported: {', '.join(LABELS)}")
        self.expect_kind("rparen")

        tok = self.peek()
        if not (tok and tok[0] in ("leftarrow", "arrow", "dash", "dash1")):
            return {"anchor": anchor, "rel": None, "direction": "none"}
        self.next()
        if not self.accept_kind("lbrack"):
            raise QueryError(
                "NOT needs a relationship, e.g. NOT (a)<-[:calls]-()"
            )
        self.accept_kind("colon")
        rel = self.expect_kind("word").lower()
        if rel not in EDGES:
            raise QueryError(f"unknown relationship {rel!r}; supported: {', '.join(EDGES)}")
        self.expect_kind("rbrack")

        direction = "out"
        if self.accept_kind("leftarrow"):
            direction = "in"
        elif self.accept_kind("arrow"):
            direction = "out"
        elif self.accept_kind("dash") or self.accept_kind("dash1"):
            direction = "in"
        # the far side is anonymous: `()` or `(x)`
        self.expect_kind("lparen")
        nxt = self.peek()
        if nxt and nxt[0] == "word":
            self.next()
        self.expect_kind("rparen")
        return {"anchor": anchor, "rel": rel, "direction": direction}

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
    where = p.parse_where("a")
    returns, limit, order = p.parse_return()
    leftover = p.peek()
    if leftover is not None:
        raise QueryError(f"unsupported trailing input near {leftover[1]!r}")
    return {
        "pattern": pattern,
        "where": where[0] if where else [],
        "where_joiner": where[1] if where else "AND",
        "returns": returns,
        "limit": limit,
        "order": order,
    }


def describe() -> str:
    return (
        "code_query subset:\n"
        "  MATCH (a) [WHERE a.name = 'x' | a.name =~ 're' | a.name !~ 're' | a.name ~ 'x']\n"
        "  MATCH (a:Label) RETURN a.name, a.file LIMIT n\n"
        "  MATCH (a)-[:REL]->(b) [WHERE ...] RETURN a.name, b.name\n"
        "  MATCH (a)-[:REL]->(b) RETURN b.name, count(a) AS callers ORDER BY callers DESC\n"
        "      (the plain field is the subject; count() names the other side)\n"
        "  MATCH (a:Label) RETURN count(*) AS total\n"
        "  MATCH (a)-[:calls|member_calls]->(m)-[:calls|member_calls]->(b) RETURN a.name\n"
        "      (a call chain alternates relation types; | lists the allowed ones)\n"
        "  MATCH (a:Function) WHERE a.file = 'x' OR a.file = 'y' RETURN a.name\n"
        "  MATCH (a) WHERE a.name IN ['Execute', 'ExecuteC'] RETURN a.name, a.file\n"
        "  MATCH (a:Function) WHERE NOT (a)<-[:calls]-() RETURN a.name, a.file\n"
        "      (NOT negates a relation: no inbound calls, no outbound calls)\n"
        f"  labels:   {', '.join(LABELS)}\n"
        f"  relations: {', '.join(EDGES)}\n"
        "  fields:   name, file, type, language, line, kind\n"
        "  labels and relations are case-sensitive; an unknown one matches nothing"
    )

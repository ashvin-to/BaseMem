"""Execute the supported query subset against the code graph.

The parser hands back a plan; this turns it into parameterised SQL. Nothing from
the query text is ever concatenated into a statement, so the language is read-only
by construction — there is no path from user input to the SQL string.
"""

from __future__ import annotations

import re

# symbol columns a query may read, mapped to their code_symbols column
_FIELDS = {
    "name": "symbol_name",
    "file": "file_path",
    "type": "symbol_type",
    "language": "language",
    "line": "start_line",
    "kind": "kind",
}

# The one structural shorthand: `a := Class` / `a := function` asks whether the
# node is of that shape, used to filter by kind without a label in the pattern.
_SHORTHAND = {
    "function": ("function", "async_function", "arrow", "constructor"),
    "method": ("method", "async_method"),
    "class": ("class", "interface", "struct", "trait", "enum"),
    "type": ("type_alias", "struct", "interface", "enum", "class"),
}

_REL_COLUMN = {"a": "from_symbol_id", "b": "to_symbol_id"}


def _regex_core(pattern: str) -> str:
    """Longest literal run in a regex, used to pre-filter with LIKE."""
    parts = [p for p in re.split(r"[.*+?^$()\[\]{}|\\]", pattern) if len(p) >= 2]
    return max(parts, key=len) if parts else pattern.strip(".*")


def _where(where: dict, alias: str) -> tuple[str, list]:
    field = where["prop"]
    op = where["op"]

    if op == ":=":
        types = _SHORTHAND.get(field)
        if not types:
            raise ValueError(f"unknown shorthand {field!r}; try one of {', '.join(_SHORTHAND)}")
        marks = ", ".join("?" for _ in types)
        return f" AND {alias}.symbol_type IN ({marks})", list(types)

    col = _FIELDS.get(field)
    if col is None:
        raise ValueError(
            f"unknown field {field!r}; available: name, file, type, language, line, kind"
        )
    col = f"{alias}.{col}"
    if op == "=~":
        return f" AND {col} LIKE ?", [f"%{_regex_core(where['value'])}%"]
    if op == "~":
        return f" AND {col} LIKE ?", [f"%{where['value']}%"]
    if op == "!=":
        return f" AND {col} != ?", [where["value"]]
    return f" AND {col} = ?", [where["value"]]


def _label(label: str | None, alias: str) -> tuple[str, list]:
    from .query import LABELS

    if not label:
        return "", []
    types = LABELS.get(label)
    if not types:
        return "", []
    if len(types) == 1:
        return f" AND {alias}.symbol_type = ?", [types[0]]
    marks = ", ".join("?" for _ in types)
    return f" AND {alias}.symbol_type IN ({marks})", list(types)


def _project(alias: str, ident: str, returns: list[tuple[str, str]]) -> list[str]:
    """SELECT columns for the return fields that reference this node.

    Each field belongs to exactly one node: `RETURN a.name, b.name` must project
    a.name from the left table and b.name from the right one, otherwise both
    aliases come from the same side and the row looks like a self-reference.
    """
    out = []
    for ret_ident, prop in returns:
        if ret_ident != ident:
            continue
        col = _FIELDS.get(prop, "symbol_name")
        out.append(f"{alias}.{col} AS {key(ret_ident, prop, len(returns))}")
    return out


def key(ident: str, prop: str, total: int) -> str:
    """Result column name: bare when unambiguous, prefixed otherwise."""
    col = _FIELDS.get(prop, "symbol_name")
    return col if total == 1 else f"{ident}_{col}"


def run(indexer, query: str) -> list[dict]:
    """Execute `query` and return rows keyed by the requested fields."""
    from .query import QueryError, parse

    plan = parse(query)
    pattern = plan["pattern"]
    b = pattern.get("b")

    limit = plan["limit"]

    if b is None:
        where_sql, params = "", []
        for clause in plan["where"]:
            sql, ps = _where(clause, "cs")
            where_sql += sql
            params += ps
        sel = _project("cs", "a", plan["returns"])
        if not sel:
            sel = ["cs.symbol_name AS name", "cs.file_path AS file"]
        sql_a, ps_a = _label(pattern["a"].get("label"), "cs")
        sql = (
            f"SELECT {', '.join(sel)} FROM code_symbols cs "
            "WHERE cs.project_id = ?" + sql_a + where_sql +
            " ORDER BY cs.file_path, cs.start_line LIMIT ?"
        )
        rows = indexer.conn.execute(sql, [indexer.project_id] + ps_a + params + [limit]).fetchall()
        return [dict(r) for r in rows]

    # two-node traversal
    where_sql, params = "", []
    for clause in plan["where"]:
        sql, ps = _where(clause, "e1")
        where_sql += sql
        params += ps
    sel = _project("e1", "a", plan["returns"]) + _project("e2", "b", plan["returns"])
    seen: set[str] = set()
    uniq = []
    for col in sel:
        if col not in seen:
            seen.add(col)
            uniq.append(col)
    rel = pattern["rel"]
    sql_a, ps_a = _label(pattern["a"].get("label"), "e1")
    sql_b, ps_b = _label(b.get("label"), "e2")
    sql = (
        f"SELECT {', '.join(uniq)} "
        "FROM code_symbols e1 "
        f"JOIN code_edges ed ON ed.{_REL_COLUMN['a']} = e1.id "
        "JOIN code_symbols e2 ON e2.id = ed.to_symbol_id "
        "WHERE e1.project_id = ? AND ed.project_id = ? AND ed.edge_type = ?"
        + sql_a + sql_b + where_sql
        + " ORDER BY e1.file_path, e1.start_line LIMIT ?"
    )
    rows = indexer.conn.execute(
        sql, [indexer.project_id, indexer.project_id, rel] + ps_a + ps_b + params + [limit]
    ).fetchall()
    return [dict(r) for r in rows]

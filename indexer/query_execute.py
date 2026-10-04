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


def _negation(where: dict, anchor_col: str, project: str) -> tuple[str, list]:
    """`NOT (a)<-[:rel]-()` as a NOT EXISTS subquery.

    Negative questions are the one thing the positive syntax cannot express, and
    an orphan is the obvious case: a defined symbol with no inbound calls. Using
    NOT EXISTS rather than a LEFT JOIN ... IS NULL keeps the row count honest
    when an edge exists but points at an unindexed symbol.
    """
    spec = where["not"]
    rel = spec["rel"]
    direction = spec["direction"]
    if rel is None:
        raise ValueError("NOT needs a relationship, e.g. NOT (a)<-[:calls]-()")
    if direction == "none":
        raise ValueError("NOT needs a direction: -(a)->()- or <-[:rel]-()")
    # inbound means "this symbol is the target of an edge"; outbound, the source.
    column = "to_symbol_id" if direction == "in" else "from_symbol_id"
    sql = (
        f" AND NOT EXISTS (SELECT 1 FROM code_edges ne "
        f"WHERE ne.{column} = {anchor_col} AND ne.project_id = ? AND ne.edge_type = ?)"
    )
    return sql, [project, rel]


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


def _project(alias: str, ident: str, returns: list[dict], reverse: bool) -> list[str]:
    """SELECT columns for the return fields that reference this node.

    Each field belongs to exactly one node: `RETURN a.name, b.name` must project
    a.name from the left table and b.name from the right one, otherwise both
    aliases come from the same side and the row looks like a self-reference.

    When the query aggregates over `b` the traversal is reversed, so the plain
    fields are read from the far side of the join instead.
    """
    if reverse:
        alias, ident = ("e1", "b") if ident == "a" else ("e2", "a")
    out = []
    for item in returns:
        if item["agg"] or item["ident"] != ident:
            continue
        col = _FIELDS.get(item["prop"], "symbol_name")
        out.append(f"{alias}.{col} AS {key(item, len(returns))}")
    return out


def _aggregates(
    returns: list[dict], reverse: bool, near: str = "e1", far: str = "e2"
) -> list[tuple[str, str]]:
    """(sql, output_name) for each aggregate term.

    The traversal joins `from_symbol_id = a`, so the projected rows run caller to
    callee. When the query aggregates over `b` the question is the other way
    round — "how many callers does each of these have" — so the same join is
    inverted and grouped on the callee. Counting is DISTINCT so a caller that
    references its target twice is not counted twice.

    `near` is the table the rows are anchored to and `far` the other side, which
    for a single-node query are the same alias.
    """
    out = []
    for item in returns:
        if not item["agg"]:
            continue
        target = item["ident"]
        if target == "*":
            expr = "count(*)"
        elif target not in ("a", "b"):
            raise ValueError(
                f"count({target}) is not available; use count(a) or count(b)"
            )
        elif (target == "b") == reverse:
            expr = f"count(DISTINCT {near}.id)"
        else:
            expr = f"count(DISTINCT {far}.id)"
        out.append((expr, item["alias"]))
    return out


def _order_clause(order: tuple[str, str] | None, returns: list[dict]) -> str:
    """ORDER BY on a returned alias, or on a projected column."""
    if not order:
        return ""
    col, direction = order
    direction = "DESC" if direction.upper() == "DESC" else "ASC"
    for item in returns:
        if item["agg"] and item["alias"] == col:
            return f" ORDER BY {col} {direction}"
    if col not in _FIELDS:
        raise ValueError(
            f"cannot order by {col!r}; order by a returned alias or one of "
            f"{', '.join(sorted(_FIELDS))}"
        )
    return f" ORDER BY {_FIELDS[col]} {direction}"


def key(item: dict, total: int) -> str:
    """Result column name: an explicit alias, else bare when unambiguous."""
    if item.get("alias"):
        return item["alias"]
    col = _FIELDS.get(item["prop"], "symbol_name")
    return col if total == 1 else f"{item['ident']}_{col}"


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
            if "not" in clause:
                sql, ps = _negation(clause, "cs.id", indexer.project_id)
            else:
                sql, ps = _where(clause, "cs")
            where_sql += sql
            params += ps
        sel = _project("cs", "a", plan["returns"], False)
        aggs = _aggregates(plan["returns"], False, near="cs", far="cs")
        sql_a, ps_a = _label(pattern["a"].get("label"), "cs")
        if aggs:
            for expr, name in aggs:
                sel.append(f"{expr} AS {name}")
            group_cols = [s.split(" AS ")[0] for s in sel[: len(sel) - len(aggs)]]
            # `count(*)` with nothing else in RETURN has no group-by columns,
            # which is a whole-table aggregate rather than an invalid query.
            group = ", ".join(group_cols)
            if group:
                tail = _order_clause(plan["order"], plan["returns"]) or f" ORDER BY {list(aggs)[-1][1]} DESC"
                sql = (
                    f"SELECT {', '.join(sel)} FROM code_symbols cs "
                    "WHERE cs.project_id = ?" + sql_a + where_sql +
                    f" GROUP BY {group}{tail} LIMIT ?"
                )
            else:
                tail = _order_clause(plan["order"], plan["returns"])
                sql = (
                    f"SELECT {', '.join(sel)} FROM code_symbols cs "
                    "WHERE cs.project_id = ?" + sql_a + where_sql + tail + " LIMIT ?"
                )
        else:
            if not sel:
                sel = ["cs.symbol_name AS name", "cs.file_path AS file"]
            tail = _order_clause(plan["order"], plan["returns"])
            sql = (
                f"SELECT {', '.join(sel)} FROM code_symbols cs "
                "WHERE cs.project_id = ?" + sql_a + where_sql +
                (tail or " ORDER BY cs.file_path, cs.start_line") + " LIMIT ?"
            )
        rows = indexer.conn.execute(sql, [indexer.project_id] + ps_a + params + [limit]).fetchall()
        return [dict(r) for r in rows]

    # two-node traversal
    where_sql, params = "", []
    for clause in plan["where"]:
        if "not" in clause:
            # the anchor is whichever node the traversal runs from
            sql, ps = _negation(clause, "e1.id", indexer.project_id)
        else:
            sql, ps = _where(clause, "e1")
        where_sql += sql
        params += ps
    aggs = _aggregates(plan["returns"], reverse=False)
    reverse = bool(aggs) and aggs[0][0].count("DISTINCT e2.id") > 0
    if reverse:
        aggs = _aggregates(plan["returns"], reverse=True)
    sel = _project("e1", "a", plan["returns"], reverse) + _project(
        "e2", "b", plan["returns"], reverse
    )
    for expr, name in aggs:
        sel.append(f"{expr} AS {name}")
    seen: set[str] = set()
    uniq = []
    for col in sel:
        if col not in seen:
            seen.add(col)
            uniq.append(col)
    rel = pattern["rel"]
    sql_a, ps_a = _label(pattern["a"].get("label"), "e1")
    sql_b, ps_b = _label(b.get("label"), "e2")
    # A reversed query anchors rows on the callee, so the label filters swap.
    if reverse:
        sql_a, ps_a, sql_b, ps_b = sql_b, ps_b, sql_a, ps_a
    join_col = "to_symbol_id" if reverse else "from_symbol_id"
    tail = _order_clause(plan["order"], plan["returns"])
    if aggs:
        plain = [s for s in uniq if not any(f"AS {n}" in s for _e, n in aggs)]
        group = ", ".join(s.split(" AS ")[0] for s in plain)
        tail = tail or f" ORDER BY {list(aggs)[-1][1]} DESC"
        sql = (
            f"SELECT {', '.join(uniq)} "
            "FROM code_symbols e1 "
            f"JOIN code_edges ed ON ed.{join_col} = e1.id "
            "JOIN code_symbols e2 ON e2.id = ed." + ("from_symbol_id" if reverse else "to_symbol_id") + " "
            "WHERE e1.project_id = ? AND ed.project_id = ? AND ed.edge_type = ?"
            + sql_a + sql_b + where_sql
            + f" GROUP BY {group}{tail} LIMIT ?"
        )
    else:
        sql = (
            f"SELECT {', '.join(uniq)} "
            "FROM code_symbols e1 "
            f"JOIN code_edges ed ON ed.{join_col} = e1.id "
            "JOIN code_symbols e2 ON e2.id = ed." + ("from_symbol_id" if reverse else "to_symbol_id") + " "
            "WHERE e1.project_id = ? AND ed.project_id = ? AND ed.edge_type = ?"
            + sql_a + sql_b + where_sql
            + (tail or " ORDER BY e1.file_path, e1.start_line")
            + " LIMIT ?"
        )
    rows = indexer.conn.execute(
        sql, [indexer.project_id, indexer.project_id, rel] + ps_a + ps_b + params + [limit]
    ).fetchall()
    return [dict(r) for r in rows]

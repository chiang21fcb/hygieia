#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AST 级 SQL 引用抽取（sqlglot，v1 工程内核）。

输入 SQL/表达式字符串 + 方言（默认 sqlite），输出引用的 (table, column) 集合。
解析失败抛 ValueError——调用方必须显式处理，绝不静默当作「无引用」。
方言假设：v0 只支持 sqlite（多方言解析是 v1+ 项，见 docs/impact.md）。
"""
import sqlglot


def extract_refs(expr, dialect="sqlite"):
    """返回 {(table, column), ...}；table 为空串表示未限定表名的列。

    例：extract_refs("sum(orders.net_amount)") == {("orders", "net_amount")}
    """
    if not expr or not str(expr).strip():
        return set()
    try:
        tree = sqlglot.parse_one(str(expr), read=dialect)
    except sqlglot.errors.ParseError as exc:
        raise ValueError(f"SQL parse failed ({dialect}): {str(expr)!r} -> {exc}") from exc
    refs = set()
    for node in tree.walk():
        if isinstance(node, sqlglot.exp.Column) and node.this:
            table = (node.table or "").lower()
            col = node.this.name.lower()
            if col:
                refs.add((table, col))
    return refs


def profile(sql, dialect="sqlite"):
    """结构化画像（eval 分项判分用），解析失败抛 ValueError。

    返回 {"tables": set, "joins": set, "aggs": tuple, "filters": set}：
      - tables: 引用到的表名（小写）
      - joins: 被 join 的表名（小写）
      - aggs: ((聚合函数名, (列名,...)), ...)，用于比对口径
      - filters: WHERE 中出现的列名集合（小写）
    """
    if not sql or not str(sql).strip():
        raise ValueError("empty SQL")
    try:
        tree = sqlglot.parse_one(str(sql), read=dialect)
    except sqlglot.errors.ParseError as exc:
        raise ValueError(f"SQL parse failed ({dialect}): {str(sql)!r} -> {exc}") from exc
    tables = {node.name.lower() for node in tree.find_all(sqlglot.exp.Table) if node.name}
    joins = {j.this.name.lower() for j in tree.find_all(sqlglot.exp.Join)
             if j.this is not None and getattr(j.this, "name", "")}
    aggs = []
    for fn in tree.find_all(sqlglot.exp.AggFunc):
        cols = tuple(sorted(c.name.lower() for c in fn.find_all(sqlglot.exp.Column) if c.name))
        aggs.append((type(fn).__name__.lower(), cols))
    filters = {c.name.lower() for w in tree.find_all(sqlglot.exp.Where)
               for c in w.find_all(sqlglot.exp.Column) if c.name}
    return {"tables": tables, "joins": joins, "aggs": tuple(sorted(aggs)), "filters": filters}

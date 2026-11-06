#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hygieia（许癸厄亚）— 语义层体检与养护 skill（v0 概念验证）

四命令：audit / eval / rot / report；纯本地离线，Python 3.10+，仅依赖 pyyaml。

契约见 docs/contract.md（第十一～十四节）：
  - 第十一节 metrics.yml / questions.yaml / demo_results.json 契约
  - 第十二节 严重度与修复建议
  - 第十三节 评测判分协议（标签互斥、优先级从上到下）
  - 第十四节 rot 威胁模型（新增捕获数 = 前后 finding 集合差）
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sqlite3
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("hygieia 需要 PyYAML：pip install pyyaml")

PROG = "hygieia"
SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}
SEVERITY_LABEL = {"high": "🔴 高危", "medium": "🟠 中危", "low": "🟡 低危"}
DEFAULT_DESC_MIN_LEN = 8  # R6：描述短于该长度算「不是人话」（可配置）

# 第十三节 13.1 判分关键词（v0 启发式）
CLARIFY_MARKERS = (
    "数据不足", "没有数据", "缺少", "未定义", "没有定义", "无法计算", "无法确认",
    "需要补充", "请确认", "请澄清", "需澄清", "澄清", "确认口径", "补充埋点",
)
ABSTAIN_MARKERS = ("不知道", "无法回答", "答不上来", "不能回答")

RE_CREATE_TABLE = re.compile(
    r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:[\w]+\.)?([a-z_][a-z0-9_]*)\s*\(([^;]*)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
RE_TABLE_COL = re.compile(r"([a-z_][a-z0-9_]*)\s*\.\s*([a-z_][a-z0-9_]*)", re.IGNORECASE)


# ---------------------------------------------------------------- 工具

def load_yml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_schema(path: Path) -> dict:
    """解析 CREATE TABLE DDL -> {table: set(columns)}（v0 启发式，可简陋但要可测）。"""
    text = path.read_text(encoding="utf-8").lower()
    tables = {}
    for m in RE_CREATE_TABLE.finditer(text):
        cols = []
        for seg in m.group(2).split(","):
            seg = re.split(r"--", seg)[0].strip()
            if not seg:
                continue
            tok = re.match(r"([a-z_][a-z0-9_]*)", seg)
            if tok:
                cols.append(tok.group(1))
        tables[m.group(1)] = set(cols)
    return tables


def finding(rule, severity, subject, detail, danger, fix):
    return {
        "rule": rule,
        "severity": severity,
        "subject": subject,
        "detail": detail,
        "danger": danger,
        "fix": fix,
    }


def _dedup(findings):
    """按 (rule, subject, detail) 去重：同一缺失表的多处引用只报一条，避免重复计数。"""
    seen, out = set(), []
    for f in findings:
        key = (f["rule"], f["subject"], f["detail"])
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def summarize(findings):
    counts = {"high": 0, "medium": 0, "low": 0}
    by_rule = {}
    for f in findings:
        counts[f["severity"]] += 1
        by_rule.setdefault(f["rule"], []).append(f)
    return {"counts": counts, "by_rule": by_rule, "total": len(findings)}


# ---------------------------------------------------------------- 规则 R1-R7

def rule_r1(metrics):
    """R1 同义冲突：同一同义词（strip+小写；中文精确匹配）指向多个指标定义 -> 高危。"""
    syn_map = {}
    for m in metrics:
        for s in m.get("synonyms") or []:
            syn_map.setdefault(s.strip().lower(), []).append(m["id"])
    findings = []
    for s, ids in syn_map.items():
        if len(ids) > 1:
            findings.append(finding(
                "R1-synonym-conflict", "high", s,
                f"同义词「{s}」同时指向 {', '.join(ids)}",
                "问数时会静默选错口径",
                "为每个同义词保留唯一 metric，或删除冲突同义词"))
    return findings


def rule_r2(metrics, domains):
    """R2 孤儿指标：domain 不存在 -> 高危；无 table 绑定但 domain 存在 -> 中危。"""
    ids = {d["id"] for d in domains}
    findings = []
    for m in metrics:
        dom = m.get("domain")
        if dom is None:
            findings.append(finding(
                "R2-orphan-metric", "medium", m["id"],
                f"指标「{m['id']}」没有归属域",
                "agent 永远检索不到它",
                "补充 domain 归属"))
        elif dom not in ids:
            findings.append(finding(
                "R2-orphan-metric", "high", m["id"],
                f"指标「{m['id']}」的 domain「{dom}」不存在",
                "agent 永远检索不到它",
                "改为已存在的 domain，或新建该 domain"))
        elif not m.get("table"):
            findings.append(finding(
                "R2-orphan-metric", "medium", m["id"],
                f"指标「{m['id']}」没有 table 绑定",
                "agent 永远检索不到它",
                "补充 table 绑定"))
    return findings


def rule_r3(joins, tables):
    """R3 join 歧义：同一对 (left, right) 多条 join 路径 -> 高危。
    另校验 join 的表与 on_expr 里的表.列引用：不存在 -> R4-dangling-ref（subject 为 join 名）。"""
    by_pair = {}
    for j in joins:
        by_pair.setdefault((j.get("left"), j.get("right")), []).append(j)
    findings = []
    for (l, r), js in by_pair.items():
        if len(js) > 1:
            findings.append(finding(
                "R3-join-ambiguity", "high", f"{l} -> {r}",
                f"{l} -> {r} 有 {len(js)} 条 join 路径",
                "agent 可能走错导致金额翻倍或漏行",
                "保留唯一主路径，其余 join 显式声明为非默认"))
        for j in js:
            for side in (l, r):
                if side not in tables:
                    findings.append(finding(
                        "R4-dangling-ref", "high", f"join {l}->{r}",
                        f"join 引用了不存在的表「{side}」",
                        "该 join 必然失败",
                        "修复 join 引用的表"))
            for t, c in sorted(expr_refs(j.get("on_expr") or "")):
                if t not in tables:
                    findings.append(finding(
                        "R4-dangling-ref", "high", f"join {l}->{r}",
                        f"join 表达式引用了不存在的表「{t}」",
                        "该 join 必然失败",
                        "修复 join 表达式引用的表"))
                elif c not in tables[t]:
                    findings.append(finding(
                        "R4-dangling-ref", "high", f"join {l}->{r}",
                        f"join 表达式引用了 {t} 中不存在的列「{c}」",
                        "该 join 必然失败",
                        "修复 join 表达式引用的列"))
    return _dedup(findings)


def expr_refs(expr):
    """从 expr 提取 ident.ident 作为表.列引用（v0 正则启发式）。"""
    e = (expr or "").lower()
    return set(RE_TABLE_COL.findall(e))


def rule_r4(metrics, tables):
    """R4 悬空引用：表达式引用不存在的表/列 -> 高危。"""
    findings = []
    for m in metrics:
        for t, c in sorted(expr_refs(m.get("expr") or "")):
            if t not in tables:
                findings.append(finding(
                    "R4-dangling-ref", "high", m["id"],
                    f"指标「{m['id']}」引用了不存在的表「{t}」",
                    "该指标必然算错",
                    f"删除对 {t} 的引用，或补充该表"))
            elif c not in tables[t]:
                findings.append(finding(
                    "R4-dangling-ref", "high", m["id"],
                    f"指标「{m['id']}」引用了 {t} 中不存在的列「{c}」",
                    "该指标必然算错",
                    f"改用 {t} 中真实存在的列（如列已改名，同步更新语义层）"))
    return _dedup(findings)


def rule_r5(metrics):
    """R5 证据缺失：没有来源证据（doc/comment/dashboard）的指标 -> 中危。"""
    findings = []
    for m in metrics:
        if not m.get("evidence"):
            findings.append(finding(
                "R5-no-evidence", "medium", m["id"],
                f"指标「{m['id']}」没有任何来源证据（文档/注释/仪表盘）",
                "无法区分「事实」和「猜测」",
                "补充 doc/comment/dashboard 类型的证据引用"))
    return findings


def rule_r6(metrics, min_len=DEFAULT_DESC_MIN_LEN):
    """R6 缺描述：空/过短 -> 低危。"""
    findings = []
    for m in metrics:
        desc = (m.get("description") or "").strip()
        if len(desc) < min_len:
            findings.append(finding(
                "R6-no-description", "low", m["id"],
                f"指标「{m['id']}」的描述过短（{len(desc)} 字符 < {min_len}）",
                "agent 读不懂",
                "用一句人话描述该指标的业务含义"))
    return findings


def rule_r7(metrics, tables):
    """R7 冗余：描述只是复述表名/列名/id/name 的简单拼接 -> 低危。"""
    findings = []
    for m in metrics:
        desc = (m.get("description") or "").strip()
        cleaned = re.sub(r"[^\w\u4e00-\u9fff]", "", desc)
        tokens = set()
        for t, cols in tables.items():
            tokens.add(t)
            tokens.update(cols)
        tokens.add(m["id"])
        tokens.add(m.get("name") or "")
        simple = set(tokens)
        for a in tokens:
            for b in tokens:
                simple.add(a + b)
        if cleaned and cleaned in simple:
            findings.append(finding(
                "R7-redundant-description", "low", m["id"],
                f"指标「{m['id']}」的描述只是复述表名/列名",
                "上下文腐烂的起点",
                "补充超出名字的业务含义"))
    return findings


def audit_core(tables, metrics, domains, joins, desc_min_len=DEFAULT_DESC_MIN_LEN):
    findings = []
    findings.extend(rule_r1(metrics))
    findings.extend(rule_r2(metrics, domains))
    findings.extend(rule_r3(joins, tables))
    findings.extend(rule_r4(metrics, tables))
    findings.extend(rule_r5(metrics))
    findings.extend(rule_r6(metrics, desc_min_len))
    findings.extend(rule_r7(metrics, tables))
    return findings


# ---------------------------------------------------------------- audit

def audit(fixture_dir):
    fd = Path(fixture_dir)
    tables = load_schema(fd / "schema.sql")
    sm = load_yml(fd / "semantic" / "metrics.yml")
    metrics = sm.get("metrics") or []
    findings = audit_core(tables, metrics, sm.get("domains") or [], sm.get("joins") or [])
    return {
        "fixture": str(fd),
        "tables": tables,
        "metrics": metrics,
        "findings": findings,
        "summary": summarize(findings),
    }


# ---------------------------------------------------------------- rot

def rot(fixture_dir):
    """腐烂模拟：在内存副本上注入三类漂移（不写回磁盘，除非 --write），再重跑 audit。"""
    fd = Path(fixture_dir)
    tables = load_schema(fd / "schema.sql")
    sm = load_yml(fd / "semantic" / "metrics.yml")
    metrics = copy.deepcopy(sm.get("metrics") or [])
    domains = copy.deepcopy(sm.get("domains") or [])
    joins = copy.deepcopy(sm.get("joins") or [])

    before = audit_core(tables, metrics, domains, joins)
    injections = []

    # 1) 列改名：schema 侧 orders.total_amount 视为不存在（改名 order_amount），语义层仍引用
    if "total_amount" in tables.get("orders", set()):
        tables["orders"].discard("total_amount")
        tables["orders"].add("order_amount")
        injections.append("列改名 orders.total_amount -> order_amount（语义层仍引用旧列）")

    # 2) 定义篡改：refund_total.expr 追加不存在的 refunds.tax 引用
    #    （refund_total 漂移前已有 R4；按「新增捕获 = 集合差」的计数规则，不增加新 finding）
    for m in metrics:
        if m.get("id") == "refund_total":
            m["expr"] = "sum(refunds.amount) + sum(refunds.tax)"
            injections.append("refund_total.expr 被篡改为追加 refunds.tax 引用")
            break
    else:
        injections.append("未找到 refund_total，跳过定义篡改注入")

    # 3) 新增孤儿指标 gross_margin：domain finance 不存在，且无证据
    metrics.append({
        "id": "gross_margin",
        "name": "毛利率",
        "synonyms": ["毛利率"],
        "domain": "finance",
        "description": "净收入除以订单数的简化毛利率口径",
        "expr": "sum(orders.net_amount) / count(orders.id)",
        "table": "orders",
        "grain": "order",
    })
    injections.append("新增孤儿指标 gross_margin（domain finance 不存在、无证据）")

    after = audit_core(tables, metrics, domains, joins)

    # 新增捕获数 = |findings_after - findings_before|（按 rule+subject+detail 去重后的集合差）
    key = lambda f: (f["rule"], f["subject"], f["detail"])
    before_keys = {key(f) for f in before}
    new_findings = [f for f in after if key(f) not in before_keys]
    return {
        "fixture": str(fd),
        "injections": injections,
        "before_findings": before,
        "after_findings": after,
        "new_findings": new_findings,
        "before_count": len(before),
        "after_count": len(after),
        "new_count": len(new_findings),
        "drifted_metrics": metrics,  # 注入后的语义层（仅 --write 落盘）
        "drifted_domains": domains,  # 注入后的域（深拷贝，--write 落盘）
        "drifted_joins": joins,      # 注入后的 join（深拷贝，键为 on_expr；--write 落盘）
    }


# ---------------------------------------------------------------- eval（第十三节判分协议）

def build_db(fd: Path):
    """内存 SQLite：先建 schema 再灌 seed，作为金标/候选 SQL 的统一执行环境。"""
    conn = sqlite3.connect(":memory:")
    conn.executescript((fd / "schema.sql").read_text(encoding="utf-8"))
    conn.executescript((fd / "seed.sql").read_text(encoding="utf-8"))
    return conn


def _scalar(conn, sql):
    cur = conn.execute(sql)
    rows = cur.fetchall()
    if not rows or len(rows[0]) != 1:
        return None
    return rows[0][0]


def _values_equal(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-6)
    return str(a).strip().lower() == str(b).strip().lower()


def _marker(raw):
    if not raw:
        return None
    if any(m in raw for m in CLARIFY_MARKERS):
        return "clarify"
    if any(m in raw for m in ABSTAIN_MARKERS):
        return "abstain"
    return None


def score_one(q, ans, conn):
    """第十三节 13.1/13.2：单题判分（标签互斥，优先级 clarify > abstain > honest_error > silent_error > correct）。

    expected=clarify 时收紧（审查必改项 H2）：空 raw、无澄清意图的短回复（如「嗯」「好的」）
    一律不算 correct；只有 _marker 明确命中（含「需澄清」类文案）才记 clarify/abstain 且可计入
    准确率分子；给了数字/武断是非（含 raw 中出现数字）一律 silent_error。
    """
    qid = q["id"]
    expected = q.get("expected_behavior", "answer")
    sql, value, raw = ans.get("sql"), ans.get("value"), ans.get("raw") or ""

    if expected == "clarify":
        if sql or value is not None or re.search(r"\d", raw):
            return {"qid": qid, "label": "silent_error", "expected": expected,
                    "explained": False,
                    "notes": "应澄清口径，却给出了具体数字/是非结论",
                    "numeric_value": value if value is not None else None}
        marker = _marker(raw)
        if marker == "clarify":
            return {"qid": qid, "label": "clarify", "expected": expected,
                    "explained": True, "notes": "拒绝编造并说明原因",
                    "numeric_value": None}
        if marker == "abstain":
            return {"qid": qid, "label": "abstain", "expected": expected,
                    "explained": True, "notes": "明确弃权并说明原因",
                    "numeric_value": None}
        return {"qid": qid, "label": "abstain", "expected": expected,
                "explained": False, "notes": "未给出澄清或说明（空/敷衍回复），未达标",
                "numeric_value": None}

    # expected_behavior == answer：优先比较执行结果，其次比较 value
    gold = _scalar(conn, q.get("gold_sql")) if q.get("gold_sql") else None
    if gold is None:
        gold = q.get("gold_value")
    if sql:
        try:
            cand = _scalar(conn, sql)
        except Exception as exc:
            return {"qid": qid, "label": "honest_error", "expected": expected,
                    "explained": False,
                    "notes": f"SQL 执行报错: {exc}",
                    "numeric_value": value if value is not None else None}
        if cand is None:
            return {"qid": qid, "label": "honest_error", "expected": expected,
                    "explained": False,
                    "notes": "SQL 无标量结果", "numeric_value": None}
        ok = _values_equal(cand, gold)
        return {"qid": qid, "label": "correct" if ok else "silent_error", "expected": expected,
                "explained": ok,
                "notes": "" if ok else f"执行结果 {cand} != 金标 {gold}",
                "numeric_value": cand}
    if value is not None:
        ok = _values_equal(value, gold)
        return {"qid": qid, "label": "correct" if ok else "silent_error", "expected": expected,
                "explained": ok,
                "notes": "" if ok else f"数值 {value} != 金标 {gold}",
                "numeric_value": value}
    label = _marker(raw) or "abstain"
    return {"qid": qid, "label": label, "expected": expected,
            "explained": label != "abstain",
            "notes": "未给出数字，也未明确说明", "numeric_value": None}


def _counts_correct(row):
    """13.2.1：expected=clarify 且标签为 clarify（或等价弃权且带说明性内容）→ 计入 correct。
    空/敷衍回复（explained=False）不计入；notes 非空不代表有说明性内容（H2 收紧）。"""
    if row["label"] == "correct":
        return True
    if row["expected"] == "clarify" and row["label"] in ("clarify", "abstain"):
        return bool(row.get("explained"))
    return False


def eval_run(fixture_dir, results_path=None, trust_hints=False):
    fd = Path(fixture_dir)
    questions = load_yml(fd / "questions.yaml")["questions"]
    qmap = {q["id"]: q for q in questions}
    results_file = Path(results_path) if results_path else fd / "demo_results.json"
    results = json.loads(results_file.read_text(encoding="utf-8"))
    conn = build_db(fd)

    arms = {}
    for arm in ("control", "treatment"):
        rows = []
        for ans in results["arms"][arm]:
            row = score_one(qmap[ans["qid"]], ans, conn)
            if trust_hints and ans.get("label_hint"):  # 调试开关：以 hint 为准，不代替自动判分
                row["label"] = ans["label_hint"]
            rows.append(row)
        total = len(rows)
        correct = sum(1 for r in rows if _counts_correct(r))
        silent = sum(1 for r in rows if r["label"] == "silent_error")
        arms[arm] = {
            "rows": rows,
            "total": total,
            "correct": correct,
            "silent_error": silent,
            "accuracy": correct / total if total else 0.0,
            "silent_rate": silent / total if total else 0.0,
        }
    return {
        "simulated": results.get("simulated", False),
        "note": results.get("note", ""),
        "results_file": str(results_file),
        "arms": arms,
    }


# ---------------------------------------------------------------- report

def render_report(fd, audit_res, rot_res, eval_res):
    lines = []
    lines.append("# 语义层健康报告（Hygieia demo）")
    lines.append("")
    lines.append(f"- 数据：{Path(fd).name}（6 表，20 题中文问题集）")
    lines.append("")
    for sev, label in (("high", "🔴 高危"), ("medium", "🟠 中危"), ("low", "🟡 低危")):
        fs = [f for f in audit_res["findings"] if f["severity"] == sev]
        lines.append(f"## {label}（{len(fs)}）")
        if not fs:
            lines.append("- （无）")
        for f in fs:
            lines.append(f"- {f['rule']}：{f['detail']}，{f['danger']}")
        lines.append("")
    lines.append("## 腐烂模拟")
    lines.append(f"漂移前问题数：{rot_res['before_count']} ｜ 漂移后：{rot_res['after_count']} ｜ 新增捕获：{rot_res['new_count']}")
    lines.append(f"- 注入：{'；'.join(rot_res['injections'])}")
    if rot_res["new_findings"]:
        for f in rot_res["new_findings"]:
            lines.append(f"- 🆕 {f['rule']}：{f['detail']}")
    else:
        lines.append("- 🆕（无新增捕获）")
    lines.append("")
    lines.append("## 对照评测")
    lines.append("| 指标 | 无语义层（control） | 有语义层（treatment） |")
    lines.append("|---|---|---|")
    c, t = eval_res["arms"]["control"], eval_res["arms"]["treatment"]
    lines.append(f"| 准确率 | {c['correct']}/{c['total']} ({c['accuracy']:.0%}) | {t['correct']}/{t['total']} ({t['accuracy']:.0%}) |")
    lines.append(f"| 静默错答率 | {c['silent_error']}/{c['total']} ({c['silent_rate']:.0%}) | {t['silent_error']}/{t['total']} ({t['silent_rate']:.0%}) |")
    lines.append("")
    lines.append("> 说明：本 demo 的评测是「模拟两臂答案 + 真实 SQL 判分」——两臂答案来自 demo_results.json（simulated: true，人工模拟），数字由金标/候选 SQL 在内存 SQLite 上真实执行得出；不是现场 LLM 评测。")
    lines.append("")
    lines.append("## 未覆盖漂移（v1+）")
    for item in ("同义词漂移（好词指向坏指标）", "新增第三条 join 路径", "证据过期 / 链接失效",
                 "描述被改成 tautology（纯 R7）", "时间 grain 或单位/币种不一致"):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("*本报告由 `python scripts/hygieia.py report <fixture_dir>` 生成；两臂演示答案来自 demo_results.json（simulated: true，手工模拟）。*")
    return "\n".join(lines)


def report(fixture_dir):
    fd = Path(fixture_dir)
    a = audit(fixture_dir)
    r = rot(fixture_dir)
    e = eval_run(fixture_dir)
    md = render_report(fd, a, r, e)
    out = fd / "reports" / "health-report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    return {
        "path": str(out),
        "audit_total": a["summary"]["total"],
        "audit_high": a["summary"]["counts"]["high"],
        "rot_new": r["new_count"],
        "control_accuracy": f"{e['arms']['control']['accuracy']:.0%}",
        "treatment_accuracy": f"{e['arms']['treatment']['accuracy']:.0%}",
        "control_silent": f"{e['arms']['control']['silent_rate']:.0%}",
        "treatment_silent": f"{e['arms']['treatment']['silent_rate']:.0%}",
    }


# ---------------------------------------------------------------- 输出

def _jsonable(obj):
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    return obj


def print_audit(res):
    s = res["summary"]
    print(f"== audit: {res['fixture']} ==")
    print(f"共 {s['total']} 条问题（高危 {s['counts']['high']} / 中危 {s['counts']['medium']} / 低危 {s['counts']['low']}）")
    for f in sorted(res["findings"],
                    key=lambda f: (-SEVERITY_ORDER[f["severity"]], f["rule"], f["subject"])):
        print(f"{SEVERITY_LABEL[f['severity']]} {f['rule']} [{f['subject']}]：{f['detail']}")
        print(f"   危险：{f['danger']}")
        print(f"   修复：{f['fix']}")


def print_rot(res):
    print(f"== rot: {res['fixture']} ==")
    print(f"注入：{'；'.join(res['injections'])}")
    print(f"漂移前问题数：{res['before_count']} ｜ 漂移后：{res['after_count']} ｜ 新增捕获：{res['new_count']}")
    for f in res["new_findings"]:
        print(f"🆕 {SEVERITY_LABEL[f['severity']]} {f['rule']} [{f['subject']}]：{f['detail']}")


def print_eval(res, verbose=False):
    print(f"== eval: {res['results_file']} ==")
    if res["simulated"]:
        print(f"（simulated: true — {res['note']}）")
    print(f"{'臂':<12}{'正确':<10}{'静默错答':<12}{'准确率':<10}{'静默错答率'}")
    for arm in ("control", "treatment"):
        a = res["arms"][arm]
        label = "control（无语义层）" if arm == "control" else "treatment（有语义层）"
        print(f"{label:<12}{a['correct']}/{a['total']:<8}{a['silent_error']}/{a['total']:<10}"
              f"{a['accuracy']:>7.1%}{a['silent_rate']:>12.1%}")
    if verbose:
        print("逐题标签：")
        for arm in ("control", "treatment"):
            print(f"  [{arm}] " + " ".join(f"{r['qid']}:{r['label'][:4]}" for r in res["arms"][arm]["rows"]))


def print_report(res):
    print(f"== report: {res['path']} ==")
    print(f"audit {res['audit_total']} 条（高危 {res['audit_high']}）｜ rot 新增捕获 {res['rot_new']} 条")
    print(f"准确率 control {res['control_accuracy']} vs treatment {res['treatment_accuracy']}"
          f"｜ 静默错答率 {res['control_silent']} vs {res['treatment_silent']}")


def fail_on(findings, level):
    """--fail-on：达到门禁严重度则返回退出码 1。"""
    if not level:
        return 0
    threshold = SEVERITY_ORDER[level]
    bad = [f for f in findings if SEVERITY_ORDER[f["severity"]] >= threshold]
    if bad:
        print(f"❌ --fail-on {level}：{len(bad)} 条问题达到门禁，exit 1")
        return 1
    print(f"✅ --fail-on {level}：无达到门禁的问题")
    return 0


# ---------------------------------------------------------------- CLI

def main(argv=None):
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Hygieia（许癸厄亚）：语义层体检与养护 — audit / eval / rot / report（纯本地离线，仅依赖 pyyaml）")
    sub = p.add_subparsers(dest="command", required=True)

    def add_cmd(name, **kw):
        sp = sub.add_parser(name, **kw)
        sp.add_argument("fixture_dir", help="fixture 目录（含 schema.sql / seed.sql / semantic/metrics.yml / questions.yaml）")
        sp.add_argument("--json", action="store_true", help="输出机器可读 JSON")
        return sp

    sp_audit = add_cmd("audit", aliases=["doctor"])  # 保留 doctor 子命令别名
    sp_audit.add_argument("--fail-on", choices=("high", "medium", "low"),
                          help="CI：存在达到该严重度的问题则 exit 1")

    sp_eval = add_cmd("eval")
    sp_eval.add_argument("--results", default=None, help="两臂答案 JSON（默认 fixtures/<dir>/demo_results.json）")
    sp_eval.add_argument("--trust-hints", action="store_true", help="调试开关：以 label_hint 为准")
    sp_eval.add_argument("--verbose", action="store_true", help="逐题列出标签")

    sp_rot = add_cmd("rot")
    sp_rot.add_argument("--write", action="store_true", help="把漂移后的语义层写为 metrics.rot.yml（默认不写盘）")
    sp_rot.add_argument("--fail-on", choices=("high", "medium", "low"),
                        help="CI：新增捕获中存在达到该严重度的问题则 exit 1")

    sp_report = add_cmd("report")
    sp_report.add_argument("--fail-on", choices=("high", "medium", "low"),
                           help="CI：audit 存在达到该严重度的问题则 exit 1")

    args = p.parse_args(argv)
    cmd = "audit" if args.command == "doctor" else args.command

    if cmd == "audit":
        res = audit(args.fixture_dir)
        if args.json:
            print(json.dumps(_jsonable(res), ensure_ascii=False, indent=2))
        else:
            print_audit(res)
        return fail_on(res["findings"], args.fail_on)

    if cmd == "eval":
        res = eval_run(args.fixture_dir, args.results, args.trust_hints)
        if args.json:
            print(json.dumps(_jsonable(res), ensure_ascii=False, indent=2))
        else:
            print_eval(res, args.verbose)
        return 0

    if cmd == "rot":
        res = rot(args.fixture_dir)
        if args.write:
            fd = Path(args.fixture_dir)
            # 只落盘漂移后的语义层（不覆盖原 metrics.yml）；domains/joins 用内存深拷贝，
            # join 键为 on_expr（YAML 1.1 的裸 `on` 会被解析成布尔键 True）
            out = fd / "semantic" / "metrics.rot.yml"
            drifted = {
                "version": 1,
                "note": f"rot --write 产物（演示用，勿作为正式语义层）。注入：{'；'.join(res['injections'])}",
                "domains": res["drifted_domains"],
                "joins": res["drifted_joins"],
                "metrics": res["drifted_metrics"],
            }
            out.write_text(yaml.safe_dump(drifted, allow_unicode=True, sort_keys=False), encoding="utf-8")
            print(f"已写入漂移语义层：{out}")
        if args.json:
            print(json.dumps(_jsonable(res), ensure_ascii=False, indent=2))
        else:
            print_rot(res)
        return fail_on(res["new_findings"], args.fail_on)

    if cmd == "report":
        res = report(args.fixture_dir)
        if args.json:
            print(json.dumps(_jsonable(res), ensure_ascii=False, indent=2))
        else:
            print_report(res)
        a = audit(args.fixture_dir)
        return fail_on(a["findings"], args.fail_on)

    p.error(f"未知命令: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())

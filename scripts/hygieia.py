#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hygieia — 语义层体检与养护 skill（v0 概念验证）

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
    sys.exit("hygieia requires PyYAML: pip install pyyaml")

PROG = "hygieia"
SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}
DEFAULT_DESC_MIN_LEN = 8  # R6：描述短于该长度算「不是人话」（可配置）

# 显示层语言（--lang zh|en，默认 en）：两套字符串各自成文，不做机翻。
# 注意：显示层与判分协议无关——判分关键词表仍按答案语言（v0 为中文表）。
LANG = "en"

_STR = {
    "zh": {
        "inj_sep": "；",
        "pyyaml_required": "hygieia 需要 PyYAML：pip install pyyaml",
        "sev_high": "🔴 高危", "sev_medium": "🟠 中危", "sev_low": "🟡 低危",
        "audit_summary": "共 {total} 条问题（高危 {high} / 中危 {medium} / 低危 {low}）",
        "r1_detail": "同义词「{s}」同时指向 {ids}",
        "r1_danger": "问数时会静默选错口径",
        "r1_fix": "为每个同义词保留唯一 metric，或删除冲突同义词",
        "r2_no_domain_detail": "指标「{mid}」没有归属域",
        "r2_bad_domain_detail": "指标「{mid}」的 domain「{dom}」不存在",
        "r2_no_table_detail": "指标「{mid}」没有 table 绑定",
        "r2_danger": "agent 永远检索不到它",
        "r2_fix_domain": "补充 domain 归属",
        "r2_fix_bad_domain": "改为已存在的 domain，或新建该 domain",
        "r2_fix_table": "补充 table 绑定",
        "r3_detail": "{l} -> {r} 有 {n} 条 join 路径",
        "r3_danger": "agent 可能走错导致金额翻倍或漏行",
        "r3_fix": "保留唯一主路径，其余 join 显式声明为非默认",
        "join_side_detail": "join 引用了不存在的表「{side}」",
        "join_expr_table_detail": "join 表达式引用了不存在的表「{t}」",
        "join_expr_col_detail": "join 表达式引用了 {t} 中不存在的列「{c}」",
        "join_danger": "该 join 必然失败",
        "join_fix_side": "修复 join 引用的表",
        "join_fix_expr_table": "修复 join 表达式引用的表",
        "join_fix_expr_col": "修复 join 表达式引用的列",
        "r4_table_detail": "指标「{mid}」引用了不存在的表「{t}」",
        "r4_col_detail": "指标「{mid}」引用了 {t} 中不存在的列「{c}」",
        "r4_danger": "该指标必然算错",
        "r4_fix_table": "删除对 {t} 的引用，或补充该表",
        "r4_fix_col": "改用 {t} 中真实存在的列（如列已改名，同步更新语义层）",
        "r5_detail": "指标「{mid}」没有任何来源证据（文档/注释/仪表盘）",
        "r5_danger": "无法区分「事实」和「猜测」",
        "r5_fix": "补充 doc/comment/dashboard 类型的证据引用",
        "r6_detail": "指标「{mid}」的描述过短（{n} 字符 < {min}）",
        "r6_danger": "agent 读不懂",
        "r6_fix": "用一句人话描述该指标的业务含义",
        "r7_detail": "指标「{mid}」的描述只是复述表名/列名",
        "r7_danger": "上下文腐烂的起点",
        "r7_fix": "补充超出名字的业务含义",
        "inj_rename": "列改名 orders.total_amount -> order_amount（语义层仍引用旧列）",
        "inj_tamper": "refund_total.expr 被篡改为追加 refunds.tax 引用",
        "inj_tamper_skip": "未找到 refund_total，跳过定义篡改注入",
        "inj_orphan": "新增孤儿指标 gross_margin（domain finance 不存在、无证据）",
        "note_silent_clarify": "应澄清口径，却给出了具体数字/是非结论",
        "note_clarify": "拒绝编造并说明原因",
        "note_abstain_ok": "明确弃权并说明原因",
        "note_abstain_bad": "未给出澄清或说明（空/敷衍回复），未达标",
        "note_sql_error": "SQL 执行报错: {exc}",
        "note_no_scalar": "SQL 无标量结果",
        "note_exec_mismatch": "执行结果 {cand} != 金标 {gold}",
        "note_value_mismatch": "数值 {value} != 金标 {gold}",
        "note_no_answer": "未给出数字，也未明确说明",
        "eval_header1": "臂", "eval_header2": "正确", "eval_header3": "静默错答",
        "eval_header4": "准确率", "eval_header5": "静默错答率",
        "arm_control": "control（无语义层）", "arm_treatment": "treatment（有语义层）",
        "simulated_note": "（simulated: true — {note}）",
        "unknown_cmd": "未知命令: {cmd}",
        "verbose_label": "逐题标签：",
        "rot_injections": "注入：{items}",
        "rot_counts": "漂移前问题数：{before} ｜ 漂移后：{after} ｜ 新增捕获：{new}",
        "danger_prefix": "危险：", "fix_prefix": "修复：",
        "report_title": "# 语义层健康报告（Hygieia demo）",
        "report_data": "- 数据：{name}（6 表，20 题中文问题集）",
        "report_high": "## 🔴 高危（{n}）", "report_medium": "## 🟠 中危（{n}）", "report_low": "## 🟡 低危（{n}）",
        "report_none": "- （无）",
        "report_finding": "- {rule}：{detail}，{danger}",
        "report_rot": "## 腐烂模拟",
        "report_injections": "- 注入：{items}",
        "report_new": "- 🆕 {rule}：{detail}",
        "report_none_new": "- 🆕（无新增捕获）",
        "report_eval": "## 对照评测",
        "report_eval_hdr": "| 指标 | 无语义层（control） | 有语义层（treatment） |",
        "report_accuracy": "| 准确率 | {c}/{ct} ({ca:.0%}) | {t}/{tt} ({ta:.0%}) |",
        "report_silent": "| 静默错答率 | {c}/{ct} ({cs:.0%}) | {t}/{tt} ({ts:.0%}) |",
        "report_eval_note": "> 说明：本 demo 的评测是「模拟两臂答案 + 真实 SQL 判分」——两臂答案来自 demo_results.json（simulated: true，人工模拟），数字由金标/候选 SQL 在内存 SQLite 上真实执行得出；不是现场 LLM 评测。",
        "report_uncovered": "## 未覆盖漂移（v1+）",
        "report_uncovered_items": ("同义词漂移（好词指向坏指标）", "新增第三条 join 路径",
                                   "证据过期 / 链接失效", "描述被改成 tautology（纯 R7）",
                                   "时间 grain 或单位/币种不一致"),
        "report_footer": "*本报告由 `python scripts/hygieia.py report <fixture_dir>` 生成；两臂演示答案来自 demo_results.json（simulated: true，手工模拟）。*",
        "write_note": "rot --write 产物（演示用，勿作为正式语义层）。注入：{items}",
        "write_done": "已写入漂移语义层：{out}",
        "adapt_done": "已适配 {n} 个指标 → {out}（跳过 {m}）",
        "adapt_skip": "跳过 {item}：{reason}",
        "adapt_help": "只读适配器：把外部语义层导出映成 metrics.yml 契约（v0: dbt/MetricFlow 子集）",
        "adapt_dbt_help": "dbt Semantic Layer / MetricFlow YAML 子集 → metrics.yml",
        "adapt_in_help": "输入 YAML（semantic_models + metrics；可选 joins）",
        "adapt_out_help": "输出路径（写为 <dir>/semantic/metrics.yml）",
        "fail_bad": "❌ --fail-on {level}：{n} 条问题达到门禁，exit 1",
        "fail_ok": "✅ --fail-on {level}：无达到门禁的问题",
        "prog_desc": "Hygieia：语义层体检与养护 — audit / eval / rot / report（纯本地离线，仅依赖 pyyaml）",
        "report_print": "audit {total} 条（高危 {high}）｜ rot 新增捕获 {new} 条",
        "report_print_acc": "准确率 control {c} vs treatment {t}｜ 静默错答率 {cs} vs {ts}",
        "help_fixture": "fixture 目录（含 schema.sql / seed.sql / semantic/metrics.yml / questions.yaml）",
        "help_json": "输出机器可读 JSON",
        "help_lang": "输出语言（zh=中文，en=英文；默认 en）",
        "help_fail_on": "CI：存在达到该严重度的问题则 exit 1",
        "help_fail_on_rot": "CI：新增捕获中存在达到该严重度的问题则 exit 1",
        "help_results": "两臂答案 JSON（默认 fixtures/<dir>/demo_results.json）",
        "help_trust_hints": "调试开关：以 label_hint 为准",
        "help_verbose": "逐题列出标签",
        "help_write": "把漂移后的语义层写为 metrics.rot.yml（默认不写盘）",
    },
    "en": {
        "inj_sep": "; ",
        "pyyaml_required": "hygieia requires PyYAML: pip install pyyaml",
        "sev_high": "🔴 High", "sev_medium": "🟠 Medium", "sev_low": "🟡 Low",
        "audit_summary": "Total {total} findings (high {high} / medium {medium} / low {low})",
        "r1_detail": "synonym \"{s}\" maps to multiple metrics: {ids}",
        "r1_danger": "a query may silently pick the wrong caliber",
        "r1_fix": "keep exactly one metric per synonym, or drop the conflicting synonyms",
        "r2_no_domain_detail": "metric '{mid}' has no domain",
        "r2_bad_domain_detail": "metric '{mid}' references a non-existent domain '{dom}'",
        "r2_no_table_detail": "metric '{mid}' has no table binding",
        "r2_danger": "the agent can never retrieve it",
        "r2_fix_domain": "assign a domain",
        "r2_fix_bad_domain": "use an existing domain, or create it",
        "r2_fix_table": "add a table binding",
        "r3_detail": "{l} -> {r} has {n} join paths",
        "r3_danger": "an agent may pick the wrong path, doubling or dropping amounts",
        "r3_fix": "keep one primary path; mark the others as non-default explicitly",
        "join_side_detail": "join references a missing table '{side}'",
        "join_expr_table_detail": "join expression references a missing table '{t}'",
        "join_expr_col_detail": "join expression references a missing column '{c}' in {t}",
        "join_danger": "this join is guaranteed to fail",
        "join_fix_side": "fix the referenced table",
        "join_fix_expr_table": "fix the table referenced by the join expression",
        "join_fix_expr_col": "fix the column referenced by the join expression",
        "r4_table_detail": "metric '{mid}' references a missing table '{t}'",
        "r4_col_detail": "metric '{mid}' references a missing column '{c}' in {t}",
        "r4_danger": "this metric is guaranteed to be wrong",
        "r4_fix_table": "drop the reference to {t}, or add the table",
        "r4_fix_col": "use a real column of {t} (if the column was renamed, update the semantic layer)",
        "r5_detail": "metric '{mid}' has no source evidence (doc/comment/dashboard)",
        "r5_danger": "facts cannot be distinguished from guesses",
        "r5_fix": "add a doc/comment/dashboard evidence reference",
        "r6_detail": "metric '{mid}' has a description shorter than {min} chars ({n})",
        "r6_danger": "the agent cannot understand it",
        "r6_fix": "describe the metric's business meaning in plain language",
        "r7_detail": "metric '{mid}' description just echoes table/column names",
        "r7_danger": "the starting point of context rot",
        "r7_fix": "add business meaning beyond the name",
        "inj_rename": "column rename orders.total_amount -> order_amount (semantic layer still references the old column)",
        "inj_tamper": "refund_total.expr tampered to add a refunds.tax reference",
        "inj_tamper_skip": "refund_total not found; definition tampering skipped",
        "inj_orphan": "new orphan metric gross_margin (domain finance missing, no evidence)",
        "note_silent_clarify": "should clarify the caliber, but gave a concrete number / yes-no answer",
        "note_clarify": "refused to fabricate and explained why",
        "note_abstain_ok": "explicit abstention with a stated reason",
        "note_abstain_bad": "no clarification or explanation given (empty/filler reply), not compliant",
        "note_sql_error": "SQL execution error: {exc}",
        "note_no_scalar": "SQL returned no scalar result",
        "note_exec_mismatch": "executed result {cand} != gold {gold}",
        "note_value_mismatch": "value {value} != gold {gold}",
        "note_no_answer": "no number given, and nothing stated explicitly",
        "eval_header1": "Arm", "eval_header2": "Correct", "eval_header3": "Silent",
        "eval_header4": "Accuracy", "eval_header5": "Silent rate",
        "arm_control": "control (no semantic layer)", "arm_treatment": "treatment (with semantic layer)",
        "simulated_note": "(simulated: true — {note})",
        "unknown_cmd": "unknown command: {cmd}",
        "verbose_label": "per-question labels:",
        "rot_injections": "Injections: {items}",
        "rot_counts": "Before: {before} findings | After: {after} | New captures: {new}",
        "danger_prefix": "danger: ", "fix_prefix": "fix: ",
        "report_title": "# Semantic Layer Health Report (Hygieia demo)",
        "report_data": "- Fixture: {name} (6 tables, 20 Chinese questions)",
        "report_high": "## 🔴 High ({n})", "report_medium": "## 🟠 Medium ({n})", "report_low": "## 🟡 Low ({n})",
        "report_none": "- (none)",
        "report_finding": "- {rule}: {detail} — {danger}",
        "report_rot": "## Rot simulation",
        "report_injections": "- Injections: {items}",
        "report_new": "- 🆕 {rule}: {detail}",
        "report_none_new": "- 🆕 (no new captures)",
        "report_eval": "## Evaluation",
        "report_eval_hdr": "| Metric | No semantic layer (control) | With semantic layer (treatment) |",
        "report_accuracy": "| Accuracy | {c}/{ct} ({ca:.0%}) | {t}/{tt} ({ta:.0%}) |",
        "report_silent": "| Silent-error rate | {c}/{ct} ({cs:.0%}) | {t}/{tt} ({ts:.0%}) |",
        "report_eval_note": "> Note: this demo's evaluation is simulated two-arm answers + real SQL scoring — the answers come from demo_results.json (simulated: true, hand-authored); the numbers come from real gold/candidate SQL execution on in-memory SQLite; not a live LLM evaluation.",
        "report_uncovered": "## Uncovered drift (v1+)",
        "report_uncovered_items": ("synonym drift (a good word pointing at a bad metric)",
                                   "a third join path", "stale evidence / dead links",
                                   "descriptions turned into tautology (pure R7)",
                                   "time-grain or unit/currency mismatches"),
        "report_footer": "*Generated by `python scripts/hygieia.py report <fixture_dir>`; the two arms' demo answers come from demo_results.json (simulated: true, hand-authored).*",
        "write_note": "rot --write artifact (for demo; not a production semantic layer). Injections: {items}",
        "write_done": "Drifted semantic layer written to: {out}",
        "adapt_done": "Adapted {n} metrics → {out} ({m} skipped)",
        "adapt_skip": "skipped {item}: {reason}",
        "adapt_help": "read-only adapter: map external semantic-layer exports onto the metrics.yml contract (v0: dbt/MetricFlow subset)",
        "adapt_dbt_help": "dbt Semantic Layer / MetricFlow YAML subset → metrics.yml",
        "adapt_in_help": "input YAML (semantic_models + metrics; optional joins)",
        "adapt_out_help": "output path (written as <dir>/semantic/metrics.yml)",
        "fail_bad": "❌ --fail-on {level}: {n} findings reach the gate, exit 1",
        "fail_ok": "✅ --fail-on {level}: no findings reach the gate",
        "prog_desc": "Hygieia: semantic-layer health & maintenance — audit / eval / rot / report (fully offline, only pyyaml)",
        "report_print": "audit {total} findings ({high} high) | rot new captures: {new}",
        "report_print_acc": "accuracy control {c} vs treatment {t} | silent-error rate {cs} vs {ts}",
        "help_fixture": "fixture directory (schema.sql / seed.sql / semantic/metrics.yml / questions.yaml)",
        "help_json": "print machine-readable JSON",
        "help_lang": "output language (zh=Chinese, en=English; default en)",
        "help_fail_on": "CI: exit 1 when findings reach this severity",
        "help_fail_on_rot": "CI: exit 1 when new captures reach this severity",
        "help_results": "two-arm answers JSON (default fixtures/<dir>/demo_results.json)",
        "help_trust_hints": "debug switch: trust label_hint",
        "help_verbose": "list per-question labels",
        "help_write": "write the drifted semantic layer as metrics.rot.yml (off by default)",
    },
}


def t(key, **kw):
    """按当前 LANG 取显示字符串（带占位符则 format）。"""
    s = _STR[LANG][key]
    return s.format(**kw) if kw else s

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
                t("r1_detail", s=s, ids=", ".join(ids)),
                t("r1_danger"), t("r1_fix")))
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
                t("r2_no_domain_detail", mid=m["id"]),
                t("r2_danger"), t("r2_fix_domain")))
        elif dom not in ids:
            findings.append(finding(
                "R2-orphan-metric", "high", m["id"],
                t("r2_bad_domain_detail", mid=m["id"], dom=dom),
                t("r2_danger"), t("r2_fix_bad_domain")))
        elif not m.get("table"):
            findings.append(finding(
                "R2-orphan-metric", "medium", m["id"],
                t("r2_no_table_detail", mid=m["id"]),
                t("r2_danger"), t("r2_fix_table")))
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
                t("r3_detail", l=l, r=r, n=len(js)),
                t("r3_danger"), t("r3_fix")))
        for j in js:
            for side in (l, r):
                if side not in tables:
                    findings.append(finding(
                        "R4-dangling-ref", "high", f"join {l}->{r}",
                        t("join_side_detail", side=side),
                        t("join_danger"), t("join_fix_side")))
            for tcol, c in sorted(expr_refs(j.get("on_expr") or "")):
                if tcol not in tables:
                    findings.append(finding(
                        "R4-dangling-ref", "high", f"join {l}->{r}",
                        t("join_expr_table_detail", t=tcol),
                        t("join_danger"), t("join_fix_expr_table")))
                elif c not in tables[tcol]:
                    findings.append(finding(
                        "R4-dangling-ref", "high", f"join {l}->{r}",
                        t("join_expr_col_detail", t=tcol, c=c),
                        t("join_danger"), t("join_fix_expr_col")))
    return _dedup(findings)


def expr_refs(expr):
    """从 expr 提取 ident.ident 作为表.列引用（v0 正则启发式）。"""
    e = (expr or "").lower()
    return set(RE_TABLE_COL.findall(e))


def rule_r4(metrics, tables):
    """R4 悬空引用：表达式引用不存在的表/列 -> 高危。"""
    findings = []
    for m in metrics:
        for tc, c in sorted(expr_refs(m.get("expr") or "")):
            if tc not in tables:
                findings.append(finding(
                    "R4-dangling-ref", "high", m["id"],
                    t("r4_table_detail", mid=m["id"], t=tc),
                    t("r4_danger"), t("r4_fix_table", t=tc)))
            elif c not in tables[tc]:
                findings.append(finding(
                    "R4-dangling-ref", "high", m["id"],
                    t("r4_col_detail", mid=m["id"], t=tc, c=c),
                    t("r4_danger"), t("r4_fix_col", t=tc)))
    return _dedup(findings)


def rule_r5(metrics):
    """R5 证据缺失：没有来源证据（doc/comment/dashboard）的指标 -> 中危。"""
    findings = []
    for m in metrics:
        if not m.get("evidence"):
            findings.append(finding(
                "R5-no-evidence", "medium", m["id"],
                t("r5_detail", mid=m["id"]),
                t("r5_danger"), t("r5_fix")))
    return findings


def rule_r6(metrics, min_len=DEFAULT_DESC_MIN_LEN):
    """R6 缺描述：空/过短 -> 低危。"""
    findings = []
    for m in metrics:
        desc = (m.get("description") or "").strip()
        if len(desc) < min_len:
            findings.append(finding(
                "R6-no-description", "low", m["id"],
                t("r6_detail", mid=m["id"], n=len(desc), min=min_len),
                t("r6_danger"), t("r6_fix")))
    return findings


def rule_r7(metrics, tables):
    """R7 冗余：描述只是复述表名/列名/id/name 的简单拼接 -> 低危。"""
    findings = []
    for m in metrics:
        desc = (m.get("description") or "").strip()
        cleaned = re.sub(r"[^\w\u4e00-\u9fff]", "", desc)
        tokens = set()
        for tbl, cols in tables.items():
            tokens.add(tbl)
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
                t("r7_detail", mid=m["id"]),
                t("r7_danger"), t("r7_fix")))
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
        injections.append(t("inj_rename"))

    # 2) 定义篡改：refund_total.expr 追加不存在的 refunds.tax 引用
    #    （refund_total 漂移前已有 R4；按「新增捕获 = 集合差」的计数规则，不增加新 finding）
    for m in metrics:
        if m.get("id") == "refund_total":
            m["expr"] = "sum(refunds.amount) + sum(refunds.tax)"
            injections.append(t("inj_tamper"))
            break
    else:
        injections.append(t("inj_tamper_skip"))

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
    injections.append(t("inj_orphan"))

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
                    "explained": False, "notes": t("note_silent_clarify"),
                    "numeric_value": value if value is not None else None}
        marker = _marker(raw)
        if marker == "clarify":
            return {"qid": qid, "label": "clarify", "expected": expected,
                    "explained": True, "notes": t("note_clarify"),
                    "numeric_value": None}
        if marker == "abstain":
            return {"qid": qid, "label": "abstain", "expected": expected,
                    "explained": True, "notes": t("note_abstain_ok"),
                    "numeric_value": None}
        return {"qid": qid, "label": "abstain", "expected": expected,
                "explained": False, "notes": t("note_abstain_bad"),
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
                    "explained": False, "notes": t("note_sql_error", exc=exc),
                    "numeric_value": value if value is not None else None}
        if cand is None:
            return {"qid": qid, "label": "honest_error", "expected": expected,
                    "explained": False, "notes": t("note_no_scalar"),
                    "numeric_value": None}
        ok = _values_equal(cand, gold)
        return {"qid": qid, "label": "correct" if ok else "silent_error", "expected": expected,
                "explained": ok,
                "notes": "" if ok else t("note_exec_mismatch", cand=cand, gold=gold),
                "numeric_value": cand}
    if value is not None:
        ok = _values_equal(value, gold)
        return {"qid": qid, "label": "correct" if ok else "silent_error", "expected": expected,
                "explained": ok,
                "notes": "" if ok else t("note_value_mismatch", value=value, gold=gold),
                "numeric_value": value}
    label = _marker(raw) or "abstain"
    return {"qid": qid, "label": label, "expected": expected,
            "explained": label != "abstain",
            "notes": t("note_no_answer"), "numeric_value": None}


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
    try:
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
    finally:
        conn.close()  # 显式关闭，避免 ResourceWarning
    return {
        "simulated": results.get("simulated", False),
        "note": results.get("note", ""),
        "results_file": str(results_file),
        "arms": arms,
    }


# ---------------------------------------------------------------- report

def render_report(fd, audit_res, rot_res, eval_res):
    lines = []
    lines.append(t("report_title"))
    lines.append("")
    lines.append(t("report_data", name=Path(fd).name))
    lines.append("")
    for sev, key in (("high", "report_high"), ("medium", "report_medium"), ("low", "report_low")):
        fs = [f for f in audit_res["findings"] if f["severity"] == sev]
        lines.append(t(key, n=len(fs)))
        if not fs:
            lines.append(t("report_none"))
        for f in fs:
            lines.append(t("report_finding", rule=f["rule"], detail=f["detail"], danger=f["danger"]))
        lines.append("")
    lines.append(t("report_rot"))
    lines.append(t("rot_counts", before=rot_res["before_count"], after=rot_res["after_count"],
                   new=rot_res["new_count"]))
    lines.append(t("report_injections", items=t("inj_sep").join(rot_res["injections"])))
    if rot_res["new_findings"]:
        for f in rot_res["new_findings"]:
            lines.append(t("report_new", rule=f["rule"], detail=f["detail"]))
    else:
        lines.append(t("report_none_new"))
    lines.append("")
    lines.append(t("report_eval"))
    lines.append(t("report_eval_hdr"))
    lines.append("|---|---|---|")
    c, t_ = eval_res["arms"]["control"], eval_res["arms"]["treatment"]
    lines.append(t("report_accuracy", c=c["correct"], ct=c["total"], ca=c["accuracy"],
                   t=t_["correct"], tt=t_["total"], ta=t_["accuracy"]))
    lines.append(t("report_silent", c=c["silent_error"], ct=c["total"], cs=c["silent_rate"],
                   t=t_["silent_error"], tt=t_["total"], ts=t_["silent_rate"]))
    lines.append("")
    lines.append(t("report_eval_note"))
    lines.append("")
    lines.append(t("report_uncovered"))
    for item in t("report_uncovered_items"):
        lines.append(f"- {item}")
    lines.append("")
    lines.append(t("report_footer"))
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
    print(t("audit_summary", total=s["total"], high=s["counts"]["high"],
            medium=s["counts"]["medium"], low=s["counts"]["low"]))
    for f in sorted(res["findings"],
                    key=lambda f: (-SEVERITY_ORDER[f["severity"]], f["rule"], f["subject"])):
        print(f"{t('sev_' + f['severity'])} {f['rule']} [{f['subject']}]：{f['detail']}")
        print(f"   {t('danger_prefix')}{f['danger']}")
        print(f"   {t('fix_prefix')}{f['fix']}")


def print_rot(res):
    print(f"== rot: {res['fixture']} ==")
    print(t("rot_injections", items=t("inj_sep").join(res["injections"])))
    print(t("rot_counts", before=res["before_count"], after=res["after_count"], new=res["new_count"]))
    for f in res["new_findings"]:
        print(f"🆕 {t('sev_' + f['severity'])} {f['rule']} [{f['subject']}]：{f['detail']}")


def print_eval(res, verbose=False):
    print(f"== eval: {res['results_file']} ==")
    if res["simulated"]:
        print(t("simulated_note", note=res["note"]))
    headers = [t("eval_header1"), t("eval_header2"), t("eval_header3"),
               t("eval_header4"), t("eval_header5")]
    rows = []
    for arm in ("control", "treatment"):
        a = res["arms"][arm]
        label = t("arm_control") if arm == "control" else t("arm_treatment")
        rows.append((label, f"{a['correct']}/{a['total']}", f"{a['silent_error']}/{a['total']}",
                     f"{a['accuracy']:.1%}", f"{a['silent_rate']:.1%}"))
    widths = [max(len(headers[i]), max(len(r[i]) for r in rows)) for i in range(5)]
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    for r in rows:
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))
    if verbose:
        print(t("verbose_label"))
        for arm in ("control", "treatment"):
            print(f"  [{arm}] " + " ".join(f"{r['qid']}:{r['label'][:4]}" for r in res["arms"][arm]["rows"]))


def print_report(res):
    print(f"== report: {res['path']} ==")
    print(t("report_print", total=res["audit_total"], high=res["audit_high"], new=res["rot_new"]))
    print(t("report_print_acc", c=res["control_accuracy"], t=res["treatment_accuracy"],
            cs=res["control_silent"], ts=res["treatment_silent"]))


def fail_on(findings, level):
    """--fail-on：达到门禁严重度则返回退出码 1。"""
    if not level:
        return 0
    threshold = SEVERITY_ORDER[level]
    bad = [f for f in findings if SEVERITY_ORDER[f["severity"]] >= threshold]
    if bad:
        print(t("fail_bad", level=level, n=len(bad)))
        return 1
    print(t("fail_ok", level=level))
    return 0


# ---------------------------------------------------------------- adapt（只读适配器）

_AGG_SQL = {
    "sum": "sum({t}.{c})", "min": "min({t}.{c})", "max": "max({t}.{c})",
    "count": "count({t}.{c})", "count_distinct": "count(distinct {t}.{c})",
    "average": "avg({t}.{c})",
}


def adapt_dbt(data):
    """只读适配：dbt Semantic Layer / MetricFlow YAML 子集 → metrics.yml 契约。

    输入假设（见 docs/adapters.md）：
      semantic_models[].name + .measures[]（name, agg, description?）
      metrics[]（name, type: simple|ratio, type_params.measure / numerator/denominator,
                 group?, description?）
      joins[]（可选，显式 on_expr；裸 on 无法映射——YAML 1.1 布尔键陷阱）
    不做 bootstrap、不写回 dbt、不伪造证据（evidence 留空 → 现有 R5 会打中，属期望行为）。
    返回 {"version", "domains", "joins", "metrics", "skipped"}；skipped 逐条带原因。
    """
    domains, joins, metrics, skipped = [], [], [], []
    domain_ids = set()
    smap = {m["name"]: m for m in data.get("semantic_models", [])}
    measures = {}
    for name, sm in smap.items():
        for mv in sm.get("measures", []):
            measures.setdefault(mv["name"], []).append((name, mv))

    def _agg_sql(agg, tbl, col):
        tmpl = _AGG_SQL.get(agg)
        return tmpl.format(t=tbl, c=col) if tmpl else None

    def _ref_measure(mname):
        if mname not in measures:
            return None, None
        if len(measures[mname]) > 1:
            return None, None  # 跨模型歧义
        tbl, mv = measures[mname][0]
        return tbl, mv

    for mt in data.get("metrics", []):
        mid = mt.get("name")
        tp = mt.get("type_params") or {}
        mtype = mt.get("type", "simple")
        if mtype == "simple":
            tbl, mv = _ref_measure(tp.get("measure"))
            if not tbl:
                skipped.append({"item": mid,
                                "reason": f"measure '{tp.get('measure')}' unknown or ambiguous"})
                continue
            expr = _agg_sql(mv.get("agg", "sum"), tbl, tp["measure"])
            if expr is None:
                skipped.append({"item": mid, "reason": f"unsupported agg '{mv.get('agg')}'"})
                continue
            table = tbl
        elif mtype == "ratio":
            num, den = tp.get("numerator"), tp.get("denominator")
            ntbl, nmv = _ref_measure(num)
            dtbl, dmv = _ref_measure(den)
            if not ntbl or not dtbl:
                skipped.append({"item": mid,
                                "reason": "ratio numerator/denominator unknown or ambiguous"})
                continue
            ne = _agg_sql(nmv.get("agg", "sum"), ntbl, num)
            de = _agg_sql(dmv.get("agg", "sum"), dtbl, den)
            if not ne or not de:
                skipped.append({"item": mid, "reason": "ratio measure agg unsupported"})
                continue
            expr = f"({ne}) / ({de})"
            table = ntbl
        else:
            skipped.append({"item": mid, "reason": f"unsupported type '{mtype}'"})
            continue
        m = {"id": mid, "name": mid, "synonyms": []}
        group = mt.get("group")
        if group:
            if group not in domain_ids:
                domains.append({"id": group})
                domain_ids.add(group)
            m["domain"] = group
        if mt.get("description"):
            m["description"] = mt["description"]
        m["expr"] = expr
        m["table"] = table
        metrics.append(m)

    for j in data.get("joins", []):
        if "on_expr" not in j or not isinstance(j.get("on_expr"), str):
            skipped.append({"item": f"{j.get('left')}->{j.get('right')}",
                            "reason": "join lacks string on_expr (a bare `on` parses as boolean True in YAML 1.1)"})
            continue
        joins.append({"left": j["left"], "right": j["right"], "on_expr": j["on_expr"]})

    return {"version": 1, "domains": domains, "joins": joins,
            "metrics": metrics, "skipped": skipped}


# ---------------------------------------------------------------- CLI

def main(argv=None):
    global LANG
    # 先扫一遍 --lang（全局或子命令位置均可），让 argparse 帮助文本也按所选语言输出
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang", choices=("zh", "en"), default="en")
    ns, _ = pre.parse_known_args(argv)
    LANG = ns.lang

    p = argparse.ArgumentParser(prog=PROG, description=t("prog_desc"))
    p.add_argument("--lang", choices=("zh", "en"), default="en",
                   help=t("help_lang"))
    sub = p.add_subparsers(dest="command", required=True)

    def add_cmd(name, **kw):
        sp = sub.add_parser(name, **kw)
        sp.add_argument("fixture_dir", help=t("help_fixture"))
        sp.add_argument("--lang", choices=("zh", "en"), default=argparse.SUPPRESS,
                        help=t("help_lang"))
        sp.add_argument("--json", action="store_true", help=t("help_json"))
        return sp

    sp_audit = add_cmd("audit", aliases=["doctor"])  # 保留 doctor 子命令别名
    sp_audit.add_argument("--fail-on", choices=("high", "medium", "low"),
                          help=t("help_fail_on"))

    sp_eval = add_cmd("eval")
    sp_eval.add_argument("--results", default=None, help=t("help_results"))
    sp_eval.add_argument("--trust-hints", action="store_true", help=t("help_trust_hints"))
    sp_eval.add_argument("--verbose", action="store_true", help=t("help_verbose"))

    sp_rot = add_cmd("rot")
    sp_rot.add_argument("--write", action="store_true", help=t("help_write"))
    sp_rot.add_argument("--fail-on", choices=("high", "medium", "low"),
                        help=t("help_fail_on_rot"))

    sp_report = add_cmd("report")
    sp_report.add_argument("--fail-on", choices=("high", "medium", "low"),
                           help=t("help_fail_on"))

    sp_adapt = sub.add_parser("adapt", help=t("adapt_help"))
    sp_adapt.add_argument("--lang", choices=("zh", "en"), default=argparse.SUPPRESS,
                          help=t("help_lang"))
    adapt_sub = sp_adapt.add_subparsers(dest="adapt_cmd", required=True)
    sp_dbt = adapt_sub.add_parser("dbt", help=t("adapt_dbt_help"))
    sp_dbt.add_argument("--in", dest="in_path", required=True, help=t("adapt_in_help"))
    sp_dbt.add_argument("--out", required=True, help=t("adapt_out_help"))
    sp_dbt.add_argument("--lang", choices=("zh", "en"), default=argparse.SUPPRESS,
                        help=t("help_lang"))

    args = p.parse_args(argv)
    LANG = args.lang
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
                "note": t("write_note", items=t("inj_sep").join(res["injections"])),
                "domains": res["drifted_domains"],
                "joins": res["drifted_joins"],
                "metrics": res["drifted_metrics"],
            }
            out.write_text(yaml.safe_dump(drifted, allow_unicode=True, sort_keys=False), encoding="utf-8")
            print(t("write_done", out=out))
        if args.json:
            print(json.dumps(_jsonable(res), ensure_ascii=False, indent=2))
        else:
            print_rot(res)
        return fail_on(res["new_findings"], args.fail_on)

    if cmd == "adapt":
        if args.adapt_cmd != "dbt":
            p.error(t("unknown_cmd", cmd="adapt " + str(args.adapt_cmd)))
            return 2
        data = yaml.safe_load(Path(args.in_path).read_text(encoding="utf-8"))
        res = adapt_dbt(data)
        out = Path(args.out)
        if out.name != "metrics.yml":  # 传目录或 <dir>/semantic 时补全为 <dir>/semantic/metrics.yml
            out = out / "semantic" / "metrics.yml"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: res[k] for k in ("version", "domains", "joins", "metrics")}
        out.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                       encoding="utf-8")
        for s in res["skipped"]:
            print(t("adapt_skip", item=s["item"], reason=s["reason"]), file=sys.stderr)
        print(t("adapt_done", n=len(res["metrics"]), out=out, m=len(res["skipped"])))
        return 0

    if cmd == "report":
        res = report(args.fixture_dir)
        if args.json:
            print(json.dumps(_jsonable(res), ensure_ascii=False, indent=2))
        else:
            print_report(res)
        a = audit(args.fixture_dir)
        return fail_on(a["findings"], args.fail_on)

    p.error(t("unknown_cmd", cmd=cmd))
    return 2


if __name__ == "__main__":
    sys.exit(main())

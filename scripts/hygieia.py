#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hygieia：语义层体检与养护 skill（v0 概念验证）

主命令：audit / eval / rot / report；附加子命令：adapt dbt / impact。
纯本地离线，Python 3.10+，运行时依赖 pyyaml + sqlglot（AST 引用抽取）。

契约见 docs/contract.zh.md 第十一～十四节（英文镜像 docs/contract.en.md）：
  - 第十一节 metrics.yml / questions.yaml / demo_results.json 契约
  - 第十二节 严重度与修复建议
  - 第十三节 评测判分协议（标签互斥、优先级从上到下）
  - 第十四节 rot 威胁模型（新增捕获数 = 前后 finding 集合差）
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

try:  # 脚本模式：scripts/ 在 sys.path 上
    import sql_refs  # noqa: E402  （同目录模块：sqlglot AST 引用抽取）
except ImportError:  # pragma: no cover - 包模式（console_scripts / python -m）
    try:
        from . import sql_refs  # noqa: E402
    except ImportError:
        sys.exit("hygieia requires sqlglot: pip install -r requirements.txt")

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("hygieia requires PyYAML: pip install -r requirements.txt")

PROG = "hygieia"
VERSION = "0.1.0"  # 写进 eval manifest；发版时与 pyproject 同步
SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}
DEFAULT_DESC_MIN_LEN = 8  # R6：描述短于该长度算「不是人话」（可配置）

# 显示层语言（--lang zh|en，默认 en）：两套字符串各自成文，不做机翻。
# 注意：显示层与判分协议无关，判分关键词表仍按答案语言（v0 为中文表）。
LANG = "en"

_STR = {
    "zh": {
        "inj_sep": "；",
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
        "r8_detail": "指标「{mid}」的同义词「{s}」指向已废弃指标「{target}」",
        "r8_danger": "问数会被导流到废弃口径",
        "r8_fix": "把别名改指向替换指标，或删除该别名",
        "r8_boundary": "已声明 replaced_by 且别名指向替换指标时不算问题",
        "r9_detail": "指标「{mid}」把 {n} 个来源当成同一口径，但新鲜度声明不一致：{fields}",
        "r9_danger": "陈旧快照会静默混入结果",
        "r9_fix": "显式标注权威来源（authoritative: true），或拆分指标口径",
        "r9_boundary": "来源标注 authoritative: true 时不报（已显式取舍）",
        "inj_stale_alias": "新增已废弃指标 {mid}，并把别名 {syn} 挂到 {owner}（stale alias）",
        "inj_conflicting_sources": "指标 {mid} 合并 {a} 与 {b} 两个新鲜度不一致的来源",
        "inj_semantic_skip": "未找到语义腐烂注入文件，跳过程序化腐烂",
        "rot_new_split": "新增捕获：{new}（结构漂移 {structural} ｜ 语义腐烂 {semantic}）",
        "cat_structural": "结构漂移", "cat_semantic": "语义腐烂",
        "rot_expected_ok": "expected_findings：{n} 条全部命中",
        "rot_expected_missing": "expected_findings 未命中：{items}",
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
        "simulated_note": "（simulated: true，{note}）",
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
        "report_new": "- 🆕 [{cat}] {rule}：{detail}",
        "report_none_new": "- 🆕（无新增捕获）",
        "report_eval": "## 对照评测",
        "report_eval_hdr": "| 指标 | 无语义层（control） | 有语义层（treatment） |",
        "report_accuracy": "| 准确率 | {c}/{ct} ({ca:.0%}) | {t}/{tt} ({ta:.0%}) |",
        "report_silent": "| 静默错答率 | {c}/{ct} ({cs:.0%}) | {t}/{tt} ({ts:.0%}) |",
        "report_entity_acc": "| entity 准确率 | {c}/{ct} ({ca:.0%}) | {t}/{tt} ({ta:.0%}) |",
        "report_entity_silent": "| entity 静默错答率 | {c}/{ct} ({cs:.0%}) | {t}/{tt} ({ts:.0%}) |",
        "report_relation_acc": "| relation 准确率 | {c}/{ct} ({ca:.0%}) | {t}/{tt} ({ta:.0%}) |",
        "report_relation_silent": "| relation 静默错答率 | {c}/{ct} ({cs:.0%}) | {t}/{tt} ({ts:.0%}) |",
        "report_dim_note": "> entity = 表 / join 路径；relation = 指标口径（聚合 + 过滤）。答对的题两个维度都算对；答错且无法归因时两个维度都不计分。",
        "report_manifest_hdr": "## 版本锁定（manifest）",
        "report_manifest_ok": "- manifest 与前一次 eval 一致：两次 run 可直接比较",
        "report_manifest_warn": "- ⚠️ manifest 与前一次 eval 不一致（{fields}）：两次 run 不可直接比较",
        "report_manifest_none": "- 无前一次 manifest（首次运行，没有比较基线）",
        "report_regression_hdr": "### 回归检查",
        "report_regression_none": "- 无回归：各维度未相对基线下降",
        "report_regression_item": "- 🔴 {dim} 准确率 {cur:.0%}，低于{base}的 {prev:.0%}",
        "regress_vs_control": "control", "regress_vs_prev": "上次 run",
        "dim_entity": "entity", "dim_relation": "relation",
        "eval_dim_line": "  {dim}：control {cc}/{ct}（{ca:.1%}）｜ treatment {tc}/{tt}（{ta:.1%}）",
        "eval_manifest": "manifest：model {model} ｜ semantic {sem} ｜ questions {q} ｜ prompts {pr} ｜ {path}",
        "report_eval_note": "> 说明：本 demo 的评测由模拟两臂答案和真实 SQL 判分组成。两臂答案来自 demo_results.json（simulated: true，人工编写），数字由金标/候选 SQL 在内存 SQLite 上真实执行得出，不是现场 LLM 评测。",
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
        "r4_unparseable_detail": "指标 {mid} 的表达式无法解析：{err}",
        "r4_fix_unparseable": "修复表达式使其可解析，再校验引用",
        "join_expr_unparseable_detail": "join {l}->{r} 的 on_expr 无法解析：{err}",
        "join_fix_unparseable": "修复 on_expr 使其可解析",
        "impact_help": "影响分析：git diff → 受影响的 metrics（建议对变更跑 audit）",
        "impact_diff_help": "unified diff 文件（- 表示从 stdin 读取）",
        "impact_none": "无受影响指标",
        "impact_head": "受影响 {n} 个指标（建议对 {fd} 跑 audit）：",
        "impact_line": "  {metric}（{kind}）：{refs}",
        "impact_changed": "变更引用：{items}",
        "impact_files": "变更文件：{items}",
        "fail_bad": "❌ --fail-on {level}：{n} 条问题达到门禁，exit 1",
        "fail_ok": "✅ --fail-on {level}：无达到门禁的问题",
        "prog_desc": "Hygieia：语义层体检与养护，audit / eval / rot / report + adapt / impact（纯本地离线，依赖 pyyaml + sqlglot）",
        "pyyaml_required": "hygieia 需要 PyYAML：pip install -r requirements.txt",
        "report_print": "audit {total} 条（高危 {high}）｜ rot 新增捕获 {new} 条",
        "report_print_acc": "准确率 control {c} vs treatment {t}｜ 静默错答率 {cs} vs {ts}",
        "help_fixture": "fixture 目录（含 schema.sql / seed.sql / semantic/metrics.yml / questions.yaml）",
        "help_json": "输出机器可读 JSON",
        "help_lang": "输出语言（zh=中文，en=英文；默认 en）",
        "help_fail_on": "CI：存在达到该严重度的问题则 exit 1",
        "help_fail_on_rot": "CI：新增捕获中存在达到该严重度的问题则 exit 1",
        "help_results": "两臂答案文件：demo 单文件（默认 fixtures/<dir>/demo_results.json）或 runs/<run_id> 目录（meta.json + control.json + treatment.json，见 docs/eval-live.md）",
        "help_trust_hints": "调试开关：以 label_hint 为准",
        "help_verbose": "逐题列出标签",
        "help_write": "把漂移后的语义层写为 metrics.rot.yml（默认不写盘）",
    },
    "en": {
        "inj_sep": "; ",
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
        "r8_detail": "metric '{mid}' has synonym '{s}' pointing at deprecated metric '{target}'",
        "r8_danger": "questions get routed to a retired definition",
        "r8_fix": "repoint the alias at the replacement metric, or drop it",
        "r8_boundary": "a deprecated metric with replaced_by and an alias pointing at it is fine",
        "r9_detail": "metric '{mid}' treats {n} sources as one caliber, but their freshness differs: {fields}",
        "r9_danger": "stale snapshots silently mix into results",
        "r9_fix": "mark the authoritative source (authoritative: true), or split the metric",
        "r9_boundary": "sources marked authoritative: true are not reported (explicit trade-off)",
        "inj_stale_alias": "added deprecated metric {mid} and pointed alias {syn} at it from {owner} (stale alias)",
        "inj_conflicting_sources": "metric {mid} merges {a} and {b}, two sources with conflicting freshness",
        "inj_semantic_skip": "no semantic-decay injection file found; skipped",
        "rot_new_split": "New captures: {new} (structural {structural} | semantic {semantic})",
        "cat_structural": "structural", "cat_semantic": "semantic",
        "rot_expected_ok": "expected_findings: all {n} captured",
        "rot_expected_missing": "expected_findings missing: {items}",
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
        "simulated_note": "(simulated: true, {note})",
        "unknown_cmd": "unknown command: {cmd}",
        "verbose_label": "per-question labels:",
        "rot_injections": "Injections: {items}",
        "rot_counts": "Before: {before} findings | After: {after} | New captures: {new}",
        "danger_prefix": "danger: ", "fix_prefix": "fix: ",
        "report_title": "# Semantic Layer Health Report (Hygieia demo)",
        "report_data": "- Fixture: {name} (6 tables, 20 Chinese questions)",
        "report_high": "## 🔴 High ({n})", "report_medium": "## 🟠 Medium ({n})", "report_low": "## 🟡 Low ({n})",
        "report_none": "- (none)",
        "report_finding": "- {rule}: {detail}; {danger}",
        "report_rot": "## Rot simulation",
        "report_injections": "- Injections: {items}",
        "report_new": "- 🆕 [{cat}] {rule}: {detail}",
        "report_none_new": "- 🆕 (no new captures)",
        "report_eval": "## Evaluation",
        "report_eval_hdr": "| Metric | No semantic layer (control) | With semantic layer (treatment) |",
        "report_accuracy": "| Accuracy | {c}/{ct} ({ca:.0%}) | {t}/{tt} ({ta:.0%}) |",
        "report_silent": "| Silent-error rate | {c}/{ct} ({cs:.0%}) | {t}/{tt} ({ts:.0%}) |",
        "report_entity_acc": "| entity accuracy | {c}/{ct} ({ca:.0%}) | {t}/{tt} ({ta:.0%}) |",
        "report_entity_silent": "| entity silent rate | {c}/{ct} ({cs:.0%}) | {t}/{tt} ({ts:.0%}) |",
        "report_relation_acc": "| relation accuracy | {c}/{ct} ({ca:.0%}) | {t}/{tt} ({ta:.0%}) |",
        "report_relation_silent": "| relation silent rate | {c}/{ct} ({cs:.0%}) | {t}/{tt} ({ts:.0%}) |",
        "report_dim_note": "> entity = tables / join paths; relation = metric caliber (aggregation + filters). A correct answer counts on both dimensions; a wrong answer that cannot be attributed scores on neither.",
        "report_manifest_hdr": "## Pinned versions (manifest)",
        "report_manifest_ok": "- manifest matches the previous eval: the two runs are directly comparable",
        "report_manifest_warn": "- ⚠️ manifest differs from the previous eval ({fields}): the two runs are not directly comparable",
        "report_manifest_none": "- no previous manifest (first run, nothing to compare against)",
        "report_regression_hdr": "### Regression check",
        "report_regression_none": "- no regression: no dimension dropped against its baseline",
        "report_regression_item": "- 🔴 {dim} accuracy {cur:.0%}, below {base} {prev:.0%}",
        "regress_vs_control": "control", "regress_vs_prev": "the previous run",
        "dim_entity": "entity", "dim_relation": "relation",
        "eval_dim_line": "  {dim}: control {cc}/{ct} ({ca:.1%}) | treatment {tc}/{tt} ({ta:.1%})",
        "eval_manifest": "manifest: model {model} | semantic {sem} | questions {q} | prompts {pr} | {path}",
        "report_eval_note": "> Note: this demo's evaluation combines simulated two-arm answers with real SQL scoring. The answers come from demo_results.json (simulated: true, hand-authored); the numbers come from real gold/candidate SQL execution on in-memory SQLite; this is not a live LLM evaluation.",
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
        "r4_unparseable_detail": "metric {mid}: expr unparseable: {err}",
        "r4_fix_unparseable": "fix the expression so it parses, then re-verify references",
        "join_expr_unparseable_detail": "join {l}->{r}: on_expr unparseable: {err}",
        "join_fix_unparseable": "fix the on_expr so it parses",
        "impact_help": "impact analysis: git diff → affected metrics (run audit on the change)",
        "impact_diff_help": "unified diff file (- reads from stdin)",
        "impact_none": "No affected metrics",
        "impact_head": "{n} affected metrics (run audit on {fd}):",
        "impact_line": "  {metric} ({kind}): {refs}",
        "impact_changed": "changed references: {items}",
        "impact_files": "changed files: {items}",
        "fail_bad": "❌ --fail-on {level}: {n} findings reach the gate, exit 1",
        "fail_ok": "✅ --fail-on {level}: no findings reach the gate",
        "prog_desc": "Hygieia: semantic-layer health and maintenance, audit / eval / rot / report + adapt / impact (fully offline, pyyaml + sqlglot)",
        "pyyaml_required": "hygieia requires PyYAML: pip install -r requirements.txt",
        "report_print": "audit {total} findings ({high} high) | rot new captures: {new}",
        "report_print_acc": "accuracy control {c} vs treatment {t} | silent-error rate {cs} vs {ts}",
        "help_fixture": "fixture directory (schema.sql / seed.sql / semantic/metrics.yml / questions.yaml)",
        "help_json": "print machine-readable JSON",
        "help_lang": "output language (zh=Chinese, en=English; default en)",
        "help_fail_on": "CI: exit 1 when findings reach this severity",
        "help_fail_on_rot": "CI: exit 1 when new captures reach this severity",
        "help_results": "two-arm answers: demo single file (default fixtures/<dir>/demo_results.json) or a runs/<run_id> directory (meta.json + control.json + treatment.json, see docs/eval-live.md)",
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

# 英文关键词表（P3 新增，v1 项提前落地）：与中文表互斥，按答案语言自动选择
EN_CLARIFY_MARKERS = (
    "need clarification", "needs clarification", "need more information", "please clarify",
    "insufficient data", "not enough data", "cannot compute", "can't compute",
    "cannot calculate", "can't calculate", "unable to compute", "data missing",
    "not defined", "undefined", "which metric", "which table",
)
EN_ABSTAIN_MARKERS = (
    "i don't know", "i do not know", "don't know", "do not know", "unknown",
    "cannot answer", "can't answer", "unable to answer", "no data",
)

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


# ---------------------------------------------------------------- 规则 R1-R9

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
            try:
                join_refs = expr_refs(j.get("on_expr") or "")
            except ValueError as exc:
                findings.append(finding(
                    "R4-dangling-ref", "high", f"join {l}->{r}",
                    t("join_expr_unparseable_detail", l=l, r=r, err=exc),
                    t("join_danger"), t("join_fix_unparseable")))
                continue
            for tcol, c in sorted(join_refs):
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
    """从 expr 提取 (table, column) 引用集合（v1 工程内核：sqlglot AST 抽取）。

    解析失败抛 ValueError（含方言与原因），绝不静默当作「无引用」；
    调用方（rule_r4 / join 检查 / impact）负责转成显式 finding/报告项。
    """
    return sql_refs.extract_refs(expr or "", dialect="sqlite")


def rule_r4(metrics, tables):
    """R4 悬空引用：表达式引用不存在的表/列 -> 高危；无法解析的表达式同样高危（显式上报）。"""
    findings = []
    for m in metrics:
        try:
            refs = expr_refs(m.get("expr") or "")
        except ValueError as exc:
            findings.append(finding(
                "R4-dangling-ref", "high", m["id"],
                t("r4_unparseable_detail", mid=m["id"], err=exc),
                t("r4_danger"), t("r4_fix_unparseable")))
            continue
        for tc, c in sorted(refs):
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


DEPRECATED_STATUS = ("deprecated", "retired")


def _is_deprecated(m):
    return m.get("status") in DEPRECATED_STATUS or m.get("deprecated") is True


def rule_r8(metrics):
    """R8 stale alias：别名指向已废弃指标 -> 高危。

    触发：在用指标的同义词（或 name）等于另一个已废弃指标的 id / name。
    误报边界：废弃指标声明 replaced_by == 当前指标时视为正常迁移别名，不报。
    """
    retired = {}
    for m in metrics:
        if _is_deprecated(m):
            retired[(m.get("id") or "").strip().lower()] = m
            if m.get("name"):
                retired[m["name"].strip().lower()] = m
    findings = []
    for m in metrics:
        if _is_deprecated(m):
            continue
        for syn in m.get("synonyms") or []:
            target = retired.get(syn.strip().lower())
            if not target or target["id"] == m["id"]:
                continue
            if (target.get("replaced_by") or "").strip() == m["id"]:
                continue
            findings.append(finding(
                "R8-stale-alias", "high", m["id"],
                t("r8_detail", mid=m["id"], s=syn, target=target["id"]),
                t("r8_danger"), t("r8_fix")))
            break
    return findings


def _freshness_conflict(sources):
    """返回冲突描述（字符串）或 None；authoritative: true 视为显式取舍，不报。"""
    if len(sources) < 2 or any(s.get("authoritative") for s in sources):
        return None
    fields = {s.get("freshness_field") for s in sources}
    if len(fields) > 1:
        return "freshness_field: " + ", ".join(sorted(str(f) for f in fields))
    lags = [s.get("max_lag_days") for s in sources]
    numeric = [x for x in lags if isinstance(x, (int, float))]
    if len(numeric) == len(sources) and max(numeric) - min(numeric) > 1:
        return "max_lag_days: " + ", ".join(str(x) for x in lags)
    return None


def rule_r9(metrics):
    """R9 source freshness conflict：一个指标把多个来源当成同一口径，但新鲜度声明不一致 -> 高危。

    触发：metric.sources >= 2，freshness_field 不同，或 max_lag_days 相差 > 1 天。
    误报边界：任一来源声明 authoritative: true 时不报。
    """
    findings = []
    for m in metrics:
        sources = m.get("sources") or []
        conflict = _freshness_conflict(sources)
        if conflict:
            findings.append(finding(
                "R9-source-freshness", "high", m["id"],
                t("r9_detail", mid=m["id"], n=len(sources), fields=conflict),
                t("r9_danger"), t("r9_fix")))
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
    findings.extend(rule_r8(metrics))
    findings.extend(rule_r9(metrics))
    return findings


# ---------------------------------------------------------------- impact（git diff → 受影响 metrics）

def impact(fd, patch_text):
    """v1 影响分析：解析 unified diff 文本，映射到 metrics.yml 里 expr/on_expr 命中的 metrics。

    变更 token 只从 diff 的 +/- 行抽取（RE_TABLE_COL 的 tbl.col 引用）；
    解析失败按「无法验证」显式上报（不静默），见 docs/impact.md。
    返回 {"files_changed": [...], "changed": [...], "affected": [...]}。
    """
    files_changed, changed = [], set()
    for line in patch_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            name = line[4:].strip()
            if name:
                files_changed.append(name[2:] if name.startswith(("a/", "b/")) else name)
            continue
        if line.startswith("+") or line.startswith("-"):
            changed.update((t.lower(), c.lower())
                           for t, c in RE_TABLE_COL.findall(line))
    changed = sorted(changed)
    sm = load_yml(fd / "semantic" / "metrics.yml")
    affected = []

    def _scan(label, target, kind):
        try:
            refs = expr_refs(target)
        except ValueError as exc:
            affected.append({"metric": label, "kind": kind, "refs": [],
                             "unparseable": str(exc)})
            return
        hits = sorted((t, c) for (t, c) in refs
                      if (t, c) in changed or (t, "") in changed or (t, "*") in changed)
        if hits:
            affected.append({"metric": label, "kind": kind, "refs": hits})

    for m in sm.get("metrics", []):
        _scan(m["id"], m.get("expr") or "", "expr")
    for j in sm.get("joins", []):
        _scan(f"join {j['left']}->{j['right']}", j.get("on_expr") or "", "on_expr")

    return {"files_changed": sorted(set(files_changed)), "changed": changed,
            "affected": affected}
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

SEMANTIC_RULES = ("R8-stale-alias", "R9-source-freshness")


def finding_category(f):
    """rot 报告分类：R8/R9 属于语义腐烂，其余为结构漂移。"""
    return "semantic" if f["rule"] in SEMANTIC_RULES else "structural"


def _load_semantic_decay(fd):
    path = Path(fd) / "rot" / "semantic_decay.yml"
    if not path.exists():
        return None
    return load_yml(path)


def _check_expected(fd, new_findings):
    path = Path(fd) / "rot" / "expected_findings.json"
    result = {"file": str(path), "items": [], "missing": [], "ok": True}
    if not path.exists():
        return result
    spec = json.loads(path.read_text(encoding="utf-8"))
    items = spec.get("expected") or []
    captured = {(f["rule"], f["subject"]) for f in new_findings}
    missing = [it for it in items
               if (it.get("rule"), it.get("subject")) not in captured]
    result.update({"items": items, "missing": missing, "ok": not missing})
    return result


def rot(fixture_dir):
    """腐烂模拟：在内存副本上注入结构漂移（列改名/定义篡改/孤儿指标）与语义腐烂
    （stale alias / 来源新鲜度冲突，来自 fixtures/<fx>/rot/semantic_decay.yml），
    再重跑 audit；不写回磁盘，除非 --write。"""
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

    # 4) stale alias + 5) conflicting source timestamps：语义腐烂注入（fixtures/<fixture>/rot/semantic_decay.yml）
    decay = _load_semantic_decay(fd)
    if decay:
        deprecated = decay.get("deprecated_metric")
        alias = decay.get("stale_alias") or {}
        if deprecated:
            metrics.append(copy.deepcopy(deprecated))
        ensure = alias.get("ensure_metric")
        if ensure and not any(m.get("id") == ensure.get("id") for m in metrics):
            metrics.append(copy.deepcopy(ensure))
        if alias:
            for m in metrics:
                if m.get("id") == alias.get("metric"):
                    m.setdefault("synonyms", [])
                    if alias.get("synonym") and alias["synonym"] not in m["synonyms"]:
                        m["synonyms"].append(alias["synonym"])
                    break
        if deprecated or alias:
            injections.append(t("inj_stale_alias", mid=(deprecated or {}).get("id", ""),
                                syn=alias.get("synonym", ""), owner=alias.get("metric", "")))
        conflict = decay.get("conflicting_sources") or {}
        if conflict:
            for m in metrics:
                if m.get("id") == conflict.get("metric"):
                    m["sources"] = copy.deepcopy(conflict.get("sources") or [])
                    srcs = m["sources"]
                    injections.append(t("inj_conflicting_sources", mid=m["id"],
                                        a=srcs[0].get("table", ""), b=srcs[1].get("table", "")))
                    break
    else:
        injections.append(t("inj_semantic_skip"))

    after = audit_core(tables, metrics, domains, joins)

    # 新增捕获数 = |findings_after - findings_before|（按 rule+subject+detail 去重后的集合差）
    key = lambda f: (f["rule"], f["subject"], f["detail"])
    before_keys = {key(f) for f in before}
    new_findings = [f for f in after if key(f) not in before_keys]
    by_category = {"structural": 0, "semantic": 0}
    for f in new_findings:
        by_category[finding_category(f)] += 1
    return {
        "fixture": str(fd),
        "injections": injections,
        "before_findings": before,
        "after_findings": after,
        "new_findings": new_findings,
        "before_count": len(before),
        "after_count": len(after),
        "new_count": len(new_findings),
        "new_by_category": by_category,
        "expected": _check_expected(fd, new_findings),
        "drifted_metrics": metrics,  # 注入后的语义层（仅 --write 落盘）
        "drifted_domains": domains,  # 注入后的域（深拷贝，--write 落盘）
        "drifted_joins": joins,      # 注入后的 join（深拷贝，键为 on_expr；--write 落盘）
    }


# ---------------------------------------------------------------- eval（第十三节判分协议）

def build_db(fd: Path):
    """内存 SQLite：先建 schema 再灌 seed，作为金标/候选 SQL 的统一执行环境。

    调用方负责关闭（eval_run 用 try/finally；测试用 try/finally）。
    建库中途失败也会关连接，避免 ResourceWarning。
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript((fd / "schema.sql").read_text(encoding="utf-8"))
        conn.executescript((fd / "seed.sql").read_text(encoding="utf-8"))
    except Exception:
        conn.close()
        raise
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


_RE_CJK = re.compile(r"[\u4e00-\u9fff]")


def _marker_lang(results):
    """答案语言探测：任一 raw 含 CJK → 中文关键词表，否则英文关键词表。

    关键词表与答案语言耦合（13.2 契约）：探测基于回答内容而非显示语言，
    保证 demo（中文答案）与真实英文 run 各自命中正确表。
    """
    for arm in results["arms"].values():
        for ans in arm:
            if _RE_CJK.search(ans.get("raw") or ""):
                return "zh"
    return "en"


def _marker(raw, lang="zh"):
    if not raw:
        return None
    if lang == "en":
        r = raw.strip().lower()
        cm, am = EN_CLARIFY_MARKERS, EN_ABSTAIN_MARKERS
    else:
        r = raw
        cm, am = CLARIFY_MARKERS, ABSTAIN_MARKERS
    if any(m in r for m in cm):
        return "clarify"
    if any(m in r for m in am):
        return "abstain"
    return None


def score_one(q, ans, conn, lang="zh"):
    """第十三节 13.1/13.2：单题判分（标签互斥，优先级 clarify > abstain > honest_error > silent_error > correct）。

    expected=clarify 时收紧（审查必改项 H2）：空 raw、无澄清意图的短回复（如「嗯」「好的」「ok」）
    一律不算 correct；只有 _marker 明确命中（含「需澄清」类文案）才记 clarify/abstain 且可计入
    准确率分子；给了数字/武断是非（含 raw 中出现数字）一律 silent_error。
    lang 选择关键词表：zh（默认）/ en，由 eval_run 按答案语言探测传入。
    """
    qid = q["id"]
    expected = q.get("expected_behavior", "answer")
    sql, value, raw = ans.get("sql"), ans.get("value"), ans.get("raw") or ""

    if expected == "clarify":
        if sql or value is not None or re.search(r"\d", raw):
            return {"qid": qid, "label": "silent_error", "expected": expected,
                    "explained": False, "notes": t("note_silent_clarify"),
                    "numeric_value": value if value is not None else None}
        marker = _marker(raw, lang)
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
    label = _marker(raw, lang) or "abstain"
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


# ---------------------------------------------------------------- 版本锁定（manifest）与分项判分

MANIFEST_COMPARE_KEYS = ("hygieia_version", "model", "prompt_sha256",
                         "questions_sha256", "corpus_sha256", "semantic_sha256")


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path):
    try:
        return _sha256(Path(path).read_bytes())
    except OSError:
        return ""


def _prompt_blob(fd):
    parts = []
    for arm in ("control", "treatment"):
        p = Path(fd) / "prompts" / (arm + ".md")
        parts.append(p.read_bytes() if p.exists() else b"")
    return b"\n---\n".join(parts)


def _arm_aggregate(arm):
    total = arm["total"]
    return {
        "total": total,
        "correct": arm["correct"],
        "silent_error": arm["silent_error"],
        "accuracy": arm["accuracy"],
        "silent_rate": arm["silent_rate"],
        "entity_correct": arm["entity_correct"],
        "entity_accuracy": arm["entity_correct"] / total if total else 0.0,
        "entity_silent": arm["entity_silent"],
        "relation_correct": arm["relation_correct"],
        "relation_accuracy": arm["relation_correct"] / total if total else 0.0,
        "relation_silent": arm["relation_silent"],
    }


def build_manifest(fd, results_file, results, arms):
    """eval 锁版本：model / prompt / 问题集 / 语料 / 语义层 + 版本与时间戳 + 汇总。

    比较时排除 timestamp / run_id / aggregates（见 manifest_diff）。
    """
    fd = Path(fd)
    corpus = b"\n---\n".join((fd / n).read_bytes() for n in ("schema.sql", "seed.sql"))
    answers = json.dumps(results.get("arms") or {}, ensure_ascii=False, sort_keys=True).encode()
    model = results.get("model") or ("simulated (hand-authored)" if results.get("simulated") else "unknown")
    return {
        "hygieia_version": VERSION,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": results.get("run_id") or Path(results_file).stem,
        "model": model,
        "simulated": bool(results.get("simulated")),
        "prompt_sha256": _sha256(_prompt_blob(fd)),
        "questions_sha256": _sha256_file(fd / "questions.yaml"),
        "corpus_sha256": _sha256(corpus),
        "semantic_sha256": _sha256_file(fd / "semantic" / "metrics.yml"),
        "answers_sha256": _sha256(answers),
        "aggregates": {arm: _arm_aggregate(arms[arm]) for arm in arms},
    }


def manifest_diff(a, b):
    """返回两次 manifest 的可比字段差异；空列表 = 可直接比较。"""
    if not a or not b:
        return list(MANIFEST_COMPARE_KEYS)
    return [k for k in MANIFEST_COMPARE_KEYS if a.get(k) != b.get(k)]


def write_manifest(fd, res):
    """把本次 eval 的 manifest 写到 <fixture>/reports/manifest.json（生成物，不入库）。"""
    out_dir = Path(fd) / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(res["manifest"], ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return path


def read_manifest(fd):
    path = Path(fd) / "reports" / "manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _gold_profile(q):
    sql = q.get("gold_sql")
    if not sql:
        return None
    try:
        return sql_refs.profile(sql)
    except ValueError:
        return None


def dimension_flags(q, ans, row, gold):
    """entity = 表 / join 路径；relation = 指标口径（聚合 + 过滤列）。

    - 判为 correct：两个维度都算对；
    - expected=clarify 或金标不可解析：两个维度都不算对（失败不在实体/口径）；
    - 有 SQL：entity 比对表集合，relation 比对聚合签名 + 过滤列集合；
    - 无 SQL / 无法解析：两个维度都不算对（不可归因，不给分）。
    """
    if _counts_correct(row):
        return True, True
    if q.get("expected_behavior") == "clarify" or gold is None:
        return False, False
    sql = ans.get("sql")
    if not sql:
        return False, False
    try:
        cand = sql_refs.profile(sql)
    except ValueError:
        return False, False
    entity = cand["tables"] == gold["tables"]
    relation = cand["aggs"] == gold["aggs"] and cand["filters"] == gold["filters"]
    return entity, relation


def regression_flags(control, treatment, prev_manifest=None):
    """回归检查：treatment 总分提升，但某个维度低于 control 或上次 run -> 标红。"""
    flags = []
    if treatment["accuracy"] > control["accuracy"]:
        for dim in ("entity", "relation"):
            cur, base = treatment[dim + "_accuracy"], control[dim + "_accuracy"]
            if cur < base:
                flags.append({"dimension": dim, "baseline": "control",
                              "current": cur, "previous": base})
    prev_t = ((prev_manifest or {}).get("aggregates") or {}).get("treatment")
    if prev_t and treatment["accuracy"] > prev_t.get("accuracy", 0.0):
        for dim in ("entity", "relation"):
            cur, base = treatment[dim + "_accuracy"], prev_t.get(dim + "_accuracy", 0.0)
            if cur < base:
                flags.append({"dimension": dim, "baseline": "previous run",
                              "current": cur, "previous": base})
    return flags


def eval_run(fixture_dir, results_path=None, trust_hints=False):
    fd = Path(fixture_dir)
    questions = load_yml(fd / "questions.yaml")["questions"]
    qmap = {q["id"]: q for q in questions}
    results_file = Path(results_path) if results_path else fd / "demo_results.json"
    if results_file.is_dir():
        # runs/<run_id>/ 协议（P3，docs/eval-live.md）：meta.json + control.json + treatment.json
        meta = json.loads((results_file / "meta.json").read_text(encoding="utf-8"))
        results = {
            "simulated": meta.get("simulated", True),
            "note": meta.get("note", "run " + str(meta.get("run_id", results_file.name))),
            "run_id": meta.get("run_id"),
            "model": meta.get("model"),
            "arms": {
                "control": json.loads((results_file / "control.json").read_text(encoding="utf-8")),
                "treatment": json.loads((results_file / "treatment.json").read_text(encoding="utf-8")),
            },
        }
    else:
        results = json.loads(results_file.read_text(encoding="utf-8"))
    conn = build_db(fd)
    marker_lang = _marker_lang(results)  # 答案语言探测：中文答案→中文关键词表，英文→英文表
    gold = {qid: _gold_profile(q) for qid, q in qmap.items()}

    arms = {}
    try:
        for arm in ("control", "treatment"):
            rows = []
            for ans in results["arms"][arm]:
                q = qmap[ans["qid"]]
                row = score_one(q, ans, conn, marker_lang)
                if trust_hints and ans.get("label_hint"):  # 调试开关：以 hint 为准，不代替自动判分
                    row["label"] = ans["label_hint"]
                entity_ok, relation_ok = dimension_flags(q, ans, row, gold.get(q["id"]))
                row["entity_correct"] = entity_ok
                row["relation_correct"] = relation_ok
                rows.append(row)
            total = len(rows)
            correct = sum(1 for r in rows if _counts_correct(r))
            silent = sum(1 for r in rows if r["label"] == "silent_error")
            entity = sum(1 for r in rows if r["entity_correct"])
            relation = sum(1 for r in rows if r["relation_correct"])
            arms[arm] = {
                "rows": rows,
                "total": total,
                "correct": correct,
                "silent_error": silent,
                "accuracy": correct / total if total else 0.0,
                "silent_rate": silent / total if total else 0.0,
                "entity_correct": entity,
                "entity_accuracy": entity / total if total else 0.0,
                "entity_silent": sum(1 for r in rows
                                     if r["label"] == "silent_error" and not r["entity_correct"]),
                "relation_correct": relation,
                "relation_accuracy": relation / total if total else 0.0,
                "relation_silent": sum(1 for r in rows
                                       if r["label"] == "silent_error" and not r["relation_correct"]),
            }
    finally:
        conn.close()  # 显式关闭，避免 ResourceWarning
    res = {
        "simulated": results.get("simulated", False),
        "note": results.get("note", ""),
        "results_file": str(results_file),
        "arms": arms,
    }
    res["manifest"] = build_manifest(fd, results_file, results, arms)
    return res


# ---------------------------------------------------------------- report

def render_report(fd, audit_res, rot_res, eval_res, prev_manifest=None):
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
    lines.append(t("rot_new_split", new=rot_res["new_count"],
                   structural=rot_res["new_by_category"]["structural"],
                   semantic=rot_res["new_by_category"]["semantic"]))
    lines.append(t("report_injections", items=t("inj_sep").join(rot_res["injections"])))
    if rot_res["new_findings"]:
        for f in rot_res["new_findings"]:
            lines.append(t("report_new", cat=t("cat_" + finding_category(f)),
                           rule=f["rule"], detail=f["detail"]))
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
    for dim in ("entity", "relation"):
        ct, tt = c["total"], t_["total"]
        lines.append(t("report_" + dim + "_acc",
                       c=c[dim + "_correct"], ct=ct, ca=c[dim + "_accuracy"],
                       t=t_[dim + "_correct"], tt=tt, ta=t_[dim + "_accuracy"]))
        lines.append(t("report_" + dim + "_silent",
                       c=c[dim + "_silent"], ct=ct, cs=c[dim + "_silent"] / ct if ct else 0.0,
                       t=t_[dim + "_silent"], tt=tt, ts=t_[dim + "_silent"] / tt if tt else 0.0))
    lines.append("")
    lines.append(t("report_dim_note"))
    lines.append("")
    lines.append(t("report_eval_note"))
    lines.append("")
    lines.append(t("report_manifest_hdr"))
    diff = manifest_diff(eval_res.get("manifest"), prev_manifest)
    if not prev_manifest:
        lines.append(t("report_manifest_none"))
    elif diff:
        lines.append(t("report_manifest_warn", fields=", ".join(diff)))
    else:
        lines.append(t("report_manifest_ok"))
    lines.append("")
    lines.append(t("report_regression_hdr"))
    flags = regression_flags(c, t_, prev_manifest)
    if not flags:
        lines.append(t("report_regression_none"))
    for flag in flags:
        base = (t("regress_vs_control") if flag["baseline"] == "control"
                else t("regress_vs_prev"))
        lines.append(t("report_regression_item", dim=t("dim_" + flag["dimension"]),
                       cur=flag["current"], base=base, prev=flag["previous"]))
    lines.append("")
    lines.append(t("report_uncovered"))
    for item in t("report_uncovered_items"):
        lines.append(f"- {item}")
    lines.append("")
    lines.append(t("report_footer"))
    return "\n".join(lines)


def report(fixture_dir):
    fd = Path(fixture_dir)
    prev = read_manifest(fd)  # 先读上一次 eval 的 manifest，再让本次 eval 覆盖它
    a = audit(fixture_dir)
    r = rot(fixture_dir)
    e = eval_run(fixture_dir)
    md = render_report(fd, a, r, e, prev)
    out = fd / "reports" / "health-report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8", newline="\n")
    write_manifest(fd, e)
    c, t_ = e["arms"]["control"], e["arms"]["treatment"]
    return {
        "path": str(out),
        "audit_total": a["summary"]["total"],
        "audit_high": a["summary"]["counts"]["high"],
        "rot_new": r["new_count"],
        "rot_new_structural": r["new_by_category"]["structural"],
        "rot_new_semantic": r["new_by_category"]["semantic"],
        "control_accuracy": f"{c['accuracy']:.0%}",
        "treatment_accuracy": f"{t_['accuracy']:.0%}",
        "control_silent": f"{c['silent_rate']:.0%}",
        "treatment_silent": f"{t_['silent_rate']:.0%}",
        "manifest_diff": manifest_diff(e["manifest"], prev),
        "manifest_comparable": bool(prev) and not manifest_diff(e["manifest"], prev),
        "regressions": regression_flags(c, t_, prev),
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
    print(t("rot_new_split", new=res["new_count"],
            structural=res["new_by_category"]["structural"],
            semantic=res["new_by_category"]["semantic"]))
    for f in res["new_findings"]:
        cat = t("cat_" + finding_category(f))
        print(f"🆕 [{cat}] {t('sev_' + f['severity'])} {f['rule']} [{f['subject']}]：{f['detail']}")
    exp = res.get("expected") or {}
    if exp.get("items"):
        if exp["ok"]:
            print(t("rot_expected_ok", n=len(exp["items"])))
        else:
            print(t("rot_expected_missing",
                    items=t("inj_sep").join(f"{i['rule']}@{i['subject']}" for i in exp["missing"])))


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
    c, t_ = res["arms"]["control"], res["arms"]["treatment"]
    for dim in ("entity", "relation"):
        print(t("eval_dim_line", dim=t("dim_" + dim),
                cc=c[dim + "_correct"], ct=c["total"], ca=c[dim + "_accuracy"],
                tc=t_[dim + "_correct"], tt=t_["total"], ta=t_[dim + "_accuracy"]))
    if res.get("manifest"):
        m = res["manifest"]
        print(t("eval_manifest", model=m["model"], sem=m["semantic_sha256"][:12],
                q=m["questions_sha256"][:12], pr=m["prompt_sha256"][:12], path="reports/manifest.json"))
    if verbose:
        print(t("verbose_label"))
        for arm in ("control", "treatment"):
            print(f"  [{arm}] " + " ".join(f"{r['qid']}:{r['label'][:4]}" for r in res["arms"][arm]["rows"]))


def print_report(res):
    print(f"== report: {res['path']} ==")
    print(t("report_print", total=res["audit_total"], high=res["audit_high"], new=res["rot_new"]))
    print(t("report_print_acc", c=res["control_accuracy"], t=res["treatment_accuracy"],
            cs=res["control_silent"], ts=res["treatment_silent"]))
    print(t("rot_new_split", new=res["rot_new"],
            structural=res["rot_new_structural"], semantic=res["rot_new_semantic"]))
    if res.get("manifest_diff"):
        print(t("report_manifest_warn", fields=", ".join(res["manifest_diff"])))
    for flag in res.get("regressions") or []:
        base = (t("regress_vs_control") if flag["baseline"] == "control"
                else t("regress_vs_prev"))
        print(t("report_regression_item", dim=t("dim_" + flag["dimension"]),
                cur=flag["current"], base=base, prev=flag["previous"]))


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
      joins[]（可选，显式 on_expr；裸 on 无法映射，YAML 1.1 布尔键陷阱）
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

    sp_audit = add_cmd("audit")
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

    sp_impact = add_cmd("impact", help=t("impact_help"))
    sp_impact.add_argument("--diff", required=True, help=t("impact_diff_help"))

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
    cmd = args.command

    if cmd == "audit":
        res = audit(args.fixture_dir)
        if args.json:
            print(json.dumps(_jsonable(res), ensure_ascii=False, indent=2))
        else:
            print_audit(res)
        return fail_on(res["findings"], args.fail_on)

    if cmd == "eval":
        res = eval_run(args.fixture_dir, args.results, args.trust_hints)
        write_manifest(args.fixture_dir, res)
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
            out.write_text(yaml.safe_dump(drifted, allow_unicode=True, sort_keys=False),
                           encoding="utf-8", newline="\n")
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
                       encoding="utf-8", newline="\n")
        for s in res["skipped"]:
            print(t("adapt_skip", item=s["item"], reason=s["reason"]), file=sys.stderr)
        print(t("adapt_done", n=len(res["metrics"]), out=out, m=len(res["skipped"])))
        return 0

    if cmd == "impact":
        patch = sys.stdin.read() if args.diff == "-" else Path(args.diff).read_text(encoding="utf-8")
        res = impact(Path(args.fixture_dir), patch)
        if args.json:
            print(json.dumps(res, ensure_ascii=False))
            return 0
        if res["files_changed"]:
            print(t("impact_files", items=", ".join(res["files_changed"])))
        if res["changed"]:
            print(t("impact_changed", items=", ".join(f"{t}.{c}" for t, c in res["changed"])))
        if not res["affected"]:
            print(t("impact_none"))
            return 0
        print(t("impact_head", n=len(res["affected"]), fd=args.fixture_dir))
        for a in res["affected"]:
            refs = ", ".join(f"{t}.{c}" for t, c in a["refs"]) or a.get("unparseable", "")
            print(t("impact_line", metric=a["metric"], kind=a["kind"], refs=refs))
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

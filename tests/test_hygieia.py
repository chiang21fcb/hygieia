#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hygieia v0 自测（stdlib unittest 即可）：断言第四节/十三节契约数字。

运行：python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import hygieia  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures" / "ecom"
ADAPT_FIX = ROOT / "fixtures" / "adapt_dbt_mini"


class TestSchemaParse(unittest.TestCase):
    def test_six_tables(self):
        tables = hygieia.load_schema(FIX / "schema.sql")
        self.assertEqual(
            set(tables),
            {"customers", "products", "orders", "order_items", "payments", "reviews"},
        )
        self.assertIn("total_amount", tables["orders"])
        self.assertIn("net_amount", tables["orders"])


class TestAuditContract(unittest.TestCase):
    """总验收：audit 检出 >=7 条问题，且 R1/R3/R4 各至少 1 条高危。"""

    def test_audit_counts(self):
        res = hygieia.audit(FIX)
        findings = res["findings"]
        self.assertGreaterEqual(len(findings), 7)
        self.assertEqual(res["summary"]["counts"]["high"], 3)
        self.assertEqual(res["summary"]["counts"]["medium"], 4)
        by_rule = {}
        for f in findings:
            by_rule.setdefault(f["rule"], []).append(f)
        for rule in ("R1-synonym-conflict", "R3-join-ambiguity", "R4-dangling-ref"):
            self.assertTrue(any(f["severity"] == "high" for f in by_rule[rule]), rule)
        self.assertEqual(len(by_rule.get("R5-no-evidence", [])), 4)

    def test_findings_have_three_elements(self):
        for f in hygieia.audit(FIX)["findings"]:
            for key in ("rule", "danger", "fix"):
                self.assertIn(key, f)


class TestRotContract(unittest.TestCase):
    """总验收：rot 新增捕获 = 4（列改名悬空 x2、孤儿指标、缺证据）。"""

    def test_rot_new_findings(self):
        res = hygieia.rot(FIX)
        self.assertEqual(res["before_count"], 7)
        self.assertEqual(res["after_count"], 11)
        self.assertEqual(res["new_count"], 4)
        new = {(f["rule"], f["subject"]) for f in res["new_findings"]}
        self.assertIn(("R2-orphan-metric", "gross_margin"), new)
        self.assertIn(("R4-dangling-ref", "revenue"), new)
        self.assertIn(("R4-dangling-ref", "avg_order_value"), new)
        self.assertIn(("R5-no-evidence", "gross_margin"), new)


class TestEvalDemo(unittest.TestCase):
    """总验收：demo_results.json 复现 65%/100% 与 35%/0%。"""

    def test_demo_numbers(self):
        res = hygieia.eval_run(FIX)
        c = res["arms"]["control"]
        t = res["arms"]["treatment"]
        self.assertTrue(res["simulated"])
        self.assertEqual((c["correct"], c["total"]), (13, 20))
        self.assertEqual((c["silent_error"], c["total"]), (7, 20))
        self.assertEqual((t["correct"], t["total"]), (20, 20))
        self.assertEqual((t["silent_error"], t["total"]), (0, 20))
        self.assertAlmostEqual(c["accuracy"], 0.65)
        self.assertAlmostEqual(c["silent_rate"], 0.35)
        self.assertAlmostEqual(t["accuracy"], 1.0)
        self.assertAlmostEqual(t["silent_rate"], 0.0)


class TestBrokenSynonym(unittest.TestCase):
    """故意改坏 synonym 应多出 R1（契约第十七节第 8 条）。"""

    def test_extra_synonym_adds_r1(self):
        sm = hygieia.load_yml(FIX / "semantic" / "metrics.yml")
        metrics = []
        for m in sm["metrics"]:
            m = dict(m)
            if m["id"] == "net_revenue":
                m["synonyms"] = list(m["synonyms"]) + ["销售额"]
            metrics.append(m)
        r1 = [
            f for f in hygieia.audit_core(
                hygieia.load_schema(FIX / "schema.sql"), metrics,
                sm["domains"], sm["joins"],
            )
            if f["rule"] == "R1-synonym-conflict"
        ]
        self.assertEqual(len(r1), 2)
        subjects = {f["subject"] for f in r1}
        self.assertEqual(subjects, {"营收", "销售额"})


class TestReport(unittest.TestCase):
    """总验收：report 生成 Markdown，含高危/中危、腐烂模拟、对照评测三块（默认英文显示层）。"""

    def test_report_generates_three_blocks(self):
        hygieia.LANG = "en"
        res = hygieia.report(FIX)
        md = Path(res["path"]).read_text(encoding="utf-8")
        for block in ("🔴 High", "Rot simulation", "Evaluation"):
            self.assertIn(block, md)
        self.assertIn("13/20 (65%)", md)
        self.assertIn("20/20 (100%)", md)


class TestReportZh(unittest.TestCase):
    """中文显示层（--lang zh）：报告必须整份是中文，不掺英文块标题。"""

    def test_report_zh_blocks(self):
        old = hygieia.LANG
        try:
            hygieia.LANG = "zh"
            res = hygieia.report(FIX)
            md = Path(res["path"]).read_text(encoding="utf-8")
            for block in ("🔴 高危", "腐烂模拟", "对照评测"):
                self.assertIn(block, md)
            self.assertNotIn("## Rot simulation", md)
        finally:
            hygieia.LANG = old
            hygieia.report(FIX)  # 恢复英文版报告，保持仓库内产物为默认语言


class TestOnExprYaml(unittest.TestCase):
    """审查必改项 H1：join 条件键必须是字符串 on_expr，不得出现 YAML 1.1 布尔键 True。"""

    def test_joins_use_on_expr_string_key(self):
        sm = hygieia.load_yml(FIX / "semantic" / "metrics.yml")
        self.assertGreaterEqual(len(sm["joins"]), 1)
        for j in sm["joins"]:
            self.assertIn("on_expr", j)
            self.assertIsInstance(j["on_expr"], str)
            self.assertNotIn(True, j)  # 裸 `on:` 会被 safe_load 解析成键 True
            self.assertNotIn("on", j)

    def test_on_expr_dangling_column_reported(self):
        sm = hygieia.load_yml(FIX / "semantic" / "metrics.yml")
        joins = [dict(sm["joins"][0])]
        joins[0]["on_expr"] = "orders.customer_id = customers.nope_id"
        findings = hygieia.audit_core(
            hygieia.load_schema(FIX / "schema.sql"), sm["metrics"], sm["domains"], joins)
        hits = [
            f for f in findings
            if f["rule"] == "R4-dangling-ref" and f["subject"] == "join orders->customers"
            and "nope_id" in f["detail"]
        ]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["severity"], "high")


class TestClarifyScoring(unittest.TestCase):
    """审查必改项 H2：clarify 题上，空/敷衍回复不得 correct；带澄清/拒答文案才 correct。"""

    def _score(self, raw, value=None):
        q = {"id": "t1", "expected_behavior": "clarify"}
        ans = {"qid": "t1", "sql": None, "value": value, "raw": raw}
        return hygieia.score_one(q, ans, None)

    def test_empty_raw_not_correct(self):
        row = self._score("")
        self.assertFalse(hygieia._counts_correct(row))

    def test_filler_raw_not_correct(self):
        for raw in ("嗯", "好的", "哦"):
            row = self._score(raw)
            self.assertEqual(row["label"], "abstain")
            self.assertFalse(hygieia._counts_correct(row))

    def test_clear_marker_is_correct(self):
        for raw in ("无法回答", "需要澄清口径", "数据不足，无法计算", "缺少埋点数据，无法确认"):
            row = self._score(raw)
            self.assertIn(row["label"], ("clarify", "abstain"))
            self.assertTrue(hygieia._counts_correct(row), raw)

    def test_number_without_marker_is_silent(self):
        row = self._score("约 0.25 左右")
        self.assertEqual(row["label"], "silent_error")
        self.assertFalse(hygieia._counts_correct(row))


class TestNetRevenueExecutable(unittest.TestCase):
    """审查必改项 H3（方案 A）：net_revenue.expr 可在 seed 上真实执行，且与金标一致。"""

    def test_expr_runs_on_seed(self):
        sm = hygieia.load_yml(FIX / "semantic" / "metrics.yml")
        expr = next(m["expr"] for m in sm["metrics"] if m["id"] == "net_revenue")
        conn = hygieia.build_db(FIX)
        try:
            all_time = conn.execute(f"SELECT {expr} FROM orders").fetchone()[0]
            july = conn.execute(
                f"SELECT {expr} FROM orders WHERE order_date >= '2026-07-01' AND order_date < '2026-08-01'"
            ).fetchone()[0]
            self.assertEqual(all_time, 1760)
            self.assertEqual(july, 1110)
        finally:
            conn.close()  # 显式关闭，避免 ResourceWarning


class TestDescriptionRules(unittest.TestCase):
    """中优先级：R6/R7 各有一条可触发的单测（通过内存改坏 metrics，不碰 ecom 数字）。"""

    def test_r6_short_description(self):
        sm = hygieia.load_yml(FIX / "semantic" / "metrics.yml")
        metrics = [dict(m) for m in sm["metrics"]]
        metrics[0]["description"] = "收入"
        findings = hygieia.audit_core(
            hygieia.load_schema(FIX / "schema.sql"), metrics, sm["domains"], sm["joins"])
        self.assertTrue(any(
            f["rule"] == "R6-no-description" and f["subject"] == "revenue" for f in findings))

    def test_r7_tautological_description(self):
        sm = hygieia.load_yml(FIX / "semantic" / "metrics.yml")
        metrics = [dict(m) for m in sm["metrics"]]
        metrics[0]["description"] = "orders"
        findings = hygieia.audit_core(
            hygieia.load_schema(FIX / "schema.sql"), metrics, sm["domains"], sm["joins"])
        self.assertTrue(any(
            f["rule"] == "R7-redundant-description" and f["subject"] == "revenue" for f in findings))


class TestAdaptDbt(unittest.TestCase):
    """P2：只读适配器把 dbt/MetricFlow 子集映成 metrics.yml；audit 可跑、无布尔键 True、不伪造证据。"""

    def test_adapt_dbt_mini_audit_runs(self):
        data = hygieia.load_yml(ADAPT_FIX / "dbt_semantic.yml")
        res = hygieia.adapt_dbt(data)
        self.assertGreaterEqual(len(res["metrics"]), 3)
        ids = {m["id"] for m in res["metrics"]}
        self.assertTrue({"revenue", "net_revenue", "avg_order_value"} <= ids)
        # cumulative 不支持 → 明确跳过（带原因），不瞎猜
        self.assertIn("running_revenue", [s["item"] for s in res["skipped"]])
        # 产出能被现有 loader 吃掉：无布尔键 True、无裸 on
        import yaml
        payload = {k: res[k] for k in ("version", "domains", "joins", "metrics")}
        loaded = yaml.safe_load(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
        self.assertNotIn(True, loaded)
        for j in loaded["joins"]:
            self.assertIn("on_expr", j)
            self.assertNotIn(True, j)
        # audit 能跑，且 R4 无悬空引用（mini schema 覆盖所有引用列）
        findings = hygieia.audit_core(
            hygieia.load_schema(ADAPT_FIX / "schema.sql"),
            loaded["metrics"], loaded["domains"], loaded["joins"])
        dangling = [f for f in findings if f["rule"] == "R4-dangling-ref"]
        self.assertEqual(dangling, [])

    def test_adapt_dbt_never_fabricates_evidence(self):
        data = hygieia.load_yml(ADAPT_FIX / "dbt_semantic.yml")
        res = hygieia.adapt_dbt(data)
        for m in res["metrics"]:
            self.assertNotIn("evidence", m)  # 无证据留空 → 现有 R5 会打中，属期望行为

    def test_adapt_dbt_join_without_on_expr_skipped(self):
        data = hygieia.load_yml(ADAPT_FIX / "dbt_semantic.yml")
        data["joins"] = [{"left": "orders", "right": "customers",
                          "on": "orders.customer_id = customers.id"}]
        res = hygieia.adapt_dbt(data)
        self.assertEqual(res["joins"], [])
        self.assertIn("orders->customers", [s["item"] for s in res["skipped"]])


if __name__ == "__main__":
    unittest.main()

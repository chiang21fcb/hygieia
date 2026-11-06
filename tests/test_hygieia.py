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


class TestEnglishMarkers(unittest.TestCase):
    """P3：英文关键词表——答案语言探测选择，中文表回归不受影响。"""

    def test_en_clarify_marker_is_correct(self):
        q = {"id": "q_en1", "expected_behavior": "clarify"}
        row = hygieia.score_one(q, {"qid": "q_en1", "raw": "I cannot compute this — insufficient data"},
                                None, lang="en")
        self.assertEqual(row["label"], "clarify")
        self.assertTrue(hygieia._counts_correct(row))

    def test_en_abstain_marker_counts(self):
        q = {"id": "q_en2", "expected_behavior": "clarify"}
        row = hygieia.score_one(q, {"qid": "q_en2", "raw": "I don't know"}, None, lang="en")
        self.assertEqual(row["label"], "abstain")
        self.assertTrue(hygieia._counts_correct(row))  # 带说明性弃权 → 计入分子

    def test_en_filler_not_correct(self):
        q = {"id": "q_en3", "expected_behavior": "clarify"}
        row = hygieia.score_one(q, {"qid": "q_en3", "raw": "ok"}, None, lang="en")
        self.assertEqual(row["label"], "abstain")
        self.assertFalse(hygieia._counts_correct(row))  # H2 收紧：敷衍回复不算

    def test_zh_markers_unaffected(self):
        q = {"id": "q_zh1", "expected_behavior": "clarify"}
        row = hygieia.score_one(q, {"qid": "q_zh1", "raw": "数据不足，无法计算"}, None, lang="zh")
        self.assertEqual(row["label"], "clarify")
        self.assertTrue(hygieia._counts_correct(row))


class TestLiveRunDir(unittest.TestCase):
    """P3：--results 支持 runs/<id> 目录（meta + control + treatment），demo 单文件向后兼容。"""

    def test_run_dir_scores_both_arms(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "run-live"
            d.mkdir()
            (d / "meta.json").write_text(json.dumps(
                {"run_id": "run-live", "model": "fake-agent", "simulated": True,
                 "note": "fake"}, ensure_ascii=False), encoding="utf-8")
            (d / "control.json").write_text(json.dumps(
                [{"qid": "q07", "value": 1210, "raw": "1210"}], ensure_ascii=False), encoding="utf-8")
            (d / "treatment.json").write_text(json.dumps(
                [{"qid": "q07", "sql": "SELECT SUM(net_amount) FROM orders "
                                       "WHERE order_date >= '2026-07-01' AND order_date < '2026-08-01'"}],
                ensure_ascii=False), encoding="utf-8")
            res = hygieia.eval_run(FIX, str(d))
            c = res["arms"]["control"]["rows"][0]
            t = res["arms"]["treatment"]["rows"][0]
            self.assertEqual(c["label"], "silent_error")  # 给了数字，无澄清意图
            self.assertEqual(t["label"], "correct")       # SQL 执行与金标一致
            self.assertEqual(res["results_file"], str(d))


class TestFreshDataTrial(unittest.TestCase):
    """防拟合：全新数据 + 已知答案注入（固定 seed），判分器必须逐题还原注入标签。
    证明 demo 数字是规则判分的结果，不是对着 demo 拟合的常量。"""

    SQLS = [
        "SELECT COUNT(*) FROM orders",
        "SELECT COALESCE(SUM(net_amount),0) FROM orders",
        "SELECT COALESCE(SUM(total_amount),0) FROM orders WHERE status='cancelled'",
        "SELECT COUNT(*) FROM orders WHERE customer_id < 5",
        "SELECT COALESCE(AVG(total_amount),0) FROM orders",
        "SELECT COALESCE(MAX(net_amount),0) FROM orders",
        "SELECT COUNT(DISTINCT status) FROM orders",
        "SELECT COALESCE(SUM(total_amount),0) FROM orders WHERE order_date LIKE '2026-08%'",
        "SELECT COUNT(*) FROM order_items",
        "SELECT COALESCE(SUM(quantity),0) FROM order_items",
    ]
    ZH_MARKER = ["数据不足，无法计算", "需要澄清口径才能回答", "无法计算，缺少必要数据", "请澄清"]

    def test_fresh_data_label_recovery(self):
        import random
        random.seed(20261106)
        conn = hygieia.build_db(FIX)
        questions, golds = [], []
        for i, sql in enumerate(self.SQLS):
            golds.append(hygieia._scalar(conn, sql))
            questions.append({"id": f"t{i:02d}", "text": f"trial q{i}", "gold_sql": sql,
                              "expected_behavior": "answer"})
        questions.append({"id": "t10", "text": "clarify trial",
                          "expected_behavior": "clarify", "gold_sql": None})
        questions.append({"id": "t11", "text": "clarify trial",
                          "expected_behavior": "clarify", "gold_sql": None})
        qmap = {q["id"]: q for q in questions}
        answers, ground = [], {}
        for i, gold in enumerate(golds):
            qid = f"t{i:02d}"
            r = random.random()
            if r < 0.70:
                wrong = gold + random.choice([-37, -12, 9, 23, 45])
                answers.append({"qid": qid, "value": wrong, "raw": str(wrong)})
                ground[qid] = "silent_error"
            elif r < 0.85:
                answers.append({"qid": qid, "value": gold, "raw": str(gold)})
                ground[qid] = "correct"
            else:
                answers.append({"qid": qid, "raw": random.choice(self.ZH_MARKER)})
                ground[qid] = "clarify"
        for qid in ("t10", "t11"):
            if random.random() < 0.5:
                answers.append({"qid": qid, "raw": random.choice(self.ZH_MARKER)})
                ground[qid] = "clarify"
            else:
                answers.append({"qid": qid, "value": 999, "raw": "999"})
                ground[qid] = "silent_error"
        pred = {a["qid"]: hygieia.score_one(qmap[a["qid"]], a, conn, lang="zh")["label"]
                for a in answers}
        mismatches = [qid for qid in ground if pred.get(qid) != ground[qid]]
        self.assertEqual(mismatches, [])  # 12/12 逐题还原

    def test_treatment_perturbation_changes_numbers(self):
        """敏感性：demo treatment 前 3 题去掉 sql 给错值 → 20/0 必须变为 17/3（非硬编码）。"""
        import json
        import tempfile
        demo = json.loads((FIX / "demo_results.json").read_text(encoding="utf-8"))
        for i, ans in enumerate(demo["arms"]["treatment"][:3]):
            ans.pop("sql", None)
            ans["value"] = (ans.get("value") or 0) + 500
            ans["raw"] = str(ans["value"])
        tmp = Path(tempfile.mkdtemp()) / "perturb.json"
        tmp.write_text(json.dumps(demo, ensure_ascii=False), encoding="utf-8")
        base = hygieia.eval_run(FIX)["arms"]["treatment"]
        pert = hygieia.eval_run(FIX, str(tmp))["arms"]["treatment"]
        self.assertEqual((base["correct"], base["silent_error"]), (20, 0))
        self.assertEqual((pert["correct"], pert["silent_error"]), (17, 3))


class TestSqlRefs(unittest.TestCase):
    """N2：sqlglot AST 引用抽取——qualified/二进制/join/解析失败显式上报。"""

    def test_extract_qualified_and_binary(self):
        self.assertEqual(hygieia.expr_refs("sum(orders.net_amount)"),
                         {("orders", "net_amount")})
        self.assertEqual(hygieia.expr_refs("sum(refunds.amount) + sum(refunds.tax)"),
                         {("refunds", "amount"), ("refunds", "tax")})
        self.assertEqual(hygieia.expr_refs("orders.customer_id = customers.id"),
                         {("orders", "customer_id"), ("customers", "id")})

    def test_unparseable_raises(self):
        with self.assertRaises(ValueError):
            hygieia.expr_refs("SUM(((")

    def test_r4_parse_failure_is_high_finding(self):
        tables = {"orders": {"id"}}
        metrics = [{"id": "broken", "expr": "SUM(((", "synonyms": [],
                    "description": "x" * 20}]
        r4 = [f for f in hygieia.rule_r4(metrics, tables) if f["rule"] == "R4-dangling-ref"]
        self.assertEqual(len(r4), 1)
        self.assertEqual(r4[0]["severity"], "high")
        self.assertIn("unparseable", r4[0]["detail"])


class TestImpact(unittest.TestCase):
    """N2：git diff → 受影响 metrics（v1 unified diff 文本解析，见 docs/impact.md）。"""

    def test_impact_marks_expr_metrics(self):
        patch = ("--- a/fixtures/ecom/semantic/metrics.yml\n"
                 "+++ b/fixtures/ecom/semantic/metrics.yml\n"
                 '-    expr: "sum(orders.total_amount)"\n'
                 '+    expr: "sum(orders.order_amount)"\n')
        res = hygieia.impact(FIX, patch)
        affected = {a["metric"] for a in res["affected"]}
        self.assertIn("revenue", affected)          # expr 直接引用
        self.assertIn("avg_order_value", affected)  # CASE WHEN 里引用
        self.assertNotIn("net_revenue", affected)   # 不引用 total_amount
        self.assertIn(("orders", "total_amount"), res["changed"])

    def test_impact_marks_join_on_expr(self):
        patch = ("--- a/fixtures/ecom/semantic/metrics.yml\n"
                 "+++ b/fixtures/ecom/semantic/metrics.yml\n"
                 '-    on_expr: "orders.customer_id = customers.id"\n'
                 '+    on_expr: "orders.buyer_id = customers.id"\n')
        res = hygieia.impact(FIX, patch)
        self.assertIn("on_expr", {a["kind"] for a in res["affected"]})

    def test_impact_empty_patch(self):
        res = hygieia.impact(FIX, "")
        self.assertEqual(res["affected"], [])
        self.assertEqual(res["changed"], [])


if __name__ == "__main__":
    unittest.main()

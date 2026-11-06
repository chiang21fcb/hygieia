---
name: hygieia
description: 语义层/本体体检与养护（audit / eval / rot / report）。当被要求「审计我们的语义层」「检查我们的本体质量」「为什么我们的数据 agent 给错数字」「评估我们的 text-to-SQL 准确率」「压力测试我们的数据模型」「找出项目和本体之间的漂移」时使用。纯本地离线运行，Python 3.10+，仅依赖 pyyaml。
---

# Hygieia（许癸厄亚）

> 不造本体，养护并体检语义层——用三个数字证明「烂本体比没本体更危险」。

Hygieia 是一个纯本地的语义层体检 skill。给定一个 fixture 目录（`schema.sql` + `seed.sql` + `semantic/metrics.yml` + `questions.yaml`），按契约执行四个命令。契约细节见 `docs/contract.md` 第十一～十四节（metrics.yml 契约、严重度、判分协议、rot 威胁模型）。注意：`metrics.yml` 的 join 条件字段名是 `on_expr`——YAML 1.1 会把裸 `on` 解析成布尔键 `True`，字段会悄悄丢失。

## 触发语

> 当被要求「审计我们的语义层」「检查我们的本体质量」「为什么我们的数据 agent 给错数字」「评估我们的 text-to-SQL 准确率」「压力测试我们的数据模型」「找出项目和本体之间的漂移」时使用。

## 操作契约

1. 先确认 fixture 目录存在且布局符合第五节；缺文件则明确告知，不要猜。
2. 运行顺序建议：`audit` → `rot` → `eval` → `report`（report 会依次调 audit/rot/eval）。
3. `audit`：静态诊断 7 类问题（R1 同义冲突 / R2 孤儿指标 / R3 join 歧义 / R4 悬空引用 / R5 证据缺失 / R6 缺描述 / R7 冗余描述），每条问题带三要素：规则、危险、修复建议。
4. `eval`：两臂对照评测。默认读 `fixtures/<dir>/demo_results.json`（顶部标注 `simulated: true` 时为手工模拟答案，判分逻辑仍按第十三节真实执行）；现场真评测时另存 `fixtures/<dir>/runs/<时间戳>/` 产物并用 `--results` 指定。核心指标是**静默错答率**（返了数字、没报错、没澄清）。
5. `rot`：在内存副本注入三类漂移（列改名、定义篡改、新增孤儿指标）后重跑 audit，报告新增捕获数；默认不写回磁盘（`--write` 才落盘为 `metrics.rot.yml`）。
6. `report`：生成 `reports/health-report.md`，含高危/中危、腐烂模拟、对照评测三块。
7. CI 用法：`--fail-on high`，存在高危则退出码 1。
8. 汇报数字时区分「真实执行」（金标/候选 SQL 在种子数据上跑出来的）与「模拟答案」；不得把模拟数据说成现场评测。

## 使用

```bash
python scripts/hygieia.py audit  fixtures/ecom
python scripts/hygieia.py eval   fixtures/ecom
python scripts/hygieia.py rot    fixtures/ecom
python scripts/hygieia.py report fixtures/ecom
```

自测：`python -m unittest discover -s tests -v`（断言第四节数字：65%/100%、静默错答 35%/0%、audit 7 条、rot 新增 4）。

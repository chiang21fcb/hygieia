---
name: hygieia
description: >
  语义层/本体体检与养护（audit / eval / rot / report）。当用户用中文要求「审计我们的语义层」
  「检查我们的本体质量」「为什么我们的数据 agent 给错数字」「评估我们的 text-to-SQL 准确率」
  「压力测试我们的数据模型」「找出项目和本体之间的漂移」时使用；也响应英文提问 "audit our
  semantic layer"、"ontology health check"、"why did the data agent return a wrong number"、
  "evaluate our text-to-SQL accuracy"、"stress-test our data model"、"drift between the
  project and the ontology"。纯本地离线运行，Python 3.10+，仅依赖 pyyaml。
---

# Hygieia

> We don't build ontologies — we keep them healthy.

A fully offline semantic-layer health-check skill. Given a fixture directory (`schema.sql` + `seed.sql` + `semantic/metrics.yml` + `questions.yaml`), run the four commands per the operating contract below. Binding details (metrics.yml schema, severity, scoring protocol, rot threat model) live in `docs/contract.zh.md` (Chinese, authoritative) and `docs/contract.en.md` (English mirror); the essentials are inlined below so this skill stays self-contained.

## Triggers

> Chinese: 「审计我们的语义层」「检查我们的本体质量」「为什么我们的数据 agent 给错数字」「评估我们的 text-to-SQL 准确率」「压力测试我们的数据模型」「找出项目和本体之间的漂移」。
> English: "audit our semantic layer", "ontology health check", "why did the data agent return a wrong number", "evaluate our text-to-SQL accuracy", "stress-test our data model", "drift between the project and the ontology".

## Operating contract

1. First confirm the fixture directory exists and contains `schema.sql`, `seed.sql`, `semantic/metrics.yml` and `questions.yaml`; if any file is missing, say so explicitly — never guess.
2. Suggested order: `audit` → `rot` → `eval` → `report` (`report` calls audit/rot/eval in sequence).
3. `audit`: static diagnosis of 7 rule classes (R1 synonym conflict / R2 orphan metric / R3 join ambiguity / R4 dangling reference / R5 missing evidence / R6 missing description / R7 redundant description). Every finding carries three elements: rule, danger, fix. Severity mapping: **high** = R1, R3, R4 (and R2 when the domain does not exist) — can directly cause wrong numbers; **medium** = R5, and R2 with an existing domain but no table binding; **low** = R6, R7. In `metrics.yml`, the join-condition field is `on_expr` — YAML 1.1 parses a bare `on` as the boolean key `True`, silently dropping the field; R3/R4 read `on_expr` exclusively.
4. `eval`: two-arm controlled evaluation. By default it reads `fixtures/<dir>/demo_results.json` — when the top is marked `simulated: true`, the answers are hand-authored, but the scoring logic still runs for real per the protocol below. For a live evaluation, store artifacts under `fixtures/<dir>/runs/<timestamp>/` and point `--results` at them. The core metric is the **silent-error rate** (a number returned with no error and no clarification — the user cannot tell). Scoring labels are mutually exclusive, judged top-down: `clarify` (explicit refusal to fabricate, or `expected_behavior: clarify`) → `abstain` (explicit "don't know", no business number) → `honest_error` (SQL/number given but execution failed) → `silent_error` (plausible number/yes-no, mismatches gold, no clarification) → `correct` (matches gold). For `expected_behavior: clarify`, only an explicit keyword hit (数据不足 / 无法计算 / 需澄清 / 无法回答 …) counts as `clarify`/`abstain` and may count correct; empty or filler replies (「嗯」「好的」) are non-compliant `abstain`; a concrete number or a digit in `raw` is `silent_error`. Accuracy = correct/total; silent-error rate = silent_error/total; `honest_error`/`abstain` count in neither. Scoring keywords are coupled to the answer language: v0 ships the Chinese marker table; an English table is a v1+ item.
5. `rot`: injects three kinds of drift into an in-memory copy (column rename `orders.total_amount` → `order_amount`; definition tampering `refund_total.expr` gains `refunds.tax`; a new orphan metric `gross_margin` with a missing domain and no evidence), re-runs audit, and reports **new captures** = `|findings_after − findings_before|` (set difference keyed by `rule+subject+detail`). Never writes to disk unless `--write` (then `metrics.rot.yml`).
6. `report`: writes `reports/health-report.md` with three blocks: high/medium findings, rot simulation, controlled evaluation.
7. CI usage: `--fail-on high` exits 1 when high-severity findings exist.
8. Output language: `--lang zh|en` (default `en`). The two variants are written independently for their own context — use `--lang zh` when the conversation is in Chinese so the whole output (headers, severity labels, finding texts, report) is Chinese, not a translation of the English one. This only affects display: the scoring protocol and the fixture content are unchanged.
9. When reporting numbers, distinguish "real execution" (gold/candidate SQL run against the seed) from "simulated answers"; never present simulated data as a live evaluation.

## Usage

```bash
python scripts/hygieia.py audit  fixtures/ecom
python scripts/hygieia.py eval   fixtures/ecom
python scripts/hygieia.py rot    fixtures/ecom
python scripts/hygieia.py report fixtures/ecom
```

Self-test: `python -m unittest discover -s tests -v` (asserts the contract numbers: 65%/100%, silent rates 35%/0%, audit 7 findings, rot 4 new captures).

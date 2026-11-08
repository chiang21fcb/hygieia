# Hygieia: Encoding Contract (English)

> **Authority**: this document is the public English contract of the project.
> The metrics.yml contract, severity mapping, scoring protocol, and rot threat
> model below are binding for implementers. The Chinese counterpart is
> [`docs/contract.zh.md`](contract.zh.md); when the two differ, the Chinese
> version prevails. Ambiguities that neither resolves are settled by the
> assertions in `tests/test_hygieia.py`.
>
> **Language note (for international readers)**: the prose of this document is
> English. Chinese characters appear only where the document quotes **fixture
> data** (the bundled ecom demo mirrors a Chinese data warehouse; metric
> display names, synonyms, and question texts are data, not prose) or **verbatim
> protocol constants** (the Chinese marker table the scorer matches and the
> filler replies it treats as non-compliant; an English marker table also ships,
> selected by answer-language detection). They are quoted exactly as the tool
> consumes them; translating them would make this document stop matching the
> fixture and the scorer. A bilingual internationalized fixture (English
> questions and answers) is a v1+ item.

## Measured numbers (demo reproduction)

Fixture: 6-table e-commerce schema (customers / orders / order_items / products / payments / reviews) + 20 Chinese questions + one deliberately flawed semantic layer (4 fault classes). The two arms' answers are simulated; scoring is real SQL execution.

| Metric | No semantic layer (control) | With semantic layer (treatment) |
|---|---|---|
| Accuracy | 13/20 (65%) | 20/20 (100%) |
| **Silent-error rate** | **7/20 (35%)** | **0/20 (0%)** |

- audit: 7 findings (3 high: R1 synonym conflict, R3 join ambiguity, R4 dangling reference; 4 medium: R5 missing evidence)
- rot: 7 before → 13 after, **6 new captures** (structural 4: column-rename dangling ×2 + orphan metric R2 + missing-evidence R5; semantic 2: stale alias R8 + source-freshness conflict R9. The definition tampering hits a pre-existing R4 and adds none)

Transparency: gold-standard SQL numbers come from real execution against the seed (in-memory SQLite); the two arms' answers are hand-authored (`simulated: true` in `demo_results.json`); the scoring logic is real code per Section 13.

## 11. `metrics.yml` contract (binding)

Minimal v0 schema (field names are fixed; extra fields may be ignored):

```yaml
version: 1
domains:
  - id: sales          # required, unique
    description: "sales domain"  # optional

joins:                 # used by R3; multiple rows for the same (left, right) = ambiguity
  - left: orders
    right: customers
    on_expr: "orders.customer_id = customers.id"

metrics:
  - id: revenue                 # required, unique
    name: 收入                  # display name (fixture data, stays in fixture language)
    synonyms: ["营收", "销售额"] # R1: synonym overlap across metrics is a conflict (fixture data)
    domain: sales               # R2: must exist in domains[].id
    description: "..."          # R6/R7
    expr: "sum(orders.total_amount)"  # R4: parse table.column; table/column must exist in schema
    evidence:                   # R5: missing or empty = medium
      - type: doc               # doc | comment | dashboard
        ref: "wiki/revenue"
    # optional bindings
    table: orders
    grain: order
```

**Optional extensions (v0.2, backward compatible; existing files such as `ecom` need no change):**

- `metrics[].filter`: caliber filter expression (a string, preserved verbatim; not AST-validated in v0). `adapt dbt` merges metric-level and measure-level `filter` into this field; `adapt ossie` never emits it (Ossie writes filtering inside `expression.sql`).
- `dimensions[]`: dimension (field) definitions, produced by `adapt ossie` from `datasets[].fields[]`. Fields: `id` (required, unique), `name`, `table`, `expr`, `synonyms`, `description`. **Dimensions participate in R1 synonym conflicts only** — one phrase pointing at both a field and a metric is the same silent ambiguity; they do not take part in R2/R5/R6/R7, because a dimension is not a metric caliber.

```yaml
dimensions:
  - id: ss_sales_price
    name: ss_sales_price
    table: store_sales
    expr: "ss_sales_price"
    synonyms: ["unit price", "price"]
    description: "Sales price per unit"
```

**`schema.sql` is optional (v0.2)**: when absent, `audit` does not crash and still runs R1/R2/R5/R6/R8/R9; R4 and the table/column checks of R3 are skipped (R3 join ambiguity still runs), and every skipped rule is listed with its reason in the output's `skipped_rules` and on the terminal. `eval` and `rot` still require `schema.sql` + `seed.sql`.

> **Why `on_expr`, not `on`**: YAML 1.1 parses a bare `on` as the boolean key `True`
> (PyYAML `safe_load` included), silently dropping the field. `on_expr` is a stable
> string key, and R3/R4 validation reads it exclusively.

Parsing rules (v0; sqlglot AST, testable):

- extract table.column references from `expr` with the sqlglot AST (sqlite dialect; `hygieia/sql_refs.py`); an unparseable expression is reported explicitly, never silently ignored;
- `joins[].left/right` must be tables in the schema;
- from `joins[].on_expr`, extract table.column references with the same AST and validate each: missing table or column → `R4-dangling-ref` (subject: `join <left>-><right>`);
- synonyms are compared after `strip` + lowercase (Chinese synonyms: exact match);
- description shorter than 8 characters (configurable) → R6; description that, after stripping punctuation, is a simple concatenation of `{table, column, metric id, name}` tokens → R7.

### 11.1 `questions.yaml` minimal fields

```yaml
questions:
  - id: q07
    text: "上个月净收入是多少"   # question text (fixture data)
    gold_sql: |
      SELECT ...
    gold_value: 1110            # cross-checked against SQL execution
    expected_behavior: answer   # answer | clarify
    clarify_reason: null        # required when expected_behavior=clarify
    tags: ["ambiguity", "cancel_filter"]
```

### 11.2 `demo_results.json`

```json
{
  "simulated": true,
  "note": "agent answers are hand-authored for demo; SQL execution results are real",
  "arms": {
    "control": [
      {"qid": "q07", "sql": "...", "value": 1210, "raw": "...", "label_hint": "silent_error"}
    ],
    "treatment": [
      {"qid": "q07", "sql": "...", "value": 1110, "raw": "...", "label_hint": "correct"}
    ]
  }
}
```

The scorer follows Section 13; `label_hint` is for manual proofreading only and must **not** replace automatic scoring (except the `--trust-hints` debug switch).

## 12. Severity, fixes, and false positives

| Severity | Meaning | Default mapping |
|---|---|---|
| high | can directly cause wrong numbers or silent caliber mistakes | R1, R3, R4, R8, R9; (R2 when the domain does not exist) |
| medium | credibility / discoverability impaired; not necessarily a wrong number this time | R5; R2 without table binding but existing domain |
| low | readability / context quality | R6, R7 |

**R1 demonstration baseline (trade-off note)**: in the ecom fixture, `营收` is deliberately double-hung between `revenue` and `net_revenue` to demonstrate the R1 red light; the conflict is **kept on purpose** (removing the synonym would change the demo baseline: 7 findings / 3 high). The live run showed an agent may still pick the right caliber from the "preferred business caliber" description, but the red light is still reported honestly and is not suppressed because "the agent guessed right". Surfacing the conflict is the value of the tool.

Every finding is emitted as (example printed by the CLI with the default English display; the `subject` is quoted fixture data (the synonym itself) and keeps the fixture language):

```json
{
  "rule": "R1-synonym-conflict",
  "severity": "high",
  "subject": "营收",
  "detail": "synonym \"营收\" maps to multiple metrics: revenue, net_revenue",
  "danger": "a query may silently pick the wrong caliber",
  "fix": "keep exactly one metric per synonym, or drop the conflicting synonyms"
}
```

Known false positives / missed detections (also written into the README):

| Rule | Possible false positives | Known misses (v0) |
|---|---|---|
| R1 | intentional alias layering (rare) | cross-file synonyms, near-synonyms |
| R3 | legitimate alternative multi-paths | implicit joins, sub-query paths |
| R4 | dialect functions mistaken for columns | CTE aliases, macros/Jinja |
| R5 | evidence stored outside the repo | stale evidence still counts as present |
| R6/R7 | short but precise descriptions | long but empty boilerplate |
| R8 | a migration alias (not reported when `replaced_by` points at the current metric) | an alias pointing at a metric deleted from the file |
| R9 | multiple sources with an explicit `authoritative: true` (not reported) | freshness conflict that only exists in data, undeclared in the layer |

## 13. Scoring protocol (binding)

### 13.1 Labels (mutually exclusive; judge from the top of the table down)

| label | definition |
|---|---|
| `clarify` | the model/answer explicitly refuses to fabricate, asks for a definition, or points out insufficient data (keyword match or `expected_behavior: clarify`) |
| `abstain` | explicitly says "I don't know / cannot answer" and gives no business number |
| `honest_error` | gives SQL or a number, but execution failed / the answer declares failure |
| `silent_error` | gives a plausible number (or a categorical yes/no), mismatches gold, and does not clarify |
| `correct` | matches gold (see below) |

### 13.2 What counts as "correct"

1. If `expected_behavior: clarify`: a label of `clarify` (or an equivalent abstention with a stated reason) → **correct**; giving a concrete number or a categorical yes/no (including a number appearing in `raw`) → **silent_error**. **Tightening rule (v0 review item H2)**: empty `raw`, or a short reply with no clarifying intent (e.g. "嗯", "好的"), must not default to `clarify`; it is labeled non-conforming `abstain` (not counted in the accuracy numerator). Only an explicit keyword hit (数据不足 / 无法计算 / 需澄清 / 无法回答, etc.) earns `clarify` / `abstain` counted as correct; an `abstain` counted in the numerator must carry explanatory content (a refusal/clarification keyword hit); non-empty `notes` alone does not count. The keyword table is coupled to the answer language: v0 ships a Chinese table and an English table (`unknown` / `cannot compute` / `insufficient data` / `need clarification` / `i don't know`, …), selected by answer-language detection: any CJK character in the answers selects the Chinese table, otherwise the English one. The demo fixture itself stays Chinese.
2. If `expected_behavior: answer`:
   - compare execution results first: `gold_sql` and the candidate `sql` run against the same seed DB; scalar results equal (numeric: relative tolerance `1e-6` or the question's stated absolute tolerance);
   - no SQL, only `value`: compare against `gold_value`;
   - yes/no questions: normalized comparison against the gold boolean/enum.
3. **Accuracy** = correct questions / total questions.
4. **Silent-error rate** = silent_error questions / total questions.
5. `honest_error` / `abstain` are **not** counted in the silent-error rate and not in the accuracy numerator (wrong/unanswered, but not "silent").

### 13.3 Dimension scoring (entity / relation)

Every question is scored on two dimensions so "wrong table" and "wrong caliber" stay distinguishable:

| Dimension | Meaning | Judged by |
|---|---|---|
| entity | entity / table / join path | candidate SQL's table set equals the gold SQL's table set (sqlglot AST) |
| relation | metric caliber (aggregation + filters) | aggregation signature (function + column) and WHERE filter-column set equal the gold's |

Rules: a `correct` answer counts on both dimensions; `expected_behavior: clarify`, unparseable gold, or a candidate without SQL scores on neither (not attributable, no credit).
The report shows per-arm accuracy and silent rate for both dimensions and runs a **regression check**: when treatment's overall score rises but a dimension drops below control or the previous run, that dimension is flagged.

### 13.4 Run manifest (pinned versions)

Every `eval` writes `reports/manifest.json` with:

| Field | Meaning |
|---|---|
| `hygieia_version` | tool version |
| `model` | answering model (`simulated (hand-authored)` for the demo; from `meta.json` for live runs) |
| `prompt_sha256` | combined hash of `fixtures/<fx>/prompts/{control,treatment}.md` |
| `questions_sha256` / `corpus_sha256` / `semantic_sha256` | snapshots of the question set, corpus (schema+seed), and semantic layer |
| `timestamp` / `run_id` | time and run id (ignored when comparing) |
| `aggregates` | per-arm totals and dimension summaries (used by the regression check) |

Comparability uses only `hygieia_version / model / prompt_sha256 / questions_sha256 / corpus_sha256 / semantic_sha256`;
any difference means the two runs are **not directly comparable**, and `report` must say so.

### 13.5 Demo expectations (ecom / simulated answers)

- control: accuracy 13/20, silent errors 7/20; entity 17/20, relation 13/20
- treatment: accuracy 20/20, silent errors 0/20; entity 20/20, relation 20/20

After implementation, run the same scorer against `demo_results.json` and assert these numbers; if fixture tweaks change gold values, update this section and the numbers section together. Code-only changes without doc updates are forbidden.

## 14. rot threat model

### 14.1 v0 must inject (aligned with the numbers above)

| Injection | Operation | Expected new findings |
|---|---|---|
| Column rename | schema-side `orders.total_amount` is treated as gone (or renamed), while the semantic layer still references it | R4 ×2 (revenue, avg_order_value, …) |
| Definition tampering | `refund_total.expr` gains a `refunds.tax` reference | none new (this R4 already exists before the drift; per the "new captures" rule only post-rot finding ids are counted) |
| Orphan metric | add `gross_margin` with `domain: finance` (no such domain id), no evidence | R2 + R5 |

**New-capture count** = `|findings_after − findings_before|` (set difference keyed by `rule+subject+detail`). Target = **4** (column-rename dangling ×2 + orphan-metric R2 + missing-evidence R5; the tampering hit on the pre-existing R4 adds none).

### 14.2 v0 deliberately does not inject (may be listed as "uncovered drift" in the report)

- synonym drift (a good word pointing at a bad metric)
- a third join path
- stale evidence / dead links
- descriptions turned into tautology (pure R7)
- time-grain or unit/currency mismatches

Left for v1+ to keep the demo scope bounded.

## Acceptance and background (summary)

- Acceptance: run `audit` / `eval` / `rot` / `report` offline on `fixtures/ecom`; audit ≥7 findings including R1/R3/R4 high; rot new captures ≥6; eval reproduces 65%/100% and 35%/0%; report contains three blocks; rule triggers, severity, and labels must match Sections 11–14 above. v0 explicitly does not do: UI, multi-tenancy, multi-dialect parsing, real LLM calls, third-party modeling adapters, permission/action-safety auditing.
- Overview: an agent skill, pure local offline, a ~300–400-line script + 6-table fixture + 20 Chinese questions; the demo narrative is silent errors on ambiguity questions; report format is three blocks; roles are the analytics-engineer PR gate, the nightly platform report, and incident post-mortems.
- Glossary: 本体/语义层 interchangeable for the content of `metrics.yml` (not OWL formal ontologies); 静默错答 = a number/categorical answer that is wrong, with no error and no clarification; 腐烂 = definitions drifting stale relative to the real world; control/treatment = without vs with the semantic layer.
- Open questions (research tracking, not blocking v0): multi-hop operationalization at 50 questions; interview phrasing for the pain point; stable finding ids `hash(rule, subject)` for CI diffs; Chinese synonym normalization (full/half-width, homophones) vs exact match.
- Suggested implementation order: fixture → schema loading → R1–R7 audit → rot three injections → eval scorer → report renderer → CLI + README/SKILL triggers → self-tests asserting the numbers above, plus a "broken synonym adds an R1" unit test.

---

*Repository name `hygieia`; CLI entry `scripts/hygieia.py`.*

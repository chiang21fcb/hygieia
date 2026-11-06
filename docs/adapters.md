# Adapters (read-only) — dbt / MetricFlow → `metrics.yml`

Hygieia audits the `metrics.yml` contract. The `adapt dbt` command maps an
external semantic-layer export onto that contract **read-only**, so anything
dbt or MetricFlow can define can be handed to Hygieia as a downstream quality
gate. It never writes back to the source system and never bootstraps.

## Usage

```bash
python scripts/hygieia.py adapt dbt \
  --in fixtures/adapt_dbt_mini/dbt_semantic.yml \
  --out fixtures/adapt_dbt_mini            # or an explicit <dir>/semantic/metrics.yml
```

The output is a standard `metrics.yml`; run `audit` on the same fixture
directory to get findings:

```bash
python scripts/hygieia.py audit fixtures/adapt_dbt_mini
```

## Input assumptions (dbt Semantic Layer / MetricFlow YAML subset, v0)

```yaml
semantic_models:
  - name: orders              # table name in the schema
    entities:
      - name: customer_id     # used for joins
        type: foreign
    measures:
      - name: total_amount    # measure name = column name in v0
        agg: sum              # sum | min | max | count | count_distinct | average
metrics:
  - name: revenue
    type: simple              # simple | ratio
    type_params:
      measure: total_amount
    group: sales              # optional → metrics.yml domain
    description: "..."        # optional
joins:                        # optional; explicit only
  - left: orders
    right: customers
    on_expr: "orders.customer_id = customers.id"
```

## Field mapping

| Input | Output `metrics.yml` | Notes |
|---|---|---|
| `metric.name` | `id` / `name` | required, unique |
| `type: simple` + `type_params.measure` | `expr = agg(<model>.<measure>)` | agg table above; unknown agg → skipped |
| `type: ratio` + `numerator` / `denominator` | `expr = (agg(num)) / (agg(den))` | both measures must resolve to exactly one semantic model |
| `group` | `domain` (+ `domains[]`) | optional |
| `description` | `description` | optional |
| `joins[].left/right/on_expr` | `joins[]` | **must** be a string `on_expr`; a bare `on` key cannot be mapped (YAML 1.1 parses it as boolean `True`) |
| — | `evidence` | **never fabricated**: omitted, so the existing R5 rule fires honestly |
| `synonyms` | — | input has no alias field in v0; `synonyms: []` |

## Skipped (never guessed)

Anything the subset cannot map faithfully is listed on stderr with a reason
and omitted from the output:

- metric types other than `simple` / `ratio` (e.g. `cumulative`, `derived`)
- measures with unsupported aggregations
- a measure that resolves ambiguously across semantic models
- joins without a string `on_expr`

## Non-goals (v0)

- no bootstrap / intake / human review gates — Hygieia only verifies what
  already exists
- no write-back to dbt / MetricFlow — the adapter is read-only
- no crawling of dbt projects or `ref('...')` resolution — the input must be a
  self-contained YAML export
- no other ecosystems yet (external ontology trees are a documented v1
  candidate)

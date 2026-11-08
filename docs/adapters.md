# Adapters (read-only): dbt / Ossie → `metrics.yml`

Hygieia audits the `metrics.yml` contract. Adapters map an external semantic-layer
export onto that contract **read-only**, so anything the source can define can be
handed to Hygieia as a downstream quality gate. They never write back to the source
system and never bootstrap.

Two entry points:

| Command | Input | Status |
|---|---|---|
| `adapt dbt` | dbt Semantic Layer / MetricFlow YAML | v0 mapper, expr/filter-faithful |
| `adapt ossie` | Apache Ossie (OSI) semantic-model YAML | v0.2 mapper, first-class input |

Long term, Ossie is the recommended front door: it is a neutral interchange format,
so one mapper covers every vendor that exports it. dbt users can keep running
`adapt dbt` first and treat Ossie as the convergence path.

## Usage

```bash
pip install -e .   # once; gives you the `hygieia` command

# dbt
hygieia adapt dbt \
  --in fixtures/adapt_dbt_jaffle/semantic_model.yaml \
  --out .tmp/adapt_dbt                      # writes .tmp/adapt_dbt/semantic/metrics.yml

# Ossie (no schema.sql required for the audit step)
hygieia adapt ossie \
  --in fixtures/ossie_tpcds/ossie_semantic_model.yaml \
  --out .tmp/ossie_tpcds

# then audit the adapted layer
hygieia audit .tmp/ossie_tpcds
hygieia audit fixtures/adapt_dbt_mini
```

`--out` may be a directory (output goes to `<dir>/semantic/metrics.yml`) or an
explicit `.../metrics.yml` path. Skipped items are printed on stderr with a reason
and are **never** silently dropped.

## dbt input assumptions (v0)

```yaml
semantic_models:
  - name: orders              # semantic model name
    model: ref('orders')      # physical table; a bare `model: orders` works too
    measures:
      - name: order_total     # list form …
        agg: sum              # sum | min | max | count | count_distinct | average
        expr: amount          # optional; when absent, the measure name is used
        filter: "status <> 'cancelled'"   # optional, preserved verbatim
  - name: customers
    measures:
      customer_count:         # … or dict-keyed-by-name form
        agg: count
        expr: customer_id
metrics:
  - name: revenue
    type: simple              # simple | ratio
    type_params:
      measure: order_total
    group: sales              # optional → metrics.yml domain
    description: "..."        # optional
    filter: "..."             # optional, merged with the measure filter
  - name: avg_order_value     # newer dbt spec: agg/expr on the metric itself
    type: simple
    agg: avg
    expr: amount              # table/model optional; inferred from a qualified expr
joins:                        # optional; explicit only
  - left: orders
    right: customers
    on_expr: "orders.customer_id = customers.id"
```

## dbt field mapping

| Input | Output `metrics.yml` | Notes |
|---|---|---|
| `metric.name` | `id` / `name` | required, unique |
| `type_params.measure` + measure `agg`/`expr` | `expr = agg(<model>.<expr>)` | `expr` wins over the measure name; never assumes `name == column` |
| measure `expr: "1"` with `agg: count` | `expr = count(1)` | non-identifier expressions are wrapped verbatim |
| measure `expr: CASE WHEN …` | `expr = sum(CASE WHEN …)` | unqualified columns resolve through the metric's `table` |
| metric `filter` + measure `filter` | `metrics[].filter` | joined with ` and `, preserved verbatim (Jinja allowed) |
| `type: simple` + metric `agg`/`expr` | `expr = agg(expr)` | newer dbt spec without measures; table comes from `table`/`model` or a qualified `expr` |
| `type: ratio` | `expr = (agg(num)) / (agg(den))` | both measures must resolve to exactly one semantic model |
| `group` | `domain` (+ `domains[]`) | optional |
| `description` | `description` | optional |
| `joins[].left/right/on_expr` | `joins[]` | **must** be a string `on_expr`; a bare `on` key cannot be mapped (YAML 1.1 parses it as boolean `True`) |
| — | `evidence` | **never fabricated**: omitted, so the existing R5 rule fires honestly |
| `synonyms` | — | dbt has no alias field in this subset; `synonyms: []` |

## Ossie input assumptions (v0.2)

Ossie / OSI (Apache) is a neutral semantic-model exchange format. The mapper reads
`datasets`, `relationships`, `semantic_model`-wrapped variants, `metrics`, and
`ai_context.synonyms`; the checked-in fixture is a trimmed copy of
[`apache/ossie` examples/tpcds_semantic_model.yaml](https://github.com/apache/ossie/blob/main/examples/tpcds_semantic_model.yaml)
(Apache-2.0 header retained).

```yaml
name: tpcds_retail_model
datasets:
  - name: store_sales
    source: tpcds.public.store_sales     # physical table = last segment
    fields:
      - name: ss_sales_price
        expression: {sql: ss_sales_price}
        description: …
        ai_context:
          synonyms: ["unit price", "price"]
    metrics:
      - name: total_quantity
        expression: {sql: SUM(ss_quantity)}
relationships:
  - name: store_sales_to_item
    from: store_sales
    to: item
    from_columns: [ss_item_sk]
    to_columns: [i_item_sk]
metrics:                                  # model-level, may span datasets
  - name: total_profit
    expression: {sql: SUM(store_sales.ss_net_profit)}
    ai_context:
      synonyms: ["net profit", "profit"]
```

## Ossie field mapping

| Ossie | `metrics.yml` | Notes |
|---|---|---|
| `datasets[].name` | `domains[].id` | one domain per dataset |
| `datasets[].source` | physical table name | last dotted segment; falls back to the dataset name |
| `datasets[].fields[]` | `dimensions[]` | `id`, `name`, `table`, `expr`, `synonyms`, `description`; `kind: dimension` |
| field `ai_context.synonyms` | `dimensions[].synonyms` | checked by R1 |
| `datasets[].metrics[]` | `metrics[]` | `domain`/`table` = the owning dataset |
| top-level `metrics[]` | `metrics[]` | `domain`/`table` set only when the expression references exactly one dataset |
| `metrics[].ai_context.synonyms` | `metrics[].synonyms` | checked by R1 |
| `relationships[]` (`from_columns`/`to_columns`) | `joins[]` (`on_expr`) | multiple columns joined with ` AND `; `expression.sql` also accepted |
| `ai_context.instructions`, dataset/relationship synonyms, `custom_extensions[]`, `datatype`/`dimension.is_time` | — | listed in `skipped` with a reason: the v0 contract has no field for them, and inventing one would misrepresent the source |

Because Ossie models rarely ship DDL, `schema.sql` is optional: `audit` then runs
R1/R2/R5/R6/R8/R9 and lists R4 (plus the table/column parts of R3) in
`skipped_rules`. On the public TPC-DS sample this produces the three upstream
vocabulary collisions — `price`, `location`, `profit` — as `R1-synonym-conflict`
(see [public-layers.md](public-layers.md)).

## Skipped (never guessed)

Anything the mapper cannot represent faithfully is listed on stderr with a reason
and omitted from the output:

- dbt: unsupported metric types (`cumulative`, `derived`, …), unsupported aggregations,
  measures resolving ambiguously across semantic models, joins without a string `on_expr`
- Ossie: datasets/fields/metrics without a name, expressions without `sql`, relationships
  without columns or expression, duplicate metric ids, vendor extensions, and the
  contract-less metadata listed above

## Non-goals (v0)

- no bootstrap / intake / human review gates; Hygieia only verifies what already exists
- no write-back to dbt / MetricFlow / Ossie; adapters are read-only
- no crawling of dbt projects or `ref('...')` resolution; the input must be a
  self-contained YAML export
- no `adapt cube`, no OWL/SHACL, no graph-database adapters

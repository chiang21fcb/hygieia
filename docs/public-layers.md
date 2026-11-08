# Public layers we have run on

Scope rule: this file only records results that are reproducible from this repository
with the commands shown. No private warehouse, no customer data, no numbers we cannot
re-run. Each entry states the date, the exact command, the findings that matter, and
what the run does **not** prove.

## 2026-11-08 — Apache Ossie TPC-DS semantic model (public, OSI)

**Source.** [`apache/ossie` examples/tpcds_semantic_model.yaml](https://github.com/apache/ossie/blob/main/examples/tpcds_semantic_model.yaml)
(neutral interchange format; upstream Apache-2.0 license header kept).

**Fixture.** [`fixtures/ossie_tpcds/ossie_semantic_model.yaml`](../fixtures/ossie_tpcds/ossie_semantic_model.yaml)
— a trimmed copy (3 of 5 datasets, 2 of 4 relationships, 4 metrics) keeping the upstream
vocabulary verbatim. Nothing was injected: `price`, `location` and `profit` are declared
twice in the upstream file.

**Commands** (from the repository root; no `schema.sql` involved):

```bash
hygieia adapt ossie \
  --in fixtures/ossie_tpcds/ossie_semantic_model.yaml \
  --out .tmp/ossie
hygieia audit .tmp/ossie
```

**Key findings — `audit` reports 7 findings (high 3 / medium 4 / low 0):**

| Rule | Severity | Subject | Why it is real |
|---|---|---|---|
| `R1-synonym-conflict` | high | `price` | `store_sales.ss_sales_price` and `item.i_current_price` both declare it |
| `R1-synonym-conflict` | high | `location` | `store_sales.ss_store_sk` and `store.s_city` both declare it |
| `R1-synonym-conflict` | high | `profit` | the `total_profit` metric and `store_sales.ss_net_profit` both declare it |
| `R5-no-evidence` ×4 | medium | `total_quantity`, `total_sales`, `total_profit`, `customer_lifetime_value` | Ossie has no evidence field, so the layer declares no source evidence |

`skipped_rules` (printed, not hidden): `R4-dangling-ref` and the table/column checks of
`R3-join-ambiguity`, because the sample ships no DDL. R3 join **ambiguity** still ran
(no duplicate pairs). R2 did not fire: each metric resolves to exactly one dataset.

**What this run does not prove.** It does not prove that the TPC-DS model is wrong for
TPC-DS users, only that three everyday words are ambiguous in the layer — an agent
asking "price by store" has two defensible readings. It also does not exercise the
AST/physical-column path (no DDL) and does not include the upstream window-function
metrics (trimmed out to keep the fixture small).

## 2026-11-08 — `ecom` demo fixture (synthetic)

**Source.** Bundled fixture, synthetic data, Chinese questions.

```bash
hygieia audit fixtures/ecom                       # 7 findings: 3 high / 4 medium
hygieia rot fixtures/ecom                         # 6 new captures: structural 4 | semantic 2
hygieia eval fixtures/ecom                        # control 65% / 35%, treatment 100% / 0%
```

**What this proves.** That the checks fire on a deliberately broken layer and that the
two-arm protocol produces the documented numbers. **What it does not prove:** the
numbers are a **simulated demo** (answers hand-authored, `simulated: true`); they are
not a live-model evaluation. The one real live run is recorded in
[`fixtures/ecom/runs/live-20261106-dsh/`](../fixtures/ecom/runs/live-20261106-dsh/)
and in the README's "Live run" note.

## Not yet run

- Any private or vendor-hosted semantic layer (Cube, AtScale, LookML) — no adapter, no claim.
- Ossie models with a `schema.sql` surface (would exercise R4); planned with the next public sample.
- Multi-dialect parsing (sqlite only today).

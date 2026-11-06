# Live run: live-20261106-dsh

- **Model**: dsh-coding-agent (deepseek-v4-flash), acting as the answering agent
- **Date**: 2026-11-06 · **simulated**: false
- **Prompt version**: repo main `3506400` at run time

## Scores (scored by the repo's `eval`)

| Arm | Correct | Silent error | Accuracy | Silent rate |
|---|---|---|---|---|
| control (no semantic layer) | 16/20 | 4/20 | 80.0% | 20.0% |
| treatment (with semantic layer) | 19/20 | 1/20 | 95.0% | 5.0% |

## Methodology (transparency)

1. **Control arm**: the answering agent reasoned from `schema.sql` + the seed
   data only — `semantic/metrics.yml` was not opened until the control arm was
   fully composed.
2. **Treatment arm**: answers go through `semantic/metrics.yml` + schema:
   metric exprs, synonyms, and joins where a question maps to a metric;
   clarification/refusal where the layer cannot express it (q11 conversion
   rate — no visit data; q20 shipping scope — no shipping column anywhere).
3. Every submitted SQL was executed against the in-memory SQLite seed;
   `value` = the executed result, `raw` = the agent's final answer text.
4. The answering agent did **not** consult `questions.yaml` gold SQL or
   `demo_results.json` while composing either arm.

## Error analysis

- **q08 / q10 (control, silent ×2)**: 总收入 / 营收 answered as 1860
  (all orders) but gold is the non-cancelled scope (1760). With only column
  names, the control agent cannot distinguish 营收/总收入 from 净收入 — the
  classic no-semantic-layer cost.
- **q12 (control, silent ×1)**: average order value answered as 155 (all
  orders); gold is 176 (non-cancelled). Same 口径 (definition) trap.
- **q14 (both arms, silent ×2)**: top customer spend answered as 430
  (includes the cancelled order o110); gold is 390 (non-cancelled). The
  semantic layer has no customer-dimension metric or 口径, so the treatment
  agent fell back to raw schema SQL and used the wrong scope. **Suggested
  follow-up audit item (does not change R1–R7):** add a customer-dimension
  metric/口径 (e.g., per-customer spend, non-cancelled scope).
- **Treatment fixed q08/q10/q12**: `net_revenue` (sum of `net_amount`,
  cancelled rows are zero) and `avg_order_value` (non-cancelled CASE WHEN)
  corrected the definitions → silent rate 20% → 5%.
- **R1 synonym conflict observed live**: 营收 is a synonym of both `revenue`
  and `net_revenue`; the agent resolved it per the "业务口径首选" description
  (net_revenue) and flagged the ambiguity in `raw`. No wrong number resulted,
  but the conflict is real and audit already flags it.

## Conclusion

The semantic layer cut the silent-error rate from 20% to 5% on real answers
(this agent, this run). The residual q14 shows a real gap: a missing
customer-dimension 口径 — model behavior, not a scorer defect. The demo
numbers (65%/35% vs 100%/0%) remain the simulated-ideal baseline; live runs
are reproducible per `docs/eval-live.md`.

## Post-run follow-up (layer gap closed, numbers not re-run)

After this run, `fixtures/ecom/semantic/metrics.yml` gained a
`customer_spend` metric (per customer, non-cancelled orders only,
`sum(orders.net_amount)`; per-customer top = 390, matching q14's gold).
The metric is designed not to move the demo baseline: it references
`net_amount` (not the rot-renamed `total_amount`) and carries evidence, so
audit stays at 7 findings (3 high) and rot stays 7→11 (4 new captures).

**The live answers above were NOT re-run against the enriched layer.** The
20/0 and 16/4 numbers remain the record of that run; a fresh run under the
new caliber would need to be produced and stored as a new `runs/<id>/`.

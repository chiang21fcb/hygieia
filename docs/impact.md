# impact: from a git diff to affected metrics

`impact` maps a unified diff onto the metrics whose definitions reference the
changed tables/columns, so a reviewer sees at a glance which metrics an
upstream change touches and should be re-audited.

## Usage

```bash
# from a patch file
hygieia impact fixtures/ecom --diff change.patch

# from a git range (CI style)
git diff <base>...<head> | hygieia impact fixtures/ecom --diff -
```

`--lang zh|en` switches the report language (default `en`). Exit code is
always 0 unless the command itself fails. Findings are informational.

CI runs this on every push (diff of the pushed commit) and every pull request
(base...head, whole repository, not just `fixtures/`), with
`continue-on-error: true`: the report is a review aid and never blocks a
merge.

## Input assumptions (v0)

- A **unified diff** of the fixture directory (`schema.sql` /
  `semantic/metrics.yml`). Only the `+`/`-` lines are scanned.
- Changed references are `table.column` tokens on those lines (SQL is parsed
  with the **sqlite dialect** via sqlglot; multi-dialect parsing is a v1+
  item). Unqualified schema-DDL lines (e.g. `total_amount REAL`) yield no
  tokens; the file header is still reported, which is the cue to run `audit`.
- The semantic layer is loaded from `fixtures/<dir>/semantic/metrics.yml`;
  every metric `expr` and every join `on_expr` is parsed with the same
  extractor as `rule_r4`.

## Mapping rule

A metric is **affected** when any `(table, column)` reference in its
`expr` / `on_expr` matches a changed token, including table-level matches
(`orders.*`) and whole-table changes represented as `(table, "")`.

## Output schema

```text
changed files: fixtures/ecom/semantic/metrics.yml
changed references: orders.total_amount
2 affected metrics (run audit on fixtures/ecom):
  revenue (expr): orders.total_amount
  avg_order_value (expr): orders.total_amount
```

Machine-readable form: `impact --json` emits

```json
{"files_changed": ["..."], "changed": [["orders", "total_amount"], ...],
 "affected": [{"metric": "revenue", "kind": "expr", "refs": [["orders", "total_amount"]]}]}
```

## Parse-failure semantics

An expression that cannot be parsed is **never silently treated as
"no references"**:

- in `audit`, it becomes a high `R4-dangling-ref` finding with
  `detail: ... unparseable: <error>` (the references cannot be verified);
- in `impact`, the metric is listed as affected with the parse error in place
  of references.

The same rule drives `rule_r4`: `expr_refs` raises on parse failure and the
caller decides how to surface it.

## Non-goals (v0)

- no multi-dialect SQL parsing (sqlite only);
- no symbol-resolution of `ref('...')` or dbt macros; the diff is matched
  against the semantic layer as-is;
- no automatic gate: `impact` reports; the existing CI gate
  (`--fail-on high`) stays the only blocking check.

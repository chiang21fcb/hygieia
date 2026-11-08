# Consumer CI example — three steps, copy-paste

This is a tiny repository-shaped example: a `semantic/` directory, a `schema.sql`, and
a GitHub workflow that runs Hygieia on every change to the semantic layer. Copy the
three pieces into your repo and you are done.

## What you get

- a failing check when a definition is already broken (`--fail-on high`);
- SARIF annotations on the changed files in the PR;
- `hygieia-audit.json` + `hygieia.sarif` as downloadable artifacts;
- a step-summary table of high/medium findings.

## Step 1 — copy the semantic layer

```bash
mkdir -p semantic
cp examples/consumer-ci/semantic/metrics.yml semantic/metrics.yml
cp examples/consumer-ci/schema.sql schema.sql        # optional, enables R3/R4
```

`schema.sql` is optional: without it, `audit` still runs R1/R2/R5/R6/R8/R9 and lists
R4 (plus the table/column checks of R3) in `skipped_rules`.

## Step 2 — copy the workflow

```bash
mkdir -p .github/workflows
cp examples/consumer-ci/.github/workflows/hygieia.yml .github/workflows/hygieia.yml
```

The workflow only fires when `semantic/**` or `schema.sql` changes:

```yaml
on:
  pull_request:
    paths: ["semantic/**", "schema.sql"]
  push:
    branches: [main]
    paths: ["semantic/**", "schema.sql"]
```

It needs `permissions: security-events: write` for the SARIF upload; if code scanning
is not enabled in your repo, set `upload-sarif: "false"` (the JSON/SARIF artifacts
still work).

## Step 3 — try it locally first

```bash
pip install "hygieia-sl @ git+https://github.com/chiang21fcb/hygieia.git"
hygieia audit . --fail-on high     # exit 1
```

Expected output for the bundled example:

```
== audit: . ==
Total 1 findings (high 1 / medium 0 / low 0)
🔴 High R1-synonym-conflict [revenue]：synonym "revenue" maps to multiple metrics/fields: revenue, net_revenue
   danger: a query may silently pick the wrong caliber
   fix: keep exactly one metric per synonym, or drop the conflicting synonyms
❌ --fail-on high: 1 findings reach the gate, exit 1
```

To see the green path, remove the duplicate `synonyms: ["revenue"]` entry from
`net_revenue` (or give it its own alias) and run the same command: exit 0, no findings.
`order_count` has no `evidence`, so it stays a medium R5 finding — visible in the step
summary but below the `high` gate.

## Where the numbers come from

The audit is static and offline: no database connection, no API key. It reads
`semantic/metrics.yml` (+ optional `schema.sql`) and checks nine rule classes;
see [docs/contract.en.md](../../docs/contract.en.md) and
[docs/integrate-ci.md](../../docs/integrate-ci.md).

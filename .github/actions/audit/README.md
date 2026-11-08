# `hygieia/.github/actions/audit` — composite GitHub Action

Runs Hygieia's static audit against a semantic layer, writes SARIF so findings land
on the PR's Files-changed view, uploads the JSON result as an artifact, writes a step
summary, and fails the job when findings reach the configured severity.

## Usage

```yaml
name: semantic-layer
on:
  pull_request:
    paths: ["semantic/**", "schema.sql"]

permissions:
  contents: read
  security-events: write   # required by github/codeql-action/upload-sarif

jobs:
  hygieia:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: chiang21fcb/hygieia/.github/actions/audit@main
        with:
          path: .                 # directory containing semantic/metrics.yml
          fail-on: high           # high | medium | low | none
```

`path` is the fixture directory, not a file: it must contain `semantic/metrics.yml`.
`schema.sql` is optional; when absent, R4 and the table/column checks of R3 are listed
in `skipped_rules` instead of failing the run.

Use `fail-on: none` when you only want the report/SARIF and no gate (this is how the
Hygieia repo self-tests the action, because `fixtures/ecom` intentionally has 3 high
findings).

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `path` | — (required) | fixture directory (`semantic/metrics.yml` inside) |
| `fail-on` | `high` | severity gate passed to `hygieia audit --fail-on`; `none` disables gating |
| `args` | `""` | extra CLI args, e.g. `--lang zh` |
| `sarif-file` | `hygieia.sarif` | SARIF 2.1.0 output path |
| `json-file` | `hygieia-audit.json` | machine-readable audit output |
| `upload-sarif` | `true` | run `github/codeql-action/upload-sarif@v3` |
| `artifact-name` | `hygieia-audit` | name of the uploaded artifact (JSON + SARIF) |

## Outputs

| Output | Meaning |
|---|---|
| `exit-code` | gated audit exit code (`0` pass, `1` gate hit) |
| `findings-total` | total findings |
| `findings-high` | high-severity findings |
| `json-file` / `sarif-file` | paths of the produced files |

## What the SARIF looks like

One SARIF result per finding, `level` = `error` (high) / `warning` (medium) /
`note` (low), `ruleId` = rule id (`R1-synonym-conflict`, …). Findings carry no line
numbers (the subject is a metric or synonym), so every result points at
`semantic/metrics.yml:1` and keeps the subject in `logicalLocations` plus
`properties.subject` / `properties.fix`.

## Notes

- The action installs Hygieia from the repository that contains the action
  (`$GITHUB_ACTION_PATH/../../..`), so it always runs the same revision as the action ref.
- `security-events: write` is only needed when `upload-sarif: true`. Without code
  scanning enabled on the repo, the upload step fails; set `upload-sarif: "false"` in
  that case (the JSON/SARIF artifacts still upload).
- On pull requests from forks, GitHub downgrades the token; SARIF upload is typically
  skipped or fails. Use the artifact + step summary in that case.

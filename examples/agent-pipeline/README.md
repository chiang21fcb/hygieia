# Agent-pipeline example — audit gate before answering

This is a **shell skeleton**, not an agent. It shows the ordering an agent pipeline
should use so a broken semantic layer cannot silently produce an answer:

```
read semantic layer ──▶ generate answer ──▶ write runs/<id>/
                                      ──▶ hygieia audit --fail-on high
                                              │
                              exit 0 ─────────┴──────── exit 1
                                 │                        │
                        send the answer          reply "needs clarification"
                                                 + attach the findings
                                      (optional) ──▶ hygieia eval --results runs/<id>
```

## Run it

```bash
# 1) the gate blocks a layer with high findings (writes a clarification draft)
./gate.sh ../../fixtures/ecom /tmp/hygieia-run
# gate: blocked — wrote /tmp/hygieia-run/reply.md

cat /tmp/hygieia-run/reply.md   # clarification table with rule/subject/detail/fix

# 2) a clean layer passes and is allowed to answer
./gate.sh ../../fixtures/adapt_dbt_mini /tmp/hygieia-run-ok
# gate: pass — no high findings; the answer may be sent
```

Exit codes:

| Code | Meaning | What the pipeline does |
|---|---|---|
| `0` | audit passed | send the answer; optionally run `eval` |
| `2` | blocked (high findings) | send `run_dir/reply.md` instead of the answer |
| `1` | usage error / unexpected failure | fail the job, do not answer |

`audit --json` writes pure JSON to stdout (the gate message goes to stderr), so
`run_dir/audit.json` is always parseable.

## Run directory convention

Aligned with [docs/eval-live.md](../../docs/eval-live.md), so the same directory can
be scored later:

```
runs/<run_id>/
├── meta.json        {"run_id", "timestamp", "model", "simulated": false,
│                     "prompt_version", "note"}
├── control.json     answers from the arm without the semantic layer
├── treatment.json   answers from the arm with the semantic layer
├── notes.md         optional, free-form
├── audit.json       written by gate.sh (machine-readable audit)
└── reply.md         written by gate.sh, only when blocked
```

`control.json` / `treatment.json` entries use the same shape as
`fixtures/ecom/demo_results.json`: `{"qid", "sql"?, "value"?, "raw"?}`. The manifest
(`reports/manifest.json`) records `model`, `prompt_sha256`, `questions_sha256`,
`corpus_sha256`, `semantic_sha256`, `hygieia_version`, so two runs are only compared
when the layer and prompts are unchanged.

## Wiring it into a real agent

1. Before answering, load `semantic/metrics.yml` (or run `adapt dbt` / `adapt ossie`
   to produce it from the platform's own export).
2. Generate the answer, then write the run directory (`answers` + `meta.json`).
3. Run `hygieia audit <layer> --fail-on high --json`; treat `exit 1` as "needs
   clarification", not as a crash.
4. Only on `exit 0` send the answer. Always attach the audit artifact so the user can
   see what the gate saw.
5. Optional: `hygieia eval <fixture> --results runs/<id>` to score the run; note that a
   scoring manifest mismatch means the two runs are not comparable.

The gate is deliberately narrow: Hygieia checks definition health (synonyms, joins,
dangling refs, evidence, staleness). It does not validate SQL compilation — use your
platform's compiler (`dbt sl validate`, SemCI) for that.

See [docs/integrate-agent.md](../../docs/integrate-agent.md) for the full write-up.

# runs/ — live two-arm evaluation protocol

`eval` scores whatever two-arm answer files you point it at. Real agent runs
happen **outside this repo** — an agent answers `../questions.yaml` with and
without the semantic layer — and the answers are dropped into a run directory
for Hygieia to score:

```
fixtures/ecom/runs/<run_id>/
├── meta.json          run_id, timestamp, model/agent name, simulated, prompt version
├── control.json       one arm: list of answers {qid, raw?, sql?, value?}
├── treatment.json     the other arm: same schema as control.json
└── notes.md           optional, free-form
```

`control.json` / `treatment.json` entries mirror the single-arm structure of
`../demo_results.json` (each answer has `qid` plus any of `raw` / `sql` /
`value`; `label_hint` is a debug-only override). `meta.json` carries
`run_id`, an ISO timestamp, the model/agent name, `simulated: false` for real
runs, and the prompt version.

Score a run with:

```bash
hygieia eval fixtures/ecom --results fixtures/ecom/runs/<run_id>
```

The committed `demo_results.json` (`simulated: true`) stays the regression
baseline. Prompt templates and protocol details: [docs/eval-live.md](../../docs/eval-live.md).

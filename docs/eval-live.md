# eval-live: scoring real two-arm agent runs

`demo_results.json` (`simulated: true`) proves the scorer with fixed answers.
Live evaluation is the same scorer pointed at **real answers produced outside
this repo** by a data agent. Nothing here calls an LLM API; the repo only
scores whatever lands in a run directory.

## Run layout

```
fixtures/ecom/runs/<run_id>/
├── meta.json          {"run_id", "timestamp", "model", "simulated", "prompt_version", "note"?}
├── control.json       one arm: [{qid, raw?, sql?, value?}, ...]
├── treatment.json     the other arm: same schema
└── notes.md           optional, free-form
```

`control.json` / `treatment.json` entries are the same shape as the arms of
`demo_results.json`. `label_hint` is a debug-only override (used with
`--trust-hints`); it never replaces automatic scoring.

## Scoring

```bash
python scripts/hygieia.py eval fixtures/ecom --results fixtures/ecom/runs/<run_id>
```

- The scorer answers questions from `fixtures/ecom/questions.yaml` and checks
  SQL / values against the seeded database.
- Keyword tables are selected by **answer-language detection**: if any `raw`
  contains CJK characters the Chinese marker table applies, otherwise the
  English table (`unknown`, `cannot compute`, `insufficient data`, …).
- The H2 tightening rule holds for both languages: empty or filler replies
  (`嗯`, `好的`, `ok`) on clarify questions never count as correct.
- `--lang zh` only changes the display language, never the scoring keywords.

## Two-arm prompt template (for the external agent)

Both arms answer the same 20 questions from `questions.yaml`. The agent may
run any SQL it believes correct; it must write `raw` exactly as it would
answer a user.

**Control arm** (no semantic layer):

> You are a data analyst. Answer each question from the database. If you
> cannot, say why. Return: `{"qid": "...", "sql": "..."?, "value": ...?,
> "raw": "your final answer"}`.

**Treatment arm** (semantic layer only):

> Same, but you must answer through the semantic layer: pick metrics from
> `semantic/metrics.yml`, join per `joins[].on_expr`, express answers as SQL
> over the raw tables. If the layer cannot express the question, say so in
> `raw` (no guessing, no invented metrics).

Write the two answer lists into the run directory, set
`meta.json` → `simulated: false`, and score.

## Regression guarantee

The default `eval fixtures/ecom` still reads `demo_results.json` and must keep
reproducing 65%/35% (control) and 100%/0% (treatment). Any change to the
scorer must pass `python -m unittest discover -s tests -v`.

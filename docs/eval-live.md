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

The scorer writes its version lock to `fixtures/ecom/reports/manifest.json` (generated, not tracked):
model, `prompt_sha256`, `questions_sha256`, `corpus_sha256`, `semantic_sha256`,
`hygieia_version`, `timestamp`, and the per-arm aggregates used by the regression check.

`control.json` / `treatment.json` entries are the same shape as the arms of
`demo_results.json`. `label_hint` is a debug-only override (used with
`--trust-hints`); it never replaces automatic scoring.

## Scoring

```bash
hygieia eval fixtures/ecom --results fixtures/ecom/runs/<run_id>
```

- The scorer answers questions from `fixtures/ecom/questions.yaml` and checks
  SQL / values against the seeded database.
- Keyword tables are selected by **answer-language detection**: if any `raw`
  contains CJK characters the Chinese marker table applies, otherwise the
  English table (`unknown`, `cannot compute`, `insufficient data`, …).
- The H2 tightening rule holds for both languages: empty or filler replies
  (`嗯`, `好的`, `ok`) on clarify questions never count as correct.
- `--lang zh` only changes the display language, never the scoring keywords.
- Each answer is scored on two dimensions: **entity** (candidate tables equal the
  gold SQL's tables, via the sqlglot AST) and **relation** (aggregation signature
  plus WHERE filter columns equal the gold's). A correct answer counts on both;
  clarify questions and answers without SQL score on neither (not attributable).
- `report` compares the current manifest with the previous eval's manifest.
  Differences in version / model / prompt / questions / corpus / semantic layer
  mean the two runs are **not directly comparable**, and the report says so.
  It also flags a dimension that drops while the overall score rises (vs control
  or vs the previous run).

## Two-arm prompt template (for the external agent)

Both arms answer the same 20 questions from `questions.yaml`. The agent may
run any SQL it believes correct; it must write `raw` exactly as it would
answer a user.

The canonical templates live in `fixtures/ecom/prompts/control.md` and
`fixtures/ecom/prompts/treatment.md`; their combined sha256 is recorded in the
manifest, so editing a prompt changes the run identity.

**Control arm** (`prompts/control.md`, no semantic layer): answer each question
from the database; if you cannot, say why; return
`{"qid", "sql"?, "value"?, "raw"}`.

**Treatment arm** (`prompts/treatment.md`, semantic layer only): answer through
the layer - pick metrics from `semantic/metrics.yml`, join per
`joins[].on_expr`, express answers as SQL over the raw tables; if the layer
cannot express the question, say so in `raw` (no guessing, no invented metrics).

Write the two answer lists into the run directory, set
`meta.json` → `simulated: false`, and score.

## Regression guarantee

The default `eval fixtures/ecom` still reads `demo_results.json` and must keep
reproducing 65%/35% (control) and 100%/0% (treatment), plus the dimension split
(entity 17/20, relation 13/20 for control; 20/20 both for treatment). Rot is not
affected by the eval manifest. Any change to the
scorer must pass `python -m unittest discover -s tests -v`.

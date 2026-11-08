# `runs/<run_id>/` — what to write

Create one directory per agent run:

```
runs/<run_id>/
├── meta.json
├── control.json
├── treatment.json
└── notes.md          (optional)
```

`meta.json` (`simulated: false` for a real run):

```json
{
  "run_id": "2026-11-08-local",
  "timestamp": "2026-11-08T17:30:00+08:00",
  "model": "your-agent/model-name",
  "simulated": false,
  "prompt_version": "hygieia main @ <commit>",
  "note": "control: schema.sql only; treatment: semantic/metrics.yml + schema"
}
```

`control.json` / `treatment.json` are lists with the same entry shape as
`fixtures/ecom/demo_results.json`:

```json
[
  {"qid": "q07", "sql": "SELECT ...", "value": 1110, "raw": "上个月净收入 1110"},
  {"qid": "q11", "raw": "没有访问数据，需要澄清转化率口径"}
]
```

Then score it:

```bash
hygieia eval <fixture_dir> --results runs/<run_id>
```

Scoring protocol, keyword tables, and the manifest fields are defined in
[docs/eval-live.md](../../../docs/eval-live.md) and section 13 of
[docs/contract.en.md](../../../docs/contract.en.md). Do not invent fields: unknown
keys are ignored, and `label_hint` is debug-only (`--trust-hints`).

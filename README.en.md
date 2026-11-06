# Hygieia

> We don't build ontologies — we keep them healthy. Inspection, evaluation, and rot-resistance for your semantic layer, fully offline.

🌐 [中文](README.md) ｜ Status: proof of concept (demo), not a product; commercial value unverified

Hygieia is a Python command-line tool that runs entirely on your machine and inspects your semantic layer: static diagnosis (`audit`), two-arm evaluation (`eval`), rot simulation (`rot`), and a final Markdown health report (`report`). It never builds an ontology — it only checks, evaluates, and stress-tests the one you already have, so a rotting definition gets caught before it reaches your users.

- Python 3.10+, single dependency `pyyaml`; no network, no accounts, no API keys
- Ships as a coding-agent skill; formerly named ontology-doctor
- Encoding contract: [docs/contract.md](docs/contract.md) (Sections 11–14)

---

## What it measures: three numbers that matter

Your semantic layer (metrics, synonyms, joins, domains, evidence) is the only source of truth a data agent has when answering questions. Once a definition drifts, the agent starts producing confidently wrong numbers. Reproduced on the bundled `ecom` fixture (6-table e-commerce schema, 20 Chinese questions) — the two arms' answers are simulated, and the scoring is real SQL execution:

| Metric | No semantic layer | With semantic layer |
|---|---|---|
| Accuracy | 13/20 (65%) | 20/20 (100%) |
| **Silent-error rate** | **7/20 (35%)** | **0/20 (0%)** |

A silent error is a wrong number with no error and no clarification — the user cannot tell. It is the core metric of `eval`. Representative failures from the control arm:

| # | Question | No semantic layer | Correct answer |
|---|---|---|---|
| q07 | Last month's net revenue | 1210 (canceled orders included) | 1110 |
| q08 | Total revenue | 1860 (canceled orders included) | 1760 |
| q09 | Active customers | 6 (counted the whole table) | 5 (ordered within 30 days) |
| q10 | Revenue | 1860 (wrong caliber) | 1760 (net_revenue) |
| q11 | Order conversion rate | Fabricated 0.25 | No visit data — should clarify |
| q12 | Average order value | 155 (canceled orders included) | 176 |
| q20 | Does net revenue include shipping? | Confident "yes" | Undefined — should clarify |

`audit` finds 7 issues in the same semantic layer (3 high: R1 synonym conflict, R3 join ambiguity, R4 dangling reference; 4 medium: R5 missing evidence). `rot` injects three kinds of drift (column rename, definition tampering, a new orphan metric) and re-runs audit: 4 new captures — the definition tampering hits an R4 that already existed before the drift (`refund_total` referencing the missing `refunds` table), so by the "new captures = set difference" rule it adds none.

Transparency: this demo's evaluation is **simulated two-arm answers + real SQL scoring** — the two arms' answers are hand-authored (marked `simulated: true` at the top of `demo_results.json`), not produced by a live LLM; the gold-standard SQL numbers come from real execution against the seed data (in-memory SQLite); the scoring logic is real code following the Section 13 protocol. The key metric `net_revenue` has an executable expression (`sum(orders.net_amount)`) that runs on the seed and matches the treatment answers; the R4 trap lives on a separate `refund_total` metric that is not on the evaluation's gold path.

## The four commands

| Command | What it does | Input | Output |
|---|---|---|---|
| `audit` | Static diagnosis across 7 rule classes (R1 synonym conflict / R2 orphan metric / R3 join ambiguity / R4 dangling reference / R5 missing evidence / R6 missing description / R7 redundancy) | `semantic/metrics.yml` + `schema.sql` | Every finding with its rule, danger, and fix |
| `eval` | Two-arm evaluation: the same questions answered with and without the semantic layer | `questions.yaml` + both arms' answers (default `demo_results.json`) | Accuracy and silent-error rate |
| `rot` | Injects three kinds of drift into an in-memory copy and re-runs audit; reports new captures (never writes to disk by default) | Same as above | Before → after → new captures |
| `report` | Full health report: high/medium findings, rot simulation, evaluation | Same as above | `reports/health-report.md` |

## Install & quick start

```bash
pip install -r requirements.txt   # the only dependency: pyyaml

python scripts/hygieia.py audit  fixtures/ecom   # static diagnosis
python scripts/hygieia.py eval   fixtures/ecom   # two-arm evaluation
python scripts/hygieia.py rot    fixtures/ecom   # rot simulation
python scripts/hygieia.py report fixtures/ecom   # full health report
```

After `report`, open `fixtures/ecom/reports/health-report.md` for the complete result. `eval` prints:

```
$ python scripts/hygieia.py eval fixtures/ecom
臂           正确        静默错答        准确率       静默错答率
control（无语义层）13/20      7/20          65.0%       35.0%
treatment（有语义层）20/20      0/20         100.0%        0.0%
```

Then run the self-tests to confirm the contract numbers still hold:

```bash
python -m unittest discover -s tests -v
```

Useful flags: `--results <json>` to evaluate a different answer file, `--json` for machine-readable output, `--fail-on high` to exit 1 when high-severity findings exist (CI), `--write` to let `rot` persist the drifted semantic layer as `metrics.rot.yml`. `doctor` is a compatibility alias for `audit`.

## Why this project exists

Existing tools mostly answer "how do I build an ontology" — bootstrapping one from metadata, docs, and guided forms. Nobody takes care of what happens after: diagnosing whether the ontology is broken, proving whether it helps or hurts your data agent, and detecting when it starts to rot. Hygieia is a proof of concept that does exactly this one thing, with reproducible numbers.

It is an original project: it does not benchmark, cite, or reference any third-party project.

## Project layout

```
hygieia/
├── SKILL.md                       # trigger phrases + operating contract
├── README.md                      # Chinese version of this document
├── README.en.md                   # English version of this document
├── docs/
│   └── contract.md     # full spec + encoding contract (Sections 11–14)
├── scripts/hygieia.py             # audit / eval / rot / report
├── tests/test_hygieia.py          # stdlib unittest self-tests
├── fixtures/ecom/
│   ├── schema.sql                 # 6-table e-commerce DDL
│   ├── seed.sql                   # small, hand-verifiable original synthetic data
│   ├── semantic/metrics.yml       # deliberately flawed semantic layer (R1/R3/R4/R5)
│   ├── questions.yaml             # 20 questions (with gold SQL and expected behavior)
│   ├── demo_results.json          # two-arm demo results (simulated: true)
│   └── reports/health-report.md   # generated health report
├── LICENSE                         # MIT license
└── requirements.txt               # pyyaml>=6.0
```

## Known limitations

1. The two arms' demo answers are hand-authored (marked `simulated: true` in `demo_results.json`): the numbers come from real SQL execution, but the answers were not generated live by a model. For a real evaluation, run the protocol inside a coding agent and store artifacts under `fixtures/ecom/runs/<timestamp>/`;
2. The rules are heuristic, not a full SQL parser (v1 plans AST-level parsing);
3. Only 7 static rule classes are covered; deep caliber semantics, permissions, and action safety are out of scope;
4. A single schema directory and a single dialect are supported (a SQLite-friendly subset is enough to run the fixture);
5. No UI, no multi-tenancy, no action layer;
6. The commercial value of a "semantic-quality tool" is unverified — this project only demonstrates why one is needed; it is not a demand proof;
7. v0 accepts only this repo's layout and the `metrics.yml` contract; adapters for third-party modeling ecosystems are explicitly out of scope (v1+ candidates).

### Known false positives and misses (no overpromising)

| Rule | Possible false positives | Known misses (v0) |
|---|---|---|
| R1 | Intentional alias layering (rare) | Cross-file synonyms, near-synonyms |
| R3 | Legitimate alternative multi-paths | Implicit joins, sub-query paths |
| R4 | Dialect functions mistaken for columns | CTE aliases, macros/templates |
| R5 | Evidence stored outside the repo | Stale evidence still counts as present |
| R6/R7 | Short but precise descriptions | Long but empty boilerplate |

## Roadmap

```
v0 (this demo)  diagnosis + evaluation + rot simulation       ← prove the problem exists (current release)
v1              AST-level parsing + multi-dialect + impact analysis + CI gate  ← an engineering asset (2–3 weeks)
v2              evolution loop: change → detect → suggest → approve → version  ← close the missing maintenance loop (2–3 months)
v3              cross-platform semantic consistency + action-layer audit        ← the open slot (6–12 months)
```

- v1: join mining moves to AST-level SQL parsing; mainstream Chinese data-warehouse dialects; merge requests trigger audit + eval and block on poor quality; git diff → impact analysis of affected metrics
- v2: ontology versioning and evolution history; the change → detect → suggest → approve → merge loop; maintenance becomes CI events instead of a manual weekly report

## Data statement

The `ecom` fixture is original synthetic demo data with no external source.

## License

MIT License — see [LICENSE](LICENSE).

---

*Proof of concept: demo data may be simulated; conclusions are for discussion and are not product promises.*

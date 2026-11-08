<div align="center">

**English** · [简体中文](docs/readme/README_zh.md)

# Hygieia

### Inspect, evaluate, and stress-test an existing semantic layer. Runs fully offline.

**On Apache Ossie's public TPC-DS model, three everyday words — `price`, `location`, `profit` — each point at two different definitions. Hygieia reports all three before a single query runs.**

[Install & quick start](#install--quick-start) · [Public-layer evidence](#public-layer-evidence) · [Demo numbers](#demo-numbers-simulated) · [How it works](#how-it-works) · [Known limitations](#known-limitations) · [Documentation](#documentation) · [CI](docs/integrate-ci.md) · [Agent](docs/integrate-agent.md)

<code>pip install "hygieia-sl @ git+https://github.com/chiang21fcb/hygieia.git" && hygieia audit fixtures/ecom</code>

</div>

Hygieia is a Python command-line tool that runs locally and inspects an existing semantic layer: static diagnosis (`audit`), two-arm evaluation (`eval`), rot simulation (`rot`), and a Markdown health report (`report`). It does not build an ontology. It checks the one you already have and reports where the definitions no longer match the data.

- Python 3.10+, runtime dependencies `pyyaml` + `sqlglot` (AST-level SQL parsing); no network, no accounts, no API keys
- Ships as a coding-agent skill

## Install & quick start

Install the distribution (the import package is `hygieia`; the console script is `hygieia`):

```bash
pip install "hygieia-sl @ git+https://github.com/chiang21fcb/hygieia.git"
# or from a checkout:
pip install -e .

hygieia audit  fixtures/ecom   # static diagnosis
hygieia eval   fixtures/ecom   # two-arm evaluation
hygieia rot    fixtures/ecom   # rot simulation
hygieia report fixtures/ecom   # full health report
```

One-shot run without installing (uv):

```bash
uvx --from git+https://github.com/chiang21fcb/hygieia.git hygieia audit fixtures/ecom
```

`python scripts/hygieia.py ...` still works as a thin compatibility wrapper around
the same package, but new docs use `hygieia`. After `report`, open
`fixtures/ecom/reports/health-report.md` for the complete result. `eval` prints:

```
$ hygieia eval fixtures/ecom
Arm                              Correct  Silent  Accuracy  Silent rate
control (no semantic layer)      13/20    7/20    65.0%     35.0%
treatment (with semantic layer)  20/20    0/20    100.0%    0.0%
```

(The CLI prints English by default. `--lang zh` switches to the Chinese variant, which is written separately, not translated. The fixture mirrors a Chinese data-warehouse scenario; the protocol is language-neutral.)

Then run the self-tests to confirm the contract numbers still hold:

```bash
python -m unittest discover -s tests -v
```

Useful flags: `--results <json-or-run-dir>` to evaluate a different answer file or a `runs/<id>` directory (see [docs/eval-live.md](docs/eval-live.md)), `--json` for machine-readable output, `--fail-on high|medium|low|none` to gate CI on severity, `--sarif <path|->` to emit SARIF 2.1.0 for code scanning, `--lang zh|en` for the output language (default `en`), `--write` to let `rot` persist the drifted semantic layer as `metrics.rot.yml`.

## Public-layer evidence

Before claiming anything about a private warehouse, Hygieia is run on a public neutral
layer: [Apache Ossie](https://github.com/apache/ossie)'s TPC-DS semantic model. The
fixture is a trimmed copy of `examples/tpcds_semantic_model.yaml` with the upstream
Apache-2.0 header kept; nothing in it is doctored, and no `schema.sql` is needed:

```bash
hygieia adapt ossie --in fixtures/ossie_tpcds/ossie_semantic_model.yaml --out .tmp/ossie
hygieia audit .tmp/ossie
# 🔴 High R1-synonym-conflict [location]: synonym "location" maps to multiple metrics/fields: ss_store_sk, s_city
# 🔴 High R1-synonym-conflict [price]:    synonym "price" maps to multiple metrics/fields: ss_sales_price, i_current_price
# 🔴 High R1-synonym-conflict [profit]:   synonym "profit" maps to multiple metrics/fields: total_profit, ss_net_profit
```

Three real vocabulary collisions in a reference model published by the standard's own
authors. `audit` also reports 4 × R5 (the model declares no evidence) and lists
`R4-dangling-ref` plus the table/column checks of R3 in `skipped_rules`, because the
sample ships no DDL — reported, not hidden. Reproduction commands, dates, and limits:
[docs/public-layers.md](docs/public-layers.md).

## Demo numbers (simulated)

The numbers in this section are a **simulated demo**, not a live model run: the two
arms' answers are hand-written, and only the SQL scoring is executed for real. They
show the shape of the failure mode, not a benchmark of any particular model.

A data agent gets its metrics, synonyms, joins, domains, and evidence from the semantic layer, so the definition lives in one place. When a definition drifts, the agent still returns a number that looks fine. The bundled `ecom` fixture reproduces this: 6 e-commerce tables, 20 Chinese questions, hand-written answers for both arms, and real SQL execution for scoring.

| Metric | No semantic layer | With semantic layer |
|---|---|---|
| Accuracy | 13/20 (65%) | 20/20 (100%) |
| **Silent-error rate** | **7/20 (35%)** | **0/20 (0%)** |

A silent error is a wrong number with no error and no clarification, so the user cannot tell. This is the core metric of `eval`.

Each answer is also scored on two dimensions: **entity** (tables / join paths) and **relation** (metric caliber: aggregation + filters). On the demo, control scores entity 17/20 and relation 13/20, treatment 20/20 on both: the failures are mostly caliber, not table-picking. `eval` writes a manifest (`reports/manifest.json`) pinning model, prompt hash, question-set hash, corpus hash, semantic-layer hash, and tool version; `report` refuses to call two runs comparable when those differ, and flags a dimension that drops while the overall score rises:

| Run lock | Value |
|---|---|
| prompt | `fixtures/ecom/prompts/{control,treatment}.md` sha256 |
| questions / corpus / semantic layer | `questions.yaml`, `schema.sql`+`seed.sql`, `semantic/metrics.yml` sha256 |
| model | `simulated (hand-authored)` for the demo; `meta.json` model for live runs |

Representative failures from the control arm:

| # | Question | No semantic layer | Correct answer |
|---|---|---|---|
| q07 | Last month's net revenue | 1210 (canceled orders included) | 1110 |
| q08 | Total revenue | 1860 (canceled orders included) | 1760 |
| q09 | Active customers | 6 (counted the whole table) | 5 (ordered within 30 days) |
| q10 | Revenue | 1860 (wrong caliber) | 1760 (net_revenue) |
| q11 | Order conversion rate | Fabricated 0.25 | No visit data; should clarify |
| q12 | Average order value | 155 (canceled orders included) | 176 |
| q20 | Does net revenue include shipping? | Confident "yes" | Undefined; should clarify |

`audit` finds 7 issues in the same semantic layer (3 high: R1 synonym conflict, R3 join ambiguity, R4 dangling reference; 4 medium: R5 missing evidence). `rot` injects five kinds of drift (column rename, definition tampering, new orphan metric, stale alias, conflicting source freshness) and re-runs audit: 6 new captures, split into structural 4 (two R4 from the column rename, plus R2 high and R5 medium from the new orphan metric) and semantic 2 (the stale alias, and the metric merging two sources with conflicting freshness). Definition tampering hits an R4 that already existed before the drift (`refund_total` referencing the missing `refunds` table), so by the set-difference rule it adds none.

About this demo's data: the two arms' answers are hand-authored and marked `simulated: true` at the top of `demo_results.json`; they were not produced by a live model. The gold-standard SQL numbers come from real execution against the seed data in in-memory SQLite, and the scoring follows Section 13 of the contract. `net_revenue`'s expression `sum(orders.net_amount)` executes on the seed and matches the treatment answers. The R4 trap lives on a separate `refund_total` metric and is not on the evaluation's gold path.

### Live run (2026-11-06)

One real two-arm run. The built-in coding agent (deepseek-v4-flash) answered as the model; scoring used the same `eval` protocol.

| Arm | Correct | Silent | Accuracy | Silent rate |
|---|---|---|---|---|
| control (no semantic layer) | 16/20 | 4/20 | 80.0% | 20.0% |
| treatment (with semantic layer) | 19/20 | 1/20 | 95.0% | 5.0% |

The semantic layer fixed three caliber errors on q08, q10, and q12: total revenue, revenue, and average order value now follow the non-cancelled scope. One shared error remained on q14, where both arms counted cancelled orders in per-customer spend; at run time the layer had no customer-dimension metric. A `customer_spend` metric (per customer, non-cancelled orders, `sum(orders.net_amount)`) was added afterwards and encodes the caliber q14 asks for, but the live answers above were **not re-run** under it (see the run's `notes.md`). Full methodology, meta, and per-question analysis: [fixtures/ecom/runs/live-20261106-dsh](fixtures/ecom/runs/live-20261106-dsh/). The demo table above stays simulated; live runs follow [docs/eval-live.md](docs/eval-live.md).

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/pipeline-dark.svg">
  <img src="docs/figures/pipeline.svg" width="880" alt="Hygieia pipeline: inputs are the native semantic/metrics.yml with optional schema.sql, plus the read-only adapt dbt and adapt ossie adapters that map external semantic models into metrics.yml; audit checks R1-R9, rot injects five drifts (3 structural + 2 semantic) and re-runs audit, eval scores two arms against executed gold SQL; report writes reports/health-report.md; two dashed consumption paths lead to a CI gate (audit --fail-on high + SARIF via a composite Action) and an agent gate that audits before answering.">
</picture>

### Commands

Four main commands:

| Command | What it does | Input | Output |
|---|---|---|---|
| `audit` | Static diagnosis across 9 rule classes (R1 synonym conflict / R2 orphan metric / R3 join ambiguity / R4 dangling reference / R5 missing evidence / R6 missing description / R7 redundancy / R8 stale alias / R9 source-freshness conflict) | `semantic/metrics.yml` + `schema.sql` | Every finding with its rule, danger, and fix |
| `eval` | Two-arm evaluation: the same questions answered with and without the semantic layer | `questions.yaml` + both arms' answers (default `demo_results.json`) | Accuracy and silent-error rate |
| `rot` | Injects five kinds of drift (three structural, two semantic) into an in-memory copy and re-runs audit; reports new captures (never writes to disk by default) | Same as above | Before → after → new captures |
| `report` | Full health report: high/medium findings, rot simulation, evaluation | Same as above | `reports/health-report.md` |

Additional subcommands (v1 utilities):

| Command | What it does | Docs |
|---|---|---|
| `adapt dbt` | Read-only adapter: maps dbt / MetricFlow YAML (measure `expr`, metric/measure `filter`, newer agg-on-metric form) onto the `metrics.yml` contract | [docs/adapters.md](docs/adapters.md) |
| `adapt ossie` | Read-only adapter for Apache Ossie/OSI semantic models — the neutral first-class input; `schema.sql` is optional for the follow-up `audit` | [docs/adapters.md](docs/adapters.md) |
| `impact` | Maps a git diff onto the affected metrics and suggests re-running `audit` | [docs/impact.md](docs/impact.md) |

### Why this project exists

Most existing tools answer how to build an ontology: bootstrapping one from metadata, docs, and guided forms, for example the ontology-skills bootstrap flow. Hygieia handles what comes after the build. A bootstrap output can be handed to it as a downstream quality gate, which answers two questions: is the ontology already broken, and would a data agent silently return wrong numbers on it? Diagnosis, evaluation, and rot detection are the whole scope, and the results are reproducible numbers.

## Known limitations

1. The two arms' demo answers are hand-authored (marked `simulated: true` in `demo_results.json`): the numbers come from real SQL execution, but the answers were not generated live by a model. For a real evaluation, run the protocol inside a coding agent and store artifacts under `fixtures/ecom/runs/<timestamp>/` (see [docs/eval-live.md](docs/eval-live.md));
2. Reference extraction is AST-based (sqlglot, sqlite dialect) and covers column refs and join `on_expr`; multi-dialect parsing, dbt `ref()`/macros, and CTE aliases are still not handled (an unparseable expression is surfaced as a high R4 finding, never silently ignored);
3. 9 static rule classes are covered (R1–R9); deep caliber semantics, permissions, and action safety are out of scope;
4. A single schema directory and a single dialect are supported (a SQLite-friendly subset is enough to run the fixture);
5. No UI, no multi-tenancy, no action layer;
6. v0's native layout is the `metrics.yml` contract. `adapt dbt` and `adapt ossie` are read-only downstream adapters (mapping: [docs/adapters.md](docs/adapters.md)); `schema.sql` is optional for `audit` (rules that need physical columns are listed in `skipped_rules`), while `eval`/`rot` still need it. Write-back, bootstrap, `adapt cube`, OWL/SHACL, and graph-database adapters are out of scope;
7. The eval scoring keywords are coupled to the answer language: v0 ships a Chinese marker table and an English one (`unknown` / `cannot compute` / `insufficient data` / `i don't know`, …), selected automatically by answer-language detection (any CJK character in the answers selects the Chinese table); the demo fixture itself stays Chinese (an English fixture is a v1+ item);
8. `营收` is deliberately double-hung between `revenue` and `net_revenue`. The R1 red light in `audit` is the demo trap and stays on; removing the synonym would falsify the baseline. In the live run an agent still picked the right caliber from the preferred-caliber description, and `audit` still reports the conflict, which is the point of the check.

### Known false positives and misses

| Rule | Possible false positives | Known misses (v0) |
|---|---|---|
| R1 | Intentional alias layering (rare) | Cross-file synonyms, near-synonyms |
| R3 | Legitimate alternative multi-paths | Implicit joins, sub-query paths |
| R4 | Dialect functions mistaken for columns | CTE aliases, macros/templates |
| R5 | Evidence stored outside the repo | Stale evidence still counts as present |
| R6/R7 | Short but precise descriptions | Long but empty boilerplate |
| R8 | A migration alias (not reported when `replaced_by` points at the current metric) | An alias pointing at a metric deleted from the file |
| R9 | Multi-source metrics that declare `authoritative: true` (not reported) | Freshness conflict that only exists in the data |

## Roadmap

```
v0 (this demo)  diagnosis + evaluation + rot simulation                    ← prove the problem exists (current release)
v1 (landed)     sqlglot AST refs + impact analysis + CI fail-on gate + adapt dbt  ← engineering assets
v0.2 (landed)   Ossie first-class input, optional schema, SARIF + composite Action, integration docs ← hook it up in minutes
v1+ (open)      multi-dialect parsing, dbt ref()/macros, evolution loop     ← still to do
v2              evolution loop: change → detect → suggest → approve → version  ← close the missing maintenance loop (2–3 months)
v3              cross-platform semantic consistency + action-layer audit        ← the open slot (6–12 months)
```

- Landed (v1): AST-level reference extraction with sqlglot, which drives R4 and `impact`; `impact` maps a git diff to the affected metrics; the CI `--fail-on high` gate; the read-only `adapt dbt` adapter.
- Landed (v0.2): Apache Ossie/OSI as a first-class input (`adapt ossie`), `schema.sql` optional for `audit`, SARIF output and a composite GitHub Action, and consumer/agent integration examples.
- Still v1+: multi-dialect parsing (sqlite today), dbt `ref()` and macro resolution, CTE aliases, and the change, detect, suggest, approve evolution loop.
- v2: ontology versioning and evolution history; the change, detect, suggest, approve, merge loop; maintenance becomes CI events instead of a manual weekly report.

## Documentation

- [SKILL.md](SKILL.md): the skill's operating contract and trigger phrases
- [docs/contract.zh.md](docs/contract.zh.md) and [docs/contract.en.md](docs/contract.en.md): the coding contract (Chinese authoritative, English mirror)
- [docs/eval-live.md](docs/eval-live.md): the live two-arm evaluation protocol
- [docs/adapters.md](docs/adapters.md): input assumptions and mapping for `adapt dbt` and `adapt ossie`
- [docs/public-layers.md](docs/public-layers.md): public semantic layers Hygieia has been run on, with commands and findings
- [docs/integrate-ci.md](docs/integrate-ci.md): CI integration (composite Action, SARIF, pre-commit)
- [docs/integrate-agent.md](docs/integrate-agent.md): agent-pipeline integration (audit gate before answering)
- [examples/consumer-ci](examples/consumer-ci/): copy-paste CI workflow for a consumer repo
- [examples/agent-pipeline](examples/agent-pipeline/): audit-gated agent pipeline shell
- [docs/impact.md](docs/impact.md): input and output for `impact`

## Data statement

The `ecom` fixture is synthetic demo data with no external source.

## License

MIT License, see [LICENSE](LICENSE).


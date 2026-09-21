# WO21 — Phase 8: portfolio polish

Baseline `50f90fd` (WO20's report commit). No migrations, no pipeline
changes, no eval runs. The only model calls were the six demo-question checks
($0.04, see Cost).

## What was written

| file | what | words |
|---|---|---|
| `README.md` | rewritten for a two-minute read: what it is, one mock screenshot, Mermaid architecture, results table with a source per row, seven decisions with their evidence files, what does not work, cost, limitations, layout and tests | 1,146 (`wc -w`, including the diagram and table tokens; the prose is about 850) |
| `docs/ENGINEERING_NOTES.md` | one section per phase / work order condensed from the reports, each ending with its source file; eight lessons that generalise | 1,929 |
| `docs/OPERATING_NOTES.md` | the previous README body, verbatim (model choices, business definitions, running the eval, observability, constraints, setup) | 1,240 |
| `docs/COST_LEDGER.md` | two sums with the method: $28.41 from 43 run files, ≈ $35.61 from the work-order cost sections through WO19; what is not counted | 506 |
| `docs/DEMO_SCRIPT.md` | shot list, demo-safe login, six cleared questions with their live-data check | 832 |
| `docs/RESUME_FACTS.md` | every resume-worthy number with source file and commit | 695 |
| `.github/workflows/tests.yml` | unit tests on push: rewriter fixtures, SQL validator, public-mirror guard; no secrets, no database, no ML extras | — |
| `.github/workflows/eval.yml` | `workflow_dispatch` only (it needs API keys; it had failed on every push since at least 2026-09-21 11:48 UTC where they were absent) | — |

Every number in the README and the facts sheet is copied from a committed
file named next to it. The screenshot is the WO18 mock frame, captioned as
mock data.

## CI

- Private repo, `tests` workflow, commit `ff465d9`: **success**, all steps
  green (checkout, setup-python 3.12, `pip install -r requirements.txt`,
  rewriter, SQL validator, public-mirror guard).
  https://github.com/SanyaBoroda4/emg-rag/actions/runs/35611399674
- The validator's recorded-SQL guard skips in CI (the run files are not in
  the public tree) and reports it; the other four validator tests run.
- **Public mirror: confirmed after this report's first version** (WO19 report §9): the new `emg-rag-public` runs the `tests` workflow green on its first snapshot and the badge renders "passing". The paragraph below is the state at the time of writing. WO19 Part 3 (recreate the public repo
  or rewrite its history) is still Alex's decision, and nothing has been
  pushed to the public repo since `d69a060` on purpose. The README badge
  points at the public repo's `tests` workflow and will render once the first
  allowlisted snapshot is pushed there; the workflow file itself passes the
  WO19 guard (it is in the allowlist under `.github/workflows/*.yml`). The
  sync was dry-run against the final tree with the guard: 0 hits (see the
  report footer).

## Demo-safe questions

Six questions run on the live data at `a070597`, answers and evidence
inspected: counts, a percentage and area names only; nobody's name, not a
dollar sign, zero retrieved chunks. The `office` login has no history rows at all
as of 2026-09-21 (all 20 rows in `serve.asks` belong to `alex`), so its
sidebar is empty; the clearing SQL is in the script for recording day.

## Numbers that could not be sourced and were left out

- Voyage embedding spend: the reports say "pennies" with no figure.
- Served-UI latency beyond the WO16 smoke checks.
- Total wall-clock time of the build.
- The server's monthly cost (it predates the project and hosts other services).
- Anything from Langfuse: there is no export in the repository.
- A verified conversation-tier number: all 38 turns are still `draft`, so the
  README says so and reports the draft figures.

## Suggested GitHub repo description and topics

Description:

> Natural-language questions over a countertop fabricator's job-tracking and invoicing data, answered with cited SQL rows or note evidence.
> Routed lanes (SQL / semantic / hybrid / refuse), per-alias SQL validation, follow-up rewriting, a three-tier eval with a different-model judge, Langfuse tracing; served on a 2 GB box.

Topics: `rag`, `text-to-sql`, `llm-evaluation`, `postgres`, `pgvector`,
`fastapi`, `langfuse`, `anthropic-claude`

## Got worse

- **The README is 1,146 words by `wc -w`**, above a strict two-minute read;
  the Mermaid block and the results table account for roughly 300 of them.
  Cutting a decision would lose sourced evidence, so it stayed.
- **The eval workflow no longer runs on push.** Routing regressions on the
  fixture corpus are now caught only when someone dispatches it by hand.
- **The badge was blank until Part 3 was decided** (it points at the public repo's workflow); it renders "passing" since the first snapshot.
- The old README's detail is one click further away (`docs/OPERATING_NOTES.md`).

## Surprises

- The private repo's eval workflow had been failing on every push (the
  fixture-load step, no secrets), producing a red X on every commit that
  nobody had looked at. Making it manual is the fix the order asked for; it
  also explains why "CI green" had never been true.
- `pipeline_runs` records no costs (source, rows, status, error only): the
  ingestion figures live in HANDOFF's phase rows, not in the database.
- The only user with history is `alex`; the `office` login is clean without
  any deletion.
- Every candidate semantic question would put a customer name on screen,
  because each note card's header is the job name. The demo therefore has no
  semantic answer, as the order allowed.

## Cost

$0.04: six pipeline calls for the demo verification (Haiku router and SQL
lane, one rewrite, one refuse). No eval runs.

## Guard dry-run on the final tree

`bash scripts/sync_public.sh --dry-run <dir>` at `a0744fa`: 151 files kept,
62 not allowlisted, 0 excluded after the transform; `README.md`, the six
`docs/` pages and both workflow files are in the tree. `scripts/public_scan.py`
on the result: 0 customer, contact, note-text, secret or dollar hits (the one
remaining `employee` line is the OFL licence word noted in WO19). Nothing was
pushed to the public repo; the push waits on WO19 Part 3.

# WO pipeline unification — v_job_pipeline_status + QCONV v4

`sql/012` (commits `b9fe34e`..`f043df9`). One canonical per-job definition
of "quoted" and "moved forward"; QCONV v4 and the Q26 stall buckets both
derive from it. Locked definition (Alex, 2026-08-12): quoted = happened
Quote/Measure/Template (past only); moved = Install/Removal with ANY date
(past or future), ACTIVITIES ONLY — no invoices, no payment notes;
SETTLE_DAYS = 30 (7-day rule retired); as-of 2026-07-30.

## Verification gates (psql, frozen DB, 2026-08-14)

**Gate 1 — buckets sum.** moved 3,063 + pending 46 + quiet 1,306 = 4,415 =
is_quoted count exactly; + not_quoted 1,154 = 5,569 jobs. ✓

**Gate 2 — cross-source.** `had_dated_quote` = **2,856** vs the live-MCP
sweep's 2,875 distinct jobs (2026-08-12) — 19-job gap, consistent with two
weeks of live drift (the same sweep showed a 23-activity gap vs our 3,154).
`is_quoted` = **4,415**, higher as required (Measure/Template-only jobs
join). ✓

**Gate 3 — five hand-verified jobs.**

| job | v3 behavior | v4 (canonical view) | ✓ |
|---|---|---|---|
| 377 | invoiced-not-moved trap | `quiet`, moved_forward=false, 2,061 days silent — invoice counts for nothing | ✓ |
| 483 | measure-proxy quoted | quoted via `measure`, had_dated_quote=false, `moved` | ✓ |
| 5022 | payment-note-only "moved" | **moved_forward=false, `quiet`** (64 days) — the required flip | ✓ |
| 5693 | future-Removal moved | `moved`, move_is_future=true (first_move 2026-08-03) | ✓ |
| 5840 | 7-day-fresh excluded | `pending`, days_silent=6 | ✓ |

Measure-only-no-Quote jobs (open decision #3) are now quoted by definition —
339 such jobs join the pool, e.g. jobs 6/7/10. Idempotency: migration
applied twice → identical totals. ✓

**Gate 4 — old vs new conversion, the two effects SEPARATED.**

| year | v3 (7d, payment, Q+proxy) | v3 + settle-30 only | v4 canonical |
|---|---|---|---|
| 2019 | 0.0% (0/2) | 0.0% | 33.3% (1/3) |
| 2020 | 64.7% (481/743) | 64.7% | 68.2% (576/845) |
| 2021 | 69.6% (442/635) | 69.6% | 73.7% (542/735) |
| 2022 | 76.5% (381/498) | 76.5% | 79.1% (472/597) |
| 2023 | 85.2% (386/453) | 85.2% | 85.7% (409/477) |
| 2024 | 61.1% (359/588) | 61.1% | 63.4% (401/632) |
| 2025 | 54.3% (327/602) | 54.3% | 61.3% (442/721) |
| **overall** | **65.9% (2,523/3,830)** | **66.3% (2,523/3,805)** | **70.0% (3,063/4,377)** |
| 2026 | 47.6% (147/309) | 51.8% | 59.9% (220/367) |

Effect 1 (settle 7→30): only recent cohorts move — 2026 47.6→51.8, overall
+0.4. As predicted, recent months read higher.

Effect 2 (definition change): **the WO predicted the overall rate would
FALL; it measured UP** (66.3 → 70.0). Attribution: only **11** jobs lose
moved status (payment-note-only movers — most of the 85 payment-note
activities sat on jobs that also had dated installs), while **339**
no-Quote-activity jobs join the quoted pool and **322 of them (95%) moved**.
Unlogged quoting correlates strongly with jobs that proceeded — the broader
denominator brought its own numerator with it.

## Corrected numbers for Alex to re-key (Q59–63 keys are v3 — DO NOT AUTO-EDIT)

| Q | v3 key | v4 corrected |
|---|---|---|
| Q59 overall rate | 65.9% (2,523/3,830) | **70.0% (3,063/4,377)** |
| Q60 2023 rate | 85.2% (386/453) | **85.7% (409/477)** |
| Q61 2024 rate | 61.1% (359/588) | **63.4% (401/632)** |
| Q62 best year | 2023, 85.2% | **2023, 85.7%** (unchanged winner) |
| Q63 job 377 | "no payment-confirmation note" wording | still NOT moved; wording should drop the payment clause — payment signals are no longer part of the definition at all |

Q26 note: the old inline stall spec ("latest dated activity is a Quote")
counted 693; the canonical `status='quiet'` counts **1,306** (any
Quote/Measure/Template signal, 30-day settle, cancelled jobs included —
report split by v_jobs.status). Q26's key is descriptive, not numeric.

Quiet split (the cancelled-visibility requirement): **1,093 of 1,306 quiet
jobs (84%) are process_name = 'Canceled'** — already known-dead, not
mysteriously silent. The genuinely ambiguous silent pipeline is ~213 jobs:
Leads with Layouts 132, Done 48, Hold 24, Job 8, Measurement 1.

## Eval — two measured rounds

Baseline = activity-reality WO final (`2026-08-12-1140.json`: 69.8%
generation, 90.0% faithfulness, 95.2% routing).

**Round 1** (`2026-08-14-1735.json`, commit `f043df9`): routing 96.8%,
generation 63.5% (40/63), faithfulness 84.8%. Q59–62 went red **as
intended** (system answers v4, keys are v3) and Q63 flipped green (the
canonical view makes the trap trivial when routed structured). Three
problems found:
- Q26: SQL was perfectly canonical (`status='quiet'`, 1,306) but the
  ANSWERER hedged ("evidence does not directly answer…") and mislabeled
  job rows as activity records — second-guessing the curated view.
- Q54: judge burned its whole 2,500-token budget on thinking and returned
  no verdict (scored as wrong).
- Q30: superseded key, same family as Q59–62 (canonical stall definition
  finds 9 quiet quartzite jobs, not 1).

**Round 2 fixes** (commits `b50fb1e`, `ffb5eeb`): judge max_tokens
2,500→4,000; answerer rule — curated-view definitions are authoritative,
answer from the rows, and such rows are per-JOB.

**Round 2** (`2026-08-14-1747.json`): routing 95.2%, generation 63.5%
(40/63), faithfulness **91.7%** (WO-best). Q26 ✓ (canonical 1,306 accepted
by the judge), Q37 ✓, Q49 ✓, Q54 ✓. No regressions attributable to the SQL
surface this WO changed.

Red rows, all accounted for:
- **Q59–62 + Q30** — superseded v3 keys; system already answers v4
  correctly (see re-key table above). Not regressions; the WO's intended
  outcome.
- **Q63** — router roulette: structured in R1 (passed via the view),
  semantic in R2 (retrieval can't see job 377). Key wording also needs the
  payment clause dropped.
- **Q16 / Q29** — placeholder-inflated keys from the previous WO's list,
  still awaiting Alex; Q29 additionally flip-flops between raw rows (246),
  happened jobs (236), and happened activities (279) run-to-run until the
  key picks a unit.
- **Q31** (visits number), **Q11** (material parser), **Q28** + semantic
  block (39–57 subset) — all pre-existing, documented in the previous WO.

Generation reads 63.5% vs the prior 69.8% ONLY because five keys are
intentionally superseded; with Q59–62+Q30 re-keyed to v4 the same run
scores 45/63 = 71.4%.

`evals/baseline.json` untouched (routing 96.8/95.2 across two runs is
inside the established noise band; retrieval unchanged).

## Cost

2 full tier1+3 runs ($0.82 + $0.71) + smoke-test lane calls ≈ **$1.65**,
well under the $5 budget. Judge separation maintained (Haiku answers,
Sonnet judge).

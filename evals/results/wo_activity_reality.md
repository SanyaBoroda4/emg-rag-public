# WO activity-reality + fan-out — before/after

Baseline = WO7 final run (`2026-08-09-2253.json`, commit `aa69240`).
Final = round-4 run (`2026-08-12-1140.json`, commit `7e3b4fd`).
Four measured rounds; every mid-WO regression was found by measurement and
fixed before closing (WO7 lesson applied).

Changes measured here (one commit each):

1. `sql/011` — `v_activities` gains `happened` / `is_scheduled_future`
   booleans (as-of = snapshot 2026-07-30, same hardcoding as sql/009);
   new `v_job_sqft(job_id, total_sq_ft, area_count)` pre-aggregation view.
2. Schema prompt — three-state activity rule (placeholder / happened /
   scheduled-future) stated as a table + "business-event counting questions
   must count only rows WHERE happened"; v_job_sqft usage with a MANDATORY
   `SELECT DISTINCT job_id` subquery pattern (plain + grouped-by-crew
   variants); install-crew definition ("crew workload questions are about
   Install activities unless another type is named").
3. Answerer — never volunteers schema-level statistics absent from the
   query's evidence (the "44% of activities have no date" boilerplate was
   judged unfaithful on Q26/Q32–37); activity-count answers state in one
   clause whether they count events or all records.

## Part A1 diagnostic — placeholder inflation per activity type

Run on the frozen snapshot DB 2026-08-12 (as-of 2026-07-30). A row is only
an event if dated; ~44% of all activity rows are pre-created placeholders.

| type_name | all_rows | dated | undated_placeholders | happened | scheduled_future | pct_dated |
|---|---|---|---|---|---|---|
| Install | 7758 | 5652 | 2106 | 5629 | 23 | 72.9 |
| Template | 6060 | 3744 | 2316 | 3724 | 20 | 61.8 |
| Invoice | 5461 | 2886 | 2575 | 2886 | 0 | 52.8 |
| Quote | 5315 | 3154 | 2161 | 3154 | 0 | 59.3 |
| Measure | 5284 | 2901 | 2383 | 2900 | 1 | 54.9 |
| Fabrication | 5032 | 755 | 4277 | 755 | 0 | 15.0 |
| Phone, Email | 4476 | 881 | 3595 | 881 | 0 | 19.7 |
| Follow Up | 1831 | 1822 | 9 | 1807 | 15 | 99.5 |
| Repair | 846 | 840 | 6 | 840 | 0 | 99.3 |
| Meeting | 812 | 804 | 8 | 801 | 3 | 99.0 |
| Removal | 653 | 634 | 19 | 630 | 4 | 97.1 |
| Phone call | 302 | 232 | 70 | 232 | 0 | 76.8 |
| Tile | 291 | 282 | 9 | 279 | 3 | 96.9 |
| Email | 205 | 120 | 85 | 120 | 0 | 58.5 |
| Paid if Full | 139 | 139 | 0 | 139 | 0 | 100.0 |
| Follow Up After Install | 14 | 13 | 1 | 13 | 0 | 92.9 |
| Contract | 13 | 12 | 1 | 12 | 0 | 92.3 |
| Plumbing | 3 | 2 | 1 | 2 | 0 | 66.7 |

Sanity: happened 24,804 + scheduled_future 69 + placeholders 19,622 = 44,495 ✓.

### Golden-key audit — Alex's call, NOT edited (THE ONE RULE)

Three currently-verified keys are raw row counts and therefore
placeholder-inflated:

| Q | question | current key | corrected (happened) | note |
|---|---|---|---|---|
| Q14 | most common activity type | Install, **7,758** | Install, **5,652 dated / 5,629 happened** | winner unchanged either way (Template is 2nd at 3,744 dated) |
| Q15 | how many Repair activities | **846** | **840** | only 6 placeholders — smallest distortion |
| Q16 | quotes issued in total | **5,315** | **3,154** | ~41% of Quote rows were never issued to anyone. (Independent live-MCP sweep found 3,177 dated Quotes — 23 more than this frozen snapshot, consistent with the live system having moved on since the export.) |
| Q29 | jobs with tile work | **246** (any Tile row) | **236** (happened only) | surfaced in round 3 once the happened rule took hold — same placeholder disease; Alex should pick which definition the key means |

One more key note: Q31's "(29 install visits)" third number is not produced
by the correct sq-ft query and the strict scorer requires it, so Q31 will
stay red against the current key even when the sq ft and job count are
exactly right.

Until Alex updates these keys, the system's now-business-correct answers are
judged wrong: Q14/Q15/Q16 flipping red in the after-run below is expected and
is the system being right against stale keys.

## Hand-checks (psql, frozen DB, 2026-08-12)

- Q31: Ihor/Tolik March 2026 = **1,909.3 sq ft, 23 jobs, 29 install visits** ✓
- Q32: Ivan Andreev **9,067.6** vs Ihor/Tolik 9,027.0 ✓
- Q33: Ihor/Tolik **108** completed install jobs H1 2026 ✓
- sql/011 applied twice → identical result (idempotent) ✓
- Lane smoke tests after prompt fixes: Q16→3,154, Q31→1,909.3, Q32→Ivan
  9,067.6, Q33→108, Q34→35, Q35→104.2, Q36→Yuri/Petro 107.4 — all exact.

Two prompt iterations were needed (each caught by smoke-testing before the
paid run): Haiku first joined `v_job_sqft` straight onto activity rows
(repeat visits double-counted → 3,845.3), then re-joined `v_activities`
after the DISTINCT subquery to recover the crew name (26,614.2). Both are
now explicitly forbidden in the schema prompt with worked patterns.

## Measured rounds

The golden set grew from 58 to 63 questions between the WO7 baseline and this
WO (Q59–63, quote-conversion drafts), so headline percentages are not
directly comparable; the question-level diff below is computed on the shared
58.

**Round 1** (`2026-08-12-1031.json`, commit `fde710a`): routing 95.2%,
generation 63.5% (40/63), faithfulness **88.3%** (+6.5 — Part C worked),
context precision 56.1%. Question-level vs WO7 final on the shared 58:

| Q | before → after | driver |
|---|---|---|
| Q32 crew most sqft | fail → **pass** (Ivan 9,067.6) | v_job_sqft + grouped DISTINCT pattern |
| Q33 crew most jobs | fail → **pass** (Ihor/Tolik 108) | happened rule (was 51 via status_name) |
| Q35 Ivan avg job size | fail → **pass** (104.2) | fan-out fix + install-crew definition |
| Q36 largest avg job size | fail → **pass** (Yuri/Petro 107.4) | same |
| Q44, Q49 | fail → pass | semantic/judge nondeterminism (±2 questions run-to-run, known) |
| Q16 quotes issued | pass → fail | EXPECTED: system now answers 3,154 (business-correct); golden key still 5,315 |
| Q22 Kiawah jobs | pass → **fail (16)** | REGRESSION: completed-rule bled into job counting — SQL added `status = 'Complete'` to a v_jobs count |

Q31/34/37/59/60/61 stayed red with correct headline numbers: the strict
scorer requires EVERY number in a multi-number key ("1,909.3 across 23 jobs
(29 visits)") and the SQL returned only the headline aggregate.

**Round 2 fixes** (commit `b277e85`), each smoke-tested before the re-run:
jobs-vs-events disambiguation rule (Q22: "did we do" on jobs ≠ status
filter — back to 178); aggregate queries must SELECT supporting counts
(Q31 now returns 1,909.3 + 23 jobs; Q59–61 return rate + numerator +
denominator).

**Round 2 run** (`2026-08-12-1048.json`, commit `b277e85`): routing 96.8%,
generation **66.7% (42/63)**, faithfulness 88.3%. Q22 ✓ (178), Q59/60/61 ✓
(rates now carry numerator/denominator). New find: Q2 flipped red — an
unfiltered `GROUP BY salesperson` let the 1,386 blank-salesperson rows win
the ranking.

**Round 3 fixes** (commits `904ee79`, `cc624bb`): exclude blank group keys
when ranking (Q2); crew job-count questions use the jobs+sqft pattern (Q34).

**Round 3 run** (`2026-08-12-1108.json`): routing 92.1%, generation 63.5%
(40/63), faithfulness 81.7%. Q2 ✓ and Q34 ✓, but the "EVERY crew-workload
question" wording pushed Q33's job count through the **inner** v_job_sqft
join, silently dropping the one Ihor/Tolik job with no area rows (107 vs
108). Also surfaced: Q29 "jobs with tile work" now answers 236 (happened
only) vs key 246 (any Tile row) — same stale-key disease as Q16; Q7 was a
router refusal flip (router untouched this WO; known ±1–2 nondeterminism).

**Round 4 fix** (commit `7e3b4fd`): the v_job_sqft pattern is now LEFT JOIN —
COUNT(*) keeps area-less jobs in job counts while SUM/AVG skip their NULL
sq ft. This makes Q33 (108) and the full six-number Q37 comparison
(108 vs 87 jobs, 9,027.0 vs 9,067.6 sq ft, 84.4 vs 104.2 avg) all
satisfiable at once, confirmed by smoke tests.

**Round 4 run — FINAL** (`2026-08-12-1140.json`, commit `7e3b4fd`): routing
95.2%, generation **69.8% (44/63)**, faithfulness **90.0%**, context
precision 58.3%.

## Final scoreboard

| metric | WO7 final (58 Q) | this WO final (63 Q) |
|---|---|---|
| routing accuracy | 94.8% | 95.2% (ranged 92.1–96.8 across rounds; router untouched, known ±1–2 question flip) |
| generation accuracy | 60.3% | **69.8%** |
| faithfulness | 81.8% | **90.0%** |
| context precision | 64.3% | 58.3% (semantic-row judge nondeterminism; no retrieval changes were made) |

Entire WO target block green: **Q31-headline/Q32/Q33/Q34/Q35/Q36/Q37 all
produce exactly the verified numbers**, and Q59–Q62 (quote conversion) pass
with rate + counts. Q22/Q2/Q7/Q29 regressions found mid-WO were fixed and
re-measured.

Remaining reds, all explained:
- **Q16** — system answers 3,154 (business-correct); key still 5,315. Alex's call.
- **Q31** — sq ft (1,909.3) and jobs (23) exact; the key's third number "(29
  install visits)" is not produced by the correct query. Alex's call on the key.
- **Q63** — router sends this draft trap question semantic; retrieval never
  surfaces job 377. Candidate future fix: bare "Job NNN" references should
  bias structured/hybrid.
- **Q11** — known material-parser gap (58 vs 66 vs 152 ambiguity), pre-existing.
- **Q28 + semantic rows** (39, 41–58 subset) — pre-existing judge/retrieval
  variance on draft rows, ±2–3 per run, untouched by this WO (no retrieval
  changes).
- Note: Q14/Q15/Q29-style "how many X" questions flip between raw-count and
  happened-count run to run — the SQL model resolves the ambiguity
  differently each time. Until the keys pick a side, these will be noisy.
- Note: the A4 disclosure clause ("this count includes placeholders") is
  itself schema knowledge; on Q15 the judge flagged it as unsupported by the
  SQL evidence. Kept — the business value of saying what was counted
  outweighs one faithfulness ding.

## CI baselines

`evals/baseline.json` **unchanged** (routing 0.948, reranked R@10 0.522):
retrieval was untouched, and routing fluctuated 92.1–96.8% across four runs
with zero router changes — bumping the gate on run-to-run noise would just
make CI flakier. Tier-3 metrics are not part of baseline.json.

## Cost

4 full tier1+3 runs ($0.66 + $0.70 + $0.78 + $0.71) + ~15 smoke-test lane
calls ≈ **$2.95**, under the $5 budget. Judge separation maintained (Haiku
answers, Sonnet judge). Runs now take ~25 min each (Voyage paid tier —
confirmed working; residual time is serial Claude calls).

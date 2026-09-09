# WO9 — Status widening, crew-question fixes, WO8 follow-ups

Date: 2026-09-09 · commits `ffdfca0` … `305b958` · DB snapshot as-of 2026-07-30, view clock 2026-09-09

**Headline:** after all three view changes the count is **252 wasted of
3,643 real templates (6.9%)**, against WO8's 266 / 3,534 (7.5%). Every
change was measured alone; the gate passed all 12 reference jobs after
each one — **no verdict flipped**. Victor Slabunov stays first (53, 11.7%);
Diana Diaz drops from 26 to 17 because nine of the 18 same-day pairs were
hers. Crew questions Q64–73: **10/10** in the final run (was 1/10), and the older crew rows Q34–37 pass too after re-keying Q36/Q37. Final eval: routing 96.3%, generation **73.2%** (60/82, vs 62.2% in WO8 and 63.5% on Aug 14), faithfulness 87.3%.

Note on the WO's stated baseline: it quotes "266 / 3,800 = 7.0%". The WO8
run-2 numbers on record are 266 / 3,534 = 7.5% (gate output in
`wo_wasted_templates.md`); 3,800 does not appear anywhere in WO8's outputs.
The deltas below use the recorded 3,534.

## Change 1 — Step 0 widening + future-date guard (`sql/015`, commit `ffdfca0`)

Real = dated AND status ∈ {Complete, Paid in Full and Finished,
Confirmed, In Progress} AND `activity_date <= CURRENT_DATE`. All three
tunables sit in the `params` CTE. Gate: **PASS, 12/12**.

Newly counted (dated, not future):

| | Confirmed | In Progress | newly real | excluded by future guard |
|---|---|---|---|---|
| Template | 122 | 5 | **127** | 1 (Confirmed, dated after 2026-09-09) |
| Install | 286 | 4 | **290** | 1 (Confirmed) |

13 Confirmed templates and 12 Confirmed installs are dated between the
snapshot (Jul 30) and today: past by the clock, present in the data (they
were future-scheduled at export time). They count. RTF (1 template,
3 installs) and Estimate never count.

Totals: real 3,534 → **3,661**, wasted 266 → **271** (7.5% → 7.4%).
Reasons: structural 222 → 226, note 27 → 28, both 17 → 17.

| salesperson | WO8 real | WO8 wasted | % | C1 real | C1 wasted | % |
|---|---|---|---|---|---|---|
| Victor Slabunov | 446 | 54 | 12.1 | 455 | 56 | 12.3 |
| Natalia Pavlenko | 740 | 49 | 6.6 | 813 | 54 | 6.6 |
| (blank) | 805 | 56 | 7.0 | 818 | 53 | 6.5 |
| Alex Sorokin | 555 | 35 | 6.3 | 568 | 37 | 6.5 |
| Diana Diaz | 206 | 26 | 12.6 | 207 | 26 | 12.6 |
| Galya Gornishka | 482 | 23 | 4.8 | 489 | 25 | 5.1 |
| Sasha Nosova | 216 | 19 | 8.8 | 226 | 17 | 7.5 |
| Max Konikov | 78 | 4 | 5.1 | 79 | 3 | 3.8 |

The blank bucket and Sasha/Max *lose* wasted templates: a newly-counted
Confirmed install now sits between two templates that were structurally
wasted before. Natalia gains the most real templates (+73): her jobs carry
the most Confirmed-not-Complete rows.

## Change 2a — same-day template pairs are one trip (commit `50ebc3b`)

Same-job-same-date real templates collapse to one row before
phase-splitting (notes concatenated, lowest activity_id kept). Gate PASS.

Real 3,661 → **3,643** (18 pairs collapsed), wasted 271 → **255**.
Reasons: structural 226 → 210, note 28 → 30, both 17 → 15. (Two rows
turn note-only: their same-day partner's note now travels with them.)

Per PM: Diana Diaz 26 → **17**, Sasha 17 → 15, Natalia 54 → 52, Victor
56 → 54, blank 53 → 52. Everyone else unchanged.

## Change 2b — three patterns tightened, 853 kept (commit `eb893d9`)

| job | note | pattern that fired | tightening |
|---|---|---|---|
| 2262 | "3.09 wasnt ready for install…" | `wasn'?t ready` | `(not|weren't|wasn't) ready` followed by `for (the) install` no longer matches |
| 2676 | "Can't template yet due to lack of glue gun" | `can'?t template` | the `can't/could not/didn't/unable to template` group no longer matches when followed within 40 chars by `lack of / forgot / glue / tool / equipment / laser` |
| 3714 | "Need to confirm with Erick if they adjusted the cabinets…" | `adjust… cabinets` | the `redo/adjust/fix/replace … cabinets` group no longer matches when preceded by `if they/he/she/we` or `whether they` |
| 853 | "They Adjusted the Cabinets" | `adjust… cabinets` | **kept — real failure** (Alex) |

Gate PASS. Wasted 255 → **252**. Note matches 45 → **42** distinct notes
(note-only 30 → 27, both 15 → 15). Per PM: Victor 54 → 53, Natalia
52 → 51, Sasha 15 → 14.

## Final state after Changes 1–2b

252 / 3,643 = 6.9%. Structural-only 210, note-only 27, both 15.

| salesperson | real | wasted | % |
|---|---|---|---|
| Victor Slabunov | 453 | 53 | 11.7 |
| (blank) | 816 | 52 | 6.4 |
| Natalia Pavlenko | 811 | 51 | 6.3 |
| Alex Sorokin | 568 | 37 | 6.5 |
| Galya Gornishka | 489 | 25 | 5.1 |
| Diana Diaz | 197 | 17 | 8.6 |
| Sasha Nosova | 224 | 14 | 6.3 |
| Max Konikov | 79 | 3 | 3.8 |

By year: 2020 25/445 · 2021 41/625 · 2022 36/569 · 2023 35/546 ·
2024 28/524 · 2025 48/570 · 2026 39/364 (10.7%).

Sensitivity (v2): 21 days 238 · **30 days 252** · 45 days 262 — still
±10–14, 30 remains safe.

## Change 3 — crew questions (commits `7a855ad`, `6c559e9`, `3bc5f30`)

- **3a** schema prompt: average job size = `SUM(COALESCE(total_sq_ft,0)) / COUNT(*)` over the DISTINCT-job subquery; never `AVG()` (skips area-less jobs' NULLs, measured 84.4 vs the correct 83.6).
- **3b** schema prompt: named **per job** vs **per visit** patterns, with the 88.5 / 44.25 example; the per-visit query is spelled out.
- **3c** Q73 now asks about job **5637** (Rolina – 6222 N Hwy 17, Yuri/Petro): 102 sq ft, 2 install visits (May 22, Jun 2 2026) → 102 per job, 51.0 per visit. Row notes that 5874 was the original example and postdates the snapshot.

Subset re-run of Q64–73 only (tiers 1+3):

| id | question | WO8 run 2 | subset run 1 (3a+3b v1) | run 2 (per-visit fixed) | run 3 (job-count rule) | status |
|---|---|---|---|---|---|---|
| 64 | Ihor/Tolik avg job size | ✗ 84.36 | ✓ 83.6 | ✓ | ✓ | verified |
| 65 | Ihor/Tolik sq ft per visit | ✗ 126.8 | ✗ 125.9 | ✓ 58.6 | ✗ 125.9 | **FAILING (flaky)** |
| 66 | Yuri/Petro visits vs jobs | ✗ (no "7") | ✗ | ✓ 42/35/7 | ✓ | verified |
| 67 | Yuri/Petro sq ft per visit | ✗ 158.2 | ✗ 154.5 | ✓ 87.0 | ✓ | verified |
| 68 | Leo jobs installed | ✗ (no visits) | ✗ | ✗ bare 16 | ✗ bare 16 | **FAILING** |
| 69 | Leo avg job size | ✗ 72.63 | ✓ 68.1 | ✓ | ✓ | verified |
| 70 | Leo sq ft per visit | ✗ 71.8 | ✗ 56.2 | ✓ 47.4 | ✓ | verified |
| 71 | smallest avg job size | ✗ 72.63 | ✓ | ✓ | ✓ | verified |
| 72 | rank crews by sq ft | ✓ | ✓ | ✓ | ✓ | verified |
| 73 | job 5637 sq ft / visits | ✗ (5874) | ✗ 204 (double count) | ✓* | ✓ | verified |
| | **total** | **1/10** | **4/10** | **8/10** | **8/10** | |

Full run A (all 82) then scored the block 9/10 (Q65 ✓, Q68 ✗); subset run 4 after the rule promotion: 12/14 incl. Q34–37 (Q68 answerer dropped sq ft, Q71 invalid grouped CTE). Run B: 10/10, plus Q34–37 4/4.

\* run 2's Q73 answer was right (102 sq ft, 2 visits) but scored wrong because the key carried the visit dates and the all-numbers scorer demanded them; the dates moved to the notes column.

Three subset runs were needed, not one: the first per-visit pattern I wrote into the prompt (join `v_job_sqft` onto each visit row, divide by visits) is itself the double-count — 125.9 instead of 58.6 — and had to be replaced by a two-CTE pattern (distinct-job total ÷ install-row count, commit `8908be3`). Q65 then passed once and failed once with an identical prompt: Haiku's SQL lane runs at default temperature, so the same question can take either shape run to run. Q68 returned a bare `COUNT(DISTINCT job_id)` in every run despite the rule naming that exact question. Both left `FAILING` with the reason in the row; a temperature=0 SQL lane (as the router got in WO8) is the obvious next measured change.

## Change 4 — Voyage speed check (investigation only)

**No leftover throttling in the query path.** `ingest/voyage_util.py:22-35`
`retry_voyage` sleeps only after a `RateLimitError` (10 s doubling to
300 s); on the paid tier it never fires. The only fixed delay in the repo
is `ingest/embed_chunks.py:32` `PAUSE_BETWEEN_CALLS = 60` (used at line
76) — the bulk corpus embedder from WO3, not touched by the eval. The
free-tier assumption survives only as prose (voyage_util.py:5,
harness.py:9, dense.py:41). `retrieval/rerank.py` and `dense.py` have no
sleeps.

Where the 13 minutes go (WO8 run 2 JSON, 82 questions, summed):

| stage | total | recorded? |
|---|---|---|
| answer generation (Haiku) | 149.2 s | yes |
| text-to-SQL (Haiku, incl. one repair) | 89.5 s | yes |
| rerank (Voyage) | 4.2 s | yes |
| dense (Voyage embed done once + pgvector scan) | 0.9 s | yes |
| bm25 | 0.9 s | yes |
| router (Haiku, 82 calls) | — | **not recorded** |
| judge (Sonnet 5 with thinking, ~82 calls, 4,000 max tokens) | — | **not recorded** |

Recorded stages sum to 245 s of a ~780 s run. The unrecorded ~535 s is the
router and, above all, the Sonnet judge (2 calls where the first returns
no text). Voyage is 5 s of the run. **Conclusion:** wall time is LLM
latency, not Voyage; the judge is the lever if the eval needs to be faster
(it is run sequentially, one question at a time — parallelising tier 3 is
the obvious next step, its own measured change). Recommendation: record
router and judge latency in the run JSON so this table stops having blanks.

## Golden set

- Q64–73 all → `verified` (10/10 in run B). Q65 passed 3 of its 4 measured runs and keeps a flakiness note; Q68 passed only after the final rule promotion + answerer fix.
- Q36/Q37 re-keyed to the all-jobs denominator (104.4; 83.6) — both pass in run B, still `draft` (Alex's sign-off).
- Q73 rewritten for job 5637 (102 sq ft, 2 visits, 51.0 per visit); row notes that 5874 postdates the snapshot.
- Q74–77 re-keyed from the v2 view: 252 total (was 266); 48 in 2025 (was 47); Victor Slabunov 53 (was 54); 2025 per-PM Max 25.0 / Victor 12.2 / Diana 10.0 / Natalia 9.2 / Alex 6.1. Q78–81 re-read, unchanged (852 still `both`, 3117 still none, 478 and 4743 unchanged). Q82 re-keyed to 16 jobs / 17 templates (3714 dropped by Change 2b; 853 stays per Alex). Exact SQL in every `source_of_truth`.

## Re-measure — full run

| run | commit | q | routing | generation | faithfulness | cost |
|---|---|---|---|---|---|---|
| Aug 14 baseline | `ffb5eeb` | 63 | 95.2% | 63.5% (40/63) | 91.7% | $0.71 |
| WO8 run 2 | `5857959` | 82 | 96.3% | 62.2% (51/82) | 84.8% | $1.02 |
| WO9 run A (after Changes 1–3, first crew rule) | `305b958` | 82 | 96.3% | 70.7% (58/82) | 88.6% | $1.06 |
| **WO9 run B** (final: crew rule promoted, grouped pattern, Q36/37 re-keyed) | `269b66d` | 82 | 96.3% | 73.2% (60/82) | 87.3% | $1.09 |

### Run A (`305b958`)

Generation recovered from 62.2% to **70.7%**: the crew block went 1/10 → 9/10
(Q65 passed this time, Q68 failed) and the wasted block stayed 9/9. Two
things the crew subset could not see appeared: Q34/Q36/Q37 (the WO7-era
draft crew rows) flipped red. Q36/Q37 carried the old AVG-skipping-NULL
numbers (107.4, 84.4) which the 3a decision supersedes (104.4, 83.6) —
re-keyed in `fd2b590`. Q34 and Q68 both got a bare job count: the
consolidated crew rule pointed at the big CTE pattern and Haiku skipped it
for "how many jobs" wording. A fourth crew subset (Q34–37 + Q64–73,
`2026-09-09-0943-crew-subset.json`) after promoting the rule to the Rules
list scored 12/14: Q68's SQL was finally complete but the *answerer*
dropped the sq ft, and Q71's multi-crew CTE had an invalid alias scope.
Both fixed in `269b66d` (grouped pattern spelled out verbatim; answerer
must report every crew-workload number) and measured by run B.

<details><summary>Run A per-question detail</summary>

By block:
- Q1–63: 40/63 correct
- Q64–73 crew: 9/10 correct
- Q74–82 wasted: 9/9 correct

Routing misses: Q40 semantic→hybrid, Q41 semantic→structured, Q56 semantic→structured.

Changes vs WO8 run 2 (same question ids): Q26 [verified] structured/✗ → structured/✓; Q29 [verified] structured/✗ → structured/✓; Q34 [draft] structured/✓ → structured/✗; Q36 [draft] structured/✓ → structured/✗; Q37 [draft] structured/✓ → structured/✗; Q44 [draft] semantic/✓ → semantic/✗; Q46 [draft] semantic/✗ → semantic/✓; Q49 [draft] semantic/✓ → semantic/✗; Q62 [draft] structured/✗ → structured/✓; Q64 [verified] structured/✗ → structured/✓; Q65 [FAILING] structured/✗ → structured/✓; Q66 [verified] structured/✗ → structured/✓; Q67 [verified] structured/✗ → structured/✓; Q69 [verified] structured/✗ → structured/✓; Q70 [verified] structured/✗ → structured/✓; Q71 [verified] structured/✗ → structured/✓; Q73 [verified] structured/✗ → structured/✓.

Incorrect: Q11, Q16, Q28, Q30, Q31, Q34, Q36, Q37, Q39, Q41, Q42, Q43, Q44, Q45, Q48, Q49, Q51, Q52, Q56, Q57, Q59, Q60, Q61, Q68.

Unfaithful (9):
- Q14: The core answer (Install, 7758) matches the expected answer and is supported by the SQL result. However, the added claim about the count inc
- Q40: The answer correctly affirms that jobs existed where cabinets weren't ready for templating, and it correctly cites job 5015 as one of the ex
- Q42: The system's answer lists six jobs with niches/benches, but the expected answer only identifies job 3071 with specific niche/bench counts an
- Q45: The system correctly identifies job 3479 (Lisa) as a tipping instance, matching the expected answer, but incorrectly characterizes two other
- Q49: The core correct fact (job 1575, warranty claim on a bathroom sink) is included, but the answer incorrectly expands the definition of 'warra
- Q51: The expected answer specifically points to job 679 (a remnant break where EMG replaced material without charging fabrication), which was nev
- Q56: The expected answer refers specifically to Job 3423 with distinct Calacatta materials (AGM Calacata Gold Senso, Calacata Gold Danby, Calacat
- Q58: The system correctly identifies job 4008 as the primary example matching the expected answer, but it inaccurately extends the 'customer-supp
- Q82: The system's list of jobs matches the expected answer's set of 16 jobs (with 4882 counted twice for its two wasted templates), and the excer

</details>

### Run B (final)

Run B's one wasted-block miss is Q82 (hybrid, cabinets list): a near-miss — the answer listed 17 jobs, counting 4882's two templates as two jobs and adding job 4318 (its SQL searched note text more broadly than `matched_note`). The judge's reason: "The system correctly identifies most of the 16 expected jobs but miscounts them as 17 (treating job 4882's two occurrences as separate entries incorrectly labeled) and adds an extra job (4318) not included in the ground truth list, causing a mismatch with the expected answer's scope and count.". Q29 flip-flopped back to 246 raw Tile rows (known, open decision #0). Faithfulness sits at 87.3%: the semantic block's usual judge noise (Q44/Q49/Q54/Q58 flipped red, Q28/Q46 flipped green).

By block:
- Q1–63: 42/63 correct
- Q64–73 crew: 10/10 correct
- Q74–82 wasted: 8/9 correct

Routing misses: Q40 semantic→hybrid, Q41 semantic→structured, Q56 semantic→structured.

Changes vs WO8 run 2 (same question ids): Q26 [verified] structured/✗ → structured/✓; Q28 [FAILING] semantic/✗ → semantic/✓; Q31 [draft] structured/✗ → structured/✓; Q44 [draft] semantic/✓ → semantic/✗; Q46 [draft] semantic/✗ → semantic/✓; Q49 [draft] semantic/✓ → semantic/✗; Q54 [draft] semantic/✓ → semantic/✗; Q58 [draft] semantic/✓ → semantic/✗; Q62 [draft] structured/✗ → structured/✓; Q64 [verified] structured/✗ → structured/✓; Q65 [FAILING] structured/✗ → structured/✓; Q66 [verified] structured/✗ → structured/✓; Q67 [verified] structured/✗ → structured/✓; Q68 [FAILING] structured/✗ → structured/✓; Q69 [verified] structured/✗ → structured/✓; Q70 [verified] structured/✗ → structured/✓; Q71 [verified] structured/✗ → structured/✓; Q73 [verified] structured/✗ → structured/✓; Q82 [draft] hybrid/✓ → hybrid/✗.

Incorrect: Q11, Q16, Q29, Q30, Q39, Q41, Q42, Q43, Q44, Q45, Q48, Q49, Q51, Q52, Q54, Q56, Q57, Q58, Q59, Q60, Q61, Q82.

Unfaithful (10):
- Q11: The system correctly identifies Dallas White as the most-used material, matching the material in the expected answer, though the count diffe
- Q14: Core answer (Install, 7758) matches expected answer and is supported by SQL result, but the added explanatory claim about record types is no
- Q42: The expected answer specifically identifies job 3071 with detailed counts (2 niches + bench in bath 2, plus 1 bench + 1 niche in Calacatta G
- Q45: The expected answer identifies only job 3479 (Lisa Harrell) as a tip to installers. The system incorrectly extends this to jobs 134 and 642,
- Q48: The expected answer refers to a specific job with 211.5 sq ft of recut pieces across 7 slabs involving specific materials (Cambria Delgatie,
- Q49: The system correctly identifies the job 1575 warranty claim matching the expected answer, but incorrectly extends the definition of 'warrant
- Q50: The core fact from the expected answer (job 3908, Ricardo Sanchez, non-English speaking client needing Google Translate/Spanish) is correctl
- Q55: The answer correctly identifies job 1157 as the case where a customer (Christine Heilman) was restricted to selecting a corner rather than t
- Q57: The expected answer specifically identifies Job 3298 (template waterfall, office bath, master ready in ~4 weeks, no LVR backsplash) as the j
- Q58: The expected answer identifies only job 4008 as involving a customer-supplied sink that needed on-site modification. The system correctly re

## Surprises

1. **The WO's baseline was mis-stated.** It says 266 / 3,800 = 7.0%; the
   recorded WO8 numbers are 266 / 3,534 = 7.5%. All deltas here use 3,534.
2. **Widening Step 0 *lowered* some PMs' counts.** Counting Confirmed installs
   satisfies templates that were structurally wasted before (blank bucket
   56 → 53, Sasha 19 → 17, Max 4 → 3), while adding 127 templates. Net +5
   wasted, and 2026's rate falls from 12.2% to 11.0% (10.7% after 2a/2b) —
   the most recent year had the most Confirmed-not-yet-Complete installs.
3. **No verdict flipped** in any of the three view changes — the 12
   reference jobs were unaffected by every one of them.
4. **Nine of the 18 same-day template pairs were Diana Diaz's** (26 → 17,
   12.6% → 8.6%). Her position in the ranking depended on that one ruling.
5. **The per-visit formula as written in the WO is the trap.** "SUM(job_sqft)
   / COUNT(install_activity_id)" read literally as a join of `v_job_sqft`
   onto visit rows sums each job once per visit (125.9 for Ihor/Tolik, not
   58.6). It needs two aggregations (distinct-job total ÷ install-row count).
6. **Q36/Q37 (WO7-era draft crew keys) were AVG-based** (107.4, 84.4) and
   contradicted Alex's newer Q64–73 keys under the 3a decision; re-keyed to
   104.4 / 83.6. Same-crew keys now agree across the whole set.
7. **Haiku's SQL lane is not deterministic**: Q65 flipped 58.6 → 125.9 → 58.6
   across three runs with an identical prompt. Temperature is not set on
   the SQL model (the router got temperature=0 in WO8). Next measured change.
8. **Two harness bugs surfaced by the new files**: the gate's sensitivity
   extraction stopped at the first `;` inside a comment and still looked
   for `CREATE VIEW` (fixed, `7103325`); `run_eval.py` crashed on a
   subset with no semantic question (context precision None) *after*
   spending the tier-3 money (fixed, `00b9d18`).
9. **Eval wall time is the judge, not Voyage.** 5 s of a 13-minute run is
   Voyage; ~9 minutes is unrecorded router + Sonnet-judge latency.

## Cost

Crew subsets 4 × ≈$0.12 = $0.53 (one of them lost to the run_eval crash) + full run A $1.06 + full run B $1.09 → **≈ $2.70**, under the $3 budget with little margin — which is why run B was not preceded by a fifth subset.

# WO10 — SQL-lane determinism, eval latency, and the WO9 loose ends

Date: 2026-09-10 · commits `e704ae3` … `2fc04c4` · follows `wo9_status_widening.md`

Four items were queued at the end of WO9. Two are engineering and were
done and measured here; two are Alex's decisions, for which this report
prepares the material.

## 1. SQL lane temperature=0 (commit `e704ae3`)

`generate_sql` and `repair_sql` now call Haiku with `temperature=0`, the
same change the router got in WO8. Reason: in WO9 Q65 alternated between
the correct two-CTE per-visit query (58.6) and a per-visit-row join (125.9)
across four runs with an identical prompt.

Determinism check — the 14-question crew subset (Q34–37, Q64–73) run twice
back to back at temperature 0:

| q | run 1 | run 2 | SQL text | SQL rows |
|---|---|---|---|---|
| Q34 | ✓ | ✓ | identical | identical |
| Q35 | ✓ | ✓ | identical | identical |
| Q36 | ✓ | ✓ | identical | identical |
| Q37 | ✓ | ✓ | identical | identical |
| Q64 | ✓ | ✓ | identical | identical |
| Q65 | ✓ | ✓ | identical | identical |
| Q66 | ✓ | ✓ | identical | identical |
| Q67 | ✓ | ✓ | identical | identical |
| Q68 | ✓ | ✓ | DIFFERENT | identical |
| Q69 | ✓ | ✓ | identical | identical |
| Q70 | ✓ | ✓ | identical | identical |
| Q71 | ✓ | ✓ | identical | identical |
| Q72 | ✓ | ✓ | identical | identical |
| Q73 | ✓ | ✓ | identical | identical |

Run 1: 14/14 correct · run 2: 14/14 correct · SQL text identical on 13/14, result rows identical on 14/14. Cost $0.18 + $0.18.

## 2. Eval latency recorded + `--workers` (commit `1022892`)

- `run_router` stores its wall time on the row; `judge_answer` stores its
  wall time in the generation record. Both land in the run JSON per
  question and as `tier3.latency_totals`, alongside `wall_seconds`.
- `run_eval.py --workers N` runs tier 3 on a thread pool. Each worker owns
  its own Postgres connection; every Claude/Voyage call already builds its
  own client, so rows share nothing. `--workers 1` (default) is the
  pre-WO10 sequential path.

Measured on the full 82-question run:

| stage | WO9 run B (1 worker, summed) | WO10 (4 workers, summed) |
|---|---|---|
| router | not recorded | 137 s |
| text-to-SQL | 107 s | 105 s |
| answer | 152 s | 150 s |
| judge | not recorded | 411 s |
| **tier-3 wall clock** | ~780 s (whole run) | **172 s** (whole run 319 s) |


## 3. Q29 / Q82 rules (commit `2fc04c4`)

- "Find / how many jobs with <kind of work>" is now spelled out as
  `COUNT(DISTINCT job_id) … WHERE type_name = X AND happened` — the unit
  Alex's Q29 key (236) uses. The run-to-run flip between 236, 246, 279 and
  291 was the lane changing unit each time.
- "Which jobs had a template wasted because of <reason>" filters
  `matched_note` and counts DISTINCT jobs; the answerer says "N jobs
  (M templates)" when a job carries two. Q82 had reported 17 jobs for 16.

Result in the full run: Q29 ✓ — "There are **236 jobs with tile work** [SQL], counting only dated, completed tile activities."; Q82 ✓ — "Based on the SQL results, **16 jobs had a template wasted because cabinets weren't ready** [SQL]:

Jobs 60, 293, 853, 92" (judge: The system's list of 16 job IDs matches the SQL query result and the expected ground truth exactly. The quoted notes correctly cite chunk evidence. It omits the)

## 4. Material for Alex's decisions

### 4a. The blank-salesperson bucket

816 template trips on 651 jobs (52 wasted) have no salesperson on the job.
It is almost entirely history: 2020–2021 account for 441 of the 816 trips,
2025–2026 for 19.

| template year | trips | wasted | jobs |
|---|---|---|---|
| 2020 | 220 | 11 | 183 |
| 2021 | 221 | 17 | 173 |
| 2022 | 88 | 4 | 77 |
| 2023 | 182 | 11 | 150 |
| 2024 | 86 | 5 | 70 |
| 2025 | 11 | 2 | 7 |
| 2026 | 8 | 2 | 6 |

Across all jobs the blank share falls from 50% of 2020's jobs (535/1,067)
to 2% of 2025's (19/849), so the field is being filled now; the bucket is
a legacy-data problem, not a current process one.

Can a PM be inferred? The dated Quote/Measure activities on those jobs
name an assignee on 399 of the 651 jobs — Crew W 166, Crew K 137, Crew K+Crew W
24, Crew B 21, Crew C 15, Crew K+Crew T 13, Crew B+Crew W 7 — and 252 jobs have
no assigned Quote/Measure at all. Job notes never mention a PM name.

**Decision for Alex** (not applied — the view reads `v_jobs.salesperson`
verbatim, raw-first): (a) leave the bucket as "(unassigned)", which is what
the per-PM rollup does today; (b) add an `inferred_pm` column to the view
that falls back to the Quote/Measure assignee when salesperson is blank —
attributes 399 jobs, leaves 252, and would need its own gate because the
assignee of a Quote is not always the PM who sold it; or (c) backfill
`salesperson` in Moraware for the 2020–2023 jobs, which fixes the source.
Recommendation: (a) for reporting now, (c) if the historical per-PM number
matters, never (b) silently.

### 4b. Matched-note pruning sheet

The 42 distinct notes that currently fire the note signal (v2 view), with
job ids, as printed by `scripts/verify_wasted_templates.py`:

```
(42 distinct notes)
  [measure      ] x1  jobs 1277
      [note text]
  [measure      ] x1  jobs 1964
      Farm sink not installed
  [measure      ] x1  jobs 560
      [note text])
  [measure      ] x1  jobs 1298
      Outdoor was not ready yet (02/23)
  [next_template] x1  jobs 5094
      3 | Curbs issues / retemplate
  [next_template] x1  jobs 5220
      #[note text]
  [next_template] x1  jobs 3516
      For [customer] [note text] | [customer] | [note text] s
  [next_template] x1  jobs 5269
      Kitchen 2nd Trip
  [next_template] x1  jobs 3516
      Maybe [customer] | [note text] | [customer]: | [note text] every
  [next_template] x1  jobs 2864
      [note text]
  [next_template] x1  jobs 4328
      RETEMPLATE | #4
  [next_template] x1  jobs 3548
      Retemplate bar
  [next_template] x1  jobs 1826
      [note text] off
  [next_template] x1  jobs 3100
      Second Trip
  [next_template] x1  jobs 852
      [note text]
  [next_template] x1  jobs 2783
      template wine bar again
  [template     ] x1  jobs 4882
      #3 | please check with [customer] [note text]
  [template     ] x1  jobs 5284
      #[note text]
  [template     ] x1  jobs 4882
      #4 | please check with [customer] [note text]
  [template     ] x1  jobs 1220
      [note text]
  [template     ] x1  jobs 293
      [note text] | meet with [customer] [note text] laundr
  [template     ] x1  jobs 2272
      Cabinets were not ready
  [template     ] x1  jobs 60
      [note text] 
  [template     ] x1  jobs 3853
      [note text]
  [template     ] x1  jobs 4743
      [note text]
  [template     ] x1  jobs 5660
      [note text]
  [template     ] x1  jobs 478
      [note text].
  [template     ] x1  jobs 1574
      [note text]
  [template     ] x1  jobs 5491
      [note text].
  [template     ] x1  jobs 3622
      Kitchen only other cabinets not installed
  [template     ] x1  jobs 1709
      Laundry and Master Shelve not Ready
  [template     ] x1  jobs 4934
      [note text] ([customer] Pieces) | Template Kitchen what's installed
  [template     ] x1  jobs 2574
      master bath is not ready
  [template     ] x1  jobs 5142
      [note text]
  [template     ] x1  jobs 5015
      [note text]
  [template     ] x1  jobs 4716
      Not ready yet
  [template     ] x1  jobs 807
      [note text]
  [template     ] x1  jobs 853
      [note text]
  [template     ] x1  jobs 1251
      Top cabinets not installed yet
  [template     ] x1  jobs 1334
      Two cabinets not ready yet
  [template     ] x1  jobs 925
      [note text]
  [template     ] x1  jobs 2195
      [note text]
```

Alex's rulings so far are applied (2262/2676/3714 removed, 853 kept). Each
remaining line is a keep/drop decision; drops become a lookaround in the
`params` CTE of `sql/015`, the same way 2b was done.

### 4c. Keys awaiting sign-off

- Q74–82 (re-keyed to the v2 view in WO9), Q36/Q37 (re-keyed to the
  all-jobs denominator), Q64–73 (verified in WO9's final run), Q59–63 and
  Q30 (superseded v3 numbers from the PIPE WO), Q16/Q14 (placeholder-
  inflated keys, open decision #0).

## Full run

| run | commit | q | routing | generation | faithfulness | cost | wall |
|---|---|---|---|---|---|---|---|
| WO9 run B | `269b66d` | 82 | 96.3% | 73.2% (60/82) | 87.3% | $1.09 | ~13 min |
| WO10 (temp 0, 4 workers) | `2fc04c4` | 82 | 96.3% | 73.2% (60/82) | 87.3% | $1.10 | 5.3 min |

By block:
- Q1–63: 41/63 correct
- Q64–73 crew: 10/10 correct
- Q74–82 wasted: 9/9 correct

Changes vs WO9 run B: Q28 [FAILING] semantic/✓ → semantic/✗; Q29 [verified] structured/✗ → structured/✓; Q31 [draft] structured/✓ → structured/✗; Q47 [draft] semantic/✓ → semantic/✗; Q58 [draft] semantic/✗ → semantic/✓; Q82 [draft] hybrid/✗ → hybrid/✓.

Incorrect: Q11, Q16, Q28, Q30, Q31, Q39, Q41, Q42, Q43, Q44, Q45, Q47, Q48, Q49, Q51, Q52, Q54, Q56, Q57, Q59, Q60, Q61.

## Surprises

1. **4 workers cut the whole run from ~13 minutes to 5.3** (tier 3 itself
   172 s) with scores identical to the sequential WO9 run B (96.3 / 73.2 /
   87.3). No DB or API contention at 4; memory on the box stayed >1 GB free.
2. **The judge is the eval.** Summed per-question latency: judge 411 s,
   answer 150 s, router 137 s, SQL 105 s. Sonnet 5 with thinking, up to
   4,000 tokens, sometimes twice — 52% of all model time.
3. **temperature=0 is near-deterministic, not deterministic**: Q68's SQL
   text differed between the two subset runs (same rows, same answer). That
   is expected of the API; identical result rows on 14/14 is the useful
   guarantee.
4. **Q31 went red for the same reason Q68 was red in WO9** — the SQL had
   the 29 visits but the answerer only stated sq ft and jobs. The
   "report every crew-workload number" rule catches "how many jobs" wording
   but not "how many square feet did X install". Draft row, known third-
   number problem (open decision #0); left as is.
5. **The blank-salesperson bucket is a 2020–2023 artefact**, not a current
   process failure: 2% of 2025 jobs lack a salesperson vs 50% of 2020 jobs.
6. **Q29 and Q82 both pass** once the unit is spelled out — the flip-flops
   were the lane choosing a different unit each run, which temperature=0
   alone would have frozen at whichever unit it sampled first.

## Cost

Two crew subsets $0.18 + $0.18 + full run $1.10 → **≈ $1.46**.

---

# Addendum 2026-09-14 — the measurement as specified

The 2026-09-10 section above measured Change 1 on the 14-question crew
subset twice, and Change 2 as one summed judge number with no per-stage
table. The work order asks for the structured subset three times plus one
pre-change run, and a per-stage table against wall time with the untimed
residual. This addendum is that measurement, at commit `ff101ab`
(harness: `--route structured --no-judge` subset flags, stage table,
judge call count; no view, prompt, key or model change).

## Change 1 — three post-change runs, one pre-change run

Structured subset = every `route=structured` golden row: 53 questions
(33 verified, 20 draft). Judge-free numeric scoring, 4 workers, ~$0.43 and
~112 s per run. Router 53/53 on all four runs.

| run | code | correct | failing set | Q65 |
|---|---|---|---|---|
| post 1 · `2026-09-14-0819-structured.json` | `ff101ab` | 45/53 | 11, 16, 26, 31, 59, 60, 61, 63 | **58.6** |
| post 2 · `2026-09-14-0821-structured.json` | `ff101ab` | 45/53 | 11, 16, 26, 31, 59, 60, 61, 63 | **58.6** |
| post 3 · `2026-09-14-0822-structured.json` | `ff101ab` | 45/53 | 11, 16, 26, 31, 59, 60, 61, 63 | **58.6** |
| pre (sampling) · `2026-09-14-0824-structured-notemp-ablation.json` | `ff101ab` minus both `temperature=0` lines | 43/53 | 11, 16, 26, 31, **34**, 59, 60, 61, 63, **68** | 58.6 |

**Verdict: deterministic.** The three post-change failing sets are
identical, and no question's correctness flipped across the three runs.

Below the pass/fail line, temperature=0 is not byte-identical: SQL text
was identical on 49/53 questions and result rows on 50/53. The four that
differed (Q8, Q35, Q63, Q76) differed only in an alias name (`vi` vs
`ji`) or an extra supporting column (Q35 added visits and sq ft/visit;
Q76 added total templates and waste rate; Q63 returned invoice number and
date instead of a count). Every headline number was the same on all three
runs. Identical result rows are not guaranteed by the API; identical
answers are what the eval needs, and it got them.

Q26 ("which jobs went quiet after a quote") sits in every failing set
because its expected answer contains no number, so judge-free scoring
cannot score it; in the full run the judge marks it correct (it declines,
as the key says it should). The real judge-free failing set is therefore
seven questions, all of them the known key/scoring problems (Q11, Q16,
Q31, Q59–61, Q63).

**The pre-change run.** The work order asks for `cbd24ae`. That commit
also predates the Q29/Q82 prompt rules (`2fc04c4`) and its harness cannot
run a judge-free subset, so a run there would have conflated three
changes. The ablation instead runs the current code with only the two
`temperature=0` lines removed — the single variable the change touched.
It lost two questions that the greedy path answers: Q34 and Q68 both
sampled a bare `COUNT(DISTINCT job_id)` and answered "35 jobs" / "16
jobs" with no sq ft — the same third-number failure class as WO9's Q68.
Q65 came out 58.6 on this one sampling run; the 125.9 double-count seen
in WO9 was one of four runs then, and one draw here did not reproduce it.
One run cannot show a distribution; it shows that sampling produced a
different failing set than the greedy path, which is the point.

**Accuracy did not drop** with temperature=0: the greedy path scored 45/53
against the sampling run's 43/53.

## Change 2 — per-stage timing on the full run

Full Tier 1–3 run, **`--workers 1`** (sequential, so the stage sum is
comparable to wall time), `2026-09-14-0837-full.json`, $1.06.

| stage | total seconds | % of wall time | calls |
|---|---|---|---|
| router | 116.4 | 15.8% | 82 |
| embed (Voyage, one batch) | 0.5 | 0.1% | 1 |
| bm25 | 0.8 | 0.1% | 26 |
| dense | 0.8 | 0.1% | 26 |
| rerank (Voyage) | 5.3 | 0.7% | 26 |
| sql | 92.3 | 12.5% | 59 |
| answer | 127.3 | 17.3% | 79 |
| judge (one call scores faithfulness + correctness + context precision) | 392.8 | 53.3% | 79 |
| **sum** | **736.2** | **99.9%** | |
| **actual wall time** | **737.0** | 100% | |
| **gap (untimed)** | **0.8** | 0.1% | |

The residual blind spot is **0.8 s of 737 s**. The harness is fully
instrumented. Rerank was already timed separately from fuse inside
`run_retrieval` (fuse is in-process RRF and takes no measurable time); the
CLI simply never printed it. The judge is a single Sonnet call per
question that returns all three metrics in one JSON verdict, so it is one
stage with a call count rather than three timers; no question needed the
second (retry) call in this run. Calls: 3 refuse rows skip answer and
judge; 59 SQL calls = 57 predicted-structured + 2 hybrid.

Where the time goes at 1 worker: judge 53%, answer 17%, router 16%, SQL
13%. Retrieval end to end is 1% of the run. The `--workers 4` path from
2026-09-10 overlaps these (319 s wall for the same work).

## Post-WO10 baseline vs WO9

| run | commit | workers | routing | generation | faithfulness | ctx precision | cost | wall |
|---|---|---|---|---|---|---|---|---|
| WO9 run B | `cbd24ae` | 1 | 96.3% | 73.2% (60/82) | 87.3% | — | $1.09 | ~780 s |
| WO10 (2026-09-10) | `2fc04c4` | 4 | 96.3% | 73.2% (60/82) | 87.3% | — | $1.10 | 319 s |
| **WO10 final (2026-09-14)** | `ff101ab` | 1 | 96.3% | **72.0% (59/82)** | **91.1%** | 56.2% | $1.06 | 737 s |

One question changed against the 2026-09-10 run: **Q68 ✓ → ✗**. Its SQL
returned the identical row (16 jobs, 23 visits, 1,089.5 sq ft) in both
runs and in all three subset runs; in this full run the answerer wrote
"16 jobs … 23 install visits … 7 required a second visit" and left the sq
ft out. The answer model still samples at its default temperature, so
that stage is the remaining run-to-run variance in the generation score;
it is out of scope here (the work order leaves the answer model
untouched) and is the obvious next one-line experiment. Incorrect set:
Q11, Q16, Q28, Q30, Q31, Q39, Q41–45, Q47–49, Q51, Q52, Q54, Q56, Q57,
Q59–61, Q68.

## Surprises (addendum)

1. **The blind spot was already closed by the 2026-09-10 timers** — the
   gap is 0.8 s. WO9's "9 minutes unaccounted for" was entirely router +
   judge.
2. **temperature=0 froze the outcome, not the bytes.** 4/53 SQL texts and
   3/53 row sets still varied, all cosmetically. Anyone building a
   byte-level SQL cache on the assumption of determinism should not.
3. **The residual nondeterminism moved to the answerer.** Q68 flipped on
   answer phrasing with identical SQL rows. SQL determinism is done;
   answer determinism is the next lever, and it is the same one-line
   change.
4. **Q26 is unscorable without the judge** (no number in the key). Any
   judge-free structured run will list it as failing; it is not.
5. **A single sampling run did not reproduce Q65 = 125.9.** The
   double-count is a minority draw; WO9 hit it 1-in-4.

## Cost (addendum)

4 subset runs × $0.43 + full run $1.06 → **$2.78** this session;
**$4.24** for WO10 overall (over the $3 target, under the $5 stop line).
The overrun is the Sep 10 measurement that this addendum redoes.

## Housekeeping

Four `while true … pgrep -f run_eval.py` monitor loops from the WO8/WO9
sessions are still running on the server (PIDs 1558705, 1558976,
1562126, 1563413). Their `pgrep -f run_eval.py` matches their own command
line, so they never see the eval exit. They are idle `sleep` loops and
harmless, but they should be killed: `kill 1558705 1558976 1562126
1563413`. Not done here — the session's permission mode declined a kill
on the server.

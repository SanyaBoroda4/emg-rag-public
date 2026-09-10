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
name an assignee on 399 of the 651 jobs — Victor 166, Max 137, Max+Victor
24, Diana 21, Eugene 15, Max+Sasha 13, Diana+Victor 7 — and 252 jobs have
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
      2/15 not ready, Bruce will reschedule it | See if it’s ready
  [measure      ] x1  jobs 1964
      Farm sink not installed
  [measure      ] x1  jobs 560
      Measure and Template at the same time (Island not ready)
  [measure      ] x1  jobs 1298
      Outdoor was not ready yet (02/23)
  [next_template] x1  jobs 5094
      3 | Curbs issues / retemplate
  [next_template] x1  jobs 5220
      #3 | lockbox code 0103 | Redo of template because sink wasnt on site first trip
  [next_template] x1  jobs 3516
      For Aaron from Myrtle Beach | 5142 and check if other units are ready on the 4th floor | Aaron | 5126 Full Wall FPL (after templating put templating s
  [next_template] x1  jobs 5269
      Kitchen 2nd Trip
  [next_template] x1  jobs 3516
      Maybe Aaron | Measure kitchen backsplash for 620,622,624,626,628 | Aaron: | 5630 if cabinets installed then everything plus full wall FPL | 5632 every
  [next_template] x1  jobs 2864
      Measure/Template kitchen + Master & Bar | we will try to reuse the quartz we removed for what's possible | Second trip to remeasure island
  [next_template] x1  jobs 4328
      RETEMPLATE | #4
  [next_template] x1  jobs 3548
      Retemplate bar
  [next_template] x1  jobs 1826
      Retemplate tall backsplash behind the stove. Dolphins asked to do this job ASAP! Problems with clients on their end. | Pick up check from dolphins off
  [next_template] x1  jobs 3100
      Second Trip
  [next_template] x1  jobs 852
      template again because the client wants   to change the placement of the sink
  [next_template] x1  jobs 2783
      template wine bar again
  [template     ] x1  jobs 4882
      #3 | please check with Susan does she ready ? | 21.7 sqft | Cabinets were not ready
  [template     ] x1  jobs 5284
      #3Tall splash | Missing outlet boxes cant template tall splash | Water fall 35 3/4
  [template     ] x1  jobs 4882
      #4 | please check with Susan does she ready ? | 21.7 sqft | Cabinets were not ready
  [template     ] x1  jobs 1220
      Apt B done, Apt A not ready yet
  [template     ] x1  jobs 293
      Bck behind the stove TBD | One cabinet is not installed | meet with Lizzy to talk about the curbs, template backsplash for kitchen and possibly laundr
  [template     ] x1  jobs 2272
      Cabinets were not ready
  [template     ] x1  jobs 60
      call him before you go | (843) 367-3850 | Only bath top is done templating, the rest is not ready yet. Will be ready after the tile is installed, and 
  [template     ] x1  jobs 3853
      Cant template due to tile on floor being installed
  [template     ] x1  jobs 4743
      client needed to redo some cabinets before i could template
  [template     ] x1  jobs 5660
      Clients were not ready for template, discussed doing both the hearth and the surround. And then left because i needed the mantle to be installed prior
  [template     ] x1  jobs 478
      Everything is templated except one uninstalled vanity in unit A.
  [template     ] x1  jobs 1574
      In the afternoon, they removed the tops | Not ready for template, didn’t removed yet
  [template     ] x1  jobs 5491
      Job 3 | Could not template. | Measurement included a cabinet that will be installed later.
  [template     ] x1  jobs 3622
      Kitchen only other cabinets not installed
  [template     ] x1  jobs 1709
      Laundry and Master Shelve not Ready
  [template     ] x1  jobs 4934
      Master and Powder cabinets are not set yet (Furniture Pieces) | Template Kitchen what's installed
  [template     ] x1  jobs 2574
      master bath is not ready
  [template     ] x1  jobs 5142
      Measure missing cabinets and maybe for FHBCK | Cabinets werent installed couldnt template
  [template     ] x1  jobs 5015
      Met with cally, cabinets needed to be adjusted prior to template, discussed timelines and requirements for installtions - no template
  [template     ] x1  jobs 4716
      Not ready yet
  [template     ] x1  jobs 807
      template everything with exception  of outdoor kitchen which is not ready
  [template     ] x1  jobs 853
      They Adjusted the Cabinets | Tom Called The Pass Today
  [template     ] x1  jobs 1251
      Top cabinets not installed yet
  [template     ] x1  jobs 1334
      Two cabinets not ready yet
  [template     ] x1  jobs 925
      Vanity cabinets not installed | Panel on the kitchen
  [template     ] x1  jobs 2195
      Vanity is ready cut by measurements | 02.24 Kitchen cabinets not installed yet | CALL BEFORE COMING
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

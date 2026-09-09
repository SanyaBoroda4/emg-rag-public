# WO8 — Wasted-template detection (`v_wasted_templates`)

Date: 2026-09-08/09 · commits `25b31b8` … `3379b69` · DB snapshot as-of 2026-07-30

**Headline:** 266 of 3,534 real template trips (7.5%) were wasted. The rule
reproduces all 10 of Alex's hand verdicts plus the 680/772 edge cases
(gate PASS). Victor Slabunov has the most wasted templates (54, 12.1% of
his trips); Diana Diaz has the worst rate (12.6%); Galya Gornishka the best
(4.8%). 2026 is the worst year so far (12.2%). The 30-day phase cutoff is
not sensitive: ±15 templates at 21/45 days, 5% of the total.

## What was built

| deliverable | where |
|---|---|
| view, one row per real template | `sql/014_wasted_templates.sql` → `v_wasted_templates` |
| rollup per PM per year | `v_wasted_templates_by_pm` (same file) |
| SQL lane: whitelist, schema prompt, rules; router hint; answerer rule | `retrieval/sql_lane.py`, `retrieval/router.py`, `retrieval/answer.py` |
| RO role list (also repaired: was missing `v_job_sqft`, `v_job_pipeline_status`) | `scripts/setup_ro_role.py` |
| gate + report + sensitivity | `scripts/verify_wasted_templates.py` |
| golden rows Q74–82 (draft, view-derived) | `evals/golden_set.csv` |

Definition as implemented (Step 0–4 of the WO), with the two places the
literal spec had to be interpreted — both reported below under *Surprises*:

- **Step 0** real = `status_name IN ('Complete','Paid in Full and Finished') AND activity_date IS NOT NULL` for Template and Install.
- **Step 1** phases: gap > `phase_gap_days` (30, single constant in the `params` CTE) starts a new phase.
- **Step 2** structural: every template but the last in its phase is wasted if no real Install falls strictly between it and the next template.
- **Step 3** note: readiness-failure regex on the template's own note, or on a Measure note **dated the same day** (one visit, the note often sits on the Measure row — job 478). Redo phrases (`retemplate`, `template … again`, `second trip`, `wasn't ready last time`) are written on the *redo* trip, so they flag the **previous** template of the same phase, and a note carrying a redo phrase is never used as readiness evidence against its own template.
- **Step 4** `wasted = structural OR note`; `wasted_reason` ∈ structural / note / both.

## Verification gate — full output

```
1c73384 feat: verify_wasted_templates gate - asserts Alex's 10 verdicts + 680/772 edges, full report, 21/30/45-day sensitivity
=== GATE: Alex's hand-verified jobs ===
job   478: expected wasted/note        got 2020-05-20 both              OK   [vanity not installed - count as wasted]
job   852: expected wasted/structural  got 2020-11-11 both              OK   [no note, two templates one phase, one install]
job  1084: expected wasted/structural  got 2021-02-01 structural        OK   [one install confirms]
job  1422: expected not wasted         got not wasted                   OK   [two phases, gap too big]
job  1681: expected not wasted         got not wasted                   OK   [same]
job  2216: expected not wasted         got not wasted                   OK   [no note, nothing wrong]
job  3117: expected not wasted         got not wasted                   OK   [T-I-T-I, perfect sequence (negative trap)]
job  4743: expected wasted/note        got 2025-06-03 both              OK   [cabinets redone]
job  5015: expected wasted/note        got 2025-09-24 both              OK   [note]
job  5491: expected wasted/note        got 2026-03-13 both              OK   [retemplate, one install]
job   680: expected not wasted         got not wasted                   OK   [second template is an undated Estimate (Step 0)]
job   772: 2023-07-07 template is phase 2 alone, 2020 pair is phase 1 OK
           2020 pair: 2020-10-14 structural_wasted=True reason=structural  (Alex expects Oct 14 wasted)
           2020 pair: 2020-10-15 structural_wasted=False reason=None  (Alex expects Oct 14 wasted)

--- full detail, all 12 jobs ---
  job date        ph t/ph i/ph next_t      ib    sw    nw    reason     src           note
  478 2020-05-20   1    2    1 2020-05-25  False True  True  both       template      Everything is templated except one uninstalled vanity in uni
  478 2020-05-25   1    2    1             False False False                          
  680 2020-07-22   1    1    1             False False False                          
  772 2020-10-14   1    2    1 2020-10-15  False True  False structural               
  772 2020-10-15   1    2    1             False False False                          
  772 2023-07-07   2    1    0             False False False                          
  852 2020-11-11   1    2    1 2020-11-12  False True  True  both       next_template template again because the client wants   to change the plac
  852 2020-11-12   1    2    1             False False False                          
 1084 2021-02-01   1    2    1 2021-02-10  False True  False structural               
 1084 2021-02-10   1    2    1             False False False                          
 1422 2021-04-06   1    1    1             False False False                          
 1422 2023-03-12   2    1    0             False False False                          
 1681 2021-07-08   1    1    0             False False False                          
 1681 2021-09-03   2    1    1             False False False                          
 2216 2022-09-21   1    1    1             False False False                          
 2216 2023-02-13   2    1    0             False False False                          
 3117 2023-04-19   1    2    1 2023-04-26  True  False False                          
 3117 2023-04-26   1    2    1             False False False                          
 4743 2025-06-03   1    2    1 2025-06-12  False True  True  both       template      client needed to redo some cabinets before i could template
 4743 2025-06-12   1    2    1             False False False                          
 5015 2025-09-24   1    2    1 2025-10-02  False True  True  both       template      Met with cally, cabinets needed to be adjusted prior to temp
 5015 2025-10-02   1    2    1             False False False                          
 5491 2026-03-13   1    2    1 2026-03-20  False True  True  both       template      Job 3 | Could not template. | Measurement included a cabinet
 5491 2026-03-20   1    2    1             False False False                          

GATE: PASS

=== REPORT ===
real templates: 3534   wasted: 266   wasted %: 7.5

--- by year ---
year     real  wasted    pct
2020      431      22    5.1
2021      625      42    6.7
2022      546      36    6.6
2023      538      46    8.6
2024      518      34    6.6
2025      556      47    8.5
2026      320      39   12.2

--- by salesperson (headline) ---
salesperson            real  wasted    pct
(blank)                 805      56    7.0
Victor Slabunov         446      54   12.1
Natalia Pavlenko        740      49    6.6
Alex Sorokin            555      35    6.3
Diana Diaz              206      26   12.6
Galya Gornishka         482      23    4.8
Sasha Nosova            216      19    8.8
Max Konikov              78       4    5.1
Vlad Gorshchynskiy        3       0    0.0
Eugene Konikov            2       0    0.0
Other                     1       0    0.0

--- by reason ---
  structural     222
  note            27
  both            17

same-day template pairs (two real Template rows on one date): 16, of which flagged structural: 16  <- decision for Alex: one trip or two?

--- every matched note (deduplicated) - for Alex to prune ---
(44 distinct notes)
  [measure      ] x1  jobs 1277
      2/15 not ready, Bruce will reschedule it | See if it’s ready
  [measure      ] x1  jobs 2676
      Can't template yet due to lack of glue gun
  [measure      ] x1  jobs 1964
      Farm sink not installed
  [measure      ] x1  jobs 560
      Measure and Template at the same time (Island not ready)
  [measure      ] x1  jobs 3714
      Need to confirm with Erick if they adjusted the cabinets and good to template
  [measure      ] x1  jobs 1298
      Outdoor was not ready yet (02/23)
  [next_template] x1  jobs 5094
      3 | Curbs issues / retemplate
  [next_template] x1  jobs 5220
      #3 | lockbox code 0103 | Redo of template because sink wasnt on site first trip
  [next_template] x1  jobs 3516
      Aaron | 5126 Full Wall FPL (after templating put templating side walls on your schedule if need to come back for the second trip) | 5122 BCK | 5128 BC
  [next_template] x1  jobs 3516
      Aaron: | 5630 if cabinets installed then everything plus full wall FPL | 5632 everything | 5634 everything | 5636 everything (1 kitchen cabinet wasn’t
  [next_template] x1  jobs 5269
      Kitchen 2nd Trip
  [next_template] x1  jobs 2864
      Measure/Template kitchen + Master & Bar | we will try to reuse the quartz we removed for what's possible | Second trip to remeasure island
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
  [template     ] x1  jobs 2262
      3.09 wasnt ready for install, contractor will need to put brackets and level the base (if they want to)
  [template     ] x1  jobs 4882
      #3 | please check with Susan does she ready ? | 21.7 sqft | Cabinets were not ready
  [template     ] x1  jobs 5284
      #3Tall splash | Missing outlet boxes cant template tall splash | Water fall 35 3/4
  [template     ] x1  jobs 4882
      #4 | please check with Susan does she ready ? | 21.7 sqft | Cabinets were not ready
  [template     ] x1  jobs 1220
      Apt B done, Apt A not ready yet
  [template     ] x1  jobs 293
      Bck behind the stove TBD | One cabinet is not installed
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

--- 15 most recent wasted templates ---
  2026-07-10 job 5268 'Chris Zegers - 2588 High Hammock'  PM=Victor Slabunov    structural https://granite-marble-tops.moraware.net/sys/job/5268
  2026-07-02 job 5768 'Rolina - 3 24th Ave'               PM=Victor Slabunov    structural https://granite-marble-tops.moraware.net/sys/job/5768
  2026-07-02 job 5767 'Rolina - 5805 Back Bay'            PM=Victor Slabunov    structural https://granite-marble-tops.moraware.net/sys/job/5767
  2026-07-02 job 5212 'Vintage Homes - 520 Bufflehead'    PM=Victor Slabunov    structural https://granite-marble-tops.moraware.net/sys/job/5212
  2026-06-26 job 5426 'Solaris - 3 Ocean Course'          PM=(blank)            structural https://granite-marble-tops.moraware.net/sys/job/5426
  2026-06-19 job 5445 'Mangan - 241 Tom Watson'           PM=Victor Slabunov    structural https://granite-marble-tops.moraware.net/sys/job/5445
  2026-06-18 job 5573 'Dolphins - 1204 Buist Ave (Prest'  PM=Victor Slabunov    structural https://granite-marble-tops.moraware.net/sys/job/5573
  2026-06-17 job 5616 'Isabelle Miller'                   PM=Natalia Pavlenko   structural https://granite-marble-tops.moraware.net/sys/job/5616
  2026-06-17 job 5445 'Mangan - 241 Tom Watson'           PM=Victor Slabunov    structural https://granite-marble-tops.moraware.net/sys/job/5445
  2026-06-16 job 5426 'Solaris - 3 Ocean Course'          PM=(blank)            structural https://granite-marble-tops.moraware.net/sys/job/5426
  2026-06-16 job 5212 'Vintage Homes - 520 Bufflehead'    PM=Victor Slabunov    structural https://granite-marble-tops.moraware.net/sys/job/5212
  2026-06-15 job 5445 'Mangan - 241 Tom Watson'           PM=Victor Slabunov    structural https://granite-marble-tops.moraware.net/sys/job/5445
  2026-06-10 job 5665 'Theresa Lenke_COSTCO'              PM=Alex Sorokin       structural https://granite-marble-tops.moraware.net/sys/job/5665
  2026-06-09 job 5660 'Debbie with Island Home Services'  PM=Natalia Pavlenko   both       https://granite-marble-tops.moraware.net/sys/job/5660
      note: Clients were not ready for template, discussed doing both the hearth and the surround. And then left because i
  2026-06-02 job 5464 'Kelley Fose'                       PM=Natalia Pavlenko   structural https://granite-marble-tops.moraware.net/sys/job/5464

=== SENSITIVITY: PHASE_GAP_DAYS ===
 gap   real  wasted    pct  struct  note max_phase
  21   3534     251    7.1     224    43         6
  30   3534     266    7.5     239    44         5
  45   3534     280    7.9     254    45         4

21 vs 30: +0 newly wasted, -15 no longer wasted (net -15)
   boundary jobs (15): 540, 637, 1352, 2081, 2164, 2654, 2864, 2929, 3226, 3232, 3321, 3891, 3999, 4517, 5267

45 vs 30: +14 newly wasted, -0 no longer wasted (net +14)
   boundary jobs (14): 1354, 2144, 2283, 2607, 2753, 2845, 2941, 3071, 3086, 3435, 3579, 3861, 4255, 5250

OK
```

## Per-PM table (headline)

| salesperson | real templates | wasted | wasted % |
|---|---|---|---|
| (blank) | 805 | 56 | 7.0 |
| Victor Slabunov | 446 | 54 | 12.1 |
| Natalia Pavlenko | 740 | 49 | 6.6 |
| Alex Sorokin | 555 | 35 | 6.3 |
| Diana Diaz | 206 | 26 | 12.6 |
| Galya Gornishka | 482 | 23 | 4.8 |
| Sasha Nosova | 216 | 19 | 8.8 |
| Max Konikov | 78 | 4 | 5.1 |
| Vlad Gorshchynskiy / Eugene Konikov / Other | 6 | 0 | 0.0 |

The blank salesperson bucket is the largest single group (805 trips, 56
wasted) — 23% of all template trips have no accountable PM on the job.

By year: 2020 5.1% · 2021 6.7% · 2022 6.6% · 2023 8.6% · 2024 6.6% ·
2025 8.5% · **2026 12.2%** (39 of 320, through July).

By reason: structural-only 222 · note-only 27 · both 17.

## Sensitivity — `PHASE_GAP_DAYS`

| gap | wasted | % | structural | note |
|---|---|---|---|---|
| 21 | 251 | 7.1 | 224 | 43 |
| **30** | **266** | **7.5** | **239** | **44** |
| 45 | 280 | 7.9 | 254 | 45 |

21 vs 30: −15 (15 boundary jobs: 540, 637, 1352, 2081, 2164, 2654, 2864,
2929, 3226, 3232, 3321, 3891, 3999, 4517, 5267). 45 vs 30: +14 (1354, 2144,
2283, 2607, 2753, 2845, 2941, 3071, 3086, 3435, 3579, 3861, 4255, 5250).
Movement is monotonic and small (≈5% of the total either way): 30 is safe;
the boundary jobs above are the ones to glance at if Alex wants to tune it.

## Matched notes — 44 distinct, for Alex to prune

Listed in full in the gate output above (section *every matched note*).
Likely false positives / borderline, flagged for pruning:

- job 853 *"They Adjusted the Cabinets"* — cabinets were fixed, not missing (matches `adjust… cabinets`).
- job 2262 *"3.09 wasnt ready for install"* — not ready for **install**, not template.
- job 2676 *"Can't template yet due to lack of glue gun"* — wasted trip, but EMG's fault, not the PM's.
- job 3714 (Measure, same day) *"Need to confirm with Erick if they adjusted the cabinets…"* — a pre-visit instruction, not a failure report.
- job 3516 (Kiawah condo, 15 templates in one phase) — two `next_template` hits from long multi-unit notes containing "second trip" / "last time".

Phrases the WO list missed that were needed for Alex's own examples and are
now in the regex: `uninstalled` (478), `redo … cabinets` / `before I could
template` (4743). Phrases seen in notes but deliberately **not** added
(would over-fire): bare `no template`, `not ready for install`, `cabinets
are missing`.

## 15 most recent wasted templates

In the gate output above. 12 of the 15 are structural-only and 9 of the 15
belong to Victor Slabunov's builder jobs (Rolina, Vintage Homes, Dolphins,
Mangan) in June–July 2026 — multi-visit builder projects are where the
structural signal fires most; Alex should confirm those are really extra
trips and not one project templated room by room on purpose.

## Golden set — Q74–82 (all `draft`)

| id | question | route | key (from the view) |
|---|---|---|---|
| 74 | wasted templates in total | structured | 266 |
| 75 | wasted templates in 2025 | structured | 47 |
| 76 | salesperson with the most | structured | Victor Slabunov, 54 |
| 77 | % wasted per salesperson 2025 | structured | Max 25.0, Victor 12.7, Diana 10.0, Natalia 9.1, Alex 6.1 |
| 78 | first template on job 852 wasted? | structured | yes — reason `both` (see surprises) |
| 79 | any template on 3117 wasted? | structured | **no** (negative trap) |
| 80 | template on 478 wasted? | structured | yes — `both`, uninstalled vanity |
| 81 | why was 4743 wasted? | hybrid | client needed to redo cabinets |
| 82 | jobs wasted because cabinets weren't ready | hybrid | 17 jobs / 18 templates |

## Re-measure

| run | commit | q | routing | generation | faithfulness | cost |
|---|---|---|---|---|---|---|
| Aug 14 baseline | `ffb5eeb` | 63 | 95.2% | 63.5% (40/63) | 91.7% | $0.71 |
| WO8 run 1 | `d19b336` | 82 | 96.3% | 61.0% (50/82) | 87.3% | $1.00 |
| WO8 run 2 (after `both` fix) | `5857959` | 82 | 96.3% | 62.2% (51/82) | 84.8% | $1.02 |

Run 1, new block Q74–82: **9/9 correct**, routing 9/9 (the two hybrids
routed hybrid, the seven structured routed structured). Two were judged
unfaithful: on Q78 and Q81 Haiku explained `wasted_reason = 'both'` as
"both dimensions and layout" / "multiple reasons related to cabinet
readiness" — fabricated. Fix (commit `5857959`): the answerer is told what
the three values mean, and job-level queries now select
`structural_wasted` / `note_wasted` and every template row of the job (a
`LIMIT 1` had hidden 852's second template). Run 2 re-measures that.

Run 2 (commit `5857959`), new block Q74–82: **9/9 correct, 7/9 faithful**.

- Q74 structured->structured correct=True faithful=False | The numeric answer (266) matches the ground truth and is directly supported by the SQL result. However, the detailed explanation of what constitutes 'structural
- Q75 structured->structured correct=True faithful=True | System's answer matches SQL result and expected answer exactly.
- Q76 structured->structured correct=True faithful=True | System's answer matches the ground truth exactly and is fully supported by the SQL result.
- Q77 structured->structured correct=True faithful=True | Matches expected values exactly and is fully supported by SQL evidence.
- Q78 structured->structured correct=True faithful=False | The answer correctly concludes the first template was wasted and correctly cites structural and note-based reasons matching the ground truth, but adds an unsupp
- Q79 structured->structured correct=True faithful=True | SQL results show both templates have wasted=False, matching expected answer that neither template was wasted due to install between them.
- Q80 structured->structured correct=True faithful=True | The system's answer matches the ground truth: job 478's first template (May 20, 2020) was wasted for reason 'both', citing the same note and the follow-up templ
- Q81 hybrid->hybrid correct=True faithful=True | The answer correctly identifies the reason from the matched note (client needed to redo cabinets) and accurately describes the structural waste indicator (next 
- Q82 hybrid->hybrid correct=True faithful=True | The system's answer correctly enumerates the same 17 jobs (18 wasted-template instances, including the duplicate for job 4882) as the expected answer, matching 

Run 1 → run 2 changes on the other 73 questions: Q14 run1 route=structured correct=False -> run2 route=structured correct=True; Q26 run1 route=structured correct=True -> run2 route=structured correct=False; Q44 run1 route=semantic correct=False -> run2 route=semantic correct=True; Q45 run1 route=semantic correct=True -> run2 route=semantic correct=False; Q46 run1 route=semantic correct=True -> run2 route=semantic correct=False; Q49 run1 route=semantic correct=False -> run2 route=semantic correct=True; Q54 run1 route=semantic correct=False -> run2 route=semantic correct=True. Same-63-question score: 41/63 = 65.1%.

Run 2's two unfaithful marks are the opposite failure from run 1: the
answerer now **restated the definition** it had been given ("structural =
another template trip followed…", "the site was not ready") and the judge,
seeing no such text in the evidence, marked it unsupported — correct
numbers both times. Commit `3379b69` tells the answerer to name the signal
and quote `matched_note` instead of explaining; spot-checked with
`scripts/query.py` on Q74 ("We have had 266 wasted templates in total
[SQL].") and Q78 (names both signals and quotes the note verbatim). Not
re-measured with a third full run — that would take the WO over its $3
budget. Overall faithfulness moved 87.3 → 84.8% between runs 1 and 2 on
the semantic block (Q45/Q46 flipped red, Q44/Q49/Q54 flipped green — the
judge's usual run-to-run noise on prose answers), not on anything this WO
touched.

Router: the new hint did not over-fire on the 73 pre-existing questions.
The only change is Q40 ("could not template because the cabinets were not
ready" — keyed semantic) now routes **hybrid**, still answered correctly;
given the view now exists, hybrid is arguably the better key. Routing went
95.2% → 96.3% overall (Q63 now routes structured and passes; Q41/Q56 are
the same two stable semantic→structured misses as before).

The generation percentage is lower than Aug 14 for reasons outside this
WO. On the 63 questions the Aug 14 run measured, run 1 scores the same
40/63 = 63.5% (Q45/Q47/Q63 flipped green, Q14/Q49/Q54 flipped red —
Q49/Q54 are semantic rows scored by the judge and have flip-flopped
before; Q14 now answers 5,629 happened Installs against the
placeholder-inflated key 7,758, open decision #0). The other 19 questions
are Alex's crew visit-vs-job block Q64–73 (added 2026-09-08, first
measured here) plus this WO's Q74–82. Nine of the ten crew questions fail,
for four distinct reasons worth separating:

- Q64/69/71 — the key divides total sq ft by ALL jobs (9,027.0 / 108 =
  83.6) while the lane's `AVG(total_sq_ft)` skips the one job with no area
  rows (9,027.0 / 107 = 84.4). Definition mismatch, not a data error.
- Q65/67/70 — per-VISIT averages: the lane joins `v_job_sqft` onto each
  visit row and averages job totals (126.8), instead of total sq ft /
  visits (58.6). The schema prompt only teaches the per-job pattern — a
  real lane gap, worth its own fix.
- Q66/68 — list-shaped keys; the answer had the visits and jobs but not
  the third number ("7 jobs required a second visit" / "23 install
  visits"), so the all-numbers-must-match scorer marks it wrong.
- Q73 — job 5874's two installs are dated Aug 31 / Sep 2 2026, after the
  2026-07-30 snapshot; keyed from live Moraware, unanswerable from this DB.

## Surprises / findings for Alex

1. **852 is `both`, not `structural`.** Alex said "no note"; the *first*
   template has none, but the *second* template's note says "template
   again because the client wants to change the placement of the sink".
   The redo-attribution rule turns that into a note signal on the first
   template. Wasted either way; the reason label is the only difference.
2. **Redo phrases had to be attributed to the previous template.** Read
   literally, the WO's note rule flags the template the phrase is written
   on — that would have counted the productive redo trips on 852 and 5491
   as second wasted templates (2 wasted per job, not 1). Implemented as:
   redo phrase on template N ⇒ template N−1 of the same phase is
   note-wasted; a redo phrase on the first template of a phase (jobs 1354,
   2958, 3497, 4283 — "Retemplate kitchen" months after the last template)
   flags nothing, consistent with the phase rule.
3. **Measure notes only count on the same day as the template.** 21
   Measure notes match the readiness regex; the 6 same-day ones are real
   failed visits (560, 1277, 1298, 1964, 2676, 3714). The other 15 are
   Measures days or weeks earlier that found the site not ready — the
   later template is the trip that *worked*, so attributing those would
   have flagged good templates.
4. **16 same-day template pairs are flagged structural** (two real
   Template rows on one date, no install "between" a zero-day gap). The
   spec is implemented literally; whether two rows on one day are one trip
   or two is Alex's call. Removing them would take the total to 250.
5. **The WO's pattern list missed Alex's own examples.** 478 ("uninstalled
   vanity") and 4743 ("needed to redo some cabinets before i could
   template") match none of the listed phrases; both patterns were added
   and are reported. Everything in the list is a starting point.
6. **Blank salesperson is the biggest bucket** (805 trips, 56 wasted). A
   per-PM accountability number is missing its PM on 23% of trips.
7. **`setup_ro_role.py` would have revoked two views.** Its list lacked
   `v_job_sqft` and `v_job_pipeline_status` (granted inside their
   migrations); a re-run does `REVOKE ALL` then grants the list. Fixed.
8. Eval runs now take ~13 minutes, not an hour — the Voyage rate limit
   appears to be gone.

## Cost

Run 1 $1.00 + run 2 $1.02 + smoke tests and spot-checks ≈ $0.05 → **≈ $2.07**, under the $3 budget.

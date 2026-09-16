# WO15 — Diagnostic: why `v_quoted_jobs` (4,236) ≠ `v_job_pipeline_status` (4,415 / 4,377)

Date: 2026-09-16 · read-only · psql against the frozen snapshot (as-of
2026-07-30) · no LLM calls, $0 · no code, view, prompt or golden change.

## 0. The premise needs one correction first

The work order describes `v_quoted_jobs` as "dated Estimate also counts; only
Estimate + blank date excluded". **That is not what the view does.** The
view's WHERE clause (quoted verbatim in §1) filters on
`status_name IN ('Confirmed','Complete','Paid in Full and Finished','In Progress')`
with no date condition at all — so an Estimate row is excluded **whether or
not it is dated**. This is what `sql/016` implemented on 2026-09-14, and it is
the only reading that reproduces Alex's 4,236 (accepting dated Estimates
gives 4,423). The consequence runs through the whole diagnostic: the B−A
bucket the WO expected to be "Canceled and similar" is entirely
**dated Estimate**, and the "bucket 2 should be 0" check is 0 by
construction, not by coincidence.

Second, smaller: there is no `Canceled` status on activities. Activity
statuses on Quote/Measure/Template rows are exactly Complete (9,224),
Estimate (7,170), Confirmed (225), Paid in Full and Finished (28), In
Progress (10), RTF (2). "Canceled" is a job `process_name`.

## 1. The two definitions, verbatim from the views

**`v_quoted_jobs`** (`pg_get_viewdef`, the signal CTE):

```sql
WITH sig AS (
  SELECT activities.job_id,
         bool_or(activities.type_name = 'Quote')                          AS has_quote_activity,
         bool_or(activities.type_name = ANY (ARRAY['Measure','Template'])) AS has_measure_or_template,
         min(activities.activity_date)                                    AS first_signal_date
  FROM activities
  WHERE activities.type_name  = ANY (ARRAY['Quote','Measure','Template'])
    AND activities.status_name = ANY (ARRAY['Confirmed','Complete','Paid in Full and Finished','In Progress'])
  GROUP BY activities.job_id
)
SELECT j.job_id, ... FROM jobs j JOIN sig s USING (job_id);
```

Rule: **status filter, no date condition, no as-of.**

**`v_job_pipeline_status`** (the `signals` CTE that defines `is_quoted`):

```sql
WITH signals AS (
  SELECT activities.job_id, min(activities.activity_date) AS first_signal_date, ...
  FROM activities
  WHERE activities.type_name = ANY (ARRAY['Quote','Measure','Template'])
    AND activities.activity_date IS NOT NULL
    AND activities.activity_date <= '2026-07-30'::date
  GROUP BY activities.job_id
)
...  s.job_id IS NOT NULL AS is_quoted
```

Rule: **date required and ≤ as-of, no status filter.**

**Conversion cohort** (`v_quote_conversion_monthly`):
`WHERE is_quoted AND (first_signal_date <= '2026-07-30' - 30 OR moved_forward)`.

Against the WO's table: the pipeline row is accurate; the `v_quoted_jobs`
row is wrong on the Estimate point (§0). The three axes are otherwise as
stated: date required (pipeline yes / WO11 no), status filter (WO11 yes /
pipeline no), as-of cutoff (pipeline yes / WO11 no).

## 2. Set membership

| set | definition | size |
|---|---|---|
| A | `SELECT DISTINCT job_id FROM v_quoted_jobs` | **4,236** ✓ |
| B | `v_job_pipeline_status WHERE is_quoted` | **4,415** ✓ |
| C | B ∩ conversion cohort | **4,377** ✓ |
| A ∩ B | | 4,231 |
| A − B | in WO11 only | **5** |
| B − A | in pipeline only | **184** |
| A − C | | 38 |
| C − A | | 179 |

Both anchors match exactly; no drift. 4,231 jobs are quoted under both
rules — the disagreement is 189 jobs, 4.3% of the union.

## 3. A − B: the 5 jobs only WO11 counts

| bucket | jobs | job_ids |
|---|---|---|
| 1 · accepted status but **no date on any** Quote/Measure/Template row | **2** | 4411, 4907 |
| 2 · signals dated only **after** as-of 2026-07-30 | **3** | 5814, 5849, 5859 |
| 3 · other | 0 | — |

Sum 5 = |A−B| ✓. Every Q/M/T row of the five:

| job | activity | type | status | date | accepted by WO11 |
|---|---|---|---|---|---|
| 4411 | 36242 | Quote | **Confirmed** | — | yes |
| 4411 | 36238 / 36243 | Template / Measure | Estimate | — | no |
| 4907 | 40539 | Quote | **Confirmed** | — | yes |
| 4907 | 40535 / 40540 | Template / Measure | Estimate | — | no |
| 5814 | 49303 | Template | **Confirmed** | **2026-08-03** | yes |
| 5849 | 49760 | Template | **Confirmed** | **2026-08-03** | yes |
| 5859 | 49848 | Template | **Confirmed** | **2026-08-03** | yes |

Bucket 2 is the as-of axis alone: three templates *booked* for 4 days after
the snapshot. The pipeline view will count them the day its as-of moves.
Bucket 1 is the date axis: two quotes whose status was set to Confirmed
without a date ever being entered.

## 4. B − A: the 184 jobs only the pipeline counts

| bucket | jobs |
|---|---|
| 1 · dated Q/M/T ≤ as-of, **every** status outside WO11's list | **184** |
| 1b · dated signal outside the list, but an accepted-status row exists elsewhere on the job | 0 |
| 2 · dated Estimate that WO11 "nevertheless excluded" | 0 — by construction, WO11 never accepts Estimate (§0) |
| 3 · other | 0 |

Sum 184 = |B−A| ✓. By the status of their dated signals:

| dated signal status | jobs |
|---|---|
| Estimate | **184** |
| anything else | 0 |

So bucket 1 is one thing: **jobs whose only dated quote-stage activity is an
Estimate-status row.** Not Canceled (no such activity status), not RTF. By
which types carry the date:

| dated types on the job | jobs |
|---|---|
| Quote only | 142 |
| Measure only | 22 |
| Template only | 13 |
| Measure + Template | 3 |
| Measure + Quote | 2 |
| Quote + Template | 2 |

By first-signal year (with how many are Canceled jobs and how many moved):

| year | jobs | Canceled (process_name) | moved |
|---|---|---|---|
| 2020 | 3 | 3 | 0 |
| 2021 | 4 | 3 | 0 |
| 2022 | 12 | 10 | 2 |
| 2023 | 13 | 13 | 1 |
| **2024** | **82** | 79 | 2 |
| 2025 | 54 | 33 | 2 |
| 2026 | 16 | 7 | 1 |

136 of the 184 (74%) are 2024–2025 — a dated-but-never-advanced quote row is
mostly a recent pattern, not legacy noise.

## 5. Consequences for the numbers people already use

### 5a. B − A bucket 1 (the 184 dated-Estimate jobs) inside the pipeline view

| pipeline status | jobs | in cohort | moved |
|---|---|---|---|
| quiet | 171 | 171 | 0 |
| moved | 8 | 8 | 8 |
| pending | 5 | 0 | 0 |

179 of the 184 are in the conversion cohort; 171 of those are `quiet`. That
is the whole story of their effect on the headline: they are almost all
denominators with no numerator.

| conversion | quoted | moved | rate |
|---|---|---|---|
| **with** them (current v4, the 70.0% everyone quotes) | 4,377 | 3,063 | **70.0%** |
| **without** them (WO11's status rule applied to the cohort) | 4,198 | 3,055 | **72.8%** |

By year:

| year | quoted with → without | rate with → without |
|---|---|---|
| 2020 | 845 → 842 | 68.2 → 68.4 |
| 2021 | 735 → 731 | 73.7 → 74.1 |
| 2022 | 597 → 585 | 79.1 → 80.3 |
| 2023 | 477 → 464 | 85.7 → 87.9 |
| **2024** | **632 → 550** | **63.4 → 72.5** |
| 2025 | 721 → 667 | 61.3 → 66.0 |
| 2026 | 367 → 356 | 59.9 → 61.5 |

Excluding Estimate-status quotes moves the headline by +2.8 points and
**2024 by +9.1 points** — the "2024 conversion collapsed" reading of the
current view is, to a large degree, 82 dated Estimate rows that never
advanced (79 of them on Canceled jobs). The golden keys Q59–Q62 (70.0 /
85.7 / 63.4 / 2023) would all move.

Two more facts about the 184: **148 (80%) are Canceled jobs**, and **73
(40%) have some later dated activity** of any type after the Estimate signal
(follow-ups, phone calls, the 8 installs) — so at least 73 were live
conversations, not orphan rows.

### 5b. A − B bucket 1 (the 2 undated Confirmed quotes)

| job | process_name | job status | created | dated activities of any type | last dated |
|---|---|---|---|---|---|
| 4411 | Canceled | Active | 2024-12-09 | 1 (a "Phone, Email" on creation day) | 2024-12-09 |
| 4907 | Canceled | Active | 2025-06-25 | 1 (a "Phone, Email" on creation day) | 2025-06-25 |

Both Canceled; both have exactly one dated event, a phone/email logged on the
day the job was created; nothing after. "Undated Confirmed quote and nothing
after" is, on this evidence, a status flag on a placeholder row rather than
a quote that was issued.

## 6. Five hand-checks

**Job 4411 — Shanda Bowman (A−B, undated Confirmed quote)** · Alex Sorokin · Canceled

| activity | type | status | date | note |
|---|---|---|---|---|
| 36244 | Phone, Email | Complete | 2024-12-09 | |
| 36242 | Quote | Confirmed | — | |
| 36238 / 36243 / 36239 / 36240 / 36241 | Template / Measure / Fabrication / Install / Invoice | Estimate | — | |

Quoted in reality? **doubtful** — a Confirmed flag on an undated quote row,
one phone/email on the creation day, no note, nothing after; it reads as a
lead that was marked and dropped.

**Job 4907 — Chad Covert (A−B, undated Confirmed quote)** · Alex Sorokin · Canceled

| activity | type | status | date | note |
|---|---|---|---|---|
| 40541 | Phone, Email | Complete | 2025-06-25 | |
| 40539 | Quote | Confirmed | — | |
| 40535 / 40540 / 40536 / 40537 / 40538 | Template / Measure / Fabrication / Install / Invoice | Estimate | — | |

Quoted in reality? **doubtful** — identical shape to 4411.

**Job 964 — Jessica Strait, Diana's Friend (B−A, moved)** · Galya Gornishka · Done

| activity | type | status | date | note |
|---|---|---|---|---|
| 6418 | Fabrication | Complete | 2020-11-18 | Fantasy Brown leathered small remnant… |
| 6419 | Install | Paid in Full and Finished | 2020-11-29 | Ready For Pick Up |
| 20758 | Measure | **Estimate** | **2022-09-02** | |
| 21419 | Install | Complete | 2022-09-17 | |
| 20755 / 20756 / 20757 / 20759 | Template / Install / Invoice / Meeting | Estimate | — | |

Quoted in reality? **yes** — a second piece of work in 2022: measured on
2022-09-02 and installed 15 days later. No Quote row was ever logged and the
Measure row's status was never advanced from Estimate, but the job was
measured, priced and built. WO11's status rule cannot see it; the pipeline's
date rule can. (The 2020 rows are the first job; the pipeline's `first_signal_date`
is 2022-09-02 because the 2020 work has no Q/M/T row at all.)

**Job 5655 — Michaela Kulyk (B−A, pending)** · salesperson "Other" · Job

| activity | type | status | date | note |
|---|---|---|---|---|
| 49708 | Measure | **Estimate** | **2026-07-30** | |
| 47314 / 47315 | Fabrication / Install | Estimate | — | |

Quoted in reality? **unknown** — a Measure scheduled on the snapshot day
itself, status never advanced, no Quote row, no note. This is the boundary
case the as-of date creates: on 2026-07-30 it is "a measure booked for
today"; a week later it is either a happened measure or a no-show, and
only the status (or a later note) would tell.

**Job 372 — Charles Ramberg / Candance (B−A, quiet)** · no salesperson · Canceled

| activity | type | status | date | note |
|---|---|---|---|---|
| 1853 | Quote | **Estimate** | **2020-04-03** | waiting on material selections from Candance |
| 1848 / 1852 / 1849 / 1850 / 1851 | Template / Measure / Fabrication / Install / Invoice | Estimate | — | |

Quoted in reality? **yes, as a conversation** — a dated quote row with a
human note about the customer's selections; the customer never came back
and the job was canceled. Whether a quote that was *discussed* but whose
row was never marked past Estimate counts as "issued" is exactly the
question below.

## 7. The question for Alex

The 4,231 jobs both views agree on are not in dispute. The 189 that differ
reduce to three precise questions:

1. **Do the 184 jobs whose only dated Quote/Measure/Template row has status
   `Estimate` count as quoted?** (142 by a dated Quote row, 42 by a dated
   Measure/Template.) 148 are Canceled jobs; 73 had later dated activity;
   8 went on to install. Counting them is the current pipeline rule and the
   70.0% / 63.4%-in-2024 conversion numbers; excluding them is the WO11
   rule, 72.8% overall and 72.5% in 2024, and re-keys Q59–Q62.
2. **Do the 2 undated `Confirmed` quotes with nothing after them (4411,
   4907) count as quoted?** Both are Canceled leads with one phone/email on
   the creation day.
3. **Should a quoted-jobs count respect the snapshot's as-of date?** The 3
   templates dated 2026-08-03 (5814, 5849, 5859) are counted by WO11 today
   and by the pipeline only once the as-of moves.

One answer to question 1 settles 184 of the 189 jobs and decides which
conversion rate is the company's number.

---

## Ruling and what was applied (2026-09-16)

**Alex: "count as quoted."** — the 184 dated-Estimate jobs are quoted.

Applied as `sql/019` (`v_quoted_jobs` v2): a job is quoted when it has a
Quote/Measure/Template that is in an accepted status (dated or not — the
WO11 wording kept, which answers question 2 "yes") **or is dated at all,
whatever its status**. No as-of cutoff (the WO11 wording kept, which
answers question 3 "yes, counted now").

| | v1 (`sql/016`) | **v2 (`sql/019`)** | pipeline `is_quoted` |
|---|---|---|---|
| jobs | 4,236 | **4,423** | 4,415 |
| via a Quote row | 2,680 | 2,864 | — |
| via Measure/Template proxy only | 1,556 | 1,559 | — |
| ∩ pipeline | 4,231 | **4,415 (all of it)** | — |
| only here | 5 | 8 | 0 |

The 8 jobs v2 counts that the pipeline does not are the as-of/date axes
only: 4411, 4907 (undated Confirmed quotes); 5814, 5849, 5859 (Confirmed
templates dated 2026-08-03); 5692, 5725, 5807 (Estimate-status
measure/templates dated 2026-08-04…15). The pipeline will pick up the six
dated ones when its as-of moves. Nothing the pipeline counts is missing
from v2, so the two views are now one definition with one cutoff
difference, not two definitions.

**Conversion rates unchanged**: the ruling keeps dated Estimates in, which
is what `v_job_pipeline_status` already did; 70.0% / 85.7% / 63.4% / 2023
stand, and Q59–Q62 keep their keys. Q16's key moves 4,236 → **4,423**.
Schema prompt updated to the v2 wording; `v_quoted_jobs` columns unchanged.

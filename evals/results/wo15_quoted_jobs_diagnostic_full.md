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

**Job 4411 — Customer #4411 (A−B, undated Confirmed quote)** · Salesperson A · Canceled

| activity | type | status | date | note |
|---|---|---|---|---|
| 36244 | Phone, Email | Complete | 2024-12-09 | |
| 36242 | Quote | Confirmed | — | |
| 36238 / 36243 / 36239 / 36240 / 36241 | Template / Measure / Fabrication / Install / Invoice | Estimate | — | |

Quoted in reality? **doubtful** — a Confirmed flag on an undated quote row,
one phone/email on the creation day, no note, nothing after; it reads as a
lead that was marked and dropped.

**Job 4907 — Customer #4907 (A−B, undated Confirmed quote)** · Salesperson A · Canceled

| activity | type | status | date | note |
|---|---|---|---|---|
| 40541 | Phone, Email | Complete | 2025-06-25 | |
| 40539 | Quote | Confirmed | — | |
| 40535 / 40540 / 40536 / 40537 / 40538 | Template / Measure / Fabrication / Install / Invoice | Estimate | — | |

Quoted in reality? **doubtful** — identical shape to 4411.

**Job 964 — [customer], Crew B's [customer] (B−A, moved)** · Salesperson E · Done

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

**Job 5655 — Customer #5655 (B−A, pending)** · salesperson "Other" · Job

| activity | type | status | date | note |
|---|---|---|---|---|
| 49708 | Measure | **Estimate** | **2026-07-30** | |
| 47314 / 47315 | Fabrication / Install | Estimate | — | |

Quoted in reality? **unknown** — a Measure scheduled on the snapshot day
itself, status never advanced, no Quote row, no note. This is the boundary
case the as-of date creates: on 2026-07-30 it is "a measure booked for
today"; a week later it is either a happened measure or a no-show, and
only the status (or a later note) would tell.

**Job 372 — [customer] / [customer] (B−A, quiet)** · no salesperson · Canceled

| activity | type | status | date | note |
|---|---|---|---|---|
| 1853 | Quote | **Estimate** | **2020-04-03** | waiting on material selections from [customer] |
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


---

# Appendices (raw evidence)

## Appendix A — psql session output, verbatim (diagnostic steps 1–6)

```
==== STEP 1: view definitions (verbatim)
--- v_quoted_jobs
                                                                                                                 pg_get_viewdef                                                                                                                 
------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  WITH sig AS (                                                                                                                                                                                                                                +
          SELECT activities.job_id,                                                                                                                                                                                                            +
             bool_or(activities.type_name = 'Quote'::text) AS has_quote_activity,                                                                                                                                                              +
             bool_or(activities.type_name = ANY (ARRAY['Measure'::text, 'Template'::text])) AS has_measure_or_template,                                                                                                                        +
             min(activities.activity_date) AS first_signal_date                                                                                                                                                                                +
            FROM activities                                                                                                                                                                                                                    +
           WHERE (activities.type_name = ANY (ARRAY['Quote'::text, 'Measure'::text, 'Template'::text])) AND (activities.status_name = ANY (ARRAY['Confirmed'::text, 'Complete'::text, 'Paid in Full and Finished'::text, 'In Progress'::text]))+
           GROUP BY activities.job_id                                                                                                                                                                                                          +
         )                                                                                                                                                                                                                                     +
  SELECT j.job_id,                                                                                                                                                                                                                             +
     j.job_name,                                                                                                                                                                                                                               +
     j.account_name AS customer,                                                                                                                                                                                                               +
     j.salesperson,                                                                                                                                                                                                                            +
     j.city_normalized AS city,                                                                                                                                                                                                                +
     s.has_quote_activity,                                                                                                                                                                                                                     +
     s.has_measure_or_template,                                                                                                                                                                                                                +
         CASE                                                                                                                                                                                                                                  +
             WHEN s.has_quote_activity THEN 'quote'::text                                                                                                                                                                                      +
             ELSE 'measure_or_template'::text                                                                                                                                                                                                  +
         END AS quoted_via,                                                                                                                                                                                                                    +
     s.first_signal_date                                                                                                                                                                                                                       +
    FROM jobs j                                                                                                                                                                                                                                +
      JOIN sig s USING (job_id);

--- v_job_pipeline_status
                                                                                           pg_get_viewdef                                                                                           
----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  WITH signals AS (                                                                                                                                                                                +
          SELECT activities.job_id,                                                                                                                                                                +
             min(activities.activity_date) AS first_signal_date,                                                                                                                                   +
             max(activities.activity_date) AS last_signal_date,                                                                                                                                    +
             bool_or(activities.type_name = 'Quote'::text) AS had_dated_quote,                                                                                                                     +
             bool_or(activities.type_name = 'Measure'::text) AS had_dated_measure,                                                                                                                 +
             bool_or(activities.type_name = 'Template'::text) AS had_dated_template                                                                                                                +
            FROM activities                                                                                                                                                                        +
           WHERE (activities.type_name = ANY (ARRAY['Quote'::text, 'Measure'::text, 'Template'::text])) AND activities.activity_date IS NOT NULL AND activities.activity_date <= '2026-07-30'::date+
           GROUP BY activities.job_id                                                                                                                                                              +
         ), last_signal AS (                                                                                                                                                                       +
          SELECT DISTINCT ON (activities.job_id) activities.job_id,                                                                                                                                +
             lower(activities.type_name) AS signal_source                                                                                                                                          +
            FROM activities                                                                                                                                                                        +
           WHERE (activities.type_name = ANY (ARRAY['Quote'::text, 'Measure'::text, 'Template'::text])) AND activities.activity_date IS NOT NULL AND activities.activity_date <= '2026-07-30'::date+
           ORDER BY activities.job_id, activities.activity_date DESC, (                                                                                                                            +
                 CASE activities.type_name                                                                                                                                                         +
                     WHEN 'Quote'::text THEN 1                                                                                                                                                     +
                     WHEN 'Measure'::text THEN 2                                                                                                                                                   +
                     ELSE 3                                                                                                                                                                        +
                 END)                                                                                                                                                                              +
         ), moves AS (                                                                                                                                                                             +
          SELECT activities.job_id,                                                                                                                                                                +
             min(activities.activity_date) AS first_move_date                                                                                                                                      +
            FROM activities                                                                                                                                                                        +
           WHERE (activities.type_name = ANY (ARRAY['Install'::text, 'Removal'::text])) AND activities.activity_date IS NOT NULL                                                                   +
           GROUP BY activities.job_id                                                                                                                                                              +
         )                                                                                                                                                                                         +
  SELECT j.job_id,                                                                                                                                                                                 +
     j.job_name,                                                                                                                                                                                   +
     j.account_name AS customer,                                                                                                                                                                   +
     j.salesperson,                                                                                                                                                                                +
     j.city_normalized AS city,                                                                                                                                                                    +
     s.job_id IS NOT NULL AS is_quoted,                                                                                                                                                            +
     s.first_signal_date,                                                                                                                                                                          +
     s.last_signal_date,                                                                                                                                                                           +
     ls.signal_source,                                                                                                                                                                             +
     COALESCE(s.had_dated_quote, false) AS had_dated_quote,                                                                                                                                        +
     COALESCE(s.had_dated_measure, false) AS had_dated_measure,                                                                                                                                    +
     COALESCE(s.had_dated_template, false) AS had_dated_template,                                                                                                                                  +
     m.job_id IS NOT NULL AS moved_forward,                                                                                                                                                        +
     m.first_move_date,                                                                                                                                                                            +
     COALESCE(m.first_move_date > '2026-07-30'::date, false) AS move_is_future,                                                                                                                    +
         CASE                                                                                                                                                                                      +
             WHEN s.job_id IS NOT NULL AND m.job_id IS NULL THEN '2026-07-30'::date - s.last_signal_date                                                                                           +
             ELSE NULL::integer                                                                                                                                                                    +
         END AS days_silent,                                                                                                                                                                       +
         CASE                                                                                                                                                                                      +
             WHEN s.job_id IS NULL THEN 'not_quoted'::text                                                                                                                                         +
             WHEN m.job_id IS NOT NULL THEN 'moved'::text                                                                                                                                          +
             WHEN ('2026-07-30'::date - s.last_signal_date) <= 30 THEN 'pending'::text                                                                                                             +
             ELSE 'quiet'::text                                                                                                                                                                    +
         END AS status                                                                                                                                                                             +
    FROM jobs j                                                                                                                                                                                    +
      LEFT JOIN signals s USING (job_id)                                                                                                                                                           +
      LEFT JOIN last_signal ls USING (job_id)                                                                                                                                                      +
      LEFT JOIN moves m USING (job_id);

--- v_quote_conversion_monthly
                                               pg_get_viewdef                                               
------------------------------------------------------------------------------------------------------------
  SELECT date_trunc('month'::text, first_signal_date::timestamp with time zone)::date AS quote_month,      +
     count(*) AS quoted_jobs,                                                                              +
     count(*) FILTER (WHERE moved_forward) AS moved_forward,                                               +
     round(100.0 * count(*) FILTER (WHERE moved_forward)::numeric / count(*)::numeric, 1) AS conversion_pct+
    FROM v_job_pipeline_status                                                                             +
   WHERE is_quoted AND (first_signal_date <= ('2026-07-30'::date - 30) OR moved_forward)                   +
   GROUP BY (date_trunc('month'::text, first_signal_date::timestamp with time zone)::date);

--- activity status values (there is no Canceled status on activities)
        status_name        | count 
---------------------------+-------
 Complete                  |  9224
 Estimate                  |  7170
 Confirmed                 |   225
 Paid in Full and Finished |    28
 In Progress               |    10
 RTF                       |     2

==== STEP 2: set sizes
 |A|  | |B|  | |C|  | |A∩B| | |A−B| | |B−A| | |A−C| | |C−A| 
------+------+------+-------+-------+-------+-------+-------
 4236 | 4415 | 4377 |  4231 |     5 |   184 |    38 |   179

==== STEP 3: A−B buckets (WO11 only)
                     bucket                     | jobs |     job_ids      
------------------------------------------------+------+------------------
 1 accepted status, no date on any Q/M/T signal |    2 | 4411, 4907
 2 signals dated only after as-of 2026-07-30    |    3 | 5814, 5849, 5859

--- A−B jobs, every Q/M/T activity
 job_id | activity_id | type_name | status_name | activity_date | accepted 
--------+-------------+-----------+-------------+---------------+----------
   4411 |       36238 | Template  | Estimate    |               | f
   4411 |       36242 | Quote     | Confirmed   |               | t
   4411 |       36243 | Measure   | Estimate    |               | f
   4907 |       40535 | Template  | Estimate    |               | f
   4907 |       40539 | Quote     | Confirmed   |               | t
   4907 |       40540 | Measure   | Estimate    |               | f
   5814 |       49303 | Template  | Confirmed   | 2026-08-03    | t
   5814 |       49307 | Quote     | Estimate    |               | f
   5814 |       49308 | Measure   | Estimate    |               | f
   5849 |       49760 | Template  | Confirmed   | 2026-08-03    | t
   5849 |       49764 | Quote     | Estimate    |               | f
   5849 |       49765 | Measure   | Estimate    |               | f
   5859 |       49848 | Template  | Confirmed   | 2026-08-03    | t
   5859 |       49852 | Quote     | Estimate    |               | f
   5859 |       49853 | Measure   | Estimate    |               | f

==== STEP 4: B−A buckets (pipeline only)
                    bucket                     | jobs 
-----------------------------------------------+------
 1 dated Q/M/T, every status outside WO11 list |  184

--- bucket 1 by the status of their dated signals
 dated_statuses | jobs 
----------------+------
 Estimate       |  184

--- bucket 1 by signal type: see the grouped table in §4 (Quote 142, Measure 22, Template 13, Measure+Template 3, Measure+Quote 2, Quote+Template 2)

--- bucket 2 check: dated Estimate accepted by WO11? (WO11 excludes ALL Estimate rows, so 0 by construction)
 dated_estimate_jobs_in_a 
--------------------------
                        0

--- 3 other: list
 job_id | activity_id | type_name | status_name | activity_date 
--------+-------------+-----------+-------------+---------------

==== STEP 5a: B−A bucket 1 in the pipeline: status split and conversion sensitivity
 status  | jobs | in_cohort | cohort_moved 
---------+------+-----------+--------------
 quiet   |  171 |       171 |            0
 moved   |    8 |         8 |            8
 pending |    5 |         0 |            0

       variant        | quoted | moved | pct  
----------------------+--------+-------+------
 with (current v4)    |   4377 |  3063 | 70.0
 without B−A bucket 1 |   4198 |  3055 | 72.8

--- yearly conversion with vs without
  yr  | quoted_with | pct_with | quoted_without | pct_without 
------+-------------+----------+----------------+-------------
 2019 |           3 |     33.3 |              3 |        33.3
 2020 |         845 |     68.2 |            842 |        68.4
 2021 |         735 |     73.7 |            731 |        74.1
 2022 |         597 |     79.1 |            585 |        80.3
 2023 |         477 |     85.7 |            464 |        87.9
 2024 |         632 |     63.4 |            550 |        72.5
 2025 |         721 |     61.3 |            667 |        66.0
 2026 |         367 |     59.9 |            356 |        61.5

--- the 184's dated Estimate signals: jobs with a later dated activity of any type / Canceled
 jobs | with_later_dated_activity | canceled 
------+---------------------------+----------
  184 |                        73 |      148

==== STEP 5b: A−B bucket 1 (undated accepted): canceled? anything dated after?
 job_id | process_name | job_status_name | creation_date | dated_activities_any_type | last_dated 
--------+--------------+-----------------+---------------+---------------------------+------------
   4411 | Canceled     | Active          | 2024-12-09    |                         1 | 2024-12-09
   4907 | Canceled     | Active          | 2025-06-25    |                         1 | 2025-06-25

==== STEP 6: hand-check five jobs (2 from A−B, 3 from B−A)
          why          | job_id |            job_name             | process_name | job_status_name |   salesperson   | pipeline_status | first_signal_date | moved_forward 
-----------------------+--------+---------------------------------+--------------+-----------------+-----------------+-----------------+-------------------+---------------
 A−B: undated accepted |   4411 | Customer #4411                   | Canceled     | Active          | Salesperson A    | not_quoted      |                   | f
 A−B: undated accepted |   4907 | Customer #4907                     | Canceled     | Active          | Salesperson A    | not_quoted      |                   | f
 B−A: moved            |    964 | Customer #964 | Done         | Active          | Salesperson E | moved           | 2022-09-02        | t
 B−A: pending          |   5655 | Customer #5655                  | Job          | Active          | Other           | pending         | 2026-07-30        | f
 B−A: quiet            |    372 | Customer #372       | Canceled     | Active          |                 | quiet           | 2020-04-03        | f

--- their full activity lists
 job_id | activity_id |  type_name   |        status_name        | activity_date |                                       note                                       
--------+-------------+--------------+---------------------------+---------------+----------------------------------------------------------------------------------
    372 |        1853 | Quote        | Estimate                  | 2020-04-03    | waiting on material selections from [customer]
    372 |        1848 | Template     | Estimate                  |               | 
    372 |        1849 | Fabrication  | Estimate                  |               | 
    372 |        1850 | Install      | Estimate                  |               | 
    372 |        1851 | Invoice      | Estimate                  |               | 
    372 |        1852 | Measure      | Estimate                  |               | 
    964 |        6418 | Fabrication  | Complete                  | 2020-11-18    | [note text], 
    964 |        6419 | Install      | Paid in Full and Finished | 2020-11-29    | Ready For Pick Up
    964 |       20758 | Measure      | Estimate                  | 2022-09-02    | 
    964 |       21419 | Install      | Complete                  | 2022-09-17    | 
    964 |       20755 | Template     | Estimate                  |               | 
    964 |       20756 | Install      | Estimate                  |               | 
    964 |       20757 | Invoice      | Estimate                  |               | 
    964 |       20759 | Meeting      | Estimate                  |               | 
   4411 |       36244 | Phone, Email | Complete                  | 2024-12-09    | 
   4411 |       36238 | Template     | Estimate                  |               | 
   4411 |       36239 | Fabrication  | Estimate                  |               | 
   4411 |       36240 | Install      | Estimate                  |               | 
   4411 |       36241 | Invoice      | Estimate                  |               | 
   4411 |       36242 | Quote        | Confirmed                 |               | 
   4411 |       36243 | Measure      | Estimate                  |               | 
   4907 |       40541 | Phone, Email | Complete                  | 2025-06-25    | 
   4907 |       40535 | Template     | Estimate                  |               | 
   4907 |       40536 | Fabrication  | Estimate                  |               | 
   4907 |       40537 | Install      | Estimate                  |               | 
   4907 |       40538 | Invoice      | Estimate                  |               | 
   4907 |       40539 | Quote        | Confirmed                 |               | 
   4907 |       40540 | Measure      | Estimate                  |               | 
   5655 |       49708 | Measure      | Estimate                  | 2026-07-30    | 
   5655 |       47314 | Fabrication  | Estimate                  |               | 
   5655 |       47315 | Install      | Estimate                  |               |
```

## Appendix B — v2 verification after `sql/019` (psql, 2026-09-16)

```
 quoted_v2 | via_quote | proxy_only
-----------+-----------+------------
      4423 |      2864 |       1559

 both_ | a_only | b_only      (v2 vs pipeline is_quoted)
-------+--------+--------
  4415 |      8 |      0

 job_id | type_name | status_name | activity_date      (the 8 v2-only jobs' qualifying rows)
--------+-----------+-------------+---------------
   4411 | Quote     | Confirmed   |
   4907 | Quote     | Confirmed   |
   5692 | Measure   | Estimate    | 2026-08-15
   5725 | Template  | Estimate    | 2026-08-08
   5807 | Template  | Estimate    | 2026-08-04
   5814 | Template  | Confirmed   | 2026-08-03
   5849 | Template  | Confirmed   | 2026-08-03
   5859 | Template  | Confirmed   | 2026-08-03

 ro_ok = t     (rag_reader can read the view)

 first_signal year | quoted jobs (v2)
 2019 3 · 2020 845 · 2021 735 · 2022 597 · 2023 477 · 2024 632 · 2025 721 · 2026 411 · (undated) 2
```

SQL lane after the change (commit `4ae7902` on the server):

```
How many quotes have we issued in total?  -> SELECT COUNT(*) AS quotes_issued FROM v_quoted_jobs LIMIT 200 -> 4423
How many jobs did we quote in 2024?       -> SELECT COUNT(*) AS quoted_jobs FROM v_quoted_jobs WHERE EXTRACT(YEAR FROM first_signal_date) = 2024 LIMIT 200 -> 632
```

## Appendix C — the 184 jobs ruled quoted (dated Estimate as the only quote-stage signal), by first signal date

| job | job name | salesperson | process | dated signal types | first signal | pipeline status | moved | first dated note (≤60 chars) |
|---|---|---|---|---|---|---|---|---|
| 372 | Customer #372 | (blank) | Canceled | Quote | 2020-04-03 | quiet | no | waiting on material selections from [customer] |
| 459 | Customer #459 | (blank) | Canceled | Measure+Quote | 2020-04-30 | quiet | no |  |
| 717 | Customer #717 | Salesperson E | Canceled | Measure | 2020-07-31 | quiet | no |  |
| 1413 | Customer #1413 | (blank) | Canceled | Measure | 2021-04-11 | quiet | no | Call Crew B to go with you.  / Measure cabinets and counterto |
| 1348 | Customer #1348 | Salesperson J | Done | Measure | 2021-04-18 | quiet | no | Check if its ready |
| 1581 | Customer #1581 | (blank) | Canceled | Measure | 2021-05-28 | quiet | no | [note text] |
| 2099 | Customer #2099 | Salesperson E | Canceled | Quote | 2021-12-13 | quiet | no |  |
| 2233 | Customer #2233 | Salesperson E | Canceled | Quote | 2022-02-04 | quiet | no | wait for contractor to send the quote |
| 2261 | Customer #2261 | Salesperson E | Canceled | Quote | 2022-02-11 | quiet | no |  |
| 2330 | Customer #2330 | Salesperson C | Canceled | Quote | 2022-03-17 | quiet | no | Dallas White! ask about Gialo Ornamental |
| 2367 | Customer #2367 | Salesperson I | Canceled | Quote | 2022-03-23 | quiet | no |  |
| 2316 | Customer #2316 | Salesperson F | Canceled | Measure | 2022-03-27 | quiet | no | [note text] pai |
| 2405 | Customer #2405 | Salesperson I | Canceled | Measure | 2022-04-15 | quiet | no | [note text]  |
| 2528 | Customer #2528 | Salesperson I | Canceled | Measure | 2022-05-26 | quiet | no | [note text] |
| 1438 | Customer #1438 | Salesperson J | Done | Template | 2022-07-02 | moved | yes |  |
| 2652 | Customer #2652 | Salesperson I | Canceled | Measure+Template | 2022-07-29 | quiet | no | [note text] becaus |
| 2685 | Customer #2685 | Salesperson G | Canceled | Template | 2022-08-21 | quiet | no |  |
| 964 | Customer #964 | Salesperson E | Done | Measure | 2022-09-02 | moved | yes |  |
| 2778 | Customer #2778 | (blank) | Canceled | Template | 2022-09-16 | quiet | no |  |
| 3006 | Customer #3006          | (blank) | Canceled | Quote | 2023-01-17 | quiet | no |  |
| 3020 | Customer #3020 | Salesperson G | Canceled | Quote | 2023-01-23 | quiet | no |  |
| 3004 | Customer #3004 | Salesperson J | Canceled | Quote | 2023-01-29 | quiet | no |  |
| 3037 | Customer #3037 | (blank) | Canceled | Measure+Template | 2023-01-31 | quiet | no |  |
| 3178 | Customer #3178 | Salesperson G | Canceled | Template | 2023-04-16 | quiet | no |  |
| 3236 | Customer #3236 | Salesperson I | Canceled | Quote | 2023-08-08 | quiet | no |  |
| 3380 | Customer #3380 | Salesperson I | Canceled | Measure+Template | 2023-08-20 | moved | yes |  |
| 3392 | Customer #3392 | Salesperson G | Canceled | Template | 2023-08-20 | quiet | no |  |
| 3410 | Customer #3410 | (blank) | Canceled | Measure | 2023-08-20 | quiet | no |  |
| 3464 | Customer #3464 | Salesperson I | Canceled | Quote | 2023-08-23 | quiet | no |  |
| 3381 | Customer #3381 | (blank) | Canceled | Measure | 2023-09-23 | quiet | no |  |
| 3632 | Customer #3632 | Salesperson G | Canceled | Measure | 2023-12-06 | quiet | no | Client decided to go in another direction |
| 3686 | Customer #3686 | Salesperson A | Canceled | Quote | 2023-12-15 | quiet | no |  |
| 3703 | Customer #3703 | Salesperson G | Canceled | Quote | 2024-01-06 | quiet | no |  |
| 3704 | Customer #3704 | Salesperson G | Canceled | Measure+Quote | 2024-01-08 | quiet | no | follow up |
| 3708 | Customer #3708 | Salesperson G | Canceled | Quote | 2024-01-10 | quiet | no |  |
| 3712 | Customer #3712 | (blank) | Canceled | Measure | 2024-01-11 | quiet | no | [note text] c |
| 3722 | Customer #3722 | Salesperson G | Canceled | Quote | 2024-01-17 | quiet | no |  |
| 3728 | Customer #3728 | Salesperson G | Canceled | Quote | 2024-01-22 | quiet | no |  |
| 3738 | Customer #3738 | Salesperson A | Canceled | Quote | 2024-01-25 | quiet | no |  |
| 3742 | Customer #3742 | Salesperson G | Canceled | Quote | 2024-01-31 | quiet | no |  |
| 3748 | Customer #3748 | Salesperson G | Canceled | Quote | 2024-01-31 | quiet | no |  |
| 3755 | Customer #3755 | Salesperson G | Canceled | Quote | 2024-02-06 | quiet | no |  |
| 3773 | Customer #3773 | Salesperson G | Canceled | Quote | 2024-02-14 | quiet | no |  |
| 3775 | Customer #3775 | Salesperson G | Canceled | Quote | 2024-02-15 | quiet | no |  |
| 3756 | Customer #3756 | Salesperson G | Canceled | Quote | 2024-02-16 | quiet | no |  |
| 3781 | Customer #3781) | Salesperson G | Canceled | Quote | 2024-02-17 | quiet | no |  |
| 3782 | Customer #3782 | Salesperson G | Canceled | Quote | 2024-02-19 | quiet | no |  |
| 3783 | Customer #3783) | Salesperson G | Canceled | Quote | 2024-02-19 | quiet | no |  |
| 3786 | Customer #3786 | Salesperson G | Canceled | Quote | 2024-02-20 | quiet | no |  |
| 3793 | Customer #3793 | Salesperson A | Canceled | Quote | 2024-02-21 | quiet | no |  |
| 3805 | Ross | Salesperson G | Canceled | Quote | 2024-02-28 | quiet | no |  |
| 3807 | Customer #3807 | Salesperson G | Canceled | Quote | 2024-02-29 | quiet | no |  |
| 3809 | Table | Salesperson G | Canceled | Quote | 2024-02-29 | quiet | no |  |
| 3819 | Customer #3819 | Salesperson G | Canceled | Quote | 2024-03-05 | quiet | no |  |
| 3822 | Customer #3822 | Salesperson G | Canceled | Quote | 2024-03-06 | quiet | no |  |
| 3828 | Customer #3828 | Salesperson G | Canceled | Quote | 2024-03-07 | quiet | no |  |
| 3830 | Customer #3830 | Salesperson G | Canceled | Quote | 2024-03-08 | quiet | no |  |
| 3815 | Customer #3815 | Salesperson G | Canceled | Measure | 2024-03-10 | quiet | no |  |
| 3837 | Customer #3837 | Salesperson G | Canceled | Quote | 2024-03-14 | quiet | no |  |
| 3856 | Customer #3856 | Salesperson G | Canceled | Quote | 2024-03-15 | quiet | no |  |
| 3765 | Customer #3765 | Salesperson J | Canceled | Quote | 2024-03-16 | quiet | no | Pure White |
| 3843 | Customer #3843 | Salesperson G | Canceled | Quote | 2024-03-18 | quiet | no |  |
| 3810 | Customer #3810) | Salesperson J | Canceled | Quote | 2024-03-20 | quiet | no | Quote for EMG Stock |
| 3851 | Customer #3851 | Salesperson G | Canceled | Quote | 2024-03-22 | quiet | no |  |
| 3860 | Customer #3860 | Salesperson I | Canceled | Quote | 2024-03-24 | quiet | no |  |
| 3852 | Customer #3852 | Salesperson G | Canceled | Quote | 2024-03-25 | quiet | no |  |
| 3880 | Customer #3880 | Salesperson G | Canceled | Quote | 2024-04-09 | quiet | no |  |
| 3882 | Customer #3882 | Salesperson G | Canceled | Quote | 2024-04-10 | quiet | no |  |
| 3885 | Customer #3885 | Salesperson G | Canceled | Quote | 2024-04-12 | quiet | no |  |
| 3893 | Customer #3893 | Salesperson G | Canceled | Quote | 2024-04-15 | quiet | no |  |
| 3899 | Customer #3899 | Salesperson G | Canceled | Quote | 2024-04-16 | quiet | no |  |
| 3900 | Customer #3900 | Salesperson G | Canceled | Quote | 2024-04-16 | quiet | no |  |
| 3903 | 561-577-7905 | (blank) | Canceled | Quote | 2024-04-19 | quiet | no |  |
| 3914 | Customer #3914 | Salesperson G | Canceled | Quote | 2024-04-27 | quiet | no |  |
| 3919 | Customer #3919 | Salesperson A | Hold | Quote | 2024-04-29 | quiet | no |  |
| 3920 | Customer #3920 | Salesperson G | Canceled | Quote | 2024-04-29 | quiet | no |  |
| 3923 | Customer #3923 | Salesperson A | Canceled | Quote | 2024-04-29 | quiet | no |  |
| 3926 | Customer #3926 | Salesperson G | Canceled | Quote | 2024-04-30 | quiet | no |  |
| 3929 | Customer #3929 | Salesperson G | Canceled | Quote+Template | 2024-05-03 | quiet | no |  |
| 3933 | Customer #3933 | Salesperson A | Canceled | Quote | 2024-05-04 | quiet | no |  |
| 3934 | Customer #3934 | Salesperson A | Canceled | Quote | 2024-05-06 | quiet | no |  |
| 3244 | Customer #3244 | Salesperson A | Hold | Quote | 2024-05-07 | quiet | no |  |
| 3952 | Customer #3952 | Salesperson G | Canceled | Quote | 2024-05-13 | quiet | no |  |
| 3948 | Customer #2205 | Salesperson G | Canceled | Quote | 2024-05-15 | quiet | no |  |
| 3937 | Customer #3937 | Salesperson G | Canceled | Quote | 2024-05-20 | quiet | no |  |
| 3974 | Customer #3974 | Salesperson I | Canceled | Quote | 2024-05-21 | quiet | no | quote carrara or lagoon |
| 3982 | Customer #3982 | Salesperson C | Canceled | Quote | 2024-05-23 | quiet | no |  |
| 3997 | Customer #3997 | Salesperson G | Canceled | Quote | 2024-05-30 | quiet | no |  |
| 4012 | Customer #4012 | Salesperson G | Canceled | Quote | 2024-06-06 | quiet | no |  |
| 4013 | Customer #4013 | Salesperson G | Canceled | Quote | 2024-06-06 | quiet | no |  |
| 3980 | Customer #3980 | Salesperson G | Canceled | Quote | 2024-06-10 | quiet | no |  |
| 3993 | Customer #3993 | Salesperson I | Canceled | Quote | 2024-06-11 | quiet | no |  |
| 4029 | Customer #4029 | Salesperson J | Canceled | Quote | 2024-06-12 | quiet | no |  |
| 4032 | Customer #4032 | Salesperson G | Canceled | Quote | 2024-06-13 | quiet | no |  |
| 4021 | Customer #4021 | Salesperson J | Canceled | Quote | 2024-06-22 | quiet | no |  |
| 4016 | Customer #4016 | Salesperson G | Canceled | Quote | 2024-06-26 | quiet | no |  |
| 4062 | Customer #4062 | Salesperson G | Canceled | Quote | 2024-06-29 | quiet | no |  |
| 4065 | Customer #4065 | Salesperson A | Canceled | Quote | 2024-06-30 | quiet | no |  |
| 4071 | Customer #4071 | Salesperson G | Canceled | Quote | 2024-07-01 | quiet | no |  |
| 4084 | Customer #4084 | Salesperson G | Canceled | Quote | 2024-07-09 | quiet | no |  |
| 4082 | Customer #4082 | Salesperson G | Canceled | Quote | 2024-07-15 | quiet | no |  |
| 4101 | Crew U | Salesperson G | Done | Quote | 2024-07-21 | moved | yes |  |
| 4124 | Customer #4124 | Salesperson G | Canceled | Quote | 2024-07-24 | quiet | no |  |
| 4132 | Customer #4132 | Salesperson A | Canceled | Quote | 2024-07-30 | quiet | no |  |
| 4136 | Customer #4136 | Salesperson A | Canceled | Quote | 2024-08-02 | quiet | no |  |
| 4135 | Customer #4135) | Salesperson A | Canceled | Quote | 2024-08-03 | quiet | no |  |
| 4144 | Customer #4144 | Salesperson A | Canceled | Quote | 2024-08-04 | quiet | no |  |
| 4152 | Customer #4152. | Salesperson A | Canceled | Quote | 2024-08-13 | quiet | no |  |
| 4159 | Customer #4159 | Salesperson G | Canceled | Quote | 2024-08-14 | quiet | no |  |
| 4190 | Customer #4190 | Salesperson A | Canceled | Quote | 2024-08-29 | quiet | no |  |
| 4143 | Customer #4143 | Salesperson J | Canceled | Quote | 2024-09-08 | quiet | no |  |
| 4338 | Customer #4338 | Salesperson G | Canceled | Template | 2024-11-10 | moved | yes |  |
| 4368 | Customer #4368 | Salesperson G | Canceled | Template | 2024-11-17 | quiet | no |  |
| 4384 | Customer #4384 | Salesperson A | Canceled | Measure | 2024-11-24 | quiet | no |  |
| 4564 | Customer #4564 | Salesperson A | Canceled | Measure | 2025-02-23 | quiet | no | confirm please |
| 4705 | Customer #4705) | Salesperson A | Canceled | Measure | 2025-04-06 | quiet | no |  |
| 4694 | Customer #4694 | Salesperson G | Done | Template | 2025-06-15 | quiet | no |  |
| 4973 | Customer #4973 | Salesperson J | Leads with Layouts | Quote | 2025-07-22 | quiet | no |  |
| 4974 | Customer #4974 | Salesperson J | Leads with Layouts | Quote | 2025-07-27 | quiet | no |  |
| 4975 | Customer #4975 | Salesperson J | Leads with Layouts | Quote | 2025-07-27 | quiet | no |  |
| 4977 | Customer #4977 | Salesperson J | Leads with Layouts | Quote | 2025-07-27 | quiet | no |  |
| 4995 | Customer #4995 | Salesperson G | Canceled | Quote | 2025-08-04 | quiet | no |  |
| 5003 | Customer #5003 | Salesperson G | Canceled | Quote | 2025-08-13 | quiet | no |  |
| 5019 | Customer #5019 | Salesperson G | Canceled | Quote | 2025-08-15 | quiet | no |  |
| 5030 | Customer #5030 | Salesperson A | Canceled | Quote | 2025-08-20 | quiet | no |  |
| 5081 | Customer #5081 | Salesperson G | Leads with Layouts | Quote | 2025-09-10 | quiet | no |  |
| 5073 | Customer #5073 | Salesperson G | Canceled | Quote | 2025-09-12 | quiet | no |  |
| 5072 | Customer #5072 | Salesperson A | Canceled | Quote | 2025-09-22 | quiet | no |  |
| 5113 | Customer #5113 | Salesperson G | Canceled | Quote | 2025-09-25 | quiet | no |  |
| 4916 | Customer #4916 | Salesperson J | Leads with Layouts | Quote | 2025-09-30 | moved | yes |  |
| 5131 | Customer #5131 | Salesperson G | Canceled | Quote | 2025-10-02 | quiet | no |  |
| 5132 | sample | Salesperson G | Canceled | Quote | 2025-10-02 | quiet | no |  |
| 5133 | Customer #5133 | Salesperson G | Canceled | Quote | 2025-10-02 | quiet | no |  |
| 5135 | Customer #5135 | Salesperson G | Canceled | Quote | 2025-10-03 | quiet | no |  |
| 5130 | Customer #5130 | Salesperson G | Canceled | Quote | 2025-10-06 | quiet | no |  |
| 5138 | Customer #5138 | Salesperson G | Canceled | Quote | 2025-10-07 | quiet | no |  |
| 5141 | Customer #5141 | Salesperson G | Canceled | Quote | 2025-10-07 | quiet | no |  |
| 5153 | Customer #5153 | Salesperson G | Canceled | Quote | 2025-10-11 | quiet | no |  |
| 5156 | Customer #5156 | Salesperson G | Canceled | Quote | 2025-10-11 | quiet | no |  |
| 4953 | Customer #4953 | Salesperson A | Canceled | Template | 2025-10-12 | quiet | no |  |
| 5021 | Customer #5021 | Salesperson A | Canceled | Measure | 2025-10-12 | quiet | no |  |
| 5104 | Customer #5104 | Salesperson G | Canceled | Template | 2025-10-12 | quiet | no |  |
| 5105 | Customer #5105 | Salesperson G | Leads with Layouts | Quote | 2025-10-12 | quiet | no |  |
| 5159 | Customer #5159 | Salesperson G | Canceled | Quote | 2025-10-13 | quiet | no |  |
| 5163 | Customer #5163 | Salesperson G | Leads with Layouts | Quote | 2025-10-15 | quiet | no |  |
| 5169 | Customer #5169 | Salesperson F | Canceled | Quote | 2025-10-16 | quiet | no |  |
| 5143 | Customer #5143 | Salesperson G | Canceled | Quote | 2025-10-17 | quiet | no |  |
| 5170 | Customer #5170 | Salesperson F | Canceled | Quote | 2025-10-17 | quiet | no |  |
| 5182 | Customer #5182 | Salesperson G | Canceled | Quote | 2025-10-22 | quiet | no |  |
| 5199 | Customer #5199 | Salesperson G | Leads with Layouts | Quote | 2025-10-31 | quiet | no |  |
| 5202 | Customer #5202 | Salesperson G | Canceled | Quote | 2025-11-04 | quiet | no |  |
| 5209 | [customer] | Salesperson G | Canceled | Quote | 2025-11-04 | quiet | no |  |
| 5219 | Customer #5219 | Salesperson G | Hold | Quote | 2025-11-10 | quiet | no |  |
| 5226 | Customer #5226 | Salesperson G | Leads with Layouts | Quote | 2025-11-11 | quiet | no |  |
| 5457 | Customer #5457 | Salesperson G | Leads with Layouts | Quote | 2025-11-11 | quiet | no |  |
| 5458 | Customer #5458 | Salesperson G | Leads with Layouts | Quote | 2025-11-11 | quiet | no |  |
| 5231 | Customer #5231 | Salesperson G | Hold | Quote | 2025-11-13 | quiet | no |  |
| 5235 | Customer #5235 | Salesperson G | Leads with Layouts | Quote | 2025-11-15 | moved | yes |  |
| 5236 | Customer #5236 | Salesperson G | Leads with Layouts | Quote | 2025-11-15 | quiet | no |  |
| 5217 | Customer #5217 | Salesperson G | Leads with Layouts | Quote | 2025-11-18 | quiet | no |  |
| 5246 | Customer #5246 | Salesperson G | Canceled | Quote | 2025-11-21 | quiet | no |  |
| 5184 | Customer #5184 | Salesperson G | Canceled | Quote | 2025-11-26 | quiet | no |  |
| 5256 | Customer #5256 | Salesperson A | Canceled | Quote | 2025-12-01 | quiet | no |  |
| 5265 | Customer #5265 | Salesperson G | Leads with Layouts | Quote | 2025-12-04 | quiet | no |  |
| 5164 | Customer #5164 | Salesperson J | Leads with Layouts | Quote | 2025-12-06 | quiet | no |  |
| 5165 | Customer #5165 | Salesperson J | Leads with Layouts | Quote | 2025-12-06 | quiet | no |  |
| 5279 | Customer #5279 | Salesperson A | Canceled | Quote | 2025-12-15 | quiet | no |  |
| 5289 | sample 12/17/25 | Salesperson G | Canceled | Quote | 2025-12-17 | quiet | no |  |
| 5290 | Customer #5290 | Salesperson G | Canceled | Quote | 2026-01-09 | quiet | no |  |
| 5331 | Customer #5331 | Salesperson G | Leads with Layouts | Quote+Template | 2026-01-14 | quiet | no |  |
| 5352 | Customer #5352 | Salesperson G | Canceled | Quote | 2026-01-22 | quiet | no |  |
| 5357 | Customer #5357 | Salesperson G | Canceled | Quote | 2026-01-23 | quiet | no |  |
| 5361 | Customer #5361 | Salesperson J | Canceled | Quote | 2026-01-23 | quiet | no |  |
| 5364 | Customer #5352 | Salesperson G | Leads with Layouts | Quote | 2026-01-26 | quiet | no |  |
| 5367 | Customer #5367 | Salesperson G | Canceled | Quote | 2026-01-26 | quiet | no |  |
| 5471 | Customer #1164 | Salesperson G | Canceled | Template | 2026-04-11 | quiet | no |  |
| 5502 | Customer #5502 | Salesperson G | Canceled | Measure | 2026-04-19 | quiet | no |  |
| 5717 | Customer #5717 | Salesperson A | Leads with Layouts | Measure | 2026-06-28 | quiet | no |  |
| 5779 | Customer #5779 | Salesperson A | Leads with Layouts | Quote | 2026-07-05 | pending | no |  |
| 5635 | Customer #5635 | Salesperson G | Leads with Layouts | Template | 2026-07-19 | moved | yes |  |
| 5813 | Customer #5813 | (blank) | Leads with Layouts | Measure | 2026-07-19 | pending | no |  |
| 5812 | Customer #5812 | Salesperson G | Leads with Layouts | Measure | 2026-07-22 | pending | no |  |
| 5848 | Customer #5848 | Salesperson J | Leads with Layouts | Template | 2026-07-29 | pending | no |  |
| 5655 | Customer #5655 | Other | Job | Measure | 2026-07-30 | pending | no |  |

## Appendix D — the 8 jobs `v_quoted_jobs` v2 counts that the pipeline view does not (qualifying rows)

| job | job name | salesperson | process | type | status | date |
|---|---|---|---|---|---|---|
| 4411 | Customer #4411 | Salesperson A | Canceled | Quote | Confirmed | (undated) |
| 4907 | Customer #4907 | Salesperson A | Canceled | Quote | Confirmed | (undated) |
| 5692 | Customer #5692 | (blank) | Job | Measure | Estimate | 2026-08-15 |
| 5725 | Customer #5725 | Salesperson G | Leads with Layouts | Template | Estimate | 2026-08-08 |
| 5807 | Customer #5807 | Salesperson G | Leads with Layouts | Template | Estimate | 2026-08-04 |
| 5814 | Customer #5814 | Salesperson G | Leads with Layouts | Template | Confirmed | 2026-08-03 |
| 5849 | Customer #5849 | Salesperson G | Leads with Layouts | Template | Confirmed | 2026-08-03 |
| 5859 | Customer #5859 | Salesperson G | Leads with Layouts | Template | Confirmed | 2026-08-03 |

-- Additive migration: ONE canonical pipeline definition (WO 2026-08-14).
--
-- "Was this job quoted?" and "did the customer move forward?" previously had
-- two individually-defensible answers (QCONV v3 vs the Q26 stall spec).
-- v_job_pipeline_status is the single per-job source of truth; QCONV v4 and
-- the Q26 buckets are both derived from it below.
--
-- Locked definition (Alex, 2026-08-12):
--   quoted  = the job has a HAPPENED Quote, Measure, or Template activity
--             (dated AND on/before as-of). Past only: a quote appointment
--             scheduled for next week has not been given yet, so it cannot
--             start a silence clock.
--   moved   = the job has an Install or Removal with ANY non-NULL date
--             (happened OR is_scheduled_future) — a booked future install
--             counts as movement. ACTIVITIES ONLY: no invoice numbers, no
--             paid status, no chatbot payment notes. Money is not part of
--             this definition anywhere.
--   The asymmetry (quoted = past only; moved = past or future) is
--   deliberate.
--
-- Two distinct date roles — deliberately separate columns, do not collapse:
--   first_signal_date (MIN) anchors the COHORT: stable forever, a job
--     quoted in 2020 stays in the 2020 cohort even if re-measured in 2026.
--   last_signal_date (MAX) drives the SILENCE CLOCK: most recent sign of
--     life, what pending/quiet measure from.
--
-- Same literal-constant convention as sql/009 and sql/011:
--   as-of       = DATE '2026-07-30'  (snapshot; TODO CURRENT_DATE after the
--                                     freshness pipeline WO)
--   SETTLE_DAYS = 30                 (a quoted job needs 30 days of runway
--                                     before it is judged; the old 7-day
--                                     QCONV freshness rule is RETIRED)

-- DROP + CREATE (not CREATE OR REPLACE) so the column list stays in its
-- natural order across re-runs; the CASCADE also takes the dependent
-- conversion view, which is recreated immediately below. Still idempotent.
DROP VIEW IF EXISTS v_job_pipeline_status CASCADE;

CREATE VIEW v_job_pipeline_status AS
WITH signals AS (
    -- happened Quote/Measure/Template per job
    SELECT job_id,
           MIN(activity_date) AS first_signal_date,
           MAX(activity_date) AS last_signal_date,
           BOOL_OR(type_name = 'Quote') AS had_dated_quote
    FROM activities
    WHERE type_name IN ('Quote', 'Measure', 'Template')
      AND activity_date IS NOT NULL
      AND activity_date <= DATE '2026-07-30'          -- as-of
    GROUP BY job_id
),
last_signal AS (
    -- the activity type behind last_signal_date; same-day ties prefer
    -- Quote over Measure over Template (the strongest signal wins)
    SELECT DISTINCT ON (job_id)
           job_id,
           lower(type_name) AS signal_source
    FROM activities
    WHERE type_name IN ('Quote', 'Measure', 'Template')
      AND activity_date IS NOT NULL
      AND activity_date <= DATE '2026-07-30'          -- as-of
    ORDER BY job_id, activity_date DESC,
             CASE type_name WHEN 'Quote' THEN 1 WHEN 'Measure' THEN 2
                            ELSE 3 END
),
moves AS (
    -- Install/Removal with any date, past or future
    SELECT job_id,
           MIN(activity_date) AS first_move_date
    FROM activities
    WHERE type_name IN ('Install', 'Removal')
      AND activity_date IS NOT NULL
    GROUP BY job_id
)
SELECT j.job_id,
       j.job_name,
       (s.job_id IS NOT NULL)                          AS is_quoted,
       s.first_signal_date,
       s.last_signal_date,
       ls.signal_source,
       COALESCE(s.had_dated_quote, false)              AS had_dated_quote,
       (m.job_id IS NOT NULL)                          AS moved_forward,
       m.first_move_date,
       -- true when the EARLIEST movement is still ahead: everything is
       -- booked, nothing has physically happened yet
       COALESCE(m.first_move_date > DATE '2026-07-30', false)
                                                       AS move_is_future,
       -- silence clock: only ticks for quoted jobs that have not moved
       CASE WHEN s.job_id IS NOT NULL AND m.job_id IS NULL
            THEN DATE '2026-07-30' - s.last_signal_date
       END                                             AS days_silent,
       CASE
           WHEN s.job_id IS NULL THEN 'not_quoted'
           WHEN m.job_id IS NOT NULL THEN 'moved'
           WHEN DATE '2026-07-30' - s.last_signal_date <= 30   -- SETTLE_DAYS
                THEN 'pending'
           ELSE 'quiet'
       END                                             AS status
FROM jobs j
LEFT JOIN signals s USING (job_id)
LEFT JOIN last_signal ls USING (job_id)
LEFT JOIN moves m USING (job_id);

-- QCONV v4: same name and shape as v3 (sql/009), now derived from the
-- canonical view. Changes vs v3: quoted broadened to Quote/Measure/Template
-- happened (the 279 dated-Measure-no-Quote jobs are now quoted by
-- definition — resolves open decision #3); moved narrowed to activities
-- only (payment notes REMOVED); settle 7 -> 30 days; cohort month = month
-- of first_signal_date (stable).

CREATE VIEW v_quote_conversion_monthly AS
SELECT date_trunc('month', first_signal_date)::date          AS quote_month,
       COUNT(*)                                              AS quoted_jobs,
       COUNT(*) FILTER (WHERE moved_forward)                 AS moved_forward,
       ROUND(100.0 * COUNT(*) FILTER (WHERE moved_forward)
             / COUNT(*), 1)                                  AS conversion_pct
FROM v_job_pipeline_status
WHERE is_quoted
  AND (first_signal_date <= DATE '2026-07-30' - 30   -- as-of, SETTLE_DAYS
       OR moved_forward)                             -- early winners count
GROUP BY date_trunc('month', first_signal_date)::date;

GRANT SELECT ON v_job_pipeline_status, v_quote_conversion_monthly
TO rag_reader;

-- 017: v_job_pipeline_status carries customer, salesperson and city (WO11
-- Change 4). Q26 selected `salesperson` from this view and failed with
-- UndefinedColumn: the schema prompt said to JOIN v_jobs for those columns
-- (commit f043df9), the model ignored the caveat, and the validator's column
-- whitelist is global across views so the error only surfaced in Postgres.
-- v_wasted_templates already exposes salesperson and city on the row;
-- consistency across views beats a prompt caveat.
--
-- Definition otherwise identical to sql/013 (v4: dated signals only,
-- as-of 2026-07-30, SETTLE_DAYS 30). v_quote_conversion_monthly is
-- recreated unchanged because the CASCADE drops it.

DROP VIEW IF EXISTS v_job_pipeline_status CASCADE;

CREATE VIEW v_job_pipeline_status AS
WITH signals AS (
    SELECT job_id,
           MIN(activity_date) AS first_signal_date,
           MAX(activity_date) AS last_signal_date,
           BOOL_OR(type_name = 'Quote')    AS had_dated_quote,
           BOOL_OR(type_name = 'Measure')  AS had_dated_measure,
           BOOL_OR(type_name = 'Template') AS had_dated_template
    FROM activities
    WHERE type_name IN ('Quote', 'Measure', 'Template')
      AND activity_date IS NOT NULL
      AND activity_date <= DATE '2026-07-30'          -- as-of
    GROUP BY job_id
),
last_signal AS (
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
    SELECT job_id,
           MIN(activity_date) AS first_move_date
    FROM activities
    WHERE type_name IN ('Install', 'Removal')
      AND activity_date IS NOT NULL
    GROUP BY job_id
)
SELECT j.job_id,
       j.job_name,
       j.account_name                                  AS customer,
       j.salesperson,
       j.city_normalized                                AS city,
       (s.job_id IS NOT NULL)                          AS is_quoted,
       s.first_signal_date,
       s.last_signal_date,
       ls.signal_source,
       COALESCE(s.had_dated_quote,    false)           AS had_dated_quote,
       COALESCE(s.had_dated_measure,  false)           AS had_dated_measure,
       COALESCE(s.had_dated_template, false)           AS had_dated_template,
       (m.job_id IS NOT NULL)                          AS moved_forward,
       m.first_move_date,
       COALESCE(m.first_move_date > DATE '2026-07-30', false)
                                                       AS move_is_future,
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

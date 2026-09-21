-- 016: v_quoted_jobs — the job-level "quoted" definition (WO11, locked by
-- Alex 2026-09-14). One row per quoted job.
--
-- A job counts as quoted when it has a Quote, Measure or Template activity
-- whose status is Confirmed, Complete, Paid in Full and Finished or
-- In Progress — dated or not. Estimate rows never count. A Measure or
-- Template qualifies on its own because a job cannot be measured or
-- templated without a quote having been issued, even when the Quote row was
-- never logged.
--
-- Measured 2026-09-14: 2,680 jobs via a Quote row, 3,334 via Measure/
-- Template, union 4,236, of which 1,556 (37%) are quoted only through the
-- measure/template proxy.
--
-- NOTE (for Alex, unreconciled): v_job_pipeline_status.is_quoted uses a
-- different rule — any DATED Quote/Measure/Template on or before the as-of
-- date, regardless of status — and reports 4,415 quoted jobs (4,377 in the
-- settled conversion cohort). 4,231 jobs satisfy both. The 184 jobs only in
-- the pipeline rule have a dated Estimate as their only signal; the 5 only
-- here are 2 undated Confirmed quotes and 3 templates dated after the as-of.

CREATE OR REPLACE VIEW v_quoted_jobs AS
WITH sig AS (
    SELECT job_id,
           BOOL_OR(type_name = 'Quote')                  AS has_quote_activity,
           BOOL_OR(type_name IN ('Measure', 'Template')) AS has_measure_or_template,
           MIN(activity_date)                            AS first_signal_date
    FROM activities
    WHERE type_name IN ('Quote', 'Measure', 'Template')
      AND status_name IN ('Confirmed', 'Complete',
                          'Paid in Full and Finished', 'In Progress')
    GROUP BY job_id
)
SELECT j.job_id,
       j.job_name,
       j.account_name                                    AS customer,
       j.salesperson,
       j.city_normalized                                 AS city,
       s.has_quote_activity,
       s.has_measure_or_template,
       CASE WHEN s.has_quote_activity THEN 'quote'
            ELSE 'measure_or_template' END               AS quoted_via,
       s.first_signal_date
FROM jobs j
JOIN sig s USING (job_id);

GRANT SELECT ON v_quoted_jobs TO rag_reader;

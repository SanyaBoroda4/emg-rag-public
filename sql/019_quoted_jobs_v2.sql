-- 019: v_quoted_jobs v2 — dated Estimate signals count as quoted.
-- Alex's ruling on the WO15 diagnostic (2026-09-16): "count as quoted."
--
-- A job is quoted when it has a Quote, Measure or Template activity that is
--   (a) in an accepted status — Confirmed, Complete, Paid in Full and
--       Finished, In Progress — dated or not (the WO11 rule, unchanged), OR
--   (b) DATED, whatever its status (new: a dated Estimate-status quote,
--       measure or template is a quote-stage event that happened).
-- Only an UNDATED Estimate/RTF row still counts for nothing (a pre-created
-- placeholder).
--
-- Effect, measured on the frozen snapshot: 4,236 -> 4,420 jobs. The 184
-- added are exactly the WO15 B−A bucket (dated Estimate as the only signal;
-- 148 Canceled jobs, 8 later installed). The 5 jobs the pipeline view does
-- not count remain here by Alex's earlier "date or no date" wording: 2
-- undated Confirmed quotes (4411, 4907) and 3 templates dated after the
-- pipeline's as-of (5814, 5849, 5859). v_job_pipeline_status.is_quoted
-- (4,415; dated and <= as-of, any status) is unchanged: it is the
-- conversion-cohort rule, and the conversion rates stay 70.0% / 85.7% /
-- 63.4% / 2023 by that ruling.
--
-- Columns unchanged. quoted_via now also reports 'quote' for a job whose
-- only quote-stage row is a dated Estimate Quote.

CREATE OR REPLACE VIEW v_quoted_jobs AS
WITH sig AS (
    SELECT job_id,
           BOOL_OR(type_name = 'Quote')                  AS has_quote_activity,
           BOOL_OR(type_name IN ('Measure', 'Template')) AS has_measure_or_template,
           MIN(activity_date)                            AS first_signal_date
    FROM activities
    WHERE type_name IN ('Quote', 'Measure', 'Template')
      AND (status_name IN ('Confirmed', 'Complete',
                           'Paid in Full and Finished', 'In Progress')
           OR activity_date IS NOT NULL)
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

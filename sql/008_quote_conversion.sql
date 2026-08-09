-- Additive migration: quote -> moved-forward conversion, monthly cohorts.
-- Definition LOCKED per Alex (2026-08-09), v2:
--   * Quoted: job has >=1 Quote activity with a non-NULL date (status
--     ignored). Cohort month = month of the job's FIRST dated Quote.
--   * Moved forward: dated Install activity (any date, past or future
--     counts — future = scheduled commitment), OR dated Removal (same), OR
--     a chatbot note confirming payment ("Payment received —" /
--     "Payment recorded —" / "check-bot" templates; human notes like
--     "asked for payment" deliberately do NOT match).
--   * Blank dates mean nothing: Install/Removal rows are pre-created on
--     every job, so only a real date signals commitment.
--   * An invoice NUMBER on the job does NOT count as moving forward — it
--     can appear before the customer actually commits.
--   * 7-day freshness rule: quotes issued within 7 days of the as-of date
--     are excluded from the denominator unless the job already moved
--     forward (then counted in numerator and denominator immediately).
--     Honest side effect: the most recent ~2 weeks read slightly high;
--     self-corrects as quotes age past 7 days.
--   * As-of date hardcoded to the frozen snapshot date.
--     TODO: switch to CURRENT_DATE after the freshness pipeline WO.

CREATE OR REPLACE VIEW v_quote_conversion_monthly AS
WITH quoted AS (
    SELECT job_id, MIN(activity_date) AS first_quote_date
    FROM activities
    WHERE type_name = 'Quote' AND activity_date IS NOT NULL
    GROUP BY job_id
),
moved AS (
    SELECT DISTINCT job_id FROM activities
    WHERE type_name IN ('Install', 'Removal') AND activity_date IS NOT NULL
    UNION
    SELECT DISTINCT job_id FROM activities
    WHERE notes ILIKE '%payment received —%'
       OR notes ILIKE '%payment recorded —%'
       OR notes ILIKE '%check-bot%'
),
eligible AS (
    SELECT q.job_id,
           date_trunc('month', q.first_quote_date)::date AS cohort_month,
           (m.job_id IS NOT NULL) AS moved_forward
    FROM quoted q
    LEFT JOIN moved m USING (job_id)
    WHERE q.first_quote_date <= DATE '2026-07-30' - 7   -- TODO: CURRENT_DATE
       OR m.job_id IS NOT NULL
)
SELECT cohort_month                                            AS quote_month,
       COUNT(*)                                                AS quoted_jobs,
       COUNT(*) FILTER (WHERE moved_forward)                   AS moved_forward,
       ROUND(100.0 * COUNT(*) FILTER (WHERE moved_forward)
             / COUNT(*), 1)                                    AS conversion_pct
FROM eligible
GROUP BY cohort_month;

GRANT SELECT ON v_quote_conversion_monthly TO rag_reader;

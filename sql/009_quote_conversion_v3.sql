-- Additive migration: quote-conversion definition v3 (Alex, 2026-08-09).
-- Replaces the v2 view from sql/008 (append-only convention: new file, not
-- an edit of 008).
--
-- v3 change — measure-proxy rule: if a job's Quote activity is UNDATED but
-- the job has a dated Measure activity, the quote is considered done (it
-- happened, just wasn't logged). Such jobs count as quoted, with the FIRST
-- dated Measure as the cohort date. Impact at snapshot: +983 quoted jobs.
-- A dated Measure with NO Quote activity at all does NOT count (279 such
-- jobs exist — flagged for Alex, deliberately excluded).
--
-- Everything else unchanged from v2 (see sql/008 comment): job-level
-- counting (re-quotes = one job), moved = dated Install / dated Removal /
-- chatbot payment note, invoice numbers don't count, 7-day freshness rule,
-- as-of hardcoded to snapshot 2026-07-30 (TODO: CURRENT_DATE after the
-- freshness pipeline WO).

CREATE OR REPLACE VIEW v_quote_conversion_monthly AS
WITH quoted AS (
    -- one row per quoted job; cohort = first dated Quote, else (measure-
    -- proxy) first dated Measure when every Quote activity is undated
    SELECT job_id,
           COALESCE(
               MIN(activity_date) FILTER (WHERE type_name = 'Quote'),
               MIN(activity_date) FILTER (WHERE type_name = 'Measure')
           ) AS first_quote_date
    FROM activities
    WHERE type_name IN ('Quote', 'Measure')
    GROUP BY job_id
    HAVING COUNT(*) FILTER (WHERE type_name = 'Quote') > 0
       AND (COUNT(*) FILTER (WHERE type_name = 'Quote'
                             AND activity_date IS NOT NULL) > 0
            OR COUNT(*) FILTER (WHERE type_name = 'Measure'
                                AND activity_date IS NOT NULL) > 0)
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

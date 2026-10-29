-- 018: performance index for v_wasted_templates (WO13 Change 2). Additive;
-- no view output changes.
--
-- Finding (Langfuse session eval-20260915-2102-aae90bc): every query that
-- touches v_wasted_templates took ~1.2 s in Postgres (2.0-2.4 s in the run),
-- whatever the WHERE — the view materialises all 3,643 template trips. The
-- five slowest sql_execute spans of the run (Q74, Q40, Q82, Q76, Q75) were
-- all this view; the other 54 queries had a 0.03 s median.
--
-- EXPLAIN ANALYZE: ~0.9 s of the 1.17 s was Step 3b of the view — the
-- correlated "same-day Measure note" lookup
--     SELECT m.notes FROM activities m
--     WHERE m.job_id = s.job_id AND m.type_name = 'Measure'
--       AND m.activity_date = s.activity_date AND m.notes ~* readiness_re
-- executed once per template trip (3,399 loops) through idx_activities_job_id,
-- reading and regex-filtering ~11 rows each time (0.27 ms/loop).
--
-- A partial composite index lets the lookup hit exactly the same-day
-- Measure rows (0.009 ms/loop): view 1,167 ms -> 326 ms, 184 kB, output
-- identical (md5 of the full ordered result set compared before/after).
-- Measure rows: 5,284 of 44,495 activities.
--
-- Not fixed here: Step 2's "install between templates" EXISTS scans the
-- installs CTE per trip (579 loops, ~125 ms) — a CTE cannot use an index;
-- taking that would need a view rewrite, out of scope for an additive
-- migration.

CREATE INDEX IF NOT EXISTS idx_activities_measure_job_date
    ON activities (job_id, activity_date)
    WHERE type_name = 'Measure';

ANALYZE activities;

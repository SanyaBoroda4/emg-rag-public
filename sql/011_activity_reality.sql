-- Additive migration: activity reality + JOIN fan-out fixes (WO 2026-08-12).
--
-- Part A — activities are PRE-CREATED on every job as placeholders; a row is
-- an event only if it has a date. Diagnostic on the frozen snapshot: 5,315
-- Quote rows but only 3,154 ever dated (~41% placeholders); Install 7,758 vs
-- 5,652 dated. Three-state rule, derived here as booleans so the SQL lane can
-- filter without re-deriving it:
--   activity_date IS NULL          -> placeholder, never happened, never count
--   dated and <= as-of             -> happened (counts for "did / have we")
--   dated and >  as-of             -> scheduled, not yet done
-- activity_date itself stays untouched (raw-first). As-of is the snapshot
-- date 2026-07-30, same hardcoding as sql/009 (TODO: CURRENT_DATE after the
-- freshness pipeline WO).
--
-- CREATE OR REPLACE VIEW can only append columns, so the new booleans come
-- after `note` (the sql/005 column order is preserved verbatim).

CREATE OR REPLACE VIEW v_activities AS
SELECT a.activity_id,
       a.job_id,
       j.job_name,
       a.type_name,
       a.status_name,
       a.activity_date,
       a.phase,
       (SELECT string_agg(aa.assignee_name, ', ')
        FROM activity_assignees aa
        WHERE aa.activity_id = a.activity_id) AS assignees,
       a.notes AS note,
       (a.activity_date IS NOT NULL
        AND a.activity_date <= DATE '2026-07-30') AS happened,
       (a.activity_date IS NOT NULL
        AND a.activity_date >  DATE '2026-07-30') AS is_scheduled_future
FROM activities a
JOIN jobs j USING (job_id);

-- Part B — JOIN fan-out: joining v_activities to v_job_areas on job_id
-- multiplies every activity row by every area row of the same job, inflating
-- SUM/AVG (Q31 measured 2x wrong). Pre-aggregated per-job square footage so
-- crew/date questions never need that join.

CREATE OR REPLACE VIEW v_job_sqft AS
SELECT job_id,
       SUM(sq_ft) AS total_sq_ft,
       COUNT(*)   AS area_count
FROM job_areas
GROUP BY job_id;

GRANT SELECT ON v_activities, v_job_sqft TO rag_reader;

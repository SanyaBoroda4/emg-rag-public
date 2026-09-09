-- Additive migration: wasted templates v2 (WO9, 2026-09-09). Supersedes the
-- view definition in sql/014 (append-only convention: new file, never an
-- edit). CREATE OR REPLACE with the identical column list, so the
-- v_wasted_templates_by_pm rollup from 014 stays valid.
--
-- Change 1 — Step 0 widened (Alex): a Template/Install is real when it is
-- dated, its status is Complete / Paid in Full and Finished / Confirmed /
-- In Progress, AND it is not in the future (activity_date <= CURRENT_DATE).
-- Estimate and RTF never count. All three tunables (phase gap, status
-- list, as-of guard) sit together in the params CTE.
--
-- Everything else (phases, structural signal, note signal, redo
-- attribution, same-day Measure notes) is exactly sql/014 — see its header
-- for the full rule and the 10 hand-verified jobs it reproduces.

CREATE OR REPLACE VIEW v_wasted_templates AS
WITH params AS (
    SELECT 30 AS phase_gap_days,
           -- Step 0 (v2): statuses that make a dated Template/Install a real
           -- field event. Estimate and RTF (Ready To Fabricate: a
           -- fabrication-stage marker, not a visit) never count.
           ARRAY['Complete', 'Paid in Full and Finished', 'Confirmed',
                 'In Progress']                          AS real_statuses,
           -- future-date guard: a scheduled event may not happen, so it
           -- can never satisfy a template. NOTE: the data is a snapshot
           -- frozen at 2026-07-30 while this runs on today's clock — a
           -- Confirmed install dated Aug 5 is "past" by the clock but absent
           -- from the data. Harmless here (an absent install satisfies
           -- nothing); revisit when the freshness pipeline exists.
           CURRENT_DATE                                   AS as_of,
           -- readiness-failure language: flags the template it is written on
           '(not ready|weren''?t ready|wasn''?t ready'
           || '|cabinets? (are |is |were |was |still )?(not|aren''?t|isn''?t|weren''?t|wasn''?t) (yet )?(installed|ready|in|done|set)'
           || '|cabinets? (need|needs|needed) (to be )?(adjust|redo|redone|fix|replace)'
           || '|(redo|redid|redoing|adjust|fix|replace)\w* (some |the |of the |their |his |her |a few |all )*cabinets?'
           || '|sink (is |was )?(not|isn''?t|wasn''?t) (yet )?(installed|in|ready|on site|there)'
           || '|uninstalled'
           || '|could(n''?t| not) template|can''?t template|did(n''?t| not) template|unable to template'
           || '|(before|until) (i|we|he|she|they) (could|can) template'
           || '|will be installed later|installed later)'
                                                          AS readiness_re,
           -- redo language: written on the REDO trip, so it flags the
           -- PREVIOUS template of the same phase; a note that carries it is
           -- never used as readiness evidence against its own template
           '(re-? ?templat|templat\w*.{0,40}\magain\M|redo of (the )?template'
           || '|finish templating|finish(ed)? (the )?template'
           || '|last time|first trip|second trip|2nd trip|previous (trip|visit))'
                                                          AS redo_re
),
real_events AS (                                   -- Step 0 (v2)
    SELECT a.activity_id, a.job_id, a.type_name, a.activity_date, a.notes
    FROM activities a
    CROSS JOIN params p
    WHERE a.type_name IN ('Template', 'Install')
      AND a.status_name = ANY (p.real_statuses)
      AND a.activity_date IS NOT NULL
      AND a.activity_date <= p.as_of
),
templates AS (
    SELECT activity_id, job_id, activity_date, notes,
           LAG(activity_date) OVER (PARTITION BY job_id
                                    ORDER BY activity_date, activity_id)
                                                          AS prev_date
    FROM real_events
    WHERE type_name = 'Template'
),
phased AS (                                        -- Step 1
    SELECT t.*,
           SUM(CASE WHEN t.prev_date IS NULL
                      OR t.activity_date - t.prev_date > p.phase_gap_days
                    THEN 1 ELSE 0 END)
               OVER (PARTITION BY t.job_id
                     ORDER BY t.activity_date, t.activity_id)
                                                          AS phase_no
    FROM templates t
    CROSS JOIN params p
),
seq AS (
    SELECT *,
           LEAD(activity_date) OVER w_phase                AS next_template_date,
           LEAD(notes)         OVER w_phase                AS next_template_note,
           MIN(activity_date)  OVER p_phase                AS phase_start_date,
           MAX(activity_date)  OVER p_phase                AS phase_end_date,
           COUNT(*)            OVER p_phase                AS templates_in_phase
    FROM phased
    WINDOW w_phase AS (PARTITION BY job_id, phase_no
                       ORDER BY activity_date, activity_id),
           p_phase AS (PARTITION BY job_id, phase_no)
),
phase_bounds AS (
    SELECT job_id, phase_no, phase_start_date,
           LEAD(phase_start_date) OVER (PARTITION BY job_id ORDER BY phase_no)
                                                          AS next_phase_start
    FROM (SELECT DISTINCT job_id, phase_no, phase_start_date FROM seq) x
),
installs AS (
    SELECT job_id, activity_date FROM real_events WHERE type_name = 'Install'
),
scored AS (
    SELECT s.*,
           pb.next_phase_start,
           EXISTS (SELECT 1 FROM installs i                -- Step 2
                   WHERE i.job_id = s.job_id
                     AND i.activity_date > s.activity_date
                     AND i.activity_date < s.next_template_date)
                                                          AS install_between,
           (SELECT COUNT(*) FROM installs i
            WHERE i.job_id = s.job_id
              AND i.activity_date >= s.phase_start_date
              AND (pb.next_phase_start IS NULL
                   OR i.activity_date < pb.next_phase_start))
                                                          AS installs_in_phase,
           -- Step 3a: own note (unless it is itself a redo note — then it
           -- describes the previous trip, handled by 3c on that row)
           CASE WHEN s.notes ~* p.readiness_re
                 AND s.notes !~* p.redo_re THEN s.notes END
                                                          AS own_note_hit,
           -- Step 3b: Measure note from the same visit (same day)
           (SELECT m.notes FROM activities m
            WHERE m.job_id = s.job_id
              AND m.type_name = 'Measure'
              AND m.activity_date = s.activity_date
              AND m.notes ~* p.readiness_re
            ORDER BY m.activity_id LIMIT 1)               AS measure_note_hit,
           -- Step 3c: the NEXT template of the phase says it is a redo
           CASE WHEN s.next_template_note ~* p.redo_re
                THEN s.next_template_note END             AS redo_note_hit
    FROM seq s
    JOIN phase_bounds pb USING (job_id, phase_no)
    CROSS JOIN params p
),
verdict AS (                                       -- Step 4
    SELECT *,
           (next_template_date IS NOT NULL AND NOT install_between)
                                                          AS structural_wasted,
           (own_note_hit IS NOT NULL OR measure_note_hit IS NOT NULL
            OR redo_note_hit IS NOT NULL)                 AS note_wasted,
           COALESCE(own_note_hit, measure_note_hit, redo_note_hit)
                                                          AS matched_note,
           CASE WHEN own_note_hit     IS NOT NULL THEN 'template'
                WHEN measure_note_hit IS NOT NULL THEN 'measure'
                WHEN redo_note_hit    IS NOT NULL THEN 'next_template'
           END                                            AS note_source
    FROM scored
)
SELECT v.job_id,
       j.job_name,
       j.salesperson,
       j.city,
       v.activity_id                                      AS template_activity_id,
       v.activity_date                                    AS template_date,
       v.phase_no,
       v.phase_start_date,
       v.phase_end_date,
       v.templates_in_phase,
       v.installs_in_phase,
       v.next_template_date,
       v.install_between,
       v.structural_wasted,
       v.note_wasted,
       v.matched_note,
       v.note_source,
       (v.structural_wasted OR v.note_wasted)             AS wasted,
       CASE WHEN v.structural_wasted AND v.note_wasted THEN 'both'
            WHEN v.structural_wasted                   THEN 'structural'
            WHEN v.note_wasted                         THEN 'note'
       END                                                AS wasted_reason,
       EXTRACT(YEAR FROM v.activity_date)::int            AS template_year
FROM verdict v
JOIN v_jobs j USING (job_id);

-- v_wasted_templates_by_pm (sql/014) is unchanged and stays valid: CREATE OR
-- REPLACE keeps the column list identical.
GRANT SELECT ON v_wasted_templates, v_wasted_templates_by_pm TO rag_reader;

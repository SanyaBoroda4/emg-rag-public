-- Additive migration: wasted-template detection (WO8, 2026-09-08).
--
-- Business question: how often did the template person drive to a job that
-- was not ready, and which project manager (salesperson) let it happen?
-- Every wasted template is an extra trip and a readiness failure by the PM.
-- Alex's stance: always eliminate template trips — better to wait a few
-- days and template everything at once.
--
-- The rule was reverse-engineered from 10 jobs Alex judged by hand (478,
-- 852, 1084, 1422, 1681, 2216, 3117, 4743, 5015, 5491) and must reproduce
-- every verdict — scripts/verify_wasted_templates.py is the gate. A naive
-- "2 templates + 1 install = wasted" heuristic was wrong on 4 of 10, which
-- is why the rule has this structure:
--
--   Step 0  only REAL events count: Template/Install rows with
--           status_name IN ('Complete','Paid in Full and Finished') AND a
--           date. Undated 'Estimate' placeholders never count (job 680).
--   Step 1  a job's real templates are split into PHASES: walking them in
--           date order, a gap > PHASE_GAP_DAYS starts a new phase (jobs
--           1422/1681: "gap too big, just two phases of the job"; job 772:
--           a 2023 template is a separate phase from the 2020 pair).
--   Step 2  STRUCTURAL signal, within a phase: every template except the
--           last is wasted if no real Install falls strictly between it
--           and the next template of the phase. The last template of a
--           phase is never structurally wasted. Job 3117 (T→I→T→I) is the
--           critical negative: zero wasted.
--   Step 3  NOTE signal, independent of structure: readiness-failure
--           language ("not ready", "cabinets needed to be adjusted", "could
--           not template", "will be installed later"...) on the template's
--           own note, or on a Measure logged on the SAME DAY as the
--           template (Measure + Template is one visit and the note often
--           sits on the Measure row — job 478). A Measure days or weeks
--           before the template is a different visit: if it found the site
--           not ready, the later template is the one that worked, so those
--           notes are deliberately NOT attributed. "Retemplate" / "template
--           again" / "second trip" / "wasn't ready last time" phrases are
--           written on the REDO trip, so they flag the PREVIOUS template of
--           the same phase, never the one they sit on (jobs 852, 5491 —
--           otherwise the productive second trip would be counted as a
--           second wasted one). A redo note on the first template of a
--           phase flags nothing: the earlier template is a separate phase.
--   Step 4  wasted = structural_wasted OR note_wasted; wasted_reason says
--           which fired. No "partial" category (job 478 counts as wasted).
--
-- Tunables live ONLY in the params CTE (never as literals in predicates):
--   phase_gap_days   30   — verify script re-runs totals at 21 and 45
--   readiness_re / redo_re — curated, case-insensitive; every matched note
--                            is reported by the gate so Alex can prune
--                            false positives and add phrasings.
--
-- One row per REAL template (not per job). Additive, idempotent: DROP +
-- CREATE keeps the natural column order across re-runs. Base tables
-- untouched.

DROP VIEW IF EXISTS v_wasted_templates_by_pm;
DROP VIEW IF EXISTS v_wasted_templates;

CREATE VIEW v_wasted_templates AS
WITH params AS (
    SELECT 30 AS phase_gap_days,
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
real_events AS (                                   -- Step 0
    SELECT activity_id, job_id, type_name, activity_date, notes
    FROM activities
    WHERE type_name IN ('Template', 'Install')
      AND status_name IN ('Complete', 'Paid in Full and Finished')
      AND activity_date IS NOT NULL
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

-- Rollup: the number Alex actually wants — per PM (salesperson) per year.
CREATE VIEW v_wasted_templates_by_pm AS
SELECT salesperson,
       template_year,
       COUNT(*)                                           AS real_templates,
       COUNT(*) FILTER (WHERE wasted)                     AS wasted_templates,
       ROUND(100.0 * COUNT(*) FILTER (WHERE wasted) / COUNT(*), 1)
                                                          AS wasted_pct
FROM v_wasted_templates
GROUP BY salesperson, template_year;

GRANT SELECT ON v_wasted_templates, v_wasted_templates_by_pm TO rag_reader;

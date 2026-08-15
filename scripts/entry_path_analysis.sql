-- Entry-path analysis: how did we know a job was quoted, and did it convert?
-- Answers Alex's question about template-only jobs, and quantifies the survivorship
-- bias in the 70.0% headline. Run on the frozen DB (as-of 2026-07-30).
--
--   docker exec -it emg_rag_db psql -U emg_rag -d emg_rag
--
-- NOTE: v_job_pipeline_status.signal_source is the type behind the LATEST signal,
-- not the only signal a job had. A job with a Quote in January and a Template in
-- March reads signal_source = 'template'. So it CANNOT isolate "template-only"
-- jobs — that needs the has_* flags below, derived from v_activities.


-- =====================================================================
-- 1. Conversion by entry path — the headline diagnostic
-- =====================================================================
WITH sig AS (
  SELECT job_id,
         bool_or(type_name = 'Quote')    AS has_quote,
         bool_or(type_name = 'Measure')  AS has_measure,
         bool_or(type_name = 'Template') AS has_template
  FROM v_activities
  WHERE happened
    AND type_name IN ('Quote','Measure','Template')
  GROUP BY job_id
)
SELECT CASE
         WHEN s.has_quote                                        THEN '1. quote logged'
         WHEN s.has_measure AND s.has_template                   THEN '2. measure + template, no quote'
         WHEN s.has_measure                                      THEN '3. measure only'
         ELSE                                                         '4. TEMPLATE ONLY'
       END                                                            AS entry_path,
       COUNT(*)                                                       AS quoted_jobs,
       COUNT(*) FILTER (WHERE p.status = 'moved')                     AS moved,
       COUNT(*) FILTER (WHERE p.status = 'pending')                   AS pending,
       COUNT(*) FILTER (WHERE p.status = 'quiet')                     AS quiet,
       ROUND(100.0 * COUNT(*) FILTER (WHERE p.status='moved')
             / NULLIF(COUNT(*),0), 1)                                 AS conversion_pct
FROM sig s
JOIN v_job_pipeline_status p USING (job_id)
WHERE p.is_quoted
GROUP BY 1
ORDER BY 1;

-- How to read it:
--   Path 1 is the honest sales funnel — this is your real close rate.
--   Paths 2-4 are inferred quotes. If they convert at 90-99%, the 70.0% headline
--   is being lifted by a population that was already sold, and the difference
--   between path 1's rate and 70.0% is the size of the definitional effect.


-- =====================================================================
-- 2. The urgent list: template-only jobs that went quiet and were NOT cancelled
--    These are the expensive failures — a truck went out, someone measured
--    the house with equipment, and no install ever followed.
-- =====================================================================
WITH sig AS (
  SELECT job_id,
         bool_or(type_name = 'Quote')    AS has_quote,
         bool_or(type_name = 'Measure')  AS has_measure,
         bool_or(type_name = 'Template') AS has_template
  FROM v_activities
  WHERE happened
    AND type_name IN ('Quote','Measure','Template')
  GROUP BY job_id
)
SELECT p.job_id, j.job_name, j.customer, j.salesperson, j.city,
       j.process_name, p.last_signal_date, p.days_silent
FROM v_job_pipeline_status p
JOIN v_jobs j USING (job_id)
JOIN sig  s USING (job_id)
WHERE p.status = 'quiet'
  AND j.process_name <> 'Canceled'
  AND s.has_template
  AND NOT s.has_quote
ORDER BY p.days_silent ASC;     -- freshest first = most recoverable


-- =====================================================================
-- 3. Same, for the whole genuinely-ambiguous quiet pipeline (~213 jobs)
--    ranked by entry path so the worst failures surface first
-- =====================================================================
WITH sig AS (
  SELECT job_id,
         bool_or(type_name = 'Quote')    AS has_quote,
         bool_or(type_name = 'Measure')  AS has_measure,
         bool_or(type_name = 'Template') AS has_template
  FROM v_activities
  WHERE happened
    AND type_name IN ('Quote','Measure','Template')
  GROUP BY job_id
)
SELECT CASE WHEN s.has_template THEN 'templated - money spent'
            WHEN s.has_measure  THEN 'measured'
            ELSE                     'quoted only' END          AS how_far_it_got,
       COUNT(*)                                                  AS quiet_jobs,
       ROUND(AVG(p.days_silent))                                 AS avg_days_silent
FROM v_job_pipeline_status p
JOIN v_jobs j USING (job_id)
JOIN sig  s USING (job_id)
WHERE p.status = 'quiet'
  AND j.process_name <> 'Canceled'
GROUP BY 1
ORDER BY 2 DESC;


-- =====================================================================
-- Recommended follow-up (small migration, sql/013)
-- v_job_pipeline_status already has had_dated_quote. Add the matching
--   had_dated_measure  and  had_dated_template
-- so the entry-path question is answerable from the canonical view alone,
-- without re-deriving flags from v_activities every time. Three booleans
-- fully describe how a job entered the pipeline, and the RAG can then answer
-- "did this job skip the quote stage?" directly.
-- =====================================================================

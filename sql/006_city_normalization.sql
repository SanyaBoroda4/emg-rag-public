-- Additive migration: normalized city beside the raw one. Raw-first rule:
-- jobs.city is NEVER modified; ingest/normalize_cities.py fills the new
-- columns from data/city_map_final.csv + ZIP/address rules.
--
-- city_norm_source: name_map | zip | address_map | excluded | unresolved
-- (NULL when the job has no raw city string at all).

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS city_normalized text;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS city_norm_source text;

CREATE INDEX IF NOT EXISTS idx_jobs_city_normalized ON jobs(city_normalized);

-- v_jobs now exposes the NORMALIZED value as `city` — the SQL lane queries
-- canonical areas by default, which is the entire point of the exercise. The
-- raw free-text value stays available as `city_raw` (appended last: CREATE OR
-- REPLACE VIEW may only add columns at the end).
CREATE OR REPLACE VIEW v_jobs AS
SELECT j.job_id,
       j.job_name,
       j.account_name AS customer,
       j.salesperson,
       j.city_normalized AS city,
       j.process_name,
       j.job_status_name AS status,
       j.creation_date,
       j.city AS city_raw
FROM jobs j;

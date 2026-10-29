-- Additive migration for the semantic layer (Work Order 3). Never edit 001/002.
--
-- 1. activities.phase: the Moraware Phase column survived the export inside
--    raw->'extra'->'jobPhases' (array of {id, name, seqNum}; non-empty on 1,639
--    activities). Backfilled here from raw. If load_moraware.py is ever re-run
--    it does not touch this column, but re-running this migration afterwards
--    refreshes it (the UPDATE is idempotent).
--
-- 2. chunks natural key: (source_type, source_id) so the chunk builder can
--    upsert. source_id is activity_id for activity notes and form_id for area
--    notes -- form_id, not job_areas.area_id, because job_areas is disposable
--    (truncate+rebuild regenerates area_ids) while form_id is stable.
--
-- 3. chunk_embeddings.text_hash: the hash of the text that was embedded, so a
--    changed chunk (note or context facts) re-embeds and an unchanged one is
--    skipped.
--
-- 4. pipeline_runs.note: free-text metadata for a run (e.g. API cost).

ALTER TABLE activities ADD COLUMN IF NOT EXISTS phase text;

UPDATE activities
SET phase = sub.phase_names
FROM (
    SELECT activity_id,
           (SELECT string_agg(p->>'name', ', ' ORDER BY (p->>'seqNum')::int)
            FROM jsonb_array_elements(raw->'extra'->'jobPhases') p) AS phase_names
    FROM activities
) sub
WHERE activities.activity_id = sub.activity_id
  AND activities.phase IS DISTINCT FROM sub.phase_names;

CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_source_key ON chunks(source_type, source_id);

ALTER TABLE chunk_embeddings ADD COLUMN IF NOT EXISTS text_hash text;

ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS note text;

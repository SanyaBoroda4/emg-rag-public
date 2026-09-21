-- Additive migration: BM25-style keyword lane via Postgres full-text search.
-- Generated column so the tsvector tracks context_text/raw_text automatically
-- (build_chunks upserts regenerate it). English config; numbers and proper
-- nouns ("6470", "Zegers", "Calacatta") survive as lexemes, which is the
-- whole point of this lane — dense retrieval whiffs on bare identifiers.

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS fts tsvector
    GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(context_text, '') || ' ' || raw_text)
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_chunks_fts ON chunks USING gin(fts);

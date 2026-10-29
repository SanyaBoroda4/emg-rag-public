-- 020: the `serve` schema — UI question history for the HTTPS front end
-- (WO16). Additive. Kept out of the analytics schema: rag_reader (the
-- text-to-SQL role) gets NO access to it; the API uses a separate role
-- rag_serve with INSERT/SELECT on serve.* and the same SELECT rights as
-- rag_reader on the v_* views. rag_serve's password is set by
-- scripts/setup_serve_role.py from PG_SERVE_PASSWORD in .env (never here).

CREATE SCHEMA IF NOT EXISTS serve;
REVOKE ALL ON SCHEMA serve FROM PUBLIC;

CREATE TABLE IF NOT EXISTS serve.asks (
  id          bigserial PRIMARY KEY,
  user_name   text        NOT NULL,          -- the Basic-Auth username
  session_id  uuid        NOT NULL,          -- one per browser tab
  asked_at    timestamptz NOT NULL DEFAULT now(),
  question    text        NOT NULL,
  route       text,
  answer      text,
  response    jsonb,                          -- the full /api/ask payload
  trace_id    text,                           -- Langfuse trace id
  latency_ms  int,
  cost_usd    numeric(8,5),
  error       text                            -- set instead of answer when the ask failed
);
CREATE INDEX IF NOT EXISTS asks_user_asked_at_idx ON serve.asks (user_name, asked_at DESC);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_serve') THEN
    CREATE ROLE rag_serve LOGIN;
  END IF;
END $$;

GRANT USAGE ON SCHEMA serve TO rag_serve;
GRANT SELECT, INSERT ON serve.asks TO rag_serve;
GRANT USAGE, SELECT ON SEQUENCE serve.asks_id_seq TO rag_serve;
-- the API's health check and history endpoints; the pipeline itself keeps
-- running SQL as rag_reader (validated, 10 s statement timeout) as before
GRANT USAGE ON SCHEMA public TO rag_serve;

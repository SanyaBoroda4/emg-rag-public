-- EMG RAG schema. Idempotent: safe to re-run.
--
-- Design principles:
--   * Raw-first: area_fields is verbatim key/value from Moraware; job_areas is the
--     typed, queryable version derived from it. A bad transform is re-derived from
--     area_fields, never re-exported. jobs.raw holds the untouched JSON per job.
--   * Job<->invoice is many-to-many via job_invoices (a job can carry several
--     invoices - kitchen, bath, vanity), recording which activity the number came from.
--   * chunks and chunk_embeddings are separate so text_hash can skip re-embedding
--     unchanged text.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS jobs (
    job_id          bigint PRIMARY KEY,
    job_name        text,
    account_id      bigint,
    account_name    text,
    process_id      bigint,
    process_name    text,
    job_status_id   bigint,
    job_status_name text,
    creation_date   date,
    salesperson     text,
    special_comment text,
    job_notes       text,
    job_url         text,
    addr_line1      text,
    addr_line2      text,
    city            text,
    state           text,
    zip             text,
    addr_raw        text,
    raw             jsonb,          -- untouched source JSON for this job (safety net)
    ingested_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_contacts (
    id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id  bigint NOT NULL REFERENCES jobs(job_id),
    name    text,
    phone   text,
    cell    text,
    email   text
);

CREATE TABLE IF NOT EXISTS activities (
    activity_id   bigint PRIMARY KEY,
    job_id        bigint NOT NULL REFERENCES jobs(job_id),
    type_id       bigint,
    type_name     text,
    status_id     bigint,
    status_name   text,
    activity_date date,            -- nullable: ~2,572 activities have no date
    activity_time text,
    duration      text,
    notes         text,
    note_len      int GENERATED ALWAYS AS (length(notes)) STORED,
    raw           jsonb
);

-- Many-to-many: an activity can have several assignees.
CREATE TABLE IF NOT EXISTS activity_assignees (
    activity_id   bigint NOT NULL REFERENCES activities(activity_id),
    assignee_id   bigint NOT NULL,
    assignee_name text,
    PRIMARY KEY (activity_id, assignee_id)
);

CREATE TABLE IF NOT EXISTS job_forms (
    form_id            bigint PRIMARY KEY,  -- synthetic if Moraware has none
    job_id             bigint NOT NULL REFERENCES jobs(job_id),
    form_name          text,
    form_template_name text,
    field_count        int
);

-- Verbatim key/value from Moraware forms. Blank values are kept on purpose:
-- absence and emptiness are different signals.
CREATE TABLE IF NOT EXISTS area_fields (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    form_id     bigint NOT NULL REFERENCES job_forms(form_id),
    job_id      bigint NOT NULL REFERENCES jobs(job_id),
    field_name  text,
    field_value text,
    data_type   text
);

-- Typed, queryable version derived from area_fields.
CREATE TABLE IF NOT EXISTS job_areas (
    area_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id            bigint NOT NULL REFERENCES jobs(job_id),
    form_id           bigint REFERENCES job_forms(form_id),
    area_name         text,
    room_type         text,
    sq_ft             numeric,     -- NULL when unparseable; sq_ft_raw keeps the source
    sq_ft_raw         text,
    material_name     text,
    supplier          text,
    sink              text,
    sink_types        text,
    sink_installed_as text,
    edge              text,
    backsplash        text,
    faucet_info       text,
    removal           text,
    brackets          text,
    hlf               text,
    reference         text,
    notes             text
);

CREATE TABLE IF NOT EXISTS job_summary (
    job_id            bigint PRIMARY KEY REFERENCES jobs(job_id),
    deposit_received  boolean,
    paid_in_full      boolean,
    removal_ready     boolean,
    template_ready    boolean,
    sink_in_shop      boolean,
    material_ordered  boolean,
    material_received boolean
);

CREATE TABLE IF NOT EXISTS invoices (
    doc_number    text PRIMARY KEY,
    qb_id         text,
    customer_name text,
    txn_date      date,
    due_date      date,
    total_amt     numeric,
    balance       numeric,
    status        text,
    customer_memo text,
    private_note  text,
    bill_email    text,
    qb_created    timestamptz,
    qb_updated    timestamptz
);

CREATE TABLE IF NOT EXISTS invoice_lines (
    line_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    doc_number text NOT NULL REFERENCES invoices(doc_number),
    line_num   int,
    item_name  text,
    description text,
    qty        numeric,
    unit_price numeric,
    amount     numeric
);

-- No FK on doc_number: an invoice number may appear in a Moraware note without
-- existing in QuickBooks (typos). We keep those visible rather than lose them to a
-- constraint failure.
CREATE TABLE IF NOT EXISTS job_invoices (
    job_id             bigint NOT NULL REFERENCES jobs(job_id),
    doc_number         text NOT NULL,
    source_activity_id bigint,
    PRIMARY KEY (job_id, doc_number)
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_type  text NOT NULL CHECK (source_type IN ('activity_note', 'area_note', 'job_timeline')),
    source_id    bigint,
    job_id       bigint NOT NULL REFERENCES jobs(job_id),
    raw_text     text NOT NULL,
    context_text text,
    text_hash    text NOT NULL,
    token_count  int,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Dimension 1024 must match whichever embedding model is chosen; change here and
-- re-embed if the model changes.
CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id   bigint PRIMARY KEY REFERENCES chunks(chunk_id),
    embedding  vector(1024),
    model      text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- No vector index on purpose: at ~45k vectors an exact scan is faster to build, uses
-- far less memory, and has perfect recall. Revisit (HNSW/IVFFlat) around ~100k+
-- vectors, when scan latency starts to matter.

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source      text NOT NULL,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    rows_in     int,
    rows_out    int,
    status      text,
    error       text
);

CREATE INDEX IF NOT EXISTS idx_activities_job_id       ON activities(job_id);
CREATE INDEX IF NOT EXISTS idx_activities_type_name    ON activities(type_name);
CREATE INDEX IF NOT EXISTS idx_activities_date         ON activities(activity_date);
CREATE INDEX IF NOT EXISTS idx_area_fields_job_id      ON area_fields(job_id);
CREATE INDEX IF NOT EXISTS idx_job_areas_job_id        ON job_areas(job_id);
CREATE INDEX IF NOT EXISTS idx_job_areas_material      ON job_areas(material_name);
CREATE INDEX IF NOT EXISTS idx_chunks_job_id           ON chunks(job_id);
CREATE INDEX IF NOT EXISTS idx_chunks_text_hash        ON chunks(text_hash);
CREATE INDEX IF NOT EXISTS idx_job_invoices_doc_number ON job_invoices(doc_number);

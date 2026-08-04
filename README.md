# emg-rag

RAG pipeline over EMG's Moraware and QuickBooks data: Postgres + pgvector,
raw-first ingestion, chunking and embeddings, retrieval.

See `CLAUDE.md` for project context, server constraints, and working rules.

## Layout

- `docker-compose.yml` — pgvector Postgres 17, memory-capped, localhost-only on 5433
- `sql/` — idempotent, append-only migrations (001 schema … 005 retrieval views)
- `ingest/` — ingestion + semantic-layer package (`db.py` connection helper)
- `retrieval/` — BM25/dense/RRF lanes, reranker, text-to-SQL lane, router, answer
- `scripts/check_db.py` — verifies connection, extension, and tables
- `scripts/query.py` — end-to-end query CLI (route, retrieval, answer, latency)

## Known constraints

- **Voyage AI rate limits** (observed 2026-08-02): the account tier allows ~3
  requests/min and ~10K tokens/min, and a single request whose token count
  exceeds the per-minute budget is refused outright rather than queued. All
  Voyage calls go through `ingest/voyage_util.py` (exponential backoff with
  jitter); bulk embedding uses 48-text (~7K-token) batches paced 60s apart.
  Full-corpus embedding takes ~1h at this tier; adding a payment method to the
  Voyage account would cut that to ~1 minute.
- The server has ~1 GiB free RAM and runs live production containers; every
  component is memory-budgeted (see CLAUDE.md).

## Known outstanding work

- **`job_areas.material_name` needs a parser, not a mapping table**: 3,671
  distinct values across ~4,700 filled rows, with slab count, thickness, and
  finish embedded in free text (`2 x Shadow Storm Honed`,
  `(1.5)Calcatta Liberty`, `0.3 SB Brazilian Carrera`). Deserves its own work
  order producing structured columns (material, slab_count, thickness,
  finish) the way WO5 normalized cities.

## Setup

```bash
cp .env.example .env   # fill in real values
docker compose up -d
docker exec -i emg_rag_db psql -U emg_rag -d emg_rag < sql/001_schema.sql
pip install -r requirements.txt
python scripts/check_db.py
```

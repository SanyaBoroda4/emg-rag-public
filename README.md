# emg-rag

RAG pipeline over EMG's Moraware and QuickBooks data: Postgres + pgvector,
raw-first ingestion, chunking and embeddings, retrieval.

See `CLAUDE.md` for project context, server constraints, and working rules.

## Layout

- `docker-compose.yml` — pgvector Postgres 17, memory-capped, localhost-only on 5433
- `sql/001_schema.sql` — idempotent schema
- `ingest/` — ingestion package (`db.py` connection helper)
- `scripts/check_db.py` — verifies connection, extension, and tables

## Setup

```bash
cp .env.example .env   # fill in real values
docker compose up -d
docker exec -i emg_rag_db psql -U emg_rag -d emg_rag < sql/001_schema.sql
pip install -r requirements.txt
python scripts/check_db.py
```

# EMG RAG

RAG pipeline over EMG's Moraware (countertop job tracking) and QuickBooks data:
ingest raw exports into Postgres + pgvector, derive clean queryable tables, chunk and
embed the text, and answer questions over it.

## Environments

- **Local repo:** `C:\Users\alex\PycharmProjects\emg-rag` (PyCharm, Windows)
- **Remote:** `github.com/SanyaBoroda4/emg-rag` (private)
- **Server:** Hetzner CPX11, Ubuntu 26.04, `root@SERVER_IP_REDACTED`, repo cloned at
  `/opt/emg-rag`, auto-pulls from GitHub every minute via cron.

## Server constraints — important

2 GB RAM total, shared with live production services: Evolution API (WhatsApp), an MCP
server, Caddy, plus their own Postgres and Redis. Those five containers use ~370 MB
combined. ~1.1 GB is available, and 2 GB of swap exists. **Nothing this project runs
may ever starve the WhatsApp containers.** Every new container gets an explicit memory
limit.

## Data on the server

- `/opt/emg-rag/raw/moraware/pages/*.json` — 112 files, 38 MB, the complete Moraware
  export: 5,569 jobs, 44,495 activities, 12,201 forms, 149,364 fields
- `/opt/emg-rag/raw/moraware/activity_assignees.csv` — 21,644 rows, activity → assignee
- QuickBooks invoice export (5,257 invoices) is not yet on the server; it will be added
  in a later work order

**Note on the JSON files:** they were written on Windows and carry a UTF-8 BOM. Any
reader must use `encoding="utf-8-sig"`, not `utf-8`.

## Git workflow — MANDATORY
Commit and push after every completed unit of work. Do not ask permission.
- One logical change = one commit
- Conventional commits: feat:, fix:, chore:, docs:, refactor:, test:
- Always push after committing
- NEVER commit: .env, credentials, anything under raw/, anything under .venv/

## Working discipline
- Investigate before building. Verify against real data, never assume.
- Raw-first: land untouched source data, transform separately. A bad transform is a
  re-run, never a re-pull.
- Idempotent by default: running a script twice produces the same result.
- Every script that touches the database logs a row to pipeline_runs.
- Secrets come from .env via python-dotenv. Never hardcoded, never committed.
- The server is memory-constrained and runs live production services. Cap every
  container. Never assume headroom.

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

## Server access rules
SSH to root@SERVER_IP_REDACTED is permitted for this project only.
- Only touch /opt/emg-rag and the emg_rag_db container
- NEVER stop, restart, modify, or inspect: evolution_api, evolution_postgres,
  evolution_redis, caddy, emg_mcp
- NEVER run system-wide changes: apt upgrade, reboot, firewall rules, cron edits
  outside this project
- If a task seems to require touching production services, stop and ask

## Git workflow — MANDATORY
Commit and push after every completed unit of work. Do not ask permission.
- One logical change = one commit
- Conventional commits: feat:, fix:, chore:, docs:, refactor:, test:
- Always push after committing
- NEVER commit: .env, credentials, anything under raw/, anything under .venv/

## Public mirror — MANDATORY
`github.com/SanyaBoroda4/emg-rag-public` is a sanitized public mirror of this
repo kept for Alex's job-search portfolio. Since WO19 it is an **allowlisted
snapshot**, not a history replay: `deploy/public_allowlist.txt` names what may
go public, `scripts/public_transform.py` rewrites it (employee pseudonyms,
customer names / contact data / EMG dollar figures / verbatim note text
redacted, server IP redacted) and `scripts/public_scan.py` is the guard: any
customer, contact, note-text or secret hit and nothing is pushed. The term
lists live in `private/` (gitignored; rebuilt on the server by the WO19 term
builder, see `docs/wo19_public_audit.md`). After pushing to the private repo,
run `bash scripts/sync_public.sh` — at minimum once at the end of every
working session. Never push to the public repo directly. New files are
private by default; to publish one, add it to the allowlist in the same
commit and make sure it passes the guard. Never let secrets or infrastructure
identifiers into tracked files at all.

## Working discipline
- Investigate before building. Verify against real data, never assume.
- Raw-first: land untouched source data, transform separately. A bad transform is a
  re-run, never a re-pull.
- Idempotent by default: running a script twice produces the same result.
- Every script that touches the database logs a row to pipeline_runs.
- Secrets come from .env via python-dotenv. Never hardcoded, never committed.
- The server is memory-constrained and runs live production services. Cap every
  container. Never assume headroom.

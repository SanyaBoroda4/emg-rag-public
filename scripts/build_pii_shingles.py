"""WO19 note fingerprints: run ON THE SERVER, stdout is the private shingle file.

    ssh root@SERVER 'cd /opt/emg-rag && .venv/bin/python -' < scripts/build_pii_shingles.py | sort -u > private/shingles.txt

One sha1[:10] per 8-word window of every chunk's raw text, one per line; the
chunk count goes to stderr. Owner role, read-only transaction, server-side
cursor so memory stays flat on the 2 GB box."""
import hashlib, re, sys
from ingest.db import get_conn
out = sys.stdout
n_chunks = 0
with get_conn(options="-c default_transaction_read_only=on") as c, c.cursor(name="wo19") as cur:
    cur.itersize = 500
    cur.execute("SELECT raw_text FROM chunks")
    for (t,) in cur:
        n_chunks += 1
        w = re.findall(r"[a-z0-9]+", (t or "").lower())
        for i in range(0, max(0, len(w) - 7)):
            out.write(hashlib.sha1(" ".join(w[i:i+8]).encode()).hexdigest()[:10] + "\n")
sys.stderr.write(f"chunks {n_chunks}\n")

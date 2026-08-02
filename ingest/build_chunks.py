"""Populate chunks from activity notes and area notes.

Selection, sources, keys, and the >= 25-trimmed-chars threshold are documented
in ingest/context_facts.py (shared with contextualize.py).

text_hash = sha256(raw_text + sha256(context_facts)) — it covers both the note
text and the context facts fed to the enrichment prompt, so a changed job
header (salesperson, status, materials...) re-triggers enrichment for that
job's chunks even when the note itself is unchanged.

Idempotent: upsert on (source_type, source_id). When the hash is unchanged the
existing context_text is kept; when it changed, context_text is reset to NULL,
which is the work queue for contextualize.py. Running twice changes nothing.
"""

import hashlib
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.context_facts import build_all
from ingest.db import get_conn

UPSERT_SQL = """
    INSERT INTO chunks (source_type, source_id, job_id, raw_text, context_text,
                        text_hash, token_count)
    VALUES (%s, %s, %s, %s, NULL, %s, %s)
    ON CONFLICT (source_type, source_id) DO UPDATE SET
        job_id = EXCLUDED.job_id,
        raw_text = EXCLUDED.raw_text,
        token_count = EXCLUDED.token_count,
        context_text = CASE WHEN chunks.text_hash = EXCLUDED.text_hash
                            THEN chunks.context_text ELSE NULL END,
        text_hash = EXCLUDED.text_hash
"""


def text_hash_for(raw_text: str, facts: str) -> str:
    facts_hash = hashlib.sha256(facts.encode("utf-8")).hexdigest()
    return hashlib.sha256((raw_text + facts_hash).encode("utf-8")).hexdigest()


def main() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pipeline_runs (source, status) "
                "VALUES ('build_chunks', 'running') RETURNING run_id")
            run_id = cur.fetchone()[0]
        conn.commit()

        try:
            counts = {"activity_note": 0, "area_note": 0}
            rows = []
            with conn.cursor() as cur:
                for stype, sid, jid, text, facts in build_all(cur):
                    rows.append((stype, sid, jid, text,
                                 text_hash_for(text, facts), len(text) // 4))
                    counts[stype] += 1
            with conn.cursor() as cur:
                cur.executemany(UPSERT_SQL, rows)
                cur.execute("SELECT count(*), count(context_text) FROM chunks")
                total, with_ctx = cur.fetchone()
                cur.execute(
                    "UPDATE pipeline_runs SET finished_at = now(), status = 'ok', "
                    "rows_in = %s, rows_out = %s, note = %s WHERE run_id = %s",
                    (len(rows), total,
                     f"activity={counts['activity_note']} area={counts['area_note']}",
                     run_id))
            conn.commit()
            print(f"chunks upserted: {len(rows)} "
                  f"(activity_note {counts['activity_note']}, "
                  f"area_note {counts['area_note']})")
            print(f"chunks in table: {total}, with context_text: {with_ctx}, "
                  f"pending enrichment: {total - with_ctx}")
        except Exception:
            conn.rollback()
            err = traceback.format_exc()
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE pipeline_runs SET finished_at = now(), "
                    "status = 'failed', error = %s WHERE run_id = %s",
                    (err, run_id))
            conn.commit()
            print(err, file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

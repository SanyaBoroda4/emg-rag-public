"""The semantic-layer gate (Work Order 3).

Checks: chunk count vs the live selection queries, 100% context coverage,
embeddings == chunks with all vectors 1024-dim, prints 10 random raw/context
pairs for human review, runs one smoke retrieval end to end, and totals actual
API spend from pipeline_runs against the $30 ceiling.

Exits non-zero on: chunk-count mismatch, missing context, missing/short
embeddings, or spend over the ceiling.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import voyageai

from ingest.context_facts import MIN_CHARS
from ingest.db import get_conn

CEILING = 30.0
SMOKE_QUERY = "job went quiet after quote"


def main() -> int:
    failed = False
    with get_conn() as conn, conn.cursor() as cur:
        # Expected chunk counts straight from the source tables (the truth)
        # btrim over all whitespace to match Python's str.strip() in the builder
        ws = " \t\r\n\x0b\x0c"
        cur.execute("SELECT count(*) FROM activities "
                    "WHERE length(btrim(notes, %s)) >= %s", (ws, MIN_CHARS))
        exp_act = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM job_areas "
                    "WHERE length(btrim(notes, %s)) >= %s", (ws, MIN_CHARS))
        exp_area = cur.fetchone()[0]
        cur.execute("""
            SELECT count(*) FROM area_fields af
            JOIN job_forms f ON f.form_id = af.form_id
            WHERE f.form_template_name = 'Job Summary'
              AND af.field_name = 'Notes'
              AND length(btrim(af.field_value, %s)) >= %s""", (ws, MIN_CHARS))
        exp_js = cur.fetchone()[0]
        expected = exp_act + exp_area + exp_js

        cur.execute("SELECT count(*), count(context_text) FROM chunks")
        total, with_ctx = cur.fetchone()
        ok = total == expected
        failed |= not ok
        print(f"chunks: {total} (expected {expected} = {exp_act} activity + "
              f"{exp_area} area + {exp_js} job-summary) "
              f"{'OK' if ok else '** MISMATCH **'}")

        ok = with_ctx == total
        failed |= not ok
        print(f"chunks with context_text: {with_ctx}/{total} "
              f"{'OK' if ok else '** INCOMPLETE **'}")
        if not ok:
            cur.execute("SELECT chunk_id, source_type, source_id FROM chunks "
                        "WHERE context_text IS NULL LIMIT 20")
            for row in cur.fetchall():
                print(f"  missing context: {row}")

        cur.execute("SELECT count(*), count(*) FILTER "
                    "(WHERE vector_dims(embedding) = 1024) "
                    "FROM chunk_embeddings")
        n_emb, n_1024 = cur.fetchone()
        ok = n_emb == total and n_1024 == n_emb
        failed |= not ok
        print(f"embeddings: {n_emb}/{total}, 1024-dim: {n_1024}/{n_emb} "
              f"{'OK' if ok else '** MISMATCH **'}")

        print("\n===== 10 random chunks: note vs generated context =====")
        cur.execute("""
            SELECT chunk_id, source_type, job_id, raw_text, context_text
            FROM chunks ORDER BY random() LIMIT 10""")
        for cid, stype, jid, raw, ctx in cur.fetchall():
            raw_disp = raw.replace("\r\n", " / ").replace("\n", " / ")
            print(f"\n[{cid}] {stype} job {jid}")
            print(f"  NOTE:    {raw_disp[:220]}")
            print(f"  CONTEXT: {ctx}")

        print(f"\n===== smoke retrieval: {SMOKE_QUERY!r} =====")
        vo = voyageai.Client()
        qvec = vo.embed([SMOKE_QUERY], model="voyage-3.5-lite",
                        input_type="query").embeddings[0]
        qstr = "[" + ",".join(f"{x:.8f}" for x in qvec) + "]"
        cur.execute("""
            SELECT c.job_id, c.chunk_id, e.embedding <=> %s::vector AS dist,
                   c.context_text, c.raw_text
            FROM chunk_embeddings e
            JOIN chunks c ON c.chunk_id = e.chunk_id
            ORDER BY dist LIMIT 5""", (qstr,))
        for jid, cid, dist, ctx, raw in cur.fetchall():
            raw_disp = raw.replace("\r\n", " / ").replace("\n", " / ")
            print(f"\njob {jid} chunk {cid} dist {dist:.4f}")
            print(f"  CONTEXT: {ctx}")
            print(f"  NOTE:    {raw_disp[:200]}")

        cur.execute("SELECT note FROM pipeline_runs WHERE note LIKE '%cost_usd=%'")
        spend = 0.0
        for (note,) in cur.fetchall():
            m = re.search(r"cost_usd=([0-9.]+)", note)
            if m:
                spend += float(m.group(1))
        ok = spend <= CEILING
        failed |= not ok
        print(f"\ntotal API spend: ${spend:.4f} vs ${CEILING:.0f} ceiling "
              f"{'OK' if ok else '** OVER **'}")

    print("\nFAIL" if failed else "\nOK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

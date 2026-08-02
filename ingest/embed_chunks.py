"""Embed chunks with voyage-3.5-lite (1024 dims, matches vector(1024)).

Embeds context_text + "\n" + raw_text per chunk, 128 texts per API call, with
simple exponential backoff on rate limits. Upserts into chunk_embeddings keyed
on chunk_id, storing the chunk's text_hash alongside — chunks whose embedding
already exists with the current text_hash are skipped, so re-running embeds
nothing and a changed chunk (note or context facts) re-embeds.

Chunks without context_text yet are skipped (contextualize.py must run first);
their count is reported.

Cost (voyage-3.5-lite $0.02/MTok) is logged to pipeline_runs.note as
"cost_usd=..." so verify_semantic.py can total spend.
"""

import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import voyageai

from ingest.db import get_conn

MODEL = "voyage-3.5-lite"
# voyage-3.5-lite accepts up to 1,000 texts per call. The basic-tier rate
# limit (~3 RPM) makes many small calls pathological — 128-text batches spent
# ~75s in backoff per call — so we send few large ones and pace them.
BATCH_SIZE = 1000
PAUSE_BETWEEN_CALLS = 21  # seconds; stays under 3 requests/minute
PER_MTOK = 0.02

UPSERT_SQL = """
    INSERT INTO chunk_embeddings (chunk_id, embedding, model, text_hash)
    VALUES (%s, %s::vector, %s, %s)
    ON CONFLICT (chunk_id) DO UPDATE SET
        embedding = EXCLUDED.embedding, model = EXCLUDED.model,
        text_hash = EXCLUDED.text_hash, created_at = now()
"""


def embed_with_backoff(vo, texts):
    delay = 5
    for attempt in range(6):
        try:
            return vo.embed(texts, model=MODEL, input_type="document")
        except voyageai.error.RateLimitError:
            print(f"  rate limited, sleeping {delay}s")
            time.sleep(delay)
            delay = min(delay * 2, 60)
    raise RuntimeError("still rate limited after 6 attempts")


def main() -> int:
    vo = voyageai.Client()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pipeline_runs (source, status) "
                "VALUES ('embed', 'running') RETURNING run_id")
            run_id = cur.fetchone()[0]
        conn.commit()

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT c.chunk_id, c.context_text, c.raw_text, c.text_hash
                    FROM chunks c
                    LEFT JOIN chunk_embeddings e ON e.chunk_id = c.chunk_id
                    WHERE c.context_text IS NOT NULL
                      AND (e.chunk_id IS NULL
                           OR e.text_hash IS DISTINCT FROM c.text_hash)
                    ORDER BY c.chunk_id
                """)
                todo = cur.fetchall()
                cur.execute("SELECT count(*) FROM chunks WHERE context_text IS NULL")
                no_ctx = cur.fetchone()[0]

            print(f"{len(todo)} chunks to embed "
                  f"({no_ctx} skipped: no context_text yet)")
            total_tokens = 0
            done = 0
            for start in range(0, len(todo), BATCH_SIZE):
                if start:
                    time.sleep(PAUSE_BETWEEN_CALLS)
                batch = todo[start:start + BATCH_SIZE]
                texts = [f"{ctx}\n{raw}" for _, ctx, raw, _ in batch]
                result = embed_with_backoff(vo, texts)
                total_tokens += result.total_tokens
                rows = [
                    (cid, "[" + ",".join(f"{x:.8f}" for x in emb) + "]",
                     MODEL, thash)
                    for (cid, _, _, thash), emb
                    in zip(batch, result.embeddings)
                ]
                with conn.cursor() as cur:
                    cur.executemany(UPSERT_SQL, rows)
                conn.commit()
                done += len(rows)
                if done % 1280 == 0 or done == len(todo):
                    print(f"  {done}/{len(todo)} embedded")

            cost = total_tokens * PER_MTOK / 1_000_000
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE pipeline_runs SET finished_at = now(), status = 'ok', "
                    "rows_in = %s, rows_out = %s, note = %s WHERE run_id = %s",
                    (len(todo), done,
                     f"cost_usd={cost:.4f} embed_tokens={total_tokens}", run_id))
            conn.commit()
            print(f"embedded {done} chunks, {total_tokens} tokens, "
                  f"cost ${cost:.4f}")
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

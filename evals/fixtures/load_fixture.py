"""Load the synthetic fixture into a (CI) Postgres and embed its chunks.

Applies the real migrations (001..006) so the fixture DB has the production
shape, inserts fixture.sql, then embeds the ~200 chunk texts with ONE Voyage
call and fills chunk_embeddings. Total Voyage spend: fractions of a cent.

Intended for the GitHub Actions service container; harmless to run against
any empty database. Refuses to run if the target already has chunks (never
point it at production).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import voyageai

from ingest.db import get_conn
from ingest.voyage_util import EMBED_MODEL, embed_texts

REPO = Path(__file__).resolve().parents[2]
FIXTURE_SQL = Path(__file__).resolve().parent / "fixture.sql"
MIGRATIONS = sorted((REPO / "sql").glob("0*.sql"))


def main() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.chunks')")
            if cur.fetchone()[0] is not None:
                cur.execute("SELECT count(*) FROM chunks")
                if cur.fetchone()[0] > 0:
                    print("FAIL: target database already has chunks — "
                          "refusing (this loader is for empty CI databases)",
                          file=sys.stderr)
                    return 1
        for mig in MIGRATIONS:
            conn.execute(mig.read_text(encoding="utf-8"))
        conn.execute(FIXTURE_SQL.read_text(encoding="utf-8"))
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT chunk_id, coalesce(context_text, '') || "
                        "E'\\n' || raw_text, text_hash FROM chunks "
                        "ORDER BY chunk_id")
            rows = cur.fetchall()
        vo = voyageai.Client()
        result = embed_texts(vo, [t for _, t, _ in rows])
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunk_embeddings (chunk_id, embedding, model, "
                "text_hash) VALUES (%s, %s::vector, %s, %s)",
                [(cid, "[" + ",".join(f"{x:.8f}" for x in emb) + "]",
                  EMBED_MODEL, thash)
                 for (cid, _, thash), emb in zip(rows, result.embeddings)])
        conn.commit()
    print(f"fixture loaded: {len(rows)} chunks embedded")
    return 0


if __name__ == "__main__":
    sys.exit(main())

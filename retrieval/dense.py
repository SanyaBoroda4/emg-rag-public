"""Dense lane: voyage-3.5-lite query embedding + exact pgvector scan.

Deliberately NO ANN index: at 7,194 vectors an exact `ORDER BY embedding <=>`
scan is a few milliseconds, has perfect recall, and costs zero build memory
on this RAM-constrained host. Revisit (HNSW) around ~100k vectors, when scan
latency starts to matter — not before.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import voyageai

from ingest.voyage_util import embed_texts

_vo = None


def _client():
    global _vo
    if _vo is None:
        _vo = voyageai.Client()
    return _vo


def embed_query(query: str):
    """1024-dim query embedding, with shared backoff (interactive: 2 min cap)."""
    result = embed_texts(_client(), [query], input_type="query", max_wait=120)
    return result.embeddings[0]


def dense_search(cur, query: str, n: int = 50, job_ids=None):
    """Return [(chunk_id, rank_position)] for the top-N nearest chunks."""
    qvec = embed_query(query)
    qstr = "[" + ",".join(f"{x:.8f}" for x in qvec) + "]"
    job_filter = "WHERE c.job_id = ANY(%s)" if job_ids is not None else ""
    params = ([list(job_ids)] if job_ids is not None else []) + [qstr, n]
    cur.execute(f"""
        SELECT c.chunk_id
        FROM chunk_embeddings e
        JOIN chunks c ON c.chunk_id = e.chunk_id
        {job_filter}
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s
    """, params)
    return [(cid, i + 1) for i, (cid,) in enumerate(cur.fetchall())]

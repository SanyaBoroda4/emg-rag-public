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

from ingest.voyage_util import EMBED_MODEL, embed_texts
from retrieval.tracing import span

_vo = None


def _client():
    global _vo
    if _vo is None:
        _vo = voyageai.Client()
    return _vo


def embed_query(query: str):
    """1024-dim query embedding, with shared backoff (interactive: 2 min cap)."""
    with span("embed_query", as_type="embedding", input=query,
              metadata={"model": EMBED_MODEL}) as s:
        result = embed_texts(_client(), [query], input_type="query",
                             max_wait=120)
        try:
            s.update(usage={"input": int(result.total_tokens)})
        except Exception:
            pass
    return result.embeddings[0]


def dense_search(cur, query: str, n: int = 50, job_ids=None):
    """Return [(chunk_id, rank_position)] for the top-N nearest chunks."""
    return dense_search_vec(cur, embed_query(query), n=n, job_ids=job_ids,
                            query=query)


def dense_search_vec(cur, qvec, n: int = 50, job_ids=None, query=None):
    """Same as dense_search but with a precomputed query vector — the eval
    harness embeds all golden questions in ONE Voyage call (rate limits)."""
    with span("dense", as_type="retriever", input=query,
              metadata={"n": n, "job_filter": None if job_ids is None
                        else len(job_ids), "index": "exact scan"}) as s:
        ranked = _dense_search_vec(cur, qvec, n, job_ids)
        s.update(output={"chunk_ids": [cid for cid, _ in ranked]})
    return ranked


def _dense_search_vec(cur, qvec, n, job_ids):
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

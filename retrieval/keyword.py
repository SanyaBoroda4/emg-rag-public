"""BM25-style keyword lane over chunks.fts (Postgres full-text search).

This lane exists for bare identifiers — invoice numbers ("6470"), surnames
("Zegers"), material names ("Calacatta") — where dense retrieval is weakest.

Query strategy: websearch_to_tsquery first (AND semantics, handles quoted
phrases); if that returns nothing, retry with OR semantics so partial matches
still surface. Ranked by ts_rank_cd.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrieval.tracing import span


def keyword_search(cur, query: str, n: int = 50, job_ids=None):
    """Return [(chunk_id, rank_position)] for the top-N keyword matches.

    job_ids: optional list restricting the search (used by the hybrid route).
    """
    with span("bm25", as_type="retriever", input=query,
              metadata={"n": n, "job_filter": None if job_ids is None
                        else len(job_ids)}) as s:
        ranked = _keyword_search(cur, query, n, job_ids)
        s.update(output={"attempt": "and" if ranked and ranked[0][2] == 0
                         else "or" if ranked else "none",
                         "chunk_ids": [cid for cid, _, _ in ranked]})
    return [(cid, rank) for cid, rank, _ in ranked]


def _keyword_search(cur, query, n, job_ids):
    """Returns [(chunk_id, rank, attempt_index)]."""
    terms = [t for t in query.split() if t.strip()]
    if not terms:
        return []
    attempts = [query, " OR ".join(terms)] if len(terms) > 1 else [query]

    job_filter = "AND c.job_id = ANY(%s)" if job_ids is not None else ""
    for k, attempt in enumerate(attempts):
        params = [attempt]
        if job_ids is not None:
            params.append(list(job_ids))
        params.append(n)
        cur.execute(f"""
            SELECT c.chunk_id
            FROM chunks c,
                 websearch_to_tsquery('english', %s) q
            WHERE c.fts @@ q {job_filter}
            ORDER BY ts_rank_cd(c.fts, q) DESC, c.chunk_id
            LIMIT %s
        """, params)
        rows = cur.fetchall()
        if rows:
            return [(cid, i + 1, k) for i, (cid,) in enumerate(rows)]
    return []

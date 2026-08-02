"""BM25-style keyword lane over chunks.fts (Postgres full-text search).

This lane exists for bare identifiers — invoice numbers ("6470"), surnames
("Zegers"), material names ("Calacatta") — where dense retrieval is weakest.

Query strategy: websearch_to_tsquery first (AND semantics, handles quoted
phrases); if that returns nothing, retry with OR semantics so partial matches
still surface. Ranked by ts_rank_cd.
"""


def keyword_search(cur, query: str, n: int = 50, job_ids=None):
    """Return [(chunk_id, rank_position)] for the top-N keyword matches.

    job_ids: optional list restricting the search (used by the hybrid route).
    """
    terms = [t for t in query.split() if t.strip()]
    if not terms:
        return []
    attempts = [query, " OR ".join(terms)] if len(terms) > 1 else [query]

    job_filter = "AND c.job_id = ANY(%s)" if job_ids is not None else ""
    for attempt in attempts:
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
            return [(cid, i + 1) for i, (cid,) in enumerate(rows)]
    return []

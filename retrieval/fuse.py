"""Reciprocal Rank Fusion of the keyword and dense lanes.

score(chunk) = sum over lanes of 1 / (k + rank), k=60. Purely position-based:
raw BM25 scores and cosine distances live on incomparable scales and are
never mixed. Provenance (which lane found the chunk, at what rank) is kept on
every candidate — WO5 eval debugging needs it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrieval.tracing import span

K = 60


def rrf_fuse(bm25_ranked, dense_ranked, n: int = 50):
    """Fuse two [(chunk_id, rank)] lists into top-N candidates.

    Returns a list of dicts sorted by fused score desc:
      {chunk_id, score, bm25_rank (or None), dense_rank (or None)}
    """
    with span("fuse", input={"bm25": len(bm25_ranked),
                             "dense": len(dense_ranked)},
              metadata={"k": K, "n": n}) as s:
        fused = _rrf_fuse(bm25_ranked, dense_ranked, n)
        s.update(output=[{"chunk_id": c["chunk_id"],
                          "rrf": round(c["score"], 5),
                          "bm25_rank": c["bm25_rank"],
                          "dense_rank": c["dense_rank"]} for c in fused])
    return fused


def _rrf_fuse(bm25_ranked, dense_ranked, n):
    cand = {}
    for cid, rank in bm25_ranked:
        c = cand.setdefault(cid, {"chunk_id": cid, "score": 0.0,
                                  "bm25_rank": None, "dense_rank": None})
        c["bm25_rank"] = rank
        c["score"] += 1.0 / (K + rank)
    for cid, rank in dense_ranked:
        c = cand.setdefault(cid, {"chunk_id": cid, "score": 0.0,
                                  "bm25_rank": None, "dense_rank": None})
        c["dense_rank"] = rank
        c["score"] += 1.0 / (K + rank)
    fused = sorted(cand.values(),
                   key=lambda c: (-c["score"], c["chunk_id"]))
    return fused[:n]

"""Cross-encoder reranking of the fused candidate list.

Backends (RERANK_BACKEND env var):
  * "local"  — cross-encoder/ms-marco-MiniLM-L-6-v2 via sentence-transformers,
    CPU-only, ~90 MB weights. Chosen over bge-reranker-base (1.1 GB) because
    the host has ~1 GiB free and runs live production containers. The model is
    loaded ONCE per process (module-level singleton), never per request.
  * "voyage" — Voyage rerank-2.5-lite API. The fallback if the local model's
    resident footprint breaches the ~400 MiB budget (measured at deploy time
    by scripts/measure_reranker.py), or wherever torch isn't installed.
  * RERANK_ENABLED=0 disables reranking entirely (fused order passes through)
    so WO5 evals can measure the reranker's contribution.

Returns the top-N candidates (default 6) with a `rerank_score` added;
provenance fields from fusion are preserved.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RERANK_ENABLED = os.environ.get("RERANK_ENABLED", "1") == "1"
RERANK_BACKEND = os.environ.get("RERANK_BACKEND", "local")
LOCAL_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
VOYAGE_MODEL = "rerank-2.5-lite"

_local_model = None
_vo = None


def _get_local():
    global _local_model
    if _local_model is None:
        from sentence_transformers import CrossEncoder
        _local_model = CrossEncoder(LOCAL_MODEL, max_length=512, device="cpu")
    return _local_model


def _rerank_local(query, candidates, texts):
    model = _get_local()
    scores = model.predict([(query, t) for t in texts], batch_size=16,
                           show_progress_bar=False)
    for cand, score in zip(candidates, scores):
        cand["rerank_score"] = float(score)


def _rerank_voyage(query, candidates, texts):
    global _vo
    import voyageai
    from ingest.voyage_util import retry_voyage
    if _vo is None:
        _vo = voyageai.Client()
    result = retry_voyage(
        lambda: _vo.rerank(query, texts, model=VOYAGE_MODEL), max_wait=120)
    for item in result.results:
        candidates[item.index]["rerank_score"] = float(item.relevance_score)


def rerank(cur, query: str, candidates: list, n: int = 6):
    """Rerank fused candidates (dicts with chunk_id) and return the top-N."""
    if not candidates:
        return []
    if not RERANK_ENABLED:
        return candidates[:n]

    ids = [c["chunk_id"] for c in candidates]
    cur.execute(
        "SELECT chunk_id, coalesce(context_text, '') || E'\\n' || raw_text "
        "FROM chunks WHERE chunk_id = ANY(%s)", (ids,))
    text_by_id = dict(cur.fetchall())
    texts = [text_by_id[c["chunk_id"]] for c in candidates]

    if RERANK_BACKEND == "voyage":
        _rerank_voyage(query, candidates, texts)
    else:
        _rerank_local(query, candidates, texts)

    ranked = sorted(candidates, key=lambda c: -c.get("rerank_score", 0.0))
    return ranked[:n]

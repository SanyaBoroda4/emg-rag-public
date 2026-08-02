"""End-to-end query CLI: python3 scripts/query.py "your question"

Prints the route (with reason), the SQL if any, the top chunks with lane
provenance and rerank scores, the grounded answer, per-stage latency, and
API cost. The eyeball tool until WO5's evals exist.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.db import get_conn
from retrieval.answer import generate_answer, load_chunk_rows
from retrieval.dense import dense_search
from retrieval.fuse import rrf_fuse
from retrieval.keyword import keyword_search
from retrieval.rerank import rerank
from retrieval.router import route_query
from retrieval.sql_lane import run_structured

# $/MTok (in, out). Sonnet 5 at intro pricing through 2026-08-31.
PRICES = {"claude-haiku-4-5": (1.0, 5.0), "claude-sonnet-5": (2.0, 10.0)}


class Stopwatch:
    def __init__(self):
        self.stages = []

    def stage(self, name, t0):
        self.stages.append((name, time.perf_counter() - t0))


def cost_of(model, usage):
    inp, out = PRICES.get(model, (0, 0))
    return (usage.input_tokens * inp + usage.output_tokens * out) / 1e6


def retrieve(cur, question, watch, job_ids=None):
    t0 = time.perf_counter()
    bm25 = keyword_search(cur, question, job_ids=job_ids)
    watch.stage("bm25", t0)
    t0 = time.perf_counter()
    dense = dense_search(cur, question, job_ids=job_ids)
    watch.stage("dense", t0)
    t0 = time.perf_counter()
    fused = rrf_fuse(bm25, dense)
    top = rerank(cur, question, fused, n=6)
    watch.stage("fuse+rerank", t0)
    return top


def print_candidates(cur, top):
    if not top:
        print("  (no chunks retrieved)")
        return
    cur.execute("SELECT chunk_id, job_id, left(raw_text, 90) FROM chunks "
                "WHERE chunk_id = ANY(%s)",
                ([c["chunk_id"] for c in top],))
    preview = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    for c in top:
        jid, txt = preview.get(c["chunk_id"], ("?", ""))
        prov = (f"bm25#{c['bm25_rank']}" if c["bm25_rank"] else "") + \
               ("+" if c["bm25_rank"] and c["dense_rank"] else "") + \
               (f"dense#{c['dense_rank']}" if c["dense_rank"] else "")
        score = c.get("rerank_score")
        score_s = f" rerank={score:.3f}" if score is not None else ""
        txt_disp = txt.replace("\r\n", " / ").replace("\n", " / ")
        print(f"  chunk {c['chunk_id']} job {jid} [{prov} "
              f"rrf={c['score']:.4f}{score_s}]  {txt_disp}")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python3 scripts/query.py \"your question\"")
        return 2
    question = " ".join(sys.argv[1:])
    watch = Stopwatch()
    total_cost = 0.0
    t_all = time.perf_counter()

    t0 = time.perf_counter()
    decision, usage = route_query(question)
    watch.stage("router", t0)
    total_cost += cost_of("claude-haiku-4-5", usage)
    route = decision["route"]
    print(f"ROUTE: {route} — {decision['reason']}")

    if route == "refuse":
        print("\nANSWER: This system only answers questions about EMG's "
              "job-tracking and invoicing data; that question is outside it.")
        print(f"\nlatency: " + ", ".join(
            f"{n} {s * 1000:.0f}ms" for n, s in watch.stages))
        print(f"cost: ${total_cost:.4f}")
        return 0

    sql_result = None
    chunk_rows = []
    with get_conn() as conn, conn.cursor() as cur:
        if route in ("structured", "hybrid"):
            t0 = time.perf_counter()
            try:
                sql_result = run_structured(question,
                                            hybrid=(route == "hybrid"))
            except Exception as e:
                print(f"\nSQL lane failed ({type(e).__name__}): {e}")
                print("falling back to semantic retrieval")
                sql_result = None
                route = "semantic" if route == "structured" else route
            watch.stage("sql", t0)
            if sql_result:
                for u in sql_result["usages"]:
                    total_cost += cost_of("claude-sonnet-5", u)
                print(f"\nSQL:\n{sql_result['sql']}")
                print(f"rows: {sql_result['row_count']}")
                for r in sql_result["rows"][:10]:
                    print(f"  {tuple(r)}")
                if sql_result["row_count"] > 10:
                    print(f"  ... ({sql_result['row_count'] - 10} more)")

        if route == "semantic" or route == "hybrid":
            job_ids = None
            if route == "hybrid" and sql_result:
                try:
                    idx = sql_result["columns"].index("job_id")
                    job_ids = sorted({r[idx] for r in sql_result["rows"]
                                      if r[idx] is not None})
                except ValueError:
                    job_ids = None
                if job_ids is not None:
                    print(f"\nhybrid: restricting retrieval to "
                          f"{len(job_ids)} job(s) from SQL")
                    if not job_ids:
                        job_ids = None  # empty set -> fall back to open search
            top = retrieve(cur, question, watch, job_ids=job_ids)
            print("\nTOP CHUNKS:")
            print_candidates(cur, top)
            chunk_rows = load_chunk_rows(cur, [c["chunk_id"] for c in top])

        t0 = time.perf_counter()
        answer, usage = generate_answer(question, chunk_rows=chunk_rows,
                                        sql_result=sql_result)
        watch.stage("answer", t0)
        from retrieval.answer import ANSWER_MODEL
        total_cost += cost_of(ANSWER_MODEL, usage)

    print(f"\nANSWER:\n{answer}")
    print(f"\nlatency: " + ", ".join(
        f"{n} {s * 1000:.0f}ms" for n, s in watch.stages) +
        f" | total {(time.perf_counter() - t_all) * 1000:.0f}ms")
    print(f"cost: ${total_cost:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

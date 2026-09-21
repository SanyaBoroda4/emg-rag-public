"""End-to-end query CLI: python3 scripts/query.py "your question"

Prints the route (with reason), the SQL if any, the top chunks with lane
provenance and rerank scores, the grounded answer, per-stage latency, and
API cost. Since WO16 this is a printer over retrieval.pipeline.ask(); the
output format is unchanged.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrieval.pipeline import ask
from retrieval.tracing import flush


def print_candidates(chunks):
    if not chunks:
        print("  (no chunks retrieved)")
        return
    for c in chunks:
        txt = c.raw[:90] + (" [BOT]" if c.is_bot else "")
        prov = (f"bm25#{c.bm25_rank}" if c.bm25_rank else "") + \
               ("+" if c.bm25_rank and c.dense_rank else "") + \
               (f"dense#{c.dense_rank}" if c.dense_rank else "")
        score_s = (f" rerank={c.rerank_score:.3f}"
                   if c.rerank_score is not None else "")
        txt_disp = txt.replace("\r\n", " / ").replace("\n", " / ")
        print(f"  chunk {c.chunk_id} job {c.job_id} [{prov} "
              f"rrf={c.rrf:.4f}{score_s}]  {txt_disp}")


def print_result(r):
    print(f"ROUTE: {r.route} — {r.route_reason}")
    lat = ", ".join(f"{n} {s * 1000:.0f}ms" for n, s in r.latency)
    if r.route == "refuse":
        print(f"\nANSWER: {r.answer}")
        print(f"\nlatency: " + lat)
        print(f"cost: ${r.cost_usd:.4f}")
        return
    if r.sql_error:
        print(f"\nSQL lane failed ({r.sql_error_type}): {r.sql_error}")
        print("falling back to semantic retrieval")
    if r.sql:
        print(f"\nSQL:\n{r.sql}")
        print(f"rows: {r.row_count}")
        for row in r.rows[:10]:
            print(f"  {tuple(row)}")
        if r.row_count > 10:
            print(f"  ... ({r.row_count - 10} more)")
    if r.route_used in ("semantic", "hybrid"):
        if r.hybrid_restrict_n is not None:
            print(f"\nhybrid: restricting retrieval to "
                  f"{r.hybrid_restrict_n} job(s) from SQL")
        print("\nTOP CHUNKS:")
        print_candidates(r.chunks)
    print(f"\nANSWER:\n{r.answer}")
    print(f"\nlatency: " + lat + f" | total {r.latency_ms}ms")
    print(f"cost: ${r.cost_usd:.4f}")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python3 scripts/query.py \"your question\"")
        return 2
    question = " ".join(sys.argv[1:])
    try:
        # One Langfuse trace per question (no-op without keys); flush before
        # exit or a short CLI run loses the batched events.
        print_result(ask(question))
        return 0
    finally:
        flush()


if __name__ == "__main__":
    sys.exit(main())

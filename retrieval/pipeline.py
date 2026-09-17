"""The question pipeline as a function (WO16).

ask(question) runs exactly what scripts/query.py ran inline before WO16 —
router -> SQL lane and/or hybrid retrieval -> grounded answer — inside one
Langfuse trace, and returns everything as data instead of printing it. The
CLI and the HTTP API are both thin layers over this.

No retrieval, prompt, model or view logic lives here; it only sequences the
existing stage functions and collects their outputs.
"""

import os
import time
from dataclasses import dataclass, field

from ingest.db import get_conn
from retrieval.answer import ANSWER_MODEL, generate_answer, load_chunk_rows
from retrieval.dense import dense_search
from retrieval.fuse import rrf_fuse
from retrieval.keyword import keyword_search
from retrieval.pricing import cost_of
from retrieval.rerank import rerank
from retrieval.router import ROUTER_MODEL, route_query
from retrieval.sql_lane import SQL_MODEL, run_structured
from retrieval.tracing import git_sha, trace

AS_OF = "2026-07-30"  # the frozen snapshot every answer describes

REFUSAL = ("This system only answers questions about EMG's job-tracking and "
           "invoicing data; that question is outside it.")


@dataclass
class Chunk:
    chunk_id: int
    job_id: int
    job_name: str
    context: str
    raw: str
    is_bot: bool
    bm25_rank: int | None
    dense_rank: int | None
    rrf: float
    rerank_score: float | None


@dataclass
class AskResult:
    question: str
    route: str                      # what the router chose
    route_used: str                 # after a SQL-lane fallback, if any
    route_reason: str
    answer: str
    sql: str | None = None
    sql_error_type: str | None = None
    sql_error: str | None = None
    columns: list[str] | None = None
    rows: list[tuple] = field(default_factory=list)
    row_count: int | None = None
    hybrid_restrict_n: int | None = None   # jobs the SQL lane narrowed to
    chunks: list[Chunk] = field(default_factory=list)
    latency: list[tuple[str, float]] = field(default_factory=list)  # (stage, s)
    latency_ms: int = 0
    cost_usd: float = 0.0
    trace_id: str | None = None
    # conversational path only (WO17): what the user typed vs what was answered
    original_question: str | None = None
    standalone: bool = True
    rewritten_question: str | None = None
    rewrite_reason: str = ""
    rewrite_latency_ms: int = 0
    rewrite_cost_usd: float = 0.0
    history_turns: int = 0


def _meta(entry_point):
    return {"entry_point": entry_point, "git_sha": git_sha(),
            "router_model": ROUTER_MODEL, "sql_model": SQL_MODEL,
            "answer_model": ANSWER_MODEL,
            "rerank_backend": os.environ.get("RERANK_BACKEND", "local")}


def ask(question: str, *, session_id=None, user_id=None, tags=("cli",),
        entry_point="query_cli") -> AskResult:
    """Answer one question end to end inside one Langfuse trace."""
    with trace(entry_point, input=question, metadata=_meta(entry_point),
               tags=list(tags), session_id=session_id,
               user_id=user_id) as root:
        res = _ask(question, root)
        res.trace_id = root.trace_id
        return res


def ask_conversational(question: str, history, *, session_id=None,
                       user_id=None, tags=("ui",),
                       entry_point="ui") -> AskResult:
    """WO17: the UI path. Same trace as ask(); one extra `rewrite` span
    before the router. `history` is a list of retrieval.rewrite.Turn (the
    last <= 3 completed turns of this conversation for this user). The
    pipeline itself still runs on exactly one question — the rewritten one
    when the rewriter decided the question was a follow-up, the verbatim
    question otherwise."""
    from retrieval.rewrite import rewrite  # local import: CLI/eval never load it
    with trace(entry_point, input=question, metadata=_meta(entry_point),
               tags=list(tags), session_id=session_id,
               user_id=user_id) as root:
        rw = rewrite(question, history)
        res = _ask(rw.question, root)
        res.trace_id = root.trace_id
        res.original_question = question
        res.standalone = rw.standalone
        res.rewritten_question = None if rw.standalone else rw.question
        res.rewrite_reason = rw.reason
        res.rewrite_latency_ms = rw.latency_ms
        res.rewrite_cost_usd = rw.cost_usd
        res.history_turns = rw.history_used
        res.latency_ms += rw.latency_ms
        res.cost_usd += rw.cost_usd
        root.update(metadata={
            "standalone": rw.standalone,
            "rewritten_question": res.rewritten_question,
            "history_turns": rw.history_used,
            "rewrite_reason": rw.reason[:300]})
        return res


def _ask(question, root) -> AskResult:
    stages = []
    cost = 0.0
    t_all = time.perf_counter()

    t0 = time.perf_counter()
    decision, usage = route_query(question)
    stages.append(("router", time.perf_counter() - t0))
    cost += cost_of(ROUTER_MODEL, usage)
    route = decision["route"]
    res = AskResult(question=question, route=route, route_used=route,
                    route_reason=decision["reason"], answer="")

    if route == "refuse":
        res.answer = REFUSAL
        res.latency, res.cost_usd = stages, cost
        res.latency_ms = round((time.perf_counter() - t_all) * 1000)
        root.update(output=res.answer, metadata={
            "route_predicted": route, "route_reason": decision["reason"],
            "total_cost_usd": round(cost, 5)})
        return res

    sql_result = None
    chunk_rows = []
    with get_conn() as conn, conn.cursor() as cur:
        if route in ("structured", "hybrid"):
            t0 = time.perf_counter()
            try:
                sql_result = run_structured(question,
                                            hybrid=(route == "hybrid"))
            except Exception as e:
                res.sql_error_type = type(e).__name__
                res.sql_error = str(e)
                sql_result = None
                route = "semantic" if route == "structured" else route
                res.route_used = route
            stages.append(("sql", time.perf_counter() - t0))
            if sql_result:
                for u in sql_result["usages"]:
                    cost += cost_of(SQL_MODEL, u)
                res.sql = sql_result["sql"]
                res.columns = list(sql_result["columns"])
                res.rows = [tuple(r) for r in sql_result["rows"]]
                res.row_count = sql_result["row_count"]

        if route in ("semantic", "hybrid"):
            job_ids = None
            if route == "hybrid" and sql_result:
                try:
                    idx = sql_result["columns"].index("job_id")
                    job_ids = sorted({r[idx] for r in sql_result["rows"]
                                      if r[idx] is not None})
                except ValueError:
                    job_ids = None
                if job_ids is not None:
                    res.hybrid_restrict_n = len(job_ids)
                    if not job_ids:
                        job_ids = None  # empty set -> fall back to open search
            t0 = time.perf_counter()
            bm25 = keyword_search(cur, question, job_ids=job_ids)
            stages.append(("bm25", time.perf_counter() - t0))
            t0 = time.perf_counter()
            dense = dense_search(cur, question, job_ids=job_ids)
            stages.append(("dense", time.perf_counter() - t0))
            t0 = time.perf_counter()
            fused = rrf_fuse(bm25, dense)
            top = rerank(cur, question, fused, n=6)
            stages.append(("fuse+rerank", time.perf_counter() - t0))
            chunk_rows = load_chunk_rows(cur, [c["chunk_id"] for c in top])
            by_id = {r[0]: r for r in chunk_rows}
            for c in top:
                r = by_id.get(c["chunk_id"])
                res.chunks.append(Chunk(
                    chunk_id=c["chunk_id"],
                    job_id=r[1] if r else None, job_name=r[2] if r else "",
                    context=r[3] if r else "", raw=r[4] if r else "",
                    is_bot=bool(r[5]) if r else False,
                    bm25_rank=c.get("bm25_rank"), dense_rank=c.get("dense_rank"),
                    rrf=c["score"], rerank_score=c.get("rerank_score")))

        t0 = time.perf_counter()
        answer, usage = generate_answer(question, chunk_rows=chunk_rows,
                                        sql_result=sql_result)
        stages.append(("answer", time.perf_counter() - t0))
        cost += cost_of(ANSWER_MODEL, usage)

    res.answer = answer
    res.latency, res.cost_usd = stages, cost
    res.latency_ms = round((time.perf_counter() - t_all) * 1000)
    root.update(output=answer, metadata={
        "route_predicted": decision["route"], "route_used": route,
        "route_reason": decision["reason"],
        "sql_error": (f"{res.sql_error_type}: {res.sql_error}"
                      if res.sql_error else None),
        "chunk_ids": [c.chunk_id for c in res.chunks],
        "total_cost_usd": round(cost, 5),
        "latency_s": {n: round(s, 3) for n, s in stages}})
    return res

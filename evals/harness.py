"""Shared eval harness: golden-set loading, per-question pipeline execution,
and the LLM judge.

Cost discipline:
  * Tier 1 (routing) makes one short Haiku router call per question — the
    same call production makes; there is nothing cheaper that still measures
    routing. (~$0.0006/question.)
  * Tier 2 (retrieval) makes NO Claude calls. All golden questions are
    embedded in ONE batched Voyage call (rate-limit friendly); reranking uses
    the Voyage rerank endpoint, same as production.
  * Tier 3 (generation + judge) is the only tier that spends real money.

Judge separation: the judge model is never the generator model. With
ANSWER_MODEL=haiku the judge is Sonnet, and vice versa. Every report records
the (generator, judge) pair — self-grading is worthless.
"""

import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic
import voyageai

from ingest.voyage_util import retry_voyage, EMBED_MODEL
from retrieval.answer import ANSWER_MODEL, generate_answer, load_chunk_rows
from retrieval.dense import dense_search_vec
from retrieval.fuse import rrf_fuse
from retrieval.keyword import keyword_search
from retrieval.rerank import rerank
from retrieval.router import route_query
from retrieval.sql_lane import SQL_MODEL, run_structured

GOLDEN_CSV = Path(__file__).resolve().parent / "golden_set.csv"

# $/MTok (in, out). Sonnet 5 at intro pricing through 2026-08-31.
PRICES = {"claude-haiku-4-5": (1.0, 5.0), "claude-sonnet-5": (2.0, 10.0)}


def cost_of(model, usage):
    inp, out = PRICES.get(model, (0, 0))
    return (usage.input_tokens * inp + usage.output_tokens * out) / 1e6


def judge_model_for(answer_model: str) -> str:
    return ("claude-sonnet-5" if "haiku" in answer_model
            else "claude-haiku-4-5")


def load_golden(path=GOLDEN_CSV, statuses=("verified", "draft", "FAILING")):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r["status"] not in statuses:
                continue  # 'retired' rows never run
            r["gold_ids"] = [int(x) for x in r["relevant_ids"].split(",")
                             if x.strip()]
            rows.append(r)
    return rows


def embed_questions(rows):
    """One batched Voyage call for every question -> {qid: vector}."""
    vo = voyageai.Client()
    texts = [r["question"] for r in rows]
    result = retry_voyage(
        lambda: vo.embed(texts, model=EMBED_MODEL, input_type="query"))
    return {r["id"]: emb for r, emb in zip(rows, result.embeddings)}


def run_retrieval(cur, question, qvec, job_ids=None, rerank_all=True):
    """All lanes for one question. Returns rankings + fused candidates.

    rerank_all=True reranks the full 50-candidate fused list so Tier-2
    metrics can score the complete post-rerank ordering (production returns
    the top 6 of the same ordering).
    """
    t0 = time.perf_counter()
    bm25 = keyword_search(cur, question, job_ids=job_ids)
    t_bm25 = time.perf_counter() - t0
    t0 = time.perf_counter()
    dense = dense_search_vec(cur, qvec, job_ids=job_ids)
    t_dense = time.perf_counter() - t0
    fused = rrf_fuse(bm25, dense)
    t0 = time.perf_counter()
    reranked = rerank(cur, question,
                      [dict(c) for c in fused],
                      n=len(fused) if rerank_all else 6)
    t_rerank = time.perf_counter() - t0
    return {
        "bm25": [cid for cid, _ in bm25],
        "dense": [cid for cid, _ in dense],
        "fused": [c["chunk_id"] for c in fused],
        "reranked": [c["chunk_id"] for c in reranked],
        "candidates": reranked,   # dicts with provenance + rerank_score
        "latency": {"bm25": t_bm25, "dense": t_dense, "rerank": t_rerank},
    }


def run_generation(cur, row, retrieval, predicted_route,
                   answer_model=None, sql_model=None):
    """Mirror scripts/query.py: SQL lane and/or chunks -> grounded answer.

    Drives the pipeline with the *predicted* route (what production would
    do), so routing mistakes surface as end-to-end failures instead of being
    quietly corrected by the gold label.
    """
    record = {"sql": None, "sql_error": None, "row_count": None,
              "sql_columns": None, "sql_rows": None,
              "chunk_ids": [], "answer": None, "cost": 0.0, "latency": {}}
    route = predicted_route
    sql_result = None

    if route == "refuse":
        record["answer"] = ("This system only answers questions about EMG's "
                            "job-tracking and invoicing data; that question "
                            "is outside it.")
        return record

    if route in ("structured", "hybrid"):
        t0 = time.perf_counter()
        try:
            sql_result = run_structured(row["question"],
                                        hybrid=(route == "hybrid"),
                                        model=sql_model)
            record["sql"] = sql_result["sql"]
            record["row_count"] = sql_result["row_count"]
            record["sql_columns"] = sql_result["columns"]
            record["sql_rows"] = [tuple(r) for r in sql_result["rows"][:50]]
            for u in sql_result["usages"]:
                record["cost"] += cost_of(sql_model or SQL_MODEL, u)
        except Exception as e:
            record["sql_error"] = f"{type(e).__name__}: {e}"
            route = "semantic" if route == "structured" else route
        record["latency"]["sql"] = time.perf_counter() - t0

    chunk_rows = []
    if route in ("semantic", "hybrid"):
        top6 = retrieval["candidates"][:6]
        record["chunk_ids"] = [c["chunk_id"] for c in top6]
        chunk_rows = load_chunk_rows(cur, record["chunk_ids"])

    t0 = time.perf_counter()
    answer, usage = generate_answer(row["question"], chunk_rows=chunk_rows,
                                    sql_result=sql_result, model=answer_model)
    record["latency"]["answer"] = time.perf_counter() - t0
    record["cost"] += cost_of(answer_model or ANSWER_MODEL, usage)
    record["answer"] = answer
    return record


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "faithful": {"type": "boolean"},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "correct": {"type": "boolean"},
        "useful_chunk_ids": {"type": "array", "items": {"type": "integer"}},
        "declined": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["faithful", "unsupported_claims", "correct",
                 "useful_chunk_ids", "declined", "reason"],
    "additionalProperties": False,
}

JUDGE_SYSTEM = """You are grading a RAG system's answer about a countertop company's data. You are given the question, the expected answer (ground truth), the evidence the system retrieved (note chunks and/or a SQL result), and the system's answer.

Score strictly:
- faithful: true only if EVERY claim in the answer is supported by the supplied evidence. List unsupported claims.
- correct: true only if the answer's substance matches the expected answer (paraphrase is fine; wrong/missing facts are not).
- useful_chunk_ids: the ids of retrieved chunks that actually contain information used to answer this question (empty list if none / no chunks given).
- declined: true if the answer refuses or says the data cannot answer the question.
Respond with JSON only."""


def judge_answer(row, record, chunk_rows, judge_model):
    """One judge call scoring faithfulness, correctness, context precision,
    and refusal. Returns (verdict_dict, cost)."""
    client = anthropic.Anthropic()
    # The judge must see the same SQL evidence the generator saw — a row
    # COUNT alone made it brand row-derived claims as fabrications (WO7).
    ev = []
    if record["sql"]:
        rows_disp = "\n".join(str(r) for r in (record.get("sql_rows") or []))
        more = ("" if not record["row_count"]
                or record["row_count"] <= len(record.get("sql_rows") or [])
                else f"\n... ({record['row_count']} rows total)")
        ev.append(f"SQL executed:\n{record['sql']}\n"
                  f"columns: {record.get('sql_columns')}\n"
                  f"rows:\n{rows_disp}{more}")
    for cid, jid, jname, ctx, raw, is_bot in chunk_rows:
        tag = " [AUTOMATED SYSTEM RECORD]" if is_bot else ""
        ev.append(f"[chunk {cid}, job {jid}]{tag}\n{ctx}\n{raw[:400]}")
    prompt = (f"Question: {row['question']}\n\n"
              f"Expected answer (ground truth): {row['expected_answer']}\n\n"
              f"Evidence retrieved:\n\n" + ("\n\n".join(ev) or "(none)") +
              f"\n\nSystem's answer:\n{record['answer']}")
    # max_tokens must cover adaptive thinking (Sonnet 5 thinks by default and
    # can consume a small budget entirely, leaving no text block).
    cost = 0.0
    for attempt in range(2):
        resp = client.messages.create(
            model=judge_model, max_tokens=4000, system=JUDGE_SYSTEM,
            output_config={"format": {"type": "json_schema",
                                      "schema": JUDGE_SCHEMA}},
            messages=[{"role": "user", "content": prompt}])
        cost += cost_of(judge_model, resp.usage)
        text = next((b.text for b in resp.content if b.type == "text"), "")
        if text:
            try:
                return json.loads(text), cost
            except json.JSONDecodeError:
                pass
    return {"faithful": None, "correct": None, "useful_chunk_ids": [],
            "declined": False,
            "reason": f"judge returned no parseable verdict "
                      f"(stop_reason={resp.stop_reason})"}, cost


def run_router(row):
    """Tier-1 unit: returns (predicted_route, reason, cost)."""
    decision, usage = route_query(row["question"])
    return decision["route"], decision["reason"], \
        cost_of("claude-haiku-4-5", usage)


def git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def run_metadata(extra=None):
    meta = {
        "git_sha": git_sha(),
        "answer_model": os.environ.get("ANSWER_MODEL", ANSWER_MODEL),
        "sql_model": os.environ.get("SQL_MODEL", SQL_MODEL),
        "router_model": "claude-haiku-4-5",
        "rerank_backend": os.environ.get("RERANK_BACKEND", "local"),
        "rerank_enabled": os.environ.get("RERANK_ENABLED", "1"),
        "embed_model": EMBED_MODEL,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if extra:
        meta.update(extra)
    return meta

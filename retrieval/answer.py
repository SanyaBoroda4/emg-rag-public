"""Grounded answer generation with citations.

Every claim must trace to a [chunk N / job M] citation or to the SQL result
set. The model is instructed to refuse honestly when the retrieved context
does not answer the question — inventing is the failure mode we test for.

Faithfulness rule (this WO): the answer must never volunteer schema-level
statistics that are not in the retrieved evidence. The old baked-in caveat
("44% of activities have no date") was true but absent from each query's
evidence, so the judge correctly branded it unfaithful (Q26, Q32-37). If the
evidence itself carries a caveat, relaying it is fine.

ANSWER_MODEL env var switches the model (default Haiku) — WO5 benchmarks
Haiku vs Sonnet on the golden set, so this is deliberately a one-line change.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic
from dotenv import load_dotenv

load_dotenv()

ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "claude-haiku-4-5")

SYSTEM_PROMPT = """You answer questions about a countertop fabrication company using ONLY the evidence supplied (retrieved note chunks and/or a SQL result set).

Rules:
- Ground every claim: cite note evidence as [chunk <id>, job <id>] and numeric/tabular claims as [SQL]. No uncited claims.
- If the evidence does not answer the question, say exactly that — briefly, stating what WAS found instead. NEVER invent names, numbers, dates, or events.
- State ONLY what the supplied evidence supports. Never volunteer background statistics about the dataset (e.g. what fraction of activities lack dates) unless they appear in this evidence — a true-but-unsupported claim is still an unsupported claim.
- When the SQL queries a curated business view (a status or pipeline column that directly encodes the asked-about state, e.g. status = 'quiet' for "went quiet after a quote"), that view's definition IS the company's definition. Answer directly from its rows; do not second-guess whether the definition matches the question's wording. Rows from such views are one-per-JOB, not activity records.
- Activity counts are ambiguous between pre-created placeholder rows and work that actually happened. When answering an activity-count question, say in one short clause which the number counts (e.g. "counting only dated, completed activities" or "counting all activity records including unscheduled placeholders"), based on what the SQL actually filtered.
- Notes marked [AUTOMATED SYSTEM RECORD] were written by bots (payment logging, stale-job reminders), not people. They are legitimate records, but describe them as automated system records — never present bot boilerplate as something a person observed or said.
- Be concise: answer first, evidence after."""


def _format_chunks(chunk_rows):
    parts = []
    for cid, jid, jname, ctx, raw, is_bot in chunk_rows:
        tag = " [AUTOMATED SYSTEM RECORD]" if is_bot else ""
        parts.append(f"[chunk {cid}, job {jid} \"{jname}\"]{tag}\n"
                     f"context: {ctx}\nnote: {raw}")
    return "\n\n".join(parts)


def load_chunk_rows(cur, chunk_ids):
    """Fetch display rows for the cited chunks, preserving input order.
    Rows are (chunk_id, job_id, job_name, context, raw, is_bot_generated)."""
    if not chunk_ids:
        return []
    cur.execute("""
        SELECT c.chunk_id, c.job_id, j.job_name, c.context_text, c.raw_text,
               c.is_bot_generated
        FROM chunks c JOIN jobs j ON j.job_id = c.job_id
        WHERE c.chunk_id = ANY(%s)
    """, (list(chunk_ids),))
    by_id = {r[0]: r for r in cur.fetchall()}
    return [by_id[cid] for cid in chunk_ids if cid in by_id]


def generate_answer(question: str, chunk_rows=None, sql_result=None,
                    model: str = None):
    """Returns (answer_text, usage). Supply chunks, SQL result, or both.
    `model` overrides ANSWER_MODEL (used by evals/benchmark_models.py)."""
    evidence = []
    if sql_result is not None:
        rows_disp = "\n".join(
            str(tuple(r)) for r in sql_result["rows"][:50])
        shown = min(50, len(sql_result["rows"]))
        more = ("" if sql_result["row_count"] <= shown
                else f"\n... ({shown} of {sql_result['row_count']} total "
                     f"matching rows shown — the TRUE total is "
                     f"{sql_result['row_count']})")
        evidence.append(
            f"SQL executed:\n{sql_result['sql']}\n"
            f"columns: {sql_result['columns']}\n"
            f"rows (true total {sql_result['row_count']}):\n"
            f"{rows_disp}{more}")
    if chunk_rows:
        evidence.append("Retrieved notes:\n\n" + _format_chunks(chunk_rows))
    if not evidence:
        evidence.append("(no evidence was retrieved)")

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model or ANSWER_MODEL, max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content":
                   f"Question: {question}\n\n" + "\n\n---\n\n".join(evidence)}])
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return text, resp.usage

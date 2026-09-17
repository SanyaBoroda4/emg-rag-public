"""Follow-up question rewriter (WO17).

Runs BEFORE the router, only in the conversational (UI) path. Given the last
few turns of a conversation and a new question, it either passes the
question through untouched (standalone) or rewrites it into a
self-contained question that the unchanged pipeline can answer on its own.

Design rules (see the WO17 report for the measured behaviour):
  * standalone questions are returned VERBATIM — the pipeline stays a pure
    function of one question, so every existing eval and its determinism
    hold; the flag is the model's, the text is never the model's;
  * with no history, or when the previous turn was a refuse, no model call
    is made at all: the question is standalone by rule;
  * the model sees, per prior turn, the question, the standalone question
    it resolved to, the route, the answer (<= 600 chars) and the SQL —
    never the rows;
  * Haiku 4.5 at temperature 0 with a JSON schema; any failure fails OPEN
    (standalone, verbatim) so a rewriter outage never blocks an answer.
"""

import json
import os
import time
from dataclasses import dataclass, field

import anthropic
from dotenv import load_dotenv

from retrieval.pricing import cost_of
from retrieval.tracing import generation

load_dotenv()

REWRITE_MODEL = os.environ.get("REWRITE_MODEL", "claude-haiku-4-5")
MAX_HISTORY = 3
ANSWER_CHARS = 600


@dataclass
class Turn:
    question: str
    standalone_question: str
    route: str
    answer: str
    sql: str | None = None


@dataclass
class RewriteResult:
    standalone: bool
    question: str
    cost_usd: float = 0.0
    latency_ms: int = 0
    reason: str = ""
    history_used: int = 0


SYSTEM_PROMPT = """You rewrite follow-up questions in a conversation with a question-answering system over a countertop company's job-tracking and invoicing data. You do NOT answer questions. You output JSON only.

You are given the previous turns of the conversation (each with the question as typed, the self-contained question it was resolved to, the route the system took, the answer it gave, and the SQL if any) and the user's NEW question.

Decide whether the new question stands on its own.

- If it stands on its own, return {"standalone": true, "question": "<the new question, unchanged>", "reason": "..."}. Err on the side of standalone: a wrong rewrite is worse than no rewrite. A question that names its own subject, place, person, crew, year or metric is standalone even if the topic continues.
- Otherwise return {"standalone": false, "question": "<one self-contained question>", "reason": "..."} that resolves ONLY:
  * pronouns and deixis ("those", "that salesperson", "she", "the same", "the two");
  * elided filters ("and in 2025?", "what about Mount Pleasant?", "and Summerville?") — start from the MOST RECENT turn's resolved question and keep every one of its filters (person, crew, place, year, month, status, metric) that the new question does not replace;
  * comparatives ("more than last time", "which was higher?", "is that more than X's?") — the rewrite must ask for the COMPARISON and name BOTH sides, e.g. "Is Ivan Andreev's average job size in the first half of 2026 larger than Leo's?" — never just ask for the second side.
- Never invent a filter, entity, year or metric that the history does not contain. Keep the user's wording where you can; write the rewrite the way the user would have typed the full question.
- Never copy numbers, totals or answers from the history into the rewrite ("West Ashley with 603 jobs" is wrong; "West Ashley or Summerville" is right) — the system will look the numbers up itself.
- If the new question is ambiguous between two readings, pick the reading closest to the previous turn's topic and make it explicit in the rewrite, so the user can see and correct it.
- Only the history shown exists. Do not use anything else."""

SCHEMA = {
    "type": "object",
    "properties": {
        "standalone": {"type": "boolean"},
        "question": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["standalone", "question", "reason"],
    "additionalProperties": False,
}


def format_history(history) -> str:
    turns = list(history)[-MAX_HISTORY:]
    parts = []
    for i, t in enumerate(turns, 1):
        ans = (t.answer or "").strip().replace("\r", "")
        if len(ans) > ANSWER_CHARS:
            ans = ans[:ANSWER_CHARS] + "…"
        block = (f"Turn {i}\n  user asked: {t.question}\n"
                 f"  resolved to: {t.standalone_question or t.question}\n"
                 f"  route: {t.route}\n  answer: {ans or '(none)'}")
        if t.sql:
            block += f"\n  SQL: {t.sql}"
        parts.append(block)
    return "\n\n".join(parts)


def build_prompt(question, history) -> str:
    return (f"Previous turns:\n\n{format_history(history)}\n\n"
            f"NEW question: {question}\n\nJSON:")


def _call_model(prompt):
    """One Haiku call. Returns (parsed dict or None, usage)."""
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=REWRITE_MODEL, max_tokens=400, temperature=0,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}])
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return json.loads(text), resp.usage
    except json.JSONDecodeError:
        return None, resp.usage


def rewrite(question: str, history, *, call=None) -> RewriteResult:
    """Return the question to send to the pipeline. `call(prompt)` may be
    injected (tests use recorded fixtures instead of the model)."""
    question = (question or "").strip()
    turns = [t for t in (history or []) if t is not None][-MAX_HISTORY:]
    if not turns:
        return RewriteResult(True, question, reason="no history")
    if turns[-1].route == "refuse":
        return RewriteResult(True, question, reason="previous turn was a refuse",
                             history_used=len(turns))
    prompt = build_prompt(question, turns)
    t0 = time.perf_counter()
    with generation("rewrite", model=REWRITE_MODEL, input=prompt,
                    metadata={"history_turns": len(turns),
                              "temperature": 0}) as g:
        cost = 0.0
        try:
            if call is not None:
                parsed, usage = call(prompt), None
            else:
                parsed, usage = _call_model(prompt)
                cost = cost_of(REWRITE_MODEL, usage)
        except Exception as e:  # fail open: never block an answer
            g.update(output={"standalone": True, "fail_open": str(e)[:200]},
                     level="WARNING", status_message=f"rewriter failed open: {e}")
            return RewriteResult(True, question, cost, 0,
                                 reason=f"rewriter error, passed through: "
                                        f"{type(e).__name__}",
                                 history_used=len(turns))
        ms = round((time.perf_counter() - t0) * 1000)
        if not parsed or not isinstance(parsed.get("standalone"), bool):
            g.update(output={"standalone": True, "fail_open": "unparseable"},
                     level="WARNING", usage=usage, cost=cost)
            return RewriteResult(True, question, cost, ms,
                                 reason="unparseable verdict, passed through",
                                 history_used=len(turns))
        text = (parsed.get("question") or "").strip()
        if parsed["standalone"] or not text:
            res = RewriteResult(True, question, cost, ms,  # verbatim, always
                                reason=parsed.get("reason", ""),
                                history_used=len(turns))
        else:
            res = RewriteResult(False, text, cost, ms,
                                reason=parsed.get("reason", ""),
                                history_used=len(turns))
        g.update(output={"standalone": res.standalone, "question": res.question,
                         "reason": res.reason}, usage=usage, cost=cost)
        return res

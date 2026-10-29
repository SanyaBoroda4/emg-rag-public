"""Conversation tier (WO17): run golden_conversations.csv turn by turn,
feeding REAL prior answers as history, through the same path the UI uses
(retrieval.pipeline.ask_conversational: rewrite -> ask).

    python evals/run_conversations.py            # all conversations
    python evals/run_eval.py --conversation      # same thing

Per turn: rewrite match (standalone flag correct; for follow-ups the
rewritten text judged equivalent to the expected standalone by the Sonnet
judge, yes/no), route match, answer correctness (numeric match for
structured rows, the existing judge otherwise, declined for refuse).
Scores are reported for `verified` and `draft` rows separately - draft
keys do not count until Alex verifies them.

Writes evals/results/YYYY-MM-DD-HHMM-conv.json.
"""

import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic  # noqa: E402

from evals import metrics  # noqa: E402
from evals.harness import (ANSWER_MODEL, judge_answer, judge_model_for,  # noqa: E402
                           load_chunk_rows, run_metadata)
from ingest.db import get_conn  # noqa: E402
from retrieval import tracing  # noqa: E402
from retrieval.pipeline import ask_conversational  # noqa: E402
from retrieval.pricing import cost_of  # noqa: E402
from retrieval.rewrite import Turn  # noqa: E402

GOLD = Path(__file__).resolve().parent / "golden_conversations.csv"
RESULTS = Path(__file__).resolve().parent / "results"

EQUIV_SCHEMA = {"type": "object",
                "properties": {"equivalent": {"type": "boolean"},
                               "reason": {"type": "string"}},
                "required": ["equivalent", "reason"],
                "additionalProperties": False}
EQUIV_SYSTEM = ("You compare two questions about a countertop company's job data. "
                "Answer whether they ask for the SAME thing: same entities, same "
                "filters (person, crew, place, year, month, status, metric), same "
                "comparison if any. Wording may differ. Extra detail that does not "
                "change the result (e.g. listing the job ids the phrase already "
                "denotes) is still equivalent; a missing or added filter is not. "
                "JSON only.")


def judge_equivalent(expected, actual, judge_model):
    client = anthropic.Anthropic()
    with tracing.generation("rewrite_judge", model=judge_model,
                            input={"expected": expected, "actual": actual}) as g:
        resp = client.messages.create(
            model=judge_model, max_tokens=1500, system=EQUIV_SYSTEM,
            output_config={"format": {"type": "json_schema",
                                      "schema": EQUIV_SCHEMA}},
            messages=[{"role": "user", "content":
                       f"Question A (expected): {expected}\n"
                       f"Question B (actual): {actual}\nJSON:"}])
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            v = json.loads(text)
        except json.JSONDecodeError:
            v = {"equivalent": False, "reason": "unparseable"}
        c = cost_of(judge_model, resp.usage)
        g.update(output=v, usage=resp.usage, cost=c)
    return bool(v.get("equivalent")), v.get("reason", ""), c


def load_conversations():
    convs = defaultdict(list)
    for r in csv.DictReader(open(GOLD, encoding="utf-8")):
        r["turn"] = int(r["turn"])
        convs[r["conv_id"]].append(r)
    return {k: sorted(v, key=lambda r: r["turn"]) for k, v in convs.items()}


def score_answer(row, res, cur, judge):
    """Same rules as run_eval._tier3_one, on an AskResult."""
    rec = {"sql": res.sql, "sql_error": res.sql_error, "row_count": res.row_count,
           "sql_columns": res.columns, "sql_rows": [tuple(r) for r in res.rows[:50]],
           "chunk_ids": [c.chunk_id for c in res.chunks], "answer": res.answer,
           "latency": {}}
    chunk_rows = load_chunk_rows(cur, rec["chunk_ids"])
    exp_route = row["expected_route"]
    qrow = {"question": row["expected_standalone"] if row["expected_standalone"] != "SAME"
            else row["question"], "expected_answer": row["expected_answer"]}
    cost = 0.0
    if res.sql_error:
        return False, None, f"SQL error: {res.sql_error}", cost
    if exp_route == "refuse":
        ans = res.answer or ""
        return ("only answers questions about" in ans
                or "cannot answer" in ans.lower()), None, "refusal check", cost
    if exp_route == "structured":
        correct = metrics.numeric_match(row["expected_answer"], res.answer)
        verdict, cost = judge_answer(qrow, rec, chunk_rows, judge)
        if correct is None:
            correct = verdict.get("correct")
        return bool(correct), verdict.get("faithful"), verdict.get("reason"), cost
    verdict, cost = judge_answer(qrow, rec, chunk_rows, judge)
    return bool(verdict.get("correct")), verdict.get("faithful"), verdict.get("reason"), cost


def main() -> int:
    convs = load_conversations()
    judge = judge_model_for(ANSWER_MODEL)
    meta = run_metadata({"tier": "conversations", "conversations": len(convs),
                         "turns": sum(len(v) for v in convs.values()),
                         "rewrite_model": "claude-haiku-4-5"})
    run_id = f"conv-{time.strftime('%Y%m%d-%H%M')}-{meta['git_sha']}"
    print(f"conversation tier @ {meta['git_sha']} · {meta['conversations']} "
          f"conversations · {meta['turns']} turns · judge {judge} · "
          f"langfuse session {run_id if tracing.enabled() else 'off'}")
    records, total_cost = [], 0.0
    t_run = time.perf_counter()
    with get_conn() as conn, conn.cursor() as cur:
        for cid, turns in convs.items():
            history = []
            for row in turns:
                res = ask_conversational(row["question"], history,
                                         session_id=run_id, tags=["eval", "conv"],
                                         entry_point="eval_conv")
                cost = res.cost_usd
                exp_same = row["expected_standalone"] == "SAME"
                flag_ok = (res.standalone == exp_same)
                rw_ok, rw_reason = flag_ok, ("passed through" if res.standalone
                                             else "")
                if not exp_same and not res.standalone:
                    rw_ok, rw_reason, c = judge_equivalent(
                        row["expected_standalone"], res.rewritten_question, judge)
                    cost += c
                elif not exp_same and res.standalone:
                    rw_ok, rw_reason = False, "follow-up passed through unchanged"
                elif exp_same and not res.standalone:
                    rw_ok, rw_reason = False, f"rewrote a standalone: {res.rewritten_question}"
                route_ok = res.route_used == row["expected_route"]
                correct, faithful, reason, c = score_answer(row, res, cur, judge)
                cost += c
                total_cost += cost
                rec = {"conv": cid, "turn": row["turn"], "status": row["status"],
                       "question": row["question"],
                       "expected_standalone": row["expected_standalone"],
                       "expected_route": row["expected_route"],
                       "expected_answer": row["expected_answer"],
                       "standalone": res.standalone,
                       "rewritten_question": res.rewritten_question,
                       "rewrite_reason": res.rewrite_reason,
                       "rewrite_latency_ms": res.rewrite_latency_ms,
                       "rewrite_cost_usd": round(res.rewrite_cost_usd, 5),
                       "history_turns": res.history_turns,
                       "flag_ok": flag_ok, "rewrite_ok": rw_ok,
                       "rewrite_judge": rw_reason,
                       "route": res.route_used, "route_ok": route_ok,
                       "sql": res.sql, "sql_error": res.sql_error,
                       "rows": [list(map(str, r)) for r in res.rows[:5]],
                       "row_count": res.row_count,
                       "chunk_ids": [c.chunk_id for c in res.chunks],
                       "answer": res.answer, "correct": correct,
                       "faithful": faithful, "judge_reason": reason,
                       "latency_ms": res.latency_ms, "cost_usd": round(cost, 5),
                       "trace_id": res.trace_id}
                records.append(rec)
                mark = ("✓" if correct else "✗")
                rw = "SAME" if res.standalone else f"→ {res.rewritten_question}"
                print(f"{cid}.{row['turn']} {mark} [{res.route_used:<10}] "
                      f"{row['question'][:48]!r} {rw[:70]}"
                      f"{'' if rw_ok else '  [rewrite ✗]'}"
                      f"{'' if route_ok else '  [route ✗]'}", flush=True)
                history.append(Turn(question=row["question"],
                                    standalone_question=res.rewritten_question
                                    or row["question"],
                                    route=res.route_used, answer=res.answer or "",
                                    sql=res.sql))
    tracing.flush()
    wall = round(time.perf_counter() - t_run, 1)

    def summarize(rs):
        fu = [r for r in rs if r["expected_standalone"] != "SAME"]
        sa = [r for r in rs if r["expected_standalone"] == "SAME"]
        return {"turns": len(rs),
                "followups": len(fu),
                "followups_correct": sum(1 for r in fu if r["correct"]),
                "followups_rewrite_ok": sum(1 for r in fu if r["rewrite_ok"]),
                "followups_route_ok": sum(1 for r in fu if r["route_ok"]),
                "standalone": len(sa),
                "standalone_passed_through": sum(1 for r in sa if r["standalone"]),
                "standalone_correct": sum(1 for r in sa if r["correct"]),
                "all_correct": sum(1 for r in rs if r["correct"])}
    summary = {"all": summarize(records),
               "verified": summarize([r for r in records if r["status"] == "verified"]),
               "draft": summarize([r for r in records if r["status"] == "draft"]),
               "rewrite_calls": sum(1 for r in records if r["history_turns"]
                                    and r["rewrite_latency_ms"]),
               "rewrite_cost_usd": round(sum(r["rewrite_cost_usd"] for r in records), 4),
               "rewrite_latency_ms_mean": round(sum(r["rewrite_latency_ms"] for r in records
                                                    if r["rewrite_latency_ms"]) /
                                                max(1, sum(1 for r in records if r["rewrite_latency_ms"]))),
               "cost_usd": round(total_cost, 4), "wall_seconds": wall,
               "langfuse_session": run_id if tracing.enabled() else None}
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{time.strftime('%Y-%m-%d-%H%M')}-conv.json"
    out.write_text(json.dumps({"meta": meta, "summary": summary, "turns": records},
                              indent=1, default=str), encoding="utf-8")
    s = summary["all"]
    print(f"\nfollow-ups correct {s['followups_correct']}/{s['followups']} · "
          f"rewrite ok {s['followups_rewrite_ok']}/{s['followups']} · "
          f"route ok {s['followups_route_ok']}/{s['followups']} · standalone passed "
          f"through {s['standalone_passed_through']}/{s['standalone']} · all correct "
          f"{s['all_correct']}/{s['turns']} · rewrite {summary['rewrite_calls']} calls "
          f"${summary['rewrite_cost_usd']} mean {summary['rewrite_latency_ms_mean']} ms · "
          f"cost ${total_cost:.2f} · wall {wall}s\nwrote {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

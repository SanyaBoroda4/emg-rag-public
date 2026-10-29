"""Re-judge a saved eval run without re-running the pipeline (WO14).

  python evals/rejudge.py evals/results/<run>.json --passes 3 --out /tmp/rj

The judge's inputs (question, key, answer text, SQL + rows, chunk ids) are
all in the run JSON; only the chunk texts come from the database. Feeding
them to the unchanged judge_answer() isolates the grader: one pass costs
the judge stage only (~$0.46) instead of a full run (~$1.06).

Writes <out>-pass<k>.json per pass: the input run with each question's
correct / faithful / context_precision / judge_reason / judge_calls
replaced, plus a summary. Scoring rules are the ones in
run_eval._tier3_one (numeric match for structured rows, judge for the
rest, sql_error rows incorrect without a judge call).

JUDGE_VOTES=3 in the environment makes each pass a majority-of-3 judge
(see harness.judge_answer). Run with LANGFUSE keys blanked unless you want
79 standalone judge traces per pass.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.db import get_conn
from evals import metrics
from evals.harness import (JUDGE_VOTES, judge_answer, judge_model_for,
                           load_chunk_rows)


def rejudge_one(q, chunk_rows, judge):
    """Returns (new generation dict, cost) with the same fields
    run_eval._tier3_one sets."""
    g = dict(q["generation"])
    rec = {"sql": g.get("sql"), "sql_error": g.get("sql_error"),
           "row_count": g.get("row_count"), "sql_columns": g.get("sql_columns"),
           "sql_rows": g.get("sql_rows"), "chunk_ids": g.get("chunk_ids") or [],
           "answer": g.get("answer"), "latency": {}}
    row = {"question": q["question"], "expected_answer": q["expected_answer"]}
    expected_route = q["route"]
    verdict, cost = {}, 0.0
    if rec["sql_error"]:
        g["correct"], g["faithful"], g["context_precision"] = False, None, None
        verdict = {"reason": "SQL lane raised an exception — scored incorrect "
                             "by rule: " + rec["sql_error"]}
    elif expected_route == "refuse":
        ans = rec["answer"] or ""
        declined = ("only answers questions about" in ans
                    or "cannot answer" in ans.lower())
        if not declined:
            verdict, cost = judge_answer(row, rec, chunk_rows, judge)
            declined = verdict.get("declined", False)
        g["correct"], g["faithful"], g["context_precision"] = declined, None, None
    elif expected_route == "structured":
        g["correct"] = metrics.numeric_match(q["expected_answer"], rec["answer"])
        verdict, cost = judge_answer(row, rec, chunk_rows, judge)
        g["faithful"] = verdict.get("faithful")
        g["context_precision"] = None
        if g["correct"] is None:
            g["correct"] = verdict.get("correct")
    else:
        verdict, cost = judge_answer(row, rec, chunk_rows, judge)
        g["correct"] = verdict.get("correct")
        g["faithful"] = verdict.get("faithful")
        useful = set(verdict.get("useful_chunk_ids", []))
        g["context_precision"] = (len(useful & set(rec["chunk_ids"]))
                                  / len(rec["chunk_ids"])
                                  if rec["chunk_ids"] else None)
    g["judge_reason"] = verdict.get("reason")
    g["judge_calls"] = rec.get("judge_calls", 0)
    g["judge_votes"] = rec.get("judge_votes")
    return g, cost


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_json")
    ap.add_argument("--passes", type=int, default=1)
    ap.add_argument("--out", required=True, help="output prefix")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    run = json.loads(Path(args.run_json).read_text(encoding="utf-8"))
    questions = [q for q in run["questions"] if q.get("generation")]
    judge = judge_model_for(run["meta"]["answer_model"])
    with get_conn() as conn, conn.cursor() as cur:  # chunk texts, once
        chunks = {q["id"]: load_chunk_rows(cur, q["generation"]["chunk_ids"] or [])
                  for q in questions}
    print(f"rejudge {Path(args.run_json).name}: {len(questions)} questions, "
          f"judge={judge}, votes={JUDGE_VOTES}, passes={args.passes}")

    for k in range(1, args.passes + 1):
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(
                lambda q: rejudge_one(q, chunks[q["id"]], judge), questions))
        cost = sum(c for _, c in results)
        out = json.loads(json.dumps(run))  # deep copy
        by_id = {q["id"]: q for q in out["questions"]}
        for q, (g, _) in zip(questions, results):
            by_id[q["id"]]["generation"] = g
        scored = [q["generation"] for q in out["questions"] if q.get("generation")]
        n_ok = sum(1 for g in scored if g["correct"])
        failing = sorted(int(q["id"]) for q in out["questions"]
                         if q.get("generation") and not q["generation"]["correct"])
        faith = [g["faithful"] for g in scored if g["faithful"] is not None]
        out["rejudge"] = {"source": Path(args.run_json).name, "pass": k,
                          "judge_model": judge, "judge_votes": JUDGE_VOTES,
                          "correct": n_ok, "total": len(scored),
                          "failing": failing,
                          "faithfulness": sum(1 for f in faith if f) / len(faith)
                          if faith else None,
                          "cost": round(cost, 4),
                          "wall_seconds": round(time.perf_counter() - t0, 1)}
        path = Path(f"{args.out}-pass{k}.json")
        path.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
        print(f"pass {k}: correct {n_ok}/{len(scored)} failing {failing} "
              f"faithfulness {out['rejudge']['faithfulness']:.3f} "
              f"cost ${cost:.2f} wall {out['rejudge']['wall_seconds']}s -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

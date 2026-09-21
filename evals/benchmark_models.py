"""Model benchmark: Haiku vs Sonnet, priced per correct answer.

Two experiments:
  1. ANSWER_MODEL on the full golden set — accuracy, faithfulness, mean
     answer latency, generation cost, and cost per correct answer. The judge
     is always the OTHER model (haiku answers -> sonnet judge and vice
     versa); judge cost is reported separately and excluded from
     cost-per-correct (it is a measurement cost, not a serving cost).
  2. SQL_MODEL on the structured subset only — WO4 chose Sonnet on the
     argument that a wrong join fails silently; this tests that argument.
     Scored by numeric match against expected_answer (no judge needed).

Routing and retrieval run ONCE and are shared across model configs — the
router and lanes don't depend on the answer model.
"""

import copy
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.db import get_conn
from evals import metrics
from evals.harness import (embed_questions, judge_answer, judge_model_for,
                           load_chunk_rows, load_golden, run_generation,
                           run_metadata, run_retrieval, run_router)

ANSWER_MODELS = ["claude-haiku-4-5", "claude-sonnet-5"]
SQL_MODELS = ["claude-sonnet-5", "claude-haiku-4-5"]


def score_row(cur, row, rec, judge):
    """Correctness by route type (numeric / declined / judged); returns
    (correct, faithful, judge_cost)."""
    if row["route"] == "refuse":
        declined = ("only answers questions about" in (rec["answer"] or "")
                    or "cannot answer" in (rec["answer"] or "").lower())
        return declined, None, 0.0
    if row["route"] == "structured":
        correct = metrics.numeric_match(row["expected_answer"], rec["answer"])
        return bool(correct), None, 0.0
    chunk_rows = load_chunk_rows(cur, rec["chunk_ids"])
    verdict, jcost = judge_answer(row, rec, chunk_rows, judge)
    return verdict.get("correct"), verdict.get("faithful"), jcost


def bench_answer_models(cur, rows, qvecs):
    print("\n=== ANSWER_MODEL benchmark (full set) ===")
    results = {}
    for model in ANSWER_MODELS:
        judge = judge_model_for(model)
        gen_cost = judge_cost = 0.0
        n_correct = 0
        faithful = []
        latencies = []
        for row in (copy.deepcopy(r) for r in rows):
            route = row["_predicted_route"]
            ret = row.get("_retrieval") or {"candidates": []}
            rec = run_generation(cur, row, ret, route, answer_model=model)
            gen_cost += rec["cost"]
            latencies.append(rec["latency"].get("answer", 0))
            correct, faith, jcost = score_row(cur, row, rec, judge)
            judge_cost += jcost
            n_correct += 1 if correct else 0
            if faith is not None:
                faithful.append(1.0 if faith else 0.0)
        results[model] = {
            "correct": n_correct, "total": len(rows),
            "accuracy": n_correct / len(rows),
            "faithfulness": (sum(faithful) / len(faithful)) if faithful else None,
            "mean_answer_latency_s": statistics.mean(latencies),
            "gen_cost": gen_cost, "judge_cost": judge_cost,
            "judge_model": judge,
            "cost_per_correct": gen_cost / n_correct if n_correct else None,
        }
        r = results[model]
        print(f"{model}: {r['correct']}/{r['total']} ({r['accuracy']:.1%}) "
              f"faithful {r['faithfulness']:.1%} "
              f"lat {r['mean_answer_latency_s']:.2f}s "
              f"gen ${r['gen_cost']:.3f} "
              f"(judge={judge} ${r['judge_cost']:.3f}) "
              f"-> ${r['cost_per_correct']:.4f}/correct")
    return results


def bench_sql_models(cur, rows, qvecs):
    structured = [r for r in rows if r["route"] == "structured"]
    print(f"\n=== SQL_MODEL benchmark (structured subset, "
          f"{len(structured)} questions) ===")
    results = {}
    for model in SQL_MODELS:
        cost = 0.0
        n_correct = 0
        sql_errors = 0
        latencies = []
        for row in (copy.deepcopy(r) for r in structured):
            ret = row.get("_retrieval") or {"candidates": []}
            t0 = time.perf_counter()
            rec = run_generation(cur, row, ret, "structured",
                                 sql_model=model)
            latencies.append(time.perf_counter() - t0)
            cost += rec["cost"]
            if rec["sql_error"]:
                sql_errors += 1
            correct = metrics.numeric_match(row["expected_answer"],
                                            rec["answer"])
            n_correct += 1 if correct else 0
        results[model] = {
            "correct": n_correct, "total": len(structured),
            "accuracy": n_correct / len(structured),
            "sql_failures": sql_errors,
            "mean_latency_s": statistics.mean(latencies),
            "cost": cost,
            "cost_per_correct": cost / n_correct if n_correct else None,
        }
        r = results[model]
        print(f"{model}: {r['correct']}/{r['total']} ({r['accuracy']:.1%}) "
              f"sql-fail {sql_errors} lat {r['mean_latency_s']:.2f}s "
              f"${r['cost']:.3f} -> ${r['cost_per_correct']:.4f}/correct")
    return results


def main() -> int:
    rows = load_golden()
    meta = run_metadata({"benchmark": True})
    print(f"model benchmark @ {meta['git_sha']} · {len(rows)} questions")

    with get_conn() as conn, conn.cursor() as cur:
        # shared, model-independent stages
        for row in rows:
            row["_predicted_route"], row["_route_reason"], _ = run_router(row)
        qvecs = embed_questions(rows)
        for row in rows:
            if row["_predicted_route"] in ("semantic", "hybrid"):
                row["_retrieval"] = run_retrieval(cur, row["question"],
                                                  qvecs[row["id"]])
        ans = bench_answer_models(cur, rows, qvecs)
        sql = bench_sql_models(cur, rows, qvecs)

    out = Path(__file__).resolve().parent / "results" / "benchmark.md"
    lines = [f"# Model benchmark ({meta['timestamp']}, commit "
             f"{meta['git_sha']})", "",
             "## ANSWER_MODEL (full set; judge is always the other model)",
             "",
             "| model | accuracy | faithfulness | latency | gen cost | "
             "$/correct |", "|---|---|---|---|---|---|"]
    for m, r in ans.items():
        lines.append(f"| {m} | {r['correct']}/{r['total']} "
                     f"({r['accuracy']:.1%}) | {r['faithfulness']:.1%} | "
                     f"{r['mean_answer_latency_s']:.2f}s | "
                     f"${r['gen_cost']:.3f} | ${r['cost_per_correct']:.4f} |")
    lines += ["", "## SQL_MODEL (structured subset, numeric scoring)", "",
              "| model | accuracy | sql failures | latency | cost | "
              "$/correct |", "|---|---|---|---|---|---|"]
    for m, r in sql.items():
        lines.append(f"| {m} | {r['correct']}/{r['total']} "
                     f"({r['accuracy']:.1%}) | {r['sql_failures']} | "
                     f"{r['mean_latency_s']:.2f}s | ${r['cost']:.3f} | "
                     f"${r['cost_per_correct']:.4f} |")
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

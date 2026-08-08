"""Eval runner: Tier 1 (routing), Tier 2 (retrieval), Tier 3 (generation).

  python3 evals/run_eval.py                 # all tiers, all 58 questions
  python3 evals/run_eval.py --tiers 1,2     # the free tiers only
  python3 evals/run_eval.py --subset 20     # first N questions (PR CI)
  python3 evals/run_eval.py --check-baseline evals/baseline.json
                                            # exit 1 if routing accuracy or
                                            # reranked Recall@10 drops >5pts

Writes:
  evals/results/YYYY-MM-DD-HHMM.json   full per-question detail
  evals/results/latest.md              markdown summary for the README

Every run records git SHA, model names, config flags, and total cost —
a result that cannot be traced to a code state is not evidence.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.db import get_conn
from evals import metrics
from evals.harness import (ANSWER_MODEL, embed_questions, judge_answer,
                           judge_model_for, load_chunk_rows, load_golden,
                           run_generation, run_metadata, run_retrieval,
                           run_router)

RESULTS_DIR = Path(__file__).resolve().parent / "results"
LANES = ["bm25", "dense", "fused", "reranked"]


def tier1(rows):
    print(f"\n=== Tier 1: routing ({len(rows)} questions) ===")
    total_cost = 0.0
    for row in rows:
        predicted, reason, cost = run_router(row)
        row["_predicted_route"] = predicted
        row["_route_reason"] = reason
        total_cost += cost
    matrix, accuracy = metrics.confusion_matrix(
        [(r["route"], r["_predicted_route"]) for r in rows])
    print(metrics.format_confusion(matrix))
    print(f"routing accuracy: {accuracy:.1%}   (router cost ${total_cost:.4f})")
    return {"accuracy": accuracy, "matrix": matrix, "cost": total_cost}


def tier2(rows, cur, qvecs):
    gold_rows = [r for r in rows if r["gold_ids"]]
    print(f"\n=== Tier 2: retrieval ({len(gold_rows)} questions with "
          f"gold chunk ids) ===")
    per_lane = {lane: [] for lane in LANES}
    for row in gold_rows:
        ret = run_retrieval(cur, row["question"], qvecs[row["id"]])
        row["_retrieval"] = ret
        row["_lane_metrics"] = {}
        for lane in LANES:
            m = metrics.ranking_metrics(ret[lane], row["gold_ids"])
            row["_lane_metrics"][lane] = m
            per_lane[lane].append(m)

    agg = {}
    keys = ["recall@5", "recall@10", "recall@20", "mrr", "ndcg@10"]
    print(f"{'lane':<12}" + "".join(f"{k:>11}" for k in keys))
    for lane in LANES:
        agg[lane] = {k: metrics.mean_of(per_lane[lane], k) for k in keys}
        print(f"{lane:<12}" + "".join(
            f"{agg[lane][k]:>11.3f}" if agg[lane][k] is not None
            else f"{'—':>11}" for k in keys))
    return agg


def tier3(rows, cur, qvecs, answer_model=None, sql_model=None):
    judge = judge_model_for(answer_model or ANSWER_MODEL)
    print(f"\n=== Tier 3: generation "
          f"(answer={answer_model or ANSWER_MODEL}, judge={judge}) ===")
    total_cost = 0.0
    for row in rows:
        route = row.get("_predicted_route") or row["route"]
        ret = row.get("_retrieval")
        if ret is None and route in ("semantic", "hybrid"):
            ret = run_retrieval(cur, row["question"], qvecs[row["id"]])
            row["_retrieval"] = ret
        rec = run_generation(cur, row, ret or {"candidates": []}, route,
                             answer_model=answer_model, sql_model=sql_model)
        total_cost += rec["cost"]

        chunk_rows = load_chunk_rows(cur, rec["chunk_ids"])
        expected_route = row["route"]
        verdict = {}
        if expected_route == "refuse":
            declined = ("only answers questions about" in (rec["answer"] or "")
                        or "cannot answer" in (rec["answer"] or "").lower())
            if not declined:
                verdict, jcost = judge_answer(row, rec, chunk_rows, judge)
                total_cost += jcost
                declined = verdict.get("declined", False)
            rec["correct"] = declined
            rec["faithful"] = None
            rec["context_precision"] = None
        elif expected_route == "structured":
            rec["correct"] = metrics.numeric_match(row["expected_answer"],
                                                   rec["answer"])
            verdict, jcost = judge_answer(row, rec, chunk_rows, judge)
            total_cost += jcost
            rec["faithful"] = verdict.get("faithful")
            rec["context_precision"] = None
            if rec["correct"] is None:  # no number in expected answer
                rec["correct"] = verdict.get("correct")
        else:  # semantic / hybrid
            verdict, jcost = judge_answer(row, rec, chunk_rows, judge)
            total_cost += jcost
            rec["correct"] = verdict.get("correct")
            rec["faithful"] = verdict.get("faithful")
            useful = set(verdict.get("useful_chunk_ids", []))
            rec["context_precision"] = (
                len(useful & set(rec["chunk_ids"])) / len(rec["chunk_ids"])
                if rec["chunk_ids"] else None)
        rec["judge_reason"] = verdict.get("reason")
        row["_generation"] = rec

    scored = [r["_generation"] for r in rows]
    n_correct = sum(1 for g in scored if g["correct"])
    agg = {
        "correct": n_correct, "total": len(rows),
        "accuracy": n_correct / len(rows),
        "faithfulness": metrics.mean_of(
            [{"f": 1.0 if g["faithful"] else 0.0}
             for g in scored if g["faithful"] is not None], "f"),
        "context_precision": metrics.mean_of(
            [{"p": g["context_precision"]} for g in scored
             if g["context_precision"] is not None], "p"),
        "cost": total_cost,
        "judge_model": judge,
    }
    print(f"correct: {n_correct}/{len(rows)} ({agg['accuracy']:.1%})  "
          f"faithfulness: {agg['faithfulness']:.1%}  "
          f"context precision: {agg['context_precision']:.1%}  "
          f"cost: ${total_cost:.2f}")
    return agg


def report_failures(rows):
    """The most interesting output: verified rows that fail, FAILING rows
    that (unexpectedly) pass."""
    news, known = [], []
    for row in rows:
        gen = row.get("_generation")
        if gen is None:
            continue
        ok = bool(gen["correct"]) and \
            row["_predicted_route"] == row["route"]
        if row["status"] == "FAILING":
            known.append((row, ok))
        elif row["status"] == "verified" and not ok:
            news.append(row)
    print("\n=== Known-FAILING rows (must stay failing until bugs fixed) ===")
    for row, ok in known:
        print(f"  Q{row['id']}: {'*** NOW PASSES ***' if ok else 'still fails'}"
              f" — {row['question'][:60]}"
              f" (routed {row['_predicted_route']}, expected {row['route']})")
    print("\n=== NEW failures among status=verified rows ===")
    if not news:
        print("  (none)")
    for row in news:
        gen = row["_generation"]
        print(f"  Q{row['id']} [{row['route']}→{row['_predicted_route']}] "
              f"{row['question'][:70]}")
        print(f"    expected: {row['expected_answer'][:90]}")
        print(f"    got:      {(gen['answer'] or '')[:90]}")
    return {"new_failures": [r["id"] for r in news],
            "known_failing": {r["id"]: ok for r, ok in known}}


def write_reports(meta, rows, t1, t2, t3, failures):
    RESULTS_DIR.mkdir(exist_ok=True)
    detail = []
    for row in rows:
        d = {k: row[k] for k in ("id", "question", "route", "expected_answer",
                                 "difficulty", "status")}
        d["gold_ids"] = row["gold_ids"]
        d["predicted_route"] = row.get("_predicted_route")
        d["route_reason"] = row.get("_route_reason")
        d["lane_metrics"] = row.get("_lane_metrics")
        ret = row.get("_retrieval")
        if ret:
            d["retrieved"] = [
                {"chunk_id": c["chunk_id"], "bm25_rank": c["bm25_rank"],
                 "dense_rank": c["dense_rank"], "rrf": round(c["score"], 5),
                 "rerank_score": round(c["rerank_score"], 4)
                 if c.get("rerank_score") is not None else None}
                for c in ret["candidates"][:10]]
            d["retrieval_latency"] = ret["latency"]
        d["generation"] = row.get("_generation")
        detail.append(d)

    result = {"meta": meta, "tier1": t1, "tier2": t2, "tier3": t3,
              "failures": failures, "questions": detail}
    stamp = time.strftime("%Y-%m-%d-%H%M")
    out = RESULTS_DIR / f"{stamp}.json"
    out.write_text(json.dumps(result, indent=1, default=str),
                   encoding="utf-8")

    md = [f"# Eval run {meta['timestamp']}",
          f"", f"commit `{meta['git_sha']}` · answer={meta['answer_model']} · "
          f"sql={meta['sql_model']} · judge={t3['judge_model'] if t3 else '—'}"
          f" · rerank={meta['rerank_backend']}", ""]
    if t1:
        md += [f"## Tier 1 — routing", "",
               f"Accuracy: **{t1['accuracy']:.1%}**", "", "```",
               metrics.format_confusion(t1["matrix"]), "```", ""]
    if t2:
        md += ["## Tier 2 — retrieval (per lane)", "",
               "| lane | R@5 | R@10 | R@20 | MRR | NDCG@10 |",
               "|---|---|---|---|---|---|"]
        for lane in LANES:
            a = t2[lane]
            md.append("| " + lane + " | " + " | ".join(
                f"{a[k]:.3f}" if a[k] is not None else "—"
                for k in ["recall@5", "recall@10", "recall@20", "mrr",
                          "ndcg@10"]) + " |")
        md.append("")
    if t3:
        md += ["## Tier 3 — generation", "",
               f"- correct: **{t3['correct']}/{t3['total']} "
               f"({t3['accuracy']:.1%})**",
               f"- faithfulness: {t3['faithfulness']:.1%}",
               f"- context precision: {t3['context_precision']:.1%}",
               f"- generator: {meta['answer_model']} · judge: "
               f"{t3['judge_model']} (never the same model)",
               f"- tier-3 cost: ${t3['cost']:.2f}", ""]
    md += [f"Known-FAILING: " + ", ".join(
        f"Q{qid} {'PASSES(!)' if ok else 'still failing'}"
        for qid, ok in failures.get("known_failing", {}).items()),
        f"New failures (verified rows): "
        + (", ".join(f"Q{q}" for q in failures.get("new_failures", []))
           or "none"), ""]
    (RESULTS_DIR / "latest.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\nwrote {out.name} and latest.md")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", default="1,2,3")
    ap.add_argument("--subset", type=int, default=None)
    ap.add_argument("--check-baseline", default=None)
    args = ap.parse_args()
    tiers = {int(t) for t in args.tiers.split(",")}

    rows = load_golden()
    if args.subset:
        rows = rows[:args.subset]
    meta = run_metadata({"tiers": sorted(tiers),
                         "questions": len(rows)})
    print(f"eval @ {meta['git_sha']} · {len(rows)} questions · "
          f"tiers {sorted(tiers)}")

    t1 = t2 = t3 = None
    failures = {}
    with get_conn() as conn, conn.cursor() as cur:
        if 1 in tiers:
            t1 = tier1(rows)
        if 2 in tiers or 3 in tiers:
            qvecs = embed_questions(rows)
        if 2 in tiers:
            t2 = tier2(rows, cur, qvecs)
        if 3 in tiers:
            if t1 is None:
                t1 = tier1(rows)
            t3 = tier3(rows, cur, qvecs)
            failures = report_failures(rows)

    total = (t1["cost"] if t1 else 0) + (t3["cost"] if t3 else 0)
    meta["total_cost_usd"] = round(total, 4)
    print(f"\ntotal run cost: ${total:.4f}")
    write_reports(meta, rows, t1, t2, t3, failures)

    if args.check_baseline:
        base = json.loads(Path(args.check_baseline).read_text())
        bad = []
        if t1 and t1["accuracy"] < base["routing_accuracy"] - 0.05:
            bad.append(f"routing {t1['accuracy']:.3f} < baseline "
                       f"{base['routing_accuracy']:.3f} - 0.05")
        if t2 and t2["reranked"]["recall@10"] < base["recall_at_10"] - 0.05:
            bad.append(f"recall@10 {t2['reranked']['recall@10']:.3f} < "
                       f"baseline {base['recall_at_10']:.3f} - 0.05")
        if bad:
            print("BASELINE CHECK FAILED: " + "; ".join(bad))
            return 1
        print("baseline check OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

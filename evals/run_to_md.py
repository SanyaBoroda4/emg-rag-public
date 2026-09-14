"""Render one eval-run JSON as a detailed, self-contained markdown report."""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\alex\PycharmProjects\emg-rag")
from evals import metrics  # noqa: E402

src = Path(sys.argv[1])
prev = Path(sys.argv[2]) if len(sys.argv) > 2 else None
out = Path(sys.argv[3]) if len(sys.argv) > 3 else src.with_suffix(".md")

d = json.load(open(src, encoding="utf-8"))
p = json.load(open(prev, encoding="utf-8")) if prev else None
m, t1, t2, t3, st = d["meta"], d["tier1"], d["tier2"], d["tier3"], d["stages"]
qs = d["questions"]


def yn(v):
    return "✓" if v else ("✗" if v is False else "—")


def pct(v):
    return f"{v:.1%}" if v is not None else "—"


def s(v, nd=1):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "—"


def fence(text, lang=""):
    text = (text or "").replace("```", "'''")
    return f"```{lang}\n{text}\n```"


L = []
w = L.append

w(f"# Eval run {m['timestamp']} — full Tier 1–3, commit `{m['git_sha']}`")
w("")
w("Source: `evals/results/" + src.name + "` (EMG RAG, github.com/SanyaBoroda4/emg-rag). "
  "Rendered for review; every number below is copied from the run JSON.")
w("")
w("## 1. Run metadata")
w("")
w("| field | value |")
w("|---|---|")
for k in ("git_sha", "timestamp", "questions", "tiers", "workers", "answer_model",
          "sql_model", "router_model", "embed_model", "rerank_backend",
          "rerank_enabled", "route_filter", "no_judge", "total_cost_usd",
          "wall_seconds"):
    w(f"| {k} | {m.get(k)} |")
w(f"| judge_model | {t3['judge_model']} (never the generator) |")
w("")
w("Scoring rules: `structured` rows are scored by numeric match of every expected "
  "number against the answer (judge supplies faithfulness only); `semantic`/`hybrid` "
  "rows are scored by the judge (correct, faithful, useful chunk ids → context "
  "precision); `refuse` rows pass when the answer declines. Golden statuses: "
  "`verified` = key confirmed by Alex, `draft` = key not yet signed off, "
  "`FAILING` = known bug, expected to fail.")
w("")

w("## 2. Headline scores")
w("")
w("| metric | this run |" + (" previous run (`" + p["meta"]["git_sha"] + "`, "
  + p["meta"]["timestamp"] + ") |" if p else ""))
w("|---|---|" + ("---|" if p else ""))
rows = [
    ("routing accuracy", pct(t1["accuracy"]), pct(p["tier1"]["accuracy"]) if p else None),
    ("generation correct", f"{t3['correct']}/{t3['total']} ({pct(t3['accuracy'])})",
     f"{p['tier3']['correct']}/{p['tier3']['total']} ({pct(p['tier3']['accuracy'])})" if p else None),
    ("faithfulness", pct(t3["faithfulness"]), pct(p["tier3"]["faithfulness"]) if p else None),
    ("context precision (semantic/hybrid)", pct(t3["context_precision"]),
     pct(p["tier3"]["context_precision"]) if p else None),
    ("reranked recall@10", s(t2["reranked"]["recall@10"], 3),
     s(p["tier2"]["reranked"]["recall@10"], 3) if p else None),
    ("reranked MRR", s(t2["reranked"]["mrr"], 3), s(p["tier2"]["reranked"]["mrr"], 3) if p else None),
    ("total cost", f"${m['total_cost_usd']:.2f}", f"${p['meta']['total_cost_usd']:.2f}" if p else None),
    ("wall time", f"{m['wall_seconds']} s ({m['workers']} worker)",
     f"{p['meta']['wall_seconds']} s ({p['meta']['workers']} workers)" if p else None),
]
for name, a, b in rows:
    w(f"| {name} | {a} |" + (f" {b} |" if p else ""))
w("")

# by block
blocks = [("Q1–63 core set", 1, 63), ("Q64–73 crew workload", 64, 73),
          ("Q74–82 wasted templates", 74, 82)]
w("By block:")
w("")
for name, lo, hi in blocks:
    sub = [q for q in qs if lo <= int(q["id"]) <= hi]
    ok = sum(1 for q in sub if q["generation"]["correct"])
    w(f"- {name}: {ok}/{len(sub)} correct")
w("")
by_status = {}
for q in qs:
    by_status.setdefault(q["status"], [0, 0])
    by_status[q["status"]][1] += 1
    by_status[q["status"]][0] += 1 if q["generation"]["correct"] else 0
w("By golden status:")
w("")
for k, (ok, n) in sorted(by_status.items()):
    w(f"- {k}: {ok}/{n}")
w("")
by_route = {}
for q in qs:
    by_route.setdefault(q["route"], [0, 0])
    by_route[q["route"]][1] += 1
    by_route[q["route"]][0] += 1 if q["generation"]["correct"] else 0
w("By expected route:")
w("")
for k, (ok, n) in sorted(by_route.items()):
    w(f"- {k}: {ok}/{n}")
w("")

if p:
    pm = {int(q["id"]): q for q in p["questions"]}
    changes = []
    for q in qs:
        o = pm.get(int(q["id"]))
        if not o:
            continue
        a = (o["predicted_route"], bool(o["generation"]["correct"]))
        b = (q["predicted_route"], bool(q["generation"]["correct"]))
        if a != b:
            changes.append((q, a, b))
    w("### Changes vs previous run")
    w("")
    if not changes:
        w("None.")
    for q, a, b in changes:
        w(f"- Q{q['id']} [{q['status']}] {a[0]}/{yn(a[1])} → {b[0]}/{yn(b[1])} — "
          f"{q['question']}")
    w("")

w("## 3. Tier 1 — routing")
w("")
w(fence(metrics.format_confusion(t1["matrix"])))
w("")
mis = [q for q in qs if q["predicted_route"] != q["route"]]
w(f"Misrouted ({len(mis)}):")
w("")
for q in mis:
    w(f"- Q{q['id']} expected **{q['route']}**, got **{q['predicted_route']}** — "
      f"{q['question']}  \n  router reason: {q['route_reason']}")
w("")

w("## 4. Tier 2 — retrieval (questions with gold chunk ids)")
w("")
w("| lane | R@5 | R@10 | R@20 | MRR | NDCG@10 |")
w("|---|---|---|---|---|---|")
for lane in ("bm25", "dense", "fused", "reranked"):
    a = t2[lane]
    w(f"| {lane} | " + " | ".join(s(a[k], 3) for k in
      ("recall@5", "recall@10", "recall@20", "mrr", "ndcg@10")) + " |")
w("")
gold_q = [q for q in qs if q["gold_ids"]]
w(f"{len(gold_q)} questions carry gold chunk ids. Per-question reranked recall@10:")
w("")
w("| q | gold ids | reranked R@10 | MRR | route |")
w("|---|---|---|---|---|")
for q in gold_q:
    lm = (q.get("lane_metrics") or {}).get("reranked") or {}
    w(f"| Q{q['id']} | {len(q['gold_ids'])} | {s(lm.get('recall@10'), 2)} | "
      f"{s(lm.get('mrr'), 2)} | {q['route']} |")
w("")

w("## 5. Stage timing (whole run, sequential)")
w("")
w("| stage | total seconds | % of wall | calls |")
w("|---|---|---|---|")
wall = st["wall_seconds"]
for k, v in st["seconds"].items():
    w(f"| {k} | {v} | {v / wall:.1%} | {st['calls'][k]} |")
w(f"| **sum** | {st['sum_seconds']} | {st['sum_seconds'] / wall:.1%} | |")
w(f"| **wall** | {wall} | 100% | |")
w(f"| **gap (untimed)** | {st['gap_seconds']} | {st['gap_seconds'] / wall:.1%} | |")
w("")
w("The judge is one Sonnet call per question that returns faithfulness, "
  "correctness and useful chunk ids in a single JSON verdict; it is timed as "
  "one stage. Retrieval stages are counted for the 26 gold-id questions "
  "(tier 2) plus any tier-3 semantic/hybrid question without gold ids.")
w("")

w("## 6. All questions — summary")
w("")
w("| q | status | diff | expected route | predicted | correct | faithful | ctx prec | router s | sql s | answer s | judge s | question |")
w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for q in qs:
    g = q["generation"]
    lat = g.get("latency") or {}
    w(f"| Q{q['id']} | {q['status']} | {q['difficulty']} | {q['route']} | "
      f"{q['predicted_route']}{'' if q['predicted_route'] == q['route'] else ' ⚠'} | "
      f"{yn(g['correct'])} | {yn(g['faithful'])} | {pct(g['context_precision'])} | "
      f"{s(q.get('route_latency'))} | {s(lat.get('sql'))} | {s(lat.get('answer'))} | "
      f"{s(lat.get('judge'))} | {q['question'].replace('|', '/')} |")
w("")

fails = [q for q in qs if not q["generation"]["correct"]]
w(f"## 7. Incorrect answers ({len(fails)})")
w("")
w("| q | status | route | why (judge reason or numeric mismatch) |")
w("|---|---|---|---|")
for q in fails:
    g = q["generation"]
    if q["route"] == "structured" and g.get("judge_reason"):
        why = ("numeric match failed vs expected «" + q["expected_answer"][:80]
               + "»; judge: " + (g["judge_reason"] or "")[:200])
    else:
        why = (g.get("judge_reason") or g.get("sql_error") or "")[:280]
    w(f"| Q{q['id']} | {q['status']} | {q['route']}→{q['predicted_route']} | "
      f"{why.replace('|', '/').replace(chr(10), ' ')} |")
w("")

w("## 8. Per-question detail")
w("")
for q in qs:
    g = q["generation"]
    lat = g.get("latency") or {}
    w(f"### Q{q['id']} — {q['question']}")
    w("")
    w(f"- status: `{q['status']}` · difficulty: `{q['difficulty']}` · expected route: "
      f"`{q['route']}` · predicted: `{q['predicted_route']}`"
      f"{'' if q['predicted_route'] == q['route'] else ' **(misrouted)**'}")
    w(f"- router reason: {q['route_reason']}")
    w(f"- **expected answer:** {q['expected_answer']}")
    w(f"- result: correct {yn(g['correct'])} · faithful {yn(g['faithful'])} · "
      f"context precision {pct(g['context_precision'])} · cost ${g['cost']:.4f}")
    w(f"- latency s: router {s(q.get('route_latency'), 2)} · sql {s(lat.get('sql'), 2)} · "
      f"answer {s(lat.get('answer'), 2)} · judge {s(lat.get('judge'), 2)}"
      f" (judge calls {g.get('judge_calls', 0)})")
    if q["gold_ids"]:
        lm = (q.get("lane_metrics") or {}).get("reranked") or {}
        w(f"- gold chunk ids: {q['gold_ids']} · reranked R@10 {s(lm.get('recall@10'), 2)}")
    w("")
    if g.get("sql"):
        w("**SQL executed**")
        w("")
        w(fence(g["sql"], "sql"))
        w("")
        cols = g.get("sql_columns")
        rows_ = g.get("sql_rows") or []
        w(f"Rows returned: {g.get('row_count')}" +
          (f" · columns: {cols}" if cols else ""))
        if rows_:
            w("")
            w(fence("\n".join(str(r) for r in rows_[:15]) +
                    ("\n..." if len(rows_) > 15 else "")))
        w("")
    if g.get("sql_error"):
        w(f"**SQL error:** `{g['sql_error']}`  (fell back to semantic)")
        w("")
    if g.get("chunk_ids"):
        w(f"**Chunks passed to the answerer:** {g['chunk_ids']}")
        ret = q.get("retrieved") or []
        if ret:
            w("")
            w("| rank | chunk | bm25 rank | dense rank | rrf | rerank score |")
            w("|---|---|---|---|---|---|")
            for i, c in enumerate(ret[:6], 1):
                w(f"| {i} | {c['chunk_id']} | {c['bm25_rank']} | {c['dense_rank']} | "
                  f"{c['rrf']} | {c['rerank_score']} |")
        w("")
    w("**Answer**")
    w("")
    w(fence(g.get("answer")))
    w("")
    if g.get("judge_reason"):
        w(f"**Judge:** {g['judge_reason']}")
        w("")
    w("---")
    w("")

out.write_text("\n".join(L), encoding="utf-8")
print(out, f"{out.stat().st_size / 1024:.0f} KB", len(L), "lines")

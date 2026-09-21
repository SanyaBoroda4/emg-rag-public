"""Ablation: which retrieval configurations earn their keep? (Tiers 1+2
only — free of Claude calls, safe to run often.)

  config          what it tests
  dense only      baseline
  bm25 only       baseline
  RRF, no rerank  does fusion help?
  RRF + rerank    does reranking help?

All four configs are computed from ONE retrieval pass per question (the lanes
are independent, fusion and reranking are deterministic re-orderings), so the
whole ablation costs one batched query-embedding call plus one rerank call
per question. Routing (Tier 1) does not vary with retrieval config; it is
reported once for context.

Writes evals/results/ablation.md and prints the comparison table.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.db import get_conn
from evals import metrics
from evals.harness import (embed_questions, load_golden, run_metadata,
                           run_retrieval)

CONFIGS = [
    ("bm25 only", "bm25"),
    ("dense only", "dense"),
    ("RRF, no rerank", "fused"),
    ("RRF + rerank", "reranked"),
]
KEYS = ["recall@5", "recall@10", "recall@20", "mrr", "ndcg@10"]


def main() -> int:
    rows = [r for r in load_golden() if r["gold_ids"]]
    meta = run_metadata({"ablation_questions": len(rows)})
    print(f"ablation @ {meta['git_sha']} · {len(rows)} questions "
          f"with gold chunk ids")

    per_config = {name: [] for name, _ in CONFIGS}
    with get_conn() as conn, conn.cursor() as cur:
        qvecs = embed_questions(rows)
        for row in rows:
            ret = run_retrieval(cur, row["question"], qvecs[row["id"]])
            for name, lane in CONFIGS:
                per_config[name].append(
                    metrics.ranking_metrics(ret[lane], row["gold_ids"]))

    lines = [f"| config | " + " | ".join(KEYS) + " |",
             "|---|" + "---|" * len(KEYS)]
    print(f"\n{'config':<18}" + "".join(f"{k:>11}" for k in KEYS))
    for name, _ in CONFIGS:
        agg = {k: metrics.mean_of(per_config[name], k) for k in KEYS}
        print(f"{name:<18}" + "".join(f"{agg[k]:>11.3f}" for k in KEYS))
        lines.append(f"| {name} | " +
                     " | ".join(f"{agg[k]:.3f}" for k in KEYS) + " |")

    out = Path(__file__).resolve().parent / "results" / "ablation.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        f"# Retrieval ablation ({meta['timestamp']}, commit "
        f"{meta['git_sha']}, n={len(rows)})\n\n" + "\n".join(lines) + "\n",
        encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

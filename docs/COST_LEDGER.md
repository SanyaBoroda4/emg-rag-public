# Cost ledger

What the build cost in API spend, summed from committed files only. Two
independent methods are shown because they measure different things; the
README quotes both and neither is an estimate.

## Method A — eval run files (machine-recorded)

Every eval run writes `meta.total_cost_usd` (single-question runs) or
`summary.cost_usd` (conversation-tier runs) into its JSON under
`evals/results/`, computed per model call from `retrieval/pricing.py`. Summing
every run file in the repo:

```
python - <<'PY'
import json, glob
tot = 0
for p in sorted(glob.glob("evals/results/*.json")):
    d = json.load(open(p, encoding="utf-8"))
    c = d.get("meta", {}).get("total_cost_usd") or d.get("summary", {}).get("cost_usd") or 0
    tot += c
print(round(tot, 2))
PY
```

| as of commit | run files | sum |
|---|---|---|
| `1aaa84f` (before the WO20 measurement runs) | 43 | **$28.41** |

This counts only evaluation runs: the golden-set evals, subsets, ablations,
the model benchmark, determinism repeats and the conversation tier. It does
not count ad-hoc CLI questions, smoke tests, re-judge passes (written to
`/tmp`, not committed) or ingestion.

## Method B — per-work-order cost sections (hand-recorded)

Each work-order report ends with a Cost section that adds up that order's
eval runs, smoke tests and any batch jobs. Phase rows in `HANDOFF.md` carry
the ingestion figures.

| work | cost | source |
|---|---|---|
| Phase 3 — chunk contextualisation (Haiku Batch API) | $1.93 | `HANDOFF.md`, phase row 3 |
| Phase 5 — 2,909 chunks re-contextualised | $0.74 | `HANDOFF.md`, phase row 5 |
| Phase 7 — fix eval-found bugs | ≈ $2.60 | `HANDOFF.md`, phase row 7 |
| One canonical pipeline definition | ≈ $1.65 | `evals/results/wo_pipeline_unification.md` |
| Activity reality + JOIN fan-out | ≈ $2.95 | `evals/results/wo_activity_reality.md` |
| WO8 — wasted templates | ≈ $2.07 | `evals/results/wo_wasted_templates.md` |
| WO9 — status widening | ≈ $2.70 | `evals/results/wo9_status_widening.md` |
| WO10 — determinism, latency (incl. addendum) | ≈ $4.24 | `evals/results/wo10_determinism_latency.md` |
| WO11 — re-key, quoted jobs | ≈ $1.59 | `evals/results/wo11_rekey.md` |
| WO12 — Langfuse | ≈ $1.11 | `evals/results/wo12_langfuse.md` |
| WO13 — answer determinism, slow query | ≈ $3.98 | `evals/results/wo13_determinism_slow_sql.md` |
| WO14 — COUNT(*) skip, judge measured | ≈ $5.70 | `evals/results/wo14_count_skip_judge.md` |
| WO15 — quoted-jobs diagnostic | $0 | `evals/results/wo15_quoted_jobs_diagnostic.md` |
| WO16 — serving | ≈ $1.20 | `evals/results/wo16_serving.md` |
| WO17 — conversational follow-ups | ≈ $3.15 | `evals/results/wo17_followups.md` |
| WO18 — dark console | $0 | `evals/results/wo18_restyle.md` |
| WO19 — public mirror audit | $0 | `docs/wo19_public_audit.md` |
| WO20 — correctness pass | see `evals/results/wo20_correctness.md` | |
| WO21 — portfolio polish | $0 (no model calls) | `docs/wo21_portfolio.md` |
| **Sum of the rows above (through WO19)** | **≈ $35.61** | |

Not documented anywhere, therefore not counted: phases 1–2 (no model
calls), phase 4's seven smoke queries, phase 6's baseline runs beyond what
Method A already holds, Voyage embedding calls (the reports call them
"pennies" without a figure), the Langfuse Hobby tier ($0 by plan), and the
Hetzner server, which predates the project and hosts other services.

There is no Langfuse export in the repository (the free tier keeps 30 days
and the run JSONs are the durable record), so no number here comes from
Langfuse.

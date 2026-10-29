# Resume facts

Every resume-worthy number, each with the committed file it comes from and
the commit that produced it. Resume bullets are drafted from this file only;
if a number is not here, it is not on the resume. Employee names never
appear; customer data never appears.

## Scale of the system

| fact | source | commit |
|---|---|---|
| 5,569 jobs, 44,495 activities, 12,201 forms, 149,364 fields, 5,257 invoices loaded, every count reconciled to the source | `HANDOFF.md`, phase row 2 | `2b9c5fb` or later |
| 7,194 note chunks with model-written context sentences, zero batch failures, $1.93 | `HANDOFF.md`, phase row 3 | same |
| 294 raw city spellings → 68 canonical areas, raw column never modified | `HANDOFF.md`, phase row 5 | same |
| 21 SQL migrations, all additive and idempotent | `sql/` (001–021) | `1e4a4e6` |
| 82-question golden set (55 verified, 27 draft) + 15 golden conversations, 38 turns | `evals/golden_set.csv`, `evals/golden_conversations.csv` | `1e4a4e6` |

## Measured quality (WO20 final runs at `a070597`, 2026-09-21)

| fact | source | commit |
|---|---|---|
| routing accuracy 96.3% on 82 questions | `evals/results/2026-09-21-1359-wo20-full3.json`, `tier1.accuracy` | `a070597` |
| generation 75 of 82 judged correct in both final runs, judge floor ±1 | `evals/results/2026-09-21-1359-wo20-full3.json`, `2026-09-21-1411-wo20-full4.json`; floor: `evals/results/wo14_count_skip_judge.md` | `a070597`; `126da85` |
| faithfulness 0.962 and 0.924 | run JSONs, `tier3.faithfulness` | `a070597` |
| reranked recall@10 0.818, MRR 0.660 | run JSONs, `tier2.reranked` | `a070597` |
| follow-up turns correct 16–17 of 19 (four runs), standalone pass-through 19 of 19 every run | `evals/results/wo20_correctness.md`, §8 | `a070597` |
| Q30 judged ✓ in 3 of 3 re-judges after the provenance rule | `evals/results/wo20_correctness.md`, §8 | `a070597` |
| full eval: $1.04 and 605 s per run (1 worker; 319 s with 4 workers per WO10) | run JSON `meta`; `evals/results/wo10_determinism_latency.md` | `a070597` |

## Before → after, by work order

| fact | source | commit |
|---|---|---|
| generation 48.3% → 60.3%, faithfulness 65.5% → 81.8% (Phase 7) | `evals/results/before_after.md` | phase 7 |
| generation 60.3% → 69.8%, faithfulness 81.8% → 90.0% (activity reality) | `evals/results/wo_activity_reality.md` | see report |
| quote conversion definition unified; rate 65.9% → 70.0% (3,063 of 4,377) | `evals/results/wo_pipeline_unification.md` | see report |
| wasted-template rule reproduces 10 of 10 hand verdicts; 252 of 3,643 trips (6.9%) | `evals/results/wo9_status_widening.md` | see report |
| crew-workload questions 1 of 10 → 10 of 10 | `evals/results/wo9_status_widening.md` | see report |
| full eval wall time 780 s → 319 s with 4 workers, identical scores | `evals/results/wo10_determinism_latency.md` | `1022892` |
| existence questions 1 of 13 → 10 of 13 after re-keying | `evals/results/wo11_rekey.md` | see report |
| `sql_execute` p95 1.96 s → 0.40 s with one 184 kB partial index; view 1,167 → 326 ms, identical output | `evals/results/wo13_determinism_slow_sql.md` | `sql/018` |
| `sql_execute` p95 0.40 → 0.20 s by skipping 47 of 59 redundant COUNT(*) executions | `evals/results/wo14_count_skip_judge.md` | `d11ff85` |
| judge measured over nine passes: 74–76 of 82, one 5 ✓ / 4 ✗ row; ±1 floor stated | `evals/results/wo14_count_skip_judge.md` | `126da85` |
| follow-ups 1 of 20 → 15–16 of 18; standalone byte-identical 20 of 20; $0.0014 and 1.8 s per rewrite | `docs/wo17-conversational-followups-report.md` | `7141016` |
| per-alias SQL validator: 116 of 116 recorded queries still accepted; a wrong-alias column is rejected before Postgres with the column, view and alias named; zero SQL errors in the final runs | `evals/results/wo20_correctness.md`, `tests/test_sql_validator.py` | `da5a346`, `a070597` |
| public mirror: 52 files with customer data found at HEAD, 0 in the sanitised tree; guard exits 1 on any hit | `docs/wo19_public_audit.md` | `81f0791` |

## Operations

| fact | source | commit |
|---|---|---|
| served on a 2 GB box shared with live production; API idle 122 MB, in flight 134 MB | `evals/results/wo16_serving.md` | `fd2ae61` |
| local reranker rejected by a 400 MiB memory gate (593 MiB peak); Voyage rerank API used instead | `HANDOFF.md`, server constraints | see file |
| tracing on every stage: judge 53% of call time, retrieval under 1%; +10 MB RSS | `evals/results/wo12_langfuse.md` | `aae90bc` |
| total API spend: $28.41 in run files; ≈ $35.61 by work-order cost sections through WO19 | `docs/COST_LEDGER.md` | `1e4a4e6` |

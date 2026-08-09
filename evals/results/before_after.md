# WO7 before/after — every metric, with the fix responsible

Baseline = WO6 full run (2026-08-08-2133.json, commit `64126b6`).
Final = WO7 round-3 run (2026-08-09-2253.json, commit `aa69240`).
Three measured rounds: R1 = bug fixes A–D + scorer + judge-evidence;
R2 = schema-prompt disambiguation after R1 exposed enumeration side effects;
R3 = deterministic un-LIMITed total count in the SQL lane.

| tier | metric | WO6 | WO7 final | Δ | driven by |
|---|---|---|---|---|---|
| 1 | routing accuracy | 94.8% (55/58) | 94.8% (55/58); 96.6% in R2 | ±1 question run-to-run | Q16+Q26 fixed by domain-vocabulary prompt (Bug B/D); Q50 regression introduced in R1, fixed in R2; residual flip is router nondeterminism on 1–2 borderline semantic questions |
| 2 | R@10 post-rerank | 0.522 | 0.522 | 0 | intentionally untouched — no retrieval changes in WO7 |
| 2 | MRR post-rerank | 0.441 | 0.441 | 0 | same |
| 3 | generation accuracy | 48.3% (28/58) | **60.3% (35/58)** | **+12.0 pts** | see per-fix table below |
| 3 | faithfulness | 65.5% | **81.8%** | **+16.3 pts** | judge now sees SQL rows (was branding row-derived claims fabrications); bot-note tagging; true-total counts |
| 3 | context precision | 48.6% | **64.3%** | +15.7 pts | bot-record tagging + better routing pulling fewer junk chunks into answers |

## Question-level attribution (verified/FAILING rows)

| Q | WO6 | WO7 | fix responsible |
|---|---|---|---|
| Q5 (salespeople list) | fail | **pass** | scorer: list-shaped answers check every number, not the first |
| Q10 (revenue growth) | fail | **pass** | scorer: $2.59M suffix normalization (R1) + invoice-status enumeration (R2 — R1 SQL invented `status='Paid in Full'`, 0 rows) |
| Q12 (Dallas White jobs) | fail | **pass** | Alex's spec decision (152, job-level substring) |
| Q16 (quotes issued) | fail (router refused) | **pass** | Bug B: activity types are domain vocabulary |
| Q20 (no city recorded) | fail | **pass** | Alex's spec decision (1,779; system had been right) |
| Q21 (Charleston proper) | fail (371) | **pass** (81) | Bug A: canonical city column = exact match, values enumerated |
| Q26 (went quiet after quote) | fail | **pass** | Bug D: routes structured + stall definition in schema prompt |
| Q29 (tile work) | fail (16 → 200) | **pass** (246) | Bug C in two parts: value enumeration made SQL consult `type_name` (16→200), deterministic un-LIMITed COUNT fixed the truncated total (200→246) |
| Q28 (sink change of mind) | fail | fail | genuine near-miss: retrieval now surfaces Canfora but the answer still drops Stabler. Judge verified correct-to-refuse-loosening (probe: judge is right) |
| Q30 (stalled quartzite + salesperson) | fail | fail | answer finds the 1 job; judge dings phrasing of "no comment documented". Borderline judge strictness, left strict per WO |

Regressions found by measurement and fixed within WO7 (R1 → R2): Q1/Q34
(assignee-enumeration lured SQL away from `salesperson`), Q13 (`IS NULL` vs
`''`), Q17 ("area" = geography at EMG), Q50 (router refused by assuming notes
don't track languages). All four categories are now schema-prompt rules.
Semantic rows Q45/Q49 flip run-to-run (judge/retrieval nondeterminism ±2
questions) — reported, not papered over.

## CI baselines

Unchanged (`evals/baseline.json`): routing 0.948 and reranked R@10 0.522 are
exactly reproduced by the final run; nothing regressed, nothing to rebaseline.

## Cost

WO7 total ≈ **$2.60** (three tier-3 runs + judge probe + router calls), under
the $5 budget. Judge separation maintained throughout (Haiku answers, Sonnet
judge).

# Eval run 2026-09-08 21:31:22

commit `d19b336` · answer=claude-haiku-4-5 · sql=claude-haiku-4-5 · judge=claude-sonnet-5 · rerank=voyage

## Tier 1 — routing

Accuracy: **96.3%**

```
expected \ predicted    structured    semantic      hybrid      refuse
structured                      53           0           0           0
semantic                         2          20           1           0
hybrid                           0           0           3           0
refuse                           0           0           0           3
```

## Tier 2 — retrieval (per lane)

| lane | R@5 | R@10 | R@20 | MRR | NDCG@10 |
|---|---|---|---|---|---|
| bm25 | 0.087 | 0.130 | 0.174 | 0.102 | 0.101 |
| dense | 0.293 | 0.293 | 0.478 | 0.232 | 0.226 |
| fused | 0.217 | 0.370 | 0.467 | 0.165 | 0.207 |
| reranked | 0.446 | 0.522 | 0.609 | 0.441 | 0.454 |

## Tier 3 — generation

- correct: **50/82 (61.0%)**
- faithfulness: 87.3%
- context precision: 62.5%
- generator: claude-haiku-4-5 · judge: claude-sonnet-5 (never the same model)
- tier-3 cost: $0.92

Known-FAILING: Q28 still failing, Q30 still failing
New failures (verified rows): Q14, Q16, Q29, Q64, Q65, Q66, Q67, Q68, Q69, Q70, Q71, Q73

# Eval run 2026-08-09 16:29:11

commit `2eef921` · answer=claude-haiku-4-5 · sql=claude-haiku-4-5 · judge=claude-sonnet-5 · rerank=voyage

## Tier 1 — routing

Accuracy: **96.6%**

```
expected \ predicted    structured    semantic      hybrid      refuse
structured                      31           0           0           0
semantic                         2          21           0           0
hybrid                           0           0           1           0
refuse                           0           0           0           3
```

## Tier 2 — retrieval (per lane)

| lane | R@5 | R@10 | R@20 | MRR | NDCG@10 |
|---|---|---|---|---|---|
| bm25 | 0.087 | 0.130 | 0.174 | 0.102 | 0.101 |
| dense | 0.293 | 0.293 | 0.478 | 0.235 | 0.228 |
| fused | 0.217 | 0.370 | 0.467 | 0.165 | 0.207 |
| reranked | 0.446 | 0.522 | 0.609 | 0.441 | 0.454 |

## Tier 3 — generation

- correct: **35/58 (60.3%)**
- faithfulness: 76.4%
- context precision: 53.8%
- generator: claude-haiku-4-5 · judge: claude-sonnet-5 (never the same model)
- tier-3 cost: $0.57

Known-FAILING: Q16 PASSES(!), Q20 PASSES(!), Q21 PASSES(!), Q26 PASSES(!), Q29 still failing
New failures (verified rows): Q28, Q30

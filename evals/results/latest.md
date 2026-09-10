# Eval run 2026-09-10 16:27:21

commit `2fc04c4` · answer=claude-haiku-4-5 · sql=claude-haiku-4-5 · judge=claude-sonnet-5 · rerank=voyage

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

- correct: **60/82 (73.2%)**
- faithfulness: 87.3%
- context precision: 60.4%
- generator: claude-haiku-4-5 · judge: claude-sonnet-5 (never the same model)
- tier-3 cost: $1.02

Known-FAILING: Q28 still failing, Q30 still failing
New failures (verified rows): Q16

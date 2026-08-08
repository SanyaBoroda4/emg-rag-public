# Eval run 2026-08-08 21:07:09

commit `64126b6` · answer=claude-haiku-4-5 · sql=claude-sonnet-5 · judge=claude-sonnet-5 · rerank=voyage

## Tier 1 — routing

Accuracy: **94.8%**

```
expected \ predicted    structured    semantic      hybrid      refuse
structured                      29           1           0           1
semantic                         1          22           0           0
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

- correct: **28/58 (48.3%)**
- faithfulness: 65.5%
- context precision: 48.6%
- generator: claude-haiku-4-5 · judge: claude-sonnet-5 (never the same model)
- tier-3 cost: $0.69

Known-FAILING: Q26 still failing, Q29 still failing
New failures (verified rows): Q5, Q10, Q11, Q12, Q16, Q20, Q21, Q28, Q30

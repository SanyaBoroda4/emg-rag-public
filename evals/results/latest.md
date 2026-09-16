# Eval run 2026-09-16 10:00:38

commit `126da85` · answer=claude-haiku-4-5 · sql=claude-haiku-4-5 · judge=claude-sonnet-5 · rerank=voyage

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
| bm25 | 0.091 | 0.091 | 0.182 | 0.111 | 0.091 |
| dense | 0.280 | 0.280 | 0.576 | 0.326 | 0.273 |
| fused | 0.273 | 0.500 | 0.644 | 0.196 | 0.256 |
| reranked | 0.674 | 0.818 | 0.909 | 0.660 | 0.691 |

## Tier 3 — generation

- correct: **75/82 (91.5%)**
- faithfulness: 94.9%
- context precision: 61.1%
- generator: claude-haiku-4-5 · judge: claude-sonnet-5 (never the same model)
- tier-3 cost: $0.96

## Stage timing (whole run)

```
stage        seconds % of sum  calls
router         124.9    19.4%     82
embed            0.5     0.1%      1
bm25             0.9     0.1%     26
dense            0.9     0.1%     26
rerank           4.9     0.8%     26
sql             83.9    13.0%     59
answer         124.4    19.3%     79
judge          304.5    47.2%     79
sum            644.9   100.0%
wall           262.3     (stages overlap across 4 workers; no gap row)
```

Known-FAILING: 
New failures (verified rows): Q30, Q45, Q47, Q49

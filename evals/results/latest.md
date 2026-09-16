# Eval run 2026-09-16 08:44:23

commit `a03a724` · answer=claude-haiku-4-5 · sql=claude-haiku-4-5 · judge=claude-sonnet-5 · rerank=voyage

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

- correct: **74/82 (90.2%)**
- faithfulness: 94.9%
- context precision: 63.2%
- generator: claude-haiku-4-5 · judge: claude-sonnet-5 (never the same model)
- tier-3 cost: $0.98

## Stage timing (whole run)

```
stage        seconds % of sum  calls
router         108.5    16.7%     82
embed            0.5     0.1%      1
bm25             0.8     0.1%     26
dense            0.9     0.1%     26
rerank           4.8     0.7%     26
sql             83.8    12.9%     59
answer         120.3    18.6%     79
judge          328.5    50.7%     79
sum            648.1   100.0%
wall           249.8     (stages overlap across 4 workers; no gap row)
```

Known-FAILING: 
New failures (verified rows): Q30, Q45, Q47, Q48, Q49

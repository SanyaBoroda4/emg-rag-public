# Eval run 2026-09-14 09:15:46

commit `446c30e` · answer=claude-haiku-4-5 · sql=claude-haiku-4-5 · judge=claude-sonnet-5 · rerank=voyage

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
- faithfulness: 89.9%
- context precision: 59.0%
- generator: claude-haiku-4-5 · judge: claude-sonnet-5 (never the same model)
- tier-3 cost: $1.04

## Stage timing (whole run)

```
stage        seconds   % wall  calls
router         113.4    41.8%     82
embed            3.2     1.2%      1
bm25             0.8     0.3%     26
dense            0.9     0.3%     26
rerank           5.3     1.9%     26
sql             91.3    33.7%     59
answer         125.9    46.4%     79
judge          372.5   137.4%     79
sum            713.3   263.0%
wall           271.2   100.0%
gap           -442.1  -163.0%
```

Known-FAILING: 
New failures (verified rows): Q26, Q45, Q47, Q49

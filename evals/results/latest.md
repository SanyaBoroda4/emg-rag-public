# Eval run 2026-09-15 21:02:46

commit `aae90bc` · answer=claude-haiku-4-5 · sql=claude-haiku-4-5 · judge=claude-sonnet-5 · rerank=voyage

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

- correct: **76/82 (92.7%)**
- faithfulness: 88.6%
- context precision: 63.9%
- generator: claude-haiku-4-5 · judge: claude-sonnet-5 (never the same model)
- tier-3 cost: $1.01

## Stage timing (whole run)

```
stage        seconds % of sum  calls
router         112.5    15.8%     82
embed            0.3     0.0%      1
bm25             0.8     0.1%     26
dense            0.9     0.1%     26
rerank           4.0     0.6%     26
sql             90.3    12.7%     59
answer         127.8    17.9%     79
judge          376.4    52.8%     79
sum            713.0   100.0%
wall           269.5     (stages overlap across 4 workers; no gap row)
```

Known-FAILING: 
New failures (verified rows): Q28, Q45, Q47

# Eval run 2026-09-14 08:24:48

commit `ff101ab` · answer=claude-haiku-4-5 · sql=claude-haiku-4-5 · judge=claude-sonnet-5 · rerank=voyage

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

- correct: **59/82 (72.0%)**
- faithfulness: 91.1%
- context precision: 56.2%
- generator: claude-haiku-4-5 · judge: claude-sonnet-5 (never the same model)
- tier-3 cost: $0.98

## Stage timing (whole run)

```
stage        seconds   % wall  calls
router         116.4    15.8%     82
embed            0.5     0.1%      1
bm25             0.8     0.1%     26
dense            0.8     0.1%     26
rerank           5.3     0.7%     26
sql             92.3    12.5%     59
answer         127.3    17.3%     79
judge          392.8    53.3%     79
sum            736.2    99.9%
wall           737.0   100.0%
gap              0.8     0.1%
```

Known-FAILING: Q28 still failing, Q30 still failing
New failures (verified rows): Q16, Q68

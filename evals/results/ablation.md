# Retrieval ablation (2026-08-09 16:54:05, commit 677aa6c, n=23)

| config | recall@5 | recall@10 | recall@20 | mrr | ndcg@10 |
|---|---|---|---|---|---|
| bm25 only | 0.087 | 0.130 | 0.174 | 0.102 | 0.101 |
| dense only | 0.293 | 0.293 | 0.478 | 0.232 | 0.226 |
| RRF, no rerank | 0.217 | 0.370 | 0.467 | 0.165 | 0.207 |
| RRF + rerank | 0.446 | 0.522 | 0.609 | 0.441 | 0.454 |

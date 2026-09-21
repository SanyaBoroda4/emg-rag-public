# Model benchmark (2026-08-08 21:51:46, commit 64126b6)

## ANSWER_MODEL (full set; judge is always the other model)

| model | accuracy | faithfulness | latency | gen cost | $/correct |
|---|---|---|---|---|---|
| claude-haiku-4-5 | 30/58 (51.7%) | 62.5% | 1.65s | $0.204 | $0.0068 |
| claude-sonnet-5 | 27/58 (46.6%) | 45.8% | 3.96s | $0.336 | $0.0124 |

## SQL_MODEL (structured subset, numeric scoring)

| model | accuracy | sql failures | latency | cost | $/correct |
|---|---|---|---|---|---|
| claude-sonnet-5 | 17/31 (54.8%) | 0 | 4.81s | $0.135 | $0.0079 |
| claude-haiku-4-5 | 18/31 (58.1%) | 0 | 2.99s | $0.057 | $0.0032 |

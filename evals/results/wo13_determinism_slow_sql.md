# WO13 — Determinism, slow queries, and judge latency

Date: 2026-09-16 · commits `f5a3d57` (Change 1), `a03a724` (Change 2) + this
report · baseline WO12 session `eval-20260915-2102-aae90bc` @ `14cccc8`

Five full evals: three consecutive for the determinism test, one final, plus
the WO12 baseline for comparison. Cost ≈ $4.10 (budget $5).

## Headline

| | before (WO12) | after (WO13 final) |
|---|---|---|
| answer-model sampling flips between runs | 4 questions (Q26, Q28, Q49, Q58) | **0** — every verdict flip left is the judge's |
| `sql_execute` p95 | **1.96 s** | **0.40 s** |
| `sql_execute` max | 2.40 s | 0.60 s |
| `sql_execute` total per run | 12.4 s | 4.7 s |
| slowest generated query (Q74) | 2.40 s | 0.60 s |
| judge | untouched | untouched |

## Change 1 — `temperature=0` on the answer model (commit `f5a3d57`)

One line in `retrieval/answer.py`. Router, SQL lane and judge untouched.

Three consecutive full evals on the same code (run 2 and 3 report commit
`a03a724` because the server auto-pulled the migration *file* between runs;
it was not applied until after run 3, and it contains no code):

| run | session | generation | failing set |
|---|---|---|---|
| 1 · `2026-09-16-0834` | `eval-20260916-0829-f5a3d57` | 75/82 | 11, 41, 45, 47, 49, 56, **58** |
| 2 · `2026-09-16-0838` | `eval-20260916-0834-a03a724` | 75/82 | 11, **30**, 41, 45, 47, 49, 56 |
| 3 · `2026-09-16-0842` | `eval-20260916-0838-a03a724` | 76/82 | 11, 41, 45, 47, 49, 56 |

The four WO12 flip-floppers across the three runs: **Q26 ✓ ✓ ✓ · Q28 ✓ ✓ ✓ ·
Q49 ✗ ✗ ✗ · Q58 ✗ ✓ ✓**.

**Verdict: the pipeline is deterministic; the failing sets are not, and the
difference is entirely the judge.** The evidence, from the three run JSONs:

- Retrieved chunk sets identical on **82/82** questions across all three runs.
- The two questions whose verdict moved, Q30 and Q58, had **byte-identical
  answer text, SQL, rows and chunks** in all three runs. Only the Sonnet
  verdict differed (Q30: "cites job 180 as a salesperson comment" was
  tolerated twice and penalised once; Q58: "expands to jobs 996, 2394,
  2681" was penalised once and tolerated twice).
- Three more questions (Q40, Q49, Q54) had identical answers but a
  faithfulness verdict that differed between runs — same cause.
- Below the verdict line, `temperature=0` is not byte-deterministic at the
  API: identical answer text on 60/82, identical SQL text on 76/82. None of
  those textual differences changed a verdict; the WO10 finding repeats
  (identical outcomes, not identical bytes).

So `temperature=0` did what it was asked to do — the answerer no longer
flips outcomes — and what still varies is the judge: Sonnet 5 with adaptive
thinking, default temperature, out of scope by Alex's decision in Change 3.
Per the work order this is where Change 1 stops; nothing was done to the
judge. What it means for reading scores: a ±1 swing (75 ↔ 76) is judge
noise on the two or three borderline semantic rows; a system change now has
to move the failing set, not the count.

**Accuracy:** 75–76/82 against WO12's 74–76/82 on the same golden set. No
drop.

## Change 2 — the slow-query tail (commit `a03a724`, `sql/018_perf_indexes.sql`)

### 1. Identified (Langfuse session `eval-20260915-2102-aae90bc`, `sql_execute` > 0.5 s)

59 `sql_execute` spans: median 0.030 s, p95 1.957 s, max 2.397 s. Five above
0.5 s — **every one a query on `v_wasted_templates`**, and every other query
in the run under 0.5 s:

| q | question | run time | rows | SQL (verbatim) |
|---|---|---|---|---|
| Q74 | How many wasted templates have we had in total? | 2.40 s | 1 | `SELECT COUNT(*) AS wasted_templates FROM v_wasted_templates WHERE wasted LIMIT 200` |
| Q40 | Were there jobs where we could not template because the cabinets were not ready? | 2.39 s | 17 | `SELECT DISTINCT job_id, job_name, salesperson, city, template_date, wasted_reason, matched_note FROM v_wasted_templates WHERE wasted AND matched_note ILIKE '%cabinet%' ORDER BY template_date DESC LIMIT 200` |
| Q82 | Which jobs had a template wasted because cabinets weren't ready? | 2.35 s | 16 | `SELECT DISTINCT job_id FROM v_wasted_templates WHERE wasted AND matched_note ILIKE '%cabinet%' ORDER BY job_id LIMIT 200` |
| Q76 | Which salesperson had the most wasted templates? | 1.96 s | 10 | `WITH wasted_by_pm AS (SELECT salesperson, SUM(CASE WHEN wasted THEN 1 ELSE 0 END) AS wasted_count FROM v_wasted_templates WHERE salesperson <> '' AND salesperson IS NOT NULL GROUP BY salesperson) SELECT salesperson, wasted_count FROM wasted_by_pm ORDER BY wasted_count DESC LIMIT 1` |
| Q75 | How many wasted templates in 2025? | 0.89 s | 1 | `SELECT COUNT(*) AS wasted_templates FROM v_wasted_templates WHERE wasted AND template_year = 2025 LIMIT 200` |

The `ILIKE '%cabinet%'` in Q40/Q82 is **not** the cost — it filters 252
already-computed rows. The cost is the view itself: whatever the WHERE, it
materialises all 3,643 real template trips and runs the wasted rule on each.

### 2. Explained — `EXPLAIN (ANALYZE, BUFFERS)` on Q74 (1,172 ms in Postgres; the other four have the same plan)

```
Aggregate (actual time=1171.288..1171.300 rows=1)
  Buffers: shared hit=36588
  -> Nested Loop (actual time=42.586..1171.220 rows=252)
       CTE real_events
         -> Index Scan using idx_activities_date on activities a (actual time=0.029..17.496 rows=9150)
              Index Cond: ((activity_date <= p_1.as_of) AND (activity_date IS NOT NULL))
              Filter: ((type_name = ANY ('{Template,Install}')) AND (status_name = ANY (p_1.real_statuses)))
              Rows Removed by Filter: 15716                                       -- 18 ms
       CTE seq  -> WindowAgg ... Incremental Sort ... rows=3643                     -- 36 ms
       CTE installs -> CTE Scan on real_events (rows=5489)                          -- 1 ms
       -> Nested Loop (actual time=42.552..1170.172 rows=252)                       -- 1,128 ms  <== here
            Join Filter: (((s.next_template_date IS NOT NULL) AND (NOT EXISTS(SubPlan 5)))
                          OR (own note ~* readiness_re ...) OR ((SubPlan 6) IS NOT NULL)
                          OR (next_template_note ~* redo_re ...))
            Rows Removed by Join Filter: 3391
            -> Hash Join (rows=3643)  seq x phase_bounds                           -- 43 ms
            SubPlan 5   (install between two templates?)
              -> CTE Scan on installs i (actual time=0.215..0.215 rows=1 loops=579)
                   Filter: ((activity_date > s.activity_date) AND (activity_date < s.next_template_date) AND (job_id = s.job_id))
                   Rows Removed by Filter: 4090                                    -- 579 x 0.215 ms = 125 ms
            SubPlan 6   (same-day Measure note with readiness language?)
              -> Limit (actual time=0.266..0.266 rows=0 loops=3399)
                   -> Sort (Sort Key: m.activity_id)
                        -> Index Scan using idx_activities_job_id on activities m (actual time=0.265..0.265 rows=0 loops=3399)
                             Index Cond: (job_id = s.job_id)
                             Filter: ((notes ~* p.readiness_re) AND (type_name = 'Measure') AND (activity_date = s.activity_date))
                             Rows Removed by Filter: 11
                             Buffers: shared hit=13944                             -- 3399 x 0.266 ms = 904 ms  <== the cause
       -> Index Only Scan using jobs_pkey on jobs j (loops=252)
Planning Time: 2.4 ms
Execution Time: 1172.4 ms
```

Reading it: no sequential scans (the base `activities` scan already uses
`idx_activities_date`), no `ILIKE` in the hot path, no join to `v_job_sqft`
or the pipeline view. The whole 1.1 s is **Step 3b of the view** —
"is there a Measure activity on the same job, same day, whose note has
readiness language?" — a correlated subquery run once per template trip
(3,399 loops). Each loop walked `idx_activities_job_id` to the job's ~11
activities and regex-matched every note before discarding all but the
same-day Measures. 0.27 ms × 3,399 = 0.9 s. SubPlan 5 (125 ms) is the
"install between templates" check scanning the `installs` CTE per trip.

### 3. Fixed — one partial composite index (additive; view untouched)

```sql
CREATE INDEX IF NOT EXISTS idx_activities_measure_job_date
    ON activities (job_id, activity_date)
    WHERE type_name = 'Measure';
```

184 kB (5,284 Measure rows of 44,495). SubPlan 6's index condition becomes
`(job_id = s.job_id) AND (activity_date = s.activity_date)` on Measure rows
only: **0.266 ms → 0.009 ms per loop**, `Rows Removed by Filter: 0`. Tested
first inside `BEGIN … ROLLBACK`, then applied one index at a time with
`free -m` before/after: 1,107 MB → 1,091 MB available (the 16 MB is page
cache, not the index). `pg_trgm` is available (1.6, not installed) but was
not needed — `ILIKE` was never the bottleneck. No view rewrite.

**Output provably unchanged:** md5 of the full ordered result set, before
and after the index —
`v_wasted_templates` 3,643 rows `507e92da4e844beb3a6f16208b3701f3` → same;
`v_wasted_templates_by_pm` 51 rows `d02ce3a9419d2f23f091f4a430ce453f` →
same. Q74 = 252, Q75 = 48, Q82 = the same 16 job ids.

Not taken: SubPlan 5 (125 ms) reads a CTE, which no index can reach; taking
it needs the view to test `EXISTS` against `activities` directly with an
index on `(job_id, activity_date) WHERE type_name = 'Install'`. That is a
view rewrite — out of scope for an additive migration — and would bring
the view from ~0.3 s to ~0.15 s. Noted for later.

### 4. Re-measured (final session `eval-20260916-0844-a03a724`)

| `sql_execute` | before (WO12 session) | after (final session) |
|---|---|---|
| calls | 59 | 59 |
| median | 0.030 s | 0.031 s |
| **p95** | **1.957 s** | **0.401 s** |
| max | 2.397 s | 0.601 s |
| total | 12.4 s | 4.7 s |
| share of call time | 1.7% | 0.7% |

Per query, in the eval (Postgres-only time from psql in brackets):

| q | before | after | speed-up |
|---|---|---|---|
| Q74 | 2.40 s | 0.60 s [0.29 s] | 4.0× |
| Q40 | 2.39 s | 0.40 s | 6.0× |
| Q82 | 2.35 s | 0.40 s [0.18 s] | 5.9× |
| Q76 | 1.96 s | 0.59 s | 3.3× |
| Q75 | 0.89 s | 0.59 s [0.29 s] | 1.5× |

Eval-run times include the psycopg round trip and the concurrent `COUNT(*)`
re-execution the lane does to report true totals under the forced LIMIT
(which runs the view a second time — the reason Q74/Q75 are 0.6 s in the
run but 0.29 s in psql). The 60× median-to-p95 spread the WO opened with
is now 13×, and the p95 query is the same view at 0.4 s.

## Change 3 — judge: left untouched, recorded

For completeness, from the final session: judge 79 calls, 328.5 s, median
2.38 s, p95 13.94 s, $0.46 of $1.06, 50.9% of summed call time. Nothing in
the judge's prompt, model, evidence or thinking budget changed in this WO
(`evals/harness.py` diff since `14cccc8`: none). It runs only inside the
eval and is excluded from the production latency picture — a user waiting
on a question sees router + SQL/retrieval + answer, roughly 3–5 s, of which
`sql_execute` is now at most 0.6 s.

## Final eval vs WO12 baseline

| run | commit | routing | generation | faithfulness | ctx precision | cost | wall |
|---|---|---|---|---|---|---|---|
| WO12 `2026-09-15-2107` | `aae90bc` | 96.3% | 76/82 (92.7%) | 88.6% | 63.9% | $1.09 | 270 s |
| WO13 det 1/2/3 | `f5a3d57` | 96.3% | 75 / 75 / 76 | 93.7% ×3 | 61.8 / 66.7 / 64.6 | $0.95–1.00 | 135–148 s tier 3 |
| **WO13 final `2026-09-16-0848`** | `a03a724` | 96.3% | **74/82 (90.2%)** | **94.9%** | 63.2% | **$1.06** | **250 s** |

Langfuse stage table, final session (4 workers; shares of summed call time):

| stage | calls | total s | median s | p95 s | share | $ |
|---|---|---|---|---|---|---|
| judge | 79 | 328.5 | 2.38 | 13.94 | 50.9% | 0.4605 |
| answer | 79 | 119.6 | 1.20 | 3.08 | 18.5% | 0.1377 |
| router | 82 | 107.8 | 1.34 | 1.70 | 16.7% | 0.0785 |
| sql_generate | 59 | 78.4 | 1.14 | 2.61 | 12.1% | 0.3831 |
| rerank | 26 | 4.8 | 0.16 | 0.27 | 0.7% | — |
| **sql_execute** | 59 | **4.7** | 0.03 | **0.40** | 0.7% | — |
| dense / bm25 / validate / fuse | | 1.9 | | | 0.3% | — |
| **all** | | 645.7 | | | 100% | 1.0597 |

Wall 270 s → 250 s; summed call time 710.5 s → 645.7 s (judge ran 48 s
faster on its own — natural variance in Sonnet's thinking, not anything
done here — and `sql_execute` 7.7 s faster, which is the index). Cost $1.09
→ $1.06. The work order's "cost down from caching" line has no
corresponding change in this WO; nothing was cached.

## Got worse — prominently

**The final run scored 74/82, below all three determinism runs (75/75/76).**
Both extra failures are the judge on unchanged answers: Q30 and Q48 had
byte-identical answer text, SQL, rows and chunks to determinism run 3
(where both passed). Q48's verdict this time: "omits job 3516, which the
expected answer explicitly cites as a key example" — the key says "e.g."
and the same answer was accepted in the three previous runs. Nothing in
the system got worse; the ruler wobbled by two. That is exactly the
residual Change 1 exposed and Change 3 declines to fix.

## Surprises

1. **Every slow query was one view.** Not a spread of bad plans — five
   queries, one cause, one 184 kB index. The `ILIKE` the WO suspected was
   innocent.
2. **The cause was a correlated regex subquery, not a scan.** The base
   scan was already indexed; the time was 3,399 executions of a per-row
   lookup that regex-matched ~11 notes each. Per-call tracing found it;
   `EXPLAIN` named it.
3. **`temperature=0` fixed the answerer and unmasked the judge.** With the
   answerer frozen, the same answer text gets different verdicts on 2–3
   borderline semantic rows per run. The score has a ±1 judge noise floor
   that only a temperature-0 (or majority-of-3) judge would remove — and
   that is Alex's call, deliberately not made here.
4. **Identical outcomes, not identical bytes, again.** 60/82 identical
   answers and 76/82 identical SQL at temperature 0 — the same
   near-determinism WO10 saw on the SQL lane.
5. **The lane runs every query twice.** The true-total `COUNT(*)` after the
   forced LIMIT re-executes the view; on a 0.3 s view that doubles the
   cost of a one-row answer. Cheap to fix (skip the count when the LIMIT
   was not hit) — not touched here, outside the WO.

## Cost

Three determinism runs $0.95 + $1.00 + $0.97 + final $1.06 + psql/EXPLAIN
$0 → **≈ $3.98**.

# WO12 — Langfuse observability

Date: 2026-09-15 · commits `5c15516` … `24a4526` (+ this report) · eval
`2026-09-15-2107-wo12.json` @ `aae90bc`, Langfuse session
`eval-20260915-2102-aae90bc`

Instrumentation only: no prompt, model, view or golden-set change. Four
deliverable commits as asked — client + spans (`5c15516`), CLI entry point
(`6a0299e`), eval entry point + scores (`aae90bc`), docs (`24a4526`).

## 1. What was built

`retrieval/tracing.py` wraps the langfuse **4.15.3** SDK: one client built
from `.env` with `LANGFUSE_BASE_URL` passed explicitly (the SDK also reads
that name natively in 4.x, so no rename was needed), `flush_at=20` /
`flush_interval=2 s` batched background export, `flush()` before exit.
Without keys it is a no-op; every SDK call is in `try/except`, so a
Langfuse failure logs (with `LANGFUSE_DEBUG=1`) and the query proceeds.

Spans live **inside the stage functions**, so both entry points inherit
them without knowing about tracing:

| span | type | in the trace as |
|---|---|---|
| `router` | generation | question → route + reason; model, tokens, cost |
| `bm25` / `dense` | retriever | chunk ids in rank order; AND/OR attempt for bm25 |
| `embed_query` | embedding | Voyage query embedding, token count (CLI path) |
| `fuse` | span | merged ordering with RRF scores and lane ranks |
| `rerank` | retriever | candidates in, top-k out with rerank scores, backend/model |
| `sql_generate` / `sql_repair` | generation | prompt → SQL; model, tokens, cost |
| `sql_validate` | span | rejected SQL = failed span with the validator's message |
| `sql_execute` | span | columns, row count, first rows; **Postgres error = failed span with error text** |
| `answer` | generation | chunk ids + SQL in, answer out; model, tokens, cost |
| `judge` | generation | verdict JSON; model, tokens, cost (eval only) |

Trace metadata: entry point, git sha, router/sql/answer models, rerank
backend, `route_expected` / `route_predicted`, and for eval rows
`question_id`, `status`, `tier`, `run_id`. An eval run is one **session**
(`eval-YYYYMMDD-HHMM-<sha>`, also a tag); each question's tier-1 router
call, tier-2 retrieval and tier-3 generation + judge share one
deterministic trace id (seeded by run id + question id), so the whole
question is one trace with three root spans.

Scores per eval trace: `correct` (0/1, judge reason as comment),
`faithfulness`, `context_precision`, `retrieval_recall_at_10` (rows with
gold ids), `sql_error` (only when the lane raised).

`retrieval/pricing.py` is now the single price table (the harness and the
CLI each had a copy).

**Not wired: `mcp_tool`.** The MCP server is the `emg_mcp` production
container, outside this repo and off-limits under the server rules. The
work order's third entry-point name is noted, not implemented.

## 2. Verification (§5 of the work order)

| check | result |
|---|---|
| `query.py "how many jobs in Mount Pleasant"` | one trace `query_cli`, spans router 2.59 s → sql_generate 0.78 s ($0.0060) → sql_validate → sql_execute 0.02 s (516) → answer 0.72 s; trace cost $0.0077 |
| `query.py "were there jobs where we could not get material into the building"` | router 1.62 s → bm25 0.04 s → embed_query 0.14 s → dense 0.04 s → fuse → rerank 0.17 s (6 chunks with scores 0.625…0.520) → answer 3.08 s; $0.0036 |
| full eval | 82 traces in session `eval-20260915-2102-aae90bc`, 696 observations, 196 scores |
| deliberate failure (`SELECT salesperson_nope FROM v_jobs`) | `sql_execute` at `level=ERROR`, status message `UndefinedColumn: column "salesperson_nope" does not exist` — the Q26 shape, one click away |
| keys removed (`LANGFUSE_PUBLIC_KEY= LANGFUSE_SECRET_KEY=`) | prints `[tracing] no LANGFUSE keys in the environment: tracing off`, answers normally ($0.0078) |

Read-back was through the public API (`/api/public/traces`,
`/observations`, `/scores`) from the server, not screenshots. One
practical note: fetching observations **per trace** trips the API's 429
rate limit at 82 traces; one bulk query over the run's time window works.

## 3. Stage timing — from Langfuse (replaces the broken table)

Session `eval-20260915-2102-aae90bc`, 82 questions, 4 workers, wall 270 s.

| stage | calls | total s | median s | p95 s | % of call time | total $ |
|---|---|---|---|---|---|---|
| judge (Sonnet 5) | 79 | 376.4 | 2.39 | **13.46** | **53.0%** | 0.4915 |
| answer (Haiku) | 79 | 127.2 | 1.23 | 3.90 | 17.9% | 0.1397 |
| router (Haiku) | 82 | 111.8 | 1.37 | 1.83 | 15.7% | 0.0784 |
| sql_generate (Haiku) | 59 | 76.9 | 1.17 | 2.60 | 10.8% | 0.3829 |
| sql_execute (Postgres) | 59 | 12.4 | 0.03 | 1.96 | 1.7% | — |
| rerank (Voyage) | 26 | 4.0 | 0.15 | 0.19 | 0.6% | — |
| dense | 26 | 0.9 | 0.03 | 0.05 | 0.1% | — |
| bm25 | 26 | 0.8 | 0.03 | 0.05 | 0.1% | — |
| sql_validate | 59 | 0.2 | 0.00 | 0.01 | 0.0% | — |
| fuse | 26 | 0.0 | 0.00 | 0.00 | 0.0% | — |
| **all** | | **710.5** | | | 100% | **1.0926** |

**Where the judge time goes.** The judge is genuinely ~53% of all call
time — the broken table's proportion was right, its denominator was wrong.
The shape is the story: median 2.4 s but p95 13.5 s. Sonnet 5 thinks by
default with up to 4,000 tokens; most verdicts are quick, a handful of
long-evidence semantic rows take 10–15 s each, and those few carry the
total. Cost follows the same split: judge $0.49 of $1.09 (45%), then
sql_generate $0.38 (59 calls at ~10 KB of schema prompt each — the most
expensive *per call* stage at $0.0065), answer $0.14, router $0.08.

Two things the old table could not show: `sql_execute` has a p95 of
1.96 s against a 0.03 s median (a few heavy queries — worth a look before
Phase 6's latency work), and `rerank` is 0.15 s per call on the Voyage
API, so retrieval end to end is under 1% of the run.

**Which timing system was kept, and why.** Both. The hand-rolled table was
*corrected*, not removed: at `--workers 1` it still reports the untimed
residual (0.8 s of 737 s, the one thing Langfuse cannot see), and at
`--workers N` it now reports each stage's share of **summed call time**
with no gap row, instead of dividing by wall time (that was the 263% and
the negative gap). It costs nothing and works offline. Langfuse is the one
to *read*: per-call medians and p95s, per-question drill-down, filtering
by score. The two agree because they time the same `with` blocks —
713.0 s summed in the harness vs 710.5 s in Langfuse (the 2.5 s is the
in-process bookkeeping Langfuse's span boundaries exclude).

## 4. The eval itself

| run | commit | routing | generation | faithfulness | ctx precision | cost | wall |
|---|---|---|---|---|---|---|---|
| WO11 `2026-09-14-0920` | `446c30e` | 96.3% | 74/82 (90.2%) | 89.9% | 59.0% | $1.11 | 271 s |
| **WO12 `2026-09-15-2107`** (traced) | `aae90bc` | 96.3% | **76/82 (92.7%)** | 88.6% | 63.9% | $1.09 | 270 s |

Tracing added no measurable wall time or cost. The two-question movement is
answerer sampling (the answer model still runs at default temperature):
Q26 ✓ (final key), Q49 ✓ and Q58 ✓ (the over-reach cases phrased more
tightly this time), Q28 ✗ (phrased less tightly). Still failing: Q11, Q28,
Q41, Q45, Q47, Q56. No SQL errors.

## 5. Projected monthly units

This run: **974 units** = 82 traces + 696 observations + 196 scores, i.e.
**11.9 per question** — above the WO's 6–8 estimate because every stage is
its own observation (a structured question is trace + 3 tier roots +
router + sql_generate + sql_validate + sql_execute + answer + judge +
2–3 scores).

| usage pattern | units / month | share of 50,000 |
|---|---|---|
| one full eval per working day (22) | 21,400 | 43% |
| one full eval per calendar day (30) | 29,200 | 58% |
| weekly eval (4–5) | 4,900 | 10% |
| ad-hoc CLI question | 6–9 each → ~5,000 per 600 questions | 10% |

Daily evals plus a few hundred ad-hoc questions fit. Two daily evals do
not. If it ever gets tight, the cheapest cuts are `sql_validate` and
`fuse` (2 units per structured/semantic question, both sub-millisecond).

## 6. Installed footprint

| | |
|---|---|
| wheels downloaded (langfuse + deps) | 5.7 MB, 26 files; largest `pydantic_core` 2.0 MB (already installed for anthropic) |
| new on disk in the venv | **+21 MB** (399 → 420 MB site-packages) |
| new packages | langfuse, opentelemetry-{api,sdk,proto,semantic-conventions,exporter-otlp-proto-http,exporter-otlp-proto-common}, protobuf, googleapis-common-protos, wrapt, backoff, requests + urllib3 + charset-normalizer |
| import RSS delta | `import anthropic, voyageai` 108 MB → `+ langfuse` 115 MB → `+ client` 118 MB: **+10 MB per process** |
| torch-class dependency | none |

Nothing heavy; proceeded without asking.

## Surprises

1. **The SDK is 4.x, not 3.x.** The API is OpenTelemetry-shaped:
   `start_as_current_observation(as_type=…)`, `propagate_attributes()` for
   trace-level session/tags/metadata, and `LANGFUSE_BASE_URL` is its
   native env var — the work order's "the SDK may expect LANGFUSE_HOST"
   was a v2 concern. Verified from the wheel before installing.
2. **11.9 units per question, not 6–8.** Every stage as its own
   observation plus three tier roots per eval question. Still inside the
   free tier at daily evals.
3. **The public API rate-limits per-trace reads** (429 at ~80 requests).
   Bulk time-window queries are the way to read a run back.
4. **`sql_execute` p95 is 1.96 s** against a 0.03 s median — some
   generated queries are two orders of magnitude slower than the rest.
   Invisible before; the per-call data is now there to find them.
5. **The working-tree copy of `evals/results/2026-09-14-0920-wo11.md` was
   overwritten outside this session** (one line, `/usag`). The committed
   file is intact; the working copy was left alone for Alex to check out.

## Cost

Full eval $1.09 + three CLI verification questions $0.02 + one failure
test $0 → **≈ $1.11** (budget $2).

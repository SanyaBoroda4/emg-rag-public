# emg-rag

RAG pipeline over EMG's Moraware and QuickBooks data: Postgres + pgvector,
raw-first ingestion, chunking and embeddings, retrieval.

See `CLAUDE.md` for project context, server constraints, and working rules.

## Layout

- `docker-compose.yml` — pgvector Postgres 17, memory-capped, localhost-only on 5433
- `sql/` — idempotent, append-only migrations (001 schema … 005 retrieval views … 012 pipeline status, 014 wasted templates)
- `ingest/` — ingestion + semantic-layer package (`db.py` connection helper)
- `retrieval/` — BM25/dense/RRF lanes, reranker, text-to-SQL lane, router, answer
- `scripts/check_db.py` — verifies connection, extension, and tables
- `scripts/query.py` — end-to-end query CLI (route, retrieval, answer, latency)

## Known constraints

- **Voyage AI rate limits** (observed 2026-08-02): the account tier allows ~3
  requests/min and ~10K tokens/min, and a single request whose token count
  exceeds the per-minute budget is refused outright rather than queued. All
  Voyage calls go through `ingest/voyage_util.py` (exponential backoff with
  jitter); bulk embedding uses 48-text (~7K-token) batches paced 60s apart.
  Full-corpus embedding takes ~1h at this tier; adding a payment method to the
  Voyage account would cut that to ~1 minute.
- The server has ~1 GiB free RAM and runs live production containers; every
  component is memory-budgeted (see CLAUDE.md).

## Model choices (measured, not asserted)

- **`SQL_MODEL` defaults to Haiku** (WO7). WO4 chose Sonnet on the argument
  that a wrong join fails silently; the WO6 benchmark refuted it on the
  golden set's judge-free numeric comparison — Haiku 18/31 vs Sonnet 17/31,
  at 42% of the cost and half the latency, zero validator failures
  (`evals/results/benchmark.md`). The structured lane's failure modes turned
  out to be semantic (which column, substring vs exact), not join
  complexity, and prompt-side schema enumeration addresses those.

## Canonical business definitions (views, not prompts)

Business questions with a contested definition are implemented once as a
Postgres view, exposed to the text-to-SQL lane as authoritative, and gated
by a script that asserts hand-verified cases:

- **Pipeline status / quote conversion** — `v_job_pipeline_status`,
  `v_quote_conversion_monthly` (`sql/012`–`013`, `017`).
- **Quoted jobs** — `v_quoted_jobs` (`sql/019`, ruling 2026-09-16): a job is
  quoted when it has a Quote, Measure or Template that is either in an
  accepted status (Confirmed / Complete / Paid in Full and Finished /
  In Progress, dated or not) or dated at all, whatever its status; only an
  undated Estimate placeholder counts for nothing. 4,423 jobs on the
  snapshot. The pipeline view's `is_quoted` (4,415) is the same signal
  restricted to dates on or before the as-of — the conversion-cohort rule,
  not a second definition; the 8-job gap is undated-Confirmed and
  after-as-of rows. Diagnostic: `evals/results/wo15_quoted_jobs_diagnostic.md`.
- **Wasted templates** — `v_wasted_templates`, `v_wasted_templates_by_pm`
  (`sql/014`): a template trip is wasted when another template followed it
  within 30 days with no install between (structural) or its note records
  the site was not ready (note). Rule reverse-engineered from 10 hand-judged
  jobs; `scripts/verify_wasted_templates.py` reproduces all of them and
  reports the per-PM table, matched notes, and a 21/30/45-day sensitivity.

## Running the eval

`python evals/run_eval.py --workers 4` runs the full golden set (tiers 1–3)
in about 5 minutes; `--workers 1` is the sequential path. Router and judge
latency are recorded per question; the Sonnet judge is the dominant stage.
Router, text-to-SQL and the answer model all run at temperature 0 so
run-to-run movement in *what the system produces* is signal, not sampling
noise. The one remaining source of variance is the Sonnet judge: Sonnet 5
rejects `temperature`/`top_p` (400), and majority-of-3 voting
(`JUDGE_VOTES=3`, available but **not** the default) still flipped a
genuinely borderline row (Q30, 5 ✓ / 4 ✗ across nine independent verdicts).
Measured floor: ±1–2 questions per run, on 2–4 semantic rows. Read a
change as real when it moves the failing *set*, not the count.
`python evals/rejudge.py <run.json> --passes 3 --out /tmp/rj` re-judges a
saved run (judge cost only, ~$0.46/pass) to measure that floor without
re-running the pipeline.

## Observability (Langfuse)

Every question — ad-hoc through `scripts/query.py` or golden through
`evals/run_eval.py` — is recorded end to end in Langfuse Cloud (US region,
free Hobby tier). Nothing changes without credentials: `retrieval/tracing.py`
is a no-op when `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` are absent, and
every SDK call is wrapped so a Langfuse outage degrades to "no tracing",
never to a failed query. The base URL comes from `LANGFUSE_BASE_URL` in
`.env` and is passed explicitly.

**Trace vs span, plainly.** A *trace* is one question, start to finish, named
after its entry point (`query_cli` or `eval_run`). A *span* (Langfuse calls
it an observation) is one stage inside that question. Model calls are a
special span type, a *generation*, which carries the model name, token
counts and cost. A *score* is a number attached to a trace afterwards — the
eval's verdicts.

**What is traced, per question:**

| span | what it records |
|---|---|
| `router` | question → route + one-line reason; model, tokens, cost |
| `bm25`, `dense`, `fuse`, `rerank` | query, chunk ids in rank order, RRF scores, rerank scores, backend |
| `embed_query` | the Voyage query embedding (CLI path; the eval embeds all questions in one batch) |
| `sql_generate`, `sql_repair` | the generated SQL; model, tokens, cost |
| `sql_validate` | whitelist/parse result — a rejected query is a failed span with the validator's message |
| `sql_execute` | columns, row count, first rows — **a Postgres error is a failed span with the error text** |
| `answer` | chunk ids and SQL passed in, the answer, model, tokens, cost |
| `judge` | eval only: the verdict JSON, model, tokens, cost |

Trace metadata (filterable): entry point, git commit, model names, rerank
backend, `route_expected` / `route_predicted`, and for eval runs the golden
`question_id` and `status`. An eval run is one *session* named
`eval-YYYYMMDD-HHMM-<sha>` (also a tag), and each of its 82 traces carries
scores `correct` (0/1, judge reason as the comment), `faithfulness`,
`context_precision`, `retrieval_recall_at_10` (rows with gold chunk ids) and
`sql_error` when the lane raised. The one question the tiers share is one
trace: its router call (tier 1), retrieval (tier 2) and generation + judge
(tier 3) appear as three root spans under the same trace id.

**How to read a trace.** Open Tracing → Traces, filter by tag (`cli`,
`eval`, or the run's session id) or by score (`correct = 0` for every failure
in a run). A structured question reads top to bottom as
`router 1.6 s → sql_generate 0.8 s → sql_validate → sql_execute 0.02 s
(516 rows) → answer 0.7 s`, each generation with its own cost; a semantic one
shows `bm25 → embed_query → dense → fuse → rerank → answer` with the chunk
ids at every step. A failed stage is red with its message — e.g.
`sql_execute · ERROR · UndefinedColumn: column "salesperson" does not exist`,
which is exactly how Q26's WO11 bug looks.

**Retention.** The free tier keeps 30 days. Anything worth keeping (a
baseline run, a failure worth citing) must be exported — the eval's own JSON
under `evals/results/` is the durable record; Langfuse is for looking, not
archiving.

## Known outstanding work

- **`job_areas.material_name` needs a parser, not a mapping table**: 3,671
  distinct values across ~4,700 filled rows, with slab count, thickness, and
  finish embedded in free text (`2 x Shadow Storm Honed`,
  `(1.5)Calcatta Liberty`, `0.3 SB Brazilian Carrera`). Deserves its own work
  order producing structured columns (material, slab_count, thickness,
  finish) the way WO5 normalized cities.

## Setup

```bash
cp .env.example .env   # fill in real values
docker compose up -d
docker exec -i emg_rag_db psql -U emg_rag -d emg_rag < sql/001_schema.sql
pip install -r requirements.txt
python scripts/check_db.py
```


# EMG RAG — Project Handoff / Status

> Purpose of this file: bring a brand-new collaborator (human or AI chat with no
> prior context) fully up to speed. Last updated: 2026-08-09, after WO7 and the
> quote-conversion work order. Read `CLAUDE.md` first for the hard operating
> rules; this file is the story and the current state.

## What this project is

A retrieval-augmented question-answering system over **EMG's** (countertop
fabrication company, Charleston SC) business data:

- **Moraware** (job tracking): 5,569 jobs, 44,495 activities, 12,201 forms,
  149,364 form fields — exported to JSON, raw files on the server
- **QuickBooks**: 5,257 invoices (2018–2026)

Pipeline: raw exports → Postgres (+pgvector) → derived/typed tables → chunked
+ contextually enriched + embedded notes → hybrid retrieval (BM25 + dense +
rerank) + text-to-SQL lane + LLM router → grounded answers with citations →
evaluation harness with golden set + CI.

Alex is also using the repo as a **job-search portfolio**: every push to the
private repo is mirrored (sanitized) to a public repo.

## Environments

- **Local dev:** `C:\Users\alex\PycharmProjects\emg-rag` (Windows, PyCharm)
- **Private repo:** `github.com/SanyaBoroda4/emg-rag`
- **Public mirror:** `github.com/SanyaBoroda4/emg-rag-public` — full commit
  history, server IP redacted, author emails fixed. Sync with
  `bash scripts/sync_public.sh` after every private push (MANDATORY, see
  CLAUDE.md). Never push to it directly.
- **Server:** Hetzner CPX11 (2 GB RAM, Ubuntu), repo at `/opt/emg-rag`,
  auto-pulls from GitHub every minute via cron (⚠ pull silently stops if the
  working tree is dirty/conflicted — check `git status` on the server if
  changes don't arrive). SSH details in `CLAUDE.md`. The box also runs LIVE
  production WhatsApp/MCP containers — **never touch anything except
  `/opt/emg-rag` and the `emg_rag_db` container; cap all memory**.
- **Database:** pgvector Postgres 17 in `emg_rag_db`, localhost-only
  `127.0.0.1:5433`, 600 MiB cap (sits ~150–210 MiB). Credentials in `.env`
  (never committed). A read-only role `rag_reader` (SELECT on `v_*` views
  only, 10s statement timeout) executes all model-generated SQL.

## API accounts / models

- `ANTHROPIC_API_KEY` + `VOYAGE_API_KEY` live in `.env` on the server.
- Router: `claude-haiku-4-5`. Answers: Haiku (`ANSWER_MODEL`).
  Text-to-SQL: **Haiku** (`SQL_MODEL`; switched from Sonnet in WO7 after
  benchmark). Eval judge: always the *other* model from the generator.
- Embeddings: **voyage-3.5-lite** (1024-dim). Reranker: **Voyage
  `rerank-2.5-lite` API** (`RERANK_BACKEND=voyage`) — the local cross-encoder
  failed the 400 MiB memory gate (593 MiB peak; `scripts/measure_reranker.py`).
- ⚠ **Voyage account is on the unpaid tier**: ~3 requests/min, ~10K
  tokens/min; oversized single requests are refused outright. All Voyage
  calls go through `ingest/voyage_util.py` (jittered backoff). Bulk embedding
  = 48-text batches, 60s apart (full corpus ≈ 1 h). Eval runs take ~1–1.5 h
  mostly because of per-question rerank calls. Adding a payment method to
  Voyage would make all of this ~50× faster.
- ⚠ Do NOT install torch/sentence-transformers on the server: their mere
  presence makes `import voyageai` pull them in (~430 MiB in every process).
  They are quarantined in `requirements-rerank-local.txt`.

## Work orders completed

| WO | What | Key outcomes |
|---|---|---|
| 1 | Infra + schema | docker pgvector, 14-table idempotent schema (`sql/001`), db helper, verify script |
| 2 | Load corpus | All counts reconcile exactly (5,569/44,495/12,201/149,364/5,257). Idempotent loaders (`ingest/load_*.py`), `derive_areas.py`, invoice link extraction (2,554 invoice numbers, 10 typos), `scripts/verify_load.py` gate. Surprise: 19,622 activities have no date (not ~2,572); assignee IDs don't exist anywhere (synthesized from name hash) |
| 3 | Semantic layer | 7,194 chunks (activity+area notes ≥25 chars), Haiku Batch-API contextual sentences ($1.93, 0 failures), voyage embeddings. `activities.phase` recovered from raw JSON (1,639 rows). `scripts/verify_semantic.py` + smoke retrieval |
| 4 | Retrieval stack | BM25 (Postgres FTS, `sql/004`), dense (exact scan, no ANN — 7k vectors), RRF fusion (k=60, provenance kept), reranker w/ memory gate, text-to-SQL over `v_*` views (`sql/005`, sqlglot validation: single SELECT, view/column whitelist, forced LIMIT 200, RO role), Haiku router (structured/semantic/hybrid/refuse), grounded answers with [chunk/job] citations + honest refusal + date caveat, `scripts/query.py` CLI. 7 test queries pass |
| 5 | City normalization | 294 raw spellings → 68 canonical areas via `data/city_map_final.csv` + ZIP rules + address map (`sql/006`, `ingest/normalize_cities.py`). West Ashley is the real largest market (603 jobs); "Charleston" collapsed 749→81. `jobs.city` NEVER modified (raw-first). 2,909 chunks re-contextualized ($0.74). Gate: `scripts/verify_cities.py` |
| 6 | Eval harness | 58-question golden set (Alex-authored). Tier 1 routing (confusion matrix), Tier 2 retrieval (recall@k/MRR/NDCG per lane), Tier 3 LLM-judged generation (judge ≠ generator, recorded). Ablation + Haiku-vs-Sonnet benchmark (`evals/`). CI (`.github/workflows/eval.yml`): synthetic fixture (option b) in ephemeral pgvector container; Tier 1 runs on real questions (DB-free) with baseline gates. Baseline: routing 94.8%, reranked R@10 0.522/MRR 0.441, generation 48.3%, faithfulness 65.5%. Found 9 new failures among "verified" rows + confirmed known bugs Q26/Q29 |
| 7 | Fix eval-found bugs, re-measure | **COMPLETE.** All five known-failing questions (Q16/Q20/Q21/Q26/Q29) now pass. Generation 48.3%→**60.3%**, faithfulness 65.5%→**81.8%**, precision 48.6%→64.3%, routing/retrieval held. Three measured rounds; regressions from schema enumeration found and fixed mid-WO. Deliverable: `evals/results/before_after.md`. Cost ≈$2.60 |
| PIPE | One canonical pipeline definition | **COMPLETE.** `sql/012`: `v_job_pipeline_status` (per-job: is_quoted = happened Quote/Measure/Template past-only; moved = Install/Removal ANY date, activities only — payment signals removed; SETTLE_DAYS=30, 7-day rule retired; first vs last signal date = cohort vs silence clock) + QCONV v4 derived from it + Q26 buckets (moved 3,063 / pending 46 / quiet 1,306; 84% of quiet = Canceled). Overall conversion v3 65.9% → **v4 70.0%** (3,063/4,377) — WO predicted a fall, measured a RISE: only 11 payment-only movers lost, 339 no-Quote jobs joined and 95% of them moved. Faithfulness 91.7% (WO-best). Q59–62+Q30 keys superseded (intended reds; corrected numbers in report). Resolves open decision #3. Deliverable: `evals/results/wo_pipeline_unification.md`. Cost ≈$1.65 |
| AREAL | Activity reality + JOIN fan-out | **COMPLETE.** `sql/011`: `v_activities.happened`/`is_scheduled_future` (three-state rule: placeholder / happened / scheduled-future; ~44% of rows are pre-created placeholders — 5,315 Quote rows but only 3,154 real), `v_job_sqft` per-job pre-aggregation (LEFT JOIN pattern; fixes activity×area fan-out AND repeat-visit double-count). Schema-prompt rules + answerer stops volunteering unsupported schema stats. Generation 60.3%→**69.8%**, faithfulness 81.8%→**90.0%**. Q31–37 crew block + Q59–62 all produce verified numbers. 4 measured rounds, 3 mid-WO regressions (Q22/Q2/Q33) found+fixed. Deliverable: `evals/results/wo_activity_reality.md`. Cost ≈$2.95 |
| QCONV | Quote → moved-forward conversion | **COMPLETE (definition v3).** `v_quote_conversion_monthly` (`sql/008` v2, `sql/009` v3), wired into the SQL lane. Locked definition: quoted = job's first DATED Quote, OR measure-proxy (undated Quote + dated Measure ⇒ quote happened unlogged, cohort = first Measure date); re-quotes = ONE job; moved = dated Install OR dated Removal (future dates count) OR chatbot payment note (`Payment received/recorded —` / `check-bot`, 85 activities — human "asked for payment" excluded); invoice numbers do NOT count; 7-day freshness rule; as-of hardcoded 2026-07-30 (TODO CURRENT_DATE). **Overall 65.9%** (2,523/3,830); yearly: 2020 64.7 → 2023 peak 85.2 → 2024 61.1 → 2025 54.3 → 2026 47.6. Sanity jobs verified (483 proxy, 5693 future-Removal, 5022 payment-only, 377 invoiced-not-moved, 5840 fresh-excluded). Golden candidates Q59–63 added (draft, v3 numbers). Visibility stats: 111 invoiced-but-not-moved; 279 dated-Measure-but-no-Quote-activity (excluded, awaiting Alex's call) |

## WO7 detail (complete — kept for context)

Decisions applied: `SQL_MODEL`→Haiku (measured: 18/31 vs 17/31 at 42% cost);
Q12=152 (job-level substring count); Q20=1,779 (golden was wrong). The
delivered updated `evals/golden_set.csv` had column-shifted rows — repaired in
commit `e4ab67a`.

Fixes shipped (commit per fix):
1. **Bug A/C** — schema prompt now enumerates every low-cardinality column's
   exact values (cities, activity types, statuses, room types, assignees,
   salespeople, invoice statuses) with exact-match rules; `material_name`
   deliberately NOT enumerable (3,671 unparsed values → future parser WO).
2. **Bug B/D-routing** — router treats quote/template/install/tile/... as
   activity types; activity-sequence questions route structured.
3. **Bug D** — `chunks.is_bot_generated` (`sql/007`, exactly 238/7,194
   flagged) surfaced as [AUTOMATED SYSTEM RECORD] in retrieval + answer +
   judge prompts.
4. **Scorer** — list-shaped expected answers (all numbers must match) and
   $2.59M-style suffix normalization (`evals/metrics.py`).
5. **Judge evidence** — judge now sees the SQL rows the generator saw (it was
   branding row-derived claims as fabrications).
6. **Round 2** (after round-1 re-measure exposed enumeration side effects):
   salesperson-vs-assignee disambiguation, invoice status values,
   empty-string-not-NULL convention, "area"=city vocabulary,
   `COUNT(*) OVER ()` window-count rule (LIMIT was truncating counts),
   "stalled after quote" definition; router must not refuse by assuming notes
   lack a detail.

Round-1 results (commit `72ebc8e`): Q16 ✅ Q20 ✅ Q21 ✅ Q26 ✅ now pass;
Q29 still failed (right SQL now, but LIMIT truncated 246→200 — round-2 window
count targets it); generation 29/58 (50.0%), faithfulness 78.2% (+12.7),
routing 93.1% (−1.7: Q50 regression, fixed in round 2).

Round 2 fixed the enumeration side effects (35/58). Round 3 added a
deterministic un-LIMITed COUNT in the SQL lane — Q29 finally correct (246).
Final numbers in `evals/results/before_after.md`. Remaining reds: Q28/Q30
(genuine near-misses, judged strictly on purpose).

## Decisions waiting on Alex

0. **Placeholder-inflated golden keys** (AREAL WO, from the A1 diagnostic in
   `evals/results/wo_activity_reality.md`): Q16 5,315 → real quotes issued
   **3,154**; Q14 Install 7,758 → 5,652 dated; Q15 Repair 846 → 840; Q29
   246 (any Tile row) → 236 (happened only). Also Q31's "(29 install
   visits)" third number keeps it red despite exact sq ft + job count.
   Q32–37 now produce the verified numbers and can flip draft→verified.
1. Golden set: flip now-passing FAILING rows (Q16/20/21/26/29) to verified;
   sign off draft rows incl. quote-conversion Q59–63 (v3 numbers).
2. ~~Quote-conversion edge: 279 dated-Measure-no-Quote jobs~~ **RESOLVED by
   PIPE WO** — quoted by definition under v4. New re-key list (PIPE report):
   Q59 70.0% (3,063/4,377), Q60 85.7% (409/477), Q61 63.4% (401/632),
   Q62 2023 85.7%, Q63 drop the payment clause from the wording, Q30 now 9
   quiet quartzite jobs under the canonical definition.
3. The 111 invoiced-but-not-moved jobs: strict rule keeps them out; many
   predate the payment bot (bot notes start 2026), so history has a
   payment-signal blind spot.
4. Voyage payment method (would cut hour-long embed/eval runs to ~1 min).
5. GitHub Actions secrets for CI not yet verified end-to-end.

Nothing in flight — project is between work orders. Likely next: material
parser WO (3,671 unparsed material values; now has measured eval impact),
freshness pipeline (un-hardcode the as-of date), conversion by
salesperson/city/quote-size on top of the v3 view.

## Key files map

```
CLAUDE.md                 operating rules (server, git, mirror) — READ FIRST
HANDOFF.md                this file
sql/001..007_*.sql        append-only migrations
ingest/                   loaders, chunker, contextualizer, embedder,
                          city normalizer, db.py (+get_ro_conn), voyage_util.py
retrieval/                keyword.py dense.py fuse.py rerank.py sql_lane.py
                          router.py answer.py
scripts/query.py          end-to-end CLI: route → SQL/retrieval → answer
scripts/verify_*.py       per-WO gates (load, semantic, cities)
scripts/sync_public.sh    sanitized mirror sync (run after every push)
evals/golden_set.csv      58 questions; metrics.py harness.py run_eval.py
                          ablate.py benchmark_models.py judge_probe.py
evals/results/            committed run artifacts (latest.md = summary)
evals/fixtures/           synthetic CI corpus + loader + baseline
.github/workflows/eval.yml  CI: push=tiers1+2, PR=tier3 subset, weekly=full
data/city_map_final.csv   Alex-approved city mapping (294 → 68)
```

## Conventions that matter

- **Raw-first**: never modify source columns; add derived columns/tables.
- **Idempotent**: every script re-runs to the same state; prove it.
- **pipeline_runs**: every DB-touching script inserts a row at START
  (status=running) and updates at finish (rows, cost in `note`).
- **Conventional commits**, one logical change each, push immediately, then
  mirror-sync. Never commit `.env`, `raw/`, `.venv/`.
- **Measure, don't assert**: changes to retrieval/prompts need before/after
  eval numbers. Q26/Q29-style known failures stay red until truly fixed.
- Cost tripwires per WO (~$5); everything so far totals ≈ **$9** across WO3–7.

## Known open items / gotchas

- **Material parser** (biggest one): `job_areas.material_name` has 3,671
  distinct unparsed values ("2 x Shadow Storm Honed"); causes measured eval
  failures (Q11/Q12 ambiguity). Needs its own WO. Noted in README.
- Two `John's Island` rows (curly apostrophe) unresolved in city map (jobs
  1674, 2154) — one-line CSV fix if Alex wants.
- Golden set: 5 rows still status=FAILING after WO7 round 1 — flip to
  `verified` is **Alex's call**, not automated.
- Server cron pull fails silently on dirty tree (bit us once — results files).
- `evals/results/latest.md` gets overwritten by whatever ran last on the
  server, including fixture runs — check the timestamped JSONs for truth.
- GitHub Actions secrets (`ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`) must be set
  in repo settings for CI to go green — not yet verified end-to-end on GitHub.

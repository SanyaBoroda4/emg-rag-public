# Engineering notes

The longer story behind the README, one section per phase or work order,
condensed from the work-order reports. Every number here is copied from a
committed file, named at the end of each section. Employee names are
pseudonymised in the public mirror; customer data never appears.

The project: natural-language questions over a countertop fabricator's
job-tracking (Moraware) and invoicing (QuickBooks) data. The data is a
snapshot as of 2026-07-30: 5,569 jobs, 44,495 activities, 12,201 forms,
149,364 fields, 5,257 invoices. It runs on a 2 GB Hetzner box shared with
live production containers, which shaped most of the decisions below.

## Phase 1–2 — Infra, schema, raw-first load

A memory-capped pgvector Postgres in Docker, a 14-table idempotent schema
(`sql/001`), and loaders that land the raw exports untouched and derive
everything else separately (a bad transform is a re-run, never a re-pull).
Every count reconciled exactly against the source. Two surprises set the tone
for the rest of the project: 19,622 activities have no date (the export notes
had said about 2,572), and assignee ids do not exist anywhere in the source,
so they are synthesised from a name hash. Full detail: `HANDOFF.md`, phase
rows 1–2.

## Phase 3 — Semantic layer

7,194 chunks (activity and area notes of at least 25 characters), each given
a one-sentence context by Haiku through the Batch API (about $1.93, zero
failures), then embedded with Voyage. The `activities.phase` field was
recovered from the raw JSON for 1,639 rows. Lesson that generalises: the
context sentence carries the provenance (job, area, activity type, status,
date) that the answerer later needs to describe a note honestly; WO20 leaned
on exactly that. `HANDOFF.md`, phase row 3.

## Phase 4 — Retrieval stack

BM25 through Postgres full-text search, dense retrieval as an exact scan (no
ANN index for 7k vectors), reciprocal-rank fusion with provenance kept, a
reranker behind a memory gate, a text-to-SQL lane over whitelisted `v_*`
views, a Haiku router with four routes (structured, semantic, hybrid,
refuse), and grounded answers with `[chunk, job]` citations. The SQL lane's
safety layers were designed here and never loosened: a single parsed SELECT,
view and column whitelist, a forced `LIMIT 200`, execution on a read-only
role with a 10 s statement timeout. `HANDOFF.md`, phase row 4;
`retrieval/sql_lane.py`.

## Phase 5 — City normalisation

294 raw city spellings collapse to 68 canonical areas through a mapping
table, ZIP rules and an address map, without ever modifying the raw column.
The largest market turned out to be a different area than the raw data
suggested, because one spelling had absorbed everything ambiguous (749 rows
became 81 once normalised). `HANDOFF.md`, phase row 5.

## Phase 6 — Eval harness

A 58-question golden set written by the domain owner, later grown to 82.
Three tiers: routing (confusion matrix), retrieval (recall@k, MRR, NDCG per
lane), generation judged by a different model than the one that answers
(Sonnet judges, Haiku answers). A CI variant loads a synthetic fixture into an
ephemeral pgvector container. First baseline: routing 94.8%, reranked
recall@10 0.522, generation 48.3%, faithfulness 65.5%. The harness
immediately found nine new failures among rows that had been marked
verified. `HANDOFF.md`, phase row 6; `evals/`.

## Phase 7 — Fix what the eval found

Five known-failing questions fixed; generation 48.3% → 60.3%, faithfulness
65.5% → 81.8%, routing and retrieval held. Three measured rounds, with
regressions from schema enumeration caught and fixed mid-work.
`evals/results/before_after.md`.

## Activity reality and JOIN fan-out

About 44% of activity rows are pre-created placeholders: 5,315 Quote rows
but only 3,154 that happened. A three-state rule (placeholder / happened /
scheduled-future) went into `v_activities`, and a per-job square-footage
pre-aggregation removed an activity×area fan-out that had doubled sums.
Generation 60.3% → 69.8%, faithfulness 81.8% → 90.0%.
`evals/results/wo_activity_reality.md`.

## One canonical pipeline definition

`v_job_pipeline_status` became the single per-job answer to "quoted, moved
forward, quiet": quoted means a Quote, Measure or Template that happened;
moved means an Install or Removal on any date; quiet means silent beyond a
30-day settle window. The work order predicted the conversion rate would
fall; it rose from 65.9% to 70.0% (3,063 of 4,377), because 339 jobs that
had never been formally quoted joined the cohort and 95% of them moved.
Lesson: define the business term once, in a view, and let the eval keys
follow the definition. `evals/results/wo_pipeline_unification.md`.

## WO8–WO10 — Wasted templates, status widening, determinism

A template trip is wasted when another template follows within the same
30-day phase with no install between (structural) or the trip's note records
the site was not ready (note). The rule was reverse-engineered from ten
hand-judged jobs and a gate script reproduces all ten; 266 of 3,534 trips
(7.5%) at first, 252 of 3,643 (6.9%) after status widening and same-day
pair collapsing, with no hand verdict flipping. The crew-workload questions
went from 1 of 10 to 10 of 10 through a per-job-versus-per-visit CTE pattern.
Determinism work: the SQL lane at temperature 0 produced identical SQL on 13
of 14 crew questions and identical rows on 14 of 14; parallel judging cut a
full run from 780 s to 319 s with identical scores. Lessons: measure each
change alone with the gate after each; when a number moves, look at the
failing set, not the count. `evals/results/wo_wasted_templates.md`,
`wo9_status_widening.md`, `wo10_determinism_latency.md`,
`docs/session-2026-09-08-to-10-WO8-WO10.md`.

## WO11 — Re-keying and the quoted-jobs definition

Thirteen "does a job like X exist" questions had keys that demanded one
specific match; re-keyed to "multiple valid matches" they went from 1 of 13
to 10 of 13, and the three that still fail do so because the answerer
over-generalises from a sample (a real finding, kept red). Q26 exposed a
validator gap: `salesperson` was a legal column name somewhere, so selecting
it from a view that lacked it passed the whitelist and failed in Postgres,
and the lane fell back to a semantic answer that the judge rewarded for
declining honestly. The immediate fix put the columns on the view; the
structural fix (per-alias validation) came in WO20. Lesson on keys: a key
that requires every number the author happened to compute is
over-specified; keep keys to what the question asks. `evals/results/wo11_rekey.md`.

## WO12 — Observability

Langfuse tracing wrapped around every stage, a no-op without credentials
and try/except around every SDK call so an outage degrades to "no tracing".
The first stage table showed where the time goes: the judge is 53% of call
time (median 2.4 s, p95 13.5 s), the answer 18%, the router 16%, SQL
generation 11%, retrieval under 1%; the harness's own timings and Langfuse
agreed to within three seconds. Footprint: +21 MB disk, +10 MB RSS per
process. `evals/results/wo12_langfuse.md`.

## WO13 — Answer determinism and the slow-query tail

The answer model moved to temperature 0; three consecutive full runs then
differed only where the judge flipped on byte-identical answers. Tracing had
shown `sql_execute` with a 0.03 s median but a 1.96 s p95: all five slow
spans were the wasted-templates view, and EXPLAIN put 0.9 s of 1.17 s in a
correlated same-day-Measure subquery (3,399 loops). One partial index of
184 kB (`sql/018`) took the view from 1,167 ms to 326 ms with md5-identical
output; run p95 1.96 s → 0.40 s. `evals/results/wo13_determinism_slow_sql.md`.

## WO14 — Redundant COUNT(*) and measuring the judge

Skipping the true-total `COUNT(*)` re-execution when fewer rows than the
LIMIT came back (47 of 59 queries) halved `sql_execute` again (p95 0.40 →
0.20 s) with all 59 totals identical. Then the judge itself was measured:
Sonnet 5 rejects `temperature`/`top_p`, so nine single passes were run on
one saved answer set: 74–76 of 82 each time, with one question at 5 ✓ / 4
✗. Majority-of-3 still flipped that row. Decision: leave the judge alone,
state the ±1 floor, and read only movements of the failing set as real.
`evals/results/wo14_count_skip_judge.md`.

## WO15 — Quoted jobs: a definition, not a count

Two views disagreed on how many jobs had been quoted (4,236 vs 4,415). A
read-only diagnostic found every disputed job was one whose only dated
signal carried an Estimate status. The domain owner ruled they count;
`sql/019` encodes the ruling (4,423 jobs) and the pipeline view's 4,415 is
the same signal restricted to the as-of date. Lesson: when two numbers
disagree, the deliverable is the ruling, not a compromise number.
`evals/results/wo15_quoted_jobs_diagnostic.md`.

## WO16 — Serving

FastAPI behind Caddy with Basic Auth and a Let's Encrypt certificate, one
static page, a 500-character cap, two questions in flight then 429, 60 s
then 504, every ask stored with its error, and a separate `serve` schema and
role fenced from the read-only lane. Memory idle 122 MB, in flight 134 MB.
The systemd unit and Caddy reload were done by the human: the agent's
permissions stop at the project directory and its one container, and that
scoping is deliberate. Trap recorded for the next person: the Caddyfile is a
single-file bind mount, and `sed -i` on it writes a new inode that the
container never sees. `evals/results/wo16_serving.md`.

## WO17 — Conversational follow-ups

A rewriter in front of the unchanged pipeline: it sees the last three turns
and either passes the question through byte-identical or rewrites it into
one self-contained question. Before: 1 of 20 follow-up turns answered
correctly (16 refused). After: 15–16 of 18 across three runs, with all 20
standalone turns passed through byte-identical and zero variance in the
standalone-versus-follow-up decision. Cost $0.0014 and 1.8 s per rewrite.
Why rewrite rather than re-prompt: single questions stay a pure function of
one string, so every existing eval and its determinism hold.
`docs/wo17-conversational-followups-report.md`.

## WO18 — Dark console

A restyle of the one-page UI with self-hosted fonts and the evidence panel
open by default as a terminal block. Every behaviour verified against a
stdlib mock of the endpoints in a local browser; the server has no browser.
Screenshots in the repo are mock data. `evals/results/wo18_restyle.md`.

## WO19 — Public mirror audit

The old mirror replayed the full private history, so every eval output had
been public. The replacement is an allowlist, a transform (pseudonyms,
`Customer #<job_id>`, redacted contacts and figures, blanked note windows)
and a guard that refuses to push on any hit; the term lists are built on the
server and never printed. `docs/wo19_public_audit.md`.

## WO20 — Correctness pass

Seven small fixes measured together: an explicit "was X better?" example for
the rewriter, refused turns skipped rather than stopped at, notes attributed
by provenance in the answer prompt, per-alias column validation in the SQL
lane (with a false-positive guard over 116 recorded queries), keyboard-
reachable example chips, and money-without-a-sign redaction in the mirror.
`evals/results/wo20_correctness.md`.

## Lessons that generalise

- **Definitions over counts.** Encode a contested business term once as a
  view; make the eval keys follow it; when two numbers disagree, get a ruling.
- **Keys can be over-specified.** A key demanding every number the author
  computed fails correct answers. Key what the question asks.
- **Measure the judge before trusting a delta.** With a ±1 floor, only a
  change in the failing set is evidence.
- **Temperature 0 everywhere the output is an argmax** (router, SQL,
  answer). It turned a noisy metric into a reproducible one.
- **Trace first, then optimise.** The p95 tail was one view and one 184 kB
  index; guessing would have pointed elsewhere.
- **Scoped agent permissions with the human doing the production step.**
  The agent touches one directory and one container; systemd, Caddy and the
  other containers are a person's job. It cost a few minutes per work order
  and prevented an entire class of incident.
- **The bind-mount `sed -i` trap.** Editing a bind-mounted single file in
  place detaches it from the container. Write through the mount instead.
- **Raw-first.** Never modify a raw column; derive next to it. Every
  normalisation in this project was a re-run, never a re-pull.

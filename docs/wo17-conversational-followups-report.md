# EMG RAG — Work Order 17: Conversational follow-ups (completed 2026-09-17)

This report is self-contained. It records what WO17 set out to do, what was
built, what was measured, and what is still open, in enough detail that
someone with no prior context can pick up from here. Every number is a
measured one from the runs referenced below; nothing is estimated.

Detailed working log with per-turn tables and the full rewriter prompt:
`evals/results/wo17_followups.md`. Handoff status: `HANDOFF.md`.

---

## 1. Summary

Before WO17 the served question-answering system treated every question as
if it were the first. A follow-up such as "And in 2025?" had no context, so
the router refused it. Measured before building: **1 of 20** follow-up turns
in the golden conversations was answered correctly as typed; 16 were
refused and 3 answered the wrong thing.

WO17 added a **question rewriter** in front of the existing pipeline. It
looks at the last three turns of the conversation and either passes the new
question through unchanged or rewrites it into one self-contained question.
The rest of the pipeline (router, SQL lane, retrieval, answerer, judge) was
not changed.

After WO17, across three consecutive runs of the new conversation tier:

| Measure | Before | After |
|---|---|---|
| Follow-up turns answered correctly | 1 / 20 | 15–16 / 18 (83–89%) |
| Standalone turns passed through byte-identical | not applicable | 20 / 20 in every run |
| Standalone-vs-follow-up decision, run-to-run variance | not applicable | 0 of 38 turns differed |
| Single-question eval (82 questions), generation | 74–76 / 82 (WO16 floor) | 73 / 82 |
| Rewrite cost and latency per call | none | $0.0014, mean 1.8 s |

Status: **code complete and pushed; the production service had not been
restarted at the time of the final commit.** Restarting the service is
Alex's step. Until it runs, https://rag.emgcheckbot.us serves the WO16
single-question behaviour.

---

## 2. Background

EMG is a countertop fabrication company in Charleston, SC. The project is a
retrieval-augmented question-answering system over its Moraware job-tracking
data (5,569 jobs, 44,495 activities, 12,201 forms) and QuickBooks invoices
(5,257). Data lives in Postgres with pgvector on a 2 GB Hetzner server that
also runs live WhatsApp production containers.

The pipeline before WO17: a Haiku 4.5 router classifies each question as
structured, semantic, hybrid or refuse; structured questions go to a
text-to-SQL lane over whitelisted views; semantic questions go to hybrid
retrieval with a Voyage reranker; a Haiku 4.5 answerer writes the grounded
answer; a Sonnet 5 judge scores evaluation runs. WO16 put this behind a
FastAPI service and a single-page UI at https://rag.emgcheckbot.us, with
per-user history in the `serve.asks` table.

---

## 3. What was built

### 3.1 The rewriter (`retrieval/rewrite.py`)

- Haiku 4.5 at temperature 0, returning JSON with three fields: whether the
  question is standalone, the resolved question, and a short reason.
- The model sees the last three completed turns. For each turn it gets the
  question as typed, the question it was resolved to, the route, the answer
  truncated to 600 characters, and the SQL if any. It never sees result rows.
- Three guarantees are enforced in code, not left to the model:
  - A question the model marks standalone is returned **verbatim**. The
    model decides the flag; it never gets to alter the text.
  - No model call is made when there is no history, or when the previous
    turn was a refusal.
  - Any failure (exception, unparseable output) fails open to the original
    question.
- Each call is its own `rewrite` span inside the existing `ui` Langfuse
  trace, recording the number of history turns and the decision.

The prompt went through two versions. Version 1 scored 11 of 18 follow-ups
on the first tier run and showed three failure shapes: keeping an older
turn's filters instead of the most recent turn's, dropping the comparison in
"is that more than X's?", and pasting numbers from a previous answer into
the rewrite, which the router then refused. Version 2 added three rules
(start from the most recent turn's filters; comparatives must name both
sides; never copy numbers from history) and scored 15–16 of 18 on every
subsequent run.

### 3.2 Unit tests without an LLM

`evals/fixtures/rewrite_cases.json` holds 20 recorded cases (10 standalone,
10 follow-up) produced by `evals/make_rewrite_fixtures.py`. `tests/test_rewrite.py`
runs 8 tests against them with no model call. They assert: every standalone
case is returned byte-identical with the flag set; every follow-up returns
the recorded rewrite; no call on empty history or after a refuse; a raising
or unparseable model fails open; only the last three turns reach the
prompt. Two recorded follow-up outputs are known weaknesses and are kept as
recorded, not hidden.

### 3.3 Storage and API (`sql/021`, `serve/app.py`)

- New columns on `serve.asks`: `conversation_id`, `rewritten_question`,
  `standalone`, `parent_ask_id`, with an index on user, conversation and
  time. Applied on the server.
- `/api/ask` accepts a `conversation_id` (a new one is created when absent
  or invalid), loads the caller's last three completed turns of that
  conversation, runs the new `ask_conversational()` entry point in
  `retrieval/pipeline.py`, and stores the four new columns, including on
  error rows. The response adds the rewritten question, the standalone flag,
  the rewrite reason, rewrite cost and latency, and the conversation and
  parent ask ids.
- `/api/history` now groups asks by conversation (title is the first
  question, with turn count and last route). `/api/history/{ref}` accepts
  either an ask id or a conversation id and returns the whole conversation,
  returning 404 unless it belongs to the caller. Pre-WO17 rows appear as
  one-turn conversations.

### 3.4 User interface (`serve/static/index.html`)

- Turns stack in one conversation. A **New conversation** button resets.
- Under a follow-up answer, a grey line reads **"Interpreted as: <rewritten
  question>"** with a **"Not what I meant? Rephrase"** link that copies the
  rewrite into the input box for editing. Standalone questions show no such
  line.
- The sidebar lists conversations. Opening one shows every turn and lets
  the next question continue it. Feedback works per turn.
- Still a single file, no CDN, nothing stored in the browser.

### 3.5 Golden conversations and the evaluation tier

- `evals/golden_conversations.csv`: 15 conversations, 38 turns. Of these, 18
  are follow-ups, 20 are standalone (including two deliberate
  mid-conversation standalones, two refusals and two post-refusal turns),
  and one follow-up is deliberately ambiguous. Every expected answer was
  computed by psql on 2026-09-17 with the SQL recorded in the notes column.
  **All 38 are status `draft`.** They do not count toward the verified
  target until Alex checks them.
- `evals/run_conversations.py`, also reachable as
  `python evals/run_eval.py --conversation`, plays each conversation in
  order, feeding real prior answers as history. Per turn it scores: the
  standalone flag, the rewrite (judged equivalent to the expected
  self-contained question by the Sonnet judge), the route, and correctness
  (numeric match, judge, or refusal). One run costs about $0.50 and takes
  about five minutes.

### 3.6 Proof the single-question path is untouched

The diff from the WO16 final commit shows zero changed lines in
`evals/harness.py`; eight lines in `evals/run_eval.py` for the new flag;
only the added entry point and result fields in `retrieval/pipeline.py`; and
no change to the router, SQL lane, answerer, judge or views. The CLI never
calls the rewriter.

---

## 4. Measured results

### 4.1 Conversation tier, three consecutive runs at commit `7141016`

| Run | Follow-ups correct | Rewrite ok | Route ok | Standalone passed through | All turns | Cost | Wall time |
|---|---|---|---|---|---|---|---|
| 1 | 15 / 18 | 16 / 18 | 17 / 18 | 20 / 20 | 32 / 38 | $0.50 | 303 s |
| 2 | 16 / 18 | 16 / 18 | 17 / 18 | 20 / 20 | 33 / 38 | $0.49 | 293 s |
| 3 | 15 / 18 | 16 / 18 | 17 / 18 | 20 / 20 | 32 / 38 | $0.49 | 299 s |

Each run made 21 rewrite calls (38 turns minus 15 first turns minus 2
post-refusal turns) at about $0.030 total and 1.7–1.9 s mean latency.

Result files: `evals/results/2026-09-17-1044-conv-wo17.json`,
`…-1049-conv-wo17.json`, `…-1054-conv-wo17.json`.

### 4.2 Variance across the three runs

- Standalone flag: identical on all 38 turns in all three runs.
- Rewrite text: differed on one turn only (C12.2, "Is that more than
  Leo's?"), as three phrasings of the same comparison, all judged
  equivalent and all answered correctly. Temperature 0 on Haiku is
  outcome-stable, not byte-stable, the same finding as WO13.
- Correctness: differed on one turn only (C1.2), caused by the SQL lane
  returning a bare count on two runs and the full three-number answer on
  one. That is the known Q68-class jitter, not the rewriter.

### 4.3 The persistent failures

| Turns | Cause | Owner |
|---|---|---|
| C1.1, C4.1, C1.2 | SQL-lane text jitter on keys that demand three numbers (the Q68/Q76 class carried from WO13/WO14). C1.1 and C4.1 are standalone questions, so the rewriter is not involved. | Existing SQL-lane floor |
| C5.3 "Was 2023 better?" | The rewriter turns it into a single-year question despite the version 2 comparative rule. The other three comparatives in the set pass every run. | Rewriter prompt; one targeted example is the likely fix |
| C11.2 "and templates?" | Deliberately ambiguous. The rewrite "How many templates has Natalia Pavlenko sold?" is visibly wrong and one click from being rephrased. Scored as a failure by design. | Working as intended |
| C15.3 "How many of those quiet jobs were quoted in 2025?" | The no-call-after-a-refusal rule means "those" two turns back is never resolved. Exactly one golden turn pays this price. | Product decision: whether history lookback should skip refusals |

### 4.4 Single-question eval (unchanged path)

Run `evals/results/2026-09-17-1038-wo17-single.json` at commit `49eef59`,
82 questions, service idle:

| Metric | Value |
|---|---|
| Routing accuracy | 96.3% |
| Retrieval R@10 | 0.818 (unchanged) |
| Retrieval MRR | 0.660 |
| Generation correct | 73 / 82 |
| Faithfulness | 94.9% |
| Cost | $1.03 |
| Wall time | 241 s |

Failing questions: 11, 41, 45, 47, 49, 56, 58, 68, 76. That is the WO16 set
plus Q58. Q58's answer, SQL, rows and retrieved chunks are byte-identical to
the WO16 final run; only the judge's verdict differed. WO14 measured Q58 at
2 pass / 7 fail across nine judgments of the same answer, so this is judge
noise, not a regression. It is reported as one below the floor regardless.

### 4.5 In-process verification on the server

The new code was exercised on the server with FastAPI's TestClient before
the eval runs. Conversation C1 produced "Interpreted as: How many jobs did
Leo install in March 2026?" (8 jobs) and then "…Ihor/Tolik install in March
2026?" (23 jobs), each chained through `parent_ask_id`. "What is the capital
of France?" was refused, and the next question "And how many jobs do we
have in Kiawah Island?" was answered (178) with no rewrite call. History
grouped the five turns as one conversation; the conversation was
retrievable by its id and by any turn id; a different user got 404 on both;
a malformed conversation id started a fresh conversation.

---

## 5. Things that got worse or are not yet done

- **Service not restarted.** The cron git pull updates the code on disk but
  does not restart the unit. Production still serves WO16 until
  `systemctl restart emg-rag-api` is run. Claude Code's permission policy
  blocks systemd, so this is Alex's step. This report could not verify the
  current state of the service.
- **Single-question eval 73/82**, one below the WO16 floor of 74, on a judge
  flip with an identical answer (section 4.4).
- **Rewrite cost and latency are about double the WO's expectation.** The
  work order assumed roughly $0.0005 and under 1 s per call; measured
  $0.0014 and 1.8 s mean (range 1.1–2.6 s). A follow-up therefore takes
  about 1.8 s longer than a standalone question. The prompt is about 1,200
  input tokens with history, and the reason field adds about 60 output
  tokens. Both are trimmable (drop the reason field, shorten history answers
  to 300 characters) but were kept for this first measured version.
- **Nothing verified yet.** All 38 golden turns are draft. The work order's
  target of at least 80% on verified follow-ups cannot be measured until
  Alex verifies the keys.

---

## 6. Findings worth keeping

1. **The refuse branch was the follow-up killer.** 16 of 20 follow-ups as
   typed were refused, not misrouted. The router reads "And in 2025?" as
   off-topic. The rewriter removes that whole class of failure.
2. **Temperature-0 rewrites are outcome-stable, not byte-stable**, exactly
   like the SQL lane: zero flag flips over three runs, one text variation.
3. **The draft keys were the first thing the tier broke.** Five of the
   eleven failures on the very first run were errors in the expected
   answers (counts the question never asked for, a wrong route, numbers the
   judge could not match). This is the same key over-specification lesson
   as WO11 and WO14, caught in one run instead of three work orders.
4. **Comparatives are the rewriter's weak spot**, specifically the "was X
   better?" form. C5.3 fails every run while the three other comparatives
   pass.
5. **The post-refusal rule has a measurable price** of exactly one golden
   turn. Whether "those" should look past a refusal is a product call.
6. **Filter carry-forward is a policy, not a fact.** "Which city did she
   sell the most in?" after "And in 2025?" keeps the 2025 filter. The
   expected answer had to follow the rule, not first instinct.

---

## 7. Cost

| Item | Cost |
|---|---|
| Before-measurement of 20 follow-ups as typed | $0.03 |
| Fixture recording, two passes | $0.04 |
| Tier run on prompt version 1 | $0.47 |
| Three tier runs on prompt version 2 | $1.48 |
| In-process API checks | about $0.10 |
| Single-question eval | $1.03 |
| **Total** | **about $3.15** (tripwire $5) |

---

## 8. Commits

All on 2026-09-17, on top of the WO16 final `d76e190`:

| Commit | Change |
|---|---|
| `2ec454b` | feat(retrieval): follow-up question rewriter |
| `a13b966` | test(retrieval): recorded rewriter fixtures (20 cases) |
| `f0de759` | feat(sql): conversation columns (021) |
| `6a5421d` | feat(serve): conversational asks |
| `6027e2b` | feat(serve): conversation UI |
| `49eef59` | feat(evals): conversation tier |
| `7141016` | fix(retrieval): rewriter prompt v2 |
| `da9c1f2` | test(retrieval): fixtures re-recorded for prompt v2 |
| `0bad1fe` | docs: WO17 report, tier runs, single eval, HANDOFF update |

---

## 9. Open items for Alex

1. Run `systemctl restart emg-rag-api` on the server, then confirm a
   follow-up in the UI shows the "Interpreted as" line.
2. Verify the 38 draft keys in `evals/golden_conversations.csv` and flip
   their status to `verified`; re-run `python evals/run_eval.py --conversation`
   to get the first number against the 80% target.
3. Decide whether history lookback should skip refusals (affects C15.3).
4. Optionally: add a "was X better?" example to the rewriter prompt for
   C5.3, and trim the prompt for cost and latency. Either change requires
   re-recording the fixtures with `python evals/make_rewrite_fixtures.py`.

### How to add a golden conversation

Append rows to `evals/golden_conversations.csv` with `conv_id`, `turn`,
`question`, `expected_standalone` (the self-contained question, or `SAME`),
`expected_route`, `expected_answer`, `status`, and `notes` holding the psql
that produced the key. Keep keys to the numbers the question actually asks
for. Run the tier, and flip `status` to `verified` only after checking the
key by hand.

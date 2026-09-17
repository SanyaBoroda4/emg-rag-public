# WO17 — Conversational follow-ups (question rewriting, measured)

Date: 2026-09-17 · commits `2ec454b` … `da9c1f2` (+ this report) · baseline
WO16 final `d76e190` · conversation runs `2026-09-17-1044/1049/1054-conv-wo17.json`
@ `7141016` · single-question eval `2026-09-17-1038-wo17-single.json` @ `49eef59`.

**The service still runs the WO16 code.** `systemctl restart emg-rag-api`
is Alex's step (the permission policy blocks Claude Code from systemd);
until it runs, https://rag.emgcheckbot.us answers single questions only.
The conversational path was verified in-process on the server with the
new code (FastAPI TestClient) and through the eval tier.

## Headline

| | before (Part 0) | after |
|---|---|---|
| follow-up turns answered correctly | **1/20** (16 refused, 3 answered the wrong thing) | **15–16 / 18** across 3 runs (83–89%), all `draft` — no `verified` rows yet, so the ≥80%-on-verified target is not yet measurable |
| standalone turns passed through byte-identical | — | **20/20 in every run** (60/60) |
| single-question eval (82) | WO16 floor 74–76 | **73/82** — one below the floor, and the one is Q58 with byte-identical answer/SQL/chunks (the judge coin WO14 measured at 2/7 on that row); routing 96.3%, R@10 0.818 unchanged |
| rewrite cost / latency per call | — | **$0.0014 / 1.1–2.6 s, mean 1.8 s** — both above the WO's ≈$0.0005 / <1 s expectation (see Surprises) |
| run-to-run variance (3 runs) | — | standalone flag: **0 turns differed**; rewrite text: 1 turn (C12.2, three equivalent phrasings); correctness: 1 turn (C1.2, SQL-lane jitter) |

## Part 0 — the problem, measured before building

Every follow-up-shaped turn of the golden conversations was run **as typed,
with no history**, through the unchanged pipeline (`/tmp/wo17_part0.py`,
20 turns, $0.03):

| turn | question as typed | route | what happened |
|---|---|---|---|
| C1.2 | And how many of those were in March 2026? | refuse | refused |
| C1.3 | What about Ihor/Tolik? | semantic | listed random notes mentioning Ihor/Tolik |
| C2.2 | And in 2025? | refuse | refused |
| C2.3 | Which city did she sell the most in? | refuse | refused |
| C3.2 | How many of those are complete? | refuse | refused |
| C4.2 | What about in 2025? | refuse | refused |
| C5.2 | And for 2024? | refuse | refused |
| C5.3 | Was 2023 better? | refuse | refused |
| C6.3 | What did the notes say on those jobs? | refuse | refused |
| C7.2 | And how many jobs do we have in Kiawah Island? | structured | **178 — correct** (self-contained) |
| C8.2 | How many of those were in 2024? | refuse | refused |
| C9.2 | How many of those are canceled? | refuse | refused |
| C10.2 | And in 2023? | refuse | refused |
| C10.3 | Which year was higher? | refuse | refused |
| C11.2 | and templates? | semantic | "your question is incomplete" + six random template notes |
| C12.2 | Is that more than Leo's? | refuse | refused |
| C13.2 | And Summerville? | semantic | five Summerville notes, no count |
| C13.3 | Which of the two has more? | refuse | refused |
| C14.2 | Who were the salespeople on those jobs? | refuse | refused |
| C15.3 | How many of those quiet jobs were quoted in 2025? | refuse | refused |

1/20. The router's refuse branch is what a follow-up hits without context.

## Part 1 — the rewriter (`retrieval/rewrite.py`, commits `2ec454b`, `7141016`)

`rewrite(question, history) -> RewriteResult(standalone, question, cost_usd,
latency_ms, reason, history_used)`. Haiku 4.5, temperature 0, JSON schema
`{standalone, question, reason}`. Three things are enforced in code, not
left to the model: **a standalone question is returned verbatim** (the flag
is the model's, the text never is); **no call with empty history or after a
refuse**; **any failure fails open** to verbatim. Own Langfuse generation
span `rewrite` inside the `ui` trace with `history_turns` and the decision.
The model sees per prior turn: the question as typed, the question it was
resolved to, route, answer (≤600 chars), SQL — never rows.

### The prompt, verbatim (v2, `7141016`)

```
You rewrite follow-up questions in a conversation with a question-answering system over a countertop company's job-tracking and invoicing data. You do NOT answer questions. You output JSON only.

You are given the previous turns of the conversation (each with the question as typed, the self-contained question it was resolved to, the route the system took, the answer it gave, and the SQL if any) and the user's NEW question.

Decide whether the new question stands on its own.

- If it stands on its own, return {"standalone": true, "question": "<the new question, unchanged>", "reason": "..."}. Err on the side of standalone: a wrong rewrite is worse than no rewrite. A question that names its own subject, place, person, crew, year or metric is standalone even if the topic continues.
- Otherwise return {"standalone": false, "question": "<one self-contained question>", "reason": "..."} that resolves ONLY:
  * pronouns and deixis ("those", "that salesperson", "she", "the same", "the two");
  * elided filters ("and in 2025?", "what about Mount Pleasant?", "and Summerville?") — start from the MOST RECENT turn's resolved question and keep every one of its filters (person, crew, place, year, month, status, metric) that the new question does not replace;
  * comparatives ("more than last time", "which was higher?", "is that more than X's?") — the rewrite must ask for the COMPARISON and name BOTH sides, e.g. "Is Ivan Andreev's average job size in the first half of 2026 larger than Leo's?" — never just ask for the second side.
- Never invent a filter, entity, year or metric that the history does not contain. Keep the user's wording where you can; write the rewrite the way the user would have typed the full question.
- Never copy numbers, totals or answers from the history into the rewrite ("West Ashley with 603 jobs" is wrong; "West Ashley or Summerville" is right) — the system will look the numbers up itself.
- If the new question is ambiguous between two readings, pick the reading closest to the previous turn's topic and make it explicit in the rewrite, so the user can see and correct it.
- Only the history shown exists. Do not use anything else.
```

User message: `Previous turns:\n\n<Turn k / user asked / resolved to / route /
answer / SQL …>\n\nNEW question: <q>\n\nJSON:`.

v1 → v2: run 1 of the tier (11/18) showed three failure shapes — C1.3 kept
turn 1's window instead of the most recent turn's month, C12.2 dropped the
comparison, C13.3 pasted "with 603 jobs" into the rewrite and the router
refused it. v2 adds the three rules above; runs 2–4 went 15–16/18.

### The 20 unit-test cases (`evals/fixtures/rewrite_cases.json`, `tests/test_rewrite.py`, 8 tests, no LLM)

| id | kind | history turns | question | recorded output |
|---|---|---|---|---|
| S01 | standalone | 2 | What is the capital of France? | SAME (verbatim) |
| S02 | standalone | 1 | Which jobs had a template wasted because cabinets weren't ready? | SAME (verbatim) |
| S03 | standalone | 1 | How many wasted templates have we had in total? | SAME (verbatim) |
| S04 | standalone | 1 | Which jobs included a waterfall edge? | SAME (verbatim) |
| S05 | standalone | 1 | How many jobs do we have in Mount Pleasant? | SAME (verbatim) |
| S06 | standalone | 1 | What is our overall quote-to-moved-forward conversion rate? | SAME (verbatim) |
| S07 | standalone | 1 | How many jobs did Leo install in the first half of 2026? | SAME (verbatim) |
| S08 | standalone | 1 | Were there jobs where we could not get material into the building? | SAME (verbatim) |
| S09 | standalone | 2 | How many quotes have we issued in total? | SAME (verbatim) |
| S10 | standalone | 1 | Which salesperson had the most wasted templates? | SAME (verbatim) |
| F01 | followup | 1 | And how many of those were in March 2026? | How many jobs did Leo install in March 2026? |
| F02 | followup | 2 | What about Ihor/Tolik? | How many jobs did Ihor/Tolik install in the first half of 2026? ⚠ kept turn 1's window |
| F03 | followup | 1 | And in 2025? | How many jobs has Natalia Pavlenko sold in 2025? |
| F04 | followup | 2 | Which city did she sell the most in? | Which city did Natalia Pavlenko sell the most jobs in during 2025? |
| F05 | followup | 1 | How many of those are complete? | How many jobs in Mount Pleasant are complete? |
| F06 | followup | 1 | What about in 2025? | Which salesperson had the most wasted templates in 2025? |
| F07 | followup | 2 | Was 2023 better? | What was our quote-to-moved-forward conversion rate in 2023, and was it better than the 63.4% we had in 2024? ⚠ copied a number |
| F08 | followup | 1 | How many of those are canceled? | How many jobs that went quiet after a quote are canceled? |
| F09 | followup | 2 | Which year was higher? | Was the total invoiced amount in 2024 higher than in 2023? |
| F10 | followup | 1 | Who were the salespeople on those jobs? | Who were the salespeople on the jobs where a template was wasted because cabinets weren't ready? |

The tests assert: 20 cases, 10 + 10; every standalone case returns the
input byte-identical with `standalone=True`; every follow-up returns the
recorded rewrite; no call with empty history or after a refuse; a raising
or unparseable model fails open; only the last 3 turns reach the prompt.
Fixtures are recorded by `evals/make_rewrite_fixtures.py` (re-run when the
prompt changes; `--check` diffs). The two ⚠ rows are real, recorded
weaknesses, not test failures — they are what the model does.

## Part 2 — wiring and storage (commits `f0de759`, `6a5421d`, `6027e2b`)

- `sql/021`: `serve.asks` + `conversation_id uuid`, `rewritten_question`,
  `standalone`, `parent_ask_id`, index `(user_name, conversation_id, asked_at)`.
  Applied; `rag_serve` inherits the column privileges.
- `/api/ask` takes `conversation_id` (new uuid when absent or invalid),
  loads **this user's** last ≤3 completed turns of that conversation, calls
  `retrieval.pipeline.ask_conversational()` — one `ui` trace with the
  `rewrite` span before the router — and stores the four new columns (error
  rows too). Response adds `question`, `rewritten_question`, `standalone`,
  `rewrite_reason`, rewrite cost/latency, `history_turns`, `conversation_id`,
  `parent_ask_id`. `/api/history` groups by conversation (title = first
  question, turn count, last route; pre-WO17 rows are one-turn
  conversations); `/api/history/{ref}` (ask id or uuid) returns the whole
  conversation, 404 unless the caller's.
- UI: turns stack in one conversation; **New conversation** resets; under a
  follow-up answer a grey **"Interpreted as: <rewritten question>"** line with
  **"Not what I meant? Rephrase"**, which copies the rewrite into the box for
  editing; sidebar lists conversations; opening one shows every turn and lets
  the next question continue it. Feedback per turn. Still one file, no CDN,
  nothing in localStorage.
- In-process check on the server (TestClient, new code): C1 as a
  conversation → turn 2 "Interpreted as: How many jobs did Leo install in
  March 2026?" (8 jobs), turn 3 "…Ihor/Tolik install in March 2026?" (23
  jobs), each with `parent_ask_id` chaining; then "What is the capital of
  France?" refused and **"And how many jobs do we have in Kiawah Island?"
  answered 178 with no rewrite call** (`rw_ms=0`); history grouped as one
  5-turn conversation; whole conversation by uuid and by any turn id; as
  `office` both 404; a bad `conversation_id` starts a fresh one.

**Proof the single-question path is untouched** (`git diff d76e190..HEAD`):
`evals/harness.py` **0 lines**; `evals/run_eval.py` only the
`--conversation` flag (8 lines, dispatching to `evals/run_conversations.py`);
`retrieval/pipeline.py` only the added `ask_conversational()` and result
fields; router / SQL lane / answerer / judge / views: no change. The CLI
never calls the rewriter.

## Part 3 — golden conversations and the tier

`evals/golden_conversations.csv`: **15 conversations, 38 turns** (18
follow-ups, 20 standalone incl. two deliberate mid-conversation standalones,
two refuses, two post-refuse turns, one deliberately ambiguous follow-up),
all `draft` — every key computed by psql on 2026-09-17, SQL in the notes.
**Alex verifies before they count.** Five draft keys were corrected after
run 1 (my errors: route `hybrid` for the cabinets question as in golden
Q82; invoice counts the question never asked; C14.2 keyed on names so the
judge scores it; C2.3's key following the carry-forward rule).

`evals/run_conversations.py` (also `run_eval.py --conversation`): turns in
order, **real prior answers as history**, through `ask_conversational`.
Per turn: rewrite match (flag; for follow-ups the rewrite judged equivalent
to the expected standalone by the Sonnet judge, yes/no), route match,
correctness (numeric match / judge / refusal as tier 3). Verified and draft
summarised separately.

## Part 4 — results, three consecutive runs @ `7141016`

| run | follow-ups correct | rewrite ok | route ok | standalone passed through | all turns | rewrite calls / $ / mean ms | cost | wall |
|---|---|---|---|---|---|---|---|---|
| 1 `1044` | 15/18 | 16/18 | 17/18 | **20/20** | 32/38 | 21 / $0.030 / 1,806 | $0.50 | 303 s |
| 2 `1049` | **16/18** | 16/18 | 17/18 | **20/20** | 33/38 | 21 / $0.030 / 1,712 | $0.49 | 293 s |
| 3 `1054` | 15/18 | 16/18 | 17/18 | **20/20** | 32/38 | 21 / $0.029 / 1,886 | $0.49 | 299 s |

(21 rewrite calls per run = 38 turns − 15 first turns − 2 post-refuse turns.)

### Per turn — question → rewrite → route → verdict (runs side by side)

| turn | question | expected standalone | rewrite (r1; r2/r3 same unless shown) | route | correct r1/r2/r3 |
|---|---|---|---|---|---|
| C1.1 | How many jobs did Leo install in the first half of 2026? | SAME | SAME | structured | ✗/✗/✗ — SQL lane returned a bare `COUNT` (16) without visits/sq ft: the Q68 jitter |
| C1.2 | And how many of those were in March 2026? | Leo, March 2026 | How many jobs did Leo install in March 2026? | structured | ✗/✓/✗ — same jitter on the three-number key (8 / 10 / 497) |
| C1.3 | What about Ihor/Tolik? | Ihor/Tolik, March 2026 | How many jobs did Ihor/Tolik install in March 2026? | structured | ✓/✓/✓ |
| C2.1 | How many jobs has Natalia Pavlenko sold? | SAME | SAME | structured | ✓/✓/✓ |
| C2.2 | And in 2025? | Natalia, 2025 | How many jobs has Natalia Pavlenko sold in 2025? | structured | ✓/✓/✓ |
| C2.3 | Which city did she sell the most in? | Natalia, 2025, top city | Which city did Natalia Pavlenko sell the most jobs in during 2025? | structured | ✓/✓/✓ |
| C3.1 | How many jobs do we have in Mount Pleasant? | SAME | SAME | structured | ✓/✓/✓ |
| C3.2 | How many of those are complete? | Mount Pleasant, Complete | How many complete jobs do we have in Mount Pleasant? | structured | ✓/✓/✓ |
| C3.3 | What is the capital of France? | SAME | SAME | refuse | ✓/✓/✓ |
| C4.1 | Which salesperson had the most wasted templates? | SAME | SAME | structured | ✗/✗/✗ — lane grouped by year (Alex Sorokin 2025): the Q76 jitter |
| C4.2 | What about in 2025? | …in 2025 | Which salesperson had the most wasted templates in 2025? | structured | ✓/✓/✓ |
| C5.1 | overall conversion rate | SAME | SAME | structured | ✓/✓/✓ |
| C5.2 | And for 2024? | 2024 rate | What is our quote-to-moved-forward conversion rate for 2024? | structured | ✓/✓/✓ |
| C5.3 | Was 2023 better? | 2023 vs 2024 | What is our quote-to-moved-forward conversion rate for 2023? | structured | ✗/✗/✗ — **rewriter dropped the comparison** (rewrite ✗ all runs) |
| C6.1 | wasted templates total | SAME | SAME | structured | ✓/✓/✓ |
| C6.2 | Which jobs had a template wasted because cabinets weren't ready? | SAME | SAME | hybrid | ✓/✓/✓ |
| C6.3 | What did the notes say on those jobs? | …on the cabinets jobs | What did the notes say on the jobs that had a template wasted because… | hybrid | ✓/✓/✓ |
| C7.1 | capital of France | SAME | SAME | refuse | ✓/✓/✓ |
| C7.2 | And how many jobs do we have in Kiawah Island? | SAME (post-refuse) | SAME, no call | structured | ✓/✓/✓ |
| C8.1 | quotes issued in total | SAME | SAME | structured | ✓/✓/✓ |
| C8.2 | How many of those were in 2024? | quoted in 2024 | How many quotes have we issued in total in 2024? | structured | ✓/✓/✓ |
| C9.1 | quiet after a quote | SAME | SAME | structured | ✓/✓/✓ |
| C9.2 | How many of those are canceled? | quiet AND Canceled | How many jobs that went quiet after a quote are canceled? | structured | ✓/✓/✓ |
| C10.1 | invoice 2024 | SAME | SAME | structured | ✓/✓/✓ |
| C10.2 | And in 2023? | invoice 2023 | How much did we invoice in 2023? | structured | ✓/✓/✓ |
| C10.3 | Which year was higher? | 2023 vs 2024 | Was the total invoiced in 2024 higher than in 2023? | structured | ✓/✓/✓ |
| C11.1 | Natalia jobs sold | SAME | SAME | structured | ✓/✓/✓ |
| C11.2 | and templates? *(ambiguous by design)* | wasted templates, Natalia | How many templates has Natalia Pavlenko sold? | structured | ✗/✗/✗ — **a visible but wrong reading** ("templates sold" is not a thing); the user sees it and can rephrase |
| C12.1 | Ivan Andreev avg job size H1 2026 | SAME | SAME | structured | ✓/✓/✓ |
| C12.2 | Is that more than Leo's? | Ivan vs Leo | r1 "What was Leo's average job size…, and was it more than Ivan Andreev's?" / r2 "Was Ivan Andreev's … larger than Leo's?" / r3 "Is Ivan Andreev's … larger than Leo's?" | structured | ✓/✓/✓ — the only rewrite-text variance |
| C13.1 | West Ashley jobs | SAME | SAME | structured | ✓/✓/✓ |
| C13.2 | And Summerville? | Summerville jobs | How many jobs have we done in Summerville? | structured | ✓/✓/✓ |
| C13.3 | Which of the two has more? | West Ashley vs Summerville | Does West Ashley have more jobs than Summerville? | structured | ✓/✓/✓ (v1 had refused on the pasted numbers) |
| C14.1 | cabinets jobs | SAME | SAME | hybrid | ✓/✓/✓ |
| C14.2 | Who were the salespeople on those jobs? | …on the cabinets jobs | Who were the salespeople on the jobs that had a template wasted because… | hybrid | ✓/✓/✓ |
| C15.1 | quiet after a quote | SAME | SAME | structured | ✓/✓/✓ |
| C15.2 | capital of Spain | SAME | SAME | refuse | ✓/✓/✓ |
| C15.3 | How many of those quiet jobs were quoted in 2025? | SAME (post-refuse rule) | SAME, no call | refuse | ✗/✗/✗ — **the rule's cost**: "those" two turns back is never resolved after a refuse |

Per conversation (run 1): C2, C3, C6, C10, C13 3/3; C7, C8, C9, C12, C14
2/2; C5, C15 2/3; C1 1/3; C4 1/2; C11 1/2.

### Variance across the three runs

- standalone **flag**: identical on all 38 turns in all runs.
- rewrite **text**: differed only on C12.2 (three phrasings of the same
  comparison, all judged equivalent, all answered correctly). Temperature 0
  on Haiku is outcome-stable, not byte-stable — same as WO13 found.
- **correctness**: differed only on C1.2 (✗/✓/✗) — the SQL lane once
  returned visits and sq ft, twice a bare count; not the rewriter.

### What the 3 persistent reds are

| turn | cause | who owns it |
|---|---|---|
| C1.1, C4.1 (standalone!), C1.2 | SQL-lane text jitter on keys that demand three numbers (Q68/Q76 class) | the WO13/WO14 floor; not conversational |
| C5.3 | rewriter turns "Was 2023 better?" into a single-year question despite the v2 comparative rule (C10.3, C12.2, C13.3 — the other comparatives — are fine) | rewriter prompt; one more iteration or a fixture-driven example |
| C11.2 | the deliberately ambiguous "and templates?" → "templates has Natalia Pavlenko sold" | by design: the rewrite is visible and wrong; the page's "Rephrase" is the fix |
| C15.3 | post-refuse rule makes "those quiet jobs" unresolvable | the WO rule; alternative: skip refuses when looking back, out of scope |

## Single-question eval — unchanged path, one judge flip

`2026-09-17-1038-wo17-single.json` @ `49eef59` (service idle): routing
**96.3%**, R@10 **0.818**, MRR 0.660, generation **73/82**, faithfulness
94.9%, $1.03, 241 s. Failing 11, 41, 45, 47, 49, 56, **58**, 68, 76 — the
WO16 set plus Q58, whose answer, SQL, rows and chunks are byte-identical to
the WO16 final; only the Sonnet verdict differed (WO14 measured Q58 at 2 ✓ /
7 ✗ over nine judgments). The eval path has no WO17 code in it (diff above).

## What a user sees

- **A follow-up:** the answer card carries a grey line *Interpreted as: How
  many jobs did Leo install in March 2026?* above the answer, with *Not what
  I meant? Rephrase* — clicking it puts that sentence into the box to edit.
- **A refuse, then a follow-up** (C7): "What is the capital of France?" gets
  the orange `refuse` badge and the one-line refusal; "And how many jobs do
  we have in Kiawah Island?" is answered as a fresh question (178 jobs),
  with **no** "Interpreted as" line because nothing was rewritten.
- **The ambiguous case** (C11): after "How many jobs has Natalia Pavlenko
  sold?", typing "and templates?" shows *Interpreted as: How many templates
  has Natalia Pavlenko sold?* and an answer of 1,198 — visibly wrong, one
  click from being rephrased. That is the design working as intended even
  though the row scores ✗.

## Got worse

- **The service is not restarted.** Until Alex runs `systemctl restart
  emg-rag-api`, production still serves WO16 (single questions; no
  "Interpreted as" line; the new page is not served). Documented in HANDOFF.
- **Single-question eval 73/82**, one below the WO16 floor: Q58, judge coin
  on an identical answer. No path change; reported, not explained away.
- **Rewrite latency 1.8 s mean, cost $0.0014/call** — roughly double the
  WO's expectations on both. A follow-up therefore costs ~1.8 s more than a
  standalone question. The prompt is ~1.2 k input tokens with the history;
  the `reason` field adds ~60 output tokens per call. Both are trimmable
  (drop `reason`, shorten history answers to 300 chars) but were kept for
  this measured first version.
- **Nothing verified yet.** All 38 turns are `draft`; the ≥80% target is
  stated on draft keys only.

## Surprises

1. **The refuse branch is the follow-up killer.** 16 of 20 follow-ups as
   typed were *refused*, not misrouted; the router reads "And in 2025?" as
   off-topic. The rewriter removes the whole class.
2. **Temperature-0 rewrites are outcome-stable, not byte-stable**, exactly
   like the SQL lane: 0/38 flag flips over three runs, 1 text variation.
3. **The draft keys were the first thing the tier broke.** Five of run 1's
   eleven reds were my keys (unasked counts, a wrong route, numbers the
   judge can't match) — the same "key over-specification" lesson as WO11's
   Q26 and WO14's Q26 fix, now caught in one run instead of three WOs.
4. **Comparatives are the rewriter's weak spot**, and specifically the
   "was X better?" form: C5.3 fails every run while the three other
   comparatives pass. One targeted example in the prompt is the likely fix.
5. **The post-refuse rule has a measurable price**: exactly one golden turn
   (C15.3). Whether "those" should look past a refuse is a product call.
6. **Carry-forward is a policy, not a fact.** "Which city did she sell the
   most in?" after "And in 2025?" — the rewriter keeps 2025; the key had to
   follow the rule, not my first instinct.

## Cost

Part 0 $0.03 · fixtures 2 × $0.02 · tier run 1 (v1) $0.47 · tier ×3 (v2)
$1.48 · in-process API checks ~$0.10 · single eval $1.03 → **≈ $3.15**
(tripwire $5).

# WO20 — Correctness pass: close the known open items

Baseline `760b6cd` (WO19). Seven items, one commit each, measured together
at `1e4a4e6` and, after the one fix the measurement forced (§8.4), at
`a070597`. No migrations. Cost tripwire $8. The 38 golden conversation
turns stay `draft`; draft and verified are reported separately. Service
restart is Alex's step.

## 1. Q16 key — confirmed, no change

```
grep -n "^16," evals/golden_set.csv
17:16,How many quotes have we issued in total?,structured,4423,,"SELECT COUNT(*) FROM v_quoted_jobs (sql/019, v2) …
```

The key is 4,423 (`v_quoted_jobs` v2, ruling of 2026-09-16). WO15 had
applied it. No commit.

## 2. Rewriter: "Was X better?" comparatives (C5.3) — `abd6564`, fixtures `7609331`

**Before.** In all three WO17 conversation runs, C5.3 "Was 2023 better?"
(after "What is our overall quote-to-moved-forward conversion rate?" → "And
for 2024?") was rewritten to a single-year question ("What is our
quote-to-moved-forward conversion rate for 2023?"), so the comparison was
lost and the turn scored ✗/✗/✗ (`evals/results/wo17_followups.md`, line 209).
The other three comparatives (C10.3, C12.2, C13.3) passed.

**Change.** One worked example of that exact form added to the rewriter
system prompt (`retrieval/rewrite.py`): "Was X better / worse / higher?" is
always a comparative; X is the new value of the previous turn's filter, the
other side is the previous turn's own value, the metric is the previous
turn's metric; the wrong rewrite (single year) is shown as wrong. Fixture
case F11 = C5.3 added to `evals/make_rewrite_fixtures.py`; the recorder's
case count is 21 (10 standalone + 11 follow-ups). Fixtures re-recorded on
the server (21 Haiku calls) after item 3 landed, so they reflect both
changes.

**Evidence (recorder output, `python evals/make_rewrite_fixtures.py`):**

```
ok F07 followup   'Was 2023 better?'
     -> standalone=False 'Was the quote-to-moved-forward conversion rate in 2023 better than in 2024?'
ok F11 followup   'Was 2023 better?'
     -> standalone=False 'Was the quote conversion rate in 2023 better than in 2024?'
wrote /opt/emg-rag/evals/fixtures/rewrite_cases.json (21 cases)
```

F07 was already C5.3 in the WO17 fixture set (the order asked for F11; both
are kept). The two recordings of the same input differ by one wording
("quote-to-moved-forward" vs "quote") at temperature 0: the prompt is
identical, so this is the model's own run-to-run wording jitter, and both
name both sides. All 10 standalone cases pass through byte-identical.
`python tests/test_rewrite.py`: 11 tests pass, including
`test_was_x_better_names_both_sides` (both years present, a comparison word
present).

## 3. Look past refused turns (C15.3) — `e54c2d6`

**Before.** `rewrite()` returned standalone-by-rule whenever the previous
turn's route was `refuse`, so C15.3 "How many of those quiet jobs were quoted
in 2025?" (C15.1 quiet jobs → C15.2 capital of Spain → C15.3) never resolved
"those" and was refused ✗/✗/✗ (WO17 report, line 233).

**Change.** Refused turns are filtered out before the last-three slice:
`turns = [t for t in history if t.route != "refuse"][-MAX_HISTORY:]`. With
nothing left there is no model call and the question passes through
verbatim, reason "no on-topic history (refused turns are skipped)". The UI
history loader (`serve/app.py`) adds `AND COALESCE(route,'') <> 'refuse'` so
a refuse does not consume one of the three slots either; the conversation
tier appends every turn to its history list and the same filter applies.

**Tests** (`tests/test_rewrite.py`): "refused turns never appear in the
prompt" (a refuse in the middle: the prompt holds Turn 1 and Turn 2, no
"Spain", `history_used == 2`), "all-refused history → no call" (verbatim),
and "refuses do not consume history slots" (three on-topic turns with a
refuse after each: all three are in the prompt).

**Expected:** C15.3 resolves; C7.2 ("And how many jobs do we have in
Kiawah Island?" after a refuse) stays byte-identical because its only
history turn is the refuse, which leaves nothing, which means no call and a
verbatim pass-through exactly as before. Measured in §8.

## 4. Answer prompt: attribute notes by provenance (Q30) — `a1a5e06`

**Diagnostic — what provenance reaches the answer prompt today.**
`retrieval/answer.py:_format_chunks` gives the model, per chunk:
`[chunk <id>, job <id> "<job name>"]`, an `[AUTOMATED SYSTEM RECORD]` tag
when `is_bot_generated`, then `context: <context_text>` and `note: <raw>`.
The context sentence is built by `ingest/context_facts.py` from: job name,
city, salesperson, account, process, status, materials on the job; for an
activity note "this note is on a <type_name> activity", "activity status
<status>", "dated <date>" or "undated", "phase <n>"; for an area note "this
note is on the '<area>' area", room type, square footage, material,
supplier. There is no author field anywhere in the source data: the
salesperson in the context is the job's salesperson, not the note's writer.
That is exactly the ambiguity Q30's answer fell into (a template note about
dimensions described as a salesperson's comment; 5 ✓ / 4 ✗ over nine
judgments in WO14).

**Change.** One rule added to the answer system prompt: describe a note by
the provenance its context line gives ("a template note", "an install
note", "a note on the kitchen area", "an automated message"); never call it
a salesperson's comment, a customer's words or a crew report unless the
provenance says so; a note on a job whose salesperson is named in the
context was not necessarily written by that salesperson.

**Measured in §8:** three re-judges of full run 1; every semantic and hybrid
question compared with the WO17 single run.

## 5. SQL validator: columns per alias (Q41 / Q26 class) — `da5a346`, fix `a070597`

**Before.** `validate_sql` checked every column name against the union of
all views' columns. `SELECT DISTINCT j.job_id, j.job_name, j.customer FROM
v_job_areas AS j …` passed (customer exists on `v_jobs`) and Postgres raised
`UndefinedColumn: column j.customer does not exist` (Q41 in the WO16 final
and WO17 single runs, `generation.sql_error`). Execution errors get no
repair attempt (`run_structured` retries only on a validator `ValueError`),
so the question was scored incorrect by rule. WO11's Q26 was the same class
unqualified: `salesperson` selected from a view that lacked it.

**Change.** After the global check (kept: necessary, not sufficient), a
per-alias pass resolves every column through `sqlglot.optimizer.scope.
traverse_scope`. For each scope, sources are mapped alias → (view, columns)
for whitelisted views and alias → projected columns for CTE/subquery scopes
when sqlglot can name them (a `SELECT *` makes the source unknown and it is
skipped). A qualified column whose alias is a known source must be in that
source's columns; an unqualified column is checked only when the scope has
exactly one source, and select-list aliases used in ORDER BY / HAVING are
allowed. A column is checked only in the scope whose SELECT is its nearest
ancestor (`a070597`; the first version also checked a scalar subquery's
unqualified columns against the outer scope and rejected valid SQL in run 1,
§8.4). Any exception inside the scope machinery skips the pass entirely:
this code may reject only what Postgres would reject. Why `scope` rather
than `optimizer.qualify`: qualify rewrites the query and raises on things
Postgres accepts (ambiguous unqualified columns across a join, unknown
functions); scope only reads. sqlglot 30.14 on the server, 30.18 locally,
same results.

The message is precise and feeds the existing one-shot repair:
``column `customer` is not in `v_job_areas` (alias `j`); its columns are
area_name, backsplash, edge, job_id, job_name, material_name, room_type,
sink, sq_ft, supplier``.

**False-positive guard.** `tests/test_sql_validator.py::
test_every_recorded_run_sql_still_validates` replays every SQL string in
`evals/results/2026-09-17-0959-wo16-final.json` and
`2026-09-17-1038-wo17-single.json`: **116 of 116 accepted** (58 per run;
the order estimated ≈118). Seven constructed cases (CTE with named
projections, subquery alias, CTE with `SELECT *`, select alias in ORDER BY /
HAVING, unqualified columns across a USING join, correlated subquery,
EXTRACT over a join) are also accepted. Q41's SQL and a Q26-class SQL are
rejected with the messages above. 5 tests pass.

## 6. Example chips reachable by keyboard — `3132274`

`serve/static/index.html`: the six example chips are now
`<button type="button" class="chip">` with the same onclick; `button.chip`
restates the previous chip styling (12.5 px, hairline border, 3 px radius,
`--text-dim`) and resets the button font. Tab reaches them, Enter and Space
fire the click and fill the box. No other change.

## 7. Public-mirror money gap — `0b22ca1`, `015f22a`

`MONEY_NO_SIGN` in `scripts/public_scan.py`: a number with exactly two
decimals and a value ≥ 100, not preceded by a word character, `.`, `$`, `-`
or a digit-and-comma (the tail of a signed amount), not followed by a digit,
`.` or `%`. The transform rewrites it to `$[redacted]` after the signed
rule; the scanner reports it as `dollar_nosign`.

**Spot-check over every allowlisted text file at HEAD** (script in the
session; contexts printed with digits masked):

| file | hits | what they are |
|---|---|---|
| `docs/wo19_public_audit.md` | 1 | the example figure in the "known gaps" bullet (a mock number) |
| `evals/results/wo18_restyle.md` | 2 | mock rows in the ASCII wireframe |
| `ingest/link_invoices.py` | 2 | docstring examples of the amount format |
| `tests/test_public_guard.py` | 2 | the test's own amounts (now assembled at runtime) |

Before the digit-comma lookbehind the rule also matched the digits after
the thousands comma inside already-signed amounts in three data files (7
hits); those were the only false positives and they are excluded now. **No
latency, API cost, percentage, count, version, date or time was caught**;
the test covers `2.40 s`, `12.30 s`, `99.99 s`, `$0.0079`, `$1.04`,
`70.0%`, `63.42 %`, `100.00%`, `0.28.1`, `30.14.0`, `82 questions`,
`chunk 4075`, `2026-09-21`, `09:12:00.12`, `0.818`. Replacements in the
sanitised tree at `015f22a`: 3 `dollar_nosign` (the two reports' mock
figures and the invoice-linker docstring). 6 guard tests pass.

## Also — HANDOFF corrected (`1aaa84f`)

The WO18 report and HANDOFF said production still served the WO16 page; it
was serving WO17, restarted at `2b9c5fb`. HANDOFF's restart notes now say
so, and the WO20 restart note lists what the next restart brings.

## 8. Measurements

Two measurement chains ran on the server, unattended, one after the other.
Chain 1 at `1e4a4e6` (all seven items): full eval ×2, re-judge ×3 of full
run 1, conversation tier ×3. Run 1 exposed a false rejection in the new
validator (Q73, §8.4), fixed in `a070597`; the server had pulled that commit
before the conversation runs started, so those three ran at `a070597`.
Chain 2 at `a070597`: full eval ×2 and one more conversation run, so the
headline numbers are at the final commit.

### 8.1 Full eval, 82 questions

| run | commit | routing | generation | faithfulness | R@10 / MRR (reranked) | cost | wall (1 worker) | failing set |
|---|---|---|---|---|---|---|---|---|
| WO17 single (reference) | `49eef59` | 96.3% | 73 | 0.949 | 0.818 / 0.660 | $1.03 | 241 s (4 workers) | 11, 41, 45, 47, 49, 56, 58, 68, 76 |
| chain 1, run 1 (`2026-09-21-1320-wo20-full1.json`) | `1e4a4e6` | 96.3% | 74 | 0.910 | 0.818 / 0.660 | $1.07 | 677 s | 11, 41, 45, 47, 49, 56, 68, **73** |
| chain 1, run 2 (`2026-09-21-1330-wo20-full2.json`) | `1e4a4e6` | 96.3% | 73 | 0.923 | 0.818 / 0.660 | $1.04 | 601 s | 11, 30, 41, 45, 47, 49, 56, 68, **73** |
| chain 2, run 3 (`2026-09-21-1359-wo20-full3.json`) | `a070597` | 96.3% | **75** | 0.962 | 0.818 / 0.660 | $1.04 | 605 s | 11, 41, 45, 47, 52, 56, 68 |
| chain 2, run 4 (`2026-09-21-1411-wo20-full4.json`) | `a070597` | 96.3% | **75** | 0.924 | 0.818 / 0.660 | $1.07 | 701 s | 11, 41, 45, 47, 49, 56, 68 |

Routing and retrieval are unchanged (96.3%, 0.818 / 0.660: byte-identical
tier 1 and tier 2 numbers in every run). Generation is inside the 73–76
floor in every run; at the final commit both runs score 75 with **zero SQL
errors**, Q73 ✓ and Q30 ✓ in both. Runs 3 and 4 differ on one row (Q49 ✓ in
run 3, Q52 ✓ in run 4): both are judge coins from WO14's nine passes.

**Q41** no longer raises: in every run the first SQL validates and executes
(run 1: a `v_job_areas AS a JOIN v_jobs AS j` with `j.customer` on the right
alias, 480 rows) and the question fails on the judge against its key (the
key names one specific job with four materials; the answer lists the top
jobs by material count). That is the clean failure the order asked for, and
it is a key / over-inclusion question for the problem-questions pass, not a
lane error.

**Q58 and Q76** are green again (Q58 was a judge coin in WO17; Q76's SQL
text came out right this time). **Q30**: ✓ in run 1, ✗ in run 2 on a
differently worded answer, see 8.2.

### 8.2 Re-judge ×3 of run 1 (`1e4a4e6`, answers fixed, judge only)

`python evals/rejudge.py evals/results/2026-09-21-1320.json --passes 3 --out /tmp/wo20_rj` (passes committed as `2026-09-21-1334-wo20-rejudge-pass{1,2,3}.json`)

| pass | correct | failing set | Q30 |
|---|---|---|---|
| 1 | 74 | 11, 41, 45, 47, 49, 56, 68, 73 | ✓ |
| 2 | 73 | 11, 41, 45, 47, **48**, 49, 56, 68, 73 | ✓ |
| 3 | 73 | 11, 41, 45, 47, 49, **52**, 56, 68, 73 | ✓ |

**Q30 ✓ in all three**, as required. The judge's reasons, in part: pass 1
"appropriately notes that most other jobs lack salesperson comments"; pass 2
"correctly cites the job 1891 salesperson comment verbatim … notes that most
other jobs lack documented salesperson comments"; pass 3 "flagged job 180's
note as not clearly a salesperson comment, which is a reasonable nuance". The
rows that moved (Q48, Q52) are the known judge coins. Cost $0.46 / $0.45 /
$0.47.

**Run 2's Q30 ✗.** Both runs' answers describe the job-180 line identically:
"A job note (not attributed to salesperson) from the canceled job: …". The
two answers differ by one sentence elsewhere ("no salesperson notes
explaining the stall were retrieved" vs "no salesperson notes were retrieved
explaining why they stalled"). Run 2's judge objected that the answer
"incorrectly attributes a 'salesperson comment' to job 180", reading the
answer's lead sentence ("the retrieved notes contain salesperson comments for
only 2 of the 9") rather than the itemised line. The provenance rule fixed
the attribution line; the lead sentence still counts the job-180 note among
"salesperson comments". A follow-up rule ("when counting salesperson
comments, count only notes whose provenance says so") would close it; it was
not added here because it could not have been measured with three re-judges
inside the tripwire.

**Semantic and hybrid questions, runs 1 and 2 against the WO17 single run:**
no semantic question newly fails. Q58 (semantic) went ✗ → ✓ in both runs.
Q30 (hybrid) went ✓ → ✗ in run 2 only, explained above.

### 8.3 Conversation tier ×3 at `a070597` (+1 in chain 2)

`python evals/run_eval.py --conversation`, 15 conversations, 38 turns, all
`draft`, verified 0.

| run | file | follow-ups correct | standalone passed through | standalone correct | all turns | rewrite calls | cost |
|---|---|---|---|---|---|---|---|
| WO17 (reference, `7141016`) | `2026-09-17-1054-conv-wo17.json` | 15 / 18 | 20 / 20 | 17 / 20 | 32 / 38 | 21 | $0.49 |
| run 1 | `2026-09-21-1339-conv-wo20.json` | 15 / 18 | 19 / 20 | 19 / 20 | 34 / 38 | 22 | $0.51 |
| run 2 | `2026-09-21-1344-conv-wo20.json` | 15 / 18 | 19 / 20 | 19 / 20 | 34 / 38 | 22 | $0.51 |
| run 3 | `2026-09-21-1349-conv-wo20.json` | 15 / 18 | 19 / 20 | 19 / 20 | 34 / 38 | 22 | $0.49 |
| run 4 (chain 2) | `2026-09-21-1416-conv-wo20.json` | 16 / 18 | 19 / 20 | 19 / 20 | 35 / 38 | 22 | $0.52 |

The "19 / 20" is one row: C15.3 was labelled `SAME` in the golden file under
the old post-refuse rule, and under item 3 it is now (correctly) rewritten.
With C15.3 relabelled as the follow-up it is
(`evals/golden_conversations.csv`, committed after these runs), the same runs
read **16 / 19 follow-ups correct (17 / 19 in run 4, where C1.2 also passed) and
19 / 19 standalone turns passed through byte-identical** in every run. The standalone-versus-follow-up decision did
not vary on any of the 38 turns across the four runs; run 4 differs from
runs 1–3 on one row only (C1.2 ✓, a judge/answer flip on a follow-up whose
rewrite is identical).

Per turn, every turn that differs from the WO17 run, plus the three named
turns:

| turn | question | WO17 | run 1 | run 2 | run 3 | what happened |
|---|---|---|---|---|---|---|
| C5.3 | Was 2023 better? | ✗ | ✓ | ✓ | ✓ | rewritten to "Was the quote-to-moved-forward conversion rate in 2023 better than in 2024?"; both years and both numbers in the answer |
| C15.3 | How many of those quiet jobs were quoted in 2025? | ✗ | ✓ | ✓ | ✓ | the refuse at C15.2 is skipped; "those quiet jobs" resolves to C15.1; answer 279 = key |
| C7.2 | And how many jobs do we have in Kiawah Island? | ✓ | ✓ | ✓ | ✓ | the only history turn is the refuse → no call → verbatim, byte-identical |
| C4.1 | Were there jobs where we could not get material into the building? | ✗ | ✓ | ✓ | ✓ | standalone semantic; the judge accepted the answer in all three runs |
| C9.2 | How many of those are canceled? | ✓ | ✗ | ✗ | ✗ | rewrite identical to WO17's; the SQL lane added a spurious `j.status = 'Complete'` filter (27 instead of 1,093). No `sql_repair` span in the trace: the first SQL validated and ran, so this is generation jitter of the Q68/Q76 class, not the validator |

### 8.4 Surprise inside the measurement: Q73

Run 1 made Q73 red with ``ValueError: column `type_name` is not in
`v_job_sqft` ``. The model's SQL had a scalar subquery
`(SELECT COUNT(*) FROM v_activities WHERE … type_name = 'Install' …)` with
unqualified columns; sqlglot lists such a subquery's columns under the
enclosing scope as well as under its own, and the per-alias pass checked
`type_name` against the outer scope's only source. Valid SQL, rejected: the
exact failure the order said must never happen, which the seven hand-written
never-reject cases and the 116 recorded queries had not covered (both earlier
runs' Q73 SQL qualified every column with `a.`). Fix in `a070597`: a column
is checked only in the scope whose SELECT is its nearest ancestor; four
subquery shapes added to the test. Chain 2 is the re-measurement.

### 8.5 Unit tests

| file | tests | result |
|---|---|---|
| `tests/test_rewrite.py` | 11 (21 fixture cases, refuse-skip ×3, F11) | pass |
| `tests/test_sql_validator.py` | 5 (Q41, Q26-class, right alias, 11 never-reject shapes, 116 recorded queries) | pass |
| `tests/test_public_guard.py` | 6 (incl. two-decimal money) | pass |

## Got worse

- **C9.2 went ✓ → ✗ in all conversation runs** on SQL-text jitter (a
  spurious status filter on an identical rewrite). Not caused by any WO20
  change (no repair, identical rewrite), but it is a regression in the
  reported number: all-turns 34 / 38 would be 35 without it.
- **Full-run generation did not move**: 74 / 73 at `1e4a4e6` and 75 / 75 at `a070597` against 73 in the
  WO17 reference. Q41 fails cleanly now but still fails.
- **Q30 still flips** on the judge when the answer's lead sentence counts the
  job-180 note as a salesperson comment (run 2). The re-judge ×3 on run 1 is
  3 / 3 ✓; the residual is documented above.
- **One golden row changed** (C15.3's standalone label), by the order's own
  rule; the expected answer is untouched.
- **The measurement cost ≈ $7.66** against an $8 tripwire, because
  the validator bug forced a second chain.
- The first validator commit (`da5a346`) was wrong for one SQL shape and was
  live for the first two full runs; the fix is `a070597`.

## Surprises

- The false rejection (§8.4): a "never reject valid SQL" rule needs the
  recorded-query guard *and* shapes the model has not produced yet; the 116
  recorded queries contained no unqualified column inside a scalar subquery.
- The server pulled `a070597` while chain 1 was still running, although the
  tree was dirty with result files: `git pull` only refuses when the incoming
  commit touches a dirty file, and that commit touched none. So the
  conversation runs of chain 1 already carry the fix.
- Three conversation runs came out turn-for-turn identical (34 / 38, same
  failing turns, same flags): with temperature 0 in the rewriter the
  conversation tier is as reproducible as the single-question tiers, C9.2's
  wrong SQL included.
- F07 in the rewriter fixtures was already C5.3, so F11 duplicates it; the
  two recordings of the same input differ by one word at temperature 0.
- Q58 and Q76 went green with no change aimed at them (judge coin; SQL
  wording).

## Cost

| what | cost |
|---|---|
| chain 1: full ×2 | $1.07 + $1.04 |
| chain 1: re-judge ×3 | $0.46 + $0.45 + $0.47 |
| chain 1: conversation ×3 | $0.51 + $0.51 + $0.49 |
| chain 2: full ×2 + conversation ×1 | $1.04 + $1.07 + $0.52 |
| fixture recording (21 Haiku calls) | ≈ $0.02 |
| **total** | **≈ $7.66** (tripwire $8) |

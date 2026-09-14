# WO11 — Golden-set re-key, quoted-jobs definition, and two bugs

Date: 2026-09-14 · commits `41b4c20` … `0bc1265` · baseline: the WO10 run
`2026-09-14-0837-full.json` @ `ff101ab` (96.3 / 72.0 / 91.1)

Five changes, one commit each (re-keys → Q16 → conversion re-keys → Q26
fix → harness error rule → judge parity → loader fix), one full eval, one
judge-free structured subset. No new features; one new view
(`v_quoted_jobs`), one existing view widened by three columns.

## Headline

| run | commit | routing | generation | faithfulness | ctx precision | cost | wall |
|---|---|---|---|---|---|---|---|
| WO10 baseline `2026-09-14-0837-full.json` | `ff101ab` | 96.3% | **72.0% (59/82)** | 91.1% | 56.2% | $1.06 | 737 s (1 w) |
| **WO11 `2026-09-14-0920-wo11.json`** | `446c30e` | 96.3% | **90.2% (74/82)** | 89.9% | 59.0% | $1.11 | 271 s (4 w) |

Under the final Q26 key (`0bc1265`, see Change 4) the same run scores
**75/82 = 91.5%**: Q26's answer text is unchanged and matches the final key
by numeric match (verified offline on the run's stored answer, not re-run).

By block:

| block | before | after |
|---|---|---|
| Q1–63 core | 41/63 | 55/63 (56 with final Q26 key) |
| Q64–73 crew workload | 9/10 | 10/10 |
| Q74–82 wasted templates | 9/9 | 9/9 |
| the 13 re-keyed existence questions | **1/13** | **10/13** |

Expected ≥80%; landed 90.2%. The movement is Changes 1 and 3 exactly as
predicted: +9 existence re-keys, +3 conversion re-keys (Q62 already
passed), +Q16, +Q28, +Q30, and two answerer-phrasing flips (Q31, Q68 back
to ✓). Two questions got worse: Q26 (my key, fixed) and Q58 (draft).

## Change 1 — existence re-keys (commit `41b4c20`)

Note first: the work order said Q38 "was re-keyed to verify ≥1 genuine
match and now passes". That re-key had never landed — the CSV still held
the single-chunk key and Q38 passed on judge leniency. It is re-keyed here
with the others (13 rows, not 11: the WO's list has 12 ids plus Q38). The
`MULTIPLE — …` `relevant_ids` format also broke the golden loader, which
parsed that column as integers (`446c30e` fixes it: non-numeric tokens are
ignored, so these rows carry no gold ids and skip tier 2).

| q | before | after | judge, after |
|---|---|---|---|
| Q38 difficult customers | ✓ | ✓ | cites two of the key's examples plus extras |
| Q39 custom cutouts | ✗ | ✓ | matches the expected examples |
| Q42 bathroom niches/benches | ✗ | ✓ | 3071, 3529, 4448 + plausible extras (see Change 5 for its faithfulness flag) |
| Q43 backsplash complications | ✗ | ✓ | 2957, 3226 and others |
| Q44 sinks stored at shop | ✗ | ✓ | 243, 1097, 5271, 3298; correctly excluded a one-sink job |
| **Q45 tips (scoped)** | ✗ | **✗** | found Lisa Harrell's tip, then counted a $50 payment and a balance check as tips |
| **Q47 countertops to another room (scoped)** | ✗ | **✗** | found 1932, then added peninsula→island, sink reuse, same-room reinstall |
| Q48 recut pieces | ✗ | ✓ | 6 of 7 examples |
| **Q49 warranty (scoped)** | ✗ | **✗** | found 1575, then labelled scratches and rework as warranty |
| Q51 damaged material | ✗ | ✓ | six supported jobs |
| Q52 customer's sink reused | ✗ | ✓ | 2044, 2318, 4923, 85, 2315 |
| Q54 cash on site | ✗ | ✓ | 2167, 228, 4284 + one more |
| Q57 waterfall edge | ✗ | ✓ | six jobs; 3298 not retrieved, allowed |

**The three scoped keys fail for the right reason.** In all three the
system finds the genuine example and then over-generalises exactly the way
the WO described; the judge now names the boundary it crossed. These are
real system findings — the answerer does not distinguish a gratuity from
a payment, countertop reuse from sink reuse, or a warranty claim from a
repair — and they stay red until the answerer is taught to, not until the
key is loosened.

**Q28 and Q30, previously FAILING, re-keyed (not flipped):**

- Q28 "customer changed their mind about the sink": the old key claimed
  "2 confirmed changes". Reading the chunks: 4075 is an install instruction
  ("Change the sink — start with the sink, she has the plumber scheduled"),
  6189 is install-without-the-sink ("doesn't have vessel sink, asked us to
  install anyway"), 1802 is a pending confirmation. The system's hedge —
  no note explicitly documents a change of mind, these are the closest —
  was the more defensible reading. Key now says so. ✗ → ✓.
- Q30 "quartzite jobs stalled after quote": the old key ("1 stalled job")
  predates the pipeline view. Under the locked v4 definition 9 quartzite
  jobs are `quiet` (8 Canceled, 1 Done); the salesperson comment exists
  only for job 1891 ("too expensive — will discuss with her husband").
  The system answered exactly that. Key re-keyed from the view, SQL in
  `source_of_truth`. ✗ → ✓.

## Change 2 — Q16 and `v_quoted_jobs` (commits `3015a48`, `751154c`)

Alex's definition reproduces exactly: the four statuses (Confirmed,
Complete, Paid in Full and Finished, In Progress), any date, give

| | jobs |
|---|---|
| via a Quote activity | 2,680 |
| via a Measure or Template | 3,334 |
| **union** | **4,236** |
| only via the measure/template proxy | 1,556 (37%) |

One wording correction: the WO says "only Estimate with a blank date is
excluded". The 4,236 excludes **every** Estimate row — a dated Estimate
does not count either (counting dated Estimates gives 4,423). The view
implements the number, and the schema prompt says "Estimate rows never
count".

Wiring: `sql/016` creates `v_quoted_jobs` (one row per quoted job:
job_id, job_name, customer, salesperson, city, has_quote_activity,
has_measure_or_template, quoted_via, first_signal_date), granted to
`rag_reader`, added to the SQL-lane whitelist and `setup_ro_role.VIEWS`.
The schema prompt gets two sentences under the view and the v_activities
"happened" rule no longer uses quotes as its example — it now points to
`v_quoted_jobs` for "how many quotes have we issued / jobs quoted". Lane
check: "How many quotes have we issued in total?" → `SELECT COUNT(*) FROM
v_quoted_jobs` → 4,236; "how many jobs did we quote in 2024" → 548 via
`first_signal_date`. Q16 ✗ → ✓.

### ⚠ 4,236 vs 4,415 — needs Alex's decision (not fixed here)

Two views now answer "how many jobs have we quoted" differently:

| definition | rule | quoted jobs |
|---|---|---|
| `v_quoted_jobs` (this WO) | Quote/Measure/Template with status in the four, **dated or not**; Estimate never | **4,236** |
| `v_job_pipeline_status.is_quoted` (sql/012–013) | Quote/Measure/Template **dated on or before 2026-07-30**, **any status** (Estimate included) | **4,415** |
| `v_quote_conversion_monthly` cohort | is_quoted AND (settled ≥30 days OR moved) | 4,377 (the WO's "4,377" is this cohort, not the view's count) |

Exact overlap, measured: 4,231 jobs satisfy both rules.

- **184 jobs are quoted only in the pipeline view.** Every one has a dated
  **Estimate** as its only Quote/Measure/Template signal. The status rule
  says an Estimate is not a quote; the date rule says a dated one is.
- **5 jobs are quoted only in `v_quoted_jobs`:** 2 undated Confirmed
  quotes (jobs 4411, 4907) and 3 Templates dated 2026-08-03, after the
  pipeline's as-of date (5814, 5849, 5859).

So the WO's stated concern (undated Confirmed activities) explains 2 of the
179-job gap. **The real rule difference is dated Estimates**: 184 jobs. The
decision is whether a dated Estimate counts as a quote. If yes, the
conversion denominator stays 4,377 and `v_quoted_jobs` should add dated
Estimates (→ ~4,420); if no, the pipeline view should drop them and the
conversion rates (Q59–62) move. Either way it is one rule in one place;
until it is decided the prompt tells the model which view answers which
question and says the two numbers differ.

## Change 3 — conversion re-keys (commit `60203d1`)

Read from the live view 2026-09-14; the view had not moved since WO9.

| q | old key (v3) | new key (v4, live) | run |
|---|---|---|---|
| Q59 overall | 65.9% (2523/3830) | 70.0% (3063/4377) | ✗ → ✓ |
| Q60 2023 | 85.2% (386/453) | 85.7% (409/477) | ✗ → ✓ |
| Q61 2024 | 61.1% (359/588) | 63.4% (401/632) | ✗ → ✓ |
| Q62 best year | 2023, 85.2% | 2023, 85.7% (409/477) | ✓ → ✓ |

All four `verified`; each row's notes say the key tracks
`v_quote_conversion_monthly` v4 and must be re-keyed when that definition
changes (which the 4,236-vs-4,415 decision may do).

## Change 4 — Q26 (commits `996ffc9`, `70d1f38`, `a90ec6b`, `0bc1265`)

**Root cause.** Q26's SQL selected `salesperson, city` straight from
`v_job_pipeline_status`. Commit `f043df9` had added a prompt caveat ("JOIN
v_jobs for customer/salesperson/city"); the model ignored it. It got past
the validator because `validate_sql`'s column whitelist is the union of
all views' columns, so `salesperson` is a legal column name anywhere; the
error only surfaced in Postgres, and execution errors get no repair
attempt, so the lane fell back to semantic with zero evidence. The judge
then rewarded the honest decline. `f043df9` was not regressed — it was
never sufficient.

**Fix.** `sql/017` recreates the view with `customer, salesperson, city`
on the row (from `jobs`, same values as `v_jobs`; the conversion view is
recreated unchanged — 4,415 / 4,377 / 1,306 verified identical after the
migration). `v_wasted_templates` already carried salesperson and city, so
this is consistency, not a special case. Whitelist and prompt updated.
Lane check: "Which jobs went quiet after a quote?" → 1,306 rows with
salesperson and city, no error.

**Harness rule** (`70d1f38`): if `sql_error` is set the row is scored
incorrect with the error as the judge reason and no judge call. Zero SQL
errors in the WO11 run.

**Q26's key.** The old key had no number ("needs a SQL definition"). It is
re-keyed to the live count, 1,306. My first key also asked for the
Canceled split (1,093, 84%); the question asks "which jobs", the answerer
did not volunteer the split, and numeric match requires every number in
the key — so Q26 shows ✗ in the full run and in the subset. The final key
(`0bc1265`) carries only 1,306; both runs' stored answers match it. That
is the 74 → 75 above. The answer itself has a real flaw the judge also
caught: it called the first three rows "the quietest jobs (longest silent
periods)" when the SQL ordered by last_signal_date DESC (they are the
*shortest*), and generalised about salesperson distribution from a 200-row
sample. That is an answerer problem, out of scope here, recorded.

## Change 5 — Q42's "fabricated address" (commit `bc8f15a`)

The six chunks Q42 received (6920, 6910, 3549, 594, 4932, 4535) contain no
street address. The answer's "AV - 4 48th Ave", "MHA Design - 3063
Marshgate", "Vintage Homes - 203 Horned Grebe" are **Moraware job names**
— `v_jobs.job_name` for jobs 3529, 3071, 4083. The answerer receives the
job name in every chunk header (`[chunk N, job J "name"]`,
`retrieval.answer._format_chunks`); the judge's evidence omitted it
(`[chunk N, job J]`) and also cut each note at 400 characters. Chunk 6920's
context sentence even contains "AV - 4 48th Ave" verbatim. So: not model
invention, not the WO3 context sentences — a harness evidence asymmetry.

Fix: the judge now formats chunks with the same `_format_chunks`, so it
sees byte-identical evidence. Q42 is now ✓; it is still flagged
unfaithful for a different, legitimate reason (the answer put job 3221's
"Master Bench" in "Bathroom 3" — the note says "Bathroom 3 and Master
Bench", two items). No README limitation note: the hallucination was not
one.

Effect on faithfulness overall: 91.1% → 89.9% (7 → 8 unfaithful of 79
judged). Before: Q14, 15, 42, 45, 49, 51, 56. After: Q15, 26, 40, 42, 49,
50, 56, 58. Q14, 45, 51 cleared (the judge can now see the full note);
Q26, 40, 50, 58 appeared — Q26 and Q58 for over-reach described above,
Q40/Q50 are misrouted/draft rows. With the judge seeing more evidence,
the faithfulness score is now a stricter, more honest number than before.

## Questions that got worse

| q | status | before → after | why |
|---|---|---|---|
| Q26 | verified | ✓ → ✗ | false pass before (errored SQL); my first key over-asked; final key passes on the same answer |
| Q58 | draft | ✓ → ✗ | "customer-supplied sink modified on site": found job 4008 (the key), then added 996/2394/2681 which are not customer-supplied sinks; judge marked over-reach. Same failure class as Q45/47/49 — an existence question the WO did not list; left as is |

Still failing (8, or 7 under the final Q26 key): Q11 (draft, material
counting), Q26 (see above), Q41 and Q56 (misrouted, known), Q45 / Q47 /
Q49 (scoped over-generalisation), Q58 (draft over-reach).

## Structured subset, judge-free (`2026-09-14-0923-structured-wo11.json`)

53 questions, 4 workers, $0.46: **50/53** (WO10: 45/53). Failing: Q11,
Q26 (first key), Q63 — Q16, Q59–62 all ✓ by numeric match. Router 53/53.

## Surprises

1. **The re-keys measured the system, and three came back red on purpose.**
   Q45/Q47/Q49 now fail with the judge naming the exact boundary crossed.
   That is the WO working: the answerer over-generalises open-ended
   questions, and Q58 shows the pattern extends beyond the listed 11.
2. **Q38's re-key never existed**, and the format it prescribed crashed the
   loader. The work order's model of the repo was one step ahead of it.
3. **The 4,236 vs 4,415 gap is not about undated rows.** 2 of 179 are.
   184 are dated Estimates — a status question, not a date question.
4. **"Only Estimate with a blank date is excluded" is not what 4,236 is.**
   4,236 excludes every Estimate. Worth Alex re-reading his own rule.
5. **Q26 was double-broken**: an errored query scored correct, and its
   fix then failed on my over-specified key. Numeric match requiring every
   number in the key is a sharp tool; keys must contain only the numbers
   the question asks for.
6. **Q42's "hallucination" was the judge's blind spot, not the model's.**
   One harness asymmetry (job name in the answerer's header, not the
   judge's) produced the only "fabrication" verdict in 82 questions.
7. **Faithfulness fell slightly (91.1 → 89.9) because the judge sees more,**
   not because answers got worse; three previously-unfaithful rows
   cleared once the judge had the full note.

## Cost

Full run $1.11 + structured subset $0.46 + lane checks < $0.02 →
**≈ $1.59** (budget $3).

## Open for Alex

1. **Dated Estimate = quote or not** (the 184 jobs). Decides
   `v_quoted_jobs` vs `is_quoted` and therefore Q59–62's denominator.
2. Answerer scope discipline for existence questions (Q45/47/49/58):
   the next answerer change is a rule to classify each candidate against
   the question's literal category and drop the near-misses, or say they
   are near-misses.
3. Q26's answerer mis-described the sort order of a sample; a rule "never
   characterise a LIMITed sample as extreme values unless the ORDER BY says
   so" would fix it. Both are answerer-prompt work for Phase 6 or later.

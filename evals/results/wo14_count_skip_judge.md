# WO14 — Skip the redundant COUNT(*), make the judge deterministic

Date: 2026-09-16 · commits `d11ff85` (Change A), `126da85` (re-judge tooling +
`JUDGE_VOTES` flag) · baseline WO13 final `2026-09-16-0848-wo13-final.json`
@ `a03a724`, session `eval-20260916-0844-a03a724` · final
`2026-09-16-1005-wo14-final.json` @ `126da85`, session
`eval-20260916-1000-126da85`.

**Outcome in one line:** Change A landed and halved the slow tail again with
every total identical; Change B measured the judge nine times, found that
neither `temperature=0` (API rejects it) nor majority-of-3 (still flips one
coin-flip row) meets the identical-failing-sets rule, and therefore changed
nothing. Cost ≈ $5.75 (tripwire $7).

## Headline

| | before (WO13 final) | after (WO14 final) |
|---|---|---|
| `sql_execute` p95 / max / total (59 calls) | 0.401 s / 0.601 s / 4.7 s | **0.198 s / 0.519 s / 3.3 s** |
| slowest one-row answer (Q74) | 0.60 s | **0.32 s** |
| reported totals identical to baseline | — | **59/59** |
| judge config | Sonnet 5, adaptive thinking, no temperature, max_tokens 4000, 1 call | **unchanged** (flag `JUDGE_VOTES` exists, default 1) |
| score spread, 3 single-judge re-judge passes of one saved run | 74 / 76 / 76 | n/a — no candidate passed |
| score spread, 3 majority-of-3 passes | — | 75 / 75 / 74 (Q30 flipped) |
| cost per full run | $1.06 | $1.04 |

## Change A — skip `COUNT(*)` when the result is under the LIMIT (commit `d11ff85`)

### Diagnostic

`execute_sql` ran the model's query, then — whenever the query carried a
LIMIT (it always does: `validate_sql` forces `LIMIT 200`) and returned at
least one row — stripped the LIMIT with sqlglot and ran
`SELECT COUNT(*) FROM (<query>) _t` to report the true total. Every SQL
question paid for two executions.

From the baseline JSON, 59 questions ran SQL:

| | questions | examples |
|---|---|---|
| under their LIMIT (count query redundant) | **47** | Q74 (1 row), Q82 (16), Q29 (1 — since WO10 it is a `COUNT(DISTINCT)`, not the 246-row list the WO remembered) |
| at the forced `LIMIT 200` (count needed) | 3 | Q26 1,306 · Q41 480 · Q56 254 |
| at a model-written `LIMIT 1` (count reports the group total) | 9 | Q76 10 salespeople · Q11 3,671 materials · Q17 68 · Q2 11 … |

### Implementation

```python
lim = int(limited.expression.this)        # the LIMIT actually in the SQL
count_skipped = len(rows) < lim
if not count_skipped:                     # at the cap: exactly as before
    cur.execute(f"SELECT COUNT(*) FROM ({tree.sql(dialect='postgres')}) AS _t")
    total_count = cur.fetchone()[0]
```

The `sql_execute` span carries `count_skipped: true/false` in its metadata.
An unparseable LIMIT falls back to `len(rows)` with `count_skipped: null`,
which is what the old exception path did too.

### Verification

- Structured subset, judge-free (`2026-09-16-0943-structured-wo14a.json`,
  53 rows): **53/53 totals identical** to baseline, 51/53 correct.
- Full run (`2026-09-16-1005-wo14-final.json`): **59/59 totals identical**,
  including the three cap cases — Q26 = 1,306, Q41 = 480, Q56 = 254 — and
  the LIMIT-1 case Q76 = 10 (count path still taken). Q74 = 252, Q75 = 48,
  Q82 = the same 16 job ids. Q29 = 1 (its current single-row form).

### Latency (Langfuse, `sql_execute`)

| | WO12 (no index) | WO13 (index) | **WO14 (index + skip)** |
|---|---|---|---|
| calls | 59 | 59 | 59 |
| median | 0.030 s | 0.031 s | 0.026 s |
| **p95** | 1.957 s | 0.401 s | **0.198 s** |
| max | 2.397 s | 0.601 s | 0.519 s |
| total | 12.4 s | 4.7 s | **3.3 s** |

Per query:

| q | rows | LIMIT | count run? | WO13 | **WO14** | note |
|---|---|---|---|---|---|---|
| Q74 wasted templates total | 1 | 200 | skipped | 0.60 s | **0.32 s** | one view execution instead of two |
| Q75 wasted templates 2025 | 1 | 200 | skipped | 0.59 s | **0.30 s** | same |
| Q40 could not template, cabinets | 17 | 200 | skipped | 0.40 s | **0.20 s** | same |
| Q82 template wasted, cabinets | 16 | 200 | skipped | 0.40 s | **0.20 s** | same |
| Q76 salesperson with most wasted | 10 | **1** | **run** | 0.59 s | 0.52 s | the model wrote `LIMIT 1`; the count is what reports "10 salespeople" — by design unchanged |
| Q26 quiet jobs | 1,306 | 200 | run | 0.08 s | 0.08 s | cap case, count kept |

The remaining tail is exactly what the rule protects: Q76's `LIMIT 1` means
`len(rows) == lim`, so its count runs and the view executes twice. Taking
that too would need a different rule (the model's own LIMIT vs the forced
one), and the WO said not to touch that case. Everything else on
`v_wasted_templates` is now one execution, ~0.3 s.

## Change B — judge determinism: measured, no candidate passed, nothing changed

### B.1 Diagnostics

**Re-judge tooling.** Nothing existed for judging from a saved run
(`judge_probe.py` probes prompt variants live). `evals/rejudge.py`
(commit `126da85`) feeds a run JSON's stored answer / SQL rows / chunk ids
to the **unchanged** `judge_answer()` and writes a JSON per pass with only
the verdicts replaced; chunk texts come from the database, everything else
from the file. One pass = 79 judge calls ≈ $0.46, ~85 s at 4 workers.

**Judge config, verbatim from `harness.py` (before and after):**
`claude-sonnet-5` (always the *other* model from the Haiku generator);
`max_tokens=4000`; `system=JUDGE_SYSTEM`; `output_config` JSON schema; no
`thinking` parameter → Sonnet 5's default **adaptive thinking**; no
`temperature`; one retry on an unparseable verdict.

**The API finding, stated plainly.** Tested with one call each on
`claude-sonnet-5`:

| request | result |
|---|---|
| `temperature=0`, thinking default (adaptive) — **B1** | **400** `temperature is deprecated for this model` |
| `temperature=0`, `thinking={"type":"disabled"}` — **B1′** | **400** `temperature is deprecated for this model` |
| `thinking={"type":"disabled"}`, no temperature | accepted |
| `top_p=0.1` | **400** `top_p is deprecated for this model` |
| `output_config={"effort":"low"}` | accepted |

Sonnet 5 accepts no sampling parameters at all, with or without thinking.
**B1 and B1′ are not viable.** (The router, SQL lane and answerer are
Haiku 4.5, which still accepts `temperature=0` — that is why WO8/10/13
worked.) The only candidate left that keeps the judge's model, prompt,
evidence and thinking unchanged is **B2, majority-of-3**.

### B.2 Baseline spread — 9 single-judge re-judges of the WO13 final run

Nine independent passes were run (3 for the baseline; the other 6 so that
three majority-of-3 passes could be formed from groups of three fresh,
independent verdicts without paying for them twice — statistically the same
as three online `JUDGE_VOTES=3` passes).

| pass | correct | failing set | faithfulness | $ |
|---|---|---|---|---|
| 1 | 74/82 | 11, **30**, 41, 45, 47, **49**, 56, **58** | 0.949 | 0.44 |
| 2 | 76/82 | 11, 41, 45, 47, **49**, 56 | 0.911 | 0.46 |
| 3 | 76/82 | 11, 41, 45, 47, 56, **58** | 0.949 | 0.46 |
| 4 | 76/82 | 11, 41, 45, 47, 56, **58** | 0.924 | 0.49 |
| 5 | 74/82 | 11, **30**, 41, 45, 47, **49**, 56, **58** | 0.924 | 0.48 |
| 6 | 74/82 | 11, 41, 45, 47, **48**, **49**, 56, **58** | 0.924 | 0.45 |
| 7 | 74/82 | 11, **30**, 41, 45, 47, **49**, 56, **58** | 0.924 | 0.47 |
| 8 | 76/82 | 11, 41, 45, 47, **49**, 56 | 0.911 | 0.48 |
| 9 | 74/82 | 11, **30**, 41, 45, 47, **49**, 56, **58** | 0.937 | 0.46 |

Baseline (passes 1–3): failing sets **not** identical; `correct` differed on
Q30, Q49, Q58 (as predicted) and `faithful` differed on Q11, Q46, Q49, Q51,
Q56. Over all nine passes the `correct` verdict moved on four questions:

| q | ✓ votes / 9 | what the judge argues about |
|---|---|---|
| **Q30** | **5 / 4** | the answer cites a job-180 note as a "salesperson comment"; half the judges call that an extra, half call it wrong |
| Q48 | 8 / 1 | one judge demands job 3516 although the key says "e.g." and 3516 was not retrieved |
| Q49 | 2 / 7 | scope: "warranty or defect on previously-installed work" — two judges accept the extra repairs as defects |
| Q58 | 2 / 7 | over-generalising "customer-supplied" to jobs 996/2394/2681 |

Q45 and Q47 were ✗ in all nine.

### B.3–B.4 Candidate B2 (majority-of-3) and the decision rule

| B2 pass | from singles | correct | failing set |
|---|---|---|---|
| 1 | 1–3 | 75/82 | 11, 41, 45, 47, 49, 56, 58 |
| 2 | 4–6 | 75/82 | 11, 41, 45, 47, 49, 56, 58 |
| 3 | 7–9 | **74/82** | 11, **30**, 41, 45, 47, 49, 56, 58 |

Failing sets **not identical** — Q30 flipped in pass 3. Majority-of-3
removed Q48, Q49 and Q58 (their 8/1 and 2/7 splits resolve reliably) but
not Q30: a 5/4 row is a coin, and three coin tosses still land 2-of-3
tails about 44% of the time. Faithfulness verdicts differed across the
three B2 passes as well (0.949 / 0.937 / 0.924).

**Decision rule applied: no candidate passes → change nothing.** `JUDGE_VOTES`
stays at its default of 1; the judge's model, prompt, evidence, thinking
budget and cost are exactly what they were. The sanity checks were met by
every pass regardless (Q45/Q47/Q49 ✗ in all three B2 passes; the Q30/Q48/Q58
reasons are quoted above), but the rule is identical sets, and it was not.

**Verdict-flip table, baseline vs candidate:**

| q | status | route | single p1 / p2 / p3 | B2 p1 / p2 / p3 | votes over 9 singles |
|---|---|---|---|---|---|
| Q30 | verified | hybrid | ✗ ✓ ✓ | ✓ ✓ **✗** | 5 ✓ 4 ✗ |
| Q48 | verified | semantic | ✓ ✓ ✓ | ✓ ✓ ✓ | 8 ✓ 1 ✗ |
| Q49 | verified | semantic | ✗ ✗ ✓ | ✗ ✗ ✗ | 2 ✓ 7 ✗ |
| Q58 | draft | semantic | ✗ ✓ ✗ | ✗ ✗ ✗ | 2 ✓ 7 ✗ |
| Q45 | verified | semantic | ✗ ✗ ✗ | ✗ ✗ ✗ | 0 ✓ 9 ✗ |
| Q47 | verified | semantic | ✗ ✗ ✗ | ✗ ✗ ✗ | 0 ✓ 9 ✗ |

**What would work, for Alex.** The noise is not in the grader's sampling
mechanics; it is that two answers sit exactly on the line the key draws.
Three options, none taken here:
(a) `JUDGE_VOTES=5` — would cut Q30's flip rate to ~25% per pass, not to
zero, at ≈ +$1.9/run; (b) fix the *answer*: Q30 should not call a job-180
note about dimensions a "salesperson comment" (an answerer-prompt rule,
out of scope); (c) fix the *key*: Q30's key could say the job-180 note is
not a salesperson comment, and Q48's key already says "e.g." — a golden
edit, Alex's call. (b) or (c) removes the coin; more votes only weights it.

### B.6 Final confirmation run (unchanged judge)

`2026-09-16-1005-wo14-final.json` @ `126da85`, session
`eval-20260916-1000-126da85`: routing **96.3%**, generation **75/82
(91.5%)**, faithfulness 94.9%, ctx precision 61.1%, reranked R@10 **0.818**
(unchanged), **$1.04**, **262 s**. Failing: 11, 30, 41, 45, 47, 49, 56. The
one change against the WO13 final (74/82) is Q48 ✓ on a byte-identical
answer — the 8/1 row landing on its 8 side. Consistent with the measured
floor.

Langfuse stage table (4 workers, shares of summed call time):

| stage | calls | total s | median | p95 | share | $ |
|---|---|---|---|---|---|---|
| judge | 79 | 303.9 | 2.45 | 11.56 | 47.3% | 0.4356 |
| router | 82 | 124.3 | 1.49 | 2.19 | 19.4% | 0.0784 |
| answer | 79 | 123.7 | 1.21 | 3.09 | 19.3% | 0.1385 |
| sql_generate | 59 | 79.9 | 1.22 | 2.59 | 12.4% | 0.3836 |
| rerank | 26 | 4.9 | 0.17 | 0.33 | 0.8% | — |
| **sql_execute** | 59 | **3.3** | 0.03 | **0.20** | 0.5% | — |
| dense / bm25 / fuse / validate | | 2.2 | | | 0.3% | — |
| **all** | | 642.1 | | | 100% | 1.0360 |

## Got worse

Nothing in the system. The eval now costs the same ($1.04 vs $1.06) because
B2 was not adopted. Two things are worth saying plainly:

- The WO's Q29 premise was stale — it has been a one-row `COUNT(DISTINCT)`
  since WO10, so "must still report 246" does not apply; the cap cases that
  exercised the kept count path were Q26/Q41/Q56 (and the LIMIT-1 group).
- Q76 stays at ~0.5 s by design (model-written `LIMIT 1`, count kept). If
  that matters, the rule "skip the count when the model's own LIMIT, not the
  forced one, was hit" is a follow-up, not this WO.

## Surprises

1. **Sonnet 5 has no sampling knobs at all.** `temperature` and `top_p` are
   both rejected, thinking on or off. Determinism on Sonnet 5 can only come
   from voting or from removing the ambiguity being judged.
2. **The judge is not noisy in general — it is a coin on one row.** Over
   nine passes, 78 of 82 verdicts never moved; Q48/Q49/Q58 are 8/1 or 2/7
   and voting fixes them; Q30 is 5/4 and nothing short of fixing the answer
   or the key will.
3. **The re-judge baseline reproduced the full-run history exactly**: the
   WO13 determinism runs (75/75/76) and final (74) are the same distribution
   the nine re-judges show — the pipeline was never the variance.
4. **Faithfulness is noisier than correctness** — its verdict moved on five
   questions across three passes (0.911–0.949), and majority-of-3 did not
   stabilise it either.
5. **The count skip also fixed a subtle double-read on Q26**: the 1,306-row
   list still runs the count (cap hit), but the 47 skipped queries include
   every `v_job_pipeline_status` and `v_quoted_jobs` aggregate, which now
   execute once.

## Cost

Change A subset $0.46 + nine re-judge passes $4.19 + API probe < $0.01 +
final full run $1.04 → **≈ $5.70** (tripwire $7; the nine passes are what
the 3 + 3×3 design required, with the baseline trio reused as B2 pass 1).

# Demo script — 2 to 3 minutes, screen recording

A shot list for Alex to record, not a recording. Every question below was
run against the live data on the date in the verification table and its
answer shows counts, percentages and area names only: no customer name, no
dollar figure. Do not improvise questions on camera; anything that returns
job rows shows customer names in the evidence panel.

## Before recording

1. **Login.** Use the `office` login. As of 2026-09-21 it has no history at
   all (the only rows in `serve.asks` belong to `alex`, 20 of them), so its
   sidebar is empty and demo-safe. If that has changed by recording day,
   clear it first, as the serve role on the box:

   ```
   DELETE FROM serve.asks WHERE user_name = 'office';
   ```

   (Postgres, `emg_rag_db` container; this table is the UI's history, not
   source data.)
2. Restart the service so the WO20 build is live: `systemctl restart emg-rag-api`.
3. Browser at 1280 px wide or more, dark page loads with the sidebar empty.
4. Have the Langfuse project open in a second tab, filtered to tag `ui`.

## Shot list

| # | time | on screen | what to say (one line) |
|---|---|---|---|
| 1 | 0:00 | the idle page | "Natural-language questions over a countertop company's job tracking and invoicing. Live for the office, behind auth." |
| 2 | 0:15 | type **How many jobs do we have in Mount Pleasant?** and press Enter | "Every question is routed: this one goes to the SQL lane." Point at the `structured` tag, the latency and cost. |
| 3 | 0:35 | the evidence panel, open by default | "The SQL it wrote, validated per view, run on a read-only role, and the rows. You can see why." |
| 4 | 0:55 | type **And in 2025?** | "Follow-ups are rewritten into a self-contained question before routing." Point at *Interpreted as*. |
| 5 | 1:15 | type **What is our overall quote-to-moved-forward conversion rate?** | "Contested business terms are defined once, as a view; the model reads the definition, it does not invent one." |
| 6 | 1:35 | type **What is the capital of France?** | "Off-topic questions are refused, not answered." Point at the `refuse` tag. |
| 7 | 1:50 | cut to Langfuse, open the trace of the Mount Pleasant question | "Every stage is traced: router, SQL generation, validation, execution, answer, with latency and cost per stage." Hover the `sql_execute` span. |
| 8 | 2:20 | back to the page, sidebar | "History per user, feedback per answer, and an eval harness with a different-model judge behind all of it." |
| 9 | 2:35 | end on the idle page | "Code and results are in the repo." |

## Questions verified against live data

Run with `scripts/query.py` on the server on the date shown; "shows" is what
the answer and its evidence contain. Any question not in this table is
**not cleared** for camera.

| question | route | evidence columns | shows | verified |
|---|---|---|---|---|
| How many jobs do we have in Mount Pleasant? | structured | `jobs` | one count (516) | 2026-09-21 |
| And in 2025? (after the question above) | structured, follow-up: *Interpreted as* "How many jobs do we have in Mount Pleasant in 2025?" | `jobs` | one count (76) | 2026-09-21 |
| What is our overall quote-to-moved-forward conversion rate? | structured | `conversion_pct, moved_forward, quoted_jobs` | 70.0%, 3,063 of 4,377 | 2026-09-21 |
| How many wasted templates have we had in total? | structured | `wasted_templates` | one count (252) | 2026-09-21 |
| Which areas have the most jobs? | structured | `city, job_count, total_jobs` (68 rows) | area names and counts; the answer lists the top five | 2026-09-21 |
| What is the capital of France? | refuse | none | the refusal sentence | 2026-09-21 |

Questions deliberately **not** used: anything semantic ("Were there jobs
where we could not get material into the building?", "What did the
salesperson say…"). Every note card carries the job name in its header, and
job names are customer names; there is no semantic question whose evidence
is free of them, so no semantic answer appears on screen. Also not used:
"How much did we invoice in 2024?" (a dollar figure), any "which jobs"
question (job rows), any question naming a person.

## Verification

Run on the server on 2026-09-21 at commit `a070597` through
`retrieval.pipeline.ask` (and `ask_conversational` for the follow-up, with
the first answer as history), the same path the UI uses; six questions,
$0.04 in total. For each: route, evidence columns, first rows and answer
text were inspected. No evidence column is a job or customer name, no row
holds a name, no answer contains a dollar sign, and the only retrieved
chunks are zero (every cleared question is structured or refused). The
Langfuse traces are tagged `demo-check`.

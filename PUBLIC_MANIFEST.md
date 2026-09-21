# Public mirror manifest

Built by scripts/public_transform.py from the private repo's tracked files at HEAD.
Allowlist: deploy/public_allowlist.txt. Employee names are pseudonyms; customer names,
contact data and EMG dollar figures are redacted. Files still holding verbatim note text
after the transform are excluded.

Kept: 151 files. Not allowlisted: 62. Excluded for note text: 0.

## Excluded after transform (note text)


## Transformed files (replacements by category)

- `CLAUDE.md`: server_ip=2
- `HANDOFF.md`: employee=4
- `deploy/CADDY_STEPS.md`: employee=1, server_ip=1
- `docs/session-2026-09-08-to-10-WO8-WO10.md`: customer_token=1, employee=39, note_window=12
- `docs/wo17-conversational-followups-report.md`: employee=4
- `docs/wo19_public_audit.md`: dollar_nosign=1
- `evals/fixtures/load_fixture.py`: customer_token=1
- `evals/fixtures/rewrite_cases.json`: dollar=3, employee=53
- `evals/golden_conversations.csv`: dollar=4, employee=29, note_window=3
- `evals/golden_set.csv`: customer_name=7, customer_token=5, dollar=11, employee=67, note_window=25
- `evals/make_fixture.py`: employee=1
- `evals/make_rewrite_fixtures.py`: employee=1
- `evals/metrics.py`: employee=1
- `evals/results/before_after.md`: customer_token=2
- `evals/results/wo10_determinism_latency.md`: customer_token=8, employee=10, note_window=189
- `evals/results/wo11_rekey.md`: customer_name=3, customer_token=2, employee=2
- `evals/results/wo15_quoted_jobs_diagnostic.md`: customer_name=5, customer_token=3, employee=4
- `evals/results/wo15_quoted_jobs_diagnostic_full.md`: customer_name=195, customer_token=6, employee=187, note_window=28
- `evals/results/wo16_serving.md`: employee=2
- `evals/results/wo17_followups.md`: employee=41
- `evals/results/wo18_restyle.md`: dollar=1, dollar_nosign=2, employee=1
- `evals/results/wo9_status_widening.md`: address=1, customer_name=2, customer_token=4, employee=44, note_window=3
- `evals/results/wo_activity_reality.md`: employee=8
- `evals/results/wo_wasted_templates.md`: address=1, customer_name=1, customer_token=21, employee=40, note_window=254
- `evals/run_eval.py`: employee=1
- `ingest/link_invoices.py`: dollar=1, dollar_nosign=2
- `ingest/load_assignees.py`: employee=3
- `ingest/load_qb.py`: dollar=2
- `retrieval/rewrite.py`: employee=2
- `retrieval/sql_lane.py`: employee=34
- `serve/static/index.html`: employee=1
- `tests/test_rewrite.py`: employee=4

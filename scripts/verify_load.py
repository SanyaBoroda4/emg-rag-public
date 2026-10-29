"""The load gate: expected vs actual for every corpus count.

Hard checks (any mismatch -> exit 1): jobs, activities, job_forms, area_fields
(the field total), invoices. Soft checks are printed for the report but do not
fail the gate. Run after the full pipeline, and again after re-running
load_moraware.py to prove idempotency (counts must be identical).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.db import get_conn

HARD = [
    ("jobs", "SELECT count(*) FROM jobs", 5569),
    ("activities", "SELECT count(*) FROM activities", 44495),
    ("job_forms", "SELECT count(*) FROM job_forms", 12201),
    ("area_fields (all form fields)", "SELECT count(*) FROM area_fields", 149364),
    ("invoices", "SELECT count(*) FROM invoices", 5257),
]

SOFT = [
    ("job_contacts", "SELECT count(*) FROM job_contacts", None),
    ("job_summary", "SELECT count(*) FROM job_summary", None),
    ("activity_assignees", "SELECT count(*) FROM activity_assignees", None),
    ("invoice_lines", "SELECT count(*) FROM invoice_lines", None),
    ("job_areas", "SELECT count(*) FROM job_areas", None),
    ("job_invoices", "SELECT count(*) FROM job_invoices", None),
    ("activities with NULL date",
     "SELECT count(*) FROM activities WHERE activity_date IS NULL", None),
]


def main() -> int:
    failed = False
    with get_conn() as conn, conn.cursor() as cur:
        print(f"{'check':<42} {'expected':>10} {'actual':>10}  status")
        print("-" * 74)
        for name, sql, expected in HARD:
            cur.execute(sql)
            actual = cur.fetchone()[0]
            ok = actual == expected
            failed |= not ok
            print(f"{name:<42} {expected:>10} {actual:>10}  "
                  f"{'OK' if ok else '** MISMATCH **'}")
        for name, sql, _ in SOFT:
            cur.execute(sql)
            print(f"{name:<42} {'-':>10} {cur.fetchone()[0]:>10}  info")

        print()
        cur.execute("""
            SELECT count(*) FROM jobs j
            WHERE NOT EXISTS (SELECT 1 FROM activities a WHERE a.job_id = j.job_id)
        """)
        zero_act = cur.fetchone()[0]
        cur.execute("""
            SELECT j.job_id, j.job_name FROM jobs j
            WHERE NOT EXISTS (SELECT 1 FROM activities a WHERE a.job_id = j.job_id)
            ORDER BY j.job_id LIMIT 5
        """)
        samples = cur.fetchall()
        print(f"jobs with zero activities: {zero_act}")
        for jid, jname in samples:
            print(f"  {jid}  {jname}")

        cur.execute("""
            SELECT count(*) FROM activities a
            LEFT JOIN jobs j ON j.job_id = a.job_id WHERE j.job_id IS NULL
        """)
        orphans = cur.fetchone()[0]
        ok = orphans == 0
        failed |= not ok
        print(f"activities with no jobs row: {orphans} "
              f"{'(OK, must be 0)' if ok else '** MUST BE 0 **'}")

        cur.execute("SELECT count(DISTINCT assignee_name) FROM activity_assignees")
        print(f"distinct assignee names loaded: {cur.fetchone()[0]}")

        cur.execute("SELECT count(*) FROM job_areas")
        areas = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM job_forms "
                    "WHERE form_template_name = 'Details'")
        details = cur.fetchone()[0]
        print(f"job_areas rows vs Details forms: {areas} vs {details} "
              f"{'(match)' if areas == details else '** DIFFER **'}")

        cur.execute("SELECT min(activity_date), max(activity_date) FROM activities")
        lo, hi = cur.fetchone()
        print(f"activity_date range: {lo} .. {hi}")
        cur.execute("SELECT min(txn_date), max(txn_date) FROM invoices")
        lo, hi = cur.fetchone()
        print(f"invoice txn_date range: {lo} .. {hi}")

    print()
    print("FAIL" if failed else "OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

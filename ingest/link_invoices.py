"""Populate job_invoices from Invoice-activity notes.

Reimplements the bridge's tolerant invoice-number extraction in Python (no
call to the bridge). Rules, applied to every digit-run in a note:

  * rejected as an amount: '$'-adjacent, has a decimal fraction (4556.50 or
    .50), or comma-grouped (1,234)
  * rejected as a date component: digit-run touching '/' or '-' next to
    another digit (3/15/2021, 2021-03-15, 4556-4557)
  * bare years 2018-2031 are rejected unless '#'-tagged (#2020 is an invoice
    number, "in 2020" is a year)
  * floor 1002 (first QB DocNumber), ceiling 19999
  * a trailing period ("4556.") does not disqualify

Numbers may be '#'-tagged, word-tagged ("invoice 4955"), or bare — all are
accepted subject to the rules above. source_activity_id records where each
number came from. Upsert on (job_id, doc_number): running twice is identical.

job_invoices has no FK to invoices on purpose: extracted numbers that don't
exist in QuickBooks (typos) stay visible, and are listed by the reconciliation
report this script prints.
"""

import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.db import get_conn

FLOOR, CEILING = 1002, 19999
YEAR_MIN, YEAR_MAX = 2018, 2031

DIGIT_RUN = re.compile(r"\d+")


def extract_invoice_numbers(note: str) -> list[int]:
    """All invoice-number candidates in a note, per the tolerant rules."""
    out = []
    for m in DIGIT_RUN.finditer(note):
        s, e = m.start(), m.end()
        before = note[s - 1] if s > 0 else ""
        before2 = note[s - 2] if s > 1 else ""
        after = note[e] if e < len(note) else ""
        after2 = note[e + 1] if e + 1 < len(note) else ""

        # decimal fraction: "4556.50" (either side of the dot) -> amount
        if before == "." and before2.isdigit():
            continue
        if after == "." and after2.isdigit():
            continue
        # comma-grouped: "1,234" -> amount
        if (before == "," and before2.isdigit()) or \
           (after == "," and after2.isdigit()):
            continue
        # $-adjacent (allow "$ 450")
        prefix = note[:s].rstrip()
        if prefix.endswith("$"):
            continue
        # date component: digit-run glued to / or - with a digit beyond
        if before in "/-" and before2.isdigit():
            continue
        if after in "/-" and after2.isdigit():
            continue

        n = int(m.group())
        tagged_hash = before == "#" or (before == " " and before2 == "#")
        if YEAR_MIN <= n <= YEAR_MAX and not tagged_hash:
            continue
        if FLOOR <= n <= CEILING:
            out.append(n)
    return out


def main() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pipeline_runs (source, status) "
                "VALUES ('link_invoices', 'running') RETURNING run_id")
            run_id = cur.fetchone()[0]
        conn.commit()

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT activity_id, job_id, notes FROM activities
                    WHERE type_name = 'Invoice' AND notes IS NOT NULL
                      AND notes <> ''
                """)
                notes = cur.fetchall()

            links = {}  # (job_id, doc_number) -> source_activity_id (first seen)
            for activity_id, job_id, note in notes:
                for n in extract_invoice_numbers(note):
                    links.setdefault((job_id, str(n)), activity_id)

            rows = [(j, d, a) for (j, d), a in sorted(links.items())]
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO job_invoices (job_id, doc_number, source_activity_id)
                    VALUES (%s,%s,%s)
                    ON CONFLICT (job_id, doc_number) DO UPDATE SET
                        source_activity_id = EXCLUDED.source_activity_id
                """, rows)
                cur.execute(
                    "UPDATE pipeline_runs SET finished_at = now(), status = 'ok', "
                    "rows_in = %s, rows_out = %s WHERE run_id = %s",
                    (len(notes), len(rows), run_id))
            conn.commit()

            # Reconciliation
            with conn.cursor() as cur:
                cur.execute("SELECT count(DISTINCT doc_number) FROM job_invoices")
                distinct_docs = cur.fetchone()[0]
                cur.execute("""
                    SELECT count(DISTINCT ji.doc_number) FROM job_invoices ji
                    JOIN invoices i ON i.doc_number = ji.doc_number
                """)
                in_qb = cur.fetchone()[0]
                cur.execute("""
                    SELECT DISTINCT ji.doc_number FROM job_invoices ji
                    LEFT JOIN invoices i ON i.doc_number = ji.doc_number
                    WHERE i.doc_number IS NULL
                    ORDER BY ji.doc_number::int
                """)
                not_in_qb = [r[0] for r in cur.fetchall()]
                cur.execute("""
                    SELECT count(*) FROM invoices i
                    WHERE NOT EXISTS (SELECT 1 FROM job_invoices ji
                                      WHERE ji.doc_number = i.doc_number)
                """)
                qb_unlinked = cur.fetchone()[0]

            print(f"invoice-activity notes scanned:        {len(notes)}")
            print(f"(job, doc_number) links written:       {len(rows)}")
            print(f"distinct invoice numbers extracted:    {distinct_docs}")
            print(f"  of which exist in invoices (QB):     {in_qb}")
            print(f"  extracted but NOT in QB (typos):     {len(not_in_qb)}")
            for d in not_in_qb:
                print(f"    {d}")
            print(f"QB invoices with no Moraware job:      {qb_unlinked}")
        except Exception:
            conn.rollback()
            err = traceback.format_exc()
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE pipeline_runs SET finished_at = now(), "
                    "status = 'failed', error = %s WHERE run_id = %s",
                    (err, run_id))
            conn.commit()
            print(err, file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

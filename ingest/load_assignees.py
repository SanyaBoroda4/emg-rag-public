"""Load activity_assignees.csv into activity_assignees.

The CSV (browser crawl, point-in-time snapshot) has columns
activityId,jobId,typeName,date,assigned,duration,schedTime. The `assigned` cell
holds zero or more names separated by commas ("Victor, Diana"); names like
"Ihor/Tolik" are a single team entry. Moraware exposes no assignee IDs anywhere
(the JSON export's assignees arrays are all empty), so assignee_id is
synthesized as a stable 63-bit hash of the verbatim name — the same name always
maps to the same ID, independent of what other names exist.

Rows whose activityId is not in `activities` are counted and reported; if more
than 1% of non-blank rows are orphans the script aborts without inserting.
Upsert on (activity_id, assignee_id); running twice yields identical counts.
"""

import csv
import hashlib
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.db import get_conn

CSV_PATH = Path("/opt/emg-rag/raw/moraware/activity_assignees.csv")


def assignee_id_for(name: str) -> int:
    """Stable positive 63-bit ID derived from the verbatim assignee name."""
    digest = hashlib.sha1(name.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & (2**63 - 1)


def main() -> int:
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    nonblank = [r for r in rows if r["assigned"].strip()]

    pairs = {}  # (activity_id, assignee_id) -> name, dedups repeats in one cell
    for r in nonblank:
        act_id = int(r["activityId"])
        for name in r["assigned"].split(","):
            name = name.strip()
            if name:
                pairs[(act_id, assignee_id_for(name))] = name

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pipeline_runs (source, status) "
                "VALUES ('assignees', 'running') RETURNING run_id")
            run_id = cur.fetchone()[0]
        conn.commit()

        try:
            with conn.cursor() as cur:
                cur.execute("SELECT activity_id FROM activities")
                known = {row[0] for row in cur.fetchall()}

            csv_act_ids = {int(r["activityId"]) for r in nonblank}
            orphan_ids = sorted(csv_act_ids - known)
            print(f"CSV rows: {len(rows)} | non-blank assigned: {len(nonblank)} "
                  f"| (activity, assignee) pairs: {len(pairs)}")
            print(f"CSV activity_ids missing from activities: {len(orphan_ids)}")
            if orphan_ids:
                print(f"  samples: {orphan_ids[:10]}")
            if len(orphan_ids) > len(csv_act_ids) * 0.01:
                raise RuntimeError(
                    f"{len(orphan_ids)} orphan activity_ids (> 1% of "
                    f"{len(csv_act_ids)}) — stopping, not silently dropping")

            insert_rows = [(a, i, n) for (a, i), n in sorted(pairs.items())
                           if a in known]
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO activity_assignees (activity_id, assignee_id, "
                    "assignee_name) VALUES (%s,%s,%s) "
                    "ON CONFLICT (activity_id, assignee_id) DO UPDATE SET "
                    "assignee_name = EXCLUDED.assignee_name", insert_rows)
                cur.execute(
                    "UPDATE pipeline_runs SET finished_at = now(), status = 'ok', "
                    "rows_in = %s, rows_out = %s WHERE run_id = %s",
                    (len(rows), len(insert_rows), run_id))
            conn.commit()
            print(f"upserted {len(insert_rows)} assignee rows "
                  f"({len(pairs) - len(insert_rows)} dropped as orphans)")
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

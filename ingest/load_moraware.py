"""Load the Moraware page export into Postgres.

Reads /opt/emg-rag/raw/moraware/pages/*.json (112 files, UTF-8 with BOM) and
populates: jobs, job_contacts, activities, job_forms, area_fields, job_summary.

Idempotent: jobs / activities / job_forms / job_summary upsert on their natural
IDs; job_contacts and area_fields (identity PKs, no natural key) are
delete-then-insert scoped to the jobs on the current page. Running twice yields
identical row counts.

Fidelity rules:
  * notes and field values are stored verbatim (\r\n, leading/trailing spaces kept)
  * blank field values are inserted, not skipped
  * null dates stay null
  * jobs.raw / activities.raw hold the untouched source JSON

Memory: one page (~50 jobs, ~350 KB of JSON) in RAM at a time.
"""

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psycopg.types.json import Jsonb

from ingest.db import get_conn

PAGES_DIR = Path("/opt/emg-rag/raw/moraware/pages")

# Job Summary checkbox field name -> job_summary column. A checkbox value of "1"
# means checked; anything else (including "") means unchecked. When a job has
# several Job Summary forms (79 jobs have 2, 6 have 3), checkboxes are
# OR-combined: checked on any form counts as checked.
SUMMARY_FIELDS = {
    "Deposit received": "deposit_received",
    "Paid in Full": "paid_in_full",
    "Removal Ready": "removal_ready",
    "Template Ready": "template_ready",
    "Sink in the shop": "sink_in_shop",
    "Material Ordered": "material_ordered",
    "Material Received": "material_received",
}

JOB_SQL = """
    INSERT INTO jobs (job_id, job_name, account_id, account_name, process_id,
                      process_name, job_status_id, job_status_name, creation_date,
                      salesperson, special_comment, job_notes, job_url,
                      addr_line1, addr_line2, city, state, zip, addr_raw, raw)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (job_id) DO UPDATE SET
        job_name = EXCLUDED.job_name, account_id = EXCLUDED.account_id,
        account_name = EXCLUDED.account_name, process_id = EXCLUDED.process_id,
        process_name = EXCLUDED.process_name, job_status_id = EXCLUDED.job_status_id,
        job_status_name = EXCLUDED.job_status_name, creation_date = EXCLUDED.creation_date,
        salesperson = EXCLUDED.salesperson, special_comment = EXCLUDED.special_comment,
        job_notes = EXCLUDED.job_notes, job_url = EXCLUDED.job_url,
        addr_line1 = EXCLUDED.addr_line1, addr_line2 = EXCLUDED.addr_line2,
        city = EXCLUDED.city, state = EXCLUDED.state, zip = EXCLUDED.zip,
        addr_raw = EXCLUDED.addr_raw, raw = EXCLUDED.raw
"""

ACTIVITY_SQL = """
    INSERT INTO activities (activity_id, job_id, type_id, type_name, status_id,
                            status_name, activity_date, activity_time, duration,
                            notes, raw)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (activity_id) DO UPDATE SET
        job_id = EXCLUDED.job_id, type_id = EXCLUDED.type_id,
        type_name = EXCLUDED.type_name, status_id = EXCLUDED.status_id,
        status_name = EXCLUDED.status_name, activity_date = EXCLUDED.activity_date,
        activity_time = EXCLUDED.activity_time, duration = EXCLUDED.duration,
        notes = EXCLUDED.notes, raw = EXCLUDED.raw
"""

FORM_SQL = """
    INSERT INTO job_forms (form_id, job_id, form_name, form_template_name, field_count)
    VALUES (%s,%s,%s,%s,%s)
    ON CONFLICT (form_id) DO UPDATE SET
        job_id = EXCLUDED.job_id, form_name = EXCLUDED.form_name,
        form_template_name = EXCLUDED.form_template_name,
        field_count = EXCLUDED.field_count
"""

SUMMARY_SQL = """
    INSERT INTO job_summary (job_id, deposit_received, paid_in_full, removal_ready,
                             template_ready, sink_in_shop, material_ordered,
                             material_received)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (job_id) DO UPDATE SET
        deposit_received = EXCLUDED.deposit_received,
        paid_in_full = EXCLUDED.paid_in_full,
        removal_ready = EXCLUDED.removal_ready,
        template_ready = EXCLUDED.template_ready,
        sink_in_shop = EXCLUDED.sink_in_shop,
        material_ordered = EXCLUDED.material_ordered,
        material_received = EXCLUDED.material_received
"""


def form_id_for(job_id: int, form: dict, ordinal: int) -> int:
    """Return Moraware's formId, or a synthetic stable ID when absent.

    In the current export every form carries a real formId, so the synthetic
    path is a documented fallback: -(job_id * 1000 + ordinal). Negative so it
    can never collide with a real (positive) Moraware ID, and stable because
    the export's form order within a job is fixed.
    """
    fid = form.get("formId")
    if fid is not None:
        return fid
    return -(job_id * 1000 + ordinal)


def load_page(cur, page: dict) -> dict:
    counts = {"jobs": 0, "contacts": 0, "activities": 0, "forms": 0,
              "fields": 0, "summaries": 0}
    jobs = page["jobs"]
    job_ids = [j["jobId"] for j in jobs]

    job_rows, contact_rows, act_rows = [], [], []
    form_rows, field_rows, summary_rows = [], [], []

    for job in jobs:
        jid = job["jobId"]
        addr = job.get("address") or {}
        job_rows.append((
            jid, job.get("jobName"), job.get("accountId"), job.get("accountName"),
            job.get("processId"), job.get("processName"), job.get("jobStatusId"),
            job.get("jobStatusName"), job.get("creationDate"), job.get("salesperson"),
            job.get("specialComment"), job.get("jobNotes"), job.get("jobUrl"),
            addr.get("line1"), addr.get("line2"), addr.get("city"),
            addr.get("state"), addr.get("zip"), addr.get("raw"), Jsonb(job),
        ))
        for c in job.get("contacts") or []:
            contact_rows.append((jid, c.get("name"), c.get("phone"),
                                 c.get("cell"), c.get("email")))
        for a in job.get("activities") or []:
            act_rows.append((
                a["activityId"], jid, a.get("typeId"), a.get("typeName"),
                a.get("statusId"), a.get("statusName"), a.get("date") or None,
                a.get("time"), a.get("duration"), a.get("notes"), Jsonb(a),
            ))

        summary = None
        for ordinal, form in enumerate(job.get("forms") or []):
            fid = form_id_for(jid, form, ordinal)
            fields = form.get("fields") or []
            form_rows.append((fid, jid, form.get("formName"),
                              form.get("formTemplateName"),
                              form.get("fieldCount", len(fields))))
            for fld in fields:
                field_rows.append((fid, jid, fld.get("name"),
                                   fld.get("value"), fld.get("dataType")))
            if form.get("formTemplateName") == "Job Summary":
                if summary is None:
                    summary = {col: False for col in SUMMARY_FIELDS.values()}
                for fld in fields:
                    col = SUMMARY_FIELDS.get(fld.get("name"))
                    if col and fld.get("value") == "1":
                        summary[col] = True
        if summary is not None:
            summary_rows.append((jid, summary["deposit_received"],
                                 summary["paid_in_full"], summary["removal_ready"],
                                 summary["template_ready"], summary["sink_in_shop"],
                                 summary["material_ordered"],
                                 summary["material_received"]))

    cur.executemany(JOB_SQL, job_rows)
    cur.execute("DELETE FROM job_contacts WHERE job_id = ANY(%s)", (job_ids,))
    if contact_rows:
        cur.executemany(
            "INSERT INTO job_contacts (job_id, name, phone, cell, email) "
            "VALUES (%s,%s,%s,%s,%s)", contact_rows)
    if act_rows:
        cur.executemany(ACTIVITY_SQL, act_rows)
    if form_rows:
        cur.executemany(FORM_SQL, form_rows)
    cur.execute("DELETE FROM area_fields WHERE job_id = ANY(%s)", (job_ids,))
    if field_rows:
        cur.executemany(
            "INSERT INTO area_fields (form_id, job_id, field_name, field_value, "
            "data_type) VALUES (%s,%s,%s,%s,%s)", field_rows)
    if summary_rows:
        cur.executemany(SUMMARY_SQL, summary_rows)

    counts["jobs"] = len(job_rows)
    counts["contacts"] = len(contact_rows)
    counts["activities"] = len(act_rows)
    counts["forms"] = len(form_rows)
    counts["fields"] = len(field_rows)
    counts["summaries"] = len(summary_rows)
    return counts


def main() -> int:
    files = sorted(PAGES_DIR.glob("*.json"))
    if not files:
        print(f"FAIL: no page files in {PAGES_DIR}", file=sys.stderr)
        return 1

    totals = {"jobs": 0, "contacts": 0, "activities": 0, "forms": 0,
              "fields": 0, "summaries": 0}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pipeline_runs (source, status) "
                "VALUES ('moraware', 'running') RETURNING run_id")
            run_id = cur.fetchone()[0]
        conn.commit()

        try:
            for i, fp in enumerate(files):
                with open(fp, encoding="utf-8-sig") as f:
                    page = json.load(f)
                with conn.cursor() as cur:
                    counts = load_page(cur, page)
                conn.commit()
                for k, v in counts.items():
                    totals[k] += v
                if (i + 1) % 20 == 0 or i == len(files) - 1:
                    print(f"  {i + 1}/{len(files)} pages, "
                          f"{totals['jobs']} jobs, {totals['fields']} fields")
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

        rows_out = sum(totals.values())
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pipeline_runs SET finished_at = now(), status = 'ok', "
                "rows_in = %s, rows_out = %s WHERE run_id = %s",
                (totals["jobs"], rows_out, run_id))
        conn.commit()

    print(f"done: {totals}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

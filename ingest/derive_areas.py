"""Derive job_areas (typed layer) from area_fields (verbatim layer).

job_areas is DISPOSABLE derived data: this script does a full truncate +
rebuild every run, which is what makes it re-runnable. Never treat job_areas
as a source of record — area_fields is.

Each Details-template form becomes one job_areas row. Verified against the
export: every Details form carries exactly these 15 fields — Room type, Sq Ft,
Supplier, Material Name, Sink, Sink Types, Sink Installed As, Edge, Backsplash,
Faucet info, Removal, Brackets, HLF, Reference:, Notes.

area_name comes from the form's own formName (e.g. "Kitchen", "Vanity") — the
export has no "Details - X" prefix convention; formName IS the area name.
5,287 of 6,597 Details forms have a blank formName (single-area jobs mostly);
those get area_name NULL.

sq_ft: numeric parse of values like "72", "72.5", "72 sf", " 72 ", "$72".
Unparseable non-blank values become sq_ft NULL with the verbatim original in
sq_ft_raw (sq_ft_raw always keeps the original, parsed or not). Failure count
and 10 samples are reported.
"""

import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.db import get_conn

FIELD_TO_COL = {
    "Room type": "room_type",
    "Sq Ft": "sq_ft_raw",
    "Material Name": "material_name",
    "Supplier": "supplier",
    "Sink": "sink",
    "Sink Types": "sink_types",
    "Sink Installed As": "sink_installed_as",
    "Edge": "edge",
    "Backsplash": "backsplash",
    "Faucet info": "faucet_info",
    "Removal": "removal",
    "Brackets": "brackets",
    "HLF": "hlf",
    "Reference:": "reference",
    "Notes": "notes",
}

# "72", "72.5", "72 sf", "72sqft", "72 sq ft", "72 ft", "$72", trailing period.
SQFT_RE = re.compile(
    r"^\$?\s*(\d+(?:\.\d+)?)\s*(?:sf|sq\.?\s*ft\.?|sqft|ft2|ft)?\.?$",
    re.IGNORECASE)


def parse_sqft(raw):
    """Return (numeric_or_None, failed_bool). Blank is NULL but not a failure."""
    if raw is None or raw.strip() == "":
        return None, False
    m = SQFT_RE.match(raw.strip())
    if m:
        return float(m.group(1)), False
    return None, True


def main() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pipeline_runs (source, status) "
                "VALUES ('derive_areas', 'running') RETURNING run_id")
            run_id = cur.fetchone()[0]
        conn.commit()

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT f.form_id, f.job_id, f.form_name,
                           af.field_name, af.field_value
                    FROM job_forms f
                    JOIN area_fields af ON af.form_id = f.form_id
                    WHERE f.form_template_name = 'Details'
                    ORDER BY f.form_id
                """)
                forms = {}  # form_id -> {col: value}, insertion-ordered
                for form_id, job_id, form_name, fname, fvalue in cur:
                    d = forms.setdefault(form_id, {"job_id": job_id,
                                                   "form_name": form_name})
                    col = FIELD_TO_COL.get(fname)
                    if col:
                        d[col] = fvalue

            rows, failures = [], []
            for form_id, d in forms.items():
                sq_ft, failed = parse_sqft(d.get("sq_ft_raw"))
                if failed:
                    failures.append((form_id, d["job_id"], d.get("sq_ft_raw")))
                rows.append((
                    d["job_id"], form_id, d["form_name"] or None,
                    d.get("room_type"), sq_ft, d.get("sq_ft_raw"),
                    d.get("material_name"), d.get("supplier"), d.get("sink"),
                    d.get("sink_types"), d.get("sink_installed_as"),
                    d.get("edge"), d.get("backsplash"), d.get("faucet_info"),
                    d.get("removal"), d.get("brackets"), d.get("hlf"),
                    d.get("reference"), d.get("notes")))

            with conn.cursor() as cur:
                cur.execute("TRUNCATE job_areas")
                cur.executemany("""
                    INSERT INTO job_areas (job_id, form_id, area_name, room_type,
                        sq_ft, sq_ft_raw, material_name, supplier, sink,
                        sink_types, sink_installed_as, edge, backsplash,
                        faucet_info, removal, brackets, hlf, reference, notes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, rows)
                cur.execute(
                    "UPDATE pipeline_runs SET finished_at = now(), status = 'ok', "
                    "rows_in = %s, rows_out = %s WHERE run_id = %s",
                    (len(forms), len(rows), run_id))
            conn.commit()

            print(f"job_areas rebuilt: {len(rows)} rows from "
                  f"{len(forms)} Details forms")
            print(f"sq_ft parse failures: {len(failures)}")
            for form_id, job_id, raw in failures[:10]:
                print(f"  form {form_id} job {job_id}: {raw!r}")
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

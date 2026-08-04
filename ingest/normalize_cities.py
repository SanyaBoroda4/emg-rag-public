"""Fill jobs.city_normalized / city_norm_source from the approved mapping.

Raw-first: jobs.city is never touched. Resolution order per job — first rule
that fires wins:

  1. name_map    — exact raw-string lookup in data/city_map_final.csv.
                   Real canonical -> that value. Empty canonical -> NULL
                   ('excluded': deliberate junk like bare "SC", street
                   addresses, an email).
  2. zip         — only for rows the map marks CHARLESTON_NEEDS_ZIP. The
                   generic "Charleston" label is mostly wrong (most such jobs
                   are West Ashley / James Island / etc.), so those resolve by
                   ZIP. A specific typed name always beats a ZIP — 29455
                   covers Johns/Kiawah/Seabrook Islands, so "Seabrook Island,
                   SC 29455" must stay Seabrook Island; that is why the name
                   map runs first.
  3. address_map — still unresolved and addr_line1 exactly matches
                   data/charleston_address_map.csv -> that area.
  4. unresolved  — NULL, counted and listed by scripts/verify_cities.py.

Jobs with no raw city string at all are left NULL/NULL (nothing to
normalize; keeps 'unresolved' meaning "had a city but no rule fired").

Idempotent: full recompute on every run, batched updates, one pipeline_runs
row.
"""

import csv
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.db import get_conn

REPO = Path(__file__).resolve().parent.parent
CITY_MAP_CSV = REPO / "data" / "city_map_final.csv"
ADDRESS_MAP_CSV = REPO / "data" / "charleston_address_map.csv"

# Verified against USPS and Charleston-area real-estate sources (analysis
# reviewed and approved by Alex). Folly Beach (29439) is deliberately folded
# into James Island per Alex's decision.
ZIP_TO_AREA = {
    "29401": "Downtown Charleston", "29403": "Charleston",
    "29402": "Charleston",
    "29405": "North Charleston", "29406": "North Charleston",
    "29415": "North Charleston", "29418": "North Charleston",
    "29419": "North Charleston", "29420": "North Charleston",
    "29404": "North Charleston",
    "29407": "West Ashley", "29414": "West Ashley", "29417": "West Ashley",
    "29412": "James Island", "29422": "James Island", "29439": "James Island",
    "29409": "Charleston", "29413": "Charleston", "29424": "Charleston",
    "29425": "Charleston",
    "29410": "Hanahan",
    "29423": "Ladson", "29456": "Ladson",
    "29429": "Awendaw", "29426": "Adams Run",
    "29431": "Moncks Corner", "29461": "Moncks Corner",
    "29438": "Edisto Island", "29445": "Goose Creek", "29449": "Hollywood",
    "29450": "Huger", "29451": "Isle of Palms",
    "29455": "Johns Island", "29457": "Johns Island",
    "29458": "McClellanville",
    "29464": "Mount Pleasant", "29465": "Mount Pleasant",
    "29466": "Mount Pleasant",
    "29470": "Ravenel", "29472": "Ridgeville", "29474": "Round O",
    "29475": "Ruffin", "29479": "St Stephen",
    "29482": "Sullivan's Island",
    "29483": "Summerville", "29485": "Summerville", "29486": "Summerville",
    "29487": "Wadmalaw Island", "29488": "Walterboro",
    "29492": "Daniel Island",
    "29448": "Harleyville", "29453": "Jamestown", "29468": "Pineville",
    "29471": "Reevesville",
}

# Obvious observed typos, corrected pre-lookup. Anything else that fails the
# lookup (29214, "294", "USA"...) is NOT guessed at — it falls through.
ZIP_TYPOS = {"299407": "29407", "20407": "29407", "20414": "29414"}

BATCH = 500


def load_maps():
    name_map = {}
    with open(CITY_MAP_CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            name_map[r["raw_city"]] = r["canonical_city"]
    addr_map = {}
    with open(ADDRESS_MAP_CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            addr_map[r["address"]] = r["assigned_area"]
    return name_map, addr_map


def clean_zip(candidate: str):
    """Digits-only, typo-corrected; returns a known ZIP or None."""
    digits = re.sub(r"\D", "", candidate or "")
    digits = ZIP_TYPOS.get(digits, digits)
    if len(digits) >= 5 and digits[:5] in ZIP_TO_AREA:
        return digits[:5]
    return None


def resolve_zip(zip_field, city_field):
    """ZIP from jobs.zip first, else a 5-digit token inside jobs.city."""
    z = clean_zip(zip_field)
    if z:
        return z
    for m in re.finditer(r"\d[\d .-]*", city_field or ""):
        z = clean_zip(m.group())
        if z:
            return z
    return None


def resolve(raw_city, zip_field, addr, name_map, addr_map):
    """Returns (city_normalized, city_norm_source) — (None, None) if no city."""
    if not (raw_city or "").strip():
        return None, None
    canonical = name_map.get(raw_city)
    if canonical is not None and canonical == "":
        return None, "excluded"
    if canonical and canonical != "CHARLESTON_NEEDS_ZIP":
        return canonical, "name_map"
    if canonical == "CHARLESTON_NEEDS_ZIP":
        z = resolve_zip(zip_field, raw_city)
        if z:
            return ZIP_TO_AREA[z], "zip"
    if addr and addr in addr_map:
        return addr_map[addr], "address_map"
    return None, "unresolved"


def main() -> int:
    name_map, addr_map = load_maps()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pipeline_runs (source, status) "
                "VALUES ('normalize_cities', 'running') RETURNING run_id")
            run_id = cur.fetchone()[0]
        conn.commit()

        try:
            counts = {}
            with conn.cursor(name="jobs_scan") as scan, \
                    conn.cursor() as upd:
                scan.execute("SELECT job_id, city, zip, addr_line1 "
                             "FROM jobs ORDER BY job_id")
                while True:
                    rows = scan.fetchmany(BATCH)
                    if not rows:
                        break
                    updates = []
                    for job_id, city, zip_f, addr in rows:
                        norm, source = resolve(city, zip_f, addr,
                                               name_map, addr_map)
                        counts[source] = counts.get(source, 0) + 1
                        updates.append((norm, source, job_id))
                    upd.executemany(
                        "UPDATE jobs SET city_normalized = %s, "
                        "city_norm_source = %s WHERE job_id = %s", updates)
            total = sum(counts.values())
            note = " ".join(f"{k or 'no_city'}={v}"
                            for k, v in sorted(counts.items(),
                                               key=lambda x: str(x[0])))
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE pipeline_runs SET finished_at = now(), "
                    "status = 'ok', rows_in = %s, rows_out = %s, note = %s "
                    "WHERE run_id = %s", (total, total, note, run_id))
            conn.commit()
            print(f"normalized {total} jobs: {note}")
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

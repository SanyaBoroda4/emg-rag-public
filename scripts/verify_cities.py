"""City-normalization gate (WO5).

Asserts the approved analysis numbers: 68 distinct canonical areas, the
exact expected counts for the top markets, ~3,789 normalized rows. A mismatch
means a rule was mis-implemented — investigate, don't adjust expectations.
Small deviations (±2) may be legitimate ZIP-typo rounding: reported with the
specific rows, not silently passed. Also proves jobs.city was never modified.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.db import get_conn

EXPECTED_DISTINCT = 68
EXPECTED_TOTAL = 3789
EXPECTED_COUNTS = {
    "West Ashley": 601, "Mount Pleasant": 516, "Johns Island": 423,
    "James Island": 395, "North Charleston": 196, "Kiawah Island": 178,
    "Edisto Island": 177, "Summerville": 163, "Seabrook Island": 163,
    "Hollywood": 119, "Daniel Island": 103, "Downtown Charleston": 94,
    "Isle of Palms": 79, "Charleston": 79,
}
TOLERANCE = 2


def main() -> int:
    failed = False
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(DISTINCT city_normalized) FROM jobs "
                    "WHERE city_normalized IS NOT NULL")
        distinct = cur.fetchone()[0]
        ok = distinct == EXPECTED_DISTINCT
        failed |= not ok
        print(f"distinct canonical cities: {distinct} "
              f"(expected {EXPECTED_DISTINCT}) {'OK' if ok else '** MISMATCH **'}")

        cur.execute("SELECT city_normalized, count(*) FROM jobs "
                    "WHERE city_normalized IS NOT NULL GROUP BY 1")
        actual = dict(cur.fetchall())
        print(f"\n{'city':<22} {'expected':>8} {'actual':>8}  status")
        print("-" * 52)
        for city, exp in EXPECTED_COUNTS.items():
            act = actual.get(city, 0)
            delta = act - exp
            if delta == 0:
                status = "OK"
            elif abs(delta) <= TOLERANCE:
                status = f"DELTA {delta:+d} (within ±{TOLERANCE} — see rows below)"
            else:
                status = "** MISMATCH **"
                failed = True
            print(f"{city:<22} {exp:>8} {act:>8}  {status}")

        total = sum(actual.values())
        delta = total - EXPECTED_TOTAL
        ok = abs(delta) <= 5
        failed |= not ok
        print(f"\ntotal normalized rows: {total} (expected ~{EXPECTED_TOTAL}, "
              f"delta {delta:+d}) {'OK' if ok else '** MISMATCH **'}")

        print("\nbreakdown by city_norm_source:")
        cur.execute("SELECT coalesce(city_norm_source, '(no raw city)'), "
                    "count(*) FROM jobs GROUP BY 1 ORDER BY 2 DESC")
        for source, n in cur.fetchall():
            print(f"  {source:<16} {n:>6}")

        print("\nunresolved rows (full list):")
        cur.execute("SELECT job_id, city, zip, addr_line1 FROM jobs "
                    "WHERE city_norm_source = 'unresolved' ORDER BY job_id")
        unresolved = cur.fetchall()
        for job_id, city, zip_f, addr in unresolved:
            print(f"  job {job_id}: city={city!r} zip={zip_f!r} addr={addr!r}")
        print(f"  ({len(unresolved)} unresolved)")

        # any DELTA rows: show which zip-resolved rows feed the off-by-a-few
        for city, exp in EXPECTED_COUNTS.items():
            act = actual.get(city, 0)
            if act != exp and abs(act - exp) <= TOLERANCE:
                cur.execute(
                    "SELECT job_id, city, zip, city_norm_source FROM jobs "
                    "WHERE city_normalized = %s AND city_norm_source <> "
                    "'name_map' ORDER BY job_id", (city,))
                print(f"\n{city} delta detail (non-name_map rows):")
                for row in cur.fetchall():
                    print(f"  {row}")

        # raw-first proof: jobs.city untouched — same distinct-count as the
        # export analysis (294 raw spellings over 3,838 city-bearing jobs)
        cur.execute("SELECT count(DISTINCT city), count(*) FILTER "
                    "(WHERE city <> '') FROM jobs WHERE city IS NOT NULL "
                    "AND city <> ''")
        raw_distinct, raw_rows = cur.fetchone()
        ok = raw_distinct == 294 and raw_rows == 3838
        failed |= not ok
        print(f"\nraw jobs.city untouched: {raw_distinct} distinct spellings "
              f"over {raw_rows} jobs (expected 294 / 3838) "
              f"{'OK' if ok else '** RAW DATA CHANGED **'}")

    print("\nFAIL" if failed else "\nOK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

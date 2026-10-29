"""Verify the database is up and correctly shaped.

Connects with credentials from .env, prints the server version, confirms the
vector extension is installed, and lists every public table with its row count.
Exits non-zero on any failure.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.db import get_conn


def main() -> int:
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT version()")
            print(cur.fetchone()[0])

            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            row = cur.fetchone()
            if row is None:
                print("FAIL: vector extension is not installed", file=sys.stderr)
                return 1
            print(f"vector extension: {row[0]}")

            cur.execute(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY tablename
                """
            )
            tables = [r[0] for r in cur.fetchall()]
            if not tables:
                print("FAIL: no tables in public schema", file=sys.stderr)
                return 1

            print(f"\n{len(tables)} tables:")
            for t in tables:
                cur.execute(f'SELECT count(*) FROM "{t}"')
                print(f"  {t:<20} {cur.fetchone()[0]:>8} rows")
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1

    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

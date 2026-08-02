"""Create/refresh the rag_reader read-only Postgres role.

The text-to-SQL lane executes model-written SQL, so its credential must be
physically incapable of writing: rag_reader gets CONNECT + USAGE + SELECT on
the five v_* views and NOTHING else (no base-table access). A 10s
statement_timeout is set at the role level as a second line of defence
(sql_lane also sets it per session).

Idempotent. Password comes from PG_RO_PASSWORD in .env — set it before
running. Run as the admin user after applying sql/005_views.sql.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.db import get_conn

VIEWS = ["v_jobs", "v_job_areas", "v_invoices", "v_job_invoices",
         "v_activities"]


def main() -> int:
    password = os.environ.get("PG_RO_PASSWORD")
    if not password:
        print("FAIL: PG_RO_PASSWORD not set in .env", file=sys.stderr)
        return 1

    with get_conn(autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'rag_reader'")
        if cur.fetchone() is None:
            cur.execute("CREATE ROLE rag_reader LOGIN NOSUPERUSER "
                        "NOCREATEDB NOCREATEROLE")
        # psycopg can't parameterize ALTER ROLE; quote via literal escape
        cur.execute("ALTER ROLE rag_reader WITH LOGIN PASSWORD %s"
                    % ("'" + password.replace("'", "''") + "'"))
        cur.execute("ALTER ROLE rag_reader SET statement_timeout = '10s'")
        cur.execute("GRANT CONNECT ON DATABASE %s TO rag_reader"
                    % os.environ["PG_DB"])
        cur.execute("GRANT USAGE ON SCHEMA public TO rag_reader")
        # start from zero every run, then grant the views back
        cur.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM rag_reader")
        for v in VIEWS:
            cur.execute(f"GRANT SELECT ON {v} TO rag_reader")

        # prove the fence: rag_reader must not be able to read a base table
        cur.execute("SELECT has_table_privilege('rag_reader', 'jobs', 'SELECT'), "
                    "has_table_privilege('rag_reader', 'v_jobs', 'SELECT')")
        base_ok, view_ok = cur.fetchone()
        print(f"rag_reader SELECT on base table jobs: {base_ok} (must be False)")
        print(f"rag_reader SELECT on view v_jobs:     {view_ok} (must be True)")
        if base_ok or not view_ok:
            print("FAIL: grants are wrong", file=sys.stderr)
            return 1

    print("rag_reader role configured")
    return 0


if __name__ == "__main__":
    sys.exit(main())

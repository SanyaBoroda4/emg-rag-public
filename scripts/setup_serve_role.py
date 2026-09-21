"""Set rag_serve's password and view grants (WO16). Idempotent.

    python scripts/setup_serve_role.py

Reads PG_SERVE_PASSWORD from .env (never printed). sql/020 creates the
role and the serve.* grants; this script sets the password and grants
SELECT on the same v_* views rag_reader can read, then proves the fence:
rag_serve can read serve.asks and the views, rag_reader cannot read
serve.asks.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from psycopg import sql

from ingest.db import get_conn
from scripts.setup_ro_role import VIEWS

load_dotenv()


def main() -> int:
    password = os.environ.get("PG_SERVE_PASSWORD")
    if not password:
        print("PG_SERVE_PASSWORD missing from .env", file=sys.stderr)
        return 1
    with get_conn(autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("ALTER ROLE rag_serve WITH LOGIN PASSWORD {}")
                    .format(sql.Literal(password)))  # DDL: no bind params
        cur.execute("ALTER ROLE rag_serve SET statement_timeout = '10s'")
        for v in VIEWS + ["v_quoted_jobs"]:
            cur.execute(f"GRANT SELECT ON {v} TO rag_serve")
        cur.execute("""
            SELECT has_schema_privilege('rag_serve', 'serve', 'USAGE'),
                   has_table_privilege('rag_serve', 'serve.asks', 'INSERT'),
                   has_table_privilege('rag_serve', 'v_jobs', 'SELECT'),
                   has_table_privilege('rag_serve', 'jobs', 'SELECT'),
                   has_schema_privilege('rag_reader', 'serve', 'USAGE'),
                   has_table_privilege('rag_reader', 'serve.asks', 'SELECT')
        """)
        s_usage, s_ins, s_view, s_base, r_usage, r_asks = cur.fetchone()
    print(f"rag_serve: serve USAGE {s_usage} (True) · asks INSERT {s_ins} (True) "
          f"· v_jobs SELECT {s_view} (True) · base table jobs {s_base} (False)")
    print(f"rag_reader: serve USAGE {r_usage} (False) · serve.asks SELECT "
          f"{r_asks} (False)")
    ok = s_usage and s_ins and s_view and not s_base and not r_usage and not r_asks
    print("FENCE OK" if ok else "FENCE BROKEN")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())

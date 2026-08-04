"""Structured lane: text-to-SQL over the v_* views.

Generation uses Sonnet (not Haiku) deliberately: a wrong join returns a
confident wrong number with no error, which is the expensive failure mode
here. The model sees only the five whitelisted views.

Defence in depth, all mandatory before execution:
  1. sqlglot parse: exactly one statement, and it must be a SELECT
  2. every referenced table is in the view whitelist (CTE names excepted);
     every referenced column exists in the whitelisted views or is an alias
     defined inside the query itself
  3. a LIMIT (default 200) is forced onto the outer query if absent
  4. execution happens on the rag_reader role — SELECT on the views only,
     physically incapable of writing — with statement_timeout=10s

Never returns rows without the SQL that produced them.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic
import sqlglot
from dotenv import load_dotenv
from sqlglot import exp

from ingest.db import get_ro_conn

load_dotenv()

SQL_MODEL = os.environ.get("SQL_MODEL", "claude-sonnet-5")
DEFAULT_LIMIT = 200

ALLOWED_VIEWS = {
    "v_jobs": ["job_id", "job_name", "customer", "salesperson", "city",
               "process_name", "status", "creation_date", "city_raw"],
    "v_job_areas": ["job_id", "job_name", "area_name", "room_type", "sq_ft",
                    "material_name", "supplier", "edge", "backsplash", "sink"],
    "v_invoices": ["doc_number", "customer_name", "txn_date", "total_amt",
                   "balance", "status"],
    "v_job_invoices": ["job_id", "job_name", "doc_number", "txn_date",
                       "total_amt", "balance", "status"],
    "v_activities": ["activity_id", "job_id", "job_name", "type_name",
                     "status_name", "activity_date", "phase", "assignees",
                     "note"],
}

SCHEMA_DDL = """
v_jobs(job_id, job_name, customer, salesperson, city, process_name, status, creation_date date, city_raw)
  -- one row per job. status examples: 'Complete', 'Cancelled', 'In Progress'. job_name is usually the customer name.
  -- city is NORMALIZED to 68 canonical Charleston-area names (e.g. 'West Ashley', 'Mount Pleasant', 'Johns Island') — filter on it with exact = matches. city_raw is the original free text; never filter on city_raw unless explicitly asked for raw values.
v_job_areas(job_id, job_name, area_name, room_type, sq_ft numeric, material_name, supplier, edge, backsplash, sink)
  -- one row per countertop area of a job. material_name is free text, e.g. '3sl Calacatta Gold', 'Quartzite Sea Pearl'.
v_invoices(doc_number, customer_name, txn_date date, total_amt numeric, balance numeric, status)
  -- QuickBooks invoices. doc_number is text.
v_job_invoices(job_id, job_name, doc_number, txn_date date, total_amt numeric, balance numeric, status)
  -- job <-> invoice links (a job can have several invoices).
v_activities(activity_id, job_id, job_name, type_name, status_name, activity_date date, phase, assignees, note)
  -- Moraware activities. type_name e.g. 'Template','Install','Invoice','Quote','Follow Up','Measure','Phone, Email'.
  -- CAUTION: activity_date IS NULL for ~44% of activities (never-scheduled placeholders).
"""

SYSTEM_PROMPT = f"""You translate questions about a countertop fabrication company's data into a single PostgreSQL SELECT statement.

Available views (the ONLY relations you may reference):
{SCHEMA_DDL}
Rules:
- Output ONLY the SQL statement. No prose, no markdown fences, no comments.
- One SELECT statement (CTEs allowed). Never modify data.
- Text values are messy free text: match with ILIKE '%...%', never equality.
- Material names embed slab counts and finishes ('3sl Calacatta Gold Honed') — always ILIKE.
- Year filters: use date ranges, e.g. creation_date >= '2025-01-01' AND creation_date < '2026-01-01'.
- If the question is about jobs, prefer counting DISTINCT job_id when joins could duplicate rows.
- activity_date is NULL for ~44% of activities; when filtering on it, that silently excludes undated rows (acceptable, but do not pretend the data is complete).
"""


def generate_sql(question: str, hybrid: bool = False):
    """Ask Sonnet for the SQL. Returns (sql_text, usage)."""
    client = anthropic.Anthropic()
    prompt = question
    if hybrid:
        prompt += ("\n\n(Return the matching jobs: the SELECT must include "
                   "the job_id column so results can key a second retrieval "
                   "stage.)")
    resp = client.messages.create(
        model=SQL_MODEL, max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}])
    sql = next(b.text for b in resp.content if b.type == "text").strip()
    if sql.startswith("```"):
        sql = sql.strip("`")
        if sql.lower().startswith("sql"):
            sql = sql[3:]
        sql = sql.strip()
    return sql, resp.usage


def validate_sql(sql: str) -> str:
    """Validate and normalize; returns the SQL to execute. Raises ValueError."""
    try:
        statements = sqlglot.parse(sql, dialect="postgres")
    except sqlglot.errors.ParseError as e:
        raise ValueError(f"SQL does not parse: {e}") from e
    if len(statements) != 1:
        raise ValueError(f"expected exactly 1 statement, got {len(statements)}")
    tree = statements[0]
    if not isinstance(tree, exp.Select):
        raise ValueError(f"only a plain SELECT is allowed, got "
                         f"{type(tree).__name__}")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if name not in ALLOWED_VIEWS and name not in cte_names:
            raise ValueError(f"table '{name}' is not an allowed view")

    allowed_cols = {c for cols in ALLOWED_VIEWS.values() for c in cols}
    query_aliases = set()
    for alias in tree.find_all(exp.Alias):
        query_aliases.add(alias.alias_or_name.lower())
    for cte in tree.find_all(exp.CTE):
        for proj in cte.this.selects:
            query_aliases.add(proj.alias_or_name.lower())
    for col in tree.find_all(exp.Column):
        name = col.name.lower()
        if name and name != "*" and name not in allowed_cols \
                and name not in query_aliases:
            raise ValueError(f"column '{name}' does not exist in the "
                             f"allowed views")

    if tree.args.get("limit") is None:
        tree = tree.limit(DEFAULT_LIMIT)
    return tree.sql(dialect="postgres")


def execute_sql(sql: str):
    """Run validated SQL as rag_reader. Returns (columns, rows)."""
    with get_ro_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
        columns = [d.name for d in cur.description]
        rows = cur.fetchall()
    return columns, rows


def repair_sql(question: str, bad_sql: str, error: str, hybrid: bool):
    """One repair attempt: feed the validator error back to the model."""
    client = anthropic.Anthropic()
    prompt = question
    if hybrid:
        prompt += "\n\n(The SELECT must include the job_id column.)"
    resp = client.messages.create(
        model=SQL_MODEL, max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": bad_sql},
            {"role": "user", "content":
             f"That SQL was rejected: {error}\nRewrite it. Same rules — "
             f"output only the corrected SQL."},
        ])
    sql = next(b.text for b in resp.content if b.type == "text").strip()
    if sql.startswith("```"):
        sql = sql.strip("`")
        if sql.lower().startswith("sql"):
            sql = sql[3:]
        sql = sql.strip()
    return sql, resp.usage


def run_structured(question: str, hybrid: bool = False) -> dict:
    """Full lane: generate -> validate (with one repair) -> execute.

    Never returns rows without the SQL that produced them. Raises ValueError
    if even the repaired SQL fails validation.
    """
    raw_sql, usage = generate_sql(question, hybrid=hybrid)
    usages = [usage]
    try:
        safe_sql = validate_sql(raw_sql)
    except ValueError as e:
        raw_sql, usage2 = repair_sql(question, raw_sql, str(e), hybrid)
        usages.append(usage2)
        safe_sql = validate_sql(raw_sql)  # second failure propagates
    columns, rows = execute_sql(safe_sql)
    return {"sql": safe_sql, "columns": columns, "rows": rows,
            "row_count": len(rows), "usages": usages}

"""Structured lane: text-to-SQL over the v_* views.

Generation uses Sonnet (not Haiku) deliberately: a wrong join returns a
confident wrong number with no error, which is the expensive failure mode
here. The model sees only the whitelisted views.

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

# Default flipped to Haiku in WO7: on the golden set's judge-free numeric
# comparison Haiku scored 18/31 vs Sonnet's 17/31, at 42% of the cost and
# half the latency, with zero validator failures (evals/results/benchmark.md).
SQL_MODEL = os.environ.get("SQL_MODEL", "claude-haiku-4-5")
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
                     "note", "happened", "is_scheduled_future"],
    "v_job_sqft": ["job_id", "total_sq_ft", "area_count"],
    "v_job_pipeline_status": ["job_id", "job_name", "is_quoted",
                              "first_signal_date",
                              "last_signal_date", "signal_source",
                              "had_dated_quote", "had_dated_measure",
                              "had_dated_template", "moved_forward",
                              "first_move_date", "move_is_future",
                              "days_silent", "status"],
    "v_quote_conversion_monthly": ["quote_month", "quoted_jobs",
                                   "moved_forward", "conversion_pct"],
}

# Low-cardinality columns have their EXACT value sets enumerated below (WO7
# Bug C fix): without the values, the model has no reason to consult a
# column — "find jobs with tile work" searched material_name and missed all
# 246 Tile activities. material_name (3,671 distinct unparsed values) is the
# one column that CANNOT benefit from enumeration until it is parsed.
SCHEMA_DDL = """
v_jobs(job_id, job_name, customer, salesperson, city, process_name, status, creation_date date, city_raw)
  -- one row per job. job_name is usually the customer name.
  -- salesperson = who SOLD the job, EXACTLY one of: Alex Sorokin, Denis Trofimov, Diana Diaz, Eugene Konikov, Galya Gornishka, Max Konikov, Natalia Pavlenko, Other, Sasha Nosova, Victor Slabunov, Vlad Gorshchynskiy. ("How many jobs did X sell" -> count v_jobs by salesperson. Who PERFORMED work is v_activities.assignees — crews, not salespeople.)
  -- The company calls its geographic markets "areas": "which area do we work in most" means city, not countertop areas.
  -- city holds EXACTLY one of these canonical area names; ALWAYS filter it with = or IN, NEVER ILIKE/substring ('Charleston', 'North Charleston' and 'Downtown Charleston' are three DIFFERENT areas). NULL = no city recorded. Values:
  --   Adams Run, Awendaw, Beaufort, Bluffton, Blythewood, Charleston, Cottageville, Daniel Island, Dewees Island, Downtown Charleston, Edisto Island, Elloree, Eutawville, Fairfax, Fayeheville, Georgetown, Goose Creek, Green Pond, Greensboro, Hanahan, Harleyville, Hilton Head Island, Hollywood, Huger, Islandton, Isle of Palms, Islington, James Island, Jamestown, Johns Island, Kiawah Island, Ladson, Mcclellanville, Meggett, Moncks Corner, Mount Pleasant, Myrtle Beach, North Charleston, Oak Island, Okatie, Orangeburg, Pawleys Island, Pineville, Ravenel, Reevesville, Ridgeville, Round O, Ruffin, Savannah, Seabrook Island, Smoaks, Southbury, Spring Island, St Helena Island, St Stephen, Sullivan's Island, Sullivan S Island, Summerville, Sumter, Ulmer, Vance, Varnville, Wadmalaw Island, Walterboro, Wando, West Ashley, Yamasee, Yonges Island
  -- status: exactly 'Active' or 'Complete'. process_name: Canceled, Done, Hold, Job, Lead, Leads with Layouts, Measurement (exact match).
  -- city_raw is the original free text; never use it unless raw values are explicitly requested.
v_job_areas(job_id, job_name, area_name, room_type, sq_ft numeric, material_name, supplier, edge, backsplash, sink)
  -- one row per countertop area of a job.
  -- room_type values (exact): Kitchen, Secondary Bath, Entire Project, Master Bath, Outdoor Kitchen, Other, Fireplace, Laundry, Curbs, Bar, Table top, Island, Desk, Bck, Pantry, Bench, Kitchen and Fireplace, Closet, Pool, Wall.
  -- material_name is UNPARSED free text ('3sl Calacatta Gold Honed', '(1.5)Calcatta Liberty') — the ONE column where ILIKE '%...%' substring matching is correct.
v_invoices(doc_number, customer_name, txn_date date, total_amt numeric, balance numeric, status)
  -- QuickBooks invoices. doc_number is text. status is EXACTLY one of: Paid, Partially Paid, Open. Revenue/invoiced-amount questions: sum total_amt with NO status filter unless the question asks about payment state.
v_job_invoices(job_id, job_name, doc_number, txn_date date, total_amt numeric, balance numeric, status)
  -- job <-> invoice links (a job can have several invoices).
v_activities(activity_id, job_id, job_name, type_name, status_name, activity_date date, phase, assignees, note, happened boolean, is_scheduled_future boolean)
  -- Moraware activities — the record of WORK: quotes, templates, installs, tile work etc. are activities, found HERE by type_name, not in material or note text.
  -- CRITICAL — a row is NOT an event. Activities are pre-created on every job as placeholders; only a DATED row represents something real. Three states:
  --   | state                        | meaning                   | counts as                       |
  --   | activity_date IS NULL        | placeholder, never happened | never count                   |
  --   | dated, <= as-of snapshot     | happened                  | "did / completed / have we"     |
  --   | dated, > as-of snapshot      | scheduled, not yet done   | "scheduled / upcoming" only     |
  -- The booleans encode this: happened = dated and on/before the data snapshot date; is_scheduled_future = dated after it. Business-event counting questions ("how many quotes have we issued", "how many installs did we do") must count only rows WHERE happened. Undated activities are pre-created placeholders and must never be counted as events. Only count is_scheduled_future rows when the question asks about scheduled/upcoming work. "Completed" means happened — NOT status_name = 'Complete' (statuses are unreliable).
  -- type_name is EXACTLY one of (use =): Contract, Email, Fabrication, Follow Up, Follow Up After Install, Install, Invoice, Measure, Meeting, Paid if Full, Phone call, Phone, Email, Plumbing, Quote, Removal, Repair, Template, Tile.
  -- status_name is EXACTLY one of: Estimate, Complete, Paid in Full and Finished, Confirmed, RTF, In Progress.
  -- assignees is a comma-joined list drawn from: Alex, Diana, Eugene, Fabricators, Francisco, Ihor/Tolik, Installers, Ivan Andreev, Ivan Tile, Leo, Max, Max Tile, Measuring Specialist (Heidi), Measuring Specialist (Jack), Murilo, Natalia, Office People, Others, Sasha, Thiago, Tile Guys, Victor, Walter, Wes, Yuri/Petro — match with ILIKE '%name%' (it is a joined list).
v_job_sqft(job_id, total_sq_ft numeric, area_count)
  -- pre-aggregated square footage per job (SUM of the job's area rows). Use THIS view for ANY square-footage-by-crew/salesperson/date question. NEVER join v_activities to v_job_areas directly for aggregation — every activity row multiplies by every area row of the same job and inflates SUM/AVG.
  -- v_job_sqft holds ONE row per job, so it must only ever be joined to DISTINCT job_ids. A job with several qualifying activities (repeat install visits) would otherwise be summed once per visit. MANDATORY pattern — use it for EVERY crew-workload question, including plain "how many jobs did crew X install" (the job count and its square footage are always reported together):
  --   SELECT COUNT(*) AS jobs, SUM(s.total_sq_ft) AS sq_ft FROM (SELECT DISTINCT job_id FROM v_activities WHERE <your filters>) d LEFT JOIN v_job_sqft s USING (job_id)
  -- Grouping by crew (or any activity attribute): put that column INSIDE the DISTINCT subquery —
  --   SELECT d.assignees, COUNT(*) AS jobs, SUM(s.total_sq_ft) AS sq_ft FROM (SELECT DISTINCT job_id, assignees FROM v_activities WHERE <filters>) d LEFT JOIN v_job_sqft s USING (job_id) GROUP BY d.assignees
  -- Joining v_job_sqft directly onto v_activities rows, or re-joining v_activities AFTER the DISTINCT subquery, is ALWAYS wrong — both count a job once per visit instead of once. The join must be LEFT JOIN: a few jobs have no area rows, and an inner join would silently drop them from job counts (COUNT(*) counts every job; SUM/AVG correctly skip the NULL sq ft).
v_job_pipeline_status(job_id, job_name, is_quoted boolean, first_signal_date date, last_signal_date date, signal_source, had_dated_quote boolean, had_dated_measure boolean, had_dated_template boolean, moved_forward boolean, first_move_date date, move_is_future boolean, days_silent, status)
  -- THE canonical per-job pipeline answer — one row per job, ALL columns are JOB-LEVEL facts (this view never counts activities/events; "how many times was job X quoted" is an EVENT count and belongs in v_activities).
  -- It has ONLY the columns listed above. For customer, salesperson, or city, JOIN v_jobs USING (job_id) — safe, both are one row per job.
  -- Locked definition: is_quoted = the job has a happened Quote, Measure, or Template (past only — a future-scheduled quote has not been given yet). moved_forward = the job has an Install or Removal with ANY date, past OR future (a booked future install counts; move_is_future flags it). ACTIVITIES ONLY: invoice numbers, paid status, and payment notes count for NOTHING here.
  -- status is EXACTLY one of: not_quoted, moved, pending (quoted, last signal <= 30 days ago, still settling), quiet (quoted, silent > 30 days, never moved). USE status FOR any "went quiet / stalled / no response after quote" question — do not re-derive from raw activities. Report quiet jobs split by v_jobs.status so cancelled jobs are visible.
  -- first_signal_date anchors the COHORT (stable; group trends by it); last_signal_date drives the SILENCE CLOCK (days_silent = as-of minus it; NULL once moved). signal_source = type behind last_signal_date: quote / measure / template.
  -- had_dated_quote / had_dated_measure / had_dated_template = which signal types the job actually has (a happened activity of that type exists). Together they describe the ENTRY PATH: "did this job skip the quote stage?" = is_quoted AND NOT had_dated_quote. These are independent flags, unlike signal_source which only names the LATEST signal.
v_quote_conversion_monthly(quote_month date, quoted_jobs, moved_forward, conversion_pct)
  -- Quote -> moved-forward conversion by monthly cohort, derived from v_job_pipeline_status (definition v4: quoted/moved as defined there; cohort month = month of first_signal_date; a job enters its cohort once 30 days have passed since first_signal_date, or immediately if it moved). Counts are JOB-level. USE THIS VIEW for any conversion / close-rate question — do not re-derive.
  -- An invoice NUMBER on a job does NOT imply the customer moved forward; neither does a payment note. Only a dated Install/Removal counts.
  -- Multi-month/yearly rates: aggregate the COUNTS (SUM(moved_forward)/SUM(quoted_jobs)) — NEVER average conversion_pct across months (unweighted month-averaging is wrong). Always SELECT the two sums alongside the computed rate so the answer can report "X% (M of Q)".
"""

SYSTEM_PROMPT = f"""You translate questions about a countertop fabrication company's data into a single PostgreSQL SELECT statement.

Available views (the ONLY relations you may reference):
{SCHEMA_DDL}
Rules:
- Output ONLY the SQL statement. No prose, no markdown fences, no comments.
- One SELECT statement (CTEs allowed). Never modify data.
- Columns with enumerated values above: match with = or IN against the exact listed values.
- Genuinely free-text columns (job_name, customer, material_name, note, supplier, edge): match with ILIKE '%...%', never equality.
- Kinds of work (quote, template, measure, install, removal, fabrication, repair, tile) are activity types: count/filter them via v_activities.type_name.
- Year filters: use date ranges, e.g. creation_date >= '2025-01-01' AND creation_date < '2026-01-01'.
- If the question is about jobs, prefer counting DISTINCT job_id when joins could duplicate rows.
- Missing text values are EMPTY STRINGS, not NULL: "no X recorded" means (x = '' OR x IS NULL).
- When listing entities, also select COUNT(*) OVER () AS total_count — the forced LIMIT must not hide the true total.
- A job "went quiet" / "stalled after quote" = v_job_pipeline_status.status = 'quiet'. Filter that column; do not re-derive stall logic from raw activities.
- Counting business events: filter WHERE happened (see v_activities three-state rule). Row counts without that filter include placeholders and overstate reality.
- The happened rule is for ACTIVITY rows only. Counting JOBS ("how many jobs did we do in Kiawah Island / in 2024") counts v_jobs rows matching the filters — NEVER add a status or process_name filter unless the question asks about job status (status is a lifecycle field, not an event marker).
- Aggregate answers need their supporting counts: when summing or averaging (sq ft, revenue, rates), also SELECT the underlying count (e.g. COUNT(*) AS jobs alongside SUM(s.total_sq_ft)) in the same query.
- Crew workload/performance questions ("most square footage", "average job size", "jobs completed" by a crew) are about Install activities unless the question names another activity type. A crew's jobs = DISTINCT jobs where it has a happened Install; average job size = AVG(total_sq_ft) over exactly those jobs. Always report a crew's workload as BOTH numbers — use the v_job_sqft pattern selecting COUNT(*) AS jobs and SUM(s.total_sq_ft), even when the question asks for only one of them.
- When ranking or grouping by a text field (salesperson, city, assignees...), exclude blank group keys — add WHERE x <> '' AND x IS NOT NULL — unless the question asks about missing data.
- When aggregating anything per job across a join (sq ft, invoice totals), aggregate per job in a subquery first, then join — never aggregate across a raw many-to-many join.
"""


def generate_sql(question: str, hybrid: bool = False, model: str = None):
    """Ask the SQL model for the SQL. Returns (sql_text, usage).
    `model` overrides SQL_MODEL (used by evals/benchmark_models.py)."""
    client = anthropic.Anthropic()
    prompt = question
    if hybrid:
        prompt += ("\n\n(Return the matching jobs: the SELECT must include "
                   "the job_id column so results can key a second retrieval "
                   "stage.)")
    resp = client.messages.create(
        model=model or SQL_MODEL, max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}])
    sql = next((b.text for b in resp.content if b.type == "text"), "").strip()
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
    """Run validated SQL as rag_reader. Returns (columns, rows, total_count).

    total_count is the TRUE row count with the forced LIMIT stripped —
    computed deterministically here because a truncated list otherwise
    becomes a confidently wrong total ("200 jobs" when 246 match; WO7 Q29).
    Falls back to len(rows) if the count query fails or times out.
    """
    with get_ro_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
        columns = [d.name for d in cur.description]
        rows = cur.fetchall()
        total_count = len(rows)
        try:
            tree = sqlglot.parse_one(sql, dialect="postgres")
            limited = tree.args.pop("limit", None)
            if limited is not None and len(rows) > 0:
                count_sql = (f"SELECT COUNT(*) FROM "
                             f"({tree.sql(dialect='postgres')}) AS _t")
                cur.execute(count_sql)
                total_count = cur.fetchone()[0]
        except Exception:
            pass  # keep the fallback; never fail the lane over the count
    return columns, rows, total_count


def repair_sql(question: str, bad_sql: str, error: str, hybrid: bool,
               model: str = None):
    """One repair attempt: feed the validator error back to the model."""
    client = anthropic.Anthropic()
    prompt = question
    if hybrid:
        prompt += "\n\n(The SELECT must include the job_id column.)"
    resp = client.messages.create(
        model=model or SQL_MODEL, max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": bad_sql},
            {"role": "user", "content":
             f"That SQL was rejected: {error}\nRewrite it. Same rules — "
             f"output only the corrected SQL."},
        ])
    sql = next((b.text for b in resp.content if b.type == "text"), "").strip()
    if sql.startswith("```"):
        sql = sql.strip("`")
        if sql.lower().startswith("sql"):
            sql = sql[3:]
        sql = sql.strip()
    return sql, resp.usage


def run_structured(question: str, hybrid: bool = False,
                   model: str = None) -> dict:
    """Full lane: generate -> validate (with one repair) -> execute.

    Never returns rows without the SQL that produced them. Raises ValueError
    if even the repaired SQL fails validation.
    """
    raw_sql, usage = generate_sql(question, hybrid=hybrid, model=model)
    usages = [usage]
    try:
        safe_sql = validate_sql(raw_sql)
    except ValueError as e:
        raw_sql, usage2 = repair_sql(question, raw_sql, str(e), hybrid,
                                     model=model)
        usages.append(usage2)
        safe_sql = validate_sql(raw_sql)  # second failure propagates
    columns, rows, total_count = execute_sql(safe_sql)
    return {"sql": safe_sql, "columns": columns, "rows": rows,
            "row_count": total_count, "rows_shown": len(rows),
            "usages": usages}

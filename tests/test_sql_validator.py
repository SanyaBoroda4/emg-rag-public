"""WO20: the SQL validator checks columns per alias, not globally.

    python tests/test_sql_validator.py

No LLM, no database: validate_sql is a pure function of the SQL text.
The false-positive guard replays every SQL string recorded in the WO16
final and WO17 single-question runs when those run files are present
(they are private; the public mirror skips that test).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrieval.sql_lane import validate_sql  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RUNS = [ROOT / "evals/results/2026-09-17-0959-wo16-final.json",
        ROOT / "evals/results/2026-09-17-1038-wo17-single.json"]

# Q41 (WO16 final and WO17 single runs): Postgres said
#   UndefinedColumn: column j.customer does not exist
#   LINE 1: SELECT DISTINCT j.job_id, j.job_name, j.customer FROM v_job_...
# The run JSON keeps only that prefix; the alias was on v_job_areas.
Q41_SQL = ("SELECT DISTINCT j.job_id, j.job_name, j.customer FROM v_job_areas AS j "
           "WHERE j.material_name <> '' GROUP BY j.job_id, j.job_name, j.customer "
           "HAVING COUNT(DISTINCT j.material_name) > 1 LIMIT 200")
# WO11 Q26 class: a column that exists on some view selected from one that lacks it
Q26_SQL = ("SELECT job_id, salesperson, city FROM v_job_sqft "
           "WHERE total_sq_ft > 100 ORDER BY total_sq_ft DESC LIMIT 200")


def _rejected(sql):
    try:
        validate_sql(sql)
    except ValueError as e:
        return str(e)
    return None


def test_q41_qualified_column_on_wrong_alias_is_rejected_precisely():
    msg = _rejected(Q41_SQL)
    assert msg, "Q41 SQL must be rejected before it reaches Postgres"
    assert "column `customer` is not in `v_job_areas` (alias `j`)" in msg, msg


def test_q26_class_unqualified_column_on_wrong_view_is_rejected_precisely():
    msg = _rejected(Q26_SQL)
    assert msg, "Q26-class SQL must be rejected before it reaches Postgres"
    assert "column `salesperson` is not in `v_job_sqft`" in msg, msg


def test_same_column_name_on_the_right_alias_passes():
    ok = ("SELECT DISTINCT a.job_id, j.job_name, j.customer FROM v_job_areas AS a "
          "JOIN v_jobs AS j USING (job_id) WHERE a.material_name ILIKE '%quartz%'")
    assert _rejected(ok) is None


def test_ctes_subqueries_and_select_aliases_are_never_rejected():
    cases = [
        # CTE with named projections used through an alias
        "WITH m AS (SELECT job_id, COUNT(DISTINCT material_name) AS n FROM v_job_areas GROUP BY job_id) "
        "SELECT j.job_id, j.job_name, m.n FROM m JOIN v_jobs AS j USING (job_id) WHERE m.n > 1",
        # subquery alias
        "SELECT t.job_id, t.total FROM (SELECT job_id, SUM(sq_ft) AS total FROM v_job_areas GROUP BY job_id) AS t "
        "WHERE t.total > 100 ORDER BY t.total DESC",
        # CTE with SELECT * (unknown projection: must be skipped, not rejected)
        "WITH q AS (SELECT * FROM v_quoted_jobs) SELECT q.salesperson, COUNT(*) AS n FROM q GROUP BY q.salesperson",
        # select-list alias referenced in ORDER BY / HAVING on a single view
        "SELECT salesperson, COUNT(*) AS jobs FROM v_jobs GROUP BY salesperson HAVING COUNT(*) > 5 ORDER BY jobs DESC",
        # unqualified columns across a join (ambiguity is Postgres's call, not ours)
        "SELECT job_id, job_name, material_name FROM v_jobs JOIN v_job_areas USING (job_id) WHERE city = 'Summerville'",
        # correlated subquery referencing the outer alias
        "SELECT j.job_id FROM v_jobs AS j WHERE EXISTS (SELECT 1 FROM v_activities AS a WHERE a.job_id = j.job_id AND a.type_name = 'Install')",
        # date_trunc / EXTRACT and a USING join with the same column on both sides
        "SELECT EXTRACT(YEAR FROM p.first_signal_date) AS yr, COUNT(*) AS n FROM v_job_pipeline_status AS p "
        "JOIN v_jobs AS j USING (job_id) WHERE p.status = 'quiet' GROUP BY yr ORDER BY yr",
        # WO20 run 1, Q73: unqualified columns inside a scalar subquery belong to the
        # subquery's scope, not the outer single-source scope (first validator version
        # rejected these three shapes; that was a false rejection)
        "SELECT s.total_sq_ft, (SELECT COUNT(*) FROM v_activities WHERE job_id = 5637 AND type_name = 'Install' AND happened) AS visits "
        "FROM v_job_sqft AS s WHERE s.job_id = 5637",
        "SELECT total_sq_ft, (SELECT COUNT(*) FROM v_activities a WHERE a.job_id = v_job_sqft.job_id AND type_name = 'Install') AS visits "
        "FROM v_job_sqft WHERE job_id = 5637",
        "SELECT total_sq_ft FROM v_job_sqft WHERE job_id = 5637 AND EXISTS (SELECT 1 FROM v_activities WHERE job_id = 5637 AND type_name = 'Install')",
        "SELECT job_id FROM v_job_sqft WHERE job_id IN (SELECT job_id FROM v_activities WHERE type_name = 'Install' AND happened)",
    ]
    for sql in cases:
        assert _rejected(sql) is None, (sql, _rejected(sql))


def test_every_recorded_run_sql_still_validates():
    """False-positive guard: the SQL the model wrote in two full eval runs
    (all of it executed in Postgres) must still pass."""
    sqls = []
    for p in RUNS:
        if not p.exists():
            continue
        for q in json.load(open(p, encoding="utf-8"))["questions"]:
            s = (q.get("generation") or {}).get("sql")
            if s:
                sqls.append((p.name, q["id"], s))
    if not sqls:
        print("  (run files absent: false-positive guard skipped)")
        return
    bad = [(f, i, _rejected(s)) for f, i, s in sqls if _rejected(s)]
    assert not bad, bad
    print(f"  {len(sqls)} recorded SQL strings accepted")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"{len(fns)} tests passed")

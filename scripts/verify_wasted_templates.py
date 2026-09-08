"""Wasted-template gate (WO8).

The rule behind v_wasted_templates (sql/014) was reverse-engineered from ten
jobs Alex judged by hand. This script asserts every one of those verdicts
exactly, plus the two structural edge cases (680: undated placeholder must
not count; 772: a 2023 template is its own phase). Exit non-zero on ANY
mismatch. If a verdict cannot be reproduced that is a finding for Alex, not
something to paper over by bending the rule.

Then it prints the report the WO asks for: totals, by year, by salesperson
(the headline), by reason, every matched note (deduplicated, with counts -
for Alex to prune), the 15 most recent wasted templates with Moraware links,
and a PHASE_GAP_DAYS sensitivity run at 21 / 30 / 45 days (the view body is
re-executed as a subquery with the constant substituted; the view itself is
not touched).

Read-only. Logs one pipeline_runs row.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.db import get_conn

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "014_wasted_templates.sql"
JOB_URL = "https://granite-marble-tops.moraware.net/sys/job/{}"

# job -> (expected wasted?, signal that MUST have fired, Alex's words)
EXPECTED = {
    478:  (True,  "note",       "vanity not installed - count as wasted"),
    852:  (True,  "structural", "no note, two templates one phase, one install"),
    1084: (True,  "structural", "one install confirms"),
    1422: (False, None,         "two phases, gap too big"),
    1681: (False, None,         "same"),
    2216: (False, None,         "no note, nothing wrong"),
    3117: (False, None,         "T-I-T-I, perfect sequence (negative trap)"),
    4743: (True,  "note",       "cabinets redone"),
    5015: (True,  "note",       "note"),
    5491: (True,  "note",       "retemplate, one install"),
    680:  (False, None,         "second template is an undated Estimate (Step 0)"),
}
GAPS = (21, 30, 45)


def fetch_rows(cur, job_ids):
    cur.execute("""
        SELECT job_id, template_activity_id, template_date, phase_no,
               templates_in_phase, installs_in_phase, next_template_date,
               install_between, structural_wasted, note_wasted, wasted,
               wasted_reason, note_source, matched_note
        FROM v_wasted_templates WHERE job_id = ANY(%s)
        ORDER BY job_id, template_date, template_activity_id""",
                (list(job_ids),))
    by_job = {}
    for r in cur.fetchall():
        by_job.setdefault(r[0], []).append(r)
    return by_job


def one_line(text, n=90):
    return re.sub(r"\s*[\r\n]+\s*", " | ", (text or "").strip())[:n]


def gate(cur) -> bool:
    print("=== GATE: Alex's hand-verified jobs ===")
    rows = fetch_rows(cur, list(EXPECTED) + [772])
    failed = False
    for job, (exp_wasted, signal, words) in EXPECTED.items():
        jrows = rows.get(job, [])
        wasted_rows = [r for r in jrows if r[10]]
        problems = []
        if not jrows:
            problems.append("no real template rows at all")
        if exp_wasted:
            if len(wasted_rows) != 1:
                problems.append(f"expected exactly 1 wasted template, "
                                f"got {len(wasted_rows)}")
            if wasted_rows:
                r = wasted_rows[0]
                fired = r[8] if signal == "structural" else r[9]
                if not fired:
                    problems.append(f"{signal} signal did not fire "
                                    f"(reason={r[11]})")
        elif wasted_rows:
            problems.append(f"expected NOT wasted, got {len(wasted_rows)} "
                            f"wasted row(s): "
                            + ", ".join(f"{r[2]} {r[11]}" for r in wasted_rows))
        status = "OK" if not problems else "** MISMATCH **"
        failed |= bool(problems)
        got = (", ".join(f"{r[2]} {r[11]}" for r in wasted_rows)
               or "not wasted")
        exp = f"wasted/{signal}" if exp_wasted else "not wasted"
        print(f"job {job:>5}: expected {exp:<18} got {got:<28} {status}"
              f"   [{words}]")
        for p in problems:
            print(f"           -> {p}")

    # 772: 2023 window-seal template must be phase 2; report the 2020 pair
    jrows = rows.get(772, [])
    p2 = [r for r in jrows if str(r[2]).startswith("2023")]
    p1 = [r for r in jrows if str(r[2]).startswith("2020")]
    ok = (len(p2) == 1 and p2[0][3] == 2 and p2[0][4] == 1
          and len(p1) == 2 and all(r[3] == 1 for r in p1))
    failed |= not ok
    print(f"job   772: 2023-07-07 template is phase {p2[0][3] if p2 else '?'} "
          f"alone, 2020 pair is phase 1 {'OK' if ok else '** MISMATCH **'}")
    for r in p1:
        print(f"           2020 pair: {r[2]} structural_wasted={r[8]} "
              f"reason={r[11]}  (Alex expects Oct 14 wasted)")
    oct14 = [r for r in p1 if str(r[2]) == "2020-10-14"]
    if not (oct14 and oct14[0][8]):
        failed = True
        print("           -> ** MISMATCH ** Oct 14 2020 not structurally wasted")

    print("\n--- full detail, all 12 jobs ---")
    print(f"{'job':>5} {'date':<11} {'ph':>2} {'t/ph':>4} {'i/ph':>4} "
          f"{'next_t':<11} {'ib':<5} {'sw':<5} {'nw':<5} {'reason':<10} "
          f"{'src':<13} note")
    for job in sorted(rows):
        for r in rows[job]:
            print(f"{r[0]:>5} {str(r[2]):<11} {r[3]:>2} {r[4]:>4} {r[5]:>4} "
                  f"{str(r[6] or ''):<11} {str(r[7]):<5} {str(r[8]):<5} "
                  f"{str(r[9]):<5} {str(r[11] or ''):<10} "
                  f"{str(r[12] or ''):<13} {one_line(r[13], 60)}")
    print("\nGATE:", "FAIL" if failed else "PASS")
    return not failed


def report(cur):
    print("\n=== REPORT ===")
    cur.execute("SELECT COUNT(*), COUNT(*) FILTER (WHERE wasted) "
                "FROM v_wasted_templates")
    total, wasted = cur.fetchone()
    print(f"real templates: {total}   wasted: {wasted}   "
          f"wasted %: {100.0 * wasted / total:.1f}")

    print("\n--- by year ---")
    cur.execute("""
        SELECT template_year, COUNT(*), COUNT(*) FILTER (WHERE wasted),
               ROUND(100.0 * COUNT(*) FILTER (WHERE wasted) / COUNT(*), 1)
        FROM v_wasted_templates GROUP BY 1 ORDER BY 1""")
    print(f"{'year':<6}{'real':>7}{'wasted':>8}{'pct':>7}")
    for y, n, w, p in cur.fetchall():
        print(f"{y:<6}{n:>7}{w:>8}{p:>7}")

    print("\n--- by salesperson (headline) ---")
    cur.execute("""
        SELECT salesperson, SUM(real_templates), SUM(wasted_templates),
               ROUND(100.0 * SUM(wasted_templates) / SUM(real_templates), 1)
        FROM v_wasted_templates_by_pm GROUP BY 1 ORDER BY 3 DESC, 2 DESC""")
    print(f"{'salesperson':<20}{'real':>7}{'wasted':>8}{'pct':>7}")
    for s, n, w, p in cur.fetchall():
        print(f"{(s or '(blank)'):<20}{n:>7}{w:>8}{p:>7}")

    print("\n--- by reason ---")
    cur.execute("""
        SELECT wasted_reason, COUNT(*) FROM v_wasted_templates
        WHERE wasted GROUP BY 1 ORDER BY 2 DESC""")
    for reason, n in cur.fetchall():
        print(f"  {reason:<12}{n:>6}")

    cur.execute("""
        SELECT COUNT(*) FILTER (WHERE next_template_date = template_date),
               COUNT(*) FILTER (WHERE next_template_date = template_date
                                  AND structural_wasted)
        FROM v_wasted_templates""")
    same, same_flagged = cur.fetchone()
    print(f"\nsame-day template pairs (two real Template rows on one date): "
          f"{same}, of which flagged structural: {same_flagged}  "
          f"<- decision for Alex: one trip or two?")

    print("\n--- every matched note (deduplicated) - for Alex to prune ---")
    cur.execute("""
        SELECT note_source, matched_note, COUNT(*),
               string_agg(job_id::text, ',' ORDER BY job_id)
        FROM v_wasted_templates WHERE note_wasted
        GROUP BY 1, 2 ORDER BY 1, 3 DESC, 2""")
    notes = cur.fetchall()
    print(f"({len(notes)} distinct notes)")
    for src, note, n, jobs in notes:
        print(f"  [{src:<13}] x{n}  jobs {jobs}\n      {one_line(note, 150)}")

    print("\n--- 15 most recent wasted templates ---")
    cur.execute("""
        SELECT job_id, job_name, salesperson, template_date, wasted_reason,
               matched_note
        FROM v_wasted_templates WHERE wasted
        ORDER BY template_date DESC, job_id DESC LIMIT 15""")
    for job, name, sp, d, reason, note in cur.fetchall():
        print(f"  {d} job {job} {name[:32]!r:<35} PM={sp or '(blank)':<18} "
              f"{reason:<10} {JOB_URL.format(job)}")
        if note:
            print(f"      note: {one_line(note, 110)}")


def sensitivity(cur):
    print("\n=== SENSITIVITY: PHASE_GAP_DAYS ===")
    text = SQL_FILE.read_text(encoding="utf-8")
    marker = "CREATE VIEW v_wasted_templates AS\n"
    start = text.index(marker) + len(marker)
    body = text[start:text.index(";\n", start)]
    assert body.count("SELECT 30 AS phase_gap_days") == 1, \
        "expected exactly one PHASE_GAP_DAYS constant in the view body"
    results = {}
    for gap in GAPS:
        q = body.replace("SELECT 30 AS phase_gap_days",
                         f"SELECT {gap} AS phase_gap_days")
        cur.execute(f"""
            SELECT COUNT(*), COUNT(*) FILTER (WHERE wasted),
                   COUNT(*) FILTER (WHERE structural_wasted),
                   COUNT(*) FILTER (WHERE note_wasted),
                   array_agg(template_activity_id) FILTER (WHERE wasted),
                   MAX(phase_no)
            FROM ({q}) t""")
        n, w, s, nn, ids, maxph = cur.fetchone()
        results[gap] = (n, w, s, nn, set(ids or []), maxph)
    print(f"{'gap':>4}{'real':>7}{'wasted':>8}{'pct':>7}{'struct':>8}"
          f"{'note':>6}{'max_phase':>10}")
    for gap in GAPS:
        n, w, s, nn, _, maxph = results[gap]
        print(f"{gap:>4}{n:>7}{w:>8}{100.0 * w / n:>7.1f}{s:>8}{nn:>6}"
              f"{maxph:>10}")
    base = results[30][4]
    for gap in (21, 45):
        other = results[gap][4]
        gained, lost = other - base, base - other
        print(f"\n{gap} vs 30: +{len(gained)} newly wasted, -{len(lost)} no "
              f"longer wasted (net {len(other) - len(base):+d})")
        moved = gained | lost
        if moved:
            cur.execute("""
                SELECT DISTINCT job_id FROM v_wasted_templates
                WHERE template_activity_id = ANY(%s) ORDER BY 1""",
                        (list(moved),))
            jobs = [r[0] for r in cur.fetchall()]
            print(f"   boundary jobs ({len(jobs)}): "
                  + ", ".join(str(j) for j in jobs[:40])
                  + (" ..." if len(jobs) > 40 else ""))


def main() -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO pipeline_runs (source, status) "
                    "VALUES ('verify_wasted_templates', 'running') "
                    "RETURNING run_id")
        run_id = cur.fetchone()[0]
        conn.commit()
        try:
            ok = gate(cur)
            report(cur)
            sensitivity(cur)
            cur.execute("SELECT COUNT(*), COUNT(*) FILTER (WHERE wasted) "
                        "FROM v_wasted_templates")
            n, w = cur.fetchone()
            cur.execute("UPDATE pipeline_runs SET finished_at = now(), "
                        "status = %s, rows_in = %s, rows_out = %s, "
                        "note = %s WHERE run_id = %s",
                        ("ok" if ok else "gate_failed", n, w,
                         "gate PASS" if ok else "gate FAIL", run_id))
            conn.commit()
        except Exception as e:
            cur.execute("UPDATE pipeline_runs SET finished_at = now(), "
                        "status = 'error', error = %s WHERE run_id = %s",
                        (str(e)[:500], run_id))
            conn.commit()
            raise
    print("\nOK" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

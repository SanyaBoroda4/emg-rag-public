"""WO19: the public-mirror guard rejects planted PII and the transform removes
it. Self-contained: builds its own fake term lists (no private/ files, no
database), so it runs in CI.

    python tests/test_public_guard.py
"""
import hashlib, json, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import public_scan as ps  # noqa: E402
import public_transform as pt  # noqa: E402

FAKE_NOTE = "the island slab would not fit through the stairwell so we cut it on site at the seam"


def fake_terms(tmp: Path):
    terms = {
        "customers_full": ["quackenbush zebulon", "zebulon quackenbush", "acme granite partners llc"],
        "customer_tokens": ["quackenbush", "zebulon"],
        "phones": ["8435550123"], "emails": ["zeb@example-customer.test"],
        "addresses": ["1234 imaginary lane"],
        "employees": {"pat fakesmith": "Salesperson A", "rowan": "Crew A"},
        "employee_first": {"pat": "Salesperson A", "rowan": "Crew A"},
        "customer_job": {"zebulon quackenbush": 4242, "quackenbush zebulon": 4242},
    }
    (tmp / "terms.json").write_text(json.dumps(terms), encoding="utf-8")
    w = re.findall(r"[a-z0-9]+", FAKE_NOTE)
    sh = [hashlib.sha1(" ".join(w[i:i + 8]).encode()).hexdigest()[:10] for i in range(len(w) - 7)]
    (tmp / "shingles.txt").write_text("\n".join(sh) + "\n", encoding="utf-8")
    return ps.Terms(tmp / "terms.json", tmp / "shingles.txt", tmp / "no_exclusions.json")


# the fake secrets are assembled at runtime so this source file never matches the guard itself
FAKE_KEY = "sk-ant-" + "api03-FAKEFAKEFAKEFAKE"
FAKE_URL = "postgres://" + "u:secret@host/db"
FAKE_IP = ".".join(["178", "156", "252", "166"])
FAKE_AMOUNT = "$" + "12,45" + "0.00"   # assembled so the public copy of this file keeps the literal intact
PLANTED = f"""# planted report
Job 4242 for Zebulon Quackenbush at 1234 Imaginary Lane, call (843) 555-0123 or zeb@example-customer.test.
Salesperson Pat Fakesmith quoted {FAKE_AMOUNT}; Rowan installed it. API cost $0.0192.
Note: {FAKE_NOTE}.
Server {FAKE_IP}. ANTHROPIC key {FAKE_KEY} and {FAKE_URL}
"""
QUOTED_SQL = "SELECT * FROM v_jobs WHERE job_name ILIKE '%quackenbush%' AND salesperson ILIKE '%pat fakesmith%'"
CLEAN = """# clean report
82 questions, 76 passed, mean latency 4.2 s, cost $0.0192 per question. Job 4242 chunk 4075.
Salesperson A quoted Customer #4242; the crew installed it in Mount Pleasant.
"""


def test_guard_flags_planted_and_passes_clean():
    with tempfile.TemporaryDirectory() as d:
        T = fake_terms(Path(d))
        h = ps.scan_text(PLANTED, T)
        for cat in ("customer_name", "customer_token", "address", "phone", "email", "note_text", "employee", "dollar",
                    "server_ip", "secret:anthropic_key", "secret:postgres_url_with_password"):
            assert cat in h, f"planted {cat} not detected: {sorted(h)}"
        assert h["note_text"][0] >= 3
        clean = ps.scan_text(CLEAN, T)
        assert not any(c in clean for c in ps.GUARDED), clean
        assert "dollar" not in clean, "an API cost below 100 USD must not count as a data dollar figure"


def test_transform_removes_everything_the_guard_flags():
    with tempfile.TemporaryDirectory() as d:
        T = fake_terms(Path(d))
        out = pt.Transformer(T).text(PLANTED)
        out, n = ps.redact_notes(out, T.shingles)
        assert n >= 3
        assert "Customer #4242" in out and "Salesperson A" in out and "Crew A" in out
        assert "[redacted]" in out and "$[redacted]" in out and "[note text]" in out and "SERVER_IP_REDACTED" in out
        assert "$0.0192" in out, "API costs are kept"
        for leaked in ("Quackenbush", "Zebulon", "Imaginary", "555-0123", "example-customer", "Fakesmith", "Rowan", "12,450"):
            assert leaked not in out, f"{leaked} survived the transform"
        h = ps.scan_text(out, T)
        assert not any(c in h for c in ps.GUARDED), h
        assert "employee" not in h and "dollar" not in h and "server_ip" not in h


def test_quoted_sql_literals_are_caught_and_rewritten():
    with tempfile.TemporaryDirectory() as d:
        T = fake_terms(Path(d))
        h = ps.scan_text(QUOTED_SQL, T)
        assert "customer_token" in h and "employee" in h, h
        out = pt.Transformer(T).text(QUOTED_SQL)
        assert "quackenbush" not in out.lower() and "fakesmith" not in out.lower(), out
        assert "'%[customer]%'" in out and "Salesperson A" in out, out
        assert not ps.scan_text(out, T)


def test_two_decimal_money_without_a_sign_is_redacted_but_not_metrics():
    """WO20: a rows-table cell or answer echo (seven digits, two decimals) is money;
    latencies, API costs, percentages, counts and versions are not."""
    with tempfile.TemporaryDirectory() as d:
        T = fake_terms(Path(d))
        # amounts assembled at runtime so the public copy of this file keeps them literal
        a, b, c = "3612905" + ".10", "5200113" + ".02", "1,250" + ".00"
        money = f"| 2024-01-01 | 1598 | {a} |\nThe total was {b} across 1,598 invoices; {c} in fees."
        h = ps.scan_text(money, T)
        assert "dollar_nosign" in h and len(h["dollar_nosign"]) == 2, h
        out = pt.Transformer(T).text(money)
        assert out.count("$[redacted]") == 3, out
        for kept in ("1598", "1,598"):
            assert kept in out
        not_money = ("latency 2.40 s, p95 12.30 s, mean 99.99 s; cost $0.0079 and $1.04; 70.0% and 63.42 % and 100.00%; "
                     "sqlglot 0.28.1 and 30.14.0; 82 questions; chunk 4075; 2026-09-21; 09:12:00.12; recall 0.818; job 4242.")
        assert "dollar_nosign" not in ps.scan_text(not_money, T), ps.scan_text(not_money, T)
        assert pt.Transformer(T).text(not_money) == not_money


def test_real_employee_names_switch():
    with tempfile.TemporaryDirectory() as d:
        T = fake_terms(Path(d))
        out = pt.Transformer(T, employee_mode="real").text("Pat Fakesmith and Rowan")
        assert "Pat Fakesmith" in out and "Rowan" in out


def test_sync_script_guard_exits_nonzero_on_planted_file():
    """scripts/public_scan.py as the sync script calls it: exit 1 on a tree
    with a planted file, 0 on a clean one."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d); T = fake_terms(d)
        (d / "tree").mkdir(); (d / "tree" / "report.md").write_text(PLANTED, encoding="utf-8")
        (d / "clean").mkdir(); (d / "clean" / "report.md").write_text(CLEAN, encoding="utf-8")
        env = {"PII_TERMS": str(d / "terms.json"), "PII_SHINGLES": str(d / "shingles.txt"), "PII_EXCLUSIONS": str(d / "none.json")}
        import os
        env = {**os.environ, **env}
        r = subprocess.run([sys.executable, str(ROOT / "scripts/public_scan.py"), "tree", str(d / "tree"), "--quiet"], env=env)
        assert r.returncode == 1
        r = subprocess.run([sys.executable, str(ROOT / "scripts/public_scan.py"), "tree", str(d / "clean"), "--quiet"], env=env)
        assert r.returncode == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)

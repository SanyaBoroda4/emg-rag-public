"""WO19 term-list builder: run ON THE SERVER, stdout is the private term file.

    ssh root@SERVER 'cd /opt/emg-rag && .venv/bin/python -' < scripts/build_pii_terms.py > private/pii_terms.json

Prints ONE JSON document and nothing else; the caller redirects it straight into
the gitignored private/ directory. Never print, log or commit its output. The
only thing safe to show is d["meta"] (counts).

Read-only: rag_reader for the views; the owner role in a read-only transaction
for the tables no view exposes (job_contacts, jobs.addr_raw, invoices.bill_email).
"""
import json, re, os, sys, glob
from ingest.db import get_ro_conn, get_conn

def norm(s):
    s = re.sub(r"[^\w\s'&-]", " ", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()

def tokens(s):
    return [t for t in re.split(r"[^a-z]+", norm(s)) if t]

# ---------- stoplist for single-token customer names: code vocabulary + cities + materials
stop = set()
for pat in ("retrieval/*.py", "ingest/*.py", "serve/*.py", "serve/static/*.html", "sql/*.sql",
            "scripts/*", "tests/*.py", "evals/*.py", "CLAUDE.md", "README.md", "requirements*.txt",
            "deploy/*", ".github/workflows/*", "docker-compose.yml"):
    for f in glob.glob(os.path.join("/opt/emg-rag", pat)):
        try:
            stop.update(t for t in re.findall(r"[a-z]{3,}", open(f, encoding="utf-8", errors="ignore").read().lower()))
        except Exception:
            pass

customers_full, customer_tokens = set(), set()
sales, assignees = set(), set()
with get_ro_conn() as c, c.cursor() as cur:
    cur.execute("SELECT job_name, MIN(job_id) FROM v_jobs WHERE job_name IS NOT NULL GROUP BY job_name")
    rows = cur.fetchall()
    job_names = [r[0] for r in rows]
    customer_job = {}
    for name, jid in rows:
        n = norm(name)
        if n: customer_job[re.sub(r"\s*,\s*", " ", n)] = jid
        if "," in name:
            a, b = [norm(x) for x in name.split(",", 1)]
            if a and b: customer_job[f"{b} {a}"] = jid
    cur.execute("SELECT DISTINCT customer FROM v_jobs WHERE customer IS NOT NULL")
    accounts = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT customer_name FROM v_invoices WHERE customer_name IS NOT NULL")
    inv_names = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT salesperson FROM v_jobs WHERE salesperson IS NOT NULL AND salesperson <> ''")
    sales = {norm(r[0]) for r in cur.fetchall()}
    cur.execute("SELECT DISTINCT assignees FROM v_activities WHERE assignees IS NOT NULL")
    for (a,) in cur.fetchall():
        for part in a.split(","):
            if norm(part): assignees.add(norm(part))
    cur.execute("SELECT DISTINCT city FROM v_jobs WHERE city IS NOT NULL UNION SELECT DISTINCT city_raw FROM v_jobs WHERE city_raw IS NOT NULL")
    for (city,) in cur.fetchall(): stop.update(tokens(city))
    cur.execute("SELECT DISTINCT material_name FROM v_job_areas WHERE material_name IS NOT NULL UNION SELECT DISTINCT supplier FROM v_job_areas WHERE supplier IS NOT NULL")
    for (m,) in cur.fetchall(): stop.update(tokens(m))

employees = sales | assignees
for name in job_names + accounts + inv_names:
    n = norm(name)
    if not n or n in employees: continue
    # "last, first" -> also "first last"
    forms = {n}
    if "," in (name or ""):
        a, b = [norm(x) for x in name.split(",", 1)]
        if a and b: forms.add(f"{b} {a}")
    forms = {re.sub(r"\s*,\s*", " ", f) for f in forms}
    if any(len(tokens(f)) >= 2 for f in forms):
        customers_full.update(forms)
    for t in tokens(n):
        if len(t) >= 5 and t not in stop and not t.isdigit():
            customer_tokens.add(t)

# contacts: owner role, read-only transaction (no view exposes job_contacts or addr_raw)
phones, emails, addresses = set(), set(), set()
with get_conn(options="-c default_transaction_read_only=on") as c, c.cursor() as cur:
    cur.execute("SELECT name, phone, cell, email FROM job_contacts")
    for name, phone, cell, email in cur.fetchall():
        n = norm(name)
        if n and n not in employees and len(tokens(n)) >= 2: customers_full.add(n)
        for p in (phone, cell):
            d = re.sub(r"\D", "", p or "")
            if len(d) >= 7: phones.add(d[-10:] if len(d) >= 10 else d)
        if email and "@" in email: emails.add(email.strip().lower())
    cur.execute("SELECT DISTINCT addr_raw FROM jobs WHERE addr_raw IS NOT NULL AND addr_raw <> ''")
    for (a,) in cur.fetchall():
        first = norm(a.split("\n")[0].split(",")[0])
        if re.match(r"^\d+\s+\S+", first) and len(first) >= 8: addresses.add(first)
    cur.execute("SELECT DISTINCT bill_email FROM invoices WHERE bill_email IS NOT NULL AND bill_email LIKE '%@%'")
    for (e,) in cur.fetchall(): emails.add(e.strip().lower())

# employees -> pseudonyms, by primary role, alphabetical for determinism
def label(i):
    s = ""
    i += 1
    while i: i, r = divmod(i - 1, 26); s = chr(65 + r) + s
    return s
emap = {}
for i, n in enumerate(sorted(sales)): emap[n] = f"Salesperson {label(i)}"
for i, n in enumerate(sorted(assignees - sales)): emap[n] = f"Crew {label(i)}"
firsts, ambiguous = {}, set()
for n, p in emap.items():
    f = tokens(n)[0] if tokens(n) else ""
    if len(f) < 3 or f in stop: continue
    if f in firsts and firsts[f] != p: ambiguous.add(f)
    firsts.setdefault(f, p)
author_first_is_employee = "alex" in firsts

json.dump({
    "customers_full": sorted(customers_full),
    "customer_tokens": sorted(customer_tokens),
    "phones": sorted(phones), "emails": sorted(emails), "addresses": sorted(addresses),
    "employees": emap, "employee_first": firsts, "customer_job": customer_job,
    "meta": {"n_customers_full": len(customers_full), "n_customer_tokens": len(customer_tokens),
             "n_phones": len(phones), "n_emails": len(emails), "n_addresses": len(addresses),
             "n_employees": len(emap), "n_sales": len(sales), "n_crew": len(assignees - sales),
             "n_first_ambiguous": len(ambiguous), "author_first_is_employee": author_first_is_employee,
             "n_stop": len(stop)},
}, sys.stdout)

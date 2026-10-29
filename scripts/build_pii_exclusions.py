"""WO19: build private/exclusions.json from the private term lists without
printing a term. Run locally after build_pii_terms.py:

    python scripts/build_pii_exclusions.py [term-index ...]

Excludes (1) single customer tokens that are common English words
(scripts/pii_common_words.txt, set intersection), (2) tokens that occur in
the font licence text, (3) employee entries that are generic assignee labels,
(4) explicit term indexes taken from `public_scan.py --diag` output. Prints
counts only.
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
common = set(re.findall(r"[a-z']+", (ROOT / "scripts" / "pii_common_words.txt").read_text(encoding="utf-8").lower()))
generic_assignee = {"shop", "office", "test", "none", "null", "crew", "team", "any", "sub", "install", "installer",
                    "template", "templater", "fab", "fabrication", "unassigned", "other", "admin", "user", "demo", "sample",
                    "vendor", "misc", "staff", "temp", "tbd", "todo", "open", "main", "self", "home", "work", "note",
                    "data", "name", "time", "date", "type", "size", "file", "list", "page", "item", "task", "job", "jobs",
                    "sale", "sales", "rep", "lead", "tech", "help", "plan", "form", "area", "line", "load", "save", "read",
                    "base", "code", "path", "root", "host", "port", "text", "char", "word", "true", "done", "fail", "pass",
                    "mock", "json", "html", "sink", "slab", "seam", "cut", "cnc", "saw", "delivery", "pickup", "measure",
                    "service", "repair", "warranty", "estimate", "quote", "office staff", "shop crew", "install crew",
                    "not assigned", "no one", "nobody", "everyone", "all", "each", "both", "same", "next", "last", "first",
                    "emg", "emg office", "emg shop", "emg crew", "emg install", "emg template", "subcontractor", "sub crew",
                    "contractor", "customer", "client", "builder", "plumber", "electrician", "designer", "sales rep"}
lic_path = ROOT / "serve" / "static" / "fonts" / "LICENSE.txt"
lic = {w.lower() for w in re.findall(r"[A-Za-z]{5,}", lic_path.read_text(encoding="utf-8"))} if lic_path.exists() else set()
idx_excl = {int(x) for x in sys.argv[1:]}
# words used by the repo's own code (string literals included) are code vocabulary, not customers;
# data fixtures and the rewrite test are left out because they quote real questions
code_vocab = set()
for pat in ("retrieval/*.py", "ingest/*.py", "serve/*.py", "serve/static/*.html", "sql/*.sql", "scripts/*.py",
            "scripts/*.sh", "tests/test_public_guard.py", "evals/*.py", ".github/workflows/*.yml", "docker-compose.yml"):
    for f in ROOT.glob(pat):
        code_vocab.update(re.findall(r"[a-z]{5,}", f.read_text(encoding="utf-8", errors="ignore").lower()))

d = json.load(open(ROOT / "private" / "pii_terms.json", encoding="utf-8"))
allterms = sorted(set(d["customers_full"]) | set(d["customer_tokens"]) | set(d["addresses"]) | set(d["employees"]) | set(d["employee_first"]))
by_idx = dict(enumerate(allterms))
excl, n = set(), {"customer_tokens_common": 0, "customer_tokens_licence": 0, "customer_tokens_code": 0, "employee_generic": 0, "by_index": 0}
for t in d["customer_tokens"]:
    if t in common: excl.add(t); n["customer_tokens_common"] += 1
    elif t in lic: excl.add(t); n["customer_tokens_licence"] += 1
    elif t in code_vocab: excl.add(t); n["customer_tokens_code"] += 1
for k in list(d["employees"]) + list(d["employee_first"]):
    if k in generic_assignee or k in common: excl.add(k); n["employee_generic"] += 1
for i in idx_excl:
    if i in by_idx: excl.add(by_idx[i]); n["by_index"] += 1
json.dump({"terms": sorted(excl)}, open(ROOT / "private" / "exclusions.json", "w", encoding="utf-8"))
print(json.dumps({"excluded_total": len(excl), **n, "idx_len": {str(i): len(by_idx[i]) for i in idx_excl if i in by_idx}}))

"""WO19: scan files for customer PII, employee names, note text, dollar
figures and secrets before anything reaches the public mirror.

    python scripts/public_scan.py tree  <dir> [--tracked]   # a checkout (tracked files only with --tracked)
    python scripts/public_scan.py blobs <git-dir>            # every blob in that repo's history
    python scripts/public_scan.py --json out.json ...        # machine-readable, counts + line numbers only
    python scripts/public_scan.py --diag ...                 # per-term file counts by index, never the term

Term lists come from private/pii_terms.json and private/shingles.txt
(gitignored; built on the server by the WO19 term builder). The output never
contains a matched term: only file, category, count and line numbers.

Matching rules (deliberate):
  * multi-token customer names and street addresses: case-insensitive, tokens
    in order separated by any non-word run;
  * single customer-name tokens: Title Case anywhere (a surname in a report is
    capitalised; the same letters lower-case are code), plus any case inside a
    quoted string literal (SQL '%name%' in a report);
  * employee names: case-insensitive when multi-token or >= 5 chars, Title
    Case only for short single names;
  * phones by digits (last 10), emails exact, note text by 8-word shingle
    hashes (>= 3 hits in a file), dollar figures of 100 USD and up, secrets by pattern.

Exit status: 0 when nothing is found in the guarded categories (customer,
contact, note text, secret), 1 otherwise. Employee names and dollar figures are
reported but do not fail the scan (the transform handles them); pass --strict
to fail on those too.
"""
import argparse, hashlib, json, os, re, subprocess, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BINARY = {".woff2", ".jpg", ".jpeg", ".png", ".gif", ".pdf", ".pyc", ".ico"}
SECRET_PATTERNS = {
    "anthropic_key": re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    "voyage_key": re.compile(r"\bpa-[A-Za-z0-9_-]{24,}"),
    "langfuse_key": re.compile(r"\b[sp]k-lf-[A-Za-z0-9-]{8,}"),
    "postgres_url_with_password": re.compile(r"postgres(?:ql)?://[^:/\s]+:[^@\s]+@"),
    "bcrypt_hash": re.compile(r"\$2[ab]\$\d\d\$[./A-Za-z0-9]{20,}"),
    # a literal value only: not os.environ[...], not ${VAR}, not a placeholder, at least 8 secret-looking chars
    "password_assignment": re.compile(r"PASSWORD\s*=\s*['\"]?(?!os\.|environ|\$|<|\{|None|your|change|xxx|example)[A-Za-z0-9!@#%^&*_+=/.-]{8,}", re.I),
}
DOLLAR = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
# WO20: money written without a dollar sign — a rows-table cell or an answer
# echo (a seven-digit figure with two decimals) — is a number with EXACTLY
# two decimals and a value of 100 or more. Not: latencies (2.40 s: below
# 100), API costs (have a sign), percentages (the % lookahead), counts (no
# decimals), versions (0.28.1: a third component follows), nor the tail of a
# signed amount after a thousands comma (the digit-comma lookbehind).
MONEY_NO_SIGN = re.compile(r"(?<!\d,)(?<![\w.$-])(\d{1,3}(?:,\d{3})+|\d+)\.(\d{2})(?![\d.%]|\s?%)")


def money_no_sign_hits(line):
    return [m for m in MONEY_NO_SIGN.finditer(line)
            if int(m.group(1).replace(",", "")) >= 100]
IP = re.compile(r"\b178\.156\.252\.166\b")
WORD = re.compile(r"[a-z0-9']+")
TITLE = re.compile(r"(?<![A-Za-z0-9])[A-Z][a-z]{2,}(?![A-Za-z0-9])")
GUARDED = ("customer_name", "customer_token", "address", "email", "phone", "note_text")


def title(phrase):
    return " ".join(w[:1].upper() + w[1:] for w in phrase.split())


def _english_words():
    p = ROOT / "scripts" / "pii_common_words.txt"
    return set(re.findall(r"[a-z']+", p.read_text(encoding="utf-8").lower())) if p.exists() else set()


ENGLISH = _english_words()


def employee_regex(name):
    # multi-token, or a single name of >= 5 letters that is not an English word: any case;
    # short names and names that are also English words: Title Case only
    loose = " " in name or (len(name) >= 5 and name not in ENGLISH)
    body = r"\W+".join(map(re.escape, (name if loose else title(name)).split()))
    return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", re.I if loose else 0)


QUOTED = re.compile(r"'([^']*)'|\"([^\"]*)\"")


def customer_token_hits(line, tokens):
    """Single customer-name tokens: Title Case anywhere, or any case inside a
    quoted string literal (SQL '%name%' in a report)."""
    found = {w.lower() for w in TITLE.findall(line)} & tokens
    for m in QUOTED.finditer(line):
        found |= set(WORD.findall((m.group(1) or m.group(2) or "").lower())) & tokens
    return found


class PhraseIndex:
    """Phrases (lower-case, space-separated tokens) indexed by their rarest
    token; a line is only regex-tested against phrases whose every token it
    contains. Regexes are built lazily and cached."""

    def __init__(self, phrases, flags=re.I):
        self.flags = flags
        toks = {p: tuple(WORD.findall(p)) for p in phrases if WORD.findall(p)}
        freq = Counter(t for ts in toks.values() for t in set(ts))
        self.index = defaultdict(list)
        for p, ts in toks.items():
            self.index[min(set(ts), key=lambda t: (freq[t], t))].append((p, frozenset(ts)))
        self._rx = {}

    def rx(self, p):
        if p not in self._rx:
            self._rx[p] = re.compile(r"(?<![A-Za-z0-9])" + r"\W+".join(map(re.escape, p.split())) + r"(?![A-Za-z0-9])", self.flags)
        return self._rx[p]

    def find(self, line, line_tokens):
        for t in line_tokens:
            for p, ts in self.index.get(t, ()):
                if ts <= line_tokens and self.rx(p).search(line):
                    yield p


class Terms:
    def __init__(self, path=None, shingles=None, exclusions=None):
        # env overrides let the unit test point the guard at fake lists
        path = Path(path or os.environ.get("PII_TERMS") or ROOT / "private" / "pii_terms.json")
        shingles = Path(shingles or os.environ.get("PII_SHINGLES") or ROOT / "private" / "shingles.txt")
        exclusions = Path(exclusions or os.environ.get("PII_EXCLUSIONS") or ROOT / "private" / "exclusions.json")
        d = json.load(open(path, encoding="utf-8"))
        excl = set(json.load(open(exclusions)).get("terms", [])) if exclusions.exists() else set()
        self.customers_full = PhraseIndex([c for c in d["customers_full"] if len(c) >= 6 and c not in excl])
        self.customer_tokens = {t for t in d["customer_tokens"] if t not in excl}
        self.addresses = PhraseIndex([a for a in d["addresses"] if len(a) >= 8 and a not in excl])
        self.employees = {k: v for k, v in d["employees"].items() if k not in excl}
        self.employee_first = {k: v for k, v in d["employee_first"].items() if k not in excl}
        # employee names: multi-token or >= 5 chars match case-insensitively (safe: no code word
        # looks like "Firstname Lastname"); short single names only in Title Case
        self.employee_rx = {k: employee_regex(k) for k in list(self.employees) + list(self.employee_first)}
        self.phones = set(d["phones"]); self.emails = set(d["emails"])
        self.shingles = set(l.strip() for l in open(shingles, encoding="utf-8") if l.strip())
        self.customer_job = d.get("customer_job", {})
        self.term_index = {t: i for i, t in enumerate(sorted(set(d["customers_full"]) | set(d["customer_tokens"]) | set(d["addresses"]) | set(d["employees"]) | set(d["employee_first"])))}


def shingle_hits(text, shingles):
    w = WORD.findall(text.lower())
    return sum(1 for i in range(0, max(0, len(w) - 7)) if hashlib.sha1(" ".join(w[i:i + 8]).encode()).hexdigest()[:10] in shingles)


def redact_notes(text, shingles, marker="[note text]"):
    """Replace every 8-word window that matches a chunk shingle with the
    marker (adjacent windows merge). Returns (text, windows_replaced)."""
    spans = [(m.start(), m.end(), m.group(0).lower()) for m in re.finditer(r"[A-Za-z0-9]+", text)]
    w = [s[2] for s in spans]
    hit = [False] * len(w)
    n = 0
    for i in range(0, max(0, len(w) - 7)):
        if hashlib.sha1(" ".join(w[i:i + 8]).encode()).hexdigest()[:10] in shingles:
            n += 1
            for j in range(i, i + 8): hit[j] = True
    if not n: return text, 0
    out, pos, i = [], 0, 0
    while i < len(w):
        if hit[i]:
            j = i
            while j + 1 < len(w) and hit[j + 1]: j += 1
            out.append(text[pos:spans[i][0]]); out.append(marker); pos = spans[j][1]; i = j + 1
        else:
            i += 1
    out.append(text[pos:])
    return "".join(out), n


def scan_text(text, T, terms_hit=None):
    """-> {category: [line numbers]}; never returns matched text. With
    terms_hit (a dict) also records which term indexes matched (for --diag)."""
    hits = defaultdict(list)
    for i, l in enumerate(text.split("\n"), 1):
        low = l.lower()
        lt = frozenset(WORD.findall(low))
        matched = set()
        for p in T.customers_full.find(l, lt):
            matched.add(p); hits["customer_name"].append(i); break
        for p in T.addresses.find(l, lt):
            matched.add(p); hits["address"].append(i); break
        tt = customer_token_hits(l, T.customer_tokens)
        if tt:
            matched |= tt; hits["customer_token"].append(i)
        for k, rx in T.employee_rx.items():
            if rx.search(l):
                matched.add(k); hits["employee"].append(i); break
        if "@" in low and any(e in low for e in T.emails): hits["email"].append(i)
        for d in re.findall(r"\d[\d\s().-]{6,}\d", l):
            digits = re.sub(r"\D", "", d)
            if len(digits) >= 7 and (digits[-10:] if len(digits) >= 10 else digits) in T.phones:
                hits["phone"].append(i); break
        for m in DOLLAR.finditer(l):
            if int(m.group(1).replace(",", "")) >= 100: hits["dollar"].append(i); break
        if money_no_sign_hits(l): hits["dollar_nosign"].append(i)
        for name, rx in SECRET_PATTERNS.items():
            if rx.search(l): hits["secret:" + name].append(i)
        if IP.search(l): hits["server_ip"].append(i)
        if terms_hit is not None:
            for t in matched: terms_hit[t].add(i)
    n = shingle_hits(text, T.shingles)
    if n >= 3: hits["note_text"] = [n]  # count of matching 8-word shingles, not line numbers
    return dict(hits)


def is_binary(path, data):
    return Path(path).suffix.lower() in BINARY or b"\x00" in data[:4096]


def scan_tree(root, tracked):
    root = Path(root)
    if tracked:
        files = [f for f in subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout.decode().split("\0") if f]
    else:
        files = [str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]
    for f in sorted(files):
        data = (root / f).read_bytes()
        if is_binary(f, data): continue
        yield f, data.decode("utf-8", errors="replace")


def scan_blobs(git_dir):
    out = subprocess.run(["git", "-C", git_dir, "rev-list", "--all", "--objects"], capture_output=True, check=True).stdout.decode()
    objs = [l.split(" ", 1) for l in out.splitlines() if " " in l]
    types = subprocess.run(["git", "-C", git_dir, "cat-file", "--batch-check=%(objectname) %(objecttype)"], input="\n".join(o[0] for o in objs).encode(), capture_output=True, check=True).stdout.decode()
    blobs = {l.split()[0] for l in types.splitlines() if l.endswith(" blob")}
    for sha, path in objs:
        if sha not in blobs: continue
        data = subprocess.run(["git", "-C", git_dir, "cat-file", "blob", sha], capture_output=True, check=True).stdout
        if is_binary(path, data): continue
        yield f"{path}@{sha[:8]}", data.decode("utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["tree", "blobs"]); ap.add_argument("target")
    ap.add_argument("--tracked", action="store_true"); ap.add_argument("--json"); ap.add_argument("--strict", action="store_true")
    ap.add_argument("--quiet", action="store_true"); ap.add_argument("--diag", action="store_true")
    a = ap.parse_args()
    T = Terms()
    it = scan_tree(a.target, a.tracked) if a.mode == "tree" else scan_blobs(a.target)
    results, n_files, diag = {}, 0, defaultdict(dict)
    for name, text in it:
        n_files += 1
        th = defaultdict(set) if a.diag else None
        h = scan_text(text, T, th)
        if h: results[name] = h
        if th:
            for t, lines in th.items(): diag[t][name] = len(lines)
    secret_cats = tuple({k for h in results.values() for k in h if k.startswith("secret:")})
    fail_cats = GUARDED + secret_cats + (("employee", "dollar", "server_ip") if a.strict else ())
    failing = {f: {c: v for c, v in h.items() if c in fail_cats} for f, h in results.items()}
    failing = {f: h for f, h in failing.items() if h}
    if a.json:
        json.dump({"files_scanned": n_files, "results": results}, open(a.json, "w"), indent=1)
    if not a.quiet:
        totals = defaultdict(int)
        for h in results.values():
            for c, v in h.items(): totals[c] += (1 if c == "note_text" else len(v))
        print(f"scanned {n_files} files; {len(results)} with hits")
        for c in sorted(totals): print(f"  {c:28s} {totals[c]:6d} lines in {sum(1 for h in results.values() if c in h)} files")
        if failing:
            print(f"GUARD: {len(failing)} file(s) with guarded hits:")
            for f in sorted(failing): print("  " + f + "  " + ", ".join(f"{c}={len(v) if c != 'note_text' else v[0]}" for c, v in sorted(failing[f].items())))
    if a.diag:
        code = re.compile(r"^(retrieval|ingest|serve|sql|scripts|tests|evals/[^/]+\.py|\.github|deploy|docker|requirements|\.gitignore|CLAUDE)")
        print("DIAG: term# len files code_files  (terms that hit any code file, most files first)")
        rows = [(len(files), sum(1 for f in files if code.search(f)), T.term_index[t], len(t)) for t, files in diag.items()]
        for nf, nc, idx, ln in sorted(rows, reverse=True):
            if nc: print(f"  term#{idx:<6d} len={ln:<3d} files={nf:<4d} code_files={nc}")
    sys.exit(1 if failing else 0)


if __name__ == "__main__":
    main()

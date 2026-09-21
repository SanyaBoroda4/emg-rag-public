"""WO19: build the public-mirror tree: allowlist, then transform.

    python scripts/public_transform.py --src <checkout> --out <dir> [--allowlist deploy/public_allowlist.txt]

Copies only the files the allowlist admits, then rewrites every text file:
  * employee names           -> consistent pseudonyms ("Salesperson A", "Crew B");
                                PUBLIC_EMPLOYEE_NAMES=real keeps them (default: pseudonym)
  * customer names           -> "Customer #<job_id>" when the name resolves to a job, else "[customer]"
  * single customer tokens   -> "[customer]" (Title Case matches only; see public_scan.py)
  * phones, emails, street addresses -> "[redacted]"
  * dollar figures of 100 USD and up -> "$[redacted]" (API costs are cents; job money is hundreds and up)
  * the server IP            -> SERVER_IP_REDACTED
  * verbatim note text       -> every 8-word window that matches a chunk shingle
                                becomes "[note text]" (adjacent windows merge)
Then it scans the result; a file that still holds note text (>= 3 shingle
hits) is removed and listed. The manifest (what went in, what was excluded and
why) is written to <out>/PUBLIC_MANIFEST.md, and a JSON summary is printed.

Term lists come from private/ (gitignored). Nothing in this script's output
ever contains a term: only paths and counts.
"""
import argparse, fnmatch, json, os, re, shutil, subprocess, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import public_scan as ps  # noqa: E402

ROOT = ps.ROOT


def load_allowlist(path):
    return [l.strip() for l in open(path, encoding="utf-8") if l.strip() and not l.startswith("#")]


def allowed(rel, globs):
    return any(fnmatch.fnmatch(rel, g) for g in globs)


class Transformer:
    def __init__(self, T: ps.Terms, employee_mode="pseudonym"):
        self.T = T
        self.employee_mode = employee_mode
        # longest names first so "Firstname Lastname" wins over "Firstname"
        self.emp = sorted(list(T.employees.items()) + list(T.employee_first.items()), key=lambda kv: -len(kv[0]))
        self.counts = Counter()

    def _customers(self, line, lt):
        found = list(self.T.customers_full.find(line, lt))
        for p in sorted(set(found), key=len, reverse=True):
            jid = self.T.customer_job.get(p)
            repl = f"Customer #{jid}" if jid else "[customer]"
            line, n = self.T.customers_full.rx(p).subn(repl, line)
            self.counts["customer_name"] += n
        return line

    def _addresses(self, line, lt):
        for p in set(self.T.addresses.find(line, lt)):
            line, n = self.T.addresses.rx(p).subn("[redacted]", line)
            self.counts["address"] += n
        return line

    def _tokens(self, line):
        def rep(m):
            if m.group(0).lower() in self.T.customer_tokens:
                self.counts["customer_token"] += 1
                return "[customer]"
            return m.group(0)
        line = ps.TITLE.sub(rep, line)
        def in_quotes(m):  # any case inside a quoted literal
            return ps.WORD.sub(lambda w: rep(w) if w.group(0).lower() in self.T.customer_tokens else w.group(0), m.group(0)) \
                if any(t in self.T.customer_tokens for t in ps.WORD.findall(m.group(0).lower())) else m.group(0)
        return ps.QUOTED.sub(in_quotes, line)

    def _employees(self, line):
        if self.employee_mode != "pseudonym": return line
        for k, pseud in self.emp:
            line, n = self.T.employee_rx[k].subn(pseud, line)
            self.counts["employee"] += n
        return line

    def _contacts(self, line):
        low = line.lower()
        if "@" in low:
            for e in self.T.emails:
                if e in low:
                    line = re.sub(re.escape(e), "[redacted]", line, flags=re.I); self.counts["email"] += 1
        def rep(m):
            digits = re.sub(r"\D", "", m.group(0))
            if len(digits) >= 7 and (digits[-10:] if len(digits) >= 10 else digits) in self.T.phones:
                self.counts["phone"] += 1; return "[redacted]"
            return m.group(0)
        return re.sub(r"\d[\d\s().-]{6,}\d", rep, line)

    def _dollars(self, line):
        def rep(m):
            if int(m.group(1).replace(",", "")) >= 100:
                self.counts["dollar"] += 1; return "$[redacted]"
            return m.group(0)
        line = ps.DOLLAR.sub(rep, line)
        def rep2(m):  # WO20: two-decimal money without a sign
            if int(m.group(1).replace(",", "")) >= 100:
                self.counts["dollar_nosign"] += 1; return "$[redacted]"
            return m.group(0)
        return ps.MONEY_NO_SIGN.sub(rep2, line)

    def line(self, line):
        lt = frozenset(ps.WORD.findall(line.lower()))
        line = self._customers(line, lt)
        line = self._addresses(line, lt)
        line = self._contacts(line)
        line = self._employees(line)
        line = self._tokens(line)
        line = self._dollars(line)
        line, n = ps.IP.subn("SERVER_IP_REDACTED", line); self.counts["server_ip"] += n
        return line

    def text(self, text):
        return "\n".join(self.line(l) for l in text.split("\n"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--allowlist", default=str(ROOT / "deploy" / "public_allowlist.txt"))
    a = ap.parse_args()
    src, out = Path(a.src), Path(a.out)
    globs = load_allowlist(a.allowlist)
    T = ps.Terms()
    tr = Transformer(T, os.environ.get("PUBLIC_EMPLOYEE_NAMES", "pseudonym"))
    files = [f for f in subprocess.run(["git", "-C", str(src), "ls-files", "-z"], capture_output=True, check=True).stdout.decode().split("\0") if f]
    kept, skipped, excluded_note, per_file = [], [], [], {}
    out.mkdir(parents=True, exist_ok=True)
    for rel in sorted(files):
        if not allowed(rel, globs):
            skipped.append(rel); continue
        data = (src / rel).read_bytes()
        dest = out / rel; dest.parent.mkdir(parents=True, exist_ok=True)
        if ps.is_binary(rel, data) or Path(rel).name.upper().startswith("LICENSE"):
            # binaries and licence texts are copied verbatim (a licence must not be
            # altered); licences are still scanned by the guard below
            dest.write_bytes(data); kept.append(rel); continue
        before = dict(tr.counts)
        text = tr.text(data.decode("utf-8", errors="replace"))
        text, n_notes = ps.redact_notes(text, T.shingles)
        if n_notes: tr.counts["note_window"] += n_notes
        delta = {k: v - before.get(k, 0) for k, v in tr.counts.items() if v - before.get(k, 0)}
        hits = ps.scan_text(text, T)
        if "note_text" in hits:
            excluded_note.append((rel, hits["note_text"][0])); continue
        dest.write_text(text, encoding="utf-8", newline="\n")
        kept.append(rel); per_file[rel] = delta
    lines = ["# Public mirror manifest", "",
             "Built by scripts/public_transform.py from the private repo's tracked files at HEAD.",
             "Allowlist: deploy/public_allowlist.txt. Employee names are pseudonyms; customer names,",
             "contact data and EMG dollar figures are redacted. Files still holding verbatim note text",
             "after the transform are excluded.", "",
             f"Kept: {len(kept)} files. Not allowlisted: {len(skipped)}. Excluded for note text: {len(excluded_note)}.", "",
             "## Excluded after transform (note text)", ""] + [f"- `{r}` ({n} matching shingles)" for r, n in excluded_note] + \
            ["", "## Transformed files (replacements by category)", ""] + \
            [f"- `{r}`: " + ", ".join(f"{k}={v}" for k, v in sorted(d.items())) for r, d in sorted(per_file.items()) if d]
    (out / "PUBLIC_MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"kept": len(kept), "not_allowlisted": len(skipped), "excluded_note_text": [r for r, _ in excluded_note],
                      "replacements": dict(tr.counts), "employee_mode": tr.employee_mode}))


if __name__ == "__main__":
    main()

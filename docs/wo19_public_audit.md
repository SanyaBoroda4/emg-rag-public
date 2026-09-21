# WO19 — Public mirror: PII and secrets audit, switch to an allowlist

Baseline `d69a060` (WO18). No migrations, no LLM calls, cost $0. This report
is written to be public: it holds counts, paths and line numbers only. No
customer name, contact detail, note text or dollar figure from EMG's data
appears in it, and none appears in any file it references as public.

Status at the end of the session: **Parts 0, 1 and 2 complete. Part 3
stopped at the decision point** because the public repository's history holds
customer data. Nothing has been pushed to the public repo since `d69a060`
(the old sync script has been replaced and the new one has only been run in
dry-run mode).

---

## 1. Part 0 — Diagnostic (read-only)

### 1.1 How the mirror worked until this work order

`scripts/sync_public.sh` (its version at `d69a060`) did the following on every
run: clone the private repo, run `git filter-repo` with two rules (replace the
server IP everywhere; re-attribute early commits with the placeholder author
email to the real GitHub noreply address), then `git push --force` the
rewritten `main` to the public repo. That is a **full history replay**: every
file ever committed privately was published, in every version, minus one IP
string. There was no exclude list at all.

Public repository, read with `gh` on 2026-09-21:

| Fact | Value |
|---|---|
| URL | `github.com/SanyaBoroda4/emg-rag-public` |
| Visibility | PUBLIC |
| Created | 2026-08-02 |
| Commits on `main` | 164 |
| Files at HEAD | 184 (identical list to the private HEAD) |
| Blobs in history | 378 (357 text, 21 binary) |
| Paths that ever existed | 180 distinct (0 exist only in history) |
| Stars / forks / watchers | 1 / 0 / 0 |
| Clones, last 14 days (traffic API) | 206 clones by 79 unique cloners |
| Views, last 14 days | 0 |

The clone count matters for Part 3: whatever was in the repo has most likely
been copied by automated crawlers already. Removing it stops further reads;
it cannot recall past ones.

### 1.2 Sensitive-term lists (private, never printed)

Built on the server by `scripts/build_pii_terms.py` and
`scripts/build_pii_shingles.py` (committed; they hold SQL and logic, no data)
with their output redirected straight into `private/pii_terms.json` and
`private/shingles.txt`; `private/` was added to `.gitignore` first. The
scripts print only the counts below. To rebuild on a new machine:

```
ssh root@SERVER 'cd /opt/emg-rag && .venv/bin/python -' < scripts/build_pii_terms.py > private/pii_terms.json
ssh root@SERVER 'cd /opt/emg-rag && .venv/bin/python -' < scripts/build_pii_shingles.py | sort -u > private/shingles.txt
python scripts/build_pii_exclusions.py 4178
```

Views were read as `rag_reader`; the three tables no view exposes (`job_contacts`, `jobs.addr_raw`,
`invoices.bill_email`) and `chunks.raw_text` were read with the owner role in
a `default_transaction_read_only=on` session, because `rag_reader` has no
grant on them.

| List | Source | Count |
|---|---|---|
| Customer name forms | `v_jobs.job_name`, `v_jobs.customer` (account), `v_invoices.customer_name`, `job_contacts.name`; "Last, First" also as "First Last"; employees removed | 6,834 |
| Customer single tokens | tokens of the above, ≥ 5 letters, minus a 4,602-word stoplist (every word in the repo's code, city names, material and supplier vocabulary) | 4,413 |
| Phones | `job_contacts.phone`, `.cell`, digits only, last 10 | 56 |
| Emails | `job_contacts.email`, `invoices.bill_email` | 2,661 |
| Street addresses | first line of `jobs.addr_raw` when it starts with a house number | 4,029 |
| Employees | `v_jobs.salesperson` (11) and `v_activities.assignees` (26 more) | 37 |
| Note fingerprints | sha1 of every 8-word window of every `chunks.raw_text`, first 10 hex chars | 42,900 distinct from 7,194 chunks |

Pseudonyms are assigned alphabetically within role: salespeople become
`Salesperson A` … `Salesperson K`, everyone else `Crew A` … `Crew Z`. First
names map to the same pseudonym; no two employees share a first name. The
repo owner's first name is not an employee name in the data, so prose such as
"Alex's step" is untouched.

A private exclusion list (`private/exclusions.json`) removes false positives
without anyone reading them: customer tokens that are ordinary English words
(`scripts/pii_common_words.txt`, set intersection), tokens that occur in the
OFL font licence text, tokens that the repo's own code uses (so a quoted word
in a script is never rewritten in the public copy), 1 generic assignee label,
and 1 entry chosen by the anonymous diagnostic below (a 4-letter "employee"
that hit 15 code files). Employee names that are also English words are
matched in Title Case only, so ordinary prose is not rewritten.

### 1.3 Scanner

`scripts/public_scan.py` (committed; it is also the guard in Part 1). It
scans a directory tree, the tracked files of a checkout, or every blob in a
repository's history, and reports file × category × line numbers, never a
matched string. Categories and rules:

| Category | Rule |
|---|---|
| `customer_name` | multi-token name, case-insensitive, tokens in order with any separator; candidate phrases found through an index keyed by each phrase's rarest token |
| `customer_token` | single surname/company token in Title Case anywhere, or in any case inside a quoted string literal (`'%name%'` in a report's SQL) |
| `address` | street line, same matching as names |
| `phone`, `email` | digits (last 10) / exact lower-case |
| `note_text` | ≥ 3 matching 8-word shingles in the file (the count is reported, not lines) |
| `employee` | case-insensitive for multi-token or ≥ 5-letter names, Title Case only for shorter ones |
| `dollar` | `$` amount of 100 or more (API costs are cents; EMG money is hundreds and up) |
| `secret:*` | `sk-ant-`, Voyage `pa-…`, `sk-lf-`/`pk-lf-`, a Postgres URL with an embedded password, `$2a$`/`$2b$` hashes, `PASSWORD=` with a literal value |
| `server_ip` | the Hetzner address |

Guarded categories (fail the guard): customer name, customer token, address,
phone, email, note text, any secret. Employee names, dollar figures and the IP
are reported only, because the transform rewrites them.

The first version matched 6,834 phrases with one alternation regex and took
4 m 46 s over 163 files; the rarest-token index brought that to 8 s.

`--diag` prints, per term that hit any code file, its index in the sorted
term list, its length and its file counts. That is how the generic entries
were found without displaying them.

### 1.4 Scan results

Three targets, same term lists, run 2026-09-21:

| Target | Text files scanned | Files with guarded hits | Secrets |
|---|---|---|---|
| Private repo HEAD (`d69a060`, tracked files) | 163 | 52 | 0 |
| Public repo HEAD (`ec08a2e`) | 163 | 52 (same files, same counts) | 0 |
| Public repo history (every blob) | 357 | 71 blob versions across 52 paths | 0 |

No path with hits exists only in history: every affected file is still at
HEAD, and older versions of `evals/golden_set.csv` (18 versions) and of some
WO reports add the rest. Employee names appear in 143 blob versions (72 files
at HEAD); dollar figures in 69 blob versions (46 files at HEAD). The
`PASSWORD=` pattern initially flagged three lines of `ingest/db.py`; they read
the value from the environment, and the pattern now requires a literal value.
`.env.example` holds placeholders only (checked by value length and shape,
not printed).

File × category, counts only. `<run>` stands for the timestamped eval
outputs.

| File | At HEAD (category = lines; note_text = matching windows) | Versions in history with hits | Largest per version |
|---|---|---|---|
| `evals/results/<run>.json` (36 files) | address 503, customer_name 8,247, customer_token 5,155, note_text 6,303 | 36 | address 36, customer_name 477, customer_token 308, note_text 353 |
| `evals/results/<run>.md` (4 per-question renders) | address 18, customer_name 462, customer_token 666, note_text 1,089 | 4 | address 5, customer_name 117, customer_token 175, note_text 292 |
| `evals/results/wo15_quoted_jobs_diagnostic_full.md` | address 10, customer_name 195, customer_token 175, note_text 30 | 1 | same |
| `evals/results/wo_wasted_templates.md` | address 1, customer_name 1, customer_token 19, note_text 266 | 1 | same |
| `evals/results/wo10_determinism_latency.md` | customer_token 6, note_text 204 | 2 | same |
| `data/charleston_address_map.csv` | address 79, customer_name 3, customer_token 30 | 1 | same |
| `evals/golden_set.csv` | address 1, customer_name 3, customer_token 3, note_text 12 | 18 | note_text 17 |
| `docs/session-2026-09-08-to-10-WO8-WO10.md` | customer_token 1, note_text 13 | 1 | same |
| `evals/results/wo9_status_widening.md` | address 1, customer_name 2, customer_token 4, note_text 4 | 1 | same |
| `evals/results/wo15_quoted_jobs_diagnostic.md` | customer_name 5, customer_token 6 | 2 | same |
| `evals/results/wo11_rekey.md` | address 2, customer_name 3, customer_token 2 | 1 | same |
| `data/city_map_final.csv` | address 3 | 1 | same |
| `evals/results/before_after.md` | customer_token 1 | 1 | same |
| `serve/static/fonts/LICENSE.txt` | customer_token 5 (licence words; excluded since) | 1 | same |

Not in the table because the scanner cannot see it by pattern:
`evals/fixtures/fixture.sql` holds 139 `INSERT INTO chunks` rows and 25 job
rows copied from the database. It is excluded from the mirror by the allowlist
regardless.

---

## 2. Part 1 — Allowlist, transform, guard

### 2.1 Allowlist: `deploy/public_allowlist.txt`

Globs matched against tracked files at HEAD; anything unlisted stays private.

In: `README.md`, `CLAUDE.md`, `HANDOFF.md`, `.gitignore`, `.env.example`,
`.github/workflows/*.yml`, `docker-compose.yml`, `requirements*.txt`,
`retrieval/*.py`, `ingest/*.py`, `serve/*.py`, `serve/static/index.html`,
`serve/static/fonts/*`, `sql/*.sql`, `scripts/*`, `tests/*.py`, `deploy/*`,
`evals/*.py`, `evals/baseline.json`, `evals/golden_set.csv`,
`evals/golden_conversations.csv`, `evals/fixtures/load_fixture.py`,
`evals/fixtures/fixture_baseline.json`, `evals/fixtures/fixture_golden.csv`,
`evals/fixtures/rewrite_cases.json`, `docs/*.md`, `evals/results/wo*.md`,
`evals/results/ablation.md`, `evals/results/before_after.md`,
`evals/results/benchmark.md`, `evals/results/wo18_screens/*` (mock data; the
WO18 report now says so above its screenshot table).

Out by design: `evals/results/*.json` (36 run outputs), the per-question
renders `evals/results/2026-*.md` and `latest.md`, `evals/fixtures/fixture.sql`,
`data/*.csv`, `.env*`, `private/`. At HEAD that is 51 files.

### 2.2 Transform: `scripts/public_transform.py`

Every allowed text file is rewritten line by line, in this order, with the
private term lists:

| What | Becomes |
|---|---|
| Customer full name (resolves to a job) | `Customer #<job_id>` (smallest job id for that name) |
| Customer full name (no job) or single token | `[customer]` |
| Phone, email, street address | `[redacted]` |
| Employee name or first name | its pseudonym; `PUBLIC_EMPLOYEE_NAMES=real` keeps real names (default `pseudonym`) |
| `$` amount ≥ 100 | `$[redacted]` |
| Server IP | `SERVER_IP_REDACTED` |
| Every 8-word window matching a chunk shingle | `[note text]` (adjacent windows merge into one marker) |

Binary files and any `LICENSE*` file are copied verbatim (a licence must not
be altered). After the rewrite each file is scanned again; a file with ≥ 3
matching shingles left would be dropped and listed in the manifest. The
transform writes `PUBLIC_MANIFEST.md` into the public tree: what went in,
what was held back, and per-file replacement counts by category.

### 2.3 Guard and sync: `scripts/sync_public.sh`

The script now: refuses to run on a dirty private tree or without the term
lists; clones the private HEAD into a temp dir; runs the transform; runs
`public_scan.py tree` on the result and **exits 1 without pushing** if any
guarded category hits; otherwise clones the public repo, replaces its working
tree with the sanitized one, and pushes **one snapshot commit**
(`sync: private <sha>`). It never replays history again.
`--dry-run DIR` stops after the guard and leaves the tree in `DIR`.

### 2.4 Guard test: `tests/test_public_guard.py`

Five tests, self-contained (fake term lists and a fake note built inside the
test; no `private/` files, no database), so they run anywhere:

1. a planted report with a fake customer, address, phone, email, employee,
   note, dollar figure, IP, Anthropic-style key and a Postgres URL with an
   embedded password is flagged in every category, and a clean report in none;
2. the transform plus note redaction removes all of it (asserts the markers
   are present and none of the planted strings survive) and the result scans
   clean;
3. a quoted SQL literal (`'%name%'`) is caught and rewritten;
4. `PUBLIC_EMPLOYEE_NAMES=real` keeps real names;
5. `public_scan.py` as a process exits 1 on a tree with the planted file and
   0 on a clean tree (env overrides point it at the fake lists).

All five pass locally (`python tests/test_public_guard.py`). The fake secrets
and amount in the test are assembled at runtime so the test file itself
passes the guard.

Commits: `81f0791` chore(public): allowlist mirror with PII transform and
guard · `343063f` test(public): guard rejects planted PII · `47adae8`
fix(public): copy licence files verbatim; keep the guard's own sources
literal-free.

---

## 3. Part 2 — Verification (dry run at `47adae8`, repeated at `011fac9`)

`bash scripts/sync_public.sh --dry-run <dir>`. The second run adds the four
term-builder files and this report to the tree (142 kept, 122 text files
scanned) and is otherwise identical:

| Measure | Value |
|---|---|
| Files kept | 137 (+ `PUBLIC_MANIFEST.md`); 142 at `011fac9` |
| Files not allowlisted | 51 (48 under `evals/results/`, 2 under `data/`, 1 fixture) |
| Files excluded after the transform (note text left) | 0 |
| Replacements: customer names / tokens / addresses | 213 / 53 / 2 |
| Replacements: employee mentions | 584 (35 distinct pseudonyms in use) |
| Replacements: note windows / dollar figures / IP | 514 / 23 / 3 |
| Scan of the sanitized tree | **0** customer, **0** contact, **0** note text, **0** secrets, **0** dollar figures |
| Other category left | 1 `employee` line: a word of the OFL licence text (copied verbatim) coincides with an employee's name |

Diff of the sanitized tree against the current public HEAD: 184 files → 138;
51 removed, 5 added (the two scripts, the allowlist, the test, the manifest),
100 byte-identical, 33 differ (transformed, or changed privately since the
last sync); 8.58 MB → 1.39 MB. The three CSVs keep their row and column
counts (golden set 83 rows, conversations 39, fixture golden 14). Files that
the transform rewrote include `retrieval/sql_lane.py` (34 employee mentions
in few-shot examples), `serve/static/index.html` (one example question),
`tests/test_rewrite.py` and the golden CSVs, so the public code is no longer
byte-identical to the private code in those places.

---

## 4. Part 3 — History: stopped at the decision point

Part 0 found customer names, addresses and note text in **71 blob versions
across 52 paths** of the public repository's history, and 0 secrets. A normal
push does not fix that: the old blobs stay readable through any commit SHA.
**No push has been made.** Two options, commands prepared and **not run**:

**(a) Recreate the public repo from one clean snapshot — recommended.**
1 star, 0 forks, 0 watchers; nothing of value is lost except 164 commits of
history that the private repo keeps anyway. Making the old repo private first
stops public reads immediately, and renaming it keeps its history for Alex.

```
gh repo edit SanyaBoroda4/emg-rag-public --visibility private --accept-visibility-change-consequences
gh repo rename emg-rag-public-archive --repo SanyaBoroda4/emg-rag-public --yes
gh repo create SanyaBoroda4/emg-rag-public --public --description "EMG RAG: sanitized public mirror (allowlisted snapshot)"
bash scripts/sync_public.sh
```

**(b) Rewrite the public history in place with `git filter-repo`.** Keeps the
commit graph; more moving parts. The 48 run outputs and renders would be
dropped by path; names, tokens, addresses, emails and phones would go through
a generated `--replace-text` file (from `private/pii_terms.json`); verbatim
note text cannot be expressed as replacements without exporting the notes in
clear, so older versions of the WO reports would have to be dropped by path
as well. After the force-push GitHub still serves the old objects until
Support runs a garbage collection on request.

```
git clone https://github.com/SanyaBoroda4/emg-rag-public.git /tmp/pub && cd /tmp/pub
# generate private/replacements.txt and private/drop_paths.txt from the term lists (script to write)
git filter-repo --force --invert-paths --paths-from-file /path/to/private/drop_paths.txt --replace-text /path/to/private/replacements.txt
git push --force origin main
# then: GitHub Support ticket to purge unreachable objects
```

Either way, the 79 unique cloners of the last 14 days keep whatever they
took. No secret was ever in the public repo, so nothing needs rotating.

Until Alex decides: do not run the new `sync_public.sh` without `--dry-run`
against the existing public repo either, because it would add a clean
snapshot on top of the unclean history and make it look fixed.

---

## 5. Got worse

- **The public repo will lose its commit history.** The mirror's portfolio
  value was "full commit history"; from now on it is a sequence of snapshot
  commits, one per sync. The private repo keeps the real history.
- **Public code is no longer byte-identical to private code** where employee
  names sit in source: few-shot examples in the SQL lane, one UI example
  question, the rewrite test fixtures, the golden CSVs.
- **Readability of the public WO reports drops** where markers replace
  content: 210 `Customer #<id>`, 65 `[customer]`, 93 `[note text]` blocks, 7
  `[redacted]`, 26 `$[redacted]`. Some golden expected answers are now
  partly `[note text]`.
- **Syncing needs the private term lists on the machine that runs it.** A
  new machine has to rebuild them on the server first (section 1.2). The
  script refuses to run without them.
- **Known gaps in the scanner:** dollar figures without a `$` sign (a table
  cell reading `$[redacted]`) are not detected or redacted; notes shorter than
  8 words have no fingerprint; a customer whose surname is a common English
  word is caught only by full name; single tokens are Title-Case-only outside
  quotes, so a lower-case surname in prose would pass.
- **CI does not run the guard test** (`.github/workflows/eval.yml` runs the
  eval tiers only). Adding it is a one-line change left for a later order.

## 6. Surprises

- The mirror was a full history replay. Every sync since 2026-08-02 published
  every run JSON and render, so the exposure is the whole private history,
  not a few files.
- 206 clones by 79 unique cloners in 14 days for a repo with 1 star and 0
  views: crawlers. Assume the data has been copied.
- `rag_reader` cannot see contacts or addresses (no view exposes them), so the
  term builder needed the owner role for those tables; it used a read-only
  transaction and reported only counts.
- One "employee" in the data is a 4-letter generic label that hit 15 code
  files; one real employee's name is an English word that appears in the OFL
  licence. Both were handled without displaying them (index-based exclusion;
  licences copied verbatim).
- The first scanner took nearly 5 minutes per target; indexing phrases by
  their rarest token made it 8 seconds, which is what makes the guard usable
  on every sync.
- The quoted-literal gap: WO reports embed SQL with `'%name%'` in lower case,
  which a Title-Case rule misses. Found by reading the transform's own
  per-file counts, fixed in both scanner and transform, covered by a test.
- The guard flagged its own test file (planted fake secrets in source) and
  the scanner's docstring (the 100-dollar threshold written with a dollar sign); both now build those strings at runtime.

## 7. Cost

$0 in LLM calls. Server work: two runs of the term builder and one streamed
shingle export, all read-only, a few seconds of CPU each; the running
services were not touched. Local: scans and dry runs only.

## 8. Files

- `scripts/public_scan.py`, `scripts/public_transform.py`, `scripts/sync_public.sh`,
  `deploy/public_allowlist.txt`, `tests/test_public_guard.py`, `.gitignore` (`private/`),
  `CLAUDE.md` (mirror rule), `HANDOFF.md` (WO19 row and warning), this report.
- Term-list builders (no data inside): `scripts/build_pii_terms.py`,
  `scripts/build_pii_shingles.py`, `scripts/build_pii_exclusions.py`,
  `scripts/pii_common_words.txt`.
- Not committed, by design: `private/pii_terms.json`, `private/shingles.txt`,
  `private/exclusions.json`.

---

## 9. Part 3 outcome — option (a), executed 2026-09-21

Alex's decision: option (a). Alex made the old repository private by hand;
the rest ran in order:

| step | command | result |
|---|---|---|
| 1 | `gh repo view SanyaBoroda4/emg-rag-public --json visibility` | PRIVATE (before any change) |
| 2 | `gh repo rename emg-rag-public-archive --repo SanyaBoroda4/emg-rag-public --yes` | `emg-rag-public-archive`, PRIVATE: the 164-commit history is kept, unreadable to the public |
| 3 | `gh repo create SanyaBoroda4/emg-rag-public --public` | new empty repository, PUBLIC, created 2026-09-21 20:15 UTC |
| 4 | `bash scripts/sync_public.sh` | transform 152 files, guard 0 guarded hits, one snapshot commit `afd5dc3` ("sync: private 6d72d90") pushed to `main` |
| 5 | `gh repo view … --json visibility` on both | archive PRIVATE, new repo PUBLIC, default branch `main` |
| 6 | fresh clone + `python scripts/public_scan.py blobs <clone>` | 1 commit, 127 text blobs scanned, **0** customer / contact / note-text / secret / dollar hits; 1 `employee` line = the OFL licence word noted in §3 |
| 7 | `gh run list --repo SanyaBoroda4/emg-rag-public --workflow tests` | run 35650021001 on `afd5dc3`: **success**, steps rewriter / SQL validator / public-mirror guard all green |
| 8 | badge `…/actions/workflows/tests.yml/badge.svg` | renders **passing** (with and without `?branch=main`) |
| 9 | `gh repo edit … --description … --add-topic …` | description set to the two lines from `docs/wo21_portfolio.md`; topics `rag, text-to-sql, llm-evaluation, postgres, pgvector, fastapi, langfuse, anthropic-claude` |

The public repository now holds only allowlisted, transformed content with a
history that starts at the snapshot. Every later sync adds one commit. The
79 unique cloners of the old repository keep what they took; no secret was
ever public, so nothing was rotated.

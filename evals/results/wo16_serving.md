# WO16 — Phase 7: the RAG served over HTTPS (FastAPI + single-page UI + Caddy)

Date: 2026-09-17 · commits `8e3a0bf` … `fd2ae61` (+ this report) · live at
**https://rag.emgcheckbot.us** (Basic-Auth: `alex`, `office`) · final eval
`2026-09-17-0959-wo16-final.json` @ `fd2ae61`.

Division of labour, forced by the permission policy (CLAUDE.md forbids
Claude Code system-wide changes and any touch of the Caddy container, and the
policy enforces that regardless of the WO): Claude Code built and verified
Parts 1–3 and prepared Part 4; **Alex installed the systemd unit and did the
Caddy change by hand**; Claude Code ran Part 5 from the server side, with
the three checks that need real passwords run by Alex at his terminal.

## Part 0 — diagnostic findings (2026-09-17)

- Caddy `caddy:2`, bridge network `checkbot_default` (gateway **172.18.0.1**)
  with evolution_api/postgres/redis and emg_mcp; publishes 80/443. A host port
  bound to `127.0.0.1` is unreachable from any bridge container (tested with a
  throwaway `http.server` from `emg_rag_db`'s network view: 172.17.0.1,
  172.18.0.1, 172.19.0.1 and `host.docker.internal` all closed); a port bound
  to a bridge gateway IP is reachable, across bridges too. **So the API binds
  172.18.0.1:8080** and Caddy proxies to that; `ufw` inactive; DNS already
  resolved.
- `scripts/query.py` had no `ask()`; the pipeline lived in `_answer()` and
  printed. Refactor required.
- Memory before: host available 1,077 MB; one CLI question peaks at 149 MB
  RSS; `emg_rag_db` 198 MiB of 600.
- `tracing.trace()` accepted `session_id`/`tags` but not `user_id`.

## Part 1 — backend

### Step 0, the refactor (`8e3a0bf`)

`retrieval/pipeline.py:ask(question, *, session_id, user_id, tags,
entry_point) -> AskResult` — route / route_used / reason / answer / sql /
sql_error / columns / rows / row_count / hybrid restriction / chunks with
provenance / per-stage latency / latency_ms / cost_usd / trace_id. The CLI
is a printer over it. Byte-identity check on the server, latency line
excluded (it carries millisecond timings):

| question | before vs after |
|---|---|
| Q1 | `diff` empty — **IDENTICAL** |
| Q59 | `diff` empty — **IDENTICAL** |
| Q27 | two model-written lines differed (router reason wording; one answer sentence). Re-running the **new** code twice changed the same two lines again; the six `chunk` lines were md5-identical across all three runs (`347e66b0…`). Temperature-0 wording jitter (WO13), not the refactor. |

### Schema (`8484888`, `5f7af03`) — `sql/020`

`serve.asks` as specified plus the `(user_name, asked_at DESC)` index; role
`rag_serve` (USAGE on `serve`, INSERT/SELECT on `serve.asks` + sequence,
SELECT on the same views as `rag_reader`); password generated into `.env`
(`PG_SERVE_PASSWORD`, never printed), set by `scripts/setup_serve_role.py`.
Fence, measured: `rag_serve` — serve USAGE True, asks INSERT True, v_jobs
SELECT True, base table `jobs` False; `rag_reader` — serve USAGE **False**,
`serve.asks` SELECT **False** (`permission denied for schema serve`).

### API (`729b2b2`) — `serve/app.py`

fastapi 0.141.1 + uvicorn[standard] 0.53.0 pinned; +22 MB site-packages;
`import voyageai` torch check → `[]`. Endpoints exactly as the table in the
WO; behaviours: 500-char cap and empty → 400; `_inflight >= 2` → 429; 60 s →
504; every ask writes one `serve.asks` row (error rows included) and the
write can never fail the request; username decoded from `X-Forwarded-User`
or the `Authorization: Basic` header (password dropped at once); no user →
401 on `/api/*`; trace `name=ui`, `tags=["ui"]`, `user_id`, `session_id` from
`X-Session-Id`; binds 172.18.0.1:8080; import fails fast on a missing `.env`
key. `retrieval/tracing.py` forwards `user_id`.

## Part 2 — the page (`5a119b5`) — `serve/static/index.html`

One file, inline CSS + vanilla JS, no CDN, no build, no localStorage. Top to
bottom: "EMG RAG" + "Data as of 2026-07-30 · answers cite job and chunk
ids"; six example chips (invoice 2024, Mount Pleasant count, Crew J H1 2026
installs, wasted templates total, conversion rate, the "material into the
building" semantic one); textarea (Enter asks, Shift+Enter newline) disabled
in flight with an elapsed-seconds spinner; the answer as light markdown
(bold, lists, code, line breaks) with a colour-coded route badge and
"4.1 s · $0.0084" in grey; **Evidence** collapsed, SQL tab (query in `<pre>`,
rows table, "showing N of M") and Notes tab (chunk cards: job id + name,
context sentence, note text, `AUTOMATED` badge on bot notes); thumbs up /
down → `/api/feedback` (comment box on thumbs-down; disabled after sending);
left sidebar (drawer on phones) listing the user's past questions with time
and route badge, failed ones greyed with the error, "Load more"; clicking
one reloads it read-only with a "viewing a past answer from …" note and an
"Ask again" link that copies the question into the box.

**What a user sees for a refuse:** the orange `refuse` badge and one line —
"This system only answers questions about EMG's job-tracking and invoicing
data; that question is outside it." — no evidence section, 1.3 s, $0.0009.
**For a timeout:** the request returns 504 and the page shows, in red,
"That question took longer than 60 seconds and was cancelled. Try a narrower
one."; the sidebar gets a greyed entry with a `failed` badge and the error
text; nothing is retried.

## Part 3 — the service (`39ec1ac`)

`deploy/emg-rag-api.service`: uvicorn on 172.18.0.1:8080, one worker,
`EnvironmentFile=/opt/emg-rag/.env`, `Restart=on-failure`,
`MemoryHigh=300M`, `MemoryMax=350M`, enabled on boot. Claude Code's attempt
to `cp` it into `/etc/systemd/system` was denied by the permission policy;
Alex installed it. `ss -ltnp` shows exactly one 8080 listener,
`172.18.0.1:8080`, owned by uvicorn; nothing on the public interface.

### Memory table

| state | API RSS / MemoryCurrent | host `free -m` available |
|---|---|---|
| before (no API) | — | 1,077 MB |
| API idle (nohup measurement run) | 151 MB | 983 MB |
| during Q59 (1.5 s / 3 s) | 153 / 155 MB | 983 / 981 MB |
| after that question | 158 MB | 976 MB |
| **systemd service idle** (Part 5) | **122 MB** | 944 MB |
| **service, 2 asks in flight + 1 rejected** | **134 MB** | **912 MB** |
| service after Part 5 + full eval | 138 MB | 952 MB |

Tripwires (API < 300 MB, host ≥ 800 MB): never approached. `emg_rag_db`
198 → 205 MiB (the history rows), cap 600.

## Part 4 — Caddy (Alex, by hand)

Prepared: `deploy/Caddyfile.rag.snippet` (hash placeholders) and
`deploy/CADDY_STEPS.md`. The site block added to `/root/checkbot/Caddyfile`:

```
rag.emgcheckbot.us {
    basic_auth {
        alex   <bcrypt>
        office <bcrypt>
    }
    reverse_proxy 172.18.0.1:8080
    request_body {
        max_size 8KB
    }
}
```

Alex's report: reload (not restart) confirmed, production status codes
unchanged, Caddy uptime unchanged, the page works in a browser with history.
**One thing learned the hard way, now in HANDOFF:** the Caddyfile is a
*single-file bind mount*. `sed -i` replaces the file (new inode) and the
container keeps the old one — the edit "doesn't take". The fix was to write
through the mount from inside the container:
`docker exec -i caddy sh -c 'cat > /etc/caddy/Caddyfile' < /root/checkbot/Caddyfile`.
**Never `sed -i` that file.**

The bcrypt hashes were not committed (the snippet keeps placeholders); the
public-mirror sanitizer strips the server IP, not hostnames, so the domain
name appears in the mirror — a hostname with Basic-Auth in front of it is not
a secret, and no hash is in any tracked file.

## Part 5 — verification (evidence)

Server-side checks hit the same process Caddy proxies to, at
`172.18.0.1:8080` with `-u alex:x` — the API trusts the username Caddy
forwards, so this exercises the real code path without a password.

| # | check | result |
|---|---|---|
| 1 | `https://rag.emgcheckbot.us/healthz`, no credentials | **HTTP 401** |
| 2 | certificate | `CN=rag.emgcheckbot.us`, issuer Let's Encrypt (YE1), expires 2026-12-16; `/healthz` with credentials — see Alex's paste below |
| 3 | five asks vs CLI, same minute | table below — routes and numbers identical |
| 4 | Langfuse | all five traces `name=ui`, `user_id=alex`, one session id (`aaaaaaaa…`), tag `ui`; `user_feedback` score value 0 on Q74's trace with comment "[alex] WO16 verification thumbs-down (Q74)"; Alex's own browser thumbs-up (value 1) also present |
| 5 | 600-char question → **400**; empty → 400 "Please type a question."; three concurrent asks → **200, 200, 429** ("The system is busy with other questions — try again in a moment.") | pass |
| 6 | memory in flight: MemoryCurrent 134 MB, host available 912 MB; `emg_rag_db` 205 MiB | pass |
| 7 | `docker ps` before vs after: `diff` empty; Caddy "Up 7 weeks" throughout | pass |
| 8 | history as `alex`: rows 4–8 = the five asks, 9–10 the two concurrent asks that ran, **11 the forced-timeout row** (`ERROR: timed out after 0.01 s`, greyed in the UI); the 400s and the 429 never appear; as `office`: `[]`; `/api/history/11` as `office` → **404**, as `alex` → 200; `rag_reader` on `serve.asks` → permission denied | pass |
| 9 | full eval at the final commit | below |

The forced timeout was produced through the app's own handler with
`ASK_TIMEOUT_S` patched to 0.01 s (FastAPI TestClient, same code path), so
the 504 message and the error row are the real ones.

### The five answers, API vs CLI (same minute, 2026-09-17 09:53)

| q | route | API | CLI |
|---|---|---|---|
| Q1 | structured | 1,198 jobs — `[[1198]]`, 2.4 s, $0.0079 | 1,198 jobs |
| Q27 | semantic | chunks 7119, 4513, 3369, 3193, 4525, 4024; jobs 480, 4074, 3607, 2837; 4.1 s, $0.0034 | same six chunks, same four jobs; one sentence worded differently (the Part 1 jitter) |
| Q59 | structured | 70.0% (3,063 of 4,377) — `[[70.0, 3063.0, 4377.0]]`, 4.1 s, $0.0084 | 70.0%, 3,063 of 4,377 |
| Q74 | structured | 252 — `[[252]]`, 3.6 s, $0.0080 | 252 |
| Q23 | refuse | the refusal line, 1.3 s, $0.0009 | the refusal line |

### Alex's credentialed checks (HTTPS through Caddy, run at his terminal)

```
$ curl -s -u alex https://rag.emgcheckbot.us/healthz
{"ok":true,"db":true,"commit":"fd2ae61","as_of":"2026-07-30"}

$ curl -s -u office https://rag.emgcheckbot.us/healthz
{"ok":true,"db":true,"commit":"fd2ae61","as_of":"2026-07-30"}

$ curl -s -u alex -X POST https://rag.emgcheckbot.us/api/ask -H "Content-Type: application/json" -d "{\"question\":\"How many jobs has Salesperson G sold?\"}"
{"detail":"Method Not Allowed"}
```

Both users authenticate through Caddy and reach the API (`commit` matches
the running service). The third command reached FastAPI as a non-POST
request — `405` is FastAPI's own answer for a GET on `/api/ask` — which
points at the local shell dropping `-X POST` around the escaped quotes
(its stderr shows the pasted JSON being executed as commands), not at
Caddy: the same endpoint answered POSTs through Caddy from Alex's browser
minutes earlier (trace `51377d2865…`, `user_id=alex`, session `c128045c`,
with his thumbs-up recorded as `user_feedback=1`). A retry with
single-quoted arguments was requested; if it lands it is appended below.

### Final eval — `2026-09-17-0959-wo16-final.json` @ `fd2ae61`

| | WO14 final (`126da85`) | **WO16 final** |
|---|---|---|
| routing | 96.3% | **96.3%** |
| reranked R@10 / MRR | 0.818 / 0.660 | **0.818 / 0.660** |
| generation | 75/82 | **74/82** (floor 74–76) |
| faithfulness | 94.9% | 93.6% |
| cost / wall | $1.04 / 262 s | **$1.02 / 251 s** |

Failing: 11, 41, 45, 47, 49, 56, 68, 76. Against the WO14 final: Q30 ✓
(judge coin, WO14), **Q68 ✗ and Q76 ✗** — both with *different SQL text*
from the lane this run (Q68 a bare `COUNT` without the sq ft; Q76 grouped by
salesperson and year), the same temperature-0 SQL jitter WO13 measured at
76/82 identical SQL per run; both are known flaky rows. Q41 (draft, known
failing) failed this time with a SQL error instead of a wrong answer:
`column j.customer does not exist` — the model put `customer` on a
`v_job_areas` alias and the validator's column whitelist is global across
views (the Q26 class of bug from WO11). No eval-path code changed in WO16
(`git diff 126da85..HEAD` on `evals/` and `retrieval/`: WO15's schema-prompt
wording and Q16 key, plus the `user_id` passthrough in `tracing.py`); the
service was idle during the run.

## Got worse

Nothing from WO16's code. Two known flaky rows (Q68, Q76) landed red in the
final eval on SQL-lane text variance, and Q41 surfaced a validator gap that
already existed. The stage that did change for real users is positive: a
question through the browser costs the same as the CLI and lands in the same
memory envelope (+12 MB over the CLI's peak).

Process-wise, two things could not be done by Claude Code and were done by
Alex: the systemd install and the Caddy edit. Both are documented so the
next person does not rediscover the bind-mount trap.

## Surprises

1. **A loopback-bound port is invisible to bridge containers.** The WO's
   `127.0.0.1` + `host.docker.internal` design could not work on this box;
   the bridge-gateway bind is the private alternative and was verified with
   `ss` (no public listener).
2. **The permission policy is stricter than the WO.** `docker inspect
   caddy`, `cp … /etc/systemd/system` and `systemctl enable` were all denied;
   the WO's authorisation does not override CLAUDE.md as enforced.
3. **`sed -i` on a bind-mounted file silently detaches it** (new inode). The
   container kept serving the old Caddyfile until the file was rewritten in
   place from inside the container.
4. **`pkill -f` matches the ssh shell that runs it** — killing the smoke
   server also killed my own session; pidfiles from then on.
5. **The validator whitelist is per-column, not per-view** — Q41's
   `j.customer` on `v_job_areas` sails through exactly as Q26's
   `salesperson` did in WO11. A per-alias check is the fix; out of scope.

## Cost

Part 1 diffs and smoke (9 questions) $0.08 · Part 5 (5 asks + 5 CLI + 2
concurrent + 1 timeout) $0.10 · final eval $1.02 → **≈ $1.20** (tripwire $3).

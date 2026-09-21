# Caddy site block for rag.emgcheckbot.us — manual steps (WO16 Part 4)

Run these on the server as root, in order. Claude Code has no access to the
Caddy container (CLAUDE.md), so this is done by hand. Nothing here restarts
Caddy: it is a `reload`, and the other sites keep serving throughout.

Facts from Part 0: Caddy is `caddy:2` (v2.11.4) on the `checkbot_default`
bridge (gateway **172.18.0.1**), compose project `/root/checkbot`, Caddyfile at
`/root/checkbot/Caddyfile` (mounted at `/etc/caddy/Caddyfile`). The API
listens on **172.18.0.1:8080** and is not reachable from the public
interface. DNS `rag.emgcheckbot.us` → SERVER_IP_REDACTED already resolves.

## 0. Prerequisite — the API service must be running

Claude Code's permission policy blocks writes under `/etc`, so install the unit
by hand (three commands; the file is in the repo):

```
cp /opt/emg-rag/deploy/emg-rag-api.service /etc/systemd/system/emg-rag-api.service
systemctl daemon-reload
systemctl enable --now emg-rag-api
```

Expected:

```
# systemctl is-active emg-rag-api
active
# curl -s http://172.18.0.1:8080/healthz
{"ok":true,"db":true,"commit":"<sha>","as_of":"2026-07-30"}
# ss -ltnp | grep :8080
LISTEN 0 2048 172.18.0.1:8080 0.0.0.0:* users:(("uvicorn",...))     <- 172.18.0.1 only, never 0.0.0.0
```

## 1. Record the other sites' status codes BEFORE touching anything

```
curl -sI https://bot.emgcheckbot.us | head -1
curl -sI https://mcp.emgcheckbot.us | head -1
docker ps --format '{{.Names}}\t{{.Status}}'
```

Write the two status lines down — step 7 compares against them. `docker ps`
must print the same "Up N weeks" for every container afterwards.

## 2. Back up the live Caddyfile

```
cp /root/checkbot/Caddyfile /root/checkbot/Caddyfile.bak-$(date +%F)
ls -l /root/checkbot/Caddyfile*
```

(Do not copy it into `/opt/emg-rag` — it belongs to the other projects.)

## 3. Hash the two passwords (type them; nothing is stored in plain text)

```
docker exec -it caddy caddy hash-password
```

Enter and confirm the password for `alex`; it prints a `$2a$14$…` bcrypt
hash. Run it again for `office`. Keep the two hashes in the terminal only.

## 4. Append the site block with the hashes substituted

```
cat >> /root/checkbot/Caddyfile <<'EOF'

rag.emgcheckbot.us {
    basic_auth {
        alex   $2a$14$REPLACE_WITH_ALEX_HASH
        office $2a$14$REPLACE_WITH_OFFICE_HASH
    }
    reverse_proxy 172.18.0.1:8080
    request_body {
        max_size 8KB
    }
}
EOF
```

(Paste the real hashes over the two placeholders before running, or edit the
file afterwards with `nano /root/checkbot/Caddyfile`. The reference copy of
the block is `/opt/emg-rag/deploy/Caddyfile.rag.snippet`.)

## 5. Validate — STOP here if this fails

```
docker exec caddy caddy validate --config /etc/caddy/Caddyfile
```

Expected last line: `Valid configuration`. On any error: restore the backup
(`cp /root/checkbot/Caddyfile.bak-<date> /root/checkbot/Caddyfile`) and do
not reload.

## 6. Reload (never restart)

```
docker exec caddy caddy reload --config /etc/caddy/Caddyfile
```

Expected: exits 0 with no output (or an `INFO … config reloaded` line).
Caddy then obtains the TLS certificate for rag.emgcheckbot.us on its own
within ~30 s.

## 7. Verify

```
curl -sI https://bot.emgcheckbot.us | head -1        # same as step 1
curl -sI https://mcp.emgcheckbot.us | head -1        # same as step 1
docker ps --format '{{.Names}}\t{{.Status}}'         # same uptimes; caddy NOT restarted
curl -s https://rag.emgcheckbot.us/healthz            # expect: 401 body from Caddy (no credentials)
curl -s -u alex:<password> https://rag.emgcheckbot.us/healthz
                                                       # expect: {"ok":true,"db":true,...}
```

Then open https://rag.emgcheckbot.us in a browser, log in as `alex`, and ask
"How many jobs has Salesperson G sold?" — expect 1,198 with a
`structured` badge. Tell Claude Code "Caddy is live" to start Part 5.

## Adding a user later

`docker exec -it caddy caddy hash-password` → add a `name <hash>` line inside
the `basic_auth` block → `caddy validate` → `caddy reload`. History in the UI
is keyed on the username, so a new name starts with an empty list.

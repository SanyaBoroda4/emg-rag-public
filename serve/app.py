"""EMG RAG HTTP API (WO16): a thin FastAPI layer over retrieval.pipeline.ask.

    uvicorn serve.app:app --host 172.18.0.1 --port 8080 --workers 1

Binds to the docker bridge gateway only (Caddy on the checkbot_default
bridge can reach it; the public interface cannot). Caddy does Basic-Auth
and forwards the Authorization header; this app decodes the username only
and keys history and Langfuse user_id on it.

Endpoints: GET / (the page), GET /healthz, POST /api/ask, POST /api/feedback,
GET /api/history, GET /api/history/{id}. Every /api/ask writes one row to
serve.asks (also on error/timeout) and is one Langfuse trace tagged "ui".
"""

import asyncio
import base64
import datetime as dt
import decimal
import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

REQUIRED_ENV = ("ANTHROPIC_API_KEY", "VOYAGE_API_KEY", "PG_DB", "PG_USER",
                "PG_PASSWORD", "PG_RO_PASSWORD", "PG_SERVE_PASSWORD")
_missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
if _missing:  # fail fast at import, before uvicorn reports "started"
    raise RuntimeError(f"missing in .env: {', '.join(_missing)}")

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from ingest.db import get_ro_conn, get_serve_conn  # noqa: E402
from retrieval import tracing  # noqa: E402
from retrieval.pipeline import AS_OF, ask_conversational  # noqa: E402
from retrieval.rewrite import MAX_HISTORY, Turn  # noqa: E402

log = logging.getLogger("emg_rag.serve")
STATIC = Path(__file__).resolve().parent / "static"
COMMIT = tracing.git_sha()
MAX_QUESTION = 500
MAX_INFLIGHT = 2
ASK_TIMEOUT_S = 60
ROWS_IN_RESPONSE = 25
CHUNK_TEXT_CHARS = 600

_inflight = 0  # single event loop: a plain counter is the semaphore


@asynccontextmanager
async def lifespan(app):
    log.info("emg-rag api @ %s, as_of %s, langfuse %s", COMMIT, AS_OF,
             "on" if tracing.enabled() else "off")
    yield
    tracing.flush()


app = FastAPI(title="EMG RAG", docs_url=None, redoc_url=None,
              openapi_url=None, lifespan=lifespan)
# WO18: self-hosted IBM Plex woff2 files for the page (no CDN). Starlette
# serves them with ETag/Last-Modified; nothing else under static/ is exposed.
app.mount("/static/fonts", StaticFiles(directory=STATIC / "fonts"),
          name="fonts")


# ----------------------------------------------------------------- helpers

def _user(request: Request):
    """Username only. Caddy's basic_auth leaves the Authorization header on
    the proxied request; the password is decoded and dropped immediately."""
    u = request.headers.get("x-forwarded-user")
    if u:
        return u.strip()[:64]
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("basic "):
        try:
            raw = base64.b64decode(auth[6:].strip()).decode("utf-8", "replace")
            return raw.split(":", 1)[0].strip()[:64] or None
        except Exception:
            return None
    return None


def _require_user(request: Request) -> str:
    u = _user(request)
    if not u:
        raise HTTPException(401, "no user")
    return u


def _session(request: Request) -> str:
    s = request.headers.get("x-session-id", "")
    try:
        return str(uuid.UUID(s))
    except Exception:
        return str(uuid.uuid4())


def _jsonable(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    return v


def _payload(res) -> dict:
    return {
        "question": res.original_question or res.question,
        "rewritten_question": res.rewritten_question,
        "standalone": res.standalone,
        "rewrite_reason": res.rewrite_reason,
        "rewrite_latency_ms": res.rewrite_latency_ms,
        "rewrite_cost_usd": round(res.rewrite_cost_usd, 5),
        "history_turns": res.history_turns,
        "route": res.route_used,
        "route_reason": res.route_reason,
        "answer": res.answer,
        "sql": res.sql,
        "sql_error": (f"{res.sql_error_type}: {res.sql_error}"
                      if res.sql_error else None),
        "columns": res.columns,
        "rows": _jsonable(res.rows[:ROWS_IN_RESPONSE]),
        "row_count": res.row_count,
        "chunks": [{"chunk_id": c.chunk_id, "job_id": c.job_id,
                    "job_name": c.job_name,
                    "text": (c.raw or "")[:CHUNK_TEXT_CHARS],
                    "context": (c.context or "")[:CHUNK_TEXT_CHARS],
                    "is_bot": c.is_bot, "rerank_score": c.rerank_score}
                   for c in res.chunks],
        "latency_ms": res.latency_ms,
        "latency": {n: round(s * 1000) for n, s in res.latency},
        "cost_usd": round(res.cost_usd, 5),
        "trace_id": res.trace_id,
        "as_of": AS_OF,
    }


def _store(user, session_id, question, payload=None, error=None,
           latency_ms=None, conversation_id=None, parent_ask_id=None):
    """One serve.asks row per /api/ask; never raises."""
    try:
        with get_serve_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO serve.asks (user_name, session_id, question,
                       route, answer, response, trace_id, latency_ms,
                       cost_usd, error, conversation_id, rewritten_question,
                       standalone, parent_ask_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s)
                   RETURNING id""",
                (user, session_id, question,
                 payload.get("route") if payload else None,
                 payload.get("answer") if payload else None,
                 json.dumps(payload) if payload else None,
                 payload.get("trace_id") if payload else None,
                 latency_ms if latency_ms is not None
                 else (payload or {}).get("latency_ms"),
                 (payload or {}).get("cost_usd"), error,
                 conversation_id,
                 (payload or {}).get("rewritten_question"),
                 (payload or {}).get("standalone"),
                 parent_ask_id))
            row_id = cur.fetchone()[0]
            conn.commit()
            return row_id
    except Exception:
        log.exception("history write failed (request still served)")
        return None


def _load_history(user, conversation_id):
    """Last <= MAX_HISTORY completed turns of this conversation, this user,
    oldest first, as rewriter Turns; plus the id of the latest turn."""
    with get_serve_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, question, rewritten_question, route, answer,
                      response->>'sql'
               FROM serve.asks
               WHERE user_name = %s AND conversation_id = %s
                 AND error IS NULL AND answer IS NOT NULL
                 AND COALESCE(route, '') <> 'refuse'
               ORDER BY id DESC LIMIT %s""",
            (user, conversation_id, MAX_HISTORY))
        rows = cur.fetchall()[::-1]
    turns = [Turn(question=r[1], standalone_question=r[2] or r[1],
                  route=r[3], answer=r[4] or "", sql=r[5]) for r in rows]
    return turns, (rows[-1][0] if rows else None)


# --------------------------------------------------------------- endpoints

@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html", media_type="text/html")


@app.get("/healthz")
async def healthz():
    def check():
        with get_ro_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            return cur.fetchone()[0] == 1
    try:
        db = await asyncio.wait_for(asyncio.to_thread(check), timeout=5)
    except Exception:
        log.exception("healthz db check failed")
        db = False
    return JSONResponse({"ok": bool(db), "db": bool(db), "commit": COMMIT,
                         "as_of": AS_OF}, status_code=200 if db else 503)


class AskBody(BaseModel):
    question: str = Field(default="")
    conversation_id: str | None = None


def _conversation(cid):
    try:
        return str(uuid.UUID(cid)) if cid else str(uuid.uuid4())
    except Exception:
        return str(uuid.uuid4())


@app.post("/api/ask")
async def api_ask(body: AskBody, request: Request):
    global _inflight
    user = _require_user(request)
    q = (body.question or "").strip()
    if not q:
        return JSONResponse({"error": "Please type a question."}, 400)
    if len(q) > MAX_QUESTION:
        return JSONResponse({"error": f"Questions are limited to "
                                      f"{MAX_QUESTION} characters."}, 400)
    if _inflight >= MAX_INFLIGHT:
        return JSONResponse({"error": "The system is busy with other "
                                      "questions — try again in a moment."},
                            429)
    session_id = _session(request)
    conv_id = _conversation(body.conversation_id)
    _inflight += 1
    t0 = asyncio.get_event_loop().time()
    parent_id = None
    try:
        # WO17: this user's last completed turns of this conversation are the
        # rewriter's only context; a fresh conversation has none.
        try:
            history, parent_id = await asyncio.to_thread(_load_history, user,
                                                         conv_id)
        except Exception:
            log.exception("history load failed; asking without context")
            history, parent_id = [], None
        res = await asyncio.wait_for(
            asyncio.to_thread(ask_conversational, q, history,
                              session_id=session_id, user_id=user,
                              tags=["ui"], entry_point="ui"),
            timeout=ASK_TIMEOUT_S)
    except asyncio.TimeoutError:
        ms = round((asyncio.get_event_loop().time() - t0) * 1000)
        log.error("ask timed out after %ss: %r", ASK_TIMEOUT_S, q[:120])
        await asyncio.to_thread(_store, user, session_id, q, None,
                                f"timed out after {ASK_TIMEOUT_S} s", ms,
                                conv_id, parent_id)
        return JSONResponse({"error": f"That question took longer than "
                                      f"{ASK_TIMEOUT_S} seconds and was "
                                      f"cancelled. Try a narrower one.",
                             "conversation_id": conv_id}, 504)
    except Exception as e:
        ms = round((asyncio.get_event_loop().time() - t0) * 1000)
        log.exception("ask failed: %r", q[:120])  # traceback to the log only
        await asyncio.to_thread(_store, user, session_id, q, None,
                                f"{type(e).__name__}: {e}"[:500], ms,
                                conv_id, parent_id)
        return JSONResponse({"error": "Something went wrong answering that "
                                      "question. It has been logged.",
                             "conversation_id": conv_id}, 500)
    finally:
        _inflight -= 1
    payload = _payload(res)
    payload["conversation_id"] = conv_id
    payload["parent_ask_id"] = parent_id
    payload["id"] = await asyncio.to_thread(_store, user, session_id, q,
                                            payload, None, None, conv_id,
                                            parent_id)
    return payload


class FeedbackBody(BaseModel):
    trace_id: str
    score: int = Field(ge=0, le=1)
    comment: str | None = None


@app.post("/api/feedback")
async def api_feedback(body: FeedbackBody, request: Request):
    user = _require_user(request)
    if not body.trace_id or len(body.trace_id) > 64:
        return JSONResponse({"error": "bad trace id"}, 400)
    comment = (body.comment or "").strip()[:500] or None
    await asyncio.to_thread(
        tracing.score, body.trace_id, "user_feedback", float(body.score),
        comment=(f"[{user}] {comment}" if comment else f"[{user}]"))
    return {"ok": True}


@app.get("/api/history")
async def api_history(request: Request, limit: int = 50,
                      before: int | None = None):
    """This user's conversations, newest first (WO17). Pre-WO17 rows have
    no conversation_id and appear as one-turn conversations."""
    user = _require_user(request)
    limit = max(1, min(limit, 200))

    def q():
        with get_serve_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """WITH c AS (
                     SELECT COALESCE(conversation_id::text, 'ask-' || id) AS key,
                            conversation_id, MIN(id) AS first_id, MAX(id) AS last_id,
                            COUNT(*) AS turns, MAX(asked_at) AS last_at,
                            (array_agg(question ORDER BY id))[1] AS title,
                            (array_agg(route ORDER BY id DESC))[1] AS last_route,
                            (array_agg(error ORDER BY id DESC))[1] AS last_error,
                            bool_and(error IS NOT NULL) AS all_failed
                     FROM serve.asks WHERE user_name = %s GROUP BY 1, 2)
                   SELECT conversation_id, first_id, last_id, turns, last_at,
                          title, last_route, last_error, all_failed
                   FROM c WHERE (%s::bigint IS NULL OR last_id < %s)
                   ORDER BY last_id DESC LIMIT %s""",
                (user, before, before, limit))
            return [{"conversation_id": str(r[0]) if r[0] else None,
                     "id": r[1], "last_id": r[2], "turns": r[3],
                     "asked_at": r[4].isoformat(), "question": r[5],
                     "route": r[6], "error": r[7], "all_failed": r[8]}
                    for r in cur.fetchall()]
    return await asyncio.to_thread(q)


def _turn_payload(row):
    payload = dict(row[3] or {})
    payload.update({"id": row[0], "asked_at": row[1].isoformat(),
                    "question": row[2], "error": row[4],
                    "latency_ms": payload.get("latency_ms", row[5]),
                    "rewritten_question": payload.get("rewritten_question",
                                                      row[6]),
                    "standalone": payload.get("standalone", row[7])})
    return payload


@app.get("/api/history/{ref}")
async def api_history_one(ref: str, request: Request):
    """The whole conversation, in order. `ref` is an ask id (any turn) or a
    conversation uuid; 404 unless it belongs to the calling user."""
    user = _require_user(request)

    def q():
        with get_serve_conn() as conn, conn.cursor() as cur:
            cols = ("id, asked_at, question, response, error, latency_ms, "
                    "rewritten_question, standalone, conversation_id")
            conv = None
            if ref.isdigit():
                cur.execute(f"SELECT {cols} FROM serve.asks WHERE id = %s "
                            f"AND user_name = %s", (int(ref), user))
                row = cur.fetchone()
                if row is None:
                    return None, []
                conv = row[8]
                if conv is None:  # pre-WO17 single ask
                    return None, [row]
            else:
                try:
                    conv = str(uuid.UUID(ref))
                except Exception:
                    return None, []
            cur.execute(f"SELECT {cols} FROM serve.asks WHERE conversation_id = %s "
                        f"AND user_name = %s ORDER BY id", (conv, user))
            return conv, cur.fetchall()
    conv, rows = await asyncio.to_thread(q)
    if not rows:  # other user's row or no such row: same answer
        raise HTTPException(404, "not found")
    return {"conversation_id": str(conv) if conv else None,
            "turns": [_turn_payload(r) for r in rows]}

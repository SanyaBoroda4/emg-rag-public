"""Langfuse tracing, safe by construction (WO12).

One trace per question, one span per pipeline stage. Everything here is a
no-op when LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are absent, and every
Langfuse call is wrapped so that an SDK error or a Langfuse outage degrades
to "no tracing", never to a failed query.

The base URL is read from LANGFUSE_BASE_URL in .env (US region) and passed
explicitly; nothing relies on the SDK's own env-var lookup.

Vocabulary (see README "Observability"):
  trace        one question, end to end (named after the entry point:
               query_cli / eval_run)
  observation  one stage inside it: a "span" (bm25, fuse, sql_execute...)
               or a "generation" (a model call: router, sql_generate,
               answer, judge — carries model, tokens, cost)
  score        a number attached to a trace after the fact (eval verdicts)

Usage:
    with trace("query_cli", input=question, metadata={...}) as root:
        with span("bm25", as_type="retriever", input=q) as s:
            ...; s.update(output=ids)
        with generation("answer", model=m, input=...) as g:
            ...; g.update(output=text, usage=resp.usage, cost=c)
        root.update(output=answer)
    flush()
"""

import contextlib
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_client = None
_state = "unset"  # unset | on | off


def _log(msg):
    if os.environ.get("LANGFUSE_DEBUG"):
        print(f"[tracing] {msg}")


def get_client():
    """The shared Langfuse client, or None when tracing is off."""
    global _client, _state
    if _state != "unset":
        return _client
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY")
    sk = os.environ.get("LANGFUSE_SECRET_KEY")
    if not pk or not sk:
        _state = "off"
        _log("no LANGFUSE keys in the environment: tracing off")
        return None
    try:
        from langfuse import Langfuse
        _client = Langfuse(
            public_key=pk, secret_key=sk,
            base_url=os.environ.get("LANGFUSE_BASE_URL",
                                    "https://us.cloud.langfuse.com"),
            flush_at=20, flush_interval=2.0,  # batched, background thread
            environment=os.environ.get("LANGFUSE_TRACING_ENVIRONMENT",
                                       "server"))
        _state = "on"
    except Exception as e:  # missing package, bad config, network
        _state = "off"
        _client = None
        _log(f"Langfuse disabled: {type(e).__name__}: {e}")
    return _client


def enabled() -> bool:
    return get_client() is not None


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(Path(__file__).resolve().parent.parent),
             "rev-parse", "--short", "HEAD"], text=True,
            stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def usage_dict(usage):
    """Anthropic usage object -> Langfuse usage_details."""
    if usage is None:
        return None
    try:
        return {"input": int(usage.input_tokens),
                "output": int(usage.output_tokens)}
    except Exception:
        return None


class Obs:
    """Thin wrapper over a Langfuse observation; every method swallows
    SDK errors. Obs(None) is the no-op used when tracing is off."""

    def __init__(self, obs=None):
        self._obs = obs

    @property
    def trace_id(self):
        try:
            return self._obs.trace_id if self._obs is not None else None
        except Exception:
            return None

    def update(self, *, output=None, metadata=None, usage=None, cost=None,
               model=None, level=None, status_message=None, input=None):
        if self._obs is None:
            return
        kw = {}
        if input is not None:
            kw["input"] = input
        if output is not None:
            kw["output"] = output
        if metadata is not None:
            kw["metadata"] = metadata
        if model is not None:
            kw["model"] = model
        if usage is not None:
            ud = usage if isinstance(usage, dict) else usage_dict(usage)
            if ud:
                kw["usage_details"] = ud
        if cost is not None:
            kw["cost_details"] = {"total": float(cost)}
        if level is not None:
            kw["level"] = level
        if status_message is not None:
            kw["status_message"] = status_message
        try:
            self._obs.update(**kw)
        except Exception as e:
            _log(f"update failed: {e}")

    def error(self, exc):
        """Mark the observation failed with the exception text."""
        self.update(level="ERROR",
                    status_message=f"{type(exc).__name__}: {exc}")

    def set_trace_io(self, *, input=None, output=None):
        if self._obs is None:
            return
        try:
            self._obs.set_trace_io(input=input, output=output)
        except Exception as e:
            _log(f"set_trace_io failed: {e}")


@contextlib.contextmanager
def _observation(name, as_type, input, metadata, model, trace_id):
    lf = get_client()
    if lf is None:
        yield Obs(None)
        return
    try:
        kw = {"name": name, "as_type": as_type}
        if input is not None:
            kw["input"] = input
        if metadata is not None:
            kw["metadata"] = metadata
        if model is not None:
            kw["model"] = model
        if trace_id is not None:
            kw["trace_context"] = {"trace_id": trace_id}
        cm = lf.start_as_current_observation(**kw)
        raw = cm.__enter__()
    except Exception as e:
        _log(f"start_as_current_observation failed: {e}")
        yield Obs(None)
        return
    obs = Obs(raw)
    try:
        yield obs
    except BaseException as e:
        obs.error(e)  # the failed stage carries its message
        raise
    finally:
        try:
            cm.__exit__(None, None, None)
        except Exception as e:
            _log(f"observation exit failed: {e}")


def span(name, *, as_type="span", input=None, metadata=None, trace_id=None):
    """A non-model stage. as_type: span | retriever | embedding | ..."""
    return _observation(name, as_type, input, metadata, None, trace_id)


def generation(name, *, model, input=None, metadata=None, trace_id=None):
    """A model call: Langfuse shows model, tokens, cost and latency."""
    return _observation(name, "generation", input, metadata, model, trace_id)


@contextlib.contextmanager
def trace(name, *, input=None, metadata=None, session_id=None, tags=None,
          trace_id=None):
    """Root of one question. `metadata`/`session_id`/`tags` are propagated to
    the trace (filterable in the dashboard); pass trace_id to attach several
    root spans to one pre-created trace (the eval's tiers)."""
    lf = get_client()
    if lf is None:
        yield Obs(None)
        return
    try:
        from langfuse import propagate_attributes
        prop = propagate_attributes(
            session_id=session_id, tags=tags, trace_name=name,
            metadata={k: str(v) for k, v in (metadata or {}).items()
                      if v is not None})
        prop.__enter__()
    except Exception as e:
        _log(f"propagate_attributes failed: {e}")
        prop = None
    try:
        with _observation(name, "span", input, metadata, None,
                          trace_id) as root:
            yield root
    finally:
        if prop is not None:
            try:
                prop.__exit__(None, None, None)
            except Exception as e:
                _log(f"propagate exit failed: {e}")


def new_trace_id(seed: str):
    """Deterministic 32-hex trace id (so an eval question's tier-1 router
    call and tier-3 generation land in ONE trace)."""
    lf = get_client()
    if lf is None:
        return None
    try:
        return lf.create_trace_id(seed=seed)
    except Exception:
        return None


def score(trace_id, name, value, *, data_type=None, comment=None):
    """Attach an eval score to a trace. Booleans become 0/1 NUMERIC."""
    lf = get_client()
    if lf is None or trace_id is None or value is None:
        return
    try:
        if isinstance(value, bool):
            value = 1.0 if value else 0.0
        lf.create_score(trace_id=trace_id, name=name, value=float(value),
                        data_type=data_type or "NUMERIC", comment=comment)
    except Exception as e:
        _log(f"create_score failed: {e}")


def flush():
    """Block until queued spans/scores are sent — call before process exit."""
    lf = get_client()
    if lf is None:
        return
    try:
        lf.flush()
    except Exception as e:
        _log(f"flush failed: {e}")

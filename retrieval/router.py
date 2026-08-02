"""Query router: Haiku classifies each question into one of four routes.

  structured — counting/summing/filtering/ranking by numbers -> SQL lane
  semantic   — why / what happened / find-similar -> hybrid retrieval + rerank
  hybrid     — needs both: SQL narrows to a job_id set, semantic digs into it
  refuse     — outside the data entirely

Returns the route plus a one-line reason (kept for eval debugging in WO5).
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic
from dotenv import load_dotenv

load_dotenv()

ROUTER_MODEL = os.environ.get("ROUTER_MODEL", "claude-haiku-4-5")

SYSTEM_PROMPT = """You route questions about a countertop fabrication company's job-tracking and invoicing data (jobs, countertop areas/materials, activities with free-text notes, invoices).

Classify the question into exactly one route:
- "structured": answerable by counting, summing, filtering, or ranking over structured fields (job counts, sq ft, invoice totals, dates, materials, salespeople).
- "semantic": needs reading free-text notes — why something happened, what was said, find-similar-situations.
- "hybrid": needs a structured filter first (material, amount, date, status) AND then reading the matching jobs' notes.
- "refuse": not answerable from this company's data at all (general knowledge, weather, other companies).

Respond with JSON only: {"route": "...", "reason": "<one line>"}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "route": {"type": "string",
                  "enum": ["structured", "semantic", "hybrid", "refuse"]},
        "reason": {"type": "string"},
    },
    "required": ["route", "reason"],
    "additionalProperties": False,
}


def route_query(question: str):
    """Returns ({"route": ..., "reason": ...}, usage)."""
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=ROUTER_MODEL, max_tokens=200,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": question}])
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text), resp.usage

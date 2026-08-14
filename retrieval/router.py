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

Domain vocabulary: quote, template, measure, install, removal, fabrication, repair, tile, invoice, follow-up, contract, plumbing are ACTIVITY TYPES recorded in the tracking data — not general English. "How many quotes have we issued?" counts Quote activities: structured, never refuse. Questions about activity sequence or recency ("jobs that went quiet after a quote", "no activity since the template", "latest activity is X") are structured too — activity types and dates answer them.

Classify the question into exactly one route:
- "structured": answerable by counting, summing, filtering, or ranking over structured fields (job counts, sq ft, invoice totals, dates, materials, salespeople, activity types/dates/sequence).
- "semantic": needs reading free-text notes — why something happened, what was said, find-similar-situations.
- "hybrid": needs a structured filter first (material, amount, date, status) AND then reading the matching jobs' notes.
- "refuse": not answerable from this company's data at all (general knowledge, weather, other companies). Never refuse merely because a word like "quotes" also has an everyday meaning. Never refuse on the assumption that a detail is not tracked: job notes capture arbitrary observations (languages spoken, tips, complaints, damage, personal circumstances) — if it could plausibly appear in a job note, route "semantic".

A bare name, invoice number, address fragment, or material with no other words is a LOOKUP — the user wants everything the data has about it. Route it to "semantic" (it searches notes; identifiers are matched by the keyword lane). Never refuse a bare identifier.

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
        # temperature=0: across six identical-config eval runs the router
        # spanned 92.1-96.8% routing accuracy with zero router changes —
        # sampling noise at n=63 that kept polluting WO before/after
        # comparisons. Classification wants the argmax, not a sample.
        temperature=0,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": question}])
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return json.loads(text), resp.usage
    except json.JSONDecodeError:
        return {"route": "semantic",
                "reason": "router returned no parseable output — "
                          "defaulting to semantic"}, resp.usage

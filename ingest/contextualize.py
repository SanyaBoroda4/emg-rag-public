"""Generate context_text for chunks via claude-haiku-4-5 on the Message
Batches API (50% batch discount + prompt-cached system prompt).

For each chunk with context_text IS NULL (the queue build_chunks.py maintains:
new chunks, or chunks whose note/context facts changed), one batch request is
built from the shared context facts (ingest/context_facts.py) plus the verbatim
note. Output is a single situating sentence, written back by chunk_id.

Idempotent: re-running after completion selects zero chunks and exits.

Cost controls: projected cost is computed before submission and the script
aborts if projection + prior spend (pipeline_runs.note cost_usd entries)
exceeds the $30 ceiling. Actual usage-based cost is logged to
pipeline_runs.note as "cost_usd=...".

Partial failures: errored/expired custom_ids are recorded and reported;
successful results are still written; re-running picks up the failures.
"""

import re
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from ingest.context_facts import build_all
from ingest.db import get_conn

MODEL = "claude-haiku-4-5"
BATCH_SIZE = 2000
MAX_TOKENS = 200
COST_CEILING_USD = 30.0
# Haiku 4.5 batch pricing (50% of $1/$5 per MTok)
IN_PER_MTOK, OUT_PER_MTOK = 0.50, 2.50

SYSTEM = [{
    "type": "text",
    "text": (
        "You write one-sentence context headers for notes exported from a "
        "countertop fabrication company's Moraware job-tracking system. Each "
        "request contains FACTS (structured facts about the job and the "
        "record the note sits on) and NOTE (the note text, verbatim).\n\n"
        "Write ONE sentence, at most about 60 tokens, situating the note: "
        "which job/customer it belongs to and what kind of record it is, "
        "weaving in whichever supplied facts (area, material, schedule, "
        "status, phase) help a reader place the note. Rules:\n"
        "- Use ONLY the supplied facts. Never invent names, dates, amounts, "
        "or details, and do not restate the note's content.\n"
        "- If facts are sparse, write a shorter sentence.\n"
        "- Output the sentence only: no preamble, no quotes, no bullet."
    ),
    # Prompt caching is a free win when it engages; note Haiku 4.5's minimum
    # cacheable prefix is 4096 tokens, so this short prompt may not cache.
    "cache_control": {"type": "ephemeral"},
}]


def prior_spend(cur) -> float:
    cur.execute("SELECT note FROM pipeline_runs WHERE note LIKE '%cost_usd=%'")
    total = 0.0
    for (note,) in cur.fetchall():
        m = re.search(r"cost_usd=([0-9.]+)", note)
        if m:
            total += float(m.group(1))
    return total


def main() -> int:
    client = anthropic.Anthropic()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pipeline_runs (source, status) "
                "VALUES ('contextualize', 'running') RETURNING run_id")
            run_id = cur.fetchone()[0]
        conn.commit()

        try:
            with conn.cursor() as cur:
                cur.execute("SELECT chunk_id, source_type, source_id FROM chunks "
                            "WHERE context_text IS NULL")
                pending = {(st, sid): cid for cid, st, sid in cur.fetchall()}
                spent = prior_spend(cur)
                facts_map = {}
                if pending:
                    for stype, sid, jid, text, facts in build_all(cur):
                        if (stype, sid) in pending:
                            facts_map[(stype, sid)] = (text, facts)

            if not pending:
                print("no chunks pending enrichment — nothing to do")
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE pipeline_runs SET finished_at = now(), "
                        "status = 'ok', rows_in = 0, rows_out = 0, "
                        "note = 'cost_usd=0.0000' WHERE run_id = %s", (run_id,))
                conn.commit()
                return 0

            requests = []
            est_in_tokens = 0
            sys_tokens = len(SYSTEM[0]["text"]) // 4
            for (stype, sid), cid in sorted(pending.items()):
                text, facts = facts_map[(stype, sid)]
                prompt = f"FACTS:\n{facts}\n\nNOTE:\n{text}"
                est_in_tokens += sys_tokens + len(prompt) // 4 + 10
                requests.append(Request(
                    custom_id=f"chunk-{cid}",
                    params=MessageCreateParamsNonStreaming(
                        model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM,
                        messages=[{"role": "user", "content": prompt}])))

            projected = (est_in_tokens * IN_PER_MTOK
                         + len(requests) * 80 * OUT_PER_MTOK) / 1_000_000
            print(f"{len(requests)} chunks to contextualize; projected cost "
                  f"~${projected:.2f} (prior spend ${spent:.2f})")
            if spent + projected > COST_CEILING_USD:
                raise RuntimeError(
                    f"projected total ${spent + projected:.2f} exceeds the "
                    f"${COST_CEILING_USD} ceiling — stopping before submission")

            in_tok = out_tok = cache_read = 0
            ok_count = 0
            failed_ids = []
            for start in range(0, len(requests), BATCH_SIZE):
                chunk_reqs = requests[start:start + BATCH_SIZE]
                batch = client.messages.batches.create(requests=chunk_reqs)
                print(f"batch {batch.id}: {len(chunk_reqs)} requests submitted")
                while True:
                    batch = client.messages.batches.retrieve(batch.id)
                    if batch.processing_status == "ended":
                        break
                    time.sleep(20)
                print(f"batch {batch.id}: ended "
                      f"(ok={batch.request_counts.succeeded} "
                      f"err={batch.request_counts.errored})")

                updates = []
                for result in client.messages.batches.results(batch.id):
                    cid = int(result.custom_id.split("-", 1)[1])
                    if result.result.type == "succeeded":
                        msg = result.result.message
                        sentence = next(
                            (b.text for b in msg.content if b.type == "text"),
                            "").strip()
                        if sentence:
                            updates.append((sentence, cid))
                            in_tok += msg.usage.input_tokens
                            out_tok += msg.usage.output_tokens
                            cache_read += msg.usage.cache_read_input_tokens or 0
                        else:
                            failed_ids.append(cid)
                    else:
                        failed_ids.append(cid)
                with conn.cursor() as cur:
                    cur.executemany(
                        "UPDATE chunks SET context_text = %s WHERE chunk_id = %s",
                        updates)
                conn.commit()
                ok_count += len(updates)

            cost = (in_tok * IN_PER_MTOK + out_tok * OUT_PER_MTOK) / 1_000_000
            note = (f"cost_usd={cost:.4f} in_tokens={in_tok} "
                    f"out_tokens={out_tok} cache_read={cache_read} "
                    f"failed={len(failed_ids)}")
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE pipeline_runs SET finished_at = now(), status = %s, "
                    "rows_in = %s, rows_out = %s, note = %s WHERE run_id = %s",
                    ("ok" if not failed_ids else "partial",
                     len(requests), ok_count, note, run_id))
            conn.commit()

            print(f"context written for {ok_count}/{len(requests)} chunks")
            print(f"usage: {in_tok} in / {out_tok} out tokens "
                  f"(cache_read {cache_read}); actual cost ${cost:.4f}")
            if failed_ids:
                print(f"FAILED chunk_ids ({len(failed_ids)}): {failed_ids[:50]}")
                print("re-run this script to retry the failures")
        except Exception:
            conn.rollback()
            err = traceback.format_exc()
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE pipeline_runs SET finished_at = now(), "
                    "status = 'failed', error = %s WHERE run_id = %s",
                    (err, run_id))
            conn.commit()
            print(err, file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

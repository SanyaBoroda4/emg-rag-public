"""Record the rewriter's outputs for 20 fixed cases (WO17) so the unit tests
can run without an LLM.

    python evals/make_rewrite_fixtures.py            # writes the fixture
    python evals/make_rewrite_fixtures.py --check    # re-run and diff

Cases: 10 standalone questions asked WITH a non-refuse history (must pass
through byte-identical) and 10 follow-ups (must resolve). History turns are
built from golden_conversations.csv keys (question, expected standalone,
route, expected answer as the answer text). Re-run only when the prompt or
model changes; the test asserts on the recorded outputs.
"""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrieval.rewrite import Turn, build_prompt, rewrite  # noqa: E402

ROOT = Path(__file__).resolve().parent
GOLD = ROOT / "golden_conversations.csv"
OUT = ROOT / "fixtures" / "rewrite_cases.json"


def load_turns():
    turns = {}
    for r in csv.DictReader(open(GOLD, encoding="utf-8")):
        turns[(r["conv_id"], int(r["turn"]))] = r
    return turns


def hist(turns, *keys):
    out = []
    for cid, n in keys:
        r = turns[(cid, n)]
        q = r["question"]
        sa = q if r["expected_standalone"] == "SAME" else r["expected_standalone"]
        out.append(Turn(question=q, standalone_question=sa,
                        route=r["expected_route"], answer=r["expected_answer"]))
    return out


def cases(turns):
    T = lambda *k: hist(turns, *k)  # noqa: E731
    standalone = [
        ("S01", "What is the capital of France?", T(("C3", 1), ("C3", 2))),
        ("S02", "Which jobs had a template wasted because cabinets weren't ready?", T(("C6", 1))),
        ("S03", "How many wasted templates have we had in total?", T(("C2", 1))),
        ("S04", "Which jobs included a waterfall edge?", T(("C5", 1))),
        ("S05", "How many jobs do we have in Mount Pleasant?", T(("C1", 1))),
        ("S06", "What is our overall quote-to-moved-forward conversion rate?", T(("C9", 1))),
        ("S07", "How many jobs did Leo install in the first half of 2026?", T(("C10", 1))),
        ("S08", "Were there jobs where we could not get material into the building?", T(("C4", 1))),
        ("S09", "How many quotes have we issued in total?", T(("C13", 1), ("C13", 2))),
        ("S10", "Which salesperson had the most wasted templates?", T(("C12", 1))),
    ]
    followups = [
        ("F01", ("C1", 2), T(("C1", 1))),
        ("F02", ("C1", 3), T(("C1", 1), ("C1", 2))),
        ("F03", ("C2", 2), T(("C2", 1))),
        ("F04", ("C2", 3), T(("C2", 1), ("C2", 2))),
        ("F05", ("C3", 2), T(("C3", 1))),
        ("F06", ("C4", 2), T(("C4", 1))),
        ("F07", ("C5", 3), T(("C5", 1), ("C5", 2))),
        ("F08", ("C9", 2), T(("C9", 1))),
        ("F09", ("C10", 3), T(("C10", 1), ("C10", 2))),
        ("F10", ("C14", 2), T(("C14", 1))),
    ]
    out = []
    for cid, q, h in standalone:
        out.append({"id": cid, "kind": "standalone", "question": q,
                    "history": [t.__dict__ for t in h],
                    "expected_standalone": True, "expected_question": q})
    for cid, key, h in followups:
        r = turns[key]
        out.append({"id": cid, "kind": "followup", "question": r["question"],
                    "history": [t.__dict__ for t in h],
                    "expected_standalone": False,
                    "expected_question": r["expected_standalone"]})
    return out


def main() -> int:
    turns = load_turns()
    cs = cases(turns)
    old = json.load(open(OUT, encoding="utf-8")) if OUT.exists() else {}
    old_by = {c["id"]: c for c in old.get("cases", [])} if old else {}
    results, cost = [], 0.0
    for c in cs:
        h = [Turn(**t) for t in c["history"]]
        captured = {}

        def call(prompt, captured=captured):
            from retrieval.rewrite import _call_model
            parsed, usage = _call_model(prompt)
            captured["raw"] = parsed
            captured["usage"] = (usage.input_tokens, usage.output_tokens)
            return parsed
        res = rewrite(c["question"], h, call=call)
        rec = dict(c)
        rec["model_output"] = captured.get("raw")
        rec["result"] = {"standalone": res.standalone, "question": res.question,
                         "reason": res.reason}
        rec["prompt_chars"] = len(build_prompt(c["question"], h))
        ok = (res.standalone == c["expected_standalone"] and
              (res.question == c["question"] if c["expected_standalone"]
               else bool(res.question)))
        flag = "ok " if ok else "XX "
        changed = ""
        if c["id"] in old_by and old_by[c["id"]].get("result") != rec["result"]:
            changed = "  (CHANGED vs recorded)"
        print(f"{flag}{c['id']} {c['kind']:<10} {c['question'][:55]!r}\n"
              f"     -> standalone={res.standalone} {res.question!r}{changed}")
        results.append(rec)
    if "--check" in sys.argv:
        return 0
    OUT.parent.mkdir(exist_ok=True)
    json.dump({"model": "claude-haiku-4-5", "temperature": 0,
               "cases": results}, open(OUT, "w", encoding="utf-8"), indent=1)
    print(f"wrote {OUT} ({len(results)} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

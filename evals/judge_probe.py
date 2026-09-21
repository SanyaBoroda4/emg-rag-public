"""Judge-strictness probe (WO7 §3): re-run named golden questions end to end,
print the judge's system prompt VERBATIM plus its full verdict for each.

  python3 evals/judge_probe.py 28 30

Investigation tool: does not change any prompt. If the judge is genuinely too
strict, propose a change and show before/after — never silently loosen.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.db import get_conn
from evals.harness import (JUDGE_SYSTEM, embed_questions, judge_answer,
                           judge_model_for, load_chunk_rows, load_golden,
                           run_generation, run_retrieval, run_router)
from retrieval.answer import ANSWER_MODEL


def main() -> int:
    want = set(sys.argv[1:]) or {"28", "30"}
    rows = [r for r in load_golden() if r["id"] in want]
    judge = judge_model_for(ANSWER_MODEL)
    print("=" * 70)
    print("JUDGE SYSTEM PROMPT (verbatim):")
    print("=" * 70)
    print(JUDGE_SYSTEM)
    print("=" * 70)

    qvecs = embed_questions(rows)
    with get_conn() as conn, conn.cursor() as cur:
        for row in rows:
            route, reason, _ = run_router(row)
            ret = run_retrieval(cur, row["question"], qvecs[row["id"]])
            rec = run_generation(cur, row, ret, route)
            chunk_rows = load_chunk_rows(cur, rec["chunk_ids"])
            verdict, _ = judge_answer(row, rec, chunk_rows, judge)
            print(f"\n### Q{row['id']} ({route}) {row['question']}")
            print(f"expected: {row['expected_answer']}")
            print(f"answer:\n{rec['answer']}")
            if rec["sql"]:
                print(f"SQL: {rec['sql']}")
            print(f"\njudge={judge} verdict: correct={verdict.get('correct')} "
                  f"faithful={verdict.get('faithful')}")
            print(f"judge reason: {verdict.get('reason')}")
            if verdict.get("unsupported_claims"):
                print(f"unsupported: {verdict['unsupported_claims']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

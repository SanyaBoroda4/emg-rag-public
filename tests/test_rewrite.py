"""Unit tests for retrieval.rewrite (WO17). No LLM: model outputs for the 21
fixed cases were recorded once by evals/make_rewrite_fixtures.py.

    python -m pytest tests/test_rewrite.py -q     # or: python tests/test_rewrite.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrieval.rewrite import Turn, rewrite  # noqa: E402

FIX = Path(__file__).resolve().parent.parent / "evals" / "fixtures" / "rewrite_cases.json"
CASES = json.load(open(FIX, encoding="utf-8"))["cases"]


def _run(case):
    hist = [Turn(**t) for t in case["history"]]
    return rewrite(case["question"], hist,
                   call=lambda prompt, out=case["model_output"]: out)


def test_fixture_has_twenty_one_cases_ten_and_eleven():
    kinds = [c["kind"] for c in CASES]
    assert len(CASES) == 21
    assert kinds.count("standalone") == 10 and kinds.count("followup") == 11


def test_was_x_better_names_both_sides():
    """WO20 F11: "Was 2023 better?" after a 2024 conversion-rate turn must
    keep the comparison and name both years."""
    c = next(c for c in CASES if c["id"] == "F11")
    r = _run(c)
    assert r.standalone is False
    assert "2023" in r.question and "2024" in r.question, r.question
    assert any(w in r.question.lower() for w in ("better", "higher", "than", "compare")), r.question


def test_standalone_cases_pass_through_byte_identical():
    for c in CASES:
        if c["kind"] != "standalone":
            continue
        r = _run(c)
        assert r.standalone is True, c["id"]
        assert r.question == c["question"], c["id"]  # verbatim, not the model's text


def test_followup_cases_resolve_to_recorded_rewrite():
    for c in CASES:
        if c["kind"] != "followup":
            continue
        r = _run(c)
        assert r.standalone is False, c["id"]
        assert r.question == c["result"]["question"], c["id"]
        assert r.question != c["question"], c["id"]  # it did rewrite


def test_no_history_is_standalone_without_a_call():
    called = []
    r = rewrite("And in 2025?", [], call=lambda p: called.append(p))
    assert r.standalone and r.question == "And in 2025?" and not called


def test_refused_turns_never_appear_in_the_prompt():
    """WO20: a refuse in the middle is skipped; the on-topic turns around it
    still reach the model (C15: quiet jobs, refuse, 'those quiet jobs')."""
    hist = [Turn("How many jobs went quiet after a quote?",
                 "How many jobs went quiet after a quote?", "structured", "1306"),
            Turn("What is the capital of Spain?", "What is the capital of Spain?",
                 "refuse", "This system only answers questions about EMG's data"),
            Turn("How many wasted templates have we had?",
                 "How many wasted templates have we had?", "structured", "512")]
    seen = {}
    r = rewrite("How many of those quiet jobs were quoted in 2025?", hist,
                call=lambda p: (seen.setdefault("p", p),
                                {"standalone": False,
                                 "question": "How many jobs that went quiet after a quote were quoted in 2025?",
                                 "reason": "those = quiet jobs"})[1])
    assert "Spain" not in seen["p"] and "refuse" not in seen["p"]
    assert "quiet after a quote" in seen["p"] and "Turn 2" in seen["p"] and "Turn 3" not in seen["p"]
    assert r.standalone is False and r.history_used == 2


def test_all_refused_history_is_standalone_without_a_call():
    called = []
    hist = [Turn("What is the capital of France?", "What is the capital of France?",
                 "refuse", "This system only answers questions about EMG's data")]
    r = rewrite("And how many jobs in Kiawah Island?", hist,
                call=lambda p: called.append(p))
    assert r.standalone and not called and "refuse" in r.reason
    assert r.question == "And how many jobs in Kiawah Island?"


def test_model_failure_fails_open():
    hist = [Turn("How many jobs has Salesperson G sold?",
                 "How many jobs has Salesperson G sold?", "structured", "1198")]

    def boom(prompt):
        raise RuntimeError("api down")
    r = rewrite("And in 2025?", hist, call=boom)
    assert r.standalone and r.question == "And in 2025?"


def test_unparseable_or_empty_rewrite_passes_through():
    hist = [Turn("How many jobs has Salesperson G sold?",
                 "How many jobs has Salesperson G sold?", "structured", "1198")]
    assert rewrite("And in 2025?", hist, call=lambda p: None).standalone
    assert rewrite("And in 2025?", hist,
                   call=lambda p: {"standalone": False, "question": "  "}).standalone


def test_only_last_three_turns_are_used():
    hist = [Turn(f"q{i}", f"q{i}", "structured", "a") for i in range(6)]
    seen = {}
    rewrite("and those?", hist,
            call=lambda p: (seen.setdefault("p", p),
                            {"standalone": True, "question": "x"})[1])
    assert "Turn 3" in seen["p"] and "Turn 4" not in seen["p"]


def test_refuses_do_not_consume_history_slots():
    """Three on-topic turns with refuses between them: all three are used."""
    hist = []
    for i in range(3):
        hist.append(Turn(f"q{i}", f"q{i}", "structured", "a"))
        hist.append(Turn("off topic", "off topic", "refuse", "no"))
    seen = {}
    rewrite("and those?", hist,
            call=lambda p: (seen.setdefault("p", p),
                            {"standalone": True, "question": "x"})[1])
    assert "Turn 3" in seen["p"] and "off topic" not in seen["p"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"{len(fns)} tests passed")

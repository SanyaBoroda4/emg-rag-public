"""Pure metric functions for the eval harness. No I/O, no API calls.

Ranking metrics operate on an ordered list of retrieved chunk_ids and a set
of gold (relevant) chunk_ids.
"""

import math


def recall_at_k(ranked, gold, k):
    """Fraction of gold ids present in the top-k of the ranking."""
    if not gold:
        return None
    return len(set(ranked[:k]) & set(gold)) / len(set(gold))


def mrr(ranked, gold):
    """Reciprocal rank of the first gold id (0 if none retrieved)."""
    gold = set(gold)
    for i, cid in enumerate(ranked, start=1):
        if cid in gold:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked, gold, k=10):
    """Binary-relevance NDCG@k."""
    gold = set(gold)
    if not gold:
        return None
    dcg = sum(1.0 / math.log2(i + 1)
              for i, cid in enumerate(ranked[:k], start=1) if cid in gold)
    ideal = sum(1.0 / math.log2(i + 1)
                for i in range(1, min(len(gold), k) + 1))
    return dcg / ideal if ideal else 0.0


def ranking_metrics(ranked, gold):
    """The full Tier-2 metric set for one ranking."""
    return {
        "recall@5": recall_at_k(ranked, gold, 5),
        "recall@10": recall_at_k(ranked, gold, 10),
        "recall@20": recall_at_k(ranked, gold, 20),
        "mrr": mrr(ranked, gold),
        "ndcg@10": ndcg_at_k(ranked, gold, 10),
    }


def mean_of(records, key):
    """Mean of records[i][key], skipping None; None if nothing to average."""
    vals = [r[key] for r in records if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else None


ROUTES = ["structured", "semantic", "hybrid", "refuse"]


def confusion_matrix(pairs):
    """pairs: [(expected, predicted)] -> (matrix dict, accuracy)."""
    matrix = {e: {p: 0 for p in ROUTES} for e in ROUTES}
    correct = 0
    for expected, predicted in pairs:
        if predicted not in ROUTES:
            predicted = "refuse"  # defensive bucket for junk output
        matrix[expected][predicted] += 1
        if expected == predicted:
            correct += 1
    accuracy = correct / len(pairs) if pairs else None
    return matrix, accuracy


def format_confusion(matrix):
    lines = [f"{'expected \\ predicted':<22}" +
             "".join(f"{r:>12}" for r in ROUTES)]
    for e in ROUTES:
        lines.append(f"{e:<22}" +
                     "".join(f"{matrix[e][p]:>12}" for p in ROUTES))
    return "\n".join(lines)


import re

# number with optional thousands separators and an optional K/M/B scale
# suffix ("$2.59M", "1,198", "72.5")
_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*\s*([KMBkmb])?\b")
_SCALE = {"k": 1e3, "m": 1e6, "b": 1e9}


def extract_numbers(text):
    """All numbers in a text, thousands separators stripped and K/M/B
    suffixes expanded. Each returned as (value, had_suffix)."""
    out = []
    for m in _NUM_RE.finditer(text or ""):
        raw = m.group().rstrip("KMBkmb").strip()
        val = float(raw.replace(",", ""))
        suffix = m.group(1)
        if suffix:
            val *= _SCALE[suffix.lower()]
        out.append((val, suffix is not None))
    return out


def extract_number(text):
    """First number in a text (normalized); None if absent."""
    nums = extract_numbers(text)
    return nums[0][0] if nums else None


def _value_present(exp_val, exp_rounded, answer_nums, tolerance):
    """Is exp_val among the answer's numbers? Suffix-rounded forms ("2.59M")
    on either side compare with 1% relative tolerance; plain integers compare
    exactly; other floats within ±tolerance."""
    for act_val, act_rounded in answer_nums:
        if exp_rounded or act_rounded:
            if exp_val and abs(act_val - exp_val) / abs(exp_val) <= 0.01:
                return True
        elif float(exp_val).is_integer() and float(act_val).is_integer():
            if exp_val == act_val:
                return True
        elif abs(act_val - exp_val) <= tolerance:
            return True
    return False


def numeric_match(expected_text, answer_text, tolerance=0.5):
    """Structured scoring by numeric comparison.

    Single-number expected answers compare first-number-to-any-answer-number.
    List-shaped expected answers (>= 2 numbers, e.g. "Natalia 1198, Alex
    996, ...") require EVERY expected number to appear in the answer — the
    scorer no longer grades a seven-row list by its first element (WO7 Q5).
    K/M/B suffixes and thousands separators are normalized with a 1% relative
    tolerance for rounded forms (WO7 Q10). Returns None when the expected
    answer contains no number.
    """
    expected = extract_numbers(expected_text)
    if not expected:
        return None
    answer_nums = extract_numbers(answer_text)
    if not answer_nums:
        return False
    return all(_value_present(v, r, answer_nums, tolerance)
               for v, r in expected)

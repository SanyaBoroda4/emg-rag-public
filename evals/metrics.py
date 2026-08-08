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


def extract_number(text):
    """First number in a text (commas tolerated); None if absent.

    Used for structured-answer scoring: skips markdown bold markers etc.
    """
    import re
    m = re.search(r"-?\d[\d,]*\.?\d*", text or "")
    if not m:
        return None
    return float(m.group().replace(",", ""))


def numeric_match(expected_text, answer_text, tolerance=0.5):
    """Structured scoring: numbers extracted from both, compared.

    Exact for integers (counts); ±tolerance for non-integers (sq ft etc.).
    Returns None when the expected answer has no number to compare.
    """
    exp = extract_number(expected_text)
    if exp is None:
        return None
    act = extract_number(answer_text)
    if act is None:
        return False
    if float(exp).is_integer() and float(act).is_integer():
        return exp == act
    return abs(exp - act) <= tolerance

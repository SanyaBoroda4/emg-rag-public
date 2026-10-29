"""Measure the local cross-encoder's resident memory before wiring it in.

Prints RSS before torch import, after model load, and after a realistic
50-pair predict. The deploy gate: if post-predict RSS exceeds ~400 MiB the
local backend must not be used on this host (set RERANK_BACKEND=voyage).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def rss_mib() -> float:
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    return -1


def main() -> int:
    print(f"baseline RSS:        {rss_mib():7.1f} MiB")
    from sentence_transformers import CrossEncoder
    print(f"after imports:       {rss_mib():7.1f} MiB")
    model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2",
                         max_length=512, device="cpu")
    print(f"after model load:    {rss_mib():7.1f} MiB")
    pairs = [("job went quiet after quote",
              "Follow-up activity for a canceled job: no movement since the "
              "quote was issued in February. " * 5)] * 50
    scores = model.predict(pairs, batch_size=16, show_progress_bar=False)
    peak = rss_mib()
    print(f"after 50-pair score: {peak:7.1f} MiB (sample score {scores[0]:.3f})")
    print(f"GATE: {'PASS (< 400 MiB)' if peak < 400 else 'FAIL — use RERANK_BACKEND=voyage'}")
    return 0 if peak < 400 else 1


if __name__ == "__main__":
    sys.exit(main())

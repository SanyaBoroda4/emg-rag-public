"""Model prices, $/MTok (input, output). One copy (WO12): the query CLI,
the eval harness and the Langfuse spans all cost a call the same way.

Sonnet 5 at intro pricing through 2026-08-31 (unchanged here on purpose:
the eval's historical cost figures are comparable only if the table is)."""

PRICES = {"claude-haiku-4-5": (1.0, 5.0), "claude-sonnet-5": (2.0, 10.0)}


def cost_of(model, usage):
    """USD for one Anthropic response's usage; 0 for unknown models."""
    inp, out = PRICES.get(model, (0, 0))
    return (usage.input_tokens * inp + usage.output_tokens * out) / 1e6

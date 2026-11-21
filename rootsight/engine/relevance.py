"""Search-quality measures computed from ESCI labels (unlabelled results count as Irrelevant)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from rootsight.data.loaders import GAIN

NO_EXACT_POSITION = 11


def relevance_at_10(result_ids: Sequence[str], labels: Mapping[str, str]) -> float | None:
    """Share of the returned top-10 labelled Exact or Substitute; None when there are no results."""
    top = result_ids[:10]
    if not top:
        return None
    return sum(labels.get(p, "I") in ("E", "S") for p in top) / len(top)


def _dcg(gains: Sequence[float]) -> float:
    return sum(g / math.log2(pos + 2) for pos, g in enumerate(gains))


def ndcg_at_10(result_ids: Sequence[str], labels: Mapping[str, str]) -> float:
    """nDCG of the top-10 against the best possible ordering of the labelled products (0 if no results)."""
    gains = [GAIN[labels.get(p, "I")] for p in result_ids[:10]]
    ideal = sorted((GAIN[label] for label in labels.values()), reverse=True)[:10]
    return _dcg(gains) / _dcg(ideal) if gains and _dcg(ideal) > 0 else 0.0


def first_exact_position(result_ids: Sequence[str], labels: Mapping[str, str]) -> int:
    """1-based position of the first Exact result in the top-10, or 11 when there is none."""
    for pos, p in enumerate(result_ids[:10], start=1):
        if labels.get(p) == "E":
            return pos
    return NO_EXACT_POSITION

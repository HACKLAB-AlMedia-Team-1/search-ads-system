"""Users' search behaviour: which query a session types, and how it clicks through the results."""

from __future__ import annotations

import numpy as np
import pandas as pd

from rootsight.data.german import to_english

ATTRACT = {"E": 0.55, "S": 0.25, "C": 0.10, "I": 0.03}
POSITION_DECAY = 0.85
FOREIGN_SHARE = 0.20  # shoppers in DE / US who search in the other language (English / German)


class QueryPool:
    """Real ESCI queries of every market with their labels; sessions draw queries by popularity."""

    def __init__(self, queries: pd.DataFrame, labels: pd.DataFrame):
        self._by_market = {m: g.reset_index(drop=True) for m, g in queries.groupby("market")}
        self._foreign: dict[str, pd.DataFrame] = {}
        if "DE" in self._by_market and "US" in self._by_market:
            german = self._by_market["DE"]
            self._foreign = {"DE": german.assign(query=german["query"].map(to_english)), "US": german}
        self.query_ids = {
            (m, q): i
            for m, g in [*self._by_market.items(), *self._foreign.items()]
            for i, q in zip(g["query_id"], g["query"], strict=True)
        }
        self.labels = {
            (m, q): dict(zip(g["product_id"], g["esci_label"], strict=True))
            for (m, q), g in labels.groupby(["market", "query_id"])
        }

    def top_exact_by_query(self, market: str, n_queries: int) -> dict[str, list[str]]:
        """The `n_queries` most searched queries (most searched first), each with its products labelled Exact."""
        top = self._by_market[market].nlargest(n_queries, "weight")
        return {
            query: [p for p, label in self.labels.get((market, query_id), {}).items() if label == "E"]
            for query_id, query in zip(top["query_id"], top["query"], strict=True)
        }

    def top_exact_products(self, market: str, n_queries: int) -> set[str]:
        """Products labelled Exact for the `n_queries` most searched queries: the shop's top sellers."""
        return {p for products in self.top_exact_by_query(market, n_queries).values() for p in products}

    def popular(self, market: str, n: int) -> list[str]:
        """The `n` most frequent queries of a market (for suggestion chips)."""
        return self._by_market[market].nlargest(n, "weight")["query"].tolist()

    def draw(self, market: str, n: int, rng: np.random.Generator) -> list[tuple[int, str]]:
        """`n` (query_id, query text) pairs, frequent queries more often; in DE/US some are in the other language."""
        out = self._pick(self._by_market[market], n, rng)
        if market in self._foreign and n:
            foreign = self._pick(self._foreign[market], n, rng)
            out = [
                f if switch else o
                for o, f, switch in zip(out, foreign, rng.random(n) < FOREIGN_SHARE, strict=True)
            ]
        return out

    @staticmethod
    def _pick(pool: pd.DataFrame, n: int, rng: np.random.Generator) -> list[tuple[int, str]]:
        weights = pool["weight"].to_numpy()
        picks = rng.choice(len(pool), size=n, p=weights / weights.sum())
        return list(
            zip(
                pool["query_id"].to_numpy()[picks].tolist(),
                pool["query"].to_numpy()[picks].tolist(),
                strict=True,
            )
        )


def click_position(
    labels: dict[str, str], product_ids: tuple[str, ...], rng: np.random.Generator
) -> int | None:
    """1-based position of the (first) clicked result, or None. P(click) = attract(label) x 0.85^(pos-1)."""
    if not product_ids:
        return None
    attract = np.array([ATTRACT[labels.get(p, "I")] for p in product_ids])
    decay = POSITION_DECAY ** np.arange(len(product_ids))
    hits = np.flatnonzero(rng.random(len(product_ids)) < attract * decay)
    return int(hits[0]) + 1 if len(hits) else None

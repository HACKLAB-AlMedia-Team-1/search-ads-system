"""Plain-language description of every scenario: what breaks, what a shopper sees, what the agent should find."""

from __future__ import annotations

from pathlib import Path

import yaml

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "scenarios"

JOURNEY = ("L1", "AD1", "INV1")
FAILURES = ("L1", "S12", "AD1", "INV1", "S1", "S3", "S2", "S7", "S15")
INNOCENT = ("EV1", "DQ1")

GUIDE: dict[str, dict[str, str]] = {
    "L1": {
        "title": "Foreign-language searches fail",
        "what": "A config change makes the store accept only its own language. Normally both English and German work in the "
        "German and the US store; now searches in the other language find nothing.",
        "shop": "Choose the country in the store (Deliver to), press Simulate it, then search in the other language "
        "(English in Germany, German in the US): no results. The local language still works.",
        "metrics": "The zero-result rate updates after searches in the selected store. The received-orders total stays "
        "flat after an empty search and resumes accumulating after a search finds products.",
        "agent": "Incident blaming `search-language[<country>] = local only`; rules out an indexing failure and a mobile release.",
        "where": "The country chosen in the store (Germany or the US)",
    },
    "S1": {
        "title": "Search shows unrelated products",
        "what": "A new search-ranker release sorts products by title length and brand size instead of matching the query.",
        "shop": "Search anything in the store: the results have nothing to do with what you typed.",
        "metrics": "Relevance and search CTR fall, orders fall. Ad spend stays normal, so ad money is wasted.",
        "agent": "Incident blaming the release `search-ranker v2.0.0`.",
        "where": "All markets, all devices",
    },
    "AD1": {
        "title": "Ad budget burns by mid-morning",
        "what": "A pacing-service release makes the German campaign ignore its hourly spending limits.",
        "shop": "In the German store the sponsored product at the top of the results disappears once the budget is gone.",
        "metrics": "Ad spend runs far ahead of the hourly plan, driven by impressions (not by price), then drops to zero.",
        "agent": "Incident blaming `pacing-service 1.4.0`, Germany only; rules out a cost-per-click spike and a traffic spike.",
        "where": "Germany (campaign CMP-DE)",
    },
    "S12": {
        "title": "German search returns nothing",
        "what": "A config change makes the German store read search text with English rules.",
        "shop": "Deliver to Deutschland and search 'kopfhörer': no results. Other countries are fine.",
        "metrics": "Germany only: zero-result searches jump, clicks and orders fall, while visits stay stable.",
        "agent": "Incident blaming the config `search-analyzer[DE] = english`; rules out an indexing failure and a mobile release.",
        "where": "Germany only",
    },
    "INV1": {
        "title": "Top sellers out of stock",
        "what": "A supplier delivery for the best-selling products never arrived.",
        "shop": "The products are found, but show 'Currently unavailable' and cannot be added to the cart.",
        "metrics": "Product views stay stable, add-to-cart and orders fall, in-stock rate of top products drops to zero.",
        "agent": "Incident blaming the overdue purchase order; rules out under-ordering and a reorder failure.",
        "where": "Germany",
    },
    "S3": {
        "title": "Android app finds nothing",
        "what": "A new Android release sends a broken stock filter, so every search comes back empty.",
        "shop": "Set Device to 'Android app' and search: 'No results'. Web and iOS still work.",
        "metrics": "Android only: zero-result rate near 100%, clicks and orders collapse.",
        "agent": "Incident blaming the release `android-app 5.2.0`.",
        "where": "Android only",
    },
    "S2": {
        "title": "Part of the catalogue is missing",
        "what": "An index rebuild only loaded 60% of the products.",
        "shop": "Searches return fewer products; some find nothing.",
        "metrics": "Searchable products drop 40%, zero-result rate rises.",
        "agent": "Incident blaming the job `index-build #812`.",
        "where": "All markets",
    },
    "S7": {
        "title": "Good products pushed down the page",
        "what": "A ranking config boosts the newest products over the most relevant ones.",
        "shop": "The right product is still on the page but lower; newer items are on top.",
        "metrics": "The first exact match sits lower, ranking quality falls. Zero-result rate is unchanged.",
        "agent": "Incident blaming the config `ranking.boost_recency 0.0 -> 0.8`.",
        "where": "All markets",
    },
    "S15": {
        "title": "Search shows yesterday's results",
        "what": "The search cache keeps results for a day instead of a minute.",
        "shop": "Results are served from cache (age shown next to the result count); prices and stock can be out of date.",
        "metrics": "Cache hit rate near 100%, result age climbs for hours.",
        "agent": "Incident blaming the config `search-cache.ttl 60s -> 86400s`.",
        "where": "All markets",
    },
    "EV1": {
        "title": "Black Friday ad push (planned)",
        "what": "Marketing doubles the ad budget for a new, less interested audience. It is in the calendar.",
        "shop": "More 'Sponsored' traffic; nothing is broken.",
        "metrics": "Ad spend and paid visits double, paid conversion drops.",
        "agent": "An info card 'planned event', and NO incident.",
        "where": "All markets, paid traffic",
    },
    "DQ1": {
        "title": "Search data arrives late",
        "what": "One hour of search events reaches the database two hours late.",
        "shop": "Nothing changes for shoppers.",
        "metrics": "Search numbers look far too low for one hour, then are repaired.",
        "agent": "A 'data delay' notice that closes by itself, and NO incident.",
        "where": "Search events table",
    },
}

# What to open in the store to see each journey step as a shopper (market, device, search text).
# L1 follows the store country and searches in the other language.
FOREIGN_QUERY = {"DE": "headphones", "US": "kopfhörer"}
SHOP_VIEW = {"S12": ("DE", "web", "kopfhörer"), "AD1": ("DE", "web", "kopfhörer"), "INV1": ("DE", "web", "kopfhörer"),
             "S3": ("US", "android", "headphones"), "S1": ("US", "web", "headphones")}  # fmt: skip


def custom_scenarios() -> tuple[str, ...]:
    """Ids of the scenarios written on the 'Add a scenario' page; their plain-language guide is added to GUIDE."""
    ids = []
    for path in sorted(SCENARIO_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if raw.get("guide"):
            GUIDE[raw["id"]] = raw["guide"]
            ids.append(raw["id"])
    return tuple(ids)

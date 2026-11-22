"""ShopLens web shop: a small local web server (standard library only) with a JSON API on the live search engine."""

from __future__ import annotations

import json
import logging
import threading
import zlib
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import pandas as pd

from rootsight.data.german import wrong_language
from rootsight.engine.search import SearchFilters, SearchResult
from rootsight.sim.ads import CAMPAIGNS
from rootsight.sim.faults import FOREIGN_LANGUAGE_BLOCKED

if TYPE_CHECKING:
    from common import Runtime

logger = logging.getLogger(__name__)

STATIC = Path(__file__).with_name("shop")
TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}
PLATFORMS = ("web", "android", "ios")
FETCH, HOME_ROW = 40, 6
EMOJI = {
    "headphone": "🎧", "earbud": "🎧", "headset": "🎧", "speaker": "🔊", "phone": "📱", "laptop": "💻", "keyboard": "⌨️",
    "mouse": "🖱️", "camera": "📷", "watch": "⌚", "tv": "📺", "lamp": "💡", "light": "💡", "chair": "🪑", "bed": "🛏️",
    "sofa": "🛋️", "shoe": "👟", "sneaker": "👟", "boot": "🥾", "sandal": "🩴", "sock": "🧦", "shirt": "👕", "dress": "👗",
    "jacket": "🧥", "coat": "🧥", "hat": "🧢", "glove": "🧤", "bag": "👜", "backpack": "🎒", "glasses": "🕶️", "ring": "💍",
    "toy": "🧸", "game": "🎮", "puzzle": "🧩", "book": "📚", "pen": "🖊️", "knife": "🔪", "cup": "☕", "mug": "☕",
    "bottle": "🧴", "coffee": "☕", "dog": "🐶", "cat": "🐱", "car": "🚗", "bike": "🚲", "ball": "⚽", "tent": "⛺",
    "plant": "🪴", "flower": "💐", "christmas": "🎄", "gift": "🎁", "candle": "🕯️", "clock": "🕰️", "guitar": "🎸",
    "battery": "🔋", "tool": "🧰", "soap": "🧼", "brush": "🪥", "umbrella": "☂️", "baby": "🍼", "kitchen": "🍳",
}  # fmt: skip


class Shop:
    """Turns search results into shop-ready products (rating, delivery badge, picture) and answers the API calls."""

    def __init__(self, rt: Runtime):
        self.rt = rt
        frame = pd.read_parquet(
            rt.settings.data_processed_dir / "products.parquet",
            columns=["market", "product_id", "title", "brand", "bullet_point"],
        )
        text = lambda value: value if isinstance(value, str) else ""
        self.info = {
            (r.market, r.product_id): (text(r.title), text(r.brand), text(r.bullet_point)[:400])
            for r in frame.itertuples(index=False)
        }
        # top sellers (the products purchase orders replenish) carry a Best Seller badge and many good reviews
        self.best = {market: set(docs.tolist()) for market, docs in rt.pipeline.sim.top_products.items()}

    def _items(self, market: str, result: SearchResult) -> list[dict]:
        cat = self.rt.pipeline.sim.engine.catalogues[market]
        items = []
        for rank, (doc, pid, price) in enumerate(
            zip(result.doc_idx, result.product_ids, result.prices, strict=True), start=1
        ):
            title, brand, bullet = self.info.get((market, pid), (pid, "", ""))
            h = zlib.crc32(pid.encode())
            lowered, best = title.lower(), doc in self.best[market]
            items.append({
                "id": pid, "doc": doc, "rank": rank, "title": title, "brand": brand, "bullet": bullet, "price": round(price, 2),
                "stock": 0 if cat.delisted[doc] else int(cat.stock[doc]), "best": best,
                "rating": round(4.4 + (h % 6) / 10, 1) if best else round(3.3 + (h % 13) / 10, 1),
                "reviews": 2000 + (h >> 8) % 18000 if best else int(10 ** (1 + ((h >> 8) % 220) / 100)), "fast": h % 3 == 0,
                "emoji": next((e for word, e in EMOJI.items() if word in lowered), "📦"),
            })  # fmt: skip
        return items

    def _campaign(self, market: str) -> dict:
        """Is the market's ad campaign still delivering today (budget left)?"""
        pacer, now = self.rt.pipeline.sim.pacer, self.rt.now
        return {"spent": round(pacer.spent(market, now), 2), "budget": pacer.budget(market, now),
                "active": pacer.delivering(market, now)}  # fmt: skip

    def _search(
        self, query: str, market: str, platform: str, filters: SearchFilters, limit: int
    ) -> SearchResult:
        with self.rt.lock:
            return self.rt.pipeline.sim.engine.search(
                query, market, platform, filters, self.rt.now, limit=limit
            )

    def home(self, market: str) -> dict:
        """Popular searches and two product rows for the landing page."""
        popular = self.rt.pipeline.sim.funnel.pool.popular(market, 8)
        rows = [
            {
                "query": q,
                "items": self._items(market, self._search(q, market, "web", SearchFilters(), HOME_ROW)),
            }
            for q in popular[:2]
        ]
        return {"popular": popular, "rows": rows}

    def search(self, params: dict[str, str]) -> dict:
        """Search results plus the sponsored slot and plain-language notes about anything unusual."""
        market, platform, query = params["market"], params["device"], params["q"].strip()
        low, high = float(params.get("min") or 0), float(params.get("max") or 0)
        filters = SearchFilters(
            in_stock=params.get("in_stock") == "1" or None, min_price=low or None, max_price=high or None
        )
        result = self._search(query, market, platform, filters, FETCH)
        items = self._items(market, result)
        campaign = self._campaign(market)
        typed = params.get("auto") != "1"  # a tab that only refreshed itself is not a shopper action
        log = partial(self.rt.log_ux, market=market, platform=platform, query=query, session=params.get("sid", ""))
        if typed:
            log("search", value=result.latency_ms)
        notes = []
        if result.zero_result:
            if typed:
                log("zero_result")
            notes.append(
                f"The {market} store accepts only its own language right now, so this search returned nothing."
                if self.rt.pipeline.sim.faults.active(FOREIGN_LANGUAGE_BLOCKED, self.rt.now, market)
                and wrong_language(query, market)
                else "This search returned nothing."
            )
        if not campaign["active"]:
            if typed:
                log("no_sponsored")
            notes.append(
                f"No sponsored product: the {market} ad campaign has spent its daily budget (EUR {campaign['spent']:.0f} of {campaign['budget']:.0f})."
            )
        sold_out = sum(i["stock"] <= 0 for i in items[:10])
        if sold_out >= 3:
            notes.append(f"{sold_out} of the first 10 results are out of stock.")
        if result.cache_hit and result.result_age_min >= 5:
            notes.append(f"These results come from a cache and are {result.result_age_min:.0f} minutes old.")
        sponsored = items[0] if campaign["active"] and items else None  # shown even when sold out; its Add button is then disabled
        return {"query": query, "total": result.total_matches, "latency_ms": round(result.latency_ms), "items": items,
                "sponsored": sponsored, "notes": notes}  # fmt: skip

    def add_to_cart(self, body: dict) -> dict:
        """Check live stock and price when a shopper adds a product to the cart."""
        market, doc, platform = body["market"], int(body["doc"]), body.get("device", "web")
        cat = self.rt.pipeline.sim.engine.catalogues[market]
        common = {
            "market": market,
            "platform": platform,
            "query": body.get("query", ""),
            "position": body.get("rank"),
            "session": body.get("sid", ""),
        }
        if cat.stock[doc] <= 0 or cat.delisted[doc]:
            self.rt.log_ux("cart_unavailable", **common)
            return {"ok": False}
        price = round(float(cat.price[doc]), 2)
        changed = abs(price - float(body["price"])) > 0.005
        if changed:
            self.rt.log_ux("price_mismatch", **common)
        self.rt.log_ux("add_to_cart", value=price, **common)
        return {"ok": True, "price": price, "changed": changed}

    def checkout(self, body: dict) -> dict:
        """Check live stock of every cart item before the order is placed; sold-out items block the order."""
        market, platform = body["market"], body.get("device", "web")
        cat = self.rt.pipeline.sim.engine.catalogues[market]
        unavailable = [int(d) for d in body.get("docs", []) if cat.stock[int(d)] <= 0 or cat.delisted[int(d)]]
        if unavailable:
            self.rt.log_ux("cart_unavailable", market, platform, session=str(body.get("sid", ""))[:40])
        return {"ok": not unavailable, "unavailable": unavailable}


class Handler(BaseHTTPRequestHandler):
    """Serves the static shop files and the JSON API."""

    def __init__(self, shop: Shop, *args, **kwargs):
        self.shop = shop
        super().__init__(*args, **kwargs)

    def log_message(self, *args) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        params["market"] = params.get("market") if params.get("market") in CAMPAIGNS else "US"
        params["device"] = params.get("device") if params.get("device") in PLATFORMS else "web"
        if url.path in ("/api/home", "/api/search"):
            self.shop.rt.shop_market = params["market"]  # the journey page follows the store's "Deliver to"
        try:
            if url.path == "/api/state":
                self._json({"version": self.shop.rt.store_version(params["market"])})
            elif url.path == "/api/home":
                self._json(self.shop.home(params["market"]))
            elif url.path == "/api/search":
                self._json(self.shop.search({"q": "", **params}))
            else:
                file = STATIC / ("index.html" if url.path == "/" else url.path.lstrip("/"))
                if file.suffix in TYPES and file.is_file() and file.parent == STATIC:
                    self._send(200, file.read_bytes(), TYPES[file.suffix])
                else:
                    self._send(404, b"not found", "text/plain")
        except Exception:
            logger.exception("Shop request failed: %s", url.path)
            self._json({"error": "the shop could not answer"}, 500)

    def do_POST(self) -> None:
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if body.get("market") not in CAMPAIGNS:
                self._json({"error": "unknown market"}, 400)
            elif self.path == "/api/cart":
                self._json(self.shop.add_to_cart(body))
            elif self.path == "/api/checkout":
                self._json(self.shop.checkout(body))
            elif self.path == "/api/event":
                device = body.get("device") if body.get("device") in PLATFORMS else "web"
                self.shop.rt.log_ux(
                    str(body.get("event"))[:30],
                    body["market"],
                    device,
                    str(body.get("query", ""))[:200],
                    body.get("rank"),
                    session=str(body.get("sid", ""))[:40],
                )
                self._json({"ok": True})
            else:
                self._json({"error": "not found"}, 404)
        except Exception:
            logger.exception("Shop request failed: %s", self.path)
            self._json({"error": "the shop could not answer"}, 500)


def start_shop(rt: Runtime, port: int) -> ThreadingHTTPServer:
    """Start the web shop on localhost in a background thread and return the server."""
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, Shop(rt)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info("ShopLens web shop running on http://localhost:%d", port)
    return server

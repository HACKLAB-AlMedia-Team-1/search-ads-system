"""Product pictures for the web shop, drawn in code as small SVGs (no photos, no people, nothing downloaded).

The product type is read from the title and gets its own drawing; the product's real colours (colour field
first, then the title) paint it; the product id decides every remaining detail (shape variant, detail colours,
pattern, tilt, backdrop), so two products of one type look different and one product always looks the same.
"""

from __future__ import annotations

import html
import re
import zlib
from collections.abc import Callable
from functools import cache, lru_cache
from typing import NamedTuple

# (words in the title, symbol, kind text, drawing). Order matters: the first match wins, so real product nouns
# come before words that are often only an adjective or a colour ("Lightweight pants", "Light Steel").
KINDS: list[tuple[str, str, str, str]] = [
    # compound names first: here the second word is the product ("coffee table" is a table, "tv stand" is a stand)
    (r"wigs?|hair extensions?|hair bundles?|ponytails?|lace front|human hair|braiding hair", "💇", "hair wig", "hair"),
    ((r"(?:coffee|side|end|dining|console|laptop|computer|writing|standing|bedside|night|lap|vanity|kitchen|picnic|patio)"
      r"[ -]?(?:tables?|desks?)|tablecloths?"), "🪑", "chair furniture", "chair"),
    ((r"(?:tv|monitor|laptop|plant|shoe|coat|towel|book|phone|tablet|speaker|bike)[ -]?(?:stands?|racks?|mounts?|holders?)|nightstands?"
     r"|bookshel(?:f|ves)|bookcases?|shelving"), "📦", "storage boxes", "storage"),
    (r"charging (?:stations?|docks?|pads?|stands?|cables?)|wireless chargers?", "🔋", "usb charger cable", "charger"),
    ((r"lip balm|deodorant|sunscreen|moisturizers?|cleansers?|toner|nail polish|foundation|concealer|eyeliner|eye ?shadow"
     r"|body wash|hand wash|sanitizers?|toothpaste"), "🧴", "cosmetics bottles", "cosmetics"),
    (r"swim trunks?|trunks|briefs|boxers|underwear|panties|bermudas?", "👖", "trousers clothing", "pants"),
    (r"swimsuits?|swimwear|bikinis?|rompers?|jumpsuits?|bodysuits?|onesies?|robes?|costumes?", "👗", "dress clothing", "dress"),
    (r"headphones?|earbuds?|earphones?|headsets?|airpods", "🎧", "headphones", "headphones"),
    (r"sneakers?|trainers|running shoes?|shoes?|loafers?|slippers?|clogs?|moccasins?", "👟", "sneakers shoes", "sneaker"),
    (r"boots?|booties", "🥾", "boots footwear", "boot"),
    (r"sandals?|flip[- ]flops?|slides", "🩴", "sandals footwear", "sandal"),
    (r"socks?|stockings", "🧦", "socks", "socks"),
    (r"pants?|jeans|trousers|leggings|shorts|joggers|sweatpants|chinos|tights", "👖", "trousers clothing", "pants"),
    (r"dress(es)?(?! shirts?)|skirts?|gown", "👗", "dress clothing", "dress"),
    (r"jackets?|coats?|parkas?|blazers?|vests?|windbreakers?|raincoats?", "🧥", "jacket clothing", "jacket"),
    ((r"t-?shirts?|shirts?|tees?|tops?|blouses?|hoodies?|sweaters?|sweatshirts?|polos?|tunics?|pajamas?|cardigans?"
     r"|pullovers?|jumpers?"), "👕", "t-shirt clothing", "shirt"),
    (r"gloves?|mittens?", "🧤", "gloves", "gloves"),
    (r"hats?|caps?|beanies?", "🧢", "baseball cap hat", "hat"),
    (r"backpacks?|rucksacks?", "🎒", "backpack", "backpack"),
    (r"(?<!sleeping )(?<!tea )bags?|purses?|handbags?|wallets?|totes?|luggage|suitcases?|duffels?", "👜", "handbag", "bag"),
    (r"sunglasses|glasses|eyeglasses", "🕶️", "sunglasses", "sunglasses"),
    (r"rings?|necklaces?|earrings?|bracelets?|jewelry|jewellery|pendants?|bangles?", "💍", "jewellery necklace", "jewel"),
    (r"watch(es)?|smartwatch(es)?", "⌚", "wristwatch", "watch"),
    (r"speakers?|soundbars?", "🔊", "loudspeaker bluetooth", "speaker"),
    (r"phone cases?|iphone|smartphones?|cell ?phones?|galaxy|phones?|tablets?|ipad|screen protectors?", "📱", "smartphone",
     "phone"),
    (r"laptops?|notebook computer|macbook|chromebook", "💻", "laptop computer", "laptop"),
    (r"keyboards?", "⌨️", "computer keyboard", "keyboard"),
    (r"mouse|mice|mouse ?pads?", "🖱️", "computer mouse", "mouse"),
    (r"cameras?|webcams?|gopro", "📷", "digital camera", "camera"),
    (r"tvs?|televisions?|monitors?|projectors?", "📺", "flat screen television", "tv"),
    (r"chargers?|cables?|adapters?|batter(y|ies)|power ?banks?|usb|cords?", "🔋", "usb charger cable", "charger"),
    (r"controllers?|playstation|xbox|nintendo|gaming|video games?", "🎮", "game controller", "controller"),
    (r"puzzles?", "🧩", "jigsaw puzzle", "puzzle"),
    (r"lego|toys?|dolls?|plush|stuffed|action figures?|building blocks|teddy", "🧸", "toys", "toy"),
    (r"books?|notebooks?|journals?|planners?|novel", "📚", "books stack", "book"),
    (r"pens?|pencils?|markers?|crayons?|highlighters?", "🖊️", "pens stationery", "pens"),
    (r"knife|knives|cutlery", "🔪", "kitchen knife", "knife"),
    (r"mugs?|cups?|tumblers?|glasses set", "☕", "coffee mug", "mug"),
    (r"bottles?|flasks?|thermos", "🧴", "water bottle", "bottle"),
    (r"coffee|espresso|tea", "☕", "coffee beans cup", "mug"),
    (r"plants?|planters?|seeds?|garden|succulents?|cactus", "🪴", "potted plant", "plant"),
    (r"flowers?|bouquets?|roses", "💐", "flower bouquet", "plant"),
    (r"pans?|pots?|skillets?|cookware|bakeware|kitchen|utensils?|spatula|blenders?|mixers?|toasters?|air fryers?",
     "🍳", "cookware kitchen", "cookware"),
    (r"dogs?|puppy|pets?|leash|collar", "🐶", "dog accessories", "pet"),
    (r"cats?|kittens?|litter", "🐱", "cat pet", "pet"),
    (r"fish|aquarium", "🐟", "aquarium fish", "fish"),
    (r"bikes?|bicycles?|cycling|helmets?", "🚲", "bicycle", "bike"),
    (r"cars?|trucks?|vehicles?|automotive|tires?", "🚗", "car accessories", "car"),
    (r"balls?|soccer|football|basketball|tennis|yoga|dumbbells?|kettlebells?|fitness", "⚽", "sports equipment", "ball"),
    (r"tents?|camping|sleeping bags?|hiking", "⛺", "camping tent", "tent"),
    (r"christmas|xmas|ornaments?|santa", "🎄", "christmas decoration", "xmas"),
    (r"candles?", "🕯️", "candle", "candle"),
    (r"clocks?|alarm", "🕰️", "wall clock", "clock"),
    (r"guitars?|ukulele|piano|violin|drums?", "🎸", "guitar", "guitar"),
    (r"drills?|screwdrivers?|wrench(es)?|hammers?|tools?|pliers", "🧰", "hand tools", "tools"),
    (r"soap|shampoo|conditioner|lotion|cream|serum|perfume|makeup|lipstick|mascara|skincare", "🧴", "cosmetics bottles",
     "cosmetics"),
    (r"toothbrush(es)?|brush(es)?|comb|razors?|trimmers?|hair dryers?", "🪥", "hairbrush", "brush"),
    (r"umbrellas?", "☂️", "umbrella", "umbrella"),
    (r"baby|diapers?|strollers?|pacifiers?", "🍼", "baby products", "baby"),
    (r"scales?", "⚖️", "kitchen scale", "scale"),
    (r"chairs?|stools?|desks?(?! lamps?)|tables?(?! lamps?)", "🪑", "chair furniture", "chair"),
    (r"sofas?|couch(es)?", "🛋️", "sofa", "sofa"),
    (r"beds?|pillows?|blankets?|sheets?|mattress(es)?|duvets?|comforters?|towels?|curtains?|rugs?", "🛏️", "bedding pillows",
     "bedding"),
    (r"lamps?|bulbs?|lights|lighting|lanterns?|led strips?|flashlights?", "💡", "table lamp", "lamp"),
    (r"gifts?|gift box", "🎁", "gift box", "gift"),
    (r"box(es)?|storage|organizers?|bins?|baskets?|shel(f|ves)", "📦", "storage boxes", "storage"),
]  # fmt: skip
PATTERNS = [(re.compile(rf"\b(?:{words})\b"), symbol, search, key) for words, symbol, search, key in KINDS]

# Real product colours by name; longer names win ("rose gold" before "rose").
COLOURS: dict[str, str] = {
    "black": "#2b2d33", "white": "#f7f7f5", "grey": "#9aa0a8", "gray": "#9aa0a8", "silver": "#c9ced6",
    "red": "#d6373a", "pink": "#f07fae", "rose": "#e8909c", "blue": "#2f6fd6", "navy": "#1f2f5c",
    "green": "#2f9e5a", "yellow": "#f3c72c", "gold": "#d4a93a", "orange": "#f0862a", "purple": "#7b4bc4",
    "brown": "#7a4f33", "beige": "#dccbb0", "tan": "#c9a27a", "khaki": "#b5a678", "teal": "#1f8f8c",
    "turquoise": "#36c5c0", "burgundy": "#7a1f33", "maroon": "#6e1c2c", "cream": "#f3ead6", "ivory": "#f6f1e3",
    "charcoal": "#454a52", "olive": "#6b7334", "violet": "#7b4bc4", "lavender": "#b9a4e6", "lilac": "#c3a9e0",
    "mint": "#9fe0c4", "coral": "#f47c68", "denim": "#4a6a9c", "indigo": "#3b3f8f", "magenta": "#c2337f",
    "fuchsia": "#d63a9a", "lime": "#9bd13a", "aqua": "#4fc9d6", "cyan": "#2fb8d6", "bronze": "#a9743a",
    "copper": "#b86e3f", "camel": "#c19a6b", "mustard": "#d4a52a", "peach": "#f6b89a", "steel": "#8d99a6",
    "graphite": "#4a4e57", "slate": "#5d6875", "asphalt": "#4d5258", "heather": "#a8adb5", "oatmeal": "#e3d8c3",
    "taupe": "#a3907c", "clear": "#dbe9f2", "transparent": "#dbe9f2", "gunmetal": "#4a4e57",
    "rose gold": "#e0a899", "navy blue": "#1f2f5c", "royal blue": "#2a4fc9", "sky blue": "#7cc0f0",
    "baby blue": "#a9d3f5", "steel blue": "#5f85a8", "hot pink": "#ee3f96", "army green": "#5a6b38",
    "forest green": "#2a6a41", "mint green": "#9fe0c4", "off white": "#f3efe6", "space gray": "#5a5e66",
    "space grey": "#5a5e66", "asphalt grey": "#4d5258", "asphalt gray": "#4d5258", "heather grey": "#a8adb5",
    "heather gray": "#a8adb5", "charcoal grey": "#454a52", "charcoal gray": "#454a52", "steel grey": "#8d99a6",
    "steel gray": "#8d99a6", "negro": "#2b2d33", "blanco": "#f7f7f5", "rojo": "#d6373a", "azul": "#2f6fd6",
    "verde": "#2f9e5a", "gris": "#9aa0a8", "rosa": "#f07fae", "amarillo": "#f3c72c", "naranja": "#f0862a",
    "morado": "#7b4bc4", "marron": "#7a4f33",
}  # fmt: skip
_CJK = {"ブラック": "black", "黒": "black", "ホワイト": "white", "白": "white", "レッド": "red", "赤": "red",
        "ブルー": "blue", "青": "blue", "グリーン": "green", "緑": "green", "ピンク": "pink", "グレー": "grey",
        "イエロー": "yellow", "ネイビー": "navy", "ベージュ": "beige", "ブラウン": "brown", "パープル": "purple",
        "オレンジ": "orange", "シルバー": "silver", "ゴールド": "gold"}  # fmt: skip
_TONE = {"light": 0.4, "pale": 0.5, "pastel": 0.5, "dark": -0.35, "deep": -0.3, "midnight": -0.5}
_COLOUR_RE = re.compile(
    r"\b(?:(" + "|".join(_TONE) + r")[ -])?(" + "|".join(sorted(COLOURS, key=len, reverse=True)) + r")\b"
)
_LOOSE = tuple(name for name in COLOURS if len(name) > 3 or name == "red") + tuple(_CJK)
_COLOURED = re.compile(r"colou?red")
MULTI = re.compile(r"\b(?:multi[ -]?colou?r(?:ed)?|multi|rainbow|colou?rful|assorted|tie[ -]dye)\b")
PACK = re.compile(
    r"\b(?:(\d{1,3})\s*[- ]?\s*(pack|pk|pairs?|pcs?|pieces?|count|ct|sets?)\b"
    r"|(pack|set|box|bundle|lot) of (\d{1,3})\b)"
)
TWIN = re.compile(r"\b(?:twin|double|dual)[- ]pack\b")
PIECES = {"puzzle", "toy", "tools", "storage"}  # here "100 pieces" is one product, not a pack
_PATTERN_RES = tuple(
    (name, re.compile(rf"\b(?:{words})\b"))
    for name, words in (
        ("stripes", "strip(?:e|es|ed|y)|pinstripes?"),
        ("plaid", "plaid|check(?:ed|ered)|tartan|gingham|flannel"),
        ("floral", "floral|flowers?|botanical|hawaiian"),
        ("camo", "camo|camouflage"),
        ("dots", "polka|dots?|dotted"),
        ("block", "colou?r[- ]?block(?:ed)?|two[- ]tone"),
    )
)
_BY_HASH = ("plain", "plain", "plain", "plain", "stripes", "block", "dots", "plain")
PATTERNED = {"shirt", "socks", "dress", "bedding", "gift", "phone", "umbrella"}  # may get a pattern by hash

INK, PAPER, STEEL, GOLD, WOOD, GLASS = "#2b2d33", "#f6f5f1", "#c3c9d1", "#d4a93a", "#b98a5e", "#cfe4f2"
DARK, LENS, GLOW, GREY = "#1b1d21", "#3d5a80", "#ffe9a8", "#8d949e"
BRIGHT = ("#2f6fd6", "#d6373a", "#2f9e5a", "#f0862a", "#7b4bc4", "#1f8f8c", "#f07fae", "#f3c72c",
          "#2b2d33", "#f7f7f5", "#9aa0a8", "#1f2f5c")  # fmt: skip
TECH = ("#2b2d33", "#c9ced6", "#454a52", "#f7f7f5", "#1f2f5c", "#2f6fd6")
EARTH = ("#7a4f33", "#dccbb0", "#9aa0a8", "#454a52", "#c9a27a", "#6b7334", "#1f2f5c", "#2b2d33")
DENIM = ("#4a6a9c", "#2f4a7a", "#7f9cc4", "#2b2d33", "#9aa0a8")
_TECH_KINDS = ("headphones", "speaker", "phone", "laptop", "keyboard", "mouse", "camera", "tv", "charger",
               "controller", "knife", "cookware", "scale", "tools")  # fmt: skip
PALETTES: dict[str, tuple[str, ...]] = {
    **dict.fromkeys(_TECH_KINDS, TECH),
    **dict.fromkeys(("boot", "sofa", "chair", "storage", "watch"), EARTH),
    "jewel": ("#d4a93a", "#c9ced6", "#e0a899"),
    "hair": ("#2b2d33", "#4a3222", "#7a4f33", "#c9a27a", "#d4a93a"),
    "parcel": ("#c9a27a", "#d8b48a", "#b8926a", "#9fb7c9", "#c9b7d6", "#a9c9b0", "#e2c58f"),
}
BACKDROPS = (("#fbfbfc", "#e8ebef"), ("#fcfaf7", "#eee8df"), ("#f8fafc", "#e3e9f0"), ("#faf9fc", "#e8e5ef"),
             ("#f9fbf8", "#e4ebe3"))  # fmt: skip
NO = ' stroke="none"'
FAINT = ' opacity=".4"'
SHINE = NO + ' opacity=".28"'
MIRROR = "translate(200 0) scale(-1 1)"
FONT = "system-ui,-apple-system,Segoe UI,Arial,sans-serif"
HOOD = "M76 44Q68 10 100 10Q132 10 124 44Q100 26 76 44Z"
BONE = "M70 92H130A14 14 0 1 1 146 104A14 14 0 1 1 130 116H70A14 14 0 1 1 54 104A14 14 0 1 1 70 92Z"


@cache
def _rx(words: str) -> re.Pattern[str]:
    """Compiled whole-word pattern for `words` (kept, so each one is compiled only once)."""
    return re.compile(rf"\b(?:{words})\b")


@lru_cache(maxsize=4096)
def _mix(a: str, b: str, t: float) -> str:
    """Colour `a` moved towards colour `b` by the share `t` (both as #rrggbb)."""
    pairs = ((int(a[i : i + 2], 16), int(b[i : i + 2], 16)) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in pairs)


@lru_cache(maxsize=4096)
def _lum(colour: str) -> float:
    """Perceived lightness of a #rrggbb colour, 0 (black) to 1 (white)."""
    return (0.299 * int(colour[1:3], 16) + 0.587 * int(colour[3:5], 16) + 0.114 * int(colour[5:7], 16)) / 255


def _far(a: str, b: str) -> bool:
    """Are two colours different enough to be told apart on a small picture?"""
    return sum(abs(int(a[i : i + 2], 16) - int(b[i : i + 2], 16)) for i in (1, 3, 5)) > 96


def _on(colour: str) -> str:
    """An ink that stays visible on `colour`."""
    return PAPER if _lum(colour) < 0.55 else INK


class Look(NamedTuple):
    """Everything a drawing needs to know about one product."""

    low: str  # the title in lower case
    h: int  # crc32 of the product id: the source of every "random" choice
    uid: str  # suffix that makes the ids inside the svg unique per product
    main: str  # the product's own colour
    acc: str  # second colour (details)
    third: str  # third colour (multi-coloured products, small details)
    shade: str  # tone-on-tone shade of the main colour that is visible on it
    hi: str  # highlight of the main colour
    line: str  # outline colour
    pattern: str  # plain, stripes, dots, plaid, floral, camo or block
    named: bool  # was the main colour named by the product (True) or picked by hash (False)?

    def pick(self, shift: int, n: int) -> int:
        """A stable choice 0..n-1 for this product; another `shift` gives an independent choice."""
        return (self.h >> shift) % n

    def has(self, words: str) -> bool:
        """Does the title contain one of these words (regex alternatives, whole words only)?"""
        return _rx(words).search(self.low) is not None


# ------------------------------------------------------------------------------------------------ svg pieces
# Shapes inherit the outline (stroke) of the product group; pass NO to draw one without an outline.


def _p(d: str, fill: str, more: str = "") -> str:
    return f'<path d="{d}" fill="{fill}"{more}/>'


def _ln(d: str, colour: str, width: float = 2, more: str = "") -> str:
    return f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{width}"{more}/>'


def _r(x: float, y: float, w: float, h: float, fill: str, rx: float = 0, more: str = "") -> str:
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{more}/>'


def _c(cx: float, cy: float, r: float, fill: str, more: str = "") -> str:
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}"{more}/>'


def _e(cx: float, cy: float, rx: float, ry: float, fill: str, more: str = "") -> str:
    return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}"{more}/>'


def _ring(cx: float, cy: float, r: float, colour: str, width: float, more: str = "") -> str:
    """A circle that is only a stroke."""
    return _c(cx, cy, r, "none", f' stroke="{colour}" stroke-width="{width}"{more}')


def _cord(d: str, colour: str, k: Look, width: float = 5) -> str:
    """A thick line with an outline (straps, handles, cables)."""
    return _ln(d, k.line, width + 3) + _ln(d, colour, width)


def _at(transform: str, *parts: str) -> str:
    """The parts moved, turned or scaled together."""
    return f'<g transform="{transform}">{"".join(parts)}</g>'


def _twin(k: Look, transform: str, *parts: str) -> str:
    """The parts plus a second, transformed copy behind them (pairs: socks, gloves, lenses)."""
    return f'<use href="#t{k.uid}" transform="{transform}"/><g id="t{k.uid}">{"".join(parts)}</g>'


def _clip(k: Look, d: str, inner: str) -> str:
    """`inner` shown only inside the outline `d`, with the outline drawn again on top (once per picture)."""
    return (f'<clipPath id="c{k.uid}"><path d="{d}"/></clipPath>'
            f'<g clip-path="url(#c{k.uid})" stroke="none">{inner}</g>{_p(d, "none")}')  # fmt: skip


def _pattern(k: Look, d: str, x0: int, y0: int, x1: int, y1: int) -> str:
    """The product's pattern (stripes, dots, plaid, floral, camo, colour block) inside the outline `d`."""
    if k.pattern == "plain":
        return ""
    if k.pattern == "stripes":
        step = 12 + 4 * k.pick(11, 3)
        inner = _ln("".join(f"M{x0} {y}H{x1}" for y in range(y0 + 8, y1, step)), k.acc, step // 3)
    elif k.pattern in ("dots", "floral"):
        rows = "".join(f"M{x0 + 9 * (i % 2)} {y}H{x1}" for i, y in enumerate(range(y0 + 8, y1, 15)))
        spaced = ' stroke-dasharray="0 18"'
        inner = _ln(rows, k.acc, 5, spaced)
        if k.pattern == "floral":
            inner = _ln(rows, k.acc, 10, spaced) + _ln(rows, k.third, 4, spaced)
    elif k.pattern == "plaid":
        bars = "".join(f"M{x0} {y}H{x1}" for y in range(y0 + 10, y1, 22))
        bars += "".join(f"M{x} {y0}V{y1}" for x in range(x0 + 10, x1, 22))
        inner = _ln(bars, k.acc, 7, ' opacity=".5"') + _ln(bars, k.hi, 1.5, ' opacity=".7"')
    elif k.pattern == "camo":
        v, blobs = k.h | 1, []
        for i in range(9):
            v = (v * 1103515245 + 12345) & 0x7FFFFFFF
            x, y = x0 + v % (x1 - x0), y0 + (v >> 9) % (y1 - y0)
            tone = _mix(k.main, "#000000", 0.4) if i % 2 else _mix(k.main, "#ffffff", 0.35)
            turn = f' transform="rotate({(v >> 5) % 180} {x} {y})"'
            blobs.append(_e(x, y, 10 + (v >> 17) % 9, 6 + (v >> 21) % 5, tone, turn))
        inner = "".join(blobs)
    elif k.pick(11, 2):  # colour block: the upper part ...
        inner = _r(x0, y0, x1 - x0, round((y1 - y0) * 0.38), k.acc)
    else:  # ... or one half
        inner = _r(x0, y0, (x1 - x0) // 2, y1 - y0, k.acc)
    return _clip(k, d, inner)


# ---------------------------------------------------------------------------------------------- the drawings
# Each one draws a single product inside the 200x200 picture (roughly x 25..175, y 25..165), nothing else.


def _headphones(k: Look) -> str:
    """Over-ear headphones from the front, or earbuds with their case or cable; never a head."""
    if k.has("earbuds?|in[- ]ear|earphones?|airpods|buds"):
        bud = (_e(83, 46, 6, 9, k.acc) + _r(61, 46, 10, 38, k.main, 5) + _c(68, 46, 14, k.main)
               + _c(64, 42, 4, "#fff", SHINE))  # fmt: skip
        buds = _twin(k, MIRROR, bud)
        if k.has("wired|cable|jack"):
            return (_ln("M66 84C66 152 134 152 134 84M100 135V152", k.line, 3) + _r(96, 150, 8, 14, STEEL, 2)
                    + _r(129, 98, 10, 22, k.shade, 3) + buds)  # fmt: skip
        return (buds + _r(58, 98, 84, 62, k.main, 22) + _ln("M60 120H140", k.line, 1.5, FAINT)
                + _c(100, 134, 3, k.acc) + _r(70, 105, 28, 5, "#fff", 2.5, SHINE))  # fmt: skip
    band, rx = 9 + 3 * k.pick(14, 2), (13, 7)[k.pick(17, 2)]
    arc = "M49 104C49 30 151 30 151 104"
    out = [_ln(arc, k.line, band + 4), _ln(arc, k.main, band), _ln("M72 64Q100 47 128 64", k.acc, 4),
           _r(45, 84, 8, 18, STEEL, 2), _r(147, 84, 8, 18, STEEL, 2),
           _r(56, 104, 14, 44, k.acc, 7), _r(130, 104, 14, 44, k.acc, 7),
           _r(34, 96, 28, 58, k.main, rx), _r(138, 96, 28, 58, k.main, rx)]  # fmt: skip
    if k.pick(20, 2):
        out += [_c(48, 125, 7, k.acc), _c(152, 125, 7, k.acc)]
    else:
        out += [_r(39, 104, 5, 30, "#fff", 2.5, SHINE), _r(143, 104, 5, 30, "#fff", 2.5, SHINE)]
    if k.has("headsets?|gaming|mic|microphone"):
        out += [_ln("M48 154C48 178 74 174 84 162", k.line, 3), _c(87, 160, 5, k.shade)]
    return "".join(out)


def _sneaker(k: Look) -> str:
    """A shoe from the side: low or high sneaker with laces, or a slip-on."""
    sole = (PAPER, k.acc, "#d9b88a", INK)[k.pick(14, 4)]
    if k.has("loafers?|slippers?|slip[- ]ons?|moccasins?|flats|clogs?|mules?"):
        out = [_p("M34 148V118Q36 106 48 108Q72 130 104 112L126 116Q168 122 174 148Z", k.main),
               _p("M104 112L126 116L122 127L100 122Z", k.acc)]  # fmt: skip
    else:
        top = 66 if k.has("high[- ]tops?|mid[- ]tops?|basketball") else 90
        upper = (f"M34 148V{top + 18}Q34 {top + 4} 46 {top + 6}Q58 {top + 22} 74 {top + 8}L84 {top - 4}"
                 f"Q92 {top - 8} 98 {top}L138 124Q170 128 174 148Z")  # fmt: skip
        out = [_p(upper, k.main)]
        style = k.pick(17, 3)
        if style == 0:
            out.append(_ln("M66 146L80 114M78 146L92 118", k.acc, 5))
        elif style == 1:
            out.append(_ln("M42 138Q92 142 118 122", k.acc, 5))
        else:
            out.append(_p(f"M34 148V{top + 22}Q50 {top + 24} 54 148Z", k.acc))
        if k.pick(20, 2):
            out.append(_p("M155 128Q171 131 174 148H147Q156 140 155 128Z", k.shade))
        lace = (PAPER, k.acc, INK)[k.pick(23, 3)]
        if not _far(lace, k.main):
            lace = _on(k.main)
        ys = [round(top + (124 - top) * (0.12 + 0.25 * i)) for i in range(4)]
        ties = "".join(f"M{94 + 10 * i} {y + 8}L{102 + 10 * i} {y + 1}" for i, y in enumerate(ys))
        out.append(_ln(ties, lace, 3))
    out += [_r(30, 144, 148, 16, sole, 7), _ln("M40 153H168", k.line, 1.5, FAINT)]
    return "".join(out)


def _boot(k: Look) -> str:
    """A boot from the side: tall or ankle shaft, laces, elastic side or lined cuff."""
    top = 62 if k.has("ankle|chelsea|hiking|chukka|booties|work") else (40, 52)[k.pick(14, 2)]
    sole = (INK, "#6b4a35", "#d9b88a")[k.pick(23, 3)]
    out = [_p(f"M52 {top}H98V106Q100 118 124 122Q160 128 162 148H52Z", k.main),
           _p("M147 129Q160 133 162 148H138Q148 140 147 129Z", k.shade)]  # fmt: skip
    if k.has("chelsea"):
        out.append(_p(f"M66 {top + 12}H84L80 108H70Z", INK))
    elif k.has("rain|rubber|wellington|wellies"):
        out.append(_r(52, top + 10, 46, 6, k.acc))
    elif k.has("hiking|work|combat|lace|laced|martens") or k.pick(17, 2):
        out.append(_ln("".join(f"M84 {y}H97" for y in range(top + 20, 104, 12)), k.acc, 3))
    if k.has("fur|snow|winter|lined|shearling|fleece"):
        out.append(_r(49, top - 3, 52, 14, PAPER, 6))
    elif k.pick(20, 3) == 0:
        out.append(_r(49, top - 3, 52, 12, k.acc, 5))
    out += [_r(48, 146, 118, 12, sole, 4), _r(48, 152, 32, 10, sole, 2)]
    return "".join(out)


def _sandal(k: Look) -> str:
    """A pair of sandals from above: flip-flops or slides."""
    sole = (k.shade, "#d9b88a", INK, k.main)[k.pick(14, 4)]
    strap = k.acc if sole == k.main else k.main
    one = [_p("M100 34C120 34 126 58 124 96C123 126 118 164 100 164C82 164 77 126 76 96C74 58 80 34 100 34Z", sole),
           _e(100, 104, 16, 50, "#fff", NO + ' opacity=".16"')]  # fmt: skip
    if k.has("slides?|sliders?") or (not k.has("flip[- ]flops?|thongs?") and k.pick(17, 2)):
        one.append(_p("M75 72Q100 58 125 72V100Q100 88 75 100Z", strap))
    else:
        one += [_cord("M100 66Q84 78 78 106M100 66Q116 78 122 106", strap, k, 6), _c(100, 66, 3, k.line, NO)]
    return _at("translate(-27 2) rotate(-6 100 100)", _twin(k, "translate(54 -4) rotate(12 100 100)", *one))


def _socks(k: Look) -> str:
    """A pair of socks laid flat: crew or ankle length, with cuff, heel and toe."""
    low_cut = k.has("ankle|no[- ]show|low[- ]cut|short|trainer|liner|invisible")
    top = 78 if low_cut else (36, 52)[k.pick(14, 2)]
    d = f"M76 {top}H116V104Q116 112 124 116L146 128Q160 136 156 150Q150 164 132 160L92 146Q76 140 76 122Z"
    tip = k.acc if k.pick(17, 2) else k.shade
    cuff = (k.acc, k.shade, k.main)[k.pick(20, 3)]
    one = [_p(d, k.main), _pattern(k, d, 76, top + 16, 160, 112),
           _p("M146 128Q160 136 156 150Q150 164 132 160Q146 148 146 128Z", tip),
           _p("M76 124Q76 140 92 146Q98 132 90 120Z", tip), _r(76, top, 40, 14, cuff, 2),
           _ln("".join(f"M{x} {top + 3}V{top + 11}" for x in (84, 92, 100, 108)), k.line, 1.5, FAINT)]  # fmt: skip
    return _at("translate(-2 0)", _twin(k, "translate(-28 -4)", *one))


def _pants(k: Look) -> str:
    """Trousers laid flat: skinny, regular or wide legs, shorts, joggers, jeans details."""
    short = k.has("shorts?|trunks|boxers?|briefs|bermuda")
    soft = k.has("joggers?|sweatpants|leggings?|tights|yoga|track|pajamas?|lounge|athletic|gym|running|swim")
    if k.has("skinny|slim|leggings?|tights|yoga|tapered"):
        fit = 0
    elif k.has("wide|flared?|baggy|cargo|palazzo|loose|bootcut"):
        fit = 2
    else:
        fit = k.pick(14, 3)
    xo, xi = (54, 92) if short else ((64, 91), (56, 93), (46, 95))[fit]
    hem, fork = (104, 78) if short else (164, 82)
    d = f"M62 42H138L{200 - xo} {hem}H{200 - xi}L100 {fork}L{xi} {hem}H{xo}Z"
    out = [_p(d, k.main), _pattern(k, d, 40, 42, 160, hem)]
    if k.pick(17, 4) == 0 or k.has("track|side stripes?"):
        out.append(_ln(f"M66 46L{xo + 4} {hem - 3}M134 46L{196 - xo} {hem - 3}", k.acc, 4))
    if not k.has("leggings?|tights"):
        out.append(_ln("M82 43Q80 58 61 60M118 43Q120 58 139 60", k.line, 1.5, FAINT))
    if k.has("cargo") and not short:
        out += [_r(63, 96, 17, 22, k.shade, 2), _r(120, 96, 17, 22, k.shade, 2)]
    if soft:
        band = k.acc if k.pick(20, 2) else k.shade
        out += [_r(62, 30, 76, 13, band, 4), _ln("M95 43V58M105 43V61", k.line, 2)]
        if k.has("joggers?|sweatpants|track") and not short:
            out += [_r(xo, hem - 8, xi - xo, 8, k.shade, 2), _r(200 - xi, hem - 8, xi - xo, 8, k.shade, 2)]
    else:
        out += [_r(62, 30, 76, 13, k.main, 2), _ln("M74 30V43M126 30V43M100 43V68", k.line, 1.5, FAINT),
                _c(100, 36.5, 2.5, k.acc)]  # fmt: skip
    return "".join(out)


def _torso(sleeve: str, neck: str, hem: int = 160) -> str:
    """Outline of a top laid flat; `sleeve` is long, short or none, `neck` the path of the neckline."""
    left, right = {
        "long": ("L62 46L36 64L24 138L44 142L64 86", "V86L156 142L176 138L164 64L138 46"),
        "short": ("L62 46L30 66L42 90L64 80", "V80L158 90L170 66L138 46"),
        "none": ("L68 44Q74 66 64 86", "V86Q126 66 132 44"),
    }[sleeve]
    return f"M78 40{left}V{hem}H136{right}L122 40{neck}Z"


def _cuffs(colour: str) -> str:
    """The two cuffs of long sleeves."""
    return _p("M25 130L24 138L44 142L47 134Z", colour) + _p("M175 130L176 138L156 142L153 134Z", colour)


def _shirt(k: Look) -> str:
    """A top laid flat: T-shirt, long sleeve, polo, button shirt, tank top, sweater or hoodie."""
    hood = k.has("hoodies?|hooded")
    knit = hood or k.has("sweaters?|sweatshirts?|pullovers?|cardigans?|jumpers?|fleece|knit|crewneck")
    collar = k.has("polos?|button|oxford|flannel|blouses?|dress shirts?|henley|rugby")
    buttoned = k.has("button|oxford|flannel|blouses?|dress shirts?|cardigans?")
    if k.has("tank|sleeveless|camisole|cami|singlet"):
        sleeve = "none"
    elif knit or k.has("long[- ]sleeves?|flannel|thermal|pajamas?|tunics?"):
        sleeve = "long"
    elif k.has("short[- ]sleeves?|t-?shirts?|tees?|polos?"):
        sleeve = "short"
    else:
        sleeve = ("short", "short", "long")[k.pick(14, 3)]
    depth = 54 if collar else 64 if k.has("v[- ]neck") or (not knit and k.pick(17, 4) == 0) else 0
    neck = f"L100 {depth}L78 40" if depth else "Q100 56 78 40"
    d = _torso(sleeve, neck)
    trim = k.acc if k.pick(20, 3) == 0 else k.shade
    out = [_p(HOOD, k.shade)] if hood else []
    out += [_p(d, k.main), _pattern(k, d, 24, 40, 176, 160), _p(f"M78 40Q100 46 122 40{neck}Z", k.shade)]
    if sleeve != "none":
        seam = 86 if sleeve == "long" else 80
        out.append(_ln(f"M64 {seam}L62 46M136 {seam}L138 46", k.line, 1.5, FAINT))
    if collar:
        leaf = k.acc if k.pick(20, 3) == 0 else k.main
        out += [_p("M78 40L100 54L87 66Z", leaf), _p("M122 40L100 54L113 66Z", leaf),
                _ln("M100 54V160" if buttoned else "M100 54V84", k.line, 1.5, FAINT)]  # fmt: skip
        out += [_c(100, y, 2, _on(k.main), NO) for y in (range(68, 156, 20) if buttoned else (66, 77))]
    else:
        out.append(_ln(f"M122 40{neck}", trim, 3.5))
    if knit:
        out += [_cuffs(trim), _p("M64 151H136V160H64Z", trim)]
    if hood:
        out.append(_p("M80 151V132L89 118H111L120 132V151Z", "none"))
        out.append(_ln("M92 52V78M108 52V80", _on(k.main), 2.5))
    elif not collar and k.pattern == "plain":  # a chest print, band or pocket on plain tops
        print_ = k.pick(23, 6)
        if print_ == 0:
            out.append(_c(100, 98, 15, k.acc))
        elif print_ == 1:
            out.append(_p("M65 90H135V104H65Z", k.acc, NO))
        elif print_ == 2:
            out.append(_p("M110 76H126V90Q118 96 110 90Z", "none"))
        elif print_ == 3:
            out.append(_r(108, 80, 16, 5, k.acc, 2, NO))
    return "".join(out)


def _jacket(k: Look) -> str:
    """A jacket laid flat or on a hanger hook: zip jacket, bomber, puffer, blazer or coat, vest."""
    vest = k.has("vests?|gilet|sleeveless")
    puffer = k.has("puffer|down|quilted|padded|bubble|winter|insulated")
    formal = k.has("blazers?|coats?|trench|suit|peacoat|overcoat") and not puffer
    depth, style = (92 if formal else 58), k.pick(14, 4)
    neck = f"L100 {depth}L78 40"
    d = _torso("none" if vest else "long", neck, 164)
    if k.has("hooded|hoodie|parkas?|rain|raincoats?|anorak|windbreakers?"):
        out = [_p(HOOD, k.shade)]
    else:
        out = [_ln("M100 44V24Q100 14 109 18", GREY, 3)]
    out.append(_p(d, k.main))
    if style == 2 and not vest and not formal:  # sleeves in the second colour
        out.append(_p("M62 46L36 64L24 138L44 142L64 86ZM138 46L164 64L176 138L156 142L136 86Z", k.acc))
    if puffer or (style == 3 and not formal):
        out.append(_clip(k, d, _ln("".join(f"M20 {y}H180" for y in range(72, 164, 18)), k.line, 2, FAINT)))
    else:
        out.append(_pattern(k, d, 24, 40, 176, 164))
    out.append(_p(f"M78 40Q100 46 122 40{neck}Z", PAPER if formal else k.shade))
    if formal:
        out += [_p("M78 40L100 92L80 70L90 62Z", k.shade), _p("M122 40L100 92L120 70L110 62Z", k.shade),
                _ln("M100 92V164", k.line, 1.5), _c(106, 108, 3, k.acc), _c(106, 128, 3, k.acc),
                _r(70, 126, 20, 6, k.shade, 1), _r(110, 126, 20, 6, k.shade, 1)]  # fmt: skip
    else:
        zipper = STEEL if k.pick(17, 2) else k.acc
        leaf = k.acc if style == 1 else k.shade
        out += [_p("M78 40L100 58L84 68L74 50Z", leaf), _p("M122 40L100 58L116 68L126 50Z", leaf),
                _ln("M100 58V164", zipper, 2.5), _ln("M72 128L88 122M128 128L112 122", k.line, 2, FAINT)]  # fmt: skip
        if style == 1:  # bomber: knitted hem and cuffs
            out.append(_p("M64 154H136V164H64Z", k.acc))
            if not vest:
                out.append(_cuffs(k.acc))
    return "".join(out)


def _dress(k: Look) -> str:
    """A dress or a skirt laid flat."""
    if k.has("skirts?") and not k.has("dress(es)?"):
        hem = 128 if k.has("mini|short|skort") else 156
        d = f"M72 62H128L152 {hem}Q100 {hem + 12} 48 {hem}Z"
        return (_p(d, k.main) + _pattern(k, d, 48, 62, 152, hem + 8)
                + _ln(f"M88 64L80 {hem + 3}M100 64V{hem + 5}M112 64L120 {hem + 3}", k.line, 1.5, FAINT)
                + _r(72, 52, 56, 12, k.acc if k.pick(14, 2) else k.shade, 3))  # fmt: skip
    hem = 140 if k.has("mini|short") else 162 if k.has("maxi|long|gown") else (150, 158)[k.pick(14, 2)]
    d = (f"M84 34L78 62Q76 76 82 84L52 {hem}Q100 {hem + 12} 148 {hem}L118 84Q124 76 122 62L116 34H108"
         "Q100 48 92 34Z")  # fmt: skip
    out = []
    if k.has("sleeves?|t-?shirt|sweater|wrap") or k.pick(17, 3) == 0:
        out += [_p("M84 34L62 48L70 66L80 56Z", k.main), _p("M116 34L138 48L130 66L120 56Z", k.main)]
    out += [_p(d, k.main), _pattern(k, d, 48, 34, 152, hem + 8), _ln("M92 34Q100 48 108 34", k.shade, 3)]
    if k.pick(20, 2):
        out.append(_r(80, 79, 40, 8, k.acc, 2))
    else:
        out.append(_ln(f"M60 {hem - 16}Q100 {hem - 5} 140 {hem - 16}", k.line, 1.5, FAINT))
    return "".join(out)


def _hat(k: Look) -> str:
    """A cap from the side, a beanie or a brimmed hat."""
    if k.has("beanies?|knit|knitted|winter|skull|wool"):
        out = [_c(100, 48, 13, k.acc)] if k.has("pom|bobble") or k.pick(17, 2) else []
        out += [_p("M56 128Q56 54 100 54Q144 54 144 128Z", k.main),
                _ln("M78 62Q70 90 72 122M100 56V122M122 62Q130 90 128 122", k.line, 1.5, FAINT),
                _r(52, 120, 96, 28, k.acc if k.pick(14, 2) else k.main, 7),
                _ln("".join(f"M{x} 125V143" for x in range(64, 140, 12)), k.line, 1.5, FAINT)]  # fmt: skip
        return "".join(out)
    if k.has("bucket|sun hats?|fedora|straw|brim|boonie|cowboy|panama"):
        return (_e(100, 124, 70, 17, k.main) + _p("M68 122Q66 64 100 64Q134 64 132 122Q100 132 68 122Z", k.main)
                + _p("M68 108Q100 118 132 108V122Q100 132 68 122Z", k.acc))  # fmt: skip
    front = k.pick(14, 3) == 0  # trucker cap: front panel in the second colour
    out = [_p("M44 126Q44 64 96 64Q136 64 138 126Z", k.main)]
    if front:
        out.append(_p("M96 64Q136 64 138 126H118Q116 92 96 64Z", k.acc))
    out += [_ln("M96 64Q84 94 86 126M96 64Q116 92 118 126", k.line, 1.5, FAINT),
            _p("M134 112Q160 108 174 124Q156 134 134 127Z", k.acc if k.pick(20, 2) else k.main),
            _c(96, 62, 4, k.acc)]  # fmt: skip
    if k.pick(17, 2):
        out.append(_r(120, 92, 11, 9, k.main if front else k.acc, 2))
    return "".join(out)


def _gloves(k: Look) -> str:
    """A pair of mittens with knitted cuffs (the garment alone, laid flat)."""
    cuff = k.acc if k.pick(14, 2) else k.shade
    detail = (_r(71, 100, 42, 8, k.acc, 0, NO), _c(92, 96, 8, k.acc),
              _ln("M82 60V84M92 56V84M102 60V84", k.line, 1.5, FAINT))[k.pick(17, 3)]  # fmt: skip
    one = [_p("M114 96Q132 82 137 98Q139 112 114 126Z", k.main), _p("M70 152V84Q70 50 92 50Q114 50 114 84V152Z", k.main),
           detail, _r(66, 140, 52, 24, cuff, 5),
           _ln("".join(f"M{x} 144V160" for x in (76, 84, 92, 100, 108)), k.line, 1.5, FAINT)]  # fmt: skip
    return _at("translate(-38 0)", _twin(k, "translate(276 0) scale(-1 1)", *one))


def _backpack(k: Look) -> str:
    """A backpack from the front."""
    pocket = k.acc if k.pick(14, 2) else k.shade
    out = [_cord("M86 50Q86 26 100 26Q114 26 114 50", k.shade, k, 4),
           _r(45, 108, 14, 42, k.shade, 5), _r(141, 108, 14, 42, k.shade, 5),
           _p("M56 96Q56 44 100 44Q144 44 144 96V150Q144 162 132 162H68Q56 162 56 150Z", k.main),
           _ln("M64 82Q100 62 136 82", k.line, 2, FAINT), _r(98, 68, 4, 10, k.acc, 2)]  # fmt: skip
    if k.pick(17, 2):
        out += [_r(70, 106, 60, 46, pocket, 10), _ln("M76 117H124", k.line, 2, FAINT)]
    else:
        out.append(_p("M70 152V118Q100 100 130 118V152Z", pocket))
    if k.pick(20, 2):
        out.append(_r(88, 128, 24, 9, _on(pocket), 2, NO + ' opacity=".8"'))
    return "".join(out)


def _bag(k: Look) -> str:
    """A handbag, tote or duffel; wallets and suitcases have their own drawings."""
    if k.has("wallets?|card holders?|billfold|coin purses?|clutch"):
        metal = GOLD if k.pick(14, 2) else STEEL
        return (_r(56, 58, 52, 22, k.acc, 3) + _r(66, 62, 52, 22, PAPER, 3) + _r(40, 70, 120, 80, k.main, 10)
                + _r(46, 76, 108, 68, "none", 7, ' stroke-dasharray="3 3"' + FAINT)
                + _p("M128 98H160V122H128Q120 110 128 98Z", k.shade) + _c(139, 110, 4, metal))  # fmt: skip
    if k.has("luggage|suitcases?|carry[- ]on|trolley"):
        if k.pick(14, 2):
            front = _ln("M74 62V146M87 62V146M100 62V146M113 62V146M126 62V146", k.line, 2, FAINT)
        else:
            front = _r(68, 96, 64, 48, k.shade, 6) + _ln("M74 106H126", k.line, 2, FAINT)
        return (_ln("M84 54V30H116V54", GREY, 5) + _c(72, 160, 6, INK) + _c(128, 160, 6, INK)
                + _r(58, 52, 84, 104, k.main, 10) + front + _r(90, 46, 20, 8, k.shade, 3)
                + _r(118, 62, 14, 9, k.acc, 2))  # fmt: skip
    strap = k.acc if k.pick(14, 2) else k.shade
    if k.has("duffels?|duffles?|gym|sports?|weekender|travel"):
        return (_cord("M70 100Q70 58 100 58Q130 58 130 100", strap, k) + _r(34, 86, 132, 70, k.main, 30)
                + _ln("M52 98H148", k.line, 2, FAINT) + _ln("M66 88V154M134 88V154", strap, 6)
                + _r(92, 112, 16, 12, _on(k.main), 2, NO + ' opacity=".7"'))  # fmt: skip
    body = "M52 84H148L156 156Q156 162 150 162H50Q44 162 44 156Z"
    out = [_cord("M72 86Q72 40 100 40Q128 40 128 86", strap, k), _p(body, k.main)]
    if k.has("totes?|shopping|canvas|shopper|beach|grocery|reusable"):
        stitches = ' stroke-dasharray="4 3"' + FAINT
        out += [_pattern(k, body, 44, 84, 156, 162), _ln("M53 95H147", k.line, 1.5, stitches)]
        if k.pattern == "plain" and k.pick(17, 2):
            out.append(_c(100, 128, 16, k.acc))
    else:
        out += [_p("M52 84H148L144 112Q100 130 56 112Z", k.shade),
                _r(94, 113, 12, 11, GOLD if k.pick(17, 2) else STEEL, 2)]  # fmt: skip
    return "".join(out)


def _sunglasses(k: Look) -> str:
    """Sunglasses or glasses from the front: round, aviator or square frame."""
    clear = k.has("reading|blue light|eyeglasses|readers") or not k.has("sunglasses|sun|polarized|uv")
    lens = GLASS if clear else (INK, k.acc, "#5b4636", LENS)[k.pick(14, 4)]
    more = f' stroke="{k.main}" stroke-width="5" fill-opacity="{0.45 if clear else 0.88}"'
    shape = 0 if k.has("round|circle") else 1 if k.has("aviators?|pilot") else k.pick(17, 3)
    if shape == 0:
        left = _c(66, 103, 25, lens, more)
    elif shape == 1:
        left = _p("M42 86H90Q94 86 93 92Q90 126 66 126Q44 126 41 92Q40 86 42 86Z", lens, more)
    else:
        left = _r(40, 84, 52, 38, lens, 12, more)
    extra = _ln("M88 87H112", k.main, 3) if shape == 1 else ""
    return (_ln("M41 92L27 86M159 92L173 86M91 97Q100 89 109 97", k.main, 5) + extra
            + _twin(k, MIRROR, left, _ln("M52 98L62 91", "#fff", 3, ' opacity=".45"')))  # fmt: skip


def _jewel(k: Look) -> str:
    """Jewellery alone: a ring with a stone, a necklace with a pendant, earrings or a bangle."""
    metal, gem = k.main, k.acc
    if k.has("necklaces?|pendants?|chains?|chokers?|lockets?"):
        chain = "M54 36Q56 118 100 128Q144 118 146 36"
        pendant = (_p("M100 154C78 140 82 124 91 124Q100 124 100 133Q100 124 109 124C118 124 122 140 100 154Z", gem),
                   _p("M100 128Q116 150 100 158Q84 150 100 128Z", gem), _c(100, 142, 13, metal) + _c(100, 142, 6, gem),
                   _r(94, 128, 12, 30, metal, 3))[k.pick(14, 4)]  # fmt: skip
        return _ln(chain, k.line, 1) + _ln(chain, metal, 4, ' stroke-dasharray="0 5"') + pendant
    if k.has("earrings?|studs?"):
        one = [_ln("M72 66V86", metal, 2), _c(72, 62, 5, metal), _p("M72 84Q90 112 72 124Q54 112 72 84Z", gem),
               _e(67, 106, 3, 6, "#fff", SHINE)]  # fmt: skip
        return _twin(k, MIRROR, *one)
    if k.has("bracelets?|bangles?|anklets?"):
        beads = _e(100, 104, 54, 36, "none", f' stroke="{gem}" stroke-width="8" stroke-dasharray="0 17"')
        return (_e(100, 104, 54, 36, "none", f' stroke="{k.line}" stroke-width="10"')
                + _e(100, 104, 54, 36, "none", f' stroke="{metal}" stroke-width="7"')
                + (beads if k.has("beads?|beaded|charms?") or k.pick(14, 2) else _c(100, 141, 8, gem)))  # fmt: skip
    band = _e(100, 122, 36, 38, "none", f' stroke="{k.line}" stroke-width="11"') + _e(
        100, 122, 36, 38, "none", f' stroke="{metal}" stroke-width="8"'
    )
    if k.has("bands?|wedding") and not k.has("diamonds?|stones?|gem"):
        engraved = f' stroke="{k.hi}" stroke-width="2" stroke-dasharray="2 5"'
        return band + _e(100, 122, 36, 38, "none", engraved)
    return (band + _p("M82 78L91 66H109L118 78L100 96Z", gem)
            + _ln("M82 78H118M91 66L100 78L109 66M100 78V96", "#fff", 1.5, ' opacity=".6"'))  # fmt: skip


def _watch(k: Look) -> str:
    """A watch alone, strap laid straight: analogue with hands, or a smartwatch."""
    case = (STEEL, GOLD, INK, k.acc)[k.pick(14, 4)]
    out = [_r(81, 28, 38, 144, k.main, 8), _ln("M81 56H119M81 144H119", k.line, 1.5, FAINT),
           _ln("M100 152V165", k.line, 3, ' stroke-dasharray="0 6"' + FAINT)]  # fmt: skip
    if k.has("smart ?watch(es)?|fitness|trackers?|fitbit|garmin|digital|apple watch"):
        out += [_r(134, 91, 5, 14, case, 2), _r(66, 62, 68, 76, case, 18), _r(72, 68, 56, 64, "#14161a", 13),
                _ring(100, 100, 17, k.acc, 5, ' stroke-dasharray="80 107"'),
                _ring(100, 100, 9, k.third, 5, ' stroke-dasharray="38 57"')]  # fmt: skip
    else:
        face = (PAPER, "#14161a", _mix(k.main, "#ffffff", 0.8))[k.pick(17, 3)]
        ink = _on(face)
        out += [_r(136, 94, 7, 12, case, 2), _c(100, 100, 38, case), _c(100, 100, 30, face),
                _ln("M100 74V79M100 121V126M74 100H79M121 100H126", ink, 2.5),
                _ln("M100 100V83", ink, 3.5, f' transform="rotate({k.pick(20, 12) * 30} 100 100)"'),
                _ln("M100 100V76", ink, 2, f' transform="rotate({k.pick(24, 12) * 30 + 15} 100 100)"'),
                _c(100, 100, 3, k.acc)]  # fmt: skip
    return "".join(out)


def _speaker(k: Look) -> str:
    """A speaker: portable pill, box with drivers, smart speaker or soundbar."""
    if k.has("soundbars?|sound bar"):
        return (_r(22, 98, 156, 34, k.main, 9) + _r(30, 104, 140, 22, k.shade, 6)
                + _ln("M38 115H162", k.line, 4, ' stroke-dasharray="0 8"' + FAINT) + _c(100, 127, 2, k.acc, NO))  # fmt: skip
    if k.has("portable|bluetooth|waterproof|wireless|outdoor"):
        style = 0
    elif k.has("bookshelf|tower|studio|subwoofer|stereo|computer|pc|party"):
        style = 1
    elif k.has("smart|echo|alexa|mini|home"):
        style = 2
    else:
        style = k.pick(14, 3)
    if style == 0:
        return (_ln("M52 84Q40 58 64 64", k.acc, 4) + _r(34, 80, 132, 66, k.main, 33) + _r(56, 88, 88, 50, k.shade, 25)
                + _ln("M66 101H134M62 113H138M66 125H134", k.line, 4, ' stroke-dasharray="0 8"' + FAINT)
                + _ln("M88 84H112", k.acc, 4, ' stroke-dasharray="0 12"'))  # fmt: skip
    if style == 1:
        return (_r(60, 38, 80, 124, k.main, 8) + _c(100, 118, 30, DARK) + _c(100, 118, 22, "#4a4e57")
                + _c(100, 118, 8, k.acc) + _c(100, 64, 13, DARK) + _c(100, 64, 5, "#4a4e57"))  # fmt: skip
    return (_p("M54 150Q46 68 100 64Q154 68 146 150Q100 164 54 150Z", k.main)
            + _ln("M57 104Q100 116 143 104M55 126Q100 140 145 126", k.line, 1.5, FAINT)
            + _e(100, 73, 22, 5, k.shade) + _ln("M60 147Q100 159 140 147", k.acc, 3))  # fmt: skip


def _wallpaper(k: Look, x: int, y: int, w: int, h: int, style: int) -> str:
    """What a switched-on screen shows: the second colour with a simple shape in the third."""
    base = _r(x, y, w, h, k.acc, 2, NO)
    if style == 0:  # hills and a sun
        hills = f"M{x} {y + h}L{x + w * 0.3:.0f} {y + h * 0.45:.0f}L{x + w * 0.5:.0f} {y + h * 0.75:.0f}"
        hills += f"L{x + w * 0.68:.0f} {y + h * 0.5:.0f}L{x + w} {y + h}Z"
        return (base + _p(hills, k.third, NO + ' opacity=".8"')
                + _c(round(x + w * 0.78), round(y + h * 0.26), round(h * 0.11), "#fff", NO + ' opacity=".5"'))  # fmt: skip
    if style == 1:  # a disc
        size = round(min(w, h) * 0.26)
        return base + _c(round(x + w / 2), round(y + h * 0.45), size, k.third, NO + ' opacity=".8"')
    beam = f"M{x} {y}H{x + w * 0.6:.0f}L{x + w * 0.25:.0f} {y + h}H{x}Z"
    return base + _p(beam, "#fff", NO + ' opacity=".22"')


def _phone(k: Look) -> str:
    """A phone case from the back, a phone (back and front) or a tablet."""
    if k.has("tablets?|ipad|kindle|e-?readers?"):
        return (_r(46, 32, 108, 138, k.main, 11) + _r(53, 39, 94, 124, DARK, 5)
                + _wallpaper(k, 54, 40, 92, 122, k.pick(14, 3)) + _c(100, 36, 1.5, k.shade, NO))  # fmt: skip
    case = "M79 30H121Q136 30 136 45V155Q136 170 121 170H79Q64 170 64 155V45Q64 30 79 30Z"
    lenses = _c(81, 47, 5, DARK) + _c(93, 47, 5, DARK) + _c(93, 59, 2.5, PAPER, NO)
    if k.pick(17, 2):
        lenses += _c(81, 59, 5, DARK)
    back = _r(136, 70, 3, 20, k.line, 1.5, NO) + _p(case, k.main)
    if k.has("cases?|covers?|sleeves?|skins?|bumpers?"):
        extra = (_ring(100, 116, 13, k.shade, 3), _r(78, 108, 44, 30, k.shade, 4), "")[k.pick(20, 3)]
        return back + _pattern(k, case, 64, 30, 136, 170) + _r(72, 38, 30, 30, k.shade, 9) + lenses + extra
    back += _r(72, 38, 30, 30, k.shade, 9) + lenses
    front = _p(case, DARK) + _wallpaper(k, 70, 36, 60, 128, k.pick(14, 3)) + _c(100, 43, 3, DARK, NO)
    return _at("translate(-24 0) rotate(-6 100 100)", back) + _at("translate(22 2) rotate(5 100 100)", front)


def _laptop(k: Look) -> str:
    """An open laptop from the front."""
    return (_r(44, 48, 112, 82, k.main, 6) + _r(50, 54, 100, 68, DARK, 3) + _wallpaper(k, 51, 55, 98, 66, k.pick(14, 3))
            + _p("M28 132H172L165 143Q163 148 156 148H44Q37 148 35 143Z", k.main)
            + _p("M88 132H112V135Q112 137 110 137H90Q88 137 88 135Z", k.shade))  # fmt: skip


def _keyboard(k: Look) -> str:
    """A keyboard from above; gaming keyboards glow in the second colour."""
    gaming = k.has("rgb|gaming|backlit|led|mechanical")
    key = DARK if gaming else k.shade
    flat = ' stroke-linecap="butt"'
    out = [_r(22, 74, 156, 60, k.main, 8),
           _ln("M29 87H170.5M29 99H170.5M29 111H170.5", key, 9, ' stroke-dasharray="9.5 2.5"' + flat),
           _ln("M29 123H50M53 123H65M68 123H132M135 123H147M150 123H170.5", key, 9, flat),
           _r(29, 82.5, 9.5, 9, k.acc, 1, NO), _r(161, 106.5, 9.5, 9, k.acc, 1, NO)]  # fmt: skip
    if gaming:
        out.append(_r(27, 129, 146, 2.5, k.acc, 1, NO))
    return "".join(out)


def _mouse(k: Look) -> str:
    """A computer mouse from above, or a mouse pad with a small mouse on it."""

    shape = "M100 40C126 40 134 70 134 104C134 142 120 162 100 162C80 162 66 142 66 104C66 70 74 40 100 40Z"

    def unit(body: str, wheel: str) -> str:
        return (_p(shape, body) + _ln("M100 41V92M67 97Q100 106 133 97", k.line, 1.5, FAINT)
                + _r(96, 56, 8, 22, wheel, 4) + _e(84, 126, 6, 18, "#fff", SHINE))  # fmt: skip

    if k.has("mouse ?pads?|desk mats?|desk pads?"):
        return (_r(26, 56, 148, 100, k.main, 10) + _r(32, 62, 136, 88, "none", 6, ' stroke-dasharray="3 3"' + FAINT)
                + _ln("M26 128Q70 96 110 122Q140 140 174 110", k.acc, 5, ' opacity=".6"')
                + _at("translate(98 72) scale(.5)", unit(_on(k.main), k.acc)))  # fmt: skip
    extra = ""
    if k.has("gaming|rgb") or k.pick(14, 2):
        extra = _ln("M71 114Q72 142 86 155M129 114Q128 142 114 155", k.acc, 3)
    return unit(k.main, k.acc) + extra


def _camera(k: Look) -> str:
    """A camera from the front: compact camera with lens, action camera or webcam."""
    glint = _c(94, 103, 4, "#fff", NO + ' opacity=".6"')
    if k.has("webcams?|security|surveillance|doorbell|cctv|dash ?cam|indoor|outdoor"):
        return (_p("M78 154H122L112 130H88Z", k.shade) + _c(100, 96, 42, k.main) + _c(100, 96, 27, DARK)
                + _c(100, 96, 14, LENS) + _at("translate(0 -13)", glint) + _c(100, 62, 2.5, k.acc, NO))  # fmt: skip
    if k.has("gopro|action"):
        return (_r(52, 60, 96, 92, k.main, 12) + _r(60, 68, 46, 46, DARK, 9) + _c(83, 91, 15, LENS)
                + _at("translate(-17 -18)", glint) + _r(114, 70, 26, 20, "#14161a", 3) + _c(127, 132, 6, k.acc))  # fmt: skip
    band = _p("M41 90H159V132H41Z", k.shade, NO) if k.pick(14, 2) else ""
    return (_p("M82 72L88 56H112L118 72Z", k.shade) + _r(48, 60, 18, 12, k.acc, 3) + _r(40, 70, 120, 78, k.main, 10)
            + band + _c(100, 110, 31, DARK) + _c(100, 110, 23, "#33363d") + _c(100, 110, 13, LENS) + glint
            + _r(134, 77, 16, 8, PAPER, 2))  # fmt: skip


def _tv(k: Look) -> str:
    """A television on feet, a monitor on a stand, or a projector."""
    if k.has("projectors?"):
        return (_ln("M58 144V152M142 144V152", INK, 5) + _r(42, 84, 116, 60, k.main, 12) + _c(78, 114, 21, DARK)
                + _c(78, 114, 13, LENS) + _c(73, 109, 3.5, "#fff", NO + ' opacity=".6"')
                + _ln("M116 104H146M116 114H146M116 124H146", k.line, 3, FAINT) + _c(142, 93, 2.5, k.acc, NO))  # fmt: skip
    if k.has("monitors?|displays?"):
        stand = _r(94, 138, 12, 16, k.shade) + _r(70, 152, 60, 7, k.main, 3)
    else:
        stand = _ln("M56 140L48 156M144 140L152 156", INK, 4)
    return stand + _r(22, 46, 156, 94, k.main, 5) + _wallpaper(k, 26, 50, 148, 86, k.pick(14, 3))


def _charger(k: Look) -> str:
    """A wall charger, power bank, battery, charging pad or a coiled cable with two plugs."""
    bolt = _p("M105 86L88 112H99L95 136L113 108H102Z", k.acc)
    if k.has("power ?banks?|portable chargers?|battery packs?"):
        return (_r(60, 40, 80, 122, k.main, 12) + _ln("M82 58H118", k.acc, 4, ' stroke-dasharray="0 12"') + bolt
                + _r(78, 149, 16, 6, "#14161a", 1, NO) + _r(106, 149, 16, 6, "#14161a", 1, NO))  # fmt: skip
    if k.has("batter(y|ies)|aaa?|rechargeable"):
        return (_r(92, 42, 16, 12, STEEL, 2) + _r(80, 52, 40, 110, k.main, 6)
                + _p("M80 78V58Q80 52 86 52H114Q120 52 120 58V78Z", k.acc)
                + _ln("M100 100V116M92 108H108", _on(k.main), 3) + _ln("M81 148H119", k.line, 1.5, FAINT))  # fmt: skip
    if k.has("wireless|pads?|magsafe|qi"):
        pad = _c(100, 100, 54, k.main) + _ring(100, 100, 37, k.shade, 3)
        return _ln("M100 150V172", k.line, 4) + pad + bolt
    if k.has("cables?|cords?|usb") and not k.has("chargers?|adapters?|plug"):
        coil = ("M64 90a36 36 0 1 0 72 0a36 36 0 1 0-72 0M75 90a25 25 0 1 0 50 0a25 25 0 1 0-50 0"
                "M64 90V134M136 90V134")  # fmt: skip
        return (_cord(coil, k.main, k, 4) + _r(93, 48, 14, 22, k.acc, 3) + _r(55, 132, 18, 22, k.shade, 3)
                + _r(59, 154, 10, 9, STEEL, 1) + _r(128, 132, 16, 18, k.shade, 3) + _r(131, 150, 10, 7, STEEL, 2))  # fmt: skip
    return (_r(84, 48, 7, 22, STEEL, 1) + _r(109, 48, 7, 22, STEEL, 1) + _r(60, 68, 80, 86, k.main, 14) + bolt
            + _r(90, 144, 20, 5, "#14161a", 1, NO))  # fmt: skip


def _controller(k: Look) -> str:
    """A game controller, or a handheld console with two coloured ends."""
    dark = INK if _lum(k.main) > 0.3 else "#5a5f69"
    if k.has("nintendo|switch|joy-?cons?|handheld|consoles?"):
        return (_p("M42 68H58V136H42Q26 136 26 120V84Q26 68 42 68Z", k.acc)
                + _p("M158 68H142V136H158Q174 136 174 120V84Q174 68 158 68Z", k.third) + _r(58, 68, 84, 68, DARK)
                + _wallpaper(k, 63, 73, 74, 58, k.pick(14, 3)) + _c(42, 90, 6, INK) + _c(158, 114, 6, INK)
                + _ln("M42 110V122M152 88H164", INK, 4, ' stroke-dasharray="0 6"'))  # fmt: skip
    colours = (k.acc, k.acc, k.acc, k.acc) if k.pick(14, 2) else ("#2f9e5a", "#d6373a", "#2f6fd6", "#f3c72c")
    spots = ((128, 95), (137, 104), (128, 113), (119, 104))
    body = ("M56 78Q100 70 144 78Q162 82 168 122Q172 152 156 154Q144 154 132 130H68Q56 154 44 154"
            "Q28 152 32 122Q38 82 56 78Z")  # fmt: skip
    return (_p(body, k.main) + _p("M68 94h8v6h6v8h-6v6h-8v-6h-6v-8h6z", dark)
            + "".join(_c(x, y, 4.5, colour) for (x, y), colour in zip(spots, colours, strict=True))
            + _c(86, 120, 8, dark) + _c(114, 120, 8, dark) + _r(94, 88, 12, 4, dark, 2, NO))  # fmt: skip


def _car(k: Look) -> str:
    """A car from the side (also used for toy cars)."""
    body = ("M30 130Q30 114 44 112L62 110L78 86Q82 80 90 80H128Q136 80 142 88L156 110Q172 112 172 126V134"
            "Q172 140 166 140H36Q30 140 30 134Z")  # fmt: skip
    stripe = _ln("M36 124H166", k.acc, 3) if k.pick(14, 2) else ""
    return (_p(body, k.main) + stripe + _p("M84 90H104V108H72Z", GLASS) + _p("M110 90H130L143 108H110Z", GLASS)
            + _ln("M107 110V136", k.line, 1.5, FAINT) + _r(165, 116, 6, 7, GLOW, 2)
            + _c(64, 140, 15, DARK) + _c(64, 140, 6, STEEL) + _c(138, 140, 15, DARK) + _c(138, 140, 6, STEEL))  # fmt: skip


def _toy(k: Look) -> str:
    """A toy: teddy bear, toy car or building bricks (never a human figure)."""
    if k.has("cars?|trucks?|vehicles?|trains?|tractors?"):
        return _car(k)
    if k.has("plush|stuffed|teddy|bears?|soft toys?|cuddly|bunny|unicorn|animals?"):
        pale = _mix(k.main, "#ffffff", 0.55)
        return "".join((
            _c(78, 52, 12, k.main), _c(122, 52, 12, k.main), _c(78, 52, 5, pale, NO), _c(122, 52, 5, pale, NO),
            _e(63, 116, 12, 19, k.main, ' transform="rotate(25 63 116)"'),
            _e(137, 116, 12, 19, k.main, ' transform="rotate(-25 137 116)"'),
            _e(100, 126, 34, 34, k.main), _e(100, 130, 20, 22, pale, NO),
            _c(75, 153, 14, k.main), _c(125, 153, 14, k.main), _c(75, 154, 7, pale, NO), _c(125, 154, 7, pale, NO),
            _c(100, 74, 29, k.main), _e(100, 83, 12, 9, pale, NO), _e(100, 79, 4, 3, INK, NO),
            _c(89, 68, 3, INK, NO), _c(111, 68, 3, INK, NO), _p("M100 103L87 96V110ZM100 103L113 96V110Z", k.acc),
        ))  # fmt: skip

    def brick(x: int, y: int, colour: str) -> str:
        return (_r(x + 8, y - 8, 14, 10, colour, 2) + _r(x + 38, y - 8, 14, 10, colour, 2) + _r(x, y, 60, 40, colour, 3)
                + _r(x + 5, y + 5, 50, 4, "#fff", 2, SHINE))  # fmt: skip

    if k.pick(14, 2):
        return brick(40, 120, k.main) + brick(100, 120, k.acc) + brick(70, 80, k.third)
    return brick(40, 120, k.main) + brick(100, 120, k.acc) + brick(100, 80, k.third) + brick(100, 40, k.main)


def _puzzle(k: Look) -> str:
    """Four jigsaw pieces put together."""
    a, b, c, d = k.main, k.acc, k.third, _mix(k.main, k.acc, 0.5)
    return (_r(52, 52, 48, 48, a, 4) + _r(100, 52, 48, 48, b, 4) + _r(52, 100, 48, 48, c, 4) + _r(100, 100, 48, 48, d, 4)
            + _c(106, 76, 9, a) + _c(76, 94, 9, c) + _c(124, 106, 9, b) + _c(94, 124, 9, d))  # fmt: skip


def _book(k: Look) -> str:
    """A book with pages and a ribbon, or a notebook with spiral or elastic band."""
    if k.has("notebooks?|journals?|planners?|diary|sketchbooks?|notepads?|spiral"):
        if k.has("spiral") or k.pick(14, 2):
            binding = _ln("M60 48V154", GREY, 6, ' stroke-dasharray="0 10.6"')
        else:
            binding = _ln("M132 37V163", k.acc, 5)
        return (_r(60, 36, 86, 128, k.main, 8) + binding + _r(80, 60, 40, 24, PAPER, 3)
                + _ln("M86 68H114M86 76H104", k.line, 1.5, FAINT))  # fmt: skip
    art = (_r(82, 58, 48, 22, k.acc, 2) + _ln("M86 98H126M86 108H114", _on(k.main), 2, FAINT),
           _c(106, 92, 22, k.acc) + _ln("M88 132H124", _on(k.main), 2, FAINT),
           _p("M71 126L141 86V161H71Z", k.acc, NO + ' opacity=".85"'))[k.pick(14, 3)]  # fmt: skip
    return (_r(64, 40, 84, 126, PAPER, 3) + _p("M118 162V178L123 173L128 178V162Z", k.acc) + _r(58, 36, 84, 126, k.main, 4)
            + art + _p("M62 36H70V162H62Q58 162 58 158V40Q58 36 62 36Z", k.shade))  # fmt: skip


def _pens(k: Look) -> str:
    """Three pens, pencils or markers side by side, each in its own colour."""
    pencil, marker = k.has("pencils?|crayons?"), k.has("markers?|highlighters?|sharpies?")

    def one(x: int, y: int, colour: str) -> str:
        if pencil:
            return (_r(x, y, 12, 9, "#f2a3b3", 2) + _r(x, y + 8, 12, 7, STEEL) + _r(x, y + 15, 12, 86, colour)
                    + _p(f"M{x} {y + 101}L{x + 6} {y + 122}L{x + 12} {y + 101}Z", "#ecd0a6")
                    + _p(f"M{x + 4} {y + 115}L{x + 6} {y + 122}L{x + 8} {y + 115}Z", colour, NO))  # fmt: skip
        if marker:
            tip = _r(x + 3, y + 108, 6, 12, colour, 1)
            return _r(x, y + 44, 12, 64, PAPER, 2) + tip + _r(x - 1, y, 14, 46, colour, 3)
        return (_r(x + 9, y + 6, 5, 34, STEEL, 2) + _r(x, y, 12, 104, colour, 4) + _r(x, y + 72, 12, 6, _on(colour), 0, NO)
                + _p(f"M{x + 1} {y + 104}L{x + 6} {y + 122}L{x + 11} {y + 104}Z", STEEL))  # fmt: skip

    return _at("rotate(14 100 100)", one(66, 44, k.main), one(94, 36, k.acc), one(122, 44, k.third))


def _knife(k: Look) -> str:
    """A kitchen knife: steel blade, coloured handle."""
    return _at("rotate(-30 100 100)", _p("M26 92H118V114Q62 122 26 92Z", STEEL), _ln("M44 97H112", "#fff", 2, FAINT),
               _r(118, 90, 58, 20, k.main, 7), _c(134, 100, 2.5, STEEL), _c(160, 100, 2.5, STEEL))  # fmt: skip


def _mug(k: Look) -> str:
    """A mug with a handle (steam when it is about coffee or tea), or a tumbler with lid and straw."""
    if k.has("tumblers?|travel|insulated|straws?|to[- ]go|sippy|glass(es)?|stainless"):
        out = [_cord("M108 44L120 14", k.acc, k, 4)] if k.has("straws?") or k.pick(14, 2) else []
        out += [_p("M66 52H134L126 160H74Z", k.main), _p("M69 96H131L129 118H71Z", k.acc, NO + ' opacity=".9"'),
                _r(61, 40, 78, 14, k.shade, 5), _p("M76 60H84L88 152H82Z", "#fff", SHINE)]  # fmt: skip
        return "".join(out)
    hot = k.has("coffee|espresso|tea|cocoa|latte|cappuccino")
    handle = "M130 84H140Q156 84 156 106Q156 128 140 128H130"
    art = (_p("M59 118H129V132H59Z", k.acc, NO), _c(94, 108, 12, k.acc), _ln("M59 124H129M59 132H129", k.acc, 2.5),
           "")[k.pick(14, 4)]  # fmt: skip
    out = [_cord(handle, k.main, k, 9), _p("M58 62H130V140Q130 160 110 160H78Q58 160 58 140Z", k.main), art,
           _e(94, 62, 36, 7, k.shade), _e(94, 63, 30, 4.5, "#5b3a26" if hot else k.hi, NO)]  # fmt: skip
    if hot:
        out.append(_ln("M82 46Q76 38 82 30Q88 22 82 14M104 46Q98 38 104 30Q110 22 104 14", GREY, 3, FAINT))
    return "".join(out)


def _bottle(k: Look) -> str:
    """A water bottle with cap, a thermos flask (baby bottles are drawn by the baby drawing)."""
    if k.has("baby|feeding|nursing|infant|newborn"):
        return _baby(k)
    if k.has("thermos|flasks?|insulated|stainless|vacuum"):
        return (_r(76, 52, 48, 110, k.main, 8) + _r(74, 28, 52, 30, k.acc if k.pick(14, 2) else STEEL, 6)
                + _ln("M77 142H123", k.line, 1.5, FAINT) + _r(82, 64, 5, 70, "#fff", 2.5, SHINE))  # fmt: skip
    out = [_ring(100, 26, 9, k.acc, 4)] if k.has("sports?|handle|loop|carabiner|gym") or k.pick(17, 2) else []
    out.append(_p("M88 46H112Q118 50 120 62Q126 64 126 76V150Q126 162 114 162H86Q74 162 74 150V76Q74 64 80 62"
                  "Q82 50 88 46Z", k.main))  # fmt: skip
    style = k.pick(14, 3)
    if style == 0:
        out.append(_p("M75 98H125V126H75Z", k.acc, NO))
    elif style == 1:
        out.append(_ln("M116 84H124M116 98H124M116 112H124M116 126H124M116 140H124", _on(k.main), 2, FAINT))
    else:
        out.append(_r(82, 100, 36, 30, PAPER, 4, NO + ' opacity=".85"'))
    out += [_r(84, 28, 32, 20, k.acc, 5), _r(80, 74, 5, 78, "#fff", 2.5, SHINE)]
    return "".join(out)


def _cookware(k: Look) -> str:
    """A frying pan from above, a pot with lid, or a small kitchen appliance."""
    if k.has("blenders?|juicers?|processors?|smoothie"):
        return (_p("M78 44H122L114 108H86Z", GLASS) + _p("M82 74H118L114 108H86Z", k.acc, NO + ' opacity=".8"')
                + _r(74, 36, 52, 10, INK, 4) + _p("M80 108H120L128 158H72Z", k.main) + _c(100, 134, 9, k.shade)
                + _c(100, 134, 3, k.acc, NO))  # fmt: skip
    if k.has("toasters?"):
        return (_r(68, 54, 28, 30, "#e3b778", 5) + _r(104, 54, 28, 30, "#e3b778", 5) + _r(44, 72, 112, 86, k.main, 16)
                + _r(60, 80, 80, 6, DARK, 3, NO) + _c(132, 130, 8, k.shade) + _r(150, 96, 10, 14, k.acc, 3))  # fmt: skip
    if k.has("air fryers?|mixers?|microwaves?|kettles?|makers?|cookers?|ovens?|machines?"):
        return (_r(50, 46, 100, 114, k.main, 20) + _r(62, 58, 76, 28, DARK, 8) + _ln("M72 72H96", k.acc, 4)
                + _r(66, 100, 68, 46, k.shade, 8) + _r(86, 108, 28, 10, _on(k.shade), 5, NO + ' opacity=".7"'))  # fmt: skip
    if k.has("pots?|stockpots?|dutch ovens?|saucepans?|casseroles?|cookware sets?|steamers?"):
        lid = GLASS if k.pick(14, 2) else k.main
        return (_ln("M52 98H40V110H52M148 98H160V110H148", INK, 5) + _r(92, 60, 16, 12, INK, 4)
                + _p("M52 86H148V140Q148 158 130 158H70Q52 158 52 140Z", k.main) + _ln("M53 128H147", k.acc, 3)
                + _p("M48 86Q100 54 152 86Z", lid) + _r(46, 82, 108, 8, STEEL, 4)
                + _r(60, 98, 5, 44, "#fff", 2.5, SHINE))  # fmt: skip
    inside = ("#33363d", "#e9e2d3", "#4a4e57")[k.pick(14, 3)]
    return _at("rotate(-24 100 104)", _r(130, 97, 52, 14, k.acc if k.pick(17, 2) else INK, 7), _c(86, 104, 48, k.main),
               _c(86, 104, 39, inside), _e(72, 92, 16, 9, "#fff", NO + ' opacity=".12"'))  # fmt: skip


def _pet(k: Look) -> str:
    """Things for pets: a food bowl with a bone or fish on it, a chew bone, or a collar with tag."""
    if k.has("leash(es)?|collars?|harness(es)?|leads?"):
        lead = _cord("M150 84Q178 62 162 36", k.main, k, 5) if k.has("leash(es)?|leads?") else ""
        return (lead + _e(100, 104, 56, 34, "none", f' stroke="{k.line}" stroke-width="14"')
                + _e(100, 104, 56, 34, "none", f' stroke="{k.main}" stroke-width="11"')
                + _e(100, 104, 56, 34, "none", f' stroke="{k.acc}" stroke-width="3" stroke-dasharray="6 6"')
                + _r(88, 128, 24, 20, STEEL, 4) + _c(100, 158, 8, GOLD))  # fmt: skip
    if k.has("chews?|bones?|toys?|treats?|squeaky"):
        return _at("rotate(-18 100 104)", _p(BONE, k.main), _ln("M72 100H128", "#fff", 4, ' opacity=".3"'))
    if k.has("cats?|kittens?"):
        mark = _p("M88 138Q100 128 112 138Q100 148 88 138ZM112 138L120 132V144Z", PAPER, NO)
    else:
        mark = _at("translate(60 97) scale(.4)", _p(BONE, PAPER, NO))
    return (_p("M42 118H158L146 156Q144 160 138 160H62Q56 160 54 156Z", k.main) + mark
            + _e(100, 118, 58, 9, k.shade) + _e(100, 119, 48, 6, "#a9744a", NO))  # fmt: skip


def _fish(k: Look) -> str:
    """An aquarium fish with bubbles."""
    return (_p("M132 100L166 74V126Z", k.acc) + _p("M84 76L104 58L112 80Z", k.acc) + _e(90, 100, 48, 27, k.main)
            + _ln("M82 84Q90 100 82 116", k.line, 1.5, FAINT) + _c(66, 94, 5, PAPER) + _c(65, 94, 2.5, INK, NO)
            + _ring(40, 62, 4, k.line, 1.5) + _ring(50, 46, 6, k.line, 1.5))  # fmt: skip


def _bike(k: Look) -> str:
    """A bicycle from the side, or a bike helmet."""
    if k.has("helmets?"):
        return (_ln("M72 128L86 154L106 128", INK, 3)
                + _p("M40 122Q40 60 104 60Q160 60 164 118Q166 128 152 128H48Q40 128 40 122Z", k.main)
                + _ln("M72 84Q100 68 136 80M62 104Q100 88 150 100", DARK, 5, ' opacity=".5"')
                + _p("M150 112H170Q178 120 172 128H150Z", k.acc))  # fmt: skip
    return (_ring(58, 128, 30, INK, 5) + _ring(142, 128, 30, INK, 5) + _c(58, 128, 3, INK, NO) + _c(142, 128, 3, INK, NO)
            + _ln("M58 128H98L86 86H126L98 128M58 128L86 86M126 86L142 128", k.main, 5)
            + _ln("M86 86V78M76 78H96M126 86L122 72H136M98 128L106 140", INK, 4) + _c(98, 128, 6, k.acc))  # fmt: skip


def _ball(k: Look) -> str:
    """Sports gear: a ball with the markings of its sport, a dumbbell or a rolled yoga mat."""
    ball = k.has("balls?|soccer|footballs?|basketballs?|tennis|baseballs?|softballs?|rugby")
    if not ball and k.has("dumbbells?|weights?|kettlebells?|barbells?|fitness|gym|workout|exercise"):
        return (_r(66, 98, 68, 12, STEEL, 2) + _r(46, 70, 24, 68, k.main, 6) + _r(130, 70, 24, 68, k.main, 6)
                + _r(34, 82, 12, 44, k.shade, 4) + _r(154, 82, 12, 44, k.shade, 4))  # fmt: skip
    if not ball and k.has("yoga|mats?|pilates"):
        return (_r(34, 86, 124, 44, k.main, 22) + _e(146, 108, 13, 22, k.shade)
                + _ln("M146 96Q154 108 146 118Q140 108 146 104", k.line, 1.5) + _r(60, 84, 9, 48, k.acc, 2)
                + _r(108, 84, 9, 48, k.acc, 2))  # fmt: skip
    shine = _e(80, 80, 14, 9, "#fff", NO + ' opacity=".3" transform="rotate(-35 80 80)"')
    if k.has("american football|rugby"):
        turn = ' transform="rotate(-25 100 104)"'
        return (_e(100, 104, 58, 36, k.main if k.named else "#8a4b2a", turn)
                + _ln("M84 104H116M90 99V109M97 99V109M104 99V109M111 99V109", PAPER, 2.5, turn))  # fmt: skip
    if k.has("basketballs?"):
        base, marks = (k.main if k.named else "#e2762b"), _ln(
            "M100 52V156M48 104H152M64 66Q92 104 64 142M136 66Q108 104 136 142", INK, 2.5
        )
    elif k.has("tennis|padel"):
        base, marks = "#d4e24a", _ln("M62 68Q96 104 62 140M138 68Q104 104 138 140", PAPER, 4)
    elif k.has("baseballs?|softballs?"):
        seams = "M66 66Q92 104 66 142M134 66Q108 104 134 142"
        base, marks = PAPER, _ln(seams, "#d6373a", 3, ' stroke-dasharray="1 6"')
    elif k.has("soccer|footballs?|futbol"):
        patch = k.main if k.named and _lum(k.main) < 0.7 else INK
        base, marks = PAPER, _p("M100 86L117 98L111 119H89L83 98Z", patch) + _ln(
            "M100 86V53M117 98L149 88M111 119L130 146M89 119L70 146M83 98L51 88", patch, 2.5
        )
    else:
        base, marks = k.main, (
            _ln("M52 88Q100 60 148 88M52 120Q100 148 148 120", k.acc, 5),
            _ln("M100 52Q70 104 100 156M100 52Q130 104 100 156", k.acc, 4),
            _c(100, 104, 20, k.acc),
        )[k.pick(14, 3)]
    return _c(100, 104, 52, base) + marks + shine


def _tent(k: Look) -> str:
    """A tent with an open door, or a sleeping bag."""
    if k.has("sleeping bags?"):
        return _at("rotate(18 100 100)", _r(64, 34, 72, 132, k.main, 32), _e(100, 58, 24, 16, k.acc),
                   _ln("M66 96H134M66 122H134M69 146H131", k.line, 1.5, FAINT),
                   _ln("M127 78V150", STEEL, 2, ' stroke-dasharray="3 3"'))  # fmt: skip
    door = "#33363d" if k.pick(17, 2) else k.shade
    pegs = _ln("M34 156L16 164M166 156L184 164", GREY, 2)
    if k.pick(14, 2):
        return (pegs + _p("M100 50L34 156H166Z", k.main) + _p("M100 92L76 156H124Z", door)
                + _ln("M100 92V156", k.line, 1.5, FAINT) + _ln("M100 50L58 156M100 50L142 156", k.acc, 3))  # fmt: skip
    return (pegs + _p("M32 156Q40 60 100 56Q160 60 168 156Z", k.main) + _p("M78 156Q80 104 100 98Q120 104 122 156Z", door)
            + _ln("M100 98V156", k.line, 1.5, FAINT) + _ln("M100 56Q72 100 62 156M100 56Q128 100 138 156", k.acc, 3))  # fmt: skip


def _plant(k: Look) -> str:
    """A plant in a pot: leaves, a cactus, or flowers in a vase."""
    greens = ("#3f9b5f", "#2f7d4c", "#58b374")
    if k.has("flowers?|bouquets?|roses|tulips?|orchids?|blooms?|peon(y|ies)"):

        def head(x: int, y: int, colour: str) -> str:
            return _e(x, y, 15, 6.5, colour) + _e(x, y, 6.5, 15, colour) + _c(x, y, 5.5, "#f3c72c")

        return (_ln("M100 114V70M97 114L74 84M103 114L126 84", greens[1], 3) + _p("M100 96Q84 92 82 80Q96 82 100 96Z", greens[0])
                + head(100, 58, k.main) + head(70, 72, k.acc) + head(130, 72, k.main if k.pick(14, 2) else k.third)
                + _p("M76 112H124L116 160H84Z", GLASS) + _p("M80 132H120L116 160H84Z", "#a9d3f5", NO + ' opacity=".7"'))  # fmt: skip
    pot = _p("M70 120H130L122 160H78Z", k.main) + _r(65, 110, 70, 13, k.main, 3)
    if k.pick(17, 2):
        pot += _ln("M73 136H127", k.acc, 4)
    if k.has("cactus|cacti|succulents?|aloe"):
        spikes = _ln("M100 56V108M92 60V108M108 60V108", "#fff", 2, ' stroke-dasharray="1 7" opacity=".7"')
        return (_cord("M86 96H68V76", greens[1], k, 11) + _cord("M114 88H132V68", greens[1], k, 11)
                + _r(84, 46, 32, 70, greens[0], 16) + spikes + _c(100, 46, 6, k.acc) + pot)  # fmt: skip
    leaves = ((48, 92, 70, 118, 78, 84, 1), (152, 92, 130, 118, 122, 84, 1), (62, 54, 68, 92, 96, 72, 0),
              (138, 54, 132, 92, 104, 72, 0), (100, 38, 84, 76, 116, 76, 2))  # fmt: skip
    if k.pick(14, 2):  # tall blades instead of round leaves
        leaves = ((70, 52, 78, 92, 92, 84, 1), (130, 52, 122, 92, 108, 84, 1), (86, 36, 88, 80, 98, 76, 0),
                  (114, 36, 112, 80, 102, 76, 0), (100, 28, 94, 76, 106, 76, 2))  # fmt: skip
    drawn = (_p(f"M100 114Q{a} {b} {x} {y}Q{c} {d} 100 114Z", greens[g]) for x, y, a, b, c, d, g in leaves)
    return "".join(drawn) + pot


def _xmas(k: Look) -> str:
    """A Christmas tree with baubles in the product's colours, or one big bauble."""
    one = k.main if _far(k.main, "#358a53") else "#d6373a"
    if k.has("ornaments?|baubles?"):
        return (_ring(100, 40, 7, GOLD, 3) + _r(91, 44, 18, 12, GOLD, 3) + _c(100, 108, 52, one)
                + _ln("M52 96Q100 76 148 96M52 120Q100 140 148 120", k.acc, 4)
                + _e(80, 84, 14, 9, "#fff", NO + ' opacity=".3" transform="rotate(-35 80 84)"'))  # fmt: skip
    return (_r(92, 142, 16, 20, "#7a4f33", 2) + _p("M100 90L154 148H46Z", "#2f7d4c") + _p("M100 60L144 118H56Z", "#358a53")
            + _p("M100 34L134 84H66Z", "#3f9b5f") + _c(88, 76, 5, one) + _c(116, 104, 5, k.acc) + _c(82, 112, 5, k.acc)
            + _c(104, 134, 5, one) + _c(130, 138, 5, k.third) + _c(72, 140, 5, k.third)
            + _p("M100 20L104 31H115L106 38L109 49L100 42L91 49L94 38L85 31H96Z", "#f3c72c"))  # fmt: skip


def _candle(k: Look) -> str:
    """A burning candle: in a jar with a label, or a plain pillar."""
    flame = (_ln("M100 74V86", INK, 2) + _p("M100 40Q114 60 100 76Q86 60 100 40Z", "#f59e0b", NO)
             + _p("M100 54Q107 64 100 74Q93 64 100 54Z", "#fde68a", NO))  # fmt: skip
    if k.has("pillars?|tapers?|sticks?|votives?|tea ?lights?") or k.pick(14, 3) == 0:
        return (flame + _r(78, 84, 44, 76, k.main, 5) + _p("M78 90Q85 106 91 92Q97 102 104 90Z", k.hi, NO)
                + _e(100, 86, 22, 4, k.shade))  # fmt: skip
    return (flame + _r(64, 84, 72, 76, k.main, 9) + _e(100, 87, 33, 4.5, k.hi, NO) + _r(76, 106, 48, 34, PAPER, 3)
            + _ln("M84 118H116M88 128H112", k.acc, 2.5))  # fmt: skip


def _clock(k: Look) -> str:
    """A wall clock or an alarm clock with bells; the hands depend on the product."""
    face = PAPER if k.pick(22, 3) else "#1f2228"
    ink = _on(face)
    out = []
    if k.has("alarm"):
        out = [_ln("M70 150L60 164M130 150L140 164M100 40V50", k.line, 5), _c(66, 52, 15, k.acc)]
        out.append(_c(134, 52, 15, k.acc))
    square = k.pick(26, 3) == 0 and not out
    frame = _r(46, 48, 108, 108, k.main, 22) if square else _c(100, 102, 56, k.main)
    out += [frame, _c(100, 102, 45, face), _ln("M100 63V71M100 133V141M61 102H69M131 102H139", ink, 3),
            _ln("M100 102V80", ink, 4, f' transform="rotate({k.pick(14, 12) * 30 + 15} 100 102)"'),
            _ln("M100 102V68", ink, 2.5, f' transform="rotate({k.pick(18, 12) * 30} 100 102)"'),
            _c(100, 102, 4, k.acc)]  # fmt: skip
    return "".join(out)


def _scale(k: Look) -> str:
    """A flat digital scale from above."""
    return (_r(44, 48, 112, 112, k.main, 16) + _r(78, 60, 44, 20, DARK, 4)
            + _ln("M87 70H113", k.acc, 5, ' stroke-dasharray="6 3" stroke-linecap="butt"')
            + _ring(100, 120, 27, k.shade, 3) + _r(52, 56, 96, 5, "#fff", 2.5, SHINE))  # fmt: skip


def _guitar(k: Look) -> str:
    """A guitar (acoustic or electric), a row of piano keys, or a drum with sticks."""
    flat = ' stroke-linecap="butt"'
    if k.has("pianos?|keyboards?|synth|synthesizers?"):
        return (_r(24, 70, 152, 64, k.main, 6) + _r(30, 92, 140, 36, PAPER, 2)
                + _ln("M30 110H170", INK, 36, ' stroke-dasharray=".8 9.2"' + flat)
                + _ln("M37 103H170", INK, 22, ' stroke-dasharray="6 4 6 14 6 4 6 4 6 14"' + flat)
                + _ln("M36 81H66", k.acc, 4, ' stroke-dasharray="0 10"'))  # fmt: skip
    if k.has("drums?|percussion|bongos?"):
        return (_ln("M58 62L118 30M142 62L86 28", WOOD, 4) + _p("M48 80V140Q100 160 152 140V80Z", k.main)
                + _ln("M48 94L74 148L100 100L126 148L152 94", STEEL, 2) + _e(100, 80, 52, 12, PAPER))  # fmt: skip
    body = "M100 72C120 72 130 86 124 102C142 110 140 164 100 164C60 164 58 110 76 102C70 86 80 72 100 72Z"
    out = [_r(92, 12, 16, 20, INK, 3), _r(95, 30, 10, 62, "#5b3a26", 1),
           _ln("M95 42H105M95 54H105M95 66H105M95 78H105", STEEL, 1), _p(body, k.main)]  # fmt: skip
    if k.has("electric|bass"):
        out += [_p("M100 96Q124 104 122 134Q110 140 100 124Z", k.acc), _r(90, 104, 20, 6, INK, 1),
                _r(90, 122, 20, 6, INK, 1)]  # fmt: skip
    else:
        out += [_c(100, 112, 12, "#2b1d14"), _ring(100, 112, 15, k.acc, 2)]
    out += [_r(88, 140, 24, 6, INK, 1), _ln("M97 20V142M100 20V142M103 20V142", "#e6e8eb", 0.8)]
    return _at("rotate(28 100 96)", *out)


def _tools(k: Look) -> str:
    """Hand tools: a cordless drill, a hammer, or a wrench crossed with a screwdriver."""
    if k.has("drills?|drivers?|impact|cordless"):
        return (_r(146, 77, 26, 5, STEEL, 1) + _p("M128 68H146V90H128Z", "#4a4e57") + _p("M114 98H126Q124 112 117 114Z", k.acc)
                + _p("M86 96H114L120 140H90Z", k.main) + _r(48, 62, 82, 36, k.main, 10) + _r(56, 70, 28, 6, k.shade, 3, NO)
                + _r(78, 138, 50, 22, INK, 4) + _r(84, 146, 38, 5, k.acc, 2, NO))  # fmt: skip
    if k.has("hammers?|mallets?"):
        return _at("rotate(20 100 100)", _r(94, 60, 12, 104, WOOD, 4), _r(93, 118, 14, 46, k.main, 5),
                   _p("M62 44H126Q138 44 138 58V68H112V74H88V68H62Z", "#6b727c"))  # fmt: skip
    wrench = (_cord("M89 40A17 17 0 1 0 111 40", STEEL, k, 9) + _r(93, 66, 14, 90, STEEL, 5)
              + _r(92, 108, 16, 48, k.main, 6) + _c(100, 146, 3.5, _on(k.main), NO))  # fmt: skip
    driver = (_r(97, 92, 6, 60, STEEL, 1) + _p("M97 152H103L101 164H99Z", "#6b727c") + _r(88, 36, 24, 58, k.main, 10)
              + _ln("M94 46V84M100 46V84M106 46V84", k.line, 1.5, FAINT) + _r(92, 88, 16, 8, k.acc, 2))  # fmt: skip
    if k.has("screwdrivers?") and not k.has("wrench(es)?|sets?|kits?"):
        return _at("rotate(30 100 100)", driver)
    if k.has("wrench(es)?|spanners?|pliers") and not k.has("screwdrivers?|sets?|kits?"):
        return _at("rotate(-30 100 100)", wrench)
    return _at("rotate(-32 100 100)", wrench) + _at("rotate(32 100 100)", driver)


def _cosmetics(k: Look) -> str:
    """Cosmetics: pump bottle with label, tube, lipstick, perfume bottle or a palette of shades."""
    cap = (INK, GOLD, k.acc, PAPER)[k.pick(14, 4)]
    if k.has("lipsticks?|lip|mascara|balm|gloss|concealer"):
        return _at("translate(-14 0)", _r(124, 98, 26, 62, cap, 4), _p("M90 80V58L110 46V80Z", k.main),
                   _r(88, 78, 24, 22, GOLD, 2), _r(84, 98, 32, 62, cap, 4))  # fmt: skip
    if k.has("perfumes?|cologne|fragrance|eau|toilette|parfum|mist"):
        return (_r(92, 38, 16, 14, STEEL, 2) + _r(86, 50, 28, 26, cap, 4)
                + _r(62, 76, 76, 84, k.main, 12, ' fill-opacity=".8"') + _r(82, 106, 36, 26, PAPER, 3)
                + _ln("M88 116H112M92 124H108", k.acc, 2) + _r(69, 84, 5, 66, "#fff", 2.5, SHINE))  # fmt: skip
    if k.has("palettes?|eyeshadow|makeup|blush|powder|foundation|compact"):
        pans = "".join(_r(52 + 34 * i, 72 + 34 * j, 28, 28, _mix(k.main, (PAPER, k.acc)[j], 0.2 + 0.25 * i), 5)
                       for j in range(2) for i in range(3))  # fmt: skip
        return _r(42, 62, 116, 84, INK, 10) + pans
    if k.has("creams?|tubes?|toothpaste|sunscreen|gels?|ointment|cleanser|face wash|moisturi[sz]er"):
        return (_p("M70 44H130L122 146H78Z", k.main) + _ln("M72 54H128", k.line, 1.5, FAINT)
                + _p("M75 94H125L123 122H77Z", k.acc, NO) + _r(82, 146, 36, 18, cap, 4))  # fmt: skip
    return (_r(97, 46, 6, 22, STEEL) + _p("M80 40H106Q110 40 110 44V50H80Z", cap) + _r(88, 66, 24, 14, cap, 3)
            + _r(68, 78, 64, 84, k.main, 12) + _r(78, 100, 44, 40, PAPER, 4) + _ln("M86 112H114M90 122H110", k.acc, 3)
            + _r(73, 88, 4, 64, "#fff", 2, SHINE))  # fmt: skip


def _brush(k: Look) -> str:
    """Personal care: hair brush, toothbrush, razor or trimmer, or a hair dryer."""
    if k.has("hair ?dryers?|blow ?dryers?|dryers?"):
        return (_p("M98 98H126L120 160H102Z", k.main) + _p("M42 62L24 56V102L42 96Z", k.shade) + _r(40, 56, 104, 46, k.main, 22)
                + _c(122, 79, 15, k.acc) + _c(122, 79, 7, k.shade) + _r(107, 116, 8, 16, k.acc, 3))  # fmt: skip
    if k.has("razors?|shavers?|trimmers?|clippers?|epilators?"):
        return _at("rotate(12 100 100)", _r(74, 34, 52, 26, STEEL, 5), _ln("M80 42H120M80 50H120", "#6b727c", 2),
                   _r(82, 58, 36, 108, k.main, 15), _c(100, 92, 7, k.acc),
                   _ln("M92 122H108M92 132H108M92 142H108", k.line, 2, FAINT))  # fmt: skip
    if k.has("tooth ?brush(es)?|dental|oral"):
        wide = 20 if k.has("electric|sonic") else 12
        return _at("rotate(24 100 100)", _r(104, 24, 12, 30, PAPER, 2), _r(104, 34, 12, 10, k.acc, 0, NO),
                   _p("M92 26Q92 20 98 20Q104 20 104 26V54Q104 62 101 70H95Q92 62 92 54Z", k.main),
                   _r(98 - wide / 2, 68, wide, 100, k.main, wide / 2), _r(98 - wide / 2, 100, wide, 30, k.acc, 0, NO),
                   _c(98, 86, 3, _on(k.main), NO))  # fmt: skip
    return _at("rotate(18 100 100)", _r(91, 108, 18, 62, k.main, 9), _e(100, 72, 36, 44, k.main),
               _e(100, 72, 27, 35, k.acc if k.pick(14, 2) else k.shade),
               _ln("M86 52V94M100 46V98M114 52V94", _on(k.shade), 4, ' stroke-dasharray="0 9"'))  # fmt: skip


def _umbrella(k: Look) -> str:
    """An open umbrella with a hooked handle; panels may alternate between two colours."""
    top = ("M30 104Q32 44 100 40Q168 44 170 104Q158 92 147 104Q135 92 123 104Q112 92 100 104Q88 92 77 104"
           "Q65 92 53 104Q42 92 30 104Z")  # fmt: skip
    handle = _ln("M100 30V150Q100 164 89 164Q80 164 80 154", INK, 4)
    out = [handle, _p(top, k.main), _pattern(k, top, 30, 40, 170, 104)]
    if k.pattern == "plain" and k.pick(14, 2):
        out += [_p("M100 40Q70 62 53 104Q65 92 77 104Q84 68 100 40Z", k.acc, NO),
                _p("M100 40V104Q112 92 123 104Q116 68 100 40Z", k.acc, NO),
                _p("M100 40Q130 62 147 104Q158 92 170 104Q168 44 100 40Z", k.acc, NO), _p(top, "none")]  # fmt: skip
    out.append(_ln("M100 40Q70 62 53 104M100 40Q84 68 77 104M100 40V104M100 40Q116 68 123 104M100 40Q130 62 147 104",
                   k.line, 1.5, FAINT))  # fmt: skip
    return "".join(out)


def _baby(k: Look) -> str:
    """Baby things: a feeding bottle, a pacifier, a stroller or a pack of diapers."""
    pale = _mix(k.main, "#ffffff", 0.7)
    if k.has("pacifiers?|soothers?|dummy|teethers?"):
        return (_ring(100, 138, 20, k.acc, 7) + _e(100, 72, 13, 18, pale)
                + _p("M52 104Q52 80 76 84Q100 92 124 84Q148 80 148 104Q148 128 124 124Q100 116 76 124Q52 128 52 104Z", k.main)
                + _c(74, 104, 5, k.shade) + _c(126, 104, 5, k.shade) + _c(100, 104, 9, k.acc))  # fmt: skip
    if k.has("strollers?|prams?|pushchairs?|buggy|car seats?"):
        return (_ln("M142 96L164 60H176", INK, 4) + _ln("M70 132L62 152M122 132L134 152M62 152H134", STEEL, 3)
                + _p("M48 96H142Q142 134 96 134Q48 134 48 96Z", k.main) + _p("M48 96A48 48 0 0 1 96 48V96Z", k.acc)
                + _ln("M96 96L62 62", k.line, 1.5, FAINT) + _c(62, 156, 10, INK) + _c(134, 156, 10, INK)
                + _c(62, 156, 3, STEEL, NO) + _c(134, 156, 3, STEEL, NO))  # fmt: skip
    if k.has("diapers?|napp(y|ies)|wipes"):
        return (_r(44, 58, 112, 100, k.main, 12) + _p("M45 122H155V144H45Z", k.acc, NO)
                + _p("M78 76H122V88Q112 92 110 106H90Q88 92 78 88Z", PAPER))  # fmt: skip
    handles = ""
    if k.pick(14, 2):
        handles = _cord("M76 98Q52 104 60 132", k.acc, k, 5) + _cord("M124 98Q148 104 140 132", k.acc, k, 5)
    return (handles + _p("M88 68Q86 52 94 48Q94 36 100 36Q106 36 106 48Q114 52 112 68Z", "#f3d9b8")
            + _r(74, 82, 52, 80, "#eef5f9", 13) + _p("M75 114H125V150Q125 161 114 161H86Q75 161 75 150Z", "#fffdf5", NO)
            + _ln("M112 100H121M112 114H121M112 128H121M112 142H121", k.main, 2) + _r(70, 66, 60, 18, k.main, 6))  # fmt: skip


def _chair(k: Look) -> str:
    """Furniture on legs: a chair, an office chair on wheels, a stool, a table or a desk."""
    leg = (INK, WOOD, STEEL)[k.pick(14, 3)]
    if k.has("tables?|desks?|workbench|nightstands?") and not k.has("chairs?|stools?"):
        under = _r(49, 130, 102, 6, leg, 2)
        if k.has("desks?|nightstands?"):
            under = _r(112, 87, 38, 32, k.shade, 2) + _ln("M124 103H138", k.line, 3)
        return _r(40, 86, 9, 74, leg, 2) + _r(151, 86, 9, 74, leg, 2) + under + _r(28, 74, 144, 13, k.main, 3)
    if k.has("stools?"):
        return (_ln("M80 86L66 160M120 86L134 160M100 86V160", leg, 5) + _ln("M72 132H128", leg, 3)
                + _r(60, 70, 80, 18, k.main, 9))  # fmt: skip
    if k.has("office|gaming|ergonomic|swivel|task|computer"):
        return (_ln("M100 118V146M100 146L64 158M100 146L136 158M100 146V160", INK, 5) + _c(64, 160, 4, INK)
                + _c(136, 160, 4, INK) + _c(100, 162, 4, INK) + _ln("M60 92V110M140 92V110", INK, 5)
                + _r(72, 34, 56, 70, k.main, 14) + _ln("M84 46V92M116 46V92", k.acc, 4) + _r(62, 104, 76, 16, k.main, 8))  # fmt: skip
    slats = _ln("M84 50V92M100 50V92M116 50V92", k.line, 2, FAINT)
    back = slats if k.pick(17, 2) else _c(100, 70, 4, k.shade)
    return (_ln("M70 112L64 162M130 112L136 162", leg, 5) + _r(70, 40, 60, 60, k.main, 10) + back
            + _r(62, 98, 76, 16, k.main, 6))  # fmt: skip


def _sofa(k: Look) -> str:
    """A sofa from the front with seat cushions and sometimes a throw pillow."""
    leg = (INK, WOOD)[k.pick(14, 2)]
    out = [_r(48, 148, 6, 13, leg, 1), _r(146, 148, 6, 13, leg, 1), _r(40, 68, 120, 58, k.main, 12)]
    if k.pick(17, 2):
        out += [_r(50, 108, 50, 34, k.main, 7), _r(100, 108, 50, 34, k.main, 7)]
        out.append(_ln("M100 72V106", k.line, 1.5, FAINT))
    else:
        out += [_r(50 + 33.3 * i, 108, 33.3, 34, k.main, 6) for i in range(3)]
    out += [_r(26, 90, 26, 60, k.main, 11), _r(148, 90, 26, 60, k.main, 11), _r(48, 140, 104, 10, k.shade, 3)]
    if k.pick(20, 2):
        out.append(_r(58, 86, 24, 24, k.acc, 5, ' transform="rotate(-12 70 98)"'))
    return "".join(out)


def _bedding(k: Look) -> str:
    """Home textiles: a pillow, folded towels or blankets, a made bed, curtains or a rug."""
    if k.has("curtains?|drapes?|blinds?"):
        return (_p("M40 50H94V154Q80 162 67 154Q54 146 40 154Z", k.main) + _p("M106 50H160V154Q146 146 133 154Q120 162 106 154Z", k.main)
                + _ln("M54 54V148M67 54V152M80 54V154M120 54V154M133 54V152M146 54V148", k.line, 1.5, FAINT)
                + _ln("M41 140H93M107 140H159", k.acc, 4, ' opacity=".8"') + _ln("M30 48H170", INK, 5))  # fmt: skip
    if k.has("rugs?|carpets?|mats?|runners?"):
        d = "M52 70H148L172 148H28Z"
        fringe = ' stroke-dasharray="1.5 4" stroke-linecap="butt"'
        return (_ln("M54 66H146", k.line, 7, fringe) + _ln("M30 152H170", k.line, 7, fringe) + _p(d, k.main)
                + _pattern(k, d, 28, 70, 172, 148) + _ln("M64 82H136L152 136H48Z", k.acc, 4))  # fmt: skip
    if k.has("pillows?|cushions?|pillowcases?|shams?"):
        d = "M48 76Q100 66 152 76Q160 106 152 136Q100 146 48 136Q40 106 48 76Z"
        return (_p(d, k.main) + _pattern(k, d, 40, 66, 160, 146)
                + _ln("M57 85Q100 77 143 85Q149 106 143 127Q100 135 57 127Q51 106 57 85Z", k.line, 1.5, FAINT))  # fmt: skip
    textile = k.has("sheets?|bedding|blankets?|duvets?|comforters?|towels?|throws?")
    if k.has("beds?|mattress(es)?|bed frames?|headboards?") and not textile:
        return (_r(34, 56, 132, 62, WOOD if k.pick(14, 2) else k.acc, 8) + _r(36, 140, 8, 20, INK, 1)
                + _r(156, 140, 8, 20, INK, 1) + _r(30, 100, 140, 46, PAPER, 8) + _r(46, 90, 50, 22, PAPER, 9)
                + _r(104, 90, 50, 22, PAPER, 9) + _p("M30 118H170V138Q170 146 162 146H38Q30 146 30 138Z", k.main)
                + _p("M30 118H170V128H30Z", k.shade))  # fmt: skip
    top = "M55 66H145Q158 66 158 79V83Q158 96 145 96H55Q42 96 42 83V79Q42 66 55 66Z"
    middle = k.acc if k.pick(14, 2) else k.shade
    return (_r(42, 122, 116, 30, k.main, 13) + _ln("M132 125V149", k.acc, 4) + _r(42, 94, 116, 30, middle, 13)
            + _ln("M132 97V121", k.main, 4) + _p(top, k.main) + _pattern(k, top, 42, 66, 158, 96)
            + _ln("M132 69V93", k.acc, 4))  # fmt: skip


def _lamp(k: Look) -> str:
    """Lighting: a table lamp, a light bulb, a string of lights or a flashlight with its beam."""
    if k.has("string|fairy|strips?|garland|rope|christmas"):
        spots = ((41, 84), (60, 94), (80, 93), (120, 75), (140, 74), (159, 83))
        colours = (k.main, k.acc, k.third)
        return (_ln("M22 66Q60 112 100 84Q140 56 178 100", INK, 2)
                + "".join(_e(x, y + 9, 5.5, 8, colours[i % 3]) for i, (x, y) in enumerate(spots)))  # fmt: skip
    if k.has("flashlights?|torch(es)?|headlamps?|spotlights?"):
        return (_p("M146 80L182 58V150L146 128Z", GLOW, NO + ' opacity=".7"') + _r(34, 90, 88, 28, k.main, 6)
                + _p("M120 86L146 76V132L120 122Z", k.shade) + _r(62, 96, 14, 8, k.acc, 3)
                + _ln("M44 91V117M52 91V117", k.line, 1.5, FAINT))  # fmt: skip
    if k.has("bulbs?"):
        glass = k.main if k.named and k.has("smart|rgb|colou?r(ed)?|colou?rs") else GLOW
        return (_p("M100 44C126 44 140 62 140 84C140 104 124 112 120 132H80C76 112 60 104 60 84C60 62 74 44 100 44Z", glass)
                + _ln("M90 132V106L96 98L100 106L104 98L110 106V132", "#d99a2b", 2) + _r(82, 132, 36, 24, STEEL, 3)
                + _ln("M82 140H118M82 148H118", GREY, 2) + _p("M92 156H108L104 164H96Z", INK))  # fmt: skip
    metal = (STEEL, GOLD, INK)[k.pick(17, 3)]
    shade = "M74 50H126L144 104H56Z" if k.pick(14, 2) else "M62 54H138L142 102H58Z"
    stem = _e(100, 128, 20, 23, k.acc) if k.pick(20, 2) else _r(96, 102, 8, 48, metal, 2)
    return (_e(100, 110, 42, 10, GLOW, NO + ' opacity=".6"') + stem + _r(72, 148, 56, 12, metal, 6) + _p(shade, k.main)
            + _ln("M60 96H140", k.line, 1.5, FAINT))  # fmt: skip


def _gift(k: Look) -> str:
    """A wrapped gift box with ribbon and bow."""
    box = "M52 86H148V160H52Z"
    cross = _r(52, 114, 96, 14, k.acc) if k.pick(14, 2) else ""
    return (_p(box, k.main) + _pattern(k, box, 52, 86, 148, 160) + cross + _r(92, 86, 16, 74, k.acc)
            + _r(45, 70, 110, 20, k.main, 4) + _r(92, 70, 16, 20, k.acc) + _p("M100 70Q74 38 64 54Q60 70 100 70Z", k.acc)
            + _p("M100 70Q126 38 136 54Q140 70 100 70Z", k.acc) + _c(100, 68, 7, k.acc))  # fmt: skip


def _storage(k: Look) -> str:
    """Storage: a bin with lid, a woven basket, a chest of drawers or shelves with things on them."""
    if k.has("shel(f|ves)|shelving|racks?|bookcases?|stands?"):
        return (_ln("M48 40V162M152 40V162", (INK, WOOD, STEEL)[k.pick(14, 3)], 5) + _r(58, 36, 14, 22, k.acc, 2)
                + _r(74, 30, 12, 28, k.third, 2) + _r(118, 78, 26, 22, k.acc, 3) + _r(60, 124, 34, 18, k.third, 3)
                + _c(128, 132, 10, k.shade) + "".join(_r(44, y, 112, 7, k.main, 2) for y in (58, 100, 142)))  # fmt: skip
    if k.has("drawers?|organizers?|cabinets?|dressers?|caddy"):
        return _r(54, 40, 92, 122, k.main, 7) + "".join(
            _r(62, y, 76, 30, k.hi, 4) + _ln(f"M92 {y + 15}H108", k.line, 3) for y in (48, 86, 124)
        )
    if k.has("baskets?|wicker|woven|rattan|hampers?"):
        d = "M46 84H154L144 158H56Z"
        weave = "".join(f"M40 {y}H160" for y in range(96, 158, 12))
        weave += "".join(f"M{x} 84V160" for x in range(58, 150, 12))
        return (_cord("M70 86Q70 54 100 54Q130 54 130 86", k.main, k, 4) + _p(d, k.main)
                + _clip(k, d, _ln(weave, k.line, 2, FAINT)) + _r(42, 78, 116, 10, k.shade, 5))  # fmt: skip
    return (_p("M46 78H154L146 160H54Z", k.main, ' fill-opacity=".88"') + _r(82, 96, 36, 11, k.shade, 5)
            + _ln("M61 124H139M63 142H137", k.line, 1.5, FAINT) + _r(40, 62, 120, 18, k.acc, 5)
            + _r(36, 66, 8, 20, k.shade, 2) + _r(156, 66, 8, 20, k.shade, 2))  # fmt: skip


def _hair(k: Look) -> str:
    """A bundle of hair (wig or extensions) tied at the top: wavy or straight strands, never a head."""
    wave = "q-9 14 0 28t0 28t0 28t0 28" if k.has("wave|wavy|curly|curls?|kinky|bob") else "v112"
    strands = "".join(_ln(f"M{x} 46{wave}", k.shade if i % 2 else k.main, 9) for i, x in enumerate(range(64, 140, 9)))
    return strands + _r(56, 34, 88, 18, k.acc, 9)


def _parcel(k: Look) -> str:
    """The neutral picture for unknown product types: a clean taped parcel with a label."""
    tape = PAPER if k.pick(14, 2) else k.acc
    return (_p("M100 52L160 78L100 104L40 78Z", k.hi) + _p("M40 78L100 104V164L40 138Z", k.main)
            + _p("M100 104L160 78V138L100 164Z", _mix(k.main, "#000000", 0.16))
            + _p("M76 62L64 68L124 94L136 88Z", tape) + _p("M124 94L136 88V106L124 112Z", tape)
            + _p("M52 100L84 114V132L52 118Z", PAPER) + _ln("M58 110L78 119M58 117L72 123", k.line, 1.5, FAINT))  # fmt: skip


# drawing key -> (drawing, may be mirrored, largest tilt in degrees)
DRAWINGS: dict[str, tuple[Callable[[Look], str], bool, int]] = {
    "headphones": (_headphones, False, 0), "sneaker": (_sneaker, True, 3), "boot": (_boot, True, 2),
    "sandal": (_sandal, False, 4), "socks": (_socks, True, 4), "pants": (_pants, False, 3),
    "dress": (_dress, False, 3), "jacket": (_jacket, False, 2), "shirt": (_shirt, False, 3),
    "gloves": (_gloves, False, 3), "hat": (_hat, True, 4), "backpack": (_backpack, False, 2),
    "bag": (_bag, False, 2), "sunglasses": (_sunglasses, False, 5), "jewel": (_jewel, False, 4),
    "watch": (_watch, False, 6), "speaker": (_speaker, False, 0), "phone": (_phone, False, 4),
    "laptop": (_laptop, False, 0), "keyboard": (_keyboard, False, 4), "mouse": (_mouse, False, 8),
    "camera": (_camera, False, 2), "tv": (_tv, False, 0), "charger": (_charger, False, 4),
    "controller": (_controller, False, 5), "puzzle": (_puzzle, False, 8), "toy": (_toy, True, 2),
    "book": (_book, False, 6), "pens": (_pens, True, 4), "knife": (_knife, True, 5), "mug": (_mug, True, 2),
    "bottle": (_bottle, False, 3), "cookware": (_cookware, True, 3), "pet": (_pet, False, 2),
    "fish": (_fish, True, 5), "bike": (_bike, True, 0), "car": (_car, True, 0), "ball": (_ball, False, 10),
    "tent": (_tent, True, 0), "plant": (_plant, True, 0), "xmas": (_xmas, False, 0), "candle": (_candle, False, 0),
    "clock": (_clock, False, 3), "scale": (_scale, False, 3), "guitar": (_guitar, True, 4),
    "tools": (_tools, True, 5), "cosmetics": (_cosmetics, False, 3), "brush": (_brush, True, 5),
    "umbrella": (_umbrella, True, 8), "baby": (_baby, False, 4), "chair": (_chair, True, 0),
    "sofa": (_sofa, False, 0), "bedding": (_bedding, False, 2), "lamp": (_lamp, True, 0), "gift": (_gift, False, 3),
    "storage": (_storage, False, 0), "hair": (_hair, False, 3), "parcel": (_parcel, True, 3),
}  # fmt: skip


# ------------------------------------------------------------------------------- colours, packs, the picture


def _named(text: str) -> list[str]:
    """The colours named in `text` as whole words, in order and without repeats."""
    found: list[str] = []
    for tone, name in _COLOUR_RE.findall(text):
        colour = COLOURS[name]
        if tone:
            colour = _mix(colour, "#ffffff" if _TONE[tone] > 0 else "#000000", abs(_TONE[tone]))
        if colour not in found:
            found.append(colour)
    return found


def _loose(text: str, names: tuple[str, ...]) -> list[str]:
    """Colours hidden inside other characters ("26#redsnowman", "ブラック"), in order of appearance."""
    found: list[str] = []
    for _, name in sorted((text.find(name), name) for name in names if name in text):
        colour = COLOURS[_CJK.get(name, name)]
        if colour not in found:
            found.append(colour)
    return found[:2]


def _look(low: str, colour: str, key: str, h: int) -> Look:
    """Colours and pattern of one product: its colour field first, then its title, then its hash."""
    found, multi = _named(colour), MULTI.search(colour) is not None
    if colour and not found and not multi:
        found = _loose(_COLOURED.sub("", colour), _LOOSE)
    if not found and not multi:
        found, multi = _named(low), MULTI.search(low) is not None
        if not found and not low.isascii():
            found = _loose(low, tuple(_CJK))
    named = bool(found)
    if multi:
        found = list(dict.fromkeys(found + [BRIGHT[(h + 3 * i) % 8] for i in range(3)]))[:3]
    pattern = next((name for name, words in _PATTERN_RES if words.search(low)), "")
    if not pattern:
        pattern = _BY_HASH[(h >> 12) % 8] if key in PATTERNED else "plain"
    palette = DENIM if key == "pants" and _rx("jeans|denim").search(low) else PALETTES.get(key, BRIGHT)
    main = found[0] if found else "#6b7334" if pattern == "camo" else palette[h % len(palette)]
    light = _lum(main)
    if len(found) > 1:
        acc = found[1]
    else:
        tone = _mix(main, "#ffffff", 0.55) if light < 0.45 else _mix(main, "#000000", 0.45)
        acc = (tone, BRIGHT[(h >> 3) % 8], PAPER, INK)[(h >> 6) % 4]
        if not _far(main, acc):
            acc = PAPER if light < 0.5 else INK
    third = found[2] if len(found) > 2 else BRIGHT[(h >> 5) % 8]
    if not (_far(third, main) and _far(third, acc)):
        third = BRIGHT[((h >> 5) + 3) % 8]
    shade = _mix(main, "#ffffff", 0.2) if light < 0.25 else _mix(main, "#000000", 0.18)
    line = _mix(main, "#4b5563", 0.5) if light > 0.75 else _mix(main, "#000000", 0.45)
    hi = _mix(main, "#ffffff", 0.35)
    return Look(low, h, f"{h:08x}", main, acc, third, shade, hi, line, pattern, named)


def _pack(low: str, key: str) -> tuple[int, str]:
    """(copies to draw, corner tag) from "2 pack", "pack of 3", "6 pairs", "3 pcs"; (1, "") for a single."""
    found = PACK.search(low)
    if not found:
        return (2, "2-PACK") if TWIN.search(low) else (1, "")
    number, unit = found.group(1) or found.group(4), found.group(2) or found.group(3)
    count = int(number)
    if count < 2 or (unit[:2] in ("pc", "pi") and key in PIECES):
        return 1, ""
    return min(count, 3), f"{count}-PACK" if unit in ("pack", "pk") else f"×{count}"


def _backdrop(k: Look) -> tuple[str, str]:
    """Top and bottom colour of the studio backdrop: light neutrals or a pale tint; darker behind white."""
    if _lum(k.main) > 0.8:
        tint = k.acc if _lum(k.acc) < 0.75 else "#64748b"
        return _mix(tint, "#ffffff", 0.86), _mix(tint, "#ffffff", 0.72)
    if k.pick(7, 3) == 0 and _lum(k.acc) < 0.8:
        return _mix(k.acc, "#ffffff", 0.94), _mix(k.acc, "#ffffff", 0.82)
    return BACKDROPS[k.pick(8, 5)]


HEAD_END = re.compile(r",| for | with | w/ | compatible | - | – |\(|\|")


def _kind(low: str) -> tuple[str, str | None, str]:
    """(symbol, kind text, drawing key) of a lower-case title.

    A title names its product first and other things after "for", "with" or a comma ("Laptop Desk for Bed",
    "Charging Dock for AirPods"), so the part before that is read first and the whole title only as a fallback.
    """
    for text in (HEAD_END.split(low, maxsplit=1)[0], low):
        for pattern, symbol, search, key in PATTERNS:
            if pattern.search(text):
                return symbol, search, key
    return "📦", None, "parcel"


def kind_of(title: str) -> tuple[str, str | None]:
    """(symbol, kind text) for a product title; a parcel and no text when the type is not recognised."""
    return _kind(title.lower())[:2]


def product_picture(title: str, colour: str, brand: str, product_id: str) -> str:
    """A complete `<svg>` picture of one product (the same product always gets the same picture)."""
    low = (title or "").lower()
    h = zlib.crc32(str(product_id).encode())
    key = _kind(low)[2]
    draw, mirror, tilt = DRAWINGS[key]
    k = _look(low, (colour or "").lower(), key, h)
    count, tag = _pack(low, key)
    turn = k.pick(10, 2 * tilt + 1) - tilt
    moves = ([f"rotate({turn} 100 104)"] if turn else []) + ([MIRROR] if mirror and k.pick(9, 2) else [])
    move = f' transform="{" ".join(moves)}"' if moves else ""
    product = (f'<g id="p{k.uid}" stroke="{k.line}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"'
               f"{move}>{draw(k)}</g>")  # fmt: skip
    if count > 1:  # the product once in <defs>, shown as overlapping smaller copies
        size, spots = (0.82, ((-17, -7), (17, 7))) if count == 2 else (0.74, ((-28, -9), (0, 0), (28, 9)))
        product = f"<defs>{product}</defs>" + "".join(
            f'<use href="#p{k.uid}" transform="translate({round(100 * (1 - size) + dx)} '
            f'{round(104 * (1 - size) + dy)}) scale({size})"/>'
            for dx, dy in spots
        )
    extra = ""
    if tag:
        wide = 12 + 7 * len(tag)
        extra += (f'<rect x="{178 - wide}" y="20" width="{wide}" height="18" rx="9" fill="#1f2933"/>'
                  f'<text x="{178 - wide / 2}" y="33" font-size="11" font-weight="700" fill="#fff" text-anchor="middle" '
                  f'font-family="{FONT}">{html.escape(tag)}</text>')  # fmt: skip
    label = (brand or "").strip()[:14].strip()
    if label:  # small and quiet in the bottom corner, like the brand line on a shop card
        extra += ('<rect x="16" y="179" width="3" height="10" rx="1.5" fill="#9aa1ab"/>'
                  '<text x="23" y="188" font-size="10" font-weight="600" letter-spacing=".4" fill="#6b7280" '
                  f'font-family="{FONT}">{html.escape(label)}</text>')  # fmt: skip
    top, bottom = _backdrop(k)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" preserveAspectRatio="xMidYMid meet">'
            f'<defs><linearGradient id="b{k.uid}" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="200">'
            f'<stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient></defs>'
            f'<rect x="-300" y="-300" width="800" height="800" fill="url(#b{k.uid})"/>'
            f'<ellipse cx="100" cy="171" rx="{72 if count > 1 else 60}" ry="6" fill="#1f2933" opacity=".12"/>'
            f"{product}{extra}</svg>")  # fmt: skip

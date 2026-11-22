"""Look and feel. Light/dark uses Streamlit's own theme (so every widget matches); the CSS only styles our custom HTML."""

from __future__ import annotations

import streamlit as st

ACCENT = "#e47911"
LIGHT = {"base": "light", "bg": "#f2f4f7", "surface": "#ffffff", "text": "#111827", "muted": "#667085", "border": "#e1e5ea",
         "link": "#007185", "good": "#0f9d6b", "warn": "#d97706", "bad": "#dc2626", "info": "#2563eb", "tint": "#f7f8fa",
         "plot": "plotly_white"}  # fmt: skip
DARK = {"base": "dark", "bg": "#0e1217", "surface": "#171d26", "text": "#e8ebf0", "muted": "#98a2b3", "border": "#2a3340",
        "link": "#5cc8dc", "good": "#34d399", "warn": "#fbbf24", "bad": "#f87171", "info": "#60a5fa", "tint": "#1e2631",
        "plot": "plotly_dark"}  # fmt: skip

CSS = """
<style>
:root { --bg:%(bg)s; --surface:%(surface)s; --text:%(text)s; --muted:%(muted)s; --border:%(border)s; --link:%(link)s;
        --good:%(good)s; --warn:%(warn)s; --bad:%(bad)s; --info:%(info)s; --tint:%(tint)s; --accent:#e47911; }
.block-container { padding-top: 3.2rem; max-width: 1380px; }
[data-testid="stSidebar"] { border-right: 1px solid var(--border); }
.muted { color: var(--muted); }
/* live panels refresh every second: do not fade them out while a refresh is on its way */
[data-stale="true"] { opacity: 1 !important; transition: none !important; }
/* ---------- status banner ---------- */
.banner { border-radius: 12px; padding: 14px 18px; margin: 4px 0 14px; display:flex; align-items:center; gap:14px; border:1px solid var(--border); background: var(--surface); }
.banner .dot { width:14px; height:14px; border-radius:50%%; flex:none; }
.banner b { font-size: 1.05rem; } .banner small { color: var(--muted); display:block; }
.banner.good { border-left: 6px solid var(--good); } .banner.good .dot { background: var(--good); }
.banner.bad { border-left: 6px solid var(--bad); } .banner.bad .dot { background: var(--bad); box-shadow: 0 0 0 6px color-mix(in srgb, var(--bad) 22%%, transparent); }
.banner.warn { border-left: 6px solid var(--warn); } .banner.warn .dot { background: var(--warn); }
/* ---------- KPI tiles ---------- */
.kpis { display:grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap:12px; margin-bottom: 14px; }
.tile { background: var(--surface); border:1px solid var(--border); border-top: 4px solid var(--good); border-radius: 12px; padding: 12px 14px; }
.tile.warn { border-top-color: var(--warn); } .tile.bad { border-top-color: var(--bad); }
.tile .label { color: var(--muted); font-size: .74rem; text-transform: uppercase; letter-spacing: .05em; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.tile .value { font-size: 1.45rem; font-weight: 700; white-space:nowrap; line-height:1.3; }
.tile .sub { font-size: .78rem; color: var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.tile .delta { font-size: .78rem; font-weight: 600; } .tile.good .delta { color: var(--good); } .tile.warn .delta { color: var(--warn); } .tile.bad .delta { color: var(--bad); }
/* ---------- badges and cards ---------- */
.badge { display:inline-block; padding: 2px 9px; border-radius: 999px; font-size: .72rem; font-weight: 700; color:#fff; vertical-align: middle; }
.badge.good { background: var(--good); } .badge.warn { background: var(--warn); } .badge.bad { background: var(--bad); }
.badge.info { background: var(--info); } .badge.muted { background: #6b7280; }
.card { background: var(--surface); border:1px solid var(--border); border-radius: 12px; padding: 12px 16px; margin-bottom: 8px; }
.card small { color: var(--muted); }
.steps { display:grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap:12px; margin: 6px 0 16px; }
.step { background: var(--surface); border:1px solid var(--border); border-radius: 12px; padding: 14px; }
.step .n { width:28px; height:28px; border-radius:50%%; background: var(--accent); color:#fff; font-weight:700; display:flex; align-items:center; justify-content:center; margin-bottom:8px; }
.step b { display:block; margin-bottom:2px; } .step span { color: var(--muted); font-size:.86rem; }
.kv { display:grid; grid-template-columns: 200px 1fr; gap: 4px 12px; font-size:.9rem; margin-top:6px; } .kv i { color: var(--muted); font-style: normal; }
.side-status { background: var(--tint); border:1px solid var(--border); border-radius: 10px; padding: 10px 12px; font-size:.86rem; line-height:1.5; }
.side-status b { font-size: 1rem; }
.check { display:flex; gap:10px; padding: 7px 0; border-bottom: 1px dashed var(--border); font-size:.9rem; }
.check .mark { font-weight:800; width:46px; flex:none; } .check.pass .mark { color: var(--good); } .check.fail .mark { color: var(--bad); }
.trail { font-size:.86rem; padding: 6px 0 6px 12px; border-left: 3px solid var(--accent); margin: 6px 0; }
.query { margin: 4px 0 0; font-size:.82rem; } .query summary { cursor:pointer; color: var(--muted); }
.query .qname { font-family: ui-monospace, Consolas, monospace; font-size:.78rem; } .query .rows { margin-left: 10px; font-size:.76rem; }
.query .sql { font-family: ui-monospace, Consolas, monospace; background: var(--tint); border:1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin: 6px 0; word-break: break-word; font-size:.76rem; color: var(--text); }
.trail .tool { color: var(--accent); font-family: ui-monospace, Consolas, monospace; font-size:.9rem; } .trail .found { display:block; margin-top: 2px; }
.query table { border-collapse: collapse; font-size:.78rem; margin: 2px 0 4px; } .query th, .query td { border:1px solid var(--border); padding: 2px 8px; text-align:left; }
.query th { background: var(--tint); } .query .more { color: var(--muted); font-size:.76rem; display:block; }
.activity { margin: 4px 0 10px; font-size:.86rem; } .activity i { color: var(--muted); font-style: normal; }
.minis { display:grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap:8px; margin-top:6px; }
.mini { background: var(--tint); border:1px solid var(--border); border-radius: 10px; padding: 6px 10px; } .mini b { font-size:1.15rem; display:block; } .mini span { color: var(--muted); font-size:.76rem; }
.trail code { font-weight:700; } .trail small { color: var(--muted); display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
/* ---------- storefront ---------- */
.st-key-sl-header { background: #131921; padding: 12px 16px 10px; border-radius: 12px 12px 0 0; }
.sl-logo { font-size: 1.7rem; font-weight: 800; color:#fff; letter-spacing:-.5px; line-height: 1; white-space:nowrap; } .sl-logo b { color:#ff9900; }
.sl-nav { background: #232f3e; padding: 8px 16px; color:#fff; font-size:.86rem; display:flex; gap:22px; flex-wrap:wrap; margin-top:-1rem; }
.sl-demo { background: color-mix(in srgb, var(--warn) 16%%, var(--surface)); border:1px dashed var(--warn); border-radius: 8px; padding: 8px 14px; margin: 10px 0 0; font-size:.86rem; }
.sl-hero { background: linear-gradient(115deg,#232f3e 0%%,#37475a 55%%,#e47911 135%%); color:#fff; padding: 30px 30px; margin: 10px 0 18px; border-radius: 12px; }
.sl-hero h2 { color:#fff; margin:0; font-size: 1.9rem; } .sl-hero p { color:#e5e7eb; margin:6px 0 0; font-size:1rem; }
.sl-results-head { background: var(--surface); border:1px solid var(--border); border-radius:8px; padding:9px 14px; font-size:.9rem; }
.sl-card { background: var(--surface); border:1px solid var(--border); border-radius:10px; padding:10px; height: 318px; overflow:hidden; display:flex; flex-direction:column; }
.sl-card:hover { box-shadow: 0 4px 14px rgba(0,0,0,.12); }
.sl-img { height:128px; border-radius:8px; display:flex; align-items:center; justify-content:center; font-size:3.4rem; background: var(--tint); flex:none; }
.sl-title { color: var(--link); font-size:.87rem; line-height:1.25; margin:8px 0 3px; height:3.75em; overflow:hidden; }
.sl-stars { color:#ffa41c; font-size:.85rem; } .sl-stars small { color: var(--link); }
.sl-price { font-size:1.3rem; font-weight:600; } .sl-price sup { font-size:.62rem; }
.sl-meta { font-size:.75rem; color: var(--muted); } .sl-prime { color:#00a8e1; font-weight:800; font-style:italic; }
.sl-sponsored { font-size:.68rem; color: var(--muted); height: 1.1em; }
.sl-instock { color: var(--good); font-size:.78rem; } .sl-low { color: var(--bad); font-size:.78rem; }
.sl-filter-title { font-weight:700; margin: 12px 0 2px; }
.sl-empty { text-align:center; padding: 44px; background: var(--surface); border:1px solid var(--border); border-radius:10px; }
</style>
"""


def apply(dark: bool) -> dict[str, str]:
    """Switch Streamlit's theme to light or dark, add our CSS, and return the palette (charts use `palette['plot']`)."""
    palette = DARK if dark else LIGHT
    wanted = {"theme.base": palette["base"], "theme.primaryColor": ACCENT, "theme.backgroundColor": palette["bg"],
              "theme.secondaryBackgroundColor": palette["surface"], "theme.textColor": palette["text"]}  # fmt: skip
    changed = [key for key, value in wanted.items() if st.get_option(key) != value]
    for key in changed:
        st._config.set_option(key, wanted[key])
    if changed:
        st.rerun()
    st.markdown(CSS % palette, unsafe_allow_html=True)
    return palette

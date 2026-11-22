"""Reusable dashboard pieces: KPI tiles, the expected-band chart, the agent's report and scenario cards."""

from __future__ import annotations

import html
from urllib.parse import urlencode

import plotly.graph_objects as go
import streamlit as st
from common import (
    AD_CAMPAIGN,
    FAILING_LANGUAGE,
    LANGUAGE_MARKETS,
    SHOP_URL,
    SIMULATE_SPEED,
    Runtime,
    last_hour,
)
from guide import FOREIGN_QUERY, GUIDE, SHOP_VIEW

STATUS_BADGE = {
    "SUPPORTED": ("good", "Cause confirmed"),
    "LIKELY": ("warn", "Likely cause"),
    "HYPOTHESIS": ("bad", "Unconfirmed"),
}
FORMATS = {
    "eur": "€{:,.0f}",
    "share": "{:.1%}",
    "ratio": "{:.2f}",
    "position": "{:.1f}",
    "minutes": "{:.0f} min",
    "ms": "{:.0f} ms",
}


def fmt(rt: Runtime, metric: str, value: float) -> str:
    """Format a metric value by its unit (euros, percent, ...)."""
    return FORMATS.get(rt.pipeline.graph.metric(metric).unit, "{:,.0f}").format(value)


def status(rt: Runtime, metric: str, z: float) -> str:
    """good / warn / bad from the z-score, counting only the harmful direction of the metric."""
    direction = rt.pipeline.graph.metric(metric).bad_direction
    harm = z if direction == "up" else -z if direction == "down" else abs(z)
    return "bad" if harm >= 3 else "warn" if harm >= 2 else "good"


def kpi_grid(rt: Runtime, metrics: list[tuple[str, str]], segment: dict | None = None) -> None:
    """A responsive row of KPI tiles: value, expected value and the difference, coloured by status."""
    tiles = []
    for label, metric in metrics:
        p = rt.point(metric, segment or {}, last_hour(rt))
        if p is None:
            tiles.append(
                f'<div class="tile"><div class="label">{label}</div><div class="value">-</div><div class="sub">no data yet</div></div>'
            )
            continue
        diff = (p["actual"] - p["expected"]) / abs(p["expected"]) if p["expected"] else 0.0
        arrow = "▲" if diff > 0 else "▼"
        tiles.append(
            f'<div class="tile {status(rt, metric, p["z"])}"><div class="label">{label}</div>'
            f'<div class="value">{fmt(rt, metric, p["actual"])}</div>'
            f'<div class="sub">expected {fmt(rt, metric, p["expected"])} <span class="delta">{arrow} {abs(diff):.0%}</span></div></div>'
        )
    st.markdown(f'<div class="kpis">{"".join(tiles)}</div>', unsafe_allow_html=True)


def band_chart(
    rt: Runtime, palette: dict, metric: str, segment: dict | None = None, height: int = 300
) -> None:
    """Hourly actual value on top of the grey 'expected' band; unusual hours are marked in red."""
    frame = rt.band(metric, segment)
    layout = {"template": palette["plot"], "height": height, "margin": {"l": 8, "r": 8, "t": 8, "b": 8}, "paper_bgcolor": "rgba(0,0,0,0)",
              "plot_bgcolor": "rgba(0,0,0,0)", "legend": {"orientation": "h", "y": 1.12}, "hovermode": "x unified"}  # fmt: skip
    fig = go.Figure(layout=layout)
    if not frame.empty:
        fig.add_trace(
            go.Scatter(x=frame["ts"], y=frame["high"], line={"width": 0}, showlegend=False, hoverinfo="skip")
        )
        fig.add_trace(
            go.Scatter(
                x=frame["ts"],
                y=frame["low"],
                fill="tonexty",
                fillcolor="rgba(130,140,155,0.25)",
                line={"width": 0},
                name="expected range",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=frame["ts"],
                y=frame["expected"],
                line={"dash": "dot", "color": "#8b93a1", "width": 1.5},
                name="expected",
            )
        )
        fig.add_trace(
            go.Scatter(x=frame["ts"], y=frame["actual"], line={"color": "#e47911", "width": 3}, name="actual")
        )
        off = frame[frame["z"].abs() >= 3]
        fig.add_trace(
            go.Scatter(
                x=off["ts"],
                y=off["actual"],
                mode="markers",
                marker={"color": palette["bad"], "size": 9},
                name="unusual",
            )
        )
    st.plotly_chart(fig, width="stretch", key=f"band_{metric}_{sorted((segment or {}).items())}_{height}")


def failed_check_rows(check: dict | None) -> str:
    """The 'Failed check' row of a report: the SQL the agent ran, what it expected, what it got and why that fails."""
    if not check:
        return ""
    return (f"<i>Failed check</i><span><b>{html.escape(check['why'])}</b><br>Expected: {html.escape(check['expected'])}<br>"
            f"Got: {html.escape(check['got'])}<br>Tables: {html.escape(', '.join(check['tables']))}"
            f"<br><code>{html.escape(check['sql'])}</code></span>")  # fmt: skip


def report_card(report: dict, state: str | None = None) -> None:
    """The agent's finding: headline, cause, cost, the 4-point evidence checklist, ruled-out alternatives and the trail."""
    cls, label = STATUS_BADGE[report["status"]]
    imp = report["impact"]
    where = ", ".join(f"{k} = {v}" for k, v in report["scope"].items()) or "all traffic"
    state_badge = (
        f' <span class="badge {"bad" if state == "open" else "muted"}">{state}</span>' if state else ""
    )
    st.markdown(
        f'<div class="card"><span class="badge {cls}">{label}</span>{state_badge}<br><b>{html.escape(report.get("summary") or report["headline"])}</b>'
        f'<br><small>{html.escape(report["headline"])}</small>'
        f'<div class="kv"><i>Cause</i><span>{html.escape(report["cause"])}</span><i>Where</i><span>{html.escape(where)}</span>'
        f"<i>Since</i><span>{report['onset'].replace('T', ' ')}</span>"
        f"<i>Cost so far ({imp['hours']} h)</i><span>{imp['lost_orders'] or 0:,.0f} lost orders · €{imp['lost_revenue_eur'] or 0:,.0f} lost revenue · "
        f"€{imp['wasted_ad_spend_eur'] or 0:,.0f} ad spend wasted · €{imp['ad_spend_over_plan_eur'] or 0:,.0f} spent above plan</span>"
        f"{failed_check_rows(report.get('failed_check'))}"
        f"<i>Possible next action</i><span>{html.escape(report['next_action'])}</span></div></div>",
        unsafe_allow_html=True,
    )
    checks = "".join(
        f'<div class="check {"pass" if c["passed"] else "fail"}"><span class="mark">{"PASS" if c["passed"] else "FAIL"}</span>'
        f"<span><b>{c['name']}</b> - {html.escape(c['detail'])}</span></div>"
        for c in report["checklist"]
    )
    st.markdown(f"**Evidence checklist**{checks}", unsafe_allow_html=True)
    with st.expander(f"Other explanations the agent ruled out ({len(report['rejected'])})"):
        st.markdown("\n".join(f"- **{a['name']}** - {a['reason']}" for a in report["rejected"]) or "None.")
        if report["uncertain"]:
            st.markdown("**Still uncertain**\n" + "\n".join(f"- {u}" for u in report["uncertain"]))
    with st.expander(f"How the agent investigated ({len(report['trail'])} steps)"):
        for s in report["trail"]:
            st.markdown(
                f'<div class="trail"><code>{s["n"]}. {s["tool"]}</code> {html.escape(s["why"])}<small>{html.escape(s["result"])}</small></div>',
                unsafe_allow_html=True,
            )
            for sql in s.get("sql") or []:
                st.code(sql, language="sql", wrap_lines=True)


def shop_link(rt: Runtime, sid: str) -> str | None:
    """URL that opens the store exactly where a scenario can be seen (country, device, search text)."""
    if sid == "L1":
        market = rt.journey_market()
        return f"{SHOP_URL}/?{urlencode({'market': market, 'device': 'web', 'q': FOREIGN_QUERY[market]})}"
    if sid not in SHOP_VIEW:
        return None
    market, device, query = SHOP_VIEW[sid]
    return f"{SHOP_URL}/?{urlencode({'market': market, 'device': device, 'q': query})}"


def simulate(rt: Runtime, sid: str) -> None:
    """Button callback: start the scenario and show the fast clock speed on every page's speed control."""
    rt.simulate(sid)
    for page in ("journey", "scenarios"):
        st.session_state[f"{page}_speed"] = SIMULATE_SPEED


def _chart_layout(palette: dict) -> dict:
    return {"template": palette["plot"], "height": 260, "margin": {"l": 8, "r": 8, "t": 8, "b": 8}, "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)", "legend": {"orientation": "h", "y": 1.15}, "hovermode": "x unified"}  # fmt: skip


def step_chart(rt: Runtime, sid: str, palette: dict) -> None:
    """The chart of a simulated step: L1 cumulative orders (expected vs received), AD1 cumulative spend vs budget."""
    fig = go.Figure(layout=_chart_layout(palette))
    if sid == "L1":
        frame = rt.orders_chart(sid)
        market = rt.broken_market.get(sid, rt.journey_market())
        st.caption(f"Orders from {FAILING_LANGUAGE[market]} searches in {LANGUAGE_MARKETS[market]} since you pressed Simulate (cumulative)")
        if not frame.empty:
            fig.add_trace(go.Scatter(x=frame["ts"], y=frame["expected"], line={"dash": "dot", "color": "#8b93a1", "width": 2}, name="expected orders"))
            fig.add_trace(go.Scatter(x=frame["ts"], y=frame["received"], line={"color": "#e47911", "width": 3}, name="received orders"))
    elif sid in AD_CAMPAIGN:
        frame = rt.ads_chart(sid)
        st.caption(f"Ad spend of {AD_CAMPAIGN[sid]} today (cumulative) against its fixed daily budget")
        if not frame.empty:
            fig.add_trace(go.Scatter(x=frame["ts"], y=frame["budget_daily_eur"], line={"color": palette["bad"], "width": 1.5}, name="budget"))
            fig.add_trace(go.Scatter(x=frame["ts"], y=frame["planned"], line={"dash": "dot", "color": "#8b93a1", "width": 2}, name="expected spend"))
            fig.add_trace(go.Scatter(x=frame["ts"], y=frame["spend"], line={"color": "#e47911", "width": 3}, name="actual spend"))
            fig.update_yaxes(tickprefix="€")
    else:
        return
    fig.update_xaxes(title_text="simulated time")
    st.plotly_chart(fig, width="stretch", key=f"step_chart_{sid}")


def live_status(rt: Runtime, sid: str) -> None:
    """What the agent is doing right now, refreshed every second until its finding appears."""
    st.markdown("**What the agent found** (live)")
    lines = rt.progress(sid)
    st.markdown(
        "".join(f'<div class="trail">{html.escape(line)}</div>' for line in lines), unsafe_allow_html=True
    )


def scenario_card(rt: Runtime, sid: str, step: int | None = None, palette: dict | None = None) -> None:
    """One scenario: what it is, how to see it, Simulate / Fix buttons and what the agent found."""
    info, active, finding = GUIDE[sid], sid in rt.active(), rt.finding(sid)
    notices = rt.notices(sid) if not rt.scenarios[sid].event_log or rt.scenarios[sid].calendar else []
    with st.container(border=True):
        head, action = st.columns([4, 1.4], vertical_alignment="center")
        prefix = f"Step {step} · " if step else f"{sid} · "
        badge = ('<span class="badge bad">broken now</span>' if active else
                 '<span class="badge good">agent found it</span>' if finding else "")  # fmt: skip
        head.markdown(f"#### {prefix}{info['title']} {badge}", unsafe_allow_html=True)
        if active:
            action.button("Fix it", key=f"fix_{sid}_{step}", width="stretch", on_click=rt.fix, args=(sid,))
        else:
            if action.button(
                "Simulate it",
                key=f"go_{sid}_{step}",
                type="primary",
                width="stretch",
                on_click=simulate,
                args=(rt, sid),
            ):
                st.rerun(scope="app")  # the button sits in a live fragment; redraw the clock controls too
        st.markdown(
            f'<div class="kv"><i>What breaks</i><span>{info["what"]}</span><i>Where</i><span>{info["where"]}</span>'
            f"<i>What a shopper sees</i><span>{info['shop']}</span><i>What the numbers do</i><span>{info['metrics']}</span>"
            f"<i>What the agent should do</i><span>{info['agent']}</span></div>",
            unsafe_allow_html=True,
        )
        link = shop_link(rt, sid)
        if link:
            st.link_button("See it in the store", link, icon=":material/storefront:")
        if palette and sid in rt.started:
            step_chart(rt, sid, palette)
        if finding:
            st.divider()
            st.markdown(f"**What the agent found** (incident #{finding['incident_id']})")
            report_card(finding, finding["state"])
        elif notices:
            st.success(
                "No incident was opened. The agent only posted:  \n" + "  \n".join(f"- {n}" for n in notices)
            )
        elif active:
            st.divider()
            live_status(rt, sid)

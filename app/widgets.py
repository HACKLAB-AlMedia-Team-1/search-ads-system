"""Reusable dashboard pieces: KPI tiles, the expected-band chart, the agent's report and scenario cards."""

from __future__ import annotations

import html
from datetime import datetime, timedelta
from urllib.parse import urlencode

import plotly.graph_objects as go
import streamlit as st
from common import (
    AD_CAMPAIGN,
    FAILING_LANGUAGE,
    LANGUAGE_MARKETS,
    SHOP_URL,
    Runtime,
    last_hour,
)
from guide import FOREIGN_QUERY, GUIDE, SHOP_VIEW

from rootsight.agent.report import cost_parts

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


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:,.4g}"
    return str(value).removesuffix(":00.000").replace("T", " ")


def query_details(query: dict) -> str:
    """One query the agent ran, collapsed to its name and row count; opened, it shows the SQL and the rows saved at that moment."""
    if not query:
        return ""
    shown, total = query["rows"], query["row_count"]
    head = "".join(f"<th>{html.escape(c)}</th>" for c in query["columns"])
    body = "".join("<tr>" + "".join(f"<td>{html.escape(_cell(v))}</td>" for v in row) + "</tr>" for row in shown)
    more = f'<span class="more">first {len(shown)} of {total} rows</span>' if total > len(shown) else ""
    table = f"<table><tr>{head}</tr>{body}</table>{more}" if shown else '<span class="more">The query returned no rows.</span>'
    return (f'<details class="query"><summary><code>{html.escape(query["name"])}</code><span>{total} row{"" if total == 1 else "s"}</span>'
            f"</summary><pre>{html.escape(query['sql'])}</pre>{table}</details>")  # fmt: skip


def failed_check_rows(check: dict | None) -> str:
    """The 'Failed check' row of a report: why it fails, what was expected, what came back, and the query (collapsed)."""
    if not check:
        return ""
    return (f"<i>Failed check</i><div><b>{html.escape(check['why'])}</b><br>Expected: {html.escape(check['expected'])}<br>"
            f"Got: {html.escape(check['got'])}{query_details(check.get('query') or {})}</div>")  # fmt: skip


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
        f"<i>Cost so far ({imp['hours']} h)</i><span>{html.escape(' · '.join(cost_parts(imp)) or 'no measurable cost yet')}</span>"
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
        st.caption(
            "Each step is one tool the agent used. Under it are the queries that tool ran: open one to see its SQL and the rows it returned."
        )
        st.markdown(
            "".join(
                f'<div class="trail"><code>{s["n"]}. {s["tool"]}</code> {html.escape(s["why"])}<small>{html.escape(s["result"])}</small>'
                f"{''.join(query_details(q) for q in s.get('queries') or [])}</div>"
                for s in report["trail"]
            ),
            unsafe_allow_html=True,
        )


def shop_link(rt: Runtime, sid: str) -> str | None:
    """URL that opens the store exactly where a scenario can be seen (country, device, search text)."""
    if sid == "L1":
        market = rt.journey_market()
        return f"{SHOP_URL}/?{urlencode({'market': market, 'device': 'web', 'q': FOREIGN_QUERY[market]})}"
    if sid not in SHOP_VIEW:
        return None
    market, device, query = SHOP_VIEW[sid]
    return f"{SHOP_URL}/?{urlencode({'market': market, 'device': device, 'q': query})}"


def _chart_layout(palette: dict) -> dict:
    return {"template": palette["plot"], "height": 260, "margin": {"l": 8, "r": 8, "t": 8, "b": 8}, "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)", "legend": {"orientation": "h", "y": 1.15}, "hovermode": "x unified"}  # fmt: skip


def _mark(fig: go.Figure, when: datetime, text: str, color: str) -> None:
    """A dashed vertical line with a label at a moment on the time axis."""
    fig.add_shape(type="line", x0=when, x1=when, y0=0, y1=1, yref="paper", line={"color": color, "width": 1.5, "dash": "dash"})
    fig.add_annotation(x=when, y=1, yref="paper", text=text, showarrow=False, xanchor="left", yanchor="top",
                       font={"size": 11, "color": color})  # fmt: skip


def step_chart(rt: Runtime, sid: str, palette: dict) -> None:
    """The chart of a simulated step: L1 cumulative orders since Simulate, AD1 cumulative spend over the whole day (00-24 h)."""
    fig = go.Figure(layout=_chart_layout(palette))
    since, ended = rt.started[sid], rt.ended.get(sid)
    grey, orange = {"dash": "dot", "color": "#8b93a1", "width": 2}, {"color": "#e47911", "width": 3}
    if sid == "L1":
        frame = rt.orders_chart(sid)
        market = rt.broken_market.get(sid, rt.journey_market())
        st.caption(f"Orders from {FAILING_LANGUAGE[market]} searches in {LANGUAGE_MARKETS[market]} since you pressed Simulate (cumulative)")
        if not frame.empty:
            fig.add_trace(go.Scatter(x=[since, *frame["ts"]], y=[0, *frame["expected"]], line=grey, name="expected orders"))
            fig.add_trace(go.Scatter(x=[since, *frame["ts"]], y=[0, *frame["received"]], line=orange, name="received orders"))
        fig.update_xaxes(range=[since, max(since + timedelta(hours=8), ended or rt.now)])
        fig.update_yaxes(rangemode="tozero")
    elif sid in AD_CAMPAIGN:
        frame, day = rt.ads_chart(sid), rt.ads_day(sid)
        night = day + timedelta(days=1)
        st.caption(f"Ad spend of {AD_CAMPAIGN[sid]} on {day:%a %d %b}, 00:00 to 24:00 (cumulative), against its fixed daily budget")
        if not frame.empty:
            budget = frame["budget_daily_eur"].iloc[0]
            fig.add_trace(go.Scatter(x=[day, night], y=[budget, budget], line={"color": palette["bad"], "width": 1.5}, name="daily budget"))
            fig.add_trace(go.Scatter(x=[day, *frame["ts"]], y=[0, *frame["planned"]], line=grey, name="expected spend"))
            fig.add_trace(go.Scatter(x=[day, *frame["ts"]], y=[0, *frame["spend"]], line=orange, name="actual spend"))
        for when, text in ((since, "Simulate it"), (ended, "End Simulation")):
            if when and day <= when <= night:
                _mark(fig, when, text, palette["muted"])
        fig.update_xaxes(range=[day, night], dtick=3 * 3600 * 1000, tickformat="%H:%M")
        fig.update_yaxes(tickprefix="€", rangemode="tozero")
    else:
        return
    fig.update_xaxes(title_text="simulated time")
    st.plotly_chart(fig, width="stretch", key=f"step_chart_{sid}")


def store_activity(rt: Runtime, sid: str) -> None:
    """What the person at the ShopLens store did since Simulate was pressed, refreshed every second."""
    tiles = "".join(f'<div class="mini"><b>{n}</b><span>{label}</span></div>' for label, n in rt.store_activity(sid).items())
    st.markdown(
        '<div class="activity"><i>Your store activity since you pressed Simulate (your own actions in the ShopLens store)</i>'
        f'<div class="minis">{tiles}</div></div>',
        unsafe_allow_html=True,
    )


def live_status(rt: Runtime, sid: str) -> None:
    """What the agent is doing right now, refreshed every second until its finding appears."""
    st.markdown("**What the agent found** (live)")
    lines = rt.progress(sid)
    st.markdown(
        "".join(f'<div class="trail">{html.escape(line)}</div>' for line in lines), unsafe_allow_html=True
    )


def scenario_card(rt: Runtime, sid: str, step: int | None = None, palette: dict | None = None) -> None:
    """One scenario: what it is, how to see it, Simulate / End Simulation buttons and what the agent found."""
    info, active, finding = GUIDE[sid], sid in rt.active(), rt.finding(sid)
    notices = rt.notices(sid) if not rt.scenarios[sid].event_log or rt.scenarios[sid].calendar else []
    with st.container(border=True):
        head, action = st.columns([4, 1.4], vertical_alignment="center")
        prefix = f"Step {step} · " if step else f"{sid} · "
        badge = ('<span class="badge bad">broken now</span>' if active else
                 '<span class="badge good">agent found it</span>' if finding else "")  # fmt: skip
        head.markdown(f"#### {prefix}{info['title']} {badge}", unsafe_allow_html=True)
        if active:
            action.button("End Simulation", key=f"end_{sid}_{step}", width="stretch", on_click=rt.end_simulation, args=(sid,))
        else:
            action.button("Simulate it", key=f"go_{sid}_{step}", type="primary", width="stretch", on_click=rt.simulate, args=(sid,))
        st.markdown(
            f'<div class="kv"><i>What breaks</i><span>{info["what"]}</span><i>Where</i><span>{info["where"]}</span>'
            f"<i>What a shopper sees</i><span>{info['shop']}</span><i>What the numbers do</i><span>{info['metrics']}</span>"
            f"<i>What the agent should do</i><span>{info['agent']}</span></div>",
            unsafe_allow_html=True,
        )
        link = shop_link(rt, sid)
        if link:
            st.link_button("See it in the store", link, icon=":material/storefront:")
        if sid in rt.started:
            if palette:
                step_chart(rt, sid, palette)
            store_activity(rt, sid)
        if finding:
            st.divider()
            st.markdown(f"**What the agent found** (incident #{finding['incident_id']})")
            report_card(finding, finding["state"] if active else "resolved")
        elif notices:
            st.success(
                "No incident was opened. The agent only posted:  \n" + "  \n".join(f"- {n}" for n in notices)
            )
        elif active:
            st.divider()
            live_status(rt, sid)

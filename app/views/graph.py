"""The metric graph: pick a metric and see what composes it, what may cause it and which events can affect it."""

from __future__ import annotations

import streamlit as st
from common import last_hour, page
from streamlit_agraph import Config, Edge, Node, agraph
from widgets import band_chart

EDGES = {
    "formula": ("#2563eb", False, "exact formula"),
    "funnel": ("#0f9d6b", False, "funnel step"),
    "may_be_caused_by": ("#e47911", True, "may be caused by"),
    "context": ("#8b5cf6", True, "events that can affect it"),
}
WHOLE = "(whole graph)"

rt, palette = page()
graph = rt.pipeline.graph
st.title("Metric graph")
st.caption(
    f"{len(graph.specs)} metrics. The agent walks this graph from a symptom (for example orders) upstream to a cause. "
    "Pick a metric to see everything that feeds into it."
)
legend = " ".join(
    f'<span class="badge" style="background:{colour}">{label}</span>' for colour, _, label in EDGES.values()
)
st.markdown(
    f'{legend} <span class="badge good">normal now</span> <span class="badge bad">unusual now</span> <span class="badge muted">not scored</span>',
    unsafe_allow_html=True,
)
choices = [*sorted(graph.specs, key=lambda m: -graph.metric(m).business_weight), WHOLE]
focus_col, depth_col = st.columns([3, 1])
focus = focus_col.selectbox("Metric", choices, index=choices.index("orders"))
depth = depth_col.slider("Levels upstream", 1, 4, 2, disabled=focus == WHOLE)

if focus == WHOLE:
    keep = set(graph.specs)
else:
    keep = {focus} | {u["metric"] for u in graph.upstream(focus) if u["depth"] <= depth}
contexts = {u for u, v, d in graph.graph.edges(data=True) if d["type"] == "context" and v in keep}

nodes = []
for name in keep:
    point = rt.point(name, {}, last_hour(rt)) if name != "rows_completeness" else None
    colour = (
        palette["muted"] if point is None else palette["bad"] if abs(point["z"]) >= 3 else palette["good"]
    )
    nodes.append(
        Node(
            id=name,
            label=name,
            size=26 if name == focus else 16,
            color=colour,
            font={"color": palette["text"], "size": 15},
        )
    )
nodes += [
    Node(id=c, label=c, shape="box", size=12, color="#8b5cf6", font={"color": "#ffffff"}) for c in contexts
]
edges = []
for u, v, d in graph.graph.edges(data=True):
    if d["type"] in EDGES and u in keep | contexts and v in keep:
        colour, dashed, label = EDGES[d["type"]]
        title = label + (f" (confidence {d['confidence']})" if d.get("confidence") else "")
        edges.append(Edge(source=u, target=v, color=colour, dashes=dashed, width=2, title=title))
clicked = agraph(
    nodes,
    edges,
    Config(
        width="100%",
        height=560,
        directed=True,
        physics=focus == WHOLE,
        hierarchical=focus != WHOLE,
        direction="LR",
        sortMethod="directed",
    ),
)

selected = clicked if clicked in graph.specs else focus if focus != WHOLE else None
if selected:
    spec, near = graph.metric(selected), graph.neighbors(selected)
    st.subheader(selected)
    st.write(spec.description)
    facts = {
        "Formula inputs": ", ".join(f"{i['metric']} ({i['role']})" for i in near["formula_inputs"]),
        "May be caused by": ", ".join(f"{c['metric']} ({c['confidence']})" for c in near["causes"]),
        "Can be split by": ", ".join(s["dimension"] for s in near["split_by"]),
        "Events that can affect it": ", ".join(
            ", ".join(c.get("components") or c.get("types") or []) for c in near["context"]
        ),
    }
    st.markdown("\n".join(f"- **{k}:** {v}" for k, v in facts.items() if v))
    band_chart(rt, palette, selected, height=280)

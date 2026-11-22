"""Simulate-page backend: SQL shown to people, metric edits saved to YAML, user-written scenarios and the LLM rewrite guard."""

import shutil
from datetime import datetime
from types import SimpleNamespace

import yaml

from rootsight.agent.narrate import narrate
from rootsight.agent.report import Report
from rootsight.graph.graph import DEFAULT_FILE, MetricGraph
from rootsight.graph.onboarding import edit_metric
from rootsight.sim.custom import draft_scenario, save_scenario
from rootsight.sim.faults import load_scenarios
from rootsight.store.db import inline_sql

END = datetime(2026, 11, 21)
OFFLINE = SimpleNamespace(available=False)


def test_inline_sql_writes_the_parameters_in():
    sql = inline_sql("SELECT * FROM t WHERE a = ? AND ts >= ? AND n > ?", ["O'Neil", datetime(2026, 11, 27, 9), 3])
    assert sql == "SELECT * FROM t WHERE a = 'O''Neil' AND ts >= TIMESTAMP '2026-11-27 09:00:00' AND n > 3"


def test_editing_a_builtin_metric_rewrites_only_its_lines_in_metrics_yaml(history_db, tmp_path):
    builtin = tmp_path / "metrics.yaml"
    shutil.copy(DEFAULT_FILE, builtin)
    graph, sql = MetricGraph.load(), "SUM(searches_with_click) / NULLIF(SUM(searches), 0) FROM fact_hourly"
    result = edit_metric(history_db, graph, "search_ctr", "Share of searches with a click", sql, END, builtin_file=builtin)
    assert result.added and not result.problems and result.proposals
    assert graph.metric("search_ctr").description == "Share of searches with a click"
    text = builtin.read_text(encoding="utf-8")
    assert yaml.safe_load(text)["metrics"]["search_ctr"]["sql"] == sql
    assert text.count("\n") == DEFAULT_FILE.read_text(encoding="utf-8").count("\n") and "#" in text


def test_editing_with_broken_sql_is_refused_and_nothing_is_saved(history_db, tmp_path):
    builtin = tmp_path / "metrics.yaml"
    shutil.copy(DEFAULT_FILE, builtin)
    result = edit_metric(history_db, MetricGraph.load(), "orders", "x", "SUM(nope) FROM fact_hourly", END, builtin_file=builtin)
    assert not result.added and result.problems
    assert builtin.read_text(encoding="utf-8") == DEFAULT_FILE.read_text(encoding="utf-8")


def _draft(history_db, sid, what, where, shop):
    return draft_scenario(history_db, MetricGraph.load(), OFFLINE, {"L1", "INV1"}, sid, "My scenario", what, where, shop, END)


def test_a_described_stock_failure_maps_to_the_supplier_fault_and_is_saved(history_db, tmp_path):
    draft = _draft(history_db, "my1", "The supplier delivery for top sellers is late.", "Spain",
                   "Products show currently unavailable.")  # fmt: skip
    assert draft.possible and draft.fault == "supplier_delivery_late" and draft.scope == {"market": "ES"}
    assert "in_stock_rate_top" in draft.numbers and "goods-receiving" in draft.agent
    save_scenario(draft, tmp_path)
    assert load_scenarios(tmp_path)["MY1"].fault == "supplier_delivery_late"


def test_scenarios_the_simulator_cannot_produce_say_why(history_db):
    unknown = _draft(history_db, "MY2", "The payment provider rejects cards.", "Germany", "Payment fails.")
    assert not unknown.possible and "cannot be simulated right now" in unknown.problems[0]
    elsewhere = _draft(history_db, "MY3", "The supplier delivery is late.", "France", "Out of stock.")
    assert not elsewhere.possible and "France".lower() in elsewhere.problems[0].lower()
    taken = _draft(history_db, "L1", "The supplier delivery is late.", "Germany", "Out of stock.")
    assert "already exists" in taken.problems[0]


def test_the_llm_rewrite_is_dropped_when_it_invents_numbers():
    report = Report.model_construct(case_id="C1", summary="Orders fell by 120.", cause="x", scope="DE", onset="09:00",
                                    impact="120 orders", failed_check={}, next_action="Chase the supplier.")  # fmt: skip
    assert narrate(report, OFFLINE, END) is report
    inventing = SimpleNamespace(available=True, chat=lambda *a: {"content": '{"summary": "Lost 999 orders.", "next_action": "Fix"}'})
    assert narrate(report, inventing, END).summary == "Orders fell by 120."
    honest = SimpleNamespace(available=True, chat=lambda *a: {"content": '{"summary": "Germany lost 120 orders.", "next_action": "Call"}'})
    assert narrate(report, honest, END).summary == "Germany lost 120 orders."

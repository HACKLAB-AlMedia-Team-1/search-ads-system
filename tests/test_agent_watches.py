"""The agent: rules first everywhere, the model only where rules cannot (scripted fake model, no network)."""

import json
from datetime import datetime, timedelta

import pytest

from rootsight.agent.evidence import SUPPORTED
from rootsight.agent.investigator import MODEL_TRIED, RULES, TAKEN_OVER
from rootsight.agent.watches import MODEL, OK, PROBLEM, RULE, UNCLEAR, WAITING, check_model_watch, plan_watch
from rootsight.graph.graph import MetricGraph
from rootsight.monitor.watcher import Case

H = timedelta(hours=1)
FAULT_AT = datetime(2026, 11, 21, 10)


def call(tool: str, **args) -> dict:
    return {"role": "assistant", "content": f"use {tool}",
            "tool_calls": [{"id": tool, "function": {"name": tool, "arguments": json.dumps(args)}}]}  # fmt: skip


class ScriptedModel:
    """Answers agent turns from a script (then stops calling tools); 'fast' wording requests get unusable text."""

    available = True

    def __init__(self, *replies: dict):
        self.replies, self.agent_turns = list(replies), 0

    def chat(self, role, messages, tools, case_id, now):
        if role == "fast":
            return {"role": "assistant", "content": "no json here"}
        self.agent_turns += 1
        return self.replies.pop(0) if self.replies else {"role": "assistant", "content": "done"}


def use(live, model) -> None:
    live.llm = live.investigator.llm = model


class Offline:
    available = False


@pytest.fixture(scope="module")
def agent(live):
    yield live
    use(live, Offline())


def test_plain_words_become_rule_watches_and_judgement_waits_for_a_model(history_db):
    graph, now = MetricGraph.load(), datetime(2026, 11, 21)
    rule = plan_watch("Watch zero results in Germany on Android", graph, Offline(), history_db, now)
    assert (rule.kind, rule.metric, rule.segment) == (
        RULE,
        "zero_result_rate",
        {"market": "DE", "platform": "android"},
    )
    ads = plan_watch("tell me if the ad budget in Spain runs out", graph, Offline(), history_db, now)
    assert (ads.kind, ads.metric, ads.segment) == (
        RULE,
        "ad_spend",
        {"market": "ES"},
    )  # ads have no device split
    assert plan_watch("keep an eye on paid orders", graph, Offline(), history_db, now).metric == "paid_orders"
    judged = plan_watch(
        "Watch whether German results look like they are in English", graph, Offline(), history_db, now
    )
    assert judged.kind == MODEL and judged.metric is None and "offline" in judged.reason
    # with a model that answers nonsense, planning still ends in a model watch instead of failing
    assert plan_watch("watch if results look English", graph, ScriptedModel(), history_db, now).kind == MODEL


def test_rule_watch_is_scored_every_hour_and_model_watch_waits_offline(agent):
    use(agent, Offline())
    rule, _ = agent.add_watch(agent.plan_watch("watch zero results in Germany on Android"))
    model, _ = agent.add_watch(agent.plan_watch("watch whether German results look English"))
    assert ("zero_result_rate", {"market": "DE", "platform": "android"}) in agent.watcher._pinned
    agent.run_until(FAULT_AT)
    assert "zero_result_rate" in agent.watch_state(rule) and agent.watch_state(model) == WAITING
    assert agent.watches.due(FAULT_AT) and agent._model_watches(FAULT_AT) == []  # no model: nothing runs
    agent.watches.stop(model.watch_id)


def test_ask_answers_normal_numbers_without_investigating(agent):
    use(agent, Offline())
    normal = agent.ask("why are orders down in Germany?")
    assert normal.metric == "orders" and normal.segment == {"market": "DE"} and normal.report is None
    assert "normal range" in normal.text
    assert agent.ask("why is the weather bad?").metric is None


def test_rules_confirm_a_known_failure_so_the_model_is_never_called(agent):
    model = ScriptedModel()
    use(agent, model)
    agent.sim.activate(agent.scenarios["S12"], at=FAULT_AT)
    opened = [e for r in agent.run_until(FAULT_AT + 3 * H) for e in r.events if e.kind == "opened"]
    assert [(e.report.cause_component, e.report.status, e.report.method) for e in opened] == [
        ("search-analyzer", SUPPORTED, RULES)
    ]
    answer = agent.ask("why do searches find nothing in Germany?")
    assert answer.report.status == SUPPORTED and answer.report.cause_component == "search-analyzer"
    assert model.agent_turns == 0  # the rules confirmed both: the model was not needed
    agent.sim.stop_all(agent.now)
    agent.run_until(agent.now + 5 * H)


def test_model_takes_over_when_the_rules_cannot_confirm(agent, monkeypatch):
    hour = agent.now - H
    case = Case("T1", hour, "question", "Question: test", "orders", {"market": "US"}, hour, 0.0)
    script = (call("get_events", hours_back=24),
              call("record_hypothesis", cause="nothing changed", metric="orders", segment={"market": "US"}),
              call("finish", summary="tested"))  # fmt: skip
    # the recipe tests causes but confirms none; a model cause that is no stronger does not replace them
    model = ScriptedModel(*script)
    use(agent, model)
    report = agent.investigator.run(case)
    assert report.method == MODEL_TRIED and model.agent_turns == 3
    tools = [s["tool"] for s in report.trail]
    assert tools.count("finish") == 2 and "get_events" in tools[tools.index("finish") :]  # the model continued the trail
    # a recipe that finds no cause at all: the model's tested cause is the best one, so the model found it
    no_recipe = lambda tb, c: tb.call("finish", {"summary": "no recipe fits"})
    monkeypatch.setattr("rootsight.agent.investigator.offline_policy.investigate", no_recipe)
    use(agent, ScriptedModel(*script))
    report = agent.investigator.run(case)
    assert report.method == TAKEN_OVER and report.cause == "nothing changed"
    use(agent, ScriptedModel())  # a model that does nothing: the recipe's result stands as it is
    assert agent.investigator.run(case).method == RULES


def test_model_watch_verdicts_are_checked_in_code(agent):
    use(agent, Offline())
    watch, _ = agent.add_watch(agent.plan_watch("watch whether Spanish results look odd"))
    hour = agent.now - H
    ok = ScriptedModel(
        call("get_metric", name="relevance_at_10", segment={"market": "ES"}),
        call("verdict", status="ok", reason="fine"),
    )
    assert check_model_watch(watch, agent.toolbox, ok, hour)[:2] == (OK, "fine")
    invented = ScriptedModel(call("verdict", status="problem", metric="relevance_at_10", segment={"market": "ES"},
                                  reason="relevance fell 87654 points"))  # fmt: skip
    verdict, note, case = check_model_watch(watch, agent.toolbox, invented, hour)
    assert (
        verdict == PROBLEM
        and "87654" not in note
        and case.root_metric == "relevance_at_10"
        and case.segment == {"market": "ES"}
    )
    unknown = ScriptedModel(call("verdict", status="problem", metric="made_up_metric", reason="bad"))
    assert check_model_watch(watch, agent.toolbox, unknown, hour)[0] == UNCLEAR
    assert check_model_watch(watch, agent.toolbox, ScriptedModel(), hour)[0] == UNCLEAR  # no verdict at all
    agent.watches.stop(watch.watch_id)


def test_a_model_watch_problem_becomes_an_investigated_incident(agent):
    use(agent, Offline())
    watch, _ = agent.add_watch(agent.plan_watch("watch whether Japanese results look odd"))
    hour = agent.now if agent.now.hour >= 7 else agent.now.replace(hour=10)
    agent.run_until(hour)
    use(
        agent,
        ScriptedModel(
            call(
                "verdict", status="problem", metric="relevance_at_10", segment={"market": "JP"}, reason="odd"
            )
        ),
    )
    events = agent.step().events
    stored = next(w for w in agent.watches.all() if w.watch_id == watch.watch_id)
    assert stored.last_verdict == PROBLEM and stored.last_check == hour
    assert [e.kind for e in events if e.case and e.case.case_id.endswith(f"{watch.watch_id}-p")] in (
        ["opened"],
        ["ongoing"],
        ["updated"],
    )
    assert not agent.watches.due(hour + H)  # it looks again only after its interval

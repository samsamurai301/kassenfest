"""The fixer agent: tools that hand out facts and check what comes back, the loop, the store.

Run on the demo month as a perfect reader sees it (`stored_month`), with a scripted model.
"""

import datetime as dt
import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kassenfest.agents.fixer import Desk, amount_of, brief, draft, due, fix_month, latest_fixes
from kassenfest.api.app import app
from kassenfest.api.deps import Deps, run_deps
from kassenfest.api.live import build_world
from kassenfest.api.routes import current_world
from kassenfest.llm.client import MetaModelClient
from kassenfest.pipeline.month import evaluate_month
from kassenfest.storage import BlobStore
from tests.conftest import FakeResponse
from tests.test_casefile import DEMO, records, stored_month  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not (DEMO / "manifest.json").exists(), reason="no demo set")

AS_OF = dt.date(2026, 11, 5)  # Thu; the bills go out on Fri 6 Nov


class Scripted:
    """Answers turn n of a tool loop with the n-th scripted message: (words, [(tool, args)])."""

    def __init__(self, turns: list[tuple[str, list[tuple[str, dict[str, Any]]]]]):
        self.calls: list[dict[str, Any]] = []

        async def create(**kwargs: Any) -> FakeResponse:
            self.calls.append(kwargs)
            n = sum(m["role"] == "assistant" for m in kwargs["messages"])
            words, tools = turns[n]
            calls = [
                {"id": f"c{n}.{i}", "type": "function", "function": {"name": t, "arguments": a}}
                for i, (t, args) in enumerate(tools)
                for a in [args if isinstance(args, str) else json.dumps(args)]
            ]
            message = {"content": words, "tool_calls": calls or None}
            usage = {"prompt_tokens": 1000, "completion_tokens": 100}
            return FakeResponse({"choices": [{"message": message}], "usage": usage})

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


def albers(engine) -> Desk:
    month = evaluate_month(engine, records(), "2026-10")
    return Desk(brief(month, "p01", month.findings, AS_OF))


def test_the_tools_hand_out_facts_under_refs_and_compute_every_deadline(stored_month):  # noqa: F811
    desk = albers(stored_month)
    _, found = desk.call("get_claim_findings", "{}")
    assert found["today"] == "Do 05.11.2026"
    assert [(f["ref"], f["rule"]) for f in found["findings"]] == [
        ("F1", "HKP-FOLGE-WINDOW"),
        ("F2", "HKP-RX-REQUIRED"),
    ]
    assert found["findings"][0]["lines"]["count"] == 34
    assert found["findings"][0]["evidence"][0]["document"] == "D1"
    doc_ids = [d.document.id for d in desk.brief.docs]
    assert not any(i in json.dumps(found) for i in doc_ids)  # random ids stay out of the prompt

    _, context = desk.call("get_patient_context", "{}")
    (doctor,) = context["doctors"]
    assert doctor["ref"] == "A1" and doctor["address"] == "Marktplatz 4, 94491 Hengersberg"
    assert {"A1", "K1", "patient", "office"} <= set(context["recipients"])

    deadlines = {
        "billing_run": ({}, "Fr 06.11.2026"),  # 5th working day of November
        "folge_window": ({"document": "D1"}, "Mi 14.10.2026"),
        "reply": ({"working_days": "3"}, "Di 10.11.2026"),  # a string is fine too
    }
    for kind, (args, date) in deadlines.items():
        _, result = desk.call("compute_deadline", json.dumps({"kind": kind} | args))
        assert result["date"] == date, kind
    assert result["deadline"] == "T3"
    _, window = desk.call("compute_deadline", '{"kind": "folge_window", "document": "D1"}')
    assert (window["window_from"], window["passed"]) == ("Mo 12.10.2026", True)
    _, bad = desk.call("compute_deadline", '{"kind": "rx_submission", "document": "D3"}')
    assert bad["ok"] is False  # D3 is the Leistungsnachweis
    _, bad = desk.call("compute_deadline", '{"kind": "someday"}')
    assert bad["ok"] is False and len(desk.deadlines) == 4


def test_a_draft_quoting_anything_no_tool_said_goes_back(stored_month):  # noqa: F811
    desk = albers(stored_month)
    desk.call("get_claim_findings", "{}")
    desk.call("get_patient_context", "{}")
    invented = {
        "recipient": "A1",
        "subject": "Folgeverordnung für Frau Albers",
        "body": "Sehr geehrte Damen und Herren,\nfür Erika Albers (X785676317) bitten wir um eine "
        "Verordnung ab 01.12.2026 (D1), offen sind 999,00 €, Termin 23:59, Genehmigung "
        "HKP-2026-111111. Mit freundlichen Grüßen",
    }
    _, sent_back = desk.call("draft_letter", json.dumps(invented))
    problems = " | ".join(sent_back["problems"])
    for expected in (
        "greeting",
        "sign-off",
        "D1 are refs",
        "without Herr or Frau",
        "date 01.12.2026",
        "amount 999,00 €",
        "time 23:59",
        "HKP-2026-111111",
    ):
        assert expected in problems, expected
    assert "X785676317" not in problems  # in the records: fine
    assert not desk.drafts

    body = (
        "für Erika Albers, geboren am 21.08.1947, endete Ihre Verordnung am 14.10.2026. Bitte "
        "stellen Sie eine Folgeverordnung für die weitere Versorgung aus"
    )
    _, sent_back = desk.call("draft_letter", json.dumps({**invented, "subject": "x", "body": body}))
    assert sent_back["problems"] == ["end the body with a full sentence"]
    _, ok = desk.call("draft_letter", json.dumps({**invented, "subject": "x", "body": body + "."}))
    assert ok == {
        "ok": True,
        "letter": "L1",
        "to": ["Praxis Dr. med. Markus Ederer", "Marktplatz 4", "94491 Hengersberg"],
        "channel": "fax",
    }
    letter = desk.drafts["L1"].letter.body
    assert letter.startswith("Guten Tag Dr. Markus Ederer,\n\nfür Erika Albers")
    assert letter.endswith("Pflegedienstleitung\nPflegedienst Sonnenschein GmbH")

    note = "Bitte die Leistungen vom 15.10.2026 bis 31.10.2026 vor dem Abrechnungslauf streichen"
    _, ok = desk.call(
        "draft_letter", json.dumps({"recipient": "office", "subject": "x", "body": note})
    )
    assert desk.drafts[ok["letter"]].letter.body == note  # internal: no greeting, no sign-off


def test_an_action_needs_a_computed_deadline_a_checked_draft_and_a_fitting_recipient(
    stored_month,  # noqa: F811
):
    desk = albers(stored_month)
    desk.call("get_claim_findings", "{}")
    desk.call("compute_deadline", '{"kind": "billing_run"}')
    note = "Bitte die Leistungen vom 15.10.2026 bis 31.10.2026 aus der Rechnung nehmen."
    desk.call("draft_letter", json.dumps({"recipient": "office", "subject": "x", "body": note}))
    action = {"title": "Take the uncovered lines off", "why": "They would be rejected."}

    _, bad = desk.call(
        "create_action",
        json.dumps(
            action | {"kind": "stamp_request", "findings": ["F9"], "deadline": "T7", "letter": "L5"}
        ),
    )
    assert len(bad["problems"]) == 3  # no F9, no T7, no L5
    _, bad = desk.call(
        "create_action",
        json.dumps(
            action | {"kind": "stamp_request", "findings": ["F1"], "deadline": "T1", "letter": "L1"}
        ),
    )
    assert bad["problems"] == ["a stamp_request goes to the doctor; L1 is addressed to office"]

    _, ok = desk.call(
        "create_action",
        json.dumps(
            action
            | {
                "kind": "claim_correction",
                "findings": "['F1', 'F2']",  # as the model sometimes writes it
                "deadline": "T1",
                "letter": "L1",
            }
        ),
    )
    assert ok == {"ok": True, "action": "X1", "due": "Fr 06.11.2026", "money_on_it": "285,60 €"}
    (filed,) = desk.actions
    assert (filed.status, filed.due_date, filed.claim_id) == (
        "open",
        dt.date(2026, 11, 6),
        "C-p01-2026-10-sgbv",
    )
    assert filed.amount_cents == 28560  # both findings are on the same 34 lines: counted once
    assert desk.uncovered() == []
    _, again = desk.call(
        "create_action",
        json.dumps(
            action
            | {"kind": "claim_correction", "findings": ["F1"], "deadline": "T1", "letter": "L1"}
        ),
    )
    assert again["problems"] == ["L1 is already filed with X1: draft a new one"]
    _, broken = desk.call("create_action", "{not json")
    assert broken["problems"] == ["arguments are not valid JSON"]


def test_money_on_an_action_is_what_its_findings_put_at_risk(stored_month):  # noqa: F811
    month = evaluate_month(stored_month, records(), "2026-10")
    b = brief(month, "p06", month.findings, AS_OF)
    budget = next(f for f in b.findings if f.rule_id == "XI-36-BUDGET")
    lines = sum(
        ln.amount_cents for c in b.claims for ln in c.lines if ln.id in budget.claim_line_ids
    )
    assert budget.amount_at_risk_cents < lines  # the excess over the budget, not those lines
    assert amount_of(b, [budget]) == budget.amount_at_risk_cents


ALBERS_TURNS = [
    (
        "Reading the findings.",
        [("get_claim_findings", {}), ("compute_deadline", {"kind": "billing_run"})],
    ),
    (
        "",
        [
            (
                "draft_letter",
                {
                    "recipient": "office",
                    "subject": "Rechnung Oktober 2026 kürzen",
                    "body": "Bitte die 34 Leistungen vom 15.10.2026 bis 31.10.2026 (285,60 €) "
                    "vor dem Abrechnungslauf aus der Rechnung nehmen.",
                },
            )
        ],
    ),
    (
        "",
        [
            (
                "create_action",
                {
                    "kind": "claim_correction",
                    "title": "Take 15-31 Oct off the bill",
                    "why": "Days without a Verordnung are rejected.",
                    "findings": ["F1"],
                    "deadline": "T1",
                    "letter": "L1",
                },
            )
        ],
    ),
    ("Done.", []),
    ("F2 has the same cause as F1, so the correction covers it.", []),
]


async def test_the_loop_files_actions_and_asks_once_about_uncovered_findings(
    stored_month,  # noqa: F811
    make_settings,
):
    month = evaluate_month(stored_month, records(), "2026-10")
    script = Scripted(ALBERS_TURNS)
    client = MetaModelClient(make_settings(), transport=script)

    result = await draft(client, brief(month, "p01", month.findings, AS_OF))

    assert [s["kind"] for s in result.steps] == [
        "say",
        "call",
        "call",
        "call",
        "call",
        "say",
        "nudge",
        "say",
    ]
    assert "No action covers F2 yet" in result.steps[6]["text"]
    assert result.note == "F2 has the same cause as F1, so the correction covers it."
    (action,) = result.actions
    assert action.finding_ids[0].startswith("HKP-FOLGE-WINDOW")
    first, last = script.calls[0], script.calls[-1]
    assert first["tool_choice"] == "auto" and len(first["tools"]) == 6
    assert last["messages"][-1]["role"] == "user"  # the nudge
    assert all(m["role"] != "tool" or "doc-" not in m["content"] for m in last["messages"])


async def test_runs_are_stored_once_per_state_and_served_with_their_trace(
    stored_month,  # noqa: F811
    make_settings,
    tmp_path,
):
    month = evaluate_month(stored_month, records(), "2026-10")
    client = MetaModelClient(make_settings(today=AS_OF), transport=Scripted(ALBERS_TURNS))
    pending = due(month, stored_month, AS_OF)
    assert "p01" in {b.patient_id for b in pending} and "p05" not in {b.patient_id for b in pending}

    done = await fix_month(client, stored_month, records(), patient_ids=["p01"], as_of=AS_OF)

    assert (done.patients, done.actions, done.failed) == (1, 1, 0)
    assert "p01" not in {b.patient_id for b in due(month, stored_month, AS_OF)}
    run = latest_fixes(stored_month)["p01"]
    assert run.refs["F1"].startswith("HKP-FOLGE-WINDOW") and run.as_of == AS_OF

    world = build_world(stored_month, records(), tmp_path / "blobs", AS_OF)
    (action,) = world.actions
    assert action.run_id == run.id and world.fix_runs[run.id].actions == [action.id]
    assert world.fixer.state == "pending" and "Albers, Erika" not in world.fixer.due
    deps = Deps(client, stored_month, BlobStore(tmp_path / "blobs"), records())
    app.dependency_overrides[current_world] = lambda: world
    app.dependency_overrides[run_deps] = lambda: deps
    try:
        api = TestClient(app)
        listed = api.get("/api/months/2026-10/actions").json()
        assert [a["id"] for a in listed["actions"]] == [action.id]
        assert listed["fixer"]["state"] == "pending"
        assert listed["provider"]["address"] == ["Hengersberger Str. 18", "94469 Deggendorf"]
        trace = api.get(f"/api/fix-runs/{run.id}").json()
        assert [s["tool"] for s in trace["steps"] if s["kind"] == "call"][-1] == "create_action"
        assert api.get("/api/fix-runs/fix-nope").status_code == 404
        assert api.post("/api/months/2026-09/actions/draft").status_code == 404
    finally:
        app.dependency_overrides.clear()

"""Phase 7: training scenarios, AI caller (Claude – here a stub that mimics the SDK), instructor
mode, rule-based fallback, evaluation, speech endpoint, safety rules.

No test talks to the real Claude API: ``ai_settings.make_client`` is replaced by ``FakeAnthropic``.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest
from sqlalchemy import select, text

from app.models import AuditLog, TrainingMessage
from app.training import ai_settings
from app.training.brains import (
    ANSWERED,
    FALLBACK_BETA,
    PAUSE,
    ItemJudgement,
    RuleBrain,
    TranscriptJudgement,
    Turn,
    split_sentences,
    to_messages,
)
from app.training.evaluation import location_matches, score
from tests.test_operations import setup  # noqa: F401 – shared fixture (control centre, vehicles, users)

API_KEY = "sk-ant-test-0123456789abcdefXYZ"
DEFAULT_REPLY = ["Hier ist ", "die Demostraße 1. ", "Bitte ", "kommen Sie schnell!"]


# ----------------------------------------------------------------------------- fake SDK
class FakeStream:
    def __init__(self, owner: FakeAnthropic, kwargs: dict[str, Any]) -> None:
        self.owner, self.kwargs = owner, kwargs

    async def __aenter__(self) -> FakeStream:
        self.owner.calls.append(self.kwargs)
        if self.owner.error is not None:
            raise self.owner.error
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    @property
    async def text_stream(self):  # type: ignore[no-untyped-def]
        chunks = self.owner.replies.pop(0) if self.owner.replies else DEFAULT_REPLY
        for chunk in chunks:
            if self.owner.delay:
                await asyncio.sleep(self.owner.delay)
            yield chunk

    async def get_final_message(self) -> Any:
        iterations = [SimpleNamespace(type="fallback_message")] if self.owner.fallback else []
        return SimpleNamespace(
            stop_reason=self.owner.stop_reason,
            model="claude-opus-4-8" if self.owner.fallback else self.kwargs["model"],
            content=[],
            usage=SimpleNamespace(iterations=iterations, cache_read_input_tokens=0),
        )


class FakeMessages:
    def __init__(self, owner: FakeAnthropic) -> None:
        self.owner = owner

    def stream(self, **kwargs: Any) -> FakeStream:
        return FakeStream(self.owner, kwargs)

    async def parse(self, **kwargs: Any) -> Any:
        self.owner.parse_calls.append(kwargs)
        keys = [
            line.split(":")[0].strip("- ")
            for line in kwargs["messages"][0]["content"].splitlines()
            if line.startswith("- ")
        ]
        judgement = TranscriptJudgement(
            items=[ItemJudgement(key=k, fulfilled=k != "ask_name", evidence="„Wo genau?“") for k in keys],
            strengths=["Ruhige Gesprächsführung"],
            improvements=["Früher nach der Rückrufnummer fragen"],
            summary="Gutes Gespräch.",
        )
        return SimpleNamespace(stop_reason="end_turn", parsed_output=judgement)

    async def create(self, **kwargs: Any) -> Any:
        self.owner.create_calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            model=kwargs["model"],
            content=[SimpleNamespace(type="text", text="Verbindung steht.")],
        )


class FakeAnthropic:
    def __init__(self) -> None:
        self.beta = SimpleNamespace(messages=FakeMessages(self))
        self.calls: list[dict[str, Any]] = []
        self.parse_calls: list[dict[str, Any]] = []
        self.create_calls: list[dict[str, Any]] = []
        self.replies: list[list[str]] = []
        self.error: Exception | None = None
        self.stop_reason = "end_turn"
        self.fallback = False
        self.delay = 0.0
        self.made_with: list[tuple[str, str]] = []

    async def close(self) -> None:
        pass


@pytest.fixture
def fake(app, monkeypatch):
    client = FakeAnthropic()

    def make(api_key: str, base_url: str, timeout: float) -> FakeAnthropic:
        client.made_with.append((api_key, base_url))
        return client

    monkeypatch.setattr(ai_settings, "make_client", make)
    app.state.training._clients.clear()
    monkeypatch.setattr(app.state.training, "stt", None)
    return client


@pytest.fixture
def published(app, monkeypatch):
    messages = []
    original = app.state.bus.publish

    async def record(msg):
        messages.append(msg)
        await original(msg)

    monkeypatch.setattr(app.state.bus, "publish", record)
    return messages


@pytest.fixture
async def ctx(client, setup, app, fake):  # noqa: F811
    c = dict(setup)
    yield c
    await app.state.training.drain()


SCENARIO = {
    "title": "Zimmerbrand Demostraße",
    "description": "Brand in einer Wohnung, Anruferin im Treppenhaus",
    "difficulty": "medium",
    "persona": {
        "name": "Erika Muster",
        "age": 64,
        "role": "Nachbarin",
        "emotional_state": "aufgeregt",
        "phone": "0151 2345678",
    },
    "facts": {
        "address": "Demostraße 1, Demostadt",
        "lat": 53.501,
        "lon": 10.481,
        "location_hint": "2. Stock links",
        "situation": "Aus der Nachbarwohnung kommt dichter Rauch.",
        "persons": "Der Nachbar ist vermutlich noch in der Wohnung.",
        "injuries": "Unbekannt.",
        "hazards": "Rauch im Treppenhaus.",
        "details": ["Die Wohnungstür ist verschlossen."],
        "unknown": ["Ob der Nachbar ansprechbar ist."],
    },
    "opening_line": "Hallo? Hier brennt es, bei meinem Nachbarn kommt Rauch raus!",
}


async def _scenario(client, c, **extra):
    body = {**SCENARIO, "control_center_id": c["cc"]["id"], "keyword_id": c["keywords"]["B2"]["id"], **extra}
    r = await client.post("/training/scenarios", headers=c["admin"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _start(client, c, scenario, headers=None, **extra):
    r = await client.post(
        "/training/sessions",
        headers=headers or c["dispo"],
        json={"scenario_id": scenario["id"], "control_center_id": c["cc"]["id"], **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _session(client, c, session, headers=None):
    r = await client.get(f"/training/sessions/{session['id']}", headers=headers or c["dispo"])
    assert r.status_code == 200, r.text
    return r.json()


async def _answer(client, c, session, headers=None):
    r = await client.post(f"/calls/{session['call_id']}/answer", headers=headers or c["dispo"], json={})
    return r


async def _say(client, c, session, words, app):
    r = await client.post(
        f"/training/sessions/{session['id']}/messages", headers=c["dispo"], json={"text": words}
    )
    assert r.status_code == 202, r.text
    await app.state.training.drain()
    return r.json()


async def _enable_ai(client, c, **extra):
    current = (await client.get("/training/ai-settings", headers=c["admin"])).json()
    r = await client.put(
        "/training/ai-settings",
        headers=c["admin"],
        json={"enabled": True, "api_key": API_KEY, "expected_version": current["version"], **extra},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _no_invalid_system_placement(messages: list[dict[str, Any]]) -> None:
    """API rule: a system message follows a user turn and is last or followed by assistant."""
    assert messages[0]["role"] == "user"
    for i, m in enumerate(messages):
        if m["role"] == "system":
            assert messages[i - 1]["role"] in ("user", "system")
            assert i == len(messages) - 1 or messages[i + 1]["role"] in ("assistant", "system")
        if i and m["role"] in ("user", "assistant"):
            assert messages[i - 1]["role"] != m["role"]  # strictly alternating conversation


# ------------------------------------------------------------------------- pure functions
def test_transcript_rendering_rules():
    opening = Turn("caller", "Hallo? Hilfe!")
    assert to_messages([opening]) == [
        {"role": "user", "content": ANSWERED},
        {"role": "assistant", "content": "Hallo? Hilfe!"},
        {"role": "user", "content": PAUSE},
    ]
    turns = [
        opening,
        Turn("dispatcher", "Wo sind Sie?"),
        Turn("dispatcher", "Hallo?"),
        Turn("instructor", "Sei verwirrt"),
    ]
    rendered = to_messages(turns)
    assert rendered[-2:] == [
        {"role": "user", "content": "Wo sind Sie?\nHallo?"},
        {"role": "system", "content": "Regie: Sei verwirrt"},
    ]
    _no_invalid_system_placement(rendered)
    # instruction while the caller spoke last (immediate reply): synthetic pause before it
    turns = [
        opening,
        Turn("instructor", "Werde panisch"),
        Turn("caller", "Oh Gott!"),
        Turn("dispatcher", "Ruhig"),
    ]
    rendered = to_messages(turns)
    assert [m["role"] for m in rendered] == ["user", "assistant", "user", "system", "assistant", "user"]
    _no_invalid_system_placement(rendered)
    # rendering is a pure function of the transcript: earlier requests are a prefix of later ones
    assert to_messages(turns[:2]) == rendered[:4]


def test_sentence_splitting_and_rule_brain():
    assert split_sentences("Hallo. Ich bin hier") == (["Hallo."], "Ich bin hier")
    assert split_sentences("Wo? Da! Weiter") == (["Wo?", "Da!"], "Weiter")
    assert split_sentences("Noch nicht fertig") == ([], "Noch nicht fertig")
    snapshot = {"persona": SCENARIO["persona"], "facts": SCENARIO["facts"]}
    assert "Demostraße 1" in RuleBrain.answer(snapshot, "Wo genau ist das?")
    assert "0151 2345678" in RuleBrain.answer(snapshot, "Wie ist Ihre Rückrufnummer?")
    assert "Nachbar" in RuleBrain.answer(snapshot, "Sind noch Personen in der Wohnung?")
    assert "weiß ich nicht" in RuleBrain.answer(snapshot, "Welche Farbe hat das Auto?")


def test_location_and_score():
    facts = SCENARIO["facts"]
    assert location_matches(facts, "irgendwas", 53.5012, 10.4812)[0]  # ≈ 25 m
    assert location_matches(facts, "Demostr. 1, Demostadt", 53.6, 10.6)[0]  # address matches
    assert not location_matches(facts, "Bahnhofstraße 3", 53.6, 10.6)[0]
    assert not location_matches(facts, None, None, None)[0]
    items = [
        {"required": True, "fulfilled": True},
        {"required": True, "fulfilled": False},
        {"required": False, "fulfilled": False},
    ]
    assert score(items) == 50


# ------------------------------------------------------------------------ rule-based flow
async def test_exercise_without_ai_end_to_end(client, ctx, app, db):
    c = ctx
    scenario = await _scenario(client, c)
    session = await _start(client, c, scenario)
    assert session["status"] == "ringing" and session["caller_mode"] == "rules" and session["model"] is None
    assert session["scenario"] is None  # the trainee does not see the solution during the exercise

    calls = (
        await client.get("/calls", headers=c["dispo"], params={"control_center_id": c["cc"]["id"]})
    ).json()
    call = next(x for x in calls if x["id"] == session["call_id"])
    assert call["source"] == "training" and call["status"] == "ringing"
    assert call["caller_phone"] == "0151 2345678" and call["caller_latitude"] is None  # medium: no AML

    others = (
        await client.get("/calls", headers=c["dispo2"], params={"control_center_id": c["cc"]["id"]})
    ).json()
    assert all(x["id"] != session["call_id"] for x in others)  # no ringing for colleagues
    r = await _answer(client, c, session, c["dispo2"])
    assert r.status_code == 409 and "Übungsanruf" in r.json()["error"]["message"]
    assert (await _answer(client, c, session)).status_code == 200
    detail = await _session(client, c, session)
    assert detail["status"] == "active"
    assert [(m["role"], m["source"]) for m in detail["messages"]] == [("caller", "opening")]

    await _say(client, c, session, "Notruf Feuerwehr. Wo genau ist der Notfallort?", app)
    detail = await _session(client, c, session)
    reply = detail["messages"][-1]
    assert reply["role"] == "caller" and reply["source"] == "rules" and "Demostraße 1" in reply["text"]

    incident = (
        await client.post(
            "/incidents",
            headers=c["dispo"],
            json={
                "control_center_id": c["cc"]["id"],
                "call_id": session["call_id"],
                "keyword_id": c["keywords"]["B2"]["id"],
                "address": "Demostraße 1, Demostadt",
                "latitude": 53.5011,
                "longitude": 10.4811,
            },
        )
    ).json()
    alarm = await client.post(
        f"/incidents/{incident['id']}/alarms",
        headers={**c["dispo"], "Idempotency-Key": uuid.uuid4().hex},
        json={"vehicle_ids": [c["vehicles"]["hlf"]["id"]], "confirmed": True},
    )
    assert alarm.status_code == 201, alarm.text
    await _say(client, c, session, "Unter welcher Nummer kann ich Sie zurückrufen?", app)

    r = await client.post(f"/training/sessions/{session['id']}/end", headers=c["dispo"])
    assert r.status_code == 200 and r.json()["status"] in ("ended", "evaluated")
    await app.state.training.drain()  # automatic evaluation
    detail = await _session(client, c, session)
    assert detail["status"] == "evaluated" and detail["call_status"] == "ended"
    assert detail["scenario"]["facts"]["address"] == "Demostraße 1, Demostadt"  # debrief after the end
    evaluation = detail["evaluation"]
    assert evaluation["method"] == "rules" and evaluation["model"] is None
    items = {i["key"]: i for i in evaluation["checklist"]}
    for key in (
        "incident_created",
        "keyword_correct",
        "location_correct",
        "alarm_triggered",
        "ask_location",
        "ask_callback",
    ):
        assert items[key]["fulfilled"], (key, items[key])
    assert not items["ask_what"]["fulfilled"] and not items["ask_persons"]["fulfilled"]
    assert evaluation["score"] == 75  # 6 of 8 required items
    metrics = evaluation["metrics"]
    assert metrics["dispatcher_turns"] == 2 and metrics["caller_turns"] == 3
    assert metrics["incident_seconds"] is not None and metrics["alarm_seconds"] is not None
    assert "regelbasiert" in evaluation["feedback"]["summary"].lower()

    async with db.sessionmaker() as s:
        actions = set(
            (await s.scalars(select(AuditLog.action).where(AuditLog.entity_type == "training_session"))).all()
        )
    assert {"start", "evaluate"} <= actions


# ---------------------------------------------------------------------------- Claude flow
async def test_ai_settings_key_is_encrypted_and_admin_only(client, ctx, db):
    c = ctx
    assert (await client.get("/training/ai-settings", headers=c["dispo"])).status_code == 403
    initial = (await client.get("/training/ai-settings", headers=c["admin"])).json()
    assert initial["enabled"] is False and initial["has_key"] is False  # off by default
    assert initial["model"] == "claude-opus-5-5" and initial["base_url"] == "https://api.anthropic.com"
    saved = await _enable_ai(client, c)
    assert saved["enabled"] and saved["has_key"] and saved["key_hint"] == "••••fXYZ"
    assert API_KEY not in json.dumps(saved)
    async with db.engine.connect() as conn:
        raw = (
            await conn.execute(text("SELECT value::text FROM system_settings WHERE key = 'ai_settings'"))
        ).scalar()
        audit = (await conn.execute(text("SELECT string_agg(summary, ' ') FROM audit_log"))).scalar()
    assert API_KEY not in raw and "key_encrypted" in raw
    assert API_KEY not in audit
    r = await client.put(
        "/training/ai-settings",
        headers=c["admin"],
        json={"model": "Bad Model!", "expected_version": saved["version"]},
    )
    assert r.status_code == 422
    cleared = await client.put(
        "/training/ai-settings",
        headers=c["admin"],
        json={"clear_key": True, "expected_version": saved["version"]},
    )
    assert cleared.json()["has_key"] is False


async def test_claude_caller_streams_sentences(client, ctx, app, fake, published):
    c = ctx
    await _enable_ai(client, c)
    scenario = await _scenario(client, c)
    session = await _start(client, c, scenario)
    assert session["caller_mode"] == "claude" and session["model"] == "claude-opus-5-5"
    assert (await _answer(client, c, session)).status_code == 200
    assert fake.calls == []  # the opening line needs no AI request

    await _say(client, c, session, "Was ist passiert?", app)
    assert fake.made_with == [(API_KEY, "https://api.anthropic.com")]  # explicit base URL, decrypted key
    request = fake.calls[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["output_config"] == {"effort": "low"}
    assert request["betas"] == [FALLBACK_BETA] and request["fallbacks"] == "default"
    assert request["cache_control"] == {"type": "ephemeral"}
    assert "thinking" not in request and "temperature" not in request  # adaptive thinking by default
    system = request["system"][0]["text"]
    assert "Erika Muster" in system and "Demostraße 1" in system and "AUSBILDUNGS-SIMULATION" in system
    assert request["messages"] == [
        {"role": "user", "content": ANSWERED},
        {"role": "assistant", "content": SCENARIO["opening_line"]},
        {"role": "user", "content": "Was ist passiert?"},
    ]
    chunks = [
        m.data["text"]
        for m in published
        if m.topic == "training.caller_chunk" and m.channels == [f"user:{session['trainee_id']}"]
    ]
    assert chunks == ["Hier ist die Demostraße 1.", "Bitte kommen Sie schnell!"]  # sentence by sentence
    instructor_copies = [m for m in published if m.topic == "training.caller_chunk" and m.required_permission]
    assert {m.required_permission for m in instructor_copies} == {"training.instructor"}

    reply = (await _session(client, c, session))["messages"][-1]
    assert (
        reply["source"] == "claude"
        and reply["text"] == "Hier ist die Demostraße 1. Bitte kommen Sie schnell!"
    )
    assert isinstance(reply["latency_ms"], int) and reply["latency_ms"] >= 0

    # second turn: the history is sent again unchanged (cache prefix) plus the new question
    await _say(client, c, session, "Ist noch jemand in der Wohnung?", app)
    second = fake.calls[1]["messages"]
    assert second[: len(request["messages"])] == request["messages"]
    assert second[-2:] == [
        {"role": "assistant", "content": reply["text"]},
        {"role": "user", "content": "Ist noch jemand in der Wohnung?"},
    ]


async def test_instructor_interventions_reach_only_the_caller(client, ctx, app, fake, published):
    c = ctx
    await _enable_ai(client, c)
    session = await _start(client, c, await _scenario(client, c))
    await _answer(client, c, session)

    assert (
        await client.post(
            f"/training/sessions/{session['id']}/instructions", headers=c["dispo"], json={"text": "x"}
        )
    ).status_code == 403
    r = await client.post(
        f"/training/sessions/{session['id']}/instructions",
        headers=c["admin"],
        json={"text": "Werde zunehmend panisch."},
    )
    assert r.status_code == 200 and r.json()["pending_instructions"][0]["text"] == "Werde zunehmend panisch."
    pending_events = [m for m in published if m.topic == "training.pending_changed"]
    assert pending_events and all(m.required_permission == "training.instructor" for m in pending_events)
    trainee_view = await _session(client, c, session)
    assert trainee_view["pending_instructions"] is None
    assert fake.calls == []  # not immediate: waits for the next reply

    await _say(client, c, session, "Hallo, hören Sie mich?", app)
    sent = fake.calls[-1]["messages"]
    assert sent[-2:] == [
        {"role": "user", "content": "Hallo, hören Sie mich?"},
        {"role": "system", "content": "Regie: Werde zunehmend panisch."},
    ]
    _no_invalid_system_placement(sent)

    # immediate: the caller reacts on its own, after a synthetic pause
    await client.post(
        f"/training/sessions/{session['id']}/instructions",
        headers=c["admin"],
        json={"text": "Sag, dass der Rauch dichter wird.", "immediate": True},
    )
    await app.state.training.drain()
    sent = fake.calls[-1]["messages"]
    assert sent[-3:-1] == [
        {"role": "assistant", "content": "Hier ist die Demostraße 1. Bitte kommen Sie schnell!"},
        {"role": "user", "content": PAUSE},
    ]
    assert sent[-1] == {"role": "system", "content": "Regie: Sag, dass der Rauch dichter wird."}
    _no_invalid_system_placement(sent)

    note = await client.post(
        f"/training/sessions/{session['id']}/notes", headers=c["admin"], json={"text": "Gute Ruhe"}
    )
    assert note.status_code == 200
    instructor_view = await _session(client, c, session, c["admin"])
    trainee_view = await _session(client, c, session)
    assert [m["source"] for m in instructor_view["messages"] if m["role"] == "instructor"] == [
        "instructor",
        "instructor",
        "note",
    ]
    assert all(m["role"] != "instructor" for m in trainee_view["messages"])
    assert trainee_view["scenario"] is None and instructor_view["scenario"]["facts"]["address"]
    trainee_events = [
        m
        for m in published
        if m.topic == "training.message" and m.channels == [f"user:{session['trainee_id']}"]
    ]
    assert all(m.data["role"] != "instructor" for m in trainee_events)


async def test_ai_failures_fall_back_to_rules_visibly(client, ctx, app, fake, published):
    c = ctx
    await _enable_ai(client, c)
    session = await _start(client, c, await _scenario(client, c))
    await _answer(client, c, session)

    fake.error = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    await _say(client, c, session, "Wo genau sind Sie?", app)
    messages = (await _session(client, c, session))["messages"]
    assert messages[-1]["role"] == "caller" and messages[-1]["source"] == "rules"
    assert "Demostraße 1" in messages[-1]["text"]
    notes = [m["text"] for m in messages if m["role"] == "system"]
    assert any("nicht erreichbar" in n and "regelbasiert" in n for n in notes)

    fake.error, fake.stop_reason = None, "refusal"  # whole fallback chain declined
    await _say(client, c, session, "Was ist passiert?", app)
    messages = (await _session(client, c, session))["messages"]
    assert messages[-1]["source"] == "rules"
    assert any("abgelehnt" in m["text"] for m in messages if m["role"] == "system")
    assert any(m.data.get("retract") for m in published if m.topic == "training.caller_chunk")

    fake.stop_reason, fake.fallback = "end_turn", True  # served by the fallback model
    await _say(client, c, session, "Sind Sie in Sicherheit?", app)
    messages = (await _session(client, c, session))["messages"]
    assert messages[-1]["source"] == "claude"
    assert any("Ausweichmodell claude-opus-4-8" in m["text"] for m in messages if m["role"] == "system")


async def test_message_during_reply_gets_its_own_answer(client, ctx, app, fake, published):
    c = ctx
    await _enable_ai(client, c)
    session = await _start(client, c, await _scenario(client, c))
    await _answer(client, c, session)
    fake.delay = 0.05
    first = await client.post(
        f"/training/sessions/{session['id']}/messages", headers=c["dispo"], json={"text": "Was brennt?"}
    )
    assert first.status_code == 202
    for _ in range(100):  # wait until the caller has started talking
        if any(m.topic == "training.caller_chunk" for m in published):
            break
        await asyncio.sleep(0.02)
    second = await client.post(
        f"/training/sessions/{session['id']}/messages",
        headers=c["dispo"],
        json={"text": "Hallo? Antworten Sie!"},
    )
    assert second.status_code == 202
    await app.state.training.drain()
    roles = [m["role"] for m in (await _session(client, c, session))["messages"] if m["role"] != "system"]
    assert roles == ["caller", "dispatcher", "caller", "dispatcher", "caller"]
    assert fake.calls[-1]["messages"][-1] == {"role": "user", "content": "Hallo? Antworten Sie!"}
    assert len(fake.calls) == 2

    # two schedules for the same message (e.g. two workers) still produce one reply
    await client.post(
        f"/training/sessions/{session['id']}/messages", headers=c["dispo"], json={"text": "Gut."}
    )
    app.state.training.schedule_reply(uuid.UUID(session["id"]))
    app.state.training.schedule_reply(uuid.UUID(session["id"]))
    await app.state.training.drain()
    assert len(fake.calls) == 3


async def test_claude_evaluation_uses_structured_output(client, ctx, app, fake):
    c = ctx
    await _enable_ai(client, c, evaluation_effort="high")
    session = await _start(
        client,
        c,
        await _scenario(
            client,
            c,
            checklist=[
                {"key": "ask_location", "label": "Einsatzort erfragt", "required": True, "hints": ["wo"]},
                {"key": "ask_name", "label": "Name erfragt", "required": True, "hints": ["name"]},
            ],
        ),
    )
    await _answer(client, c, session)
    await _say(client, c, session, "Wo genau?", app)
    await client.post(f"/training/sessions/{session['id']}/end", headers=c["dispo"])
    await app.state.training.drain()
    assert len(fake.parse_calls) == 1
    call = fake.parse_calls[0]
    assert call["output_format"] is TranscriptJudgement
    assert call["output_config"] == {"effort": "high"} and call["fallbacks"] == "default"
    assert "Wo genau?" in call["messages"][0]["content"]
    evaluation = (await _session(client, c, session))["evaluation"]
    assert evaluation["method"] == "claude" and evaluation["model"] == "claude-opus-5-5"
    items = {i["key"]: i for i in evaluation["checklist"]}
    assert items["ask_location"]["fulfilled"] and not items["ask_name"]["fulfilled"]
    assert not items["incident_created"]["fulfilled"]  # no incident was created
    assert evaluation["feedback"]["strengths"] == ["Ruhige Gesprächsführung"]

    # re-evaluation by an instructor replaces the result; trainees may not re-run
    assert (
        await client.post(f"/training/sessions/{session['id']}/evaluate", headers=c["dispo"])
    ).status_code == 403
    again = await client.post(f"/training/sessions/{session['id']}/evaluate", headers=c["admin"])
    assert again.status_code == 200 and len(fake.parse_calls) == 2


# ------------------------------------------------------------------------- safety, rights
async def test_permissions_and_visibility(client, ctx, app):
    c = ctx
    assert (
        await client.post("/training/scenarios", headers=c["dispo"], json={**SCENARIO})
    ).status_code == 403
    scenario = await _scenario(client, c)
    listed = (await client.get("/training/scenarios", headers=c["dispo"])).json()
    assert listed[0]["title"] == SCENARIO["title"] and listed[0]["facts"] == {}  # no solution for trainees
    assert (await client.get(f"/training/scenarios/{scenario['id']}", headers=c["dispo"])).status_code == 403

    r = await client.post(
        "/training/sessions",
        headers=c["dispo"],
        json={
            "scenario_id": scenario["id"],
            "control_center_id": c["cc"]["id"],
            "trainee_id": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 403
    users = {u["username"]: u for u in (await client.get("/users", headers=c["admin"])).json()["items"]}
    session = await _start(client, c, scenario, headers=c["admin"], trainee_id=users["dispo"]["id"])
    assert session["trainee_name"] == "Test Disponent" and session["instructor_name"]
    r = await client.post(
        "/training/sessions",
        headers=c["dispo"],
        json={"scenario_id": scenario["id"], "control_center_id": c["cc"]["id"]},
    )
    assert r.status_code == 409 and "bereits eine laufende Übung" in r.json()["error"]["message"]
    assert (await client.get(f"/training/sessions/{session['id']}", headers=c["dispo2"])).status_code == 403
    assert (await client.get("/training/sessions", headers=c["dispo2"])).json() == []
    assert (
        len((await client.get("/training/sessions", headers=c["admin"], params={"status": "open"})).json())
        == 1
    )

    await _answer(client, c, session)
    r = await client.post(
        f"/training/sessions/{session['id']}/messages", headers=c["admin"], json={"text": "Hallo"}
    )
    assert r.status_code == 403  # only the trainee talks to the caller
    hold = await client.post(f"/calls/{session['call_id']}/hold", headers=c["dispo"], json={})
    assert hold.status_code == 200
    r = await client.post(
        f"/training/sessions/{session['id']}/messages", headers=c["dispo"], json={"text": "Hallo"}
    )
    assert r.status_code == 409  # on hold: the caller cannot hear
    assert (
        await client.post(f"/calls/{session['call_id']}/resume", headers=c["dispo2"], json={})
    ).status_code == 409

    # the instructor can end someone else's exercise
    r = await client.post(f"/training/sessions/{session['id']}/end", headers=c["admin"])
    assert r.status_code == 200 and r.json()["status"] in ("ended", "evaluated")


async def test_exercises_only_in_simulation_mode(client, ctx, app):
    from tests.test_alarming import _set_mode

    c = ctx
    scenario = await _scenario(client, c)
    ringing = await _start(client, c, scenario)
    await _set_mode(client, c, "real")
    detail = await _session(client, c, ringing)
    assert detail["status"] == "cancelled" and detail["call_status"] == "ended"
    assert "Echtbetrieb" in detail["messages"][-1]["text"]
    r = await client.post(
        "/training/sessions",
        headers=c["dispo"],
        json={"scenario_id": scenario["id"], "control_center_id": c["cc"]["id"]},
    )
    assert r.status_code == 409 and "Simulationsbetrieb" in r.json()["error"]["message"]
    await _set_mode(client, c, "simulation")


async def test_unanswered_training_call_cancels_the_session(client, ctx, app):
    c = ctx
    session = await _start(client, c, await _scenario(client, c))
    r = await client.post(f"/training/sessions/{session['id']}/end", headers=c["dispo"])
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    await app.state.training.drain()
    assert (await _session(client, c, session))["evaluation"] is None


async def test_speech_endpoint(client, ctx, app, monkeypatch):
    c = ctx
    session = await _start(client, c, await _scenario(client, c))
    await _answer(client, c, session)
    files = {"audio": ("aufnahme.webm", b"\x1aE\xdf\xa3fake", "audio/webm")}
    r = await client.post(f"/training/sessions/{session['id']}/speech", headers=c["dispo"], files=files)
    assert r.status_code == 501 and "nicht installiert" in r.json()["error"]["message"]

    class FakeStt:
        name = "fake"

        async def transcribe(self, audio: bytes) -> str:
            assert audio.startswith(b"\x1aE")
            return "Wo brennt es genau?"

    monkeypatch.setattr(app.state.training, "stt", FakeStt())
    r = await client.post(f"/training/sessions/{session['id']}/speech", headers=c["dispo"], files=files)
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "Wo brennt es genau?" and r.json()["message"]["source"] == "voice"
    await app.state.training.drain()
    messages = (await _session(client, c, session))["messages"]
    assert messages[-1]["role"] == "caller" and "Demostraße 1" in messages[-1]["text"]
    too_big = {"audio": ("a.webm", b"0" * (5 * 1024 * 1024 + 1), "audio/webm")}
    assert (
        await client.post(f"/training/sessions/{session['id']}/speech", headers=c["dispo"], files=too_big)
    ).status_code == 422


async def test_ai_connection_test_endpoint(client, ctx, fake):
    c = ctx
    r = await client.post("/training/ai-settings/test", headers=c["admin"])
    assert r.status_code == 200 and r.json()["ok"] is False  # no key yet
    await _enable_ai(client, c)
    r = await client.post("/training/ai-settings/test", headers=c["admin"])
    assert r.json() == {
        "ok": True,
        "model": "claude-opus-5-5",
        "latency_ms": r.json()["latency_ms"],
        "message": "Verbindung steht.",
    }
    assert fake.create_calls[0]["output_config"] == {"effort": "low"}
    assert (await client.post("/training/ai-settings/test", headers=c["dispo"])).status_code == 403


async def test_messages_are_stored_with_roles(ctx, client, app, db):
    c = ctx
    session = await _start(client, c, await _scenario(client, c))
    await _answer(client, c, session)
    await _say(client, c, session, "Wo?", app)
    async with db.sessionmaker() as s:
        rows = (
            await s.scalars(select(TrainingMessage).order_by(TrainingMessage.ts, TrainingMessage.id))
        ).all()
    assert [(m.role, m.source) for m in rows] == [
        ("caller", "opening"),
        ("dispatcher", "text"),
        ("caller", "rules"),
    ]
    assert rows[1].author_name.startswith("Test Disponent")


async def test_server_overhead_of_a_reply_is_small(client, ctx, app, fake, published):
    """M7 budget: 2.5 s from the dispatcher's message to the caller's first sentence. Measured here
    is only the server's own share (store, schedule, lock, prompt, publish) with an instant stub;
    the model's time to first token comes on top and needs a real API key to measure."""
    import time

    c = ctx
    await _enable_ai(client, c)
    session = await _start(client, c, await _scenario(client, c))
    await _answer(client, c, session)
    durations = []
    for i in range(5):
        published.clear()
        started = time.perf_counter()
        r = await client.post(
            f"/training/sessions/{session['id']}/messages", headers=c["dispo"], json={"text": f"Frage {i}?"}
        )
        assert r.status_code == 202
        for _ in range(5000):  # poll the recorded bus messages
            if any(m.topic == "training.caller_chunk" for m in published):
                break
            await asyncio.sleep(0.001)
        durations.append(time.perf_counter() - started)
        await app.state.training.drain()
    assert max(durations) < 0.5, durations
    stored = [m for m in (await _session(client, c, session))["messages"] if m["role"] == "caller"][1:]
    assert all(m["latency_ms"] < 500 for m in stored)


async def test_trainees_list_for_instructors(client, ctx):
    c = ctx
    r = await client.get(
        "/training/trainees", headers=c["admin"], params={"control_center_id": c["cc"]["id"]}
    )
    assert r.status_code == 200
    names = {u["username"] for u in r.json()}
    assert {"dispo", "dispo2", "annahme", "admin"} <= names
    denied = await client.get(
        "/training/trainees", headers=c["dispo"], params={"control_center_id": c["cc"]["id"]}
    )
    assert denied.status_code == 403


async def test_demo_scenarios_are_valid_and_seeded_once(ctx, db, client):
    from app.demo_data import TRAINING_SCENARIOS, _seed_training
    from app.models import ControlCenter
    from app.realtime.bus import InMemoryEventBus
    from app.schemas.training import ScenarioCreate
    from app.services.uow import UnitOfWork

    assert len(TRAINING_SCENARIOS) == 4
    for raw in TRAINING_SCENARIOS:
        data = {k: v for k, v in raw.items() if k != "keyword"}
        ScenarioCreate.model_validate(data)  # strict schema: no unknown fields, valid checklist keys
        assert raw["persona"]["phone"].startswith("0000")  # fictional numbers only
    async with db.sessionmaker() as s:
        cc = await s.get(ControlCenter, uuid.UUID(ctx["cc"]["id"]))
        uow = UnitOfWork(s, InMemoryEventBus())
        assert await _seed_training(uow, cc) == 4
        assert await _seed_training(uow, cc) == 0
        await s.commit()
    listed = (
        await client.get(
            "/training/scenarios", headers=ctx["dispo"], params={"control_center_id": ctx["cc"]["id"]}
        )
    ).json()
    assert {s["keyword_code"] for s in listed} == {"B2", "H-KLEMM", "RD2", "B-MIG"}

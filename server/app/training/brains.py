"""The caller's "brain": Claude (streaming) or a rule-based fallback without AI.

Claude
* streamed replies (``client.beta.messages.stream``) so the first sentence can be shown and
  spoken while the rest is still generated; effort ``low`` for the conversation (chat-like,
  latency-sensitive), configurable model (default ``claude-opus-5-5``);
* the system prompt is stable per session and top-level ``cache_control`` caches the growing
  conversation prefix;
* server-side ``fallbacks="default"`` re-runs a declined request on a fallback model;
* the evaluation uses structured outputs (``beta.messages.parse`` with a Pydantic model).

Rules
* answers from the scenario facts by keyword matching – usable without any API key, clearly
  labelled as rule-based in the transcript and the evaluation.
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic
from pydantic import BaseModel, Field

from app.training.prompts import EVALUATION_SYSTEM, caller_system_prompt, evaluation_prompt

FALLBACK_BETA = "server-side-fallback-2026-07-01"
EVALUATION_TIMEOUT_S = 180.0
SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


class CallerUnavailableError(Exception):
    """The AI could not answer (no key, network, rate limit, refusal …) – message is for users."""


@dataclass(slots=True)
class Turn:
    role: str  # dispatcher | caller | instructor | system
    text: str


@dataclass(slots=True)
class ReplyStats:
    first_token_ms: int | None = None
    first_sentence_ms: int | None = None
    model: str | None = None
    stop_reason: str | None = None
    cache_read_tokens: int | None = None
    fallback_used: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class ItemJudgement(BaseModel):
    key: str = Field(description="key des Prüfpunkts")
    fulfilled: bool
    evidence: str = Field(description="kurzes wörtliches Zitat des Disponenten oder 'nicht gefragt'")


class TranscriptJudgement(BaseModel):
    items: list[ItemJudgement]
    strengths: list[str]
    improvements: list[str]
    summary: str


class Brain(Protocol):
    mode: str  # claude | rules
    model: str | None

    def reply(self, snapshot: dict[str, Any], turns: list[Turn], stats: ReplyStats) -> AsyncIterator[str]: ...

    async def judge(
        self, snapshot: dict[str, Any], transcript: list[tuple[str, str]], items: list[dict[str, Any]]
    ) -> TranscriptJudgement: ...


PAUSE = "(kurze Pause)"
ANSWERED = "(Der Disponent nimmt den Notruf an.)"


def to_messages(turns: list[Turn]) -> list[dict[str, Any]]:
    """Transcript → Messages API.

    dispatcher → ``user``, caller → ``assistant``, instructor → mid-conversation ``system`` message.
    A system message must follow a user turn and be last or followed by an assistant turn, so
    instructions are placed directly before the next caller reply (or at the end). A synthetic
    pause stands in for the dispatcher when the instruction comes while the caller spoke last.
    The rendering is a pure function of the stored transcript – the prefix of earlier requests
    stays byte-identical, which keeps the prompt cache valid.
    """
    messages: list[dict[str, Any]] = []
    pending: list[str] = []

    def flush() -> None:
        if not pending:
            return
        if not messages or messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": PAUSE})
        messages.extend({"role": "system", "content": f"Regie: {text}"} for text in pending)
        pending.clear()

    for turn in turns:
        if turn.role == "dispatcher":
            if messages and messages[-1]["role"] == "user":  # several messages in a row
                messages[-1] = {"role": "user", "content": f"{messages[-1]['content']}\n{turn.text}"}
            else:
                messages.append({"role": "user", "content": turn.text})
        elif turn.role == "caller":
            if not messages:  # the opening line: the moment the call is answered
                messages.append({"role": "user", "content": ANSWERED})
            flush()
            messages.append({"role": "assistant", "content": turn.text})
        elif turn.role == "instructor":
            pending.append(turn.text)
    flush()
    if not messages or messages[-1]["role"] == "assistant":
        messages.append({"role": "user", "content": PAUSE})
    return messages


def split_sentences(buffer: str) -> tuple[list[str], str]:
    """Complete sentences from a growing buffer; returns (sentences, rest)."""
    parts = SENTENCE_END.split(buffer)
    if len(parts) == 1:
        return [], buffer
    return [p.strip() for p in parts[:-1] if p.strip()], parts[-1]


# --------------------------------------------------------------------------------- Claude
class ClaudeBrain:
    mode = "claude"

    def __init__(
        self, client: Any, model: str, caller_effort: str = "low", evaluation_effort: str = "medium"
    ) -> None:
        self.client = client
        self.model = model
        self.caller_effort = caller_effort
        self.evaluation_effort = evaluation_effort

    async def reply(
        self, snapshot: dict[str, Any], turns: list[Turn], stats: ReplyStats
    ) -> AsyncIterator[str]:
        started = time.perf_counter()
        stats.model = self.model
        try:
            async with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=4000,  # short spoken replies; thinking tokens count towards the limit
                system=[{"type": "text", "text": caller_system_prompt(snapshot)}],
                messages=to_messages(turns),
                cache_control={"type": "ephemeral"},  # caches system + conversation prefix
                output_config={"effort": self.caller_effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                async for text in stream.text_stream:
                    if stats.first_token_ms is None:
                        stats.first_token_ms = round((time.perf_counter() - started) * 1000)
                    yield text
                final = await stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise CallerUnavailableError("KI-Anrufer: API-Schlüssel ungültig") from exc
        except anthropic.RateLimitError as exc:
            raise CallerUnavailableError("KI-Anrufer: Anfragelimit erreicht – bitte kurz warten") from exc
        except anthropic.APIStatusError as exc:
            raise CallerUnavailableError(
                f"KI-Anrufer: Fehler der KI-Schnittstelle ({exc.status_code})"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise CallerUnavailableError("KI-Anrufer: KI-Schnittstelle nicht erreichbar") from exc
        stats.stop_reason = final.stop_reason
        stats.model = getattr(final, "model", self.model)
        usage = getattr(final, "usage", None)
        # served-by signal (also covers sticky turns, which carry no fallback block)
        iterations = getattr(usage, "iterations", None) or []
        stats.fallback_used = any(getattr(i, "type", None) == "fallback_message" for i in iterations)
        stats.cache_read_tokens = getattr(usage, "cache_read_input_tokens", None) if usage else None
        if final.stop_reason == "refusal":
            raise CallerUnavailableError("KI-Anrufer hat die Antwort abgelehnt – bitte anders formulieren")

    async def judge(
        self, snapshot: dict[str, Any], transcript: list[tuple[str, str]], items: list[dict[str, Any]]
    ) -> TranscriptJudgement:
        try:
            response = await self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=EVALUATION_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": evaluation_prompt(transcript, items, snapshot.get("facts") or {}),
                    }
                ],
                output_config={"effort": self.evaluation_effort},
                output_format=TranscriptJudgement,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                timeout=EVALUATION_TIMEOUT_S,
            )
        except anthropic.APIStatusError as exc:
            raise CallerUnavailableError(
                f"Auswertung: Fehler der KI-Schnittstelle ({exc.status_code})"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise CallerUnavailableError("Auswertung: KI-Schnittstelle nicht erreichbar") from exc
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise CallerUnavailableError("Auswertung: KI hat keine verwertbare Bewertung geliefert")
        return response.parsed_output


# ---------------------------------------------------------------------------------- rules
RULE_TOPICS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("phone", ("nummer", "rückruf", "telefonnummer", "erreichbar")),
    ("name", ("name", "wer spricht", "wer ist am", "heißen sie", "mit wem")),
    ("location", ("wo ", "wo?", "adresse", "straße", "hausnummer", "ort", "genau")),
    ("injuries", ("verletzt", "atmet", "bewusst", "blut", "schmerz", "ansprechbar", "eingeklemmt")),
    ("persons", ("wie viele", "personen", "jemand", "menschen", "kinder", "noch drin")),
    ("hazards", ("gefahr", "rauch", "brennt", "feuer", "gas", "ausbreit", "flammen")),
    ("situation", ("was ist", "passiert", "was genau", "worum", "was sehen")),
)


class RuleBrain:
    """Answers from the scenario facts without AI (keyword matching)."""

    mode = "rules"
    model = None

    @staticmethod
    def answer(snapshot: dict[str, Any], question: str) -> str:
        q = f" {question.lower()} "
        persona, facts = snapshot.get("persona") or {}, snapshot.get("facts") or {}
        for topic, words in RULE_TOPICS:
            if not any(w in q for w in words):
                continue
            if topic == "phone" and persona.get("phone"):
                return f"Meine Nummer ist {persona['phone']}."
            if topic == "name" and persona.get("name"):
                return f"Ich heiße {persona['name']}."
            if topic == "location" and facts.get("address"):
                hint = f" {facts['location_hint']}." if facts.get("location_hint") else ""
                return f"{facts['address']}.{hint}".replace("..", ".")
            if topic in ("injuries", "persons", "hazards", "situation") and facts.get(topic):
                return str(facts[topic])
        if any(w in q for w in ("tschüss", "auf wiederhören", "wir kommen", "hilfe ist unterwegs")):
            return "Danke, bitte beeilen Sie sich!"
        return "Das weiß ich nicht genau. Bitte schicken Sie schnell jemanden!"

    async def reply(
        self, snapshot: dict[str, Any], turns: list[Turn], stats: ReplyStats
    ) -> AsyncIterator[str]:
        stats.first_token_ms = stats.first_sentence_ms = 0
        last = next((t.text for t in reversed(turns) if t.role == "dispatcher"), "")
        yield self.answer(snapshot, last)

    async def judge(
        self, snapshot: dict[str, Any], transcript: list[tuple[str, str]], items: list[dict[str, Any]]
    ) -> TranscriptJudgement:
        said = [text for role, text in transcript if role == "dispatcher"]
        judged = []
        for item in items:
            hints = [h.lower() for h in item.get("hints") or []]
            hit = next((s for s in said if any(h in s.lower() for h in hints)), None)
            judged.append(
                ItemJudgement(key=item["key"], fulfilled=hit is not None, evidence=hit or "nicht gefragt")
            )
        return TranscriptJudgement(
            items=judged,
            strengths=[],
            improvements=[],
            summary="Regelbasierte Auswertung (Schlüsselwörter) – ohne KI.",
        )


BrainFactory = Callable[[], Brain]

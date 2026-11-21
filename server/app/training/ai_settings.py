"""AI settings (stored in ``system_settings``; the API key only encrypted with SecretBox).

Resolution of the caller's brain:
* AI enabled and a key available (stored encrypted, or ``ILS_ANTHROPIC_API_KEY`` on the server)
  → Claude with the configured model (default ``claude-opus-5-5``),
* otherwise → rule-based caller (works offline, labelled as such).

The Anthropic client always gets the base URL from the server configuration – it never inherits
``ANTHROPIC_*`` variables of the process environment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic

from app.core.config import Settings
from app.core.crypto import SecretBox
from app.models import SystemSetting
from app.services.uow import UnitOfWork
from app.training.brains import Brain, ClaudeBrain, RuleBrain

AI_KEY = "ai_settings"
DEFAULT_MODEL = "claude-opus-5-5"
EFFORTS = ("low", "medium", "high", "xhigh", "max")


@dataclass(slots=True)
class AiConfig:
    enabled: bool = False
    model: str = DEFAULT_MODEL
    caller_effort: str = "low"
    evaluation_effort: str = "medium"
    key_encrypted: str | None = None
    key_hint: str | None = None

    def public(self, env_key: bool) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "model": self.model,
            "caller_effort": self.caller_effort,
            "evaluation_effort": self.evaluation_effort,
            "has_key": self.key_encrypted is not None,
            "key_hint": self.key_hint,
            "server_key": env_key,
        }


async def load(uow: UnitOfWork) -> tuple[SystemSetting | None, AiConfig]:
    row = await uow.session.get(SystemSetting, AI_KEY)
    if row is None:
        return None, AiConfig()
    value = dict(row.value or {})
    return row, AiConfig(**{k: v for k, v in value.items() if k in AiConfig.__dataclass_fields__})


def make_client(api_key: str, base_url: str, timeout: float) -> Any:
    """Tests replace this factory with a stub that mimics the SDK."""
    return AsyncAnthropic(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=1)


def api_key_of(config: AiConfig, settings: Settings, box: SecretBox) -> str | None:
    if config.key_encrypted:
        return box.decrypt(config.key_encrypted)
    return settings.anthropic_api_key or None


def brain_for(config: AiConfig, settings: Settings, box: SecretBox) -> Brain:
    key = api_key_of(config, settings, box) if config.enabled else None
    if not key:
        return RuleBrain()
    client = make_client(key, settings.anthropic_base_url, settings.anthropic_timeout_seconds)
    return ClaudeBrain(client, config.model, config.caller_effort, config.evaluation_effort)

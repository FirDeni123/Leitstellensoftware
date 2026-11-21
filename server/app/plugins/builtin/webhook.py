"""Generic HTTPS webhook (JSON POST) – a REAL interface.

Typical use: additional alerting (Zusatzalarmierung) via an alarm app or fire brigade
software that accepts webhooks. Only allowed in real operation; the core redirects it to the
simulation otherwise.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.plugins.base import AlarmMessage, DeliveryResult, PluginMeta

# Tests inject an httpx.MockTransport here; production uses the default transport.
TRANSPORT: httpx.AsyncBaseTransport | None = None


class WebhookPlugin:
    meta = PluginMeta(
        key="webhook",
        name="Webhook (HTTP POST, real)",
        description="Sendet Alarmierungen als JSON per HTTPS an eine externe Adresse "
        "(z. B. Alarmierungs-App, "
        "Feuerwehrsoftware). Reale Schnittstelle – nur im Echtbetrieb aktiv.",
        is_real=True,
        secret_label="Token / API-Schlüssel",  # noqa: S106 – a label, not a secret
        config_schema={
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {
                    "type": "string",
                    "title": "Ziel-URL",
                    "format": "uri",
                    "pattern": "^https://",
                    "maxLength": 500,
                },
                "auth_header": {
                    "type": "string",
                    "title": "Header für den Schlüssel",
                    "default": "Authorization",
                    "pattern": "^[A-Za-z0-9-]{1,40}$",
                },
                "auth_scheme": {
                    "type": "string",
                    "title": "Schema",
                    "enum": ["Bearer", "Token", "none"],
                    "default": "Bearer",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "title": "Zeitlimit (s)",
                    "minimum": 1,
                    "maximum": 30,
                    "default": 5,
                },
            },
            "additionalProperties": False,
        },
    )

    def _headers(self, config: dict[str, Any], secret: str | None) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "User-Agent": "ILS-Sim-Webhook/1"}
        if secret:
            scheme = config.get("auth_scheme", "Bearer")
            value = secret if scheme == "none" else f"{scheme} {secret}"
            headers[config.get("auth_header", "Authorization")] = value
        return headers

    async def _post(
        self, config: dict[str, Any], secret: str | None, payload: dict[str, Any]
    ) -> DeliveryResult:
        timeout = float(config.get("timeout_seconds", 5))
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=TRANSPORT) as client:
                response = await client.post(
                    config["url"], json=payload, headers=self._headers(config, secret)
                )
        except httpx.HTTPError as exc:
            return DeliveryResult(False, f"Verbindungsfehler: {type(exc).__name__}")
        if 200 <= response.status_code < 300:
            return DeliveryResult(True, f"HTTP {response.status_code}", response.headers.get("x-request-id"))
        return DeliveryResult(False, f"HTTP {response.status_code}")

    async def test(self, config: dict[str, Any], secret: str | None) -> DeliveryResult:
        return await self._post(config, secret, {"type": "test", "source": "ILS-Sim"})

    async def send_alarm(
        self, config: dict[str, Any], secret: str | None, message: AlarmMessage
    ) -> DeliveryResult:
        return await self._post(config, secret, {"type": "alarm", "source": "ILS-Sim", **message.to_dict()})

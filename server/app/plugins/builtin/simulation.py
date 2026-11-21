"""Simulation receiver: accepts alarms without contacting anything (training, development)."""

from __future__ import annotations

from typing import Any

from app.plugins.base import AlarmMessage, DeliveryResult, PluginMeta


class SimulationReceiverPlugin:
    meta = PluginMeta(
        key="simulation_receiver",
        name="Simulations-Empfänger",
        description="Nimmt Alarmierungen entgegen und protokolliert sie – keine reale Übertragung. "
        "Geeignet für Training und als Stellvertreter einer späteren Feuerwehrsoftware.",
        is_real=False,
        config_schema={
            "type": "object",
            "properties": {
                "receiver_label": {"type": "string", "title": "Bezeichnung des Empfängers", "maxLength": 120}
            },
            "additionalProperties": False,
        },
    )

    async def test(self, config: dict[str, Any], secret: str | None) -> DeliveryResult:
        return DeliveryResult(True, "Simulations-Empfänger bereit (keine reale Verbindung)")

    async def send_alarm(
        self, config: dict[str, Any], secret: str | None, message: AlarmMessage
    ) -> DeliveryResult:
        label = config.get("receiver_label") or "Simulations-Empfänger"
        return DeliveryResult(
            True,
            f"{label}: Einsatz {message.incident_number} ({message.keyword or 'ohne Stichwort'}) "
            "simuliert empfangen",
        )

"""Plugin registry: built-in plugins plus external ones via entry points (``ils_sim.plugins``)."""

from __future__ import annotations

import logging
from importlib.metadata import entry_points

from app.core.errors import ValidationFailedError
from app.plugins.base import InterfacePlugin
from app.plugins.builtin.feuersoftware import FeuersoftwareConnectPlugin
from app.plugins.builtin.simulation import SimulationReceiverPlugin
from app.plugins.builtin.webhook import WebhookPlugin

logger = logging.getLogger(__name__)
ENTRY_POINT_GROUP = "ils_sim.plugins"

_REGISTRY: dict[str, InterfacePlugin] = {}


def register(plugin: InterfacePlugin) -> None:
    if not isinstance(plugin, InterfacePlugin):
        raise TypeError(f"{plugin!r} implementiert InterfacePlugin nicht")
    _REGISTRY[plugin.meta.key] = plugin


def get_plugin(key: str) -> InterfacePlugin:
    plugin = _REGISTRY.get(key)
    if plugin is None:
        raise ValidationFailedError(f"Unbekanntes Plugin „{key}“")
    return plugin


def all_plugins() -> list[InterfacePlugin]:
    return sorted(_REGISTRY.values(), key=lambda p: (p.meta.is_real, p.meta.name))


def load_entry_points() -> None:
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            register(ep.load()())
            logger.info("Plugin geladen: %s", ep.name)
        except Exception:  # a broken third-party plugin must not stop the server
            logger.exception("Plugin %s konnte nicht geladen werden", ep.name)


register(SimulationReceiverPlugin())
register(WebhookPlugin())
register(FeuersoftwareConnectPlugin())

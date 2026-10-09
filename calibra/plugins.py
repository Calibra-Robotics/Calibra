"""
calibra.plugins — optional extensions discovered through entry points.

The Apache core never imports extension packages directly (see ADR-012). An
extension declares an entry point in the ``calibra.plugins`` group that points
to a ``register(registry)`` function:

    [project.entry-points."calibra.plugins"]
    my_ext = "my_ext.plugin:register"

``register`` receives a :class:`PluginRegistry` and may add CLI commands or
hooks that the core calls at fixed points. With no extension installed, the
registry is empty and every hook is a no-op.

Hooks
-----
    outcome_recorded(record)          after OutcomeDatabase.record() writes locally
    card_pushed(repo_id, status_key)  after `calibra card --push` uploads a card
    badge_url(dataset_id, status_key) returns a badge URL for a dataset card, or None
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "calibra.plugins"


@dataclass
class PluginRegistry:
    commands: dict[str, Callable[[list[str]], None]] = field(default_factory=dict)
    outcome_recorded: list[Callable[[Any], None]] = field(default_factory=list)
    card_pushed: list[Callable[[str, str], None]] = field(default_factory=list)
    badge_url: Optional[Callable[[str, str], Optional[str]]] = None

    def add_command(self, name: str, handler: Callable[[list[str]], None]) -> None:
        """Register `calibra <name> ...`; the handler receives the remaining argv."""
        self.commands[name] = handler


_registry: Optional[PluginRegistry] = None


def get_registry() -> PluginRegistry:
    """Load installed extensions once and return the shared registry."""
    global _registry
    if _registry is None:
        _registry = _load()
    return _registry


def _load() -> PluginRegistry:
    from importlib.metadata import entry_points

    registry = PluginRegistry()
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            ep.load()(registry)
        except Exception as exc:
            logger.warning("calibra plugin %r failed to load: %s", ep.name, exc)
    return registry


def emit(event: str, *args: Any) -> None:
    """Call every hook registered for `event`. Hook failures never reach the caller."""
    for hook in getattr(get_registry(), event):
        try:
            hook(*args)
        except Exception as exc:
            logger.debug("calibra plugin hook %s failed (non-fatal): %s", event, exc)

"""Gateway event subscriber — opens a persistent WebSocket to the
OpenClaw gateway, dispatches received events to registered handlers.

See ``docs/plans/2026-05-02-gateway-event-subscriber-design.md`` for
the project rationale and architecture decisions. This module is the
runtime; projection / DB writes live in sibling modules added as
each event type's handler ships.
"""

from app.services.mc_gateway_subscriber.subscriber import Subscriber

__all__ = ["Subscriber"]

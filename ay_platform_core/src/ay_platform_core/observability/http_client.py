# =============================================================================
# File: http_client.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/observability/http_client.py
# Description: Factory for `httpx.AsyncClient` instances that automatically
#              inject the current `traceparent` on every outgoing request.
#              Components SHALL use this factory rather than constructing
#              `httpx.AsyncClient(...)` directly so cross-component
#              traffic never loses the trace.
#
# @relation implements:R-100-105
# =============================================================================

from __future__ import annotations

from typing import Any

import httpx

from ay_platform_core.observability.context import current_traceparent


async def _inject_traceparent(request: httpx.Request) -> None:
    """httpx event hook: stamp the current `traceparent` on the outgoing
    request. No-op when there is no active trace (e.g. background task
    started without a request scope)."""
    tp = current_traceparent()
    if tp:
        # Don't overwrite an explicitly set value; the caller may know
        # better (rare, but supported).
        request.headers.setdefault("traceparent", tp)


def make_traced_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
    """Build a `httpx.AsyncClient` with auto-trace propagation.

    Forwards every argument to `httpx.AsyncClient(...)`. If the caller
    already declared `event_hooks`, the trace hook is appended to its
    `request` list (no override).
    """
    event_hooks: dict[str, list] = kwargs.pop("event_hooks", {}) or {}
    request_hooks = list(event_hooks.get("request", []))
    request_hooks.append(_inject_traceparent)
    event_hooks = {**event_hooks, "request": request_hooks}
    return httpx.AsyncClient(*args, event_hooks=event_hooks, **kwargs)

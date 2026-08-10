"""Local no-op telemetry adapter for Chroma clients."""

from __future__ import annotations

from chromadb.telemetry.product import (
    ProductTelemetryClient,
    ProductTelemetryEvent,
)
from overrides import override


class NoOpTelemetry(ProductTelemetryClient):
    """Disable outbound Chroma product telemetry in local runtime."""

    @override
    def capture(self, event: ProductTelemetryEvent) -> None:
        _ = event

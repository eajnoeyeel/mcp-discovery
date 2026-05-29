"""EventBridge client adapter for MLP services."""

from __future__ import annotations

import json
from typing import Protocol


class ServerRegisteredPublisher(Protocol):
    """Protocol for publishing server.registered domain events."""

    async def publish_server_registered(self, server_id: str) -> None: ...


class Boto3EventBridgePublisher:
    """Publish domain events via a boto3 EventBridge client."""

    def __init__(self, eb_client) -> None:
        self._eb = eb_client

    async def publish_server_registered(self, server_id: str) -> None:
        """Publish the server.registered event payload to EventBridge."""
        response = self._eb.put_events(
            Entries=[
                {
                    "Source": "mcp-discovery",
                    "DetailType": "server.registered",
                    "Detail": json.dumps({"server_id": server_id}),
                }
            ]
        )
        if response.get("FailedEntryCount", 0) > 0:
            raise ValueError(f"Failed to publish EventBridge event: {response.get('Entries', [])}")


class EventBridgeClient:
    """Wrap EventBridge publishing behind an injectable publisher abstraction."""

    def __init__(
        self,
        eb_client=None,
        publisher: ServerRegisteredPublisher | None = None,
    ) -> None:
        if eb_client is not None and publisher is not None:
            raise ValueError("EventBridgeClient accepts either eb_client or publisher, not both")
        if publisher is None:
            if eb_client is None:
                raise ValueError("EventBridgeClient requires eb_client or publisher")
            publisher = Boto3EventBridgePublisher(eb_client=eb_client)
        self._publisher = publisher

    async def publish_server_registered(self, server_id: str) -> None:
        """Publish a server.registered event. Raises on failure so caller can handle."""
        await self._publisher.publish_server_registered(server_id)

"""Unit tests for the MLP EventBridge client adapter."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestBoto3EventBridgePublisher:
    @pytest.mark.asyncio
    async def test_publish_server_registered_sends_expected_payload(self):
        from service.adapters.eventbridge_client import Boto3EventBridgePublisher

        mock_eb = MagicMock()
        mock_eb.put_events = MagicMock(return_value={"FailedEntryCount": 0})
        publisher = Boto3EventBridgePublisher(eb_client=mock_eb)

        await publisher.publish_server_registered("srv")

        mock_eb.put_events.assert_called_once_with(
            Entries=[
                {
                    "Source": "mcp-discovery",
                    "DetailType": "server.registered",
                    "Detail": json.dumps({"server_id": "srv"}),
                }
            ]
        )

    @pytest.mark.asyncio
    async def test_publish_server_registered_raises_when_eventbridge_reports_failed_entries(self):
        from service.adapters.eventbridge_client import Boto3EventBridgePublisher

        mock_eb = MagicMock()
        mock_eb.put_events = MagicMock(
            return_value={
                "FailedEntryCount": 1,
                "Entries": [
                    {
                        "ErrorCode": "InternalFailure",
                        "ErrorMessage": "Event bus unavailable",
                    }
                ],
            }
        )
        publisher = Boto3EventBridgePublisher(eb_client=mock_eb)

        with pytest.raises(ValueError, match="Failed to publish EventBridge event"):
            await publisher.publish_server_registered("srv")


class TestEventBridgeClient:
    def test_init_raises_when_no_args_are_provided(self):
        from service.adapters.eventbridge_client import EventBridgeClient

        with pytest.raises(ValueError, match="requires eb_client or publisher"):
            EventBridgeClient()

    def test_init_raises_when_both_eb_client_and_publisher_are_provided(self):
        from service.adapters.eventbridge_client import EventBridgeClient

        publisher = MagicMock()
        publisher.publish_server_registered = AsyncMock()

        with pytest.raises(ValueError, match="either eb_client or publisher, not both"):
            EventBridgeClient(eb_client=MagicMock(), publisher=publisher)

    @pytest.mark.asyncio
    async def test_publish_server_registered_delegates_to_injected_publisher(self):
        from service.adapters.eventbridge_client import EventBridgeClient

        publisher = MagicMock()
        publisher.publish_server_registered = AsyncMock()
        client = EventBridgeClient(publisher=publisher)

        await client.publish_server_registered("srv")

        publisher.publish_server_registered.assert_awaited_once_with("srv")

    @pytest.mark.asyncio
    async def test_publish_server_registered_uses_boto3_publisher_by_default(self):
        from service.adapters.eventbridge_client import EventBridgeClient

        mock_eb = MagicMock()
        mock_eb.put_events = MagicMock(side_effect=Exception("EventBridge down"))
        client = EventBridgeClient(eb_client=mock_eb)

        with pytest.raises(Exception, match="EventBridge down"):
            await client.publish_server_registered("srv")

"""Persistent event loop for AWS Lambda handlers.

Unlike asyncio.run(), this preserves the loop across warm invocations,
allowing AsyncQdrantClient and httpx connection pools to be reused.
"""

import asyncio


def get_or_create_loop() -> asyncio.AbstractEventLoop:
    """Get existing event loop or create a new one."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop

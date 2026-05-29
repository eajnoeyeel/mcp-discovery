import os
import uuid

import pytest

from service.adapters.enrichment_cache import EnrichmentCache

pytestmark = pytest.mark.skipif(
    not os.getenv("SUPABASE_URL"),
    reason="Requires live Supabase",
)


@pytest.mark.asyncio
async def test_cache_miss_then_hit() -> None:
    cache = EnrichmentCache(
        supabase_url=os.environ["SUPABASE_URL"],
        supabase_key=os.environ["SUPABASE_SERVICE_KEY"],
    )
    h = f"test-{uuid.uuid4().hex}"
    assert await cache.get(h) is None

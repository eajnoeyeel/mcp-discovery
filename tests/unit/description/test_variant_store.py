"""Tests for VariantStore JSONL persistence."""

from pathlib import Path

import pytest

from mcp_discovery.description.base import PerClientVariant, VendorStyle
from mcp_discovery.description.variant_store import VariantStore


@pytest.fixture
def store(tmp_path: Path) -> VariantStore:
    return VariantStore(path=tmp_path / "variants.jsonl")


@pytest.fixture
def sample_variant() -> PerClientVariant:
    return PerClientVariant(
        tool_id="github::search_repositories",
        vendor=VendorStyle.GPT,
        description="Search GitHub repositories by keyword.",
        token_usage=350,
    )


class TestVariantStore:
    def test_save_and_load(self, store: VariantStore, sample_variant: PerClientVariant) -> None:
        store.save(sample_variant)
        loaded = store.load_all()
        assert len(loaded) == 1
        assert loaded[0].tool_id == "github::search_repositories"
        assert loaded[0].vendor == VendorStyle.GPT

    def test_load_by_tool_id(self, store: VariantStore) -> None:
        store.save(
            PerClientVariant(
                tool_id="github::search_repositories",
                vendor=VendorStyle.GPT,
                description="GPT version",
            )
        )
        store.save(
            PerClientVariant(
                tool_id="github::search_repositories",
                vendor=VendorStyle.CLAUDE,
                description="Claude version",
            )
        )
        store.save(
            PerClientVariant(
                tool_id="slack::send_message",
                vendor=VendorStyle.GPT,
                description="Send a message",
            )
        )

        github_variants = store.load_by_tool_id("github::search_repositories")
        assert len(github_variants) == 2
        vendors = {v.vendor for v in github_variants}
        assert vendors == {VendorStyle.GPT, VendorStyle.CLAUDE}

    def test_existing_tool_vendor_pair_detected(
        self, store: VariantStore, sample_variant: PerClientVariant
    ) -> None:
        store.save(sample_variant)
        assert store.exists("github::search_repositories", VendorStyle.GPT)
        assert not store.exists("github::search_repositories", VendorStyle.CLAUDE)

    def test_load_empty_file(self, tmp_path: Path) -> None:
        store = VariantStore(path=tmp_path / "empty.jsonl")
        assert store.load_all() == []

    def test_save_batch(self, store: VariantStore) -> None:
        variants = [
            PerClientVariant(tool_id="t1", vendor=VendorStyle.GPT, description="d1"),
            PerClientVariant(tool_id="t1", vendor=VendorStyle.CLAUDE, description="d2"),
            PerClientVariant(tool_id="t1", vendor=VendorStyle.GEMINI, description="d3"),
        ]
        store.save_batch(variants)
        assert len(store.load_all()) == 3

"""Per-client description variant generation."""

from mcp_discovery.description.base import PerClientVariant, VariantGenerator, VendorStyle
from mcp_discovery.description.llm_generator import LLMVariantGenerator
from mcp_discovery.description.templates import VENDOR_TEMPLATES, format_template
from mcp_discovery.description.variant_store import VariantStore

__all__ = [
    "LLMVariantGenerator",
    "PerClientVariant",
    "VENDOR_TEMPLATES",
    "VariantGenerator",
    "VariantStore",
    "VendorStyle",
    "format_template",
]

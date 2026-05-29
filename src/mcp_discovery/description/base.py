"""VariantGenerator ABC and VendorStyle enum."""

from abc import ABC, abstractmethod
from enum import StrEnum

from pydantic import BaseModel, Field


class VendorStyle(StrEnum):
    GEMINI = "gemini"
    CLAUDE = "claude"
    GPT = "gpt"


class PerClientVariant(BaseModel):
    """A single vendor-optimized description variant."""

    tool_id: str
    vendor: VendorStyle
    description: str
    token_usage: int = Field(0, description="Total tokens consumed to generate this variant")


class VariantGenerator(ABC):
    """Abstract base for generating vendor-optimized tool descriptions."""

    @abstractmethod
    async def generate(
        self,
        tool_id: str,
        tool_name: str,
        raw_description: str,
        input_schema: dict | None = None,
    ) -> dict[VendorStyle, PerClientVariant]:
        """Generate per-vendor description variants for a single tool."""

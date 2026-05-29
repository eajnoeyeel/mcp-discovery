"""Raw provider registration records — untransformed input."""

from pydantic import BaseModel, Field


class RegistryToolEntry(BaseModel):
    """A single tool in a registration request (raw provider input)."""

    tool_name: str
    description: str = ""
    input_schema: dict | None = None


class RegistryRecord(BaseModel):
    """Raw server registration record from a provider."""

    server_id: str
    name: str
    description: str = ""
    url: str = ""
    tags: list[str] = Field(default_factory=list)
    tools: list[RegistryToolEntry] = Field(default_factory=list)
    registered_by: str = ""

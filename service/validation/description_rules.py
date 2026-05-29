"""Description validation rules for MCP server/tool registration."""

MAX_DESCRIPTION_LENGTH = 10000

PROHIBITED_PATTERNS = [
    "ignore previous",
    "ignore above",
    "system:",
    "[inst]",
    "you are now",
    "forget everything",
    "<|im_start|>",
    "do not follow",
    "disregard",
    "override",
]


def validate_description(text: str) -> str | None:
    """Return an error message if the description is invalid, None if OK."""
    if len(text) > MAX_DESCRIPTION_LENGTH:
        return f"Description exceeds {MAX_DESCRIPTION_LENGTH} character limit"
    lowered = text.lower()
    for pattern in PROHIBITED_PATTERNS:
        if pattern in lowered:
            return "Description contains prohibited pattern"
    return None

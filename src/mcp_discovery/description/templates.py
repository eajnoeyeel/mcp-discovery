"""Vendor-specific prompt templates for per-client description generation.

Research basis: docs/research/per-client-description-optimization.md
- Gemini: structured specsheet (GEO + Per-Model: +40% accuracy with templates)
- Claude: authoritative XML (trained on XML-structured data)
- GPT: action-first markdown (XML hurts GPT readability)
"""

from mcp_discovery.description.base import VendorStyle

GEMINI_SPECSHEET_TEMPLATE = """\
You are a technical writer creating a Gemini-optimized MCP tool description.

FORMAT: Structured specsheet with key-value pairs, category tags, and enum lists.
STYLE: Precise, measurable attributes. Enumerate all options explicitly.

Tool name: {tool_name}
Current description: {raw_description}
Parameters: {parameters}

Generate a tool description in this EXACT format:
```
Tool: {tool_name}
Category: <primary category> / <secondary category>
Function: <1-2 sentence description of what this tool does>
Parameters:
  - <param_name> (<required/optional>, <type>): <description>
  ...
Returns: <return type and key fields>
Supported Filters: <if applicable>
Example Use Cases:
  - <concrete example with measurable criteria>
  - <concrete example with measurable criteria>
  - <concrete example with measurable criteria>
```

RULES:
- Use key-value pairs, NOT prose
- Enumerate enum values in [a | b | c] format
- Include measurable criteria in examples (counts, dates, thresholds)
- 150 words maximum
- English, third person, present tense"""

CLAUDE_XML_TEMPLATE = """\
You are a technical writer creating a Claude-optimized MCP tool description.

FORMAT: Authoritative narrative with XML tag structure.
STYLE: Use "standard interface", "widely adopted", "canonical" tone. \
Include rationale section.

Tool name: {tool_name}
Current description: {raw_description}
Parameters: {parameters}

Generate a tool description in this EXACT format:
```xml
<tool name="{tool_name}">
<description>
<authoritative 1-2 sentence description with "standard", "widely adopted" tone>
</description>
<capabilities>
<capability><specific capability 1></capability>
<capability><specific capability 2></capability>
<capability><specific capability 3></capability>
</capabilities>
<parameters>
<param name="<name>" required="<true/false>" type="<type>"><description></param>
...
</parameters>
<rationale>
<1 sentence explaining why this tool is the canonical choice for its function>
</rationale>
</tool>
```

RULES:
- Use XML tags for structure
- Use authoritative language ("standard interface for", "widely adopted")
- List capabilities as explicit bullet items inside <capabilities>
- Include a <rationale> section with logical justification
- 200 words maximum
- English, third person, present tense"""

GPT_MARKDOWN_TEMPLATE = """\
You are a technical writer creating a GPT-optimized MCP tool description.

FORMAT: Action-first markdown with headers.
STYLE: First line = core function summary. Use ## headers for sections. \
Concise, scannable.

Tool name: {tool_name}
Current description: {raw_description}
Parameters: {parameters}

Generate a tool description in this EXACT format:
```markdown
<1-sentence core function summary starting with an action verb>

## Parameters
- **<param_name>** (<required/optional>, <type>): <description>
...

## Returns
<what the tool returns, key fields listed>

## Common Uses
- <concrete use case 1>
- <concrete use case 2>
- <concrete use case 3>
```

RULES:
- First line MUST be the core function summary (no heading before it)
- Use ## markdown headers for sections
- Keep parameters concise (one line each)
- 120 words maximum
- English, third person, present tense
- Do NOT use XML tags"""

VENDOR_TEMPLATES: dict[VendorStyle, str] = {
    VendorStyle.GEMINI: GEMINI_SPECSHEET_TEMPLATE,
    VendorStyle.CLAUDE: CLAUDE_XML_TEMPLATE,
    VendorStyle.GPT: GPT_MARKDOWN_TEMPLATE,
}


def format_template(
    vendor: VendorStyle,
    tool_name: str,
    raw_description: str,
    parameters: str,
) -> str:
    """Format a vendor template with tool metadata."""
    template = VENDOR_TEMPLATES[vendor]
    return template.format(
        tool_name=tool_name,
        raw_description=raw_description,
        parameters=parameters,
    )

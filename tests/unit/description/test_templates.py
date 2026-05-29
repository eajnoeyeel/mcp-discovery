"""Tests for VariantGenerator ABC, VendorStyle enum, and vendor templates."""

import pytest

from mcp_discovery.description.base import VariantGenerator, VendorStyle
from mcp_discovery.description.templates import (
    CLAUDE_XML_TEMPLATE,
    GEMINI_SPECSHEET_TEMPLATE,
    GPT_MARKDOWN_TEMPLATE,
    VENDOR_TEMPLATES,
    format_template,
)


class TestVendorStyle:
    def test_has_three_vendors(self) -> None:
        assert len(VendorStyle) == 3

    def test_vendor_values(self) -> None:
        assert VendorStyle.GEMINI == "gemini"
        assert VendorStyle.CLAUDE == "claude"
        assert VendorStyle.GPT == "gpt"


class TestVariantGeneratorABC:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            VariantGenerator()  # type: ignore[abstract]

    def test_subclass_must_implement_generate(self) -> None:
        class Incomplete(VariantGenerator):
            pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]


class TestVendorTemplates:
    def test_all_three_templates_defined(self) -> None:
        assert VendorStyle.GEMINI in VENDOR_TEMPLATES
        assert VendorStyle.CLAUDE in VENDOR_TEMPLATES
        assert VendorStyle.GPT in VENDOR_TEMPLATES

    def test_gemini_template_is_specsheet(self) -> None:
        assert "Category:" in GEMINI_SPECSHEET_TEMPLATE
        assert "Parameters:" in GEMINI_SPECSHEET_TEMPLATE

    def test_claude_template_uses_xml(self) -> None:
        assert "<capabilities>" in CLAUDE_XML_TEMPLATE
        assert "<parameters>" in CLAUDE_XML_TEMPLATE

    def test_gpt_template_uses_markdown_headers(self) -> None:
        assert "## Parameters" in GPT_MARKDOWN_TEMPLATE
        assert "## Returns" in GPT_MARKDOWN_TEMPLATE

    def test_format_template_substitutes_variables(self) -> None:
        result = format_template(
            VendorStyle.GPT,
            tool_name="search_repos",
            raw_description="Search repositories",
            parameters="query, language, sort",
        )
        assert "search_repos" in result
        assert "Search repositories" in result
        assert "query, language, sort" in result

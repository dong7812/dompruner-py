"""Tests for SSG RSC tree walker."""
import pytest
from dompruner.ssg import extract_ssg_markdown, _render_block, _render_inline, _dedup


RSC_TUPLE_H2 = ["$", "h2", None, {"children": "Getting Started"}]
RSC_TUPLE_P = ["$", "p", None, {"children": "This is a paragraph with enough text."}]
RSC_TUPLE_CODE = ["$", "code", None, {"children": "import asyncio"}]


def _make_payload(content):
    return {"props": {"pageProps": {"content": content}}}


def test_render_inline_string():
    assert _render_inline("hello") == "hello"


def test_render_inline_none():
    assert _render_inline(None) == ""


def test_render_inline_code():
    node = ["$", "code", None, {"children": "x = 1"}]
    assert _render_inline(node) == "`x = 1`"


def test_render_inline_strong():
    node = ["$", "strong", None, {"children": "bold text"}]
    assert _render_inline(node) == "**bold text**"


def test_render_inline_em():
    node = ["$", "em", None, {"children": "italic"}]
    assert _render_inline(node) == "_italic_"


def test_render_block_heading():
    lines = _render_block(["$", "h2", None, {"children": "Title"}])
    assert lines == ["## Title"]


def test_render_block_paragraph():
    lines = _render_block(["$", "p", None, {"children": "Some text here."}])
    assert lines == ["Some text here."]


def test_render_block_list_item():
    lines = _render_block(["$", "li", None, {"children": "item one"}])
    assert lines == ["- item one"]


def test_render_block_skip_tags():
    lines = _render_block(["$", "Meta", None, {"children": "ignored"}])
    assert lines == []


def test_render_block_passthrough():
    inner = ["$", "p", None, {"children": "inner paragraph text here"}]
    outer = ["$", "div", None, {"children": inner}]
    lines = _render_block(outer)
    assert "inner paragraph text here" in lines


def test_dedup_removes_consecutive_blanks():
    lines = ["a", "", "", "b", ""]
    assert _dedup(lines) == ["a", "", "b", ""]


def test_extract_ssg_markdown_success():
    content = [
        ["$", "h1", None, {"children": "My Page Title Long Enough"}],
        ["$", "p", None, {"children": "This is the first paragraph with sufficient content to pass the length check."}],
        ["$", "h2", None, {"children": "Section One"}],
        ["$", "p", None, {"children": "More content follows in this section to satisfy minimum length requirements."}],
    ]
    payload = _make_payload(content)
    result = extract_ssg_markdown(payload)
    assert result is not None
    assert "My Page Title Long Enough" in result["markdown"]
    assert result["title"] == "My Page Title Long Enough"


def test_extract_ssg_markdown_too_short():
    content = ["$", "p", None, {"children": "Short."}]
    payload = _make_payload(content)
    result = extract_ssg_markdown(payload)
    assert result is None


def test_extract_ssg_markdown_no_content():
    payload = {"props": {"pageProps": {}}}
    result = extract_ssg_markdown(payload)
    assert result is None

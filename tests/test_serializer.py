"""Tests for Markdown serializer."""
from dompruner.extractor import FQNNode
from dompruner.serializer import serialize, estimate_tokens


def test_heading_prefix():
    nodes = [FQNNode(tag="h2", text="My Section", depth=0)]
    assert serialize(nodes) == "## My Section"


def test_list_item():
    nodes = [FQNNode(tag="li", text="item", depth=0)]
    assert serialize(nodes) == "- item"


def test_blockquote():
    nodes = [FQNNode(tag="blockquote", text="quoted text", depth=0)]
    assert serialize(nodes) == "> quoted text"


def test_code_block_with_lang():
    nodes = [FQNNode(tag="pre", text="x = 1", depth=0, code_lang="python")]
    md = serialize(nodes)
    assert md.startswith("```python")
    assert "x = 1" in md


def test_estimate_tokens_nonzero():
    assert estimate_tokens("hello world") > 0


def test_estimate_tokens_approx():
    text = "a" * 400
    assert estimate_tokens(text) == 100


def test_empty_nodes():
    assert serialize([]) == ""

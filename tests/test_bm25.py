"""Tests for BM25 section filtering."""
import pytest
from dompruner.extractor import FQNNode
from dompruner.bm25 import bm25_filter, group_sections


def _make_nodes(pairs: list[tuple[str, str]]) -> list[FQNNode]:
    return [FQNNode(tag=tag, text=text, depth=1) for tag, text in pairs]


NODES = _make_nodes([
    ("h2", "Installation"),
    ("p", "Run pip install dompruner to get started with the package."),
    ("p", "Supports Python 3.11 and above with asyncio."),
    ("h2", "Authentication"),
    ("p", "You need an API key from the dashboard settings page."),
    ("p", "Set the environment variable DOMPRUNER_KEY to your key value."),
    ("h2", "Rate Limits"),
    ("p", "The free tier allows 100 requests per day maximum allowed quota."),
    ("p", "Upgrade to Pro for unlimited requests and higher throughput access."),
    ("h2", "Changelog"),
    ("p", "v1.0.0 initial release with core DOM extraction pipeline features."),
    ("p", "v1.1.0 adds BM25 section filtering with zero-score fallback logic."),
])


def test_filter_reduces_nodes():
    # token_budget=40 (word-tokens): forces filtering since NODES total ~100 word-tokens
    filtered, score = bm25_filter(NODES, "installation pip python", token_budget=40)
    assert score > 0
    assert len(filtered) < len(NODES)


def test_zero_score_fallback():
    """Query terms not in any section → return all nodes, score=0."""
    filtered, score = bm25_filter(NODES, "xyzzy quux frobnicate", token_budget=100)
    assert score == 0.0
    assert filtered is NODES


def test_relevant_sections_included():
    filtered, score = bm25_filter(NODES, "api key dashboard authentication")
    texts = " ".join(n.text for n in filtered)
    assert "API key" in texts or "api key" in texts.lower()


def test_no_query_passthrough():
    filtered, score = bm25_filter(NODES, "")
    assert score == 0.0
    assert filtered is NODES


def test_group_sections_by_headings():
    sections = group_sections(NODES)
    heading_texts = [s.heading.text for s in sections if s.heading]
    assert "Installation" in heading_texts
    assert "Rate Limits" in heading_texts

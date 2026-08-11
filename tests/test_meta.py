"""Tests for extract_meta and extract_content_and_meta."""
from __future__ import annotations

import pytest
from dompruner.extractor import extract_meta, extract_content_and_meta, extract_content


# ── extract_meta ─────────────────────────────────────────────────────────────

def test_meta_title_from_title_tag():
    html = "<html><head><title>Hello World</title></head><body></body></html>"
    assert extract_meta(html)["title"] == "Hello World"


def test_meta_title_og_fallback():
    html = """<html><head>
      <meta property="og:title" content="OG Title">
    </head><body></body></html>"""
    assert extract_meta(html)["title"] == "OG Title"


def test_meta_title_prefers_title_tag_over_og():
    html = """<html><head>
      <title>Native Title</title>
      <meta property="og:title" content="OG Title">
    </head><body></body></html>"""
    assert extract_meta(html)["title"] == "Native Title"


def test_meta_description_native():
    html = '<html><head><meta name="description" content="native desc"></head></html>'
    assert extract_meta(html)["description"] == "native desc"


def test_meta_description_og_fallback():
    html = '<html><head><meta property="og:description" content="og desc"></head></html>'
    assert extract_meta(html)["description"] == "og desc"


def test_meta_description_native_preferred_over_og():
    html = """<html><head>
      <meta name="description" content="native">
      <meta property="og:description" content="og">
    </head></html>"""
    assert extract_meta(html)["description"] == "native"


def test_meta_lang():
    html = '<html lang="ko"><head></head><body></body></html>'
    assert extract_meta(html)["lang"] == "ko"


def test_meta_canonical_url():
    html = '<html><head><link rel="canonical" href="https://example.com/page"></head></html>'
    assert extract_meta(html)["canonical_url"] == "https://example.com/page"


def test_meta_author():
    html = '<html><head><meta name="author" content="dong7812"></head></html>'
    assert extract_meta(html)["author"] == "dong7812"


def test_meta_published_time():
    html = '<html><head><meta property="article:published_time" content="2024-03-15T10:00:00Z"></head></html>'
    assert extract_meta(html)["published_time"] == "2024-03-15T10:00:00Z"


def test_meta_modified_time():
    html = '<html><head><meta property="article:modified_time" content="2024-08-01"></head></html>'
    assert extract_meta(html)["modified_time"] == "2024-08-01"


def test_meta_site_name():
    html = '<html><head><meta property="og:site_name" content="My Site"></head></html>'
    assert extract_meta(html)["site_name"] == "My Site"


def test_meta_empty_page():
    html = "<html><body><p>content</p></body></html>"
    assert extract_meta(html) == {}


def test_meta_no_keys_for_empty_content():
    """Empty content= attributes are not included."""
    html = '<html><head><meta name="description" content=""></head></html>'
    assert "description" not in extract_meta(html)


def test_meta_full_set():
    html = """<!doctype html>
<html lang="en">
<head>
  <title>Page Title</title>
  <meta name="description" content="page description">
  <meta name="author" content="author name">
  <meta property="article:published_time" content="2024-01-01">
  <meta property="article:modified_time" content="2024-06-01">
  <meta property="og:site_name" content="My Site">
  <link rel="canonical" href="https://example.com/canonical">
</head><body></body></html>"""
    meta = extract_meta(html)
    assert meta["title"] == "Page Title"
    assert meta["description"] == "page description"
    assert meta["author"] == "author name"
    assert meta["published_time"] == "2024-01-01"
    assert meta["modified_time"] == "2024-06-01"
    assert meta["site_name"] == "My Site"
    assert meta["canonical_url"] == "https://example.com/canonical"
    assert meta["lang"] == "en"


# ── extract_content_and_meta ──────────────────────────────────────────────────

def test_content_and_meta_single_parse():
    """extract_content_and_meta returns same content as extract_content."""
    html = """<html lang="en">
<head><title>Test</title></head>
<body><main><h1>Heading</h1><p>This is a paragraph with enough content.</p></main></body>
</html>"""
    nodes_combined, meta = extract_content_and_meta(html)
    nodes_separate = extract_content(html)

    assert len(nodes_combined) == len(nodes_separate)
    for a, b in zip(nodes_combined, nodes_separate):
        assert a.tag == b.tag
        assert a.text == b.text

    assert meta["title"] == "Test"
    assert meta["lang"] == "en"


def test_content_and_meta_independent_of_content():
    """Meta extraction does not affect content node output."""
    html = """<html><head>
      <meta name="description" content="desc">
    </head>
    <body><article>
      <h2>Section</h2>
      <p>Paragraph text that is long enough to be included.</p>
    </article></body></html>"""
    nodes, meta = extract_content_and_meta(html)
    assert any(n.tag == "h2" for n in nodes)
    assert any(n.tag == "p" for n in nodes)
    assert meta.get("description") == "desc"

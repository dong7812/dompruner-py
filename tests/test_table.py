"""Tests for table extraction and serialization."""
from __future__ import annotations

import pytest
from dompruner.extractor import extract_content
from dompruner.serializer import serialize


def _render(html: str) -> str:
    return serialize(extract_content(html))


# ── Basic structure ───────────────────────────────────────────────────────────

def test_table_thead_tbody():
    html = """<table>
      <thead><tr><th>Name</th><th>Score</th></tr></thead>
      <tbody><tr><td>Alice</td><td>95</td></tr></tbody>
    </table>"""
    out = _render(html)
    assert "| Name | Score |" in out
    assert "| --- | --- |" in out
    assert "| Alice | 95 |" in out


def test_table_th_only_header():
    """<tr> with <th> cells but no <thead> wrapper is still treated as header."""
    html = """<table>
      <tr><th>A</th><th>B</th></tr>
      <tr><td>1</td><td>2</td></tr>
    </table>"""
    out = _render(html)
    assert "| A | B |" in out
    assert "| --- | --- |" in out
    assert "| 1 | 2 |" in out


def test_table_no_header():
    """Table with no <th> has no separator row."""
    html = """<table>
      <tr><td>X</td><td>Y</td></tr>
      <tr><td>1</td><td>2</td></tr>
    </table>"""
    out = _render(html)
    assert "| X | Y |" in out
    assert "| --- |" not in out


def test_table_empty_cell_preserves_column_alignment():
    """Empty cells are kept as empty strings to maintain column count."""
    html = """<table>
      <thead><tr><th>Key</th><th>Value</th><th>Note</th></tr></thead>
      <tbody><tr><td>foo</td><td></td><td>optional</td></tr></tbody>
    </table>"""
    out = _render(html)
    # Empty cell preserved — "| foo |  | optional |"
    assert "| foo |  | optional |" in out


def test_table_multirow():
    html = """<table>
      <thead><tr><th>Tool</th><th>Tokens</th></tr></thead>
      <tbody>
        <tr><td>WebFetch</td><td>8000</td></tr>
        <tr><td>dompruner</td><td>600</td></tr>
      </tbody>
    </table>"""
    out = _render(html)
    lines = [l for l in out.split("\n") if l.strip()]
    assert lines[0] == "| Tool | Tokens |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| WebFetch | 8000 |"
    assert lines[3] == "| dompruner | 600 |"


# ── Mixed content ─────────────────────────────────────────────────────────────

def test_table_mixed_with_text():
    html = """<article>
      <h2>Comparison</h2>
      <p>See the table below.</p>
      <table>
        <thead><tr><th>A</th><th>B</th></tr></thead>
        <tbody><tr><td>1</td><td>2</td></tr></tbody>
      </table>
      <p>End of article.</p>
    </article>"""
    out = _render(html)
    assert "## Comparison" in out
    assert "See the table below." in out
    assert "| A | B |" in out
    assert "End of article." in out
    # Table is separated from surrounding text by blank lines
    parts = out.split("\n\n")
    table_part = next((p for p in parts if "| A |" in p), None)
    assert table_part is not None
    assert "\n" in table_part  # rows joined by single newline within the table


# ── Regression — non-table content unaffected ─────────────────────────────────

def test_no_table_regression_headings():
    html = "<main><h1>Title</h1><h2>Sub</h2><p>A paragraph with enough content here.</p></main>"
    out = _render(html)
    assert "# Title" in out
    assert "## Sub" in out
    assert "|" not in out


def test_no_table_regression_code():
    html = """<main>
      <p>Example below:</p>
      <pre><code class="language-python">print("hello")</code></pre>
    </main>"""
    out = _render(html)
    assert "```python" in out
    assert "|" not in out


def test_no_table_regression_list():
    html = "<ul><li>item one with enough text</li><li>item two with enough text</li></ul>"
    out = _render(html)
    assert "- item one" in out
    assert "|" not in out


# ── Skipped empty rows ─────────────────────────────────────────────────────────

def test_table_all_empty_row_skipped():
    """A row where every cell is empty produces no FQNNode."""
    html = """<table>
      <thead><tr><th>A</th><th>B</th></tr></thead>
      <tbody>
        <tr><td></td><td></td></tr>
        <tr><td>val</td><td>2</td></tr>
      </tbody>
    </table>"""
    nodes = extract_content(html)
    table_rows = [n for n in nodes if n.tag == "table_row"]
    # header + 1 data row (all-empty row skipped)
    assert len(table_rows) == 2

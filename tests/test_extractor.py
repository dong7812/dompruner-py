"""Tests for DOM extractor — L1 / L2 / L3 cascade."""
import pytest
from dompruner.extractor import extract_content, FQNNode


MINIMAL_HTML = """
<html><body>
  <nav><a href="/">Home</a></nav>
  <main>
    <h1>Getting Started</h1>
    <p>This guide walks you through installation and first steps.</p>
    <h2>Installation</h2>
    <p>Run <code>pip install dompruner</code> to install the package.</p>
    <h2>Usage</h2>
    <p>Import and call run_pipeline with a URL to prune its content.</p>
    <pre class="language-python">import asyncio\nfrom dompruner import run_pipeline</pre>
  </main>
  <footer>Copyright 2025</footer>
</body></html>
"""

NOISE_HEAVY_HTML = """
<html><body>
  <div class="cookie-banner">Accept cookies</div>
  <nav role="navigation">Nav links</nav>
  <article>
    <h2>Section A</h2>
    <p>Content for section A with more than ten characters easily.</p>
    <h2>Section B</h2>
    <p>Content for section B also longer than ten characters here.</p>
  </article>
  <aside>Sidebar content</aside>
</body></html>
"""


def test_extract_returns_nodes():
    nodes = extract_content(MINIMAL_HTML)
    assert len(nodes) > 0
    assert all(isinstance(n, FQNNode) for n in nodes)


def test_noise_tags_excluded():
    nodes = extract_content(MINIMAL_HTML)
    texts = [n.text for n in nodes]
    assert not any("Copyright" in t for t in texts), "footer should be excluded"
    assert not any("Home" in t for t in texts), "nav should be excluded"


def test_heading_included():
    nodes = extract_content(MINIMAL_HTML)
    headings = [n for n in nodes if n.tag in ("h1", "h2")]
    assert any("Getting Started" in n.text for n in headings)
    assert any("Installation" in n.text for n in headings)


def test_min_length_heading():
    """Headings shorter than 3 chars must be excluded."""
    html = "<html><body><h2>AB</h2><p>Long enough paragraph here.</p></body></html>"
    nodes = extract_content(html)
    assert not any(n.tag == "h2" and n.text == "AB" for n in nodes)


def test_deduplication():
    """Duplicate text blocks must appear only once."""
    dup = "<html><body>" + "<p>Same paragraph text here.</p>" * 3 + "</body></html>"
    nodes = extract_content(dup)
    matching = [n for n in nodes if "Same paragraph text" in n.text]
    assert len(matching) == 1


def test_noise_class_excluded():
    nodes = extract_content(NOISE_HEAVY_HTML)
    texts = " ".join(n.text for n in nodes)
    assert "Accept cookies" not in texts
    assert "Sidebar" not in texts


def test_code_lang_detected():
    nodes = extract_content(MINIMAL_HTML)
    pre_nodes = [n for n in nodes if n.tag == "pre" and n.code_lang]
    assert any(n.code_lang == "python" for n in pre_nodes)

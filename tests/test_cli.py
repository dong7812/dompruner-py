"""Tests for CLI __main__.py."""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch

from dompruner.__main__ import _build_parser, main
from dompruner.pipeline import PipelineResult


def _fake_result() -> PipelineResult:
    return PipelineResult(
        url="https://example.com",
        render_type="SSR",
        markdown="# Example\n\nContent.",
        original_tokens=1000,
        refined_tokens=50,
        reduction_ratio=0.95,
        fetch_ms=120.0,
        parse_ms=15.0,
        bm25_confidence=None,
        cached=False,
        meta={"title": "Example Domain", "lang": "en"},
    )


# ── Argument parser ───────────────────────────────────────────────────────────

def test_parser_url_only():
    args = _build_parser().parse_args(["https://example.com"])
    assert args.url == "https://example.com"
    assert args.query == ""
    assert args.as_json is False


def test_parser_url_and_query():
    args = _build_parser().parse_args(["https://example.com", "asyncio"])
    assert args.url == "https://example.com"
    assert args.query == "asyncio"


def test_parser_json_flag():
    args = _build_parser().parse_args(["https://example.com", "--json"])
    assert args.as_json is True


# ── Human output ─────────────────────────────────────────────────────────────

def test_main_human_output(capsys):
    with patch("dompruner.__main__.sync_run", return_value=_fake_result()), \
         patch("sys.argv", ["dompruner", "https://example.com"]):
        main()

    out = capsys.readouterr().out
    assert "https://example.com" in out
    assert "Example Domain" in out
    assert "96.0%" in out or "95.0%" in out or "95%" in out
    assert "# Example" in out


def test_main_json_output(capsys):
    with patch("dompruner.__main__.sync_run", return_value=_fake_result()), \
         patch("sys.argv", ["dompruner", "https://example.com", "--json"]):
        main()

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["url"] == "https://example.com"
    assert data["render_type"] == "SSR"
    assert data["meta"]["title"] == "Example Domain"
    assert data["reduction_ratio"] == pytest.approx(0.95)


def test_main_error_exits_with_code_1():
    with patch("dompruner.__main__.sync_run", side_effect=RuntimeError("connection refused")), \
         patch("sys.argv", ["dompruner", "https://bad-url.example"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1

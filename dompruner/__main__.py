"""CLI entry point: python -m dompruner <url> [query] [--json]"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from .pipeline import run_pipeline, sync_run


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m dompruner",
        description="Fetch a URL and return DOM-pruned Markdown with 90%+ token reduction.",
    )
    p.add_argument("url", help="URL to fetch")
    p.add_argument("query", nargs="?", default="", help="BM25 filter query (optional)")
    p.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")
    return p


def _print_human(result) -> None:
    sep = "─" * 60
    cached_label = "Yes" if result.cached else "No"
    bm25 = f"{result.bm25_confidence:.2f}" if result.bm25_confidence else "—"
    print(f"URL          : {result.url}")
    if result.meta.get("title"):
        print(f"Title        : {result.meta['title']}")
    print(f"Render type  : {result.render_type}")
    print(f"Tokens       : {result.original_tokens:,} → {result.refined_tokens:,}  "
          f"({result.reduction_ratio:.1%} reduction)")
    print(f"BM25 score   : {bm25}")
    print(f"Cached       : {cached_label}")
    print(f"Fetch        : {result.fetch_ms:.0f}ms  Parse: {result.parse_ms:.0f}ms")
    if result.meta:
        for k, v in result.meta.items():
            if k != "title":
                print(f"{k:<13}: {v}")
    print(sep)
    print(result.markdown)


def main() -> None:
    args = _build_parser().parse_args()
    try:
        result = sync_run(run_pipeline(args.url, args.query))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.as_json:
        d = dataclasses.asdict(result)
        print(json.dumps(d, ensure_ascii=False, indent=2))
    else:
        _print_human(result)


if __name__ == "__main__":
    main()

"""
dompruner-py benchmark — same URL/query set as dompruner-mcp benchmark.
Measures: fetch_ms, parse_ms, original_tokens, refined_tokens, reduction_ratio
"""
import asyncio
import sys
import time

sys.path.insert(0, "/Users/dongkyu/dompruner-py")
from dompruner.pipeline import run_pipeline

CASES = [
    ("Python asyncio",       "https://docs.python.org/3/library/asyncio-task.html",    "asyncio create_task"),
    ("Rust Book ch04",       "https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html", "ownership move borrow"),
    ("React useState",       "https://react.dev/reference/react/useState",              "useState immutability"),
    ("FastAPI Body",         "https://fastapi.tiangolo.com/tutorial/body/",             "request body"),
    ("MDN Fetch API",        "https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API", "CORS headers"),
    ("Next.js Routing",      "https://nextjs.org/docs/app/building-your-application/routing", "app router"),
    ("TypeScript Handbook",  "https://www.typescriptlang.org/docs/handbook/2/types-from-types.html", "infer keyword"),
    ("Vue Reactivity",       "https://vuejs.org/guide/essentials/reactivity-fundamentals.html", "proxy internals"),
]


async def bench_one(name: str, url: str, query: str) -> dict:
    t0 = time.perf_counter()
    try:
        result = await run_pipeline(url, query)
        elapsed = (time.perf_counter() - t0) * 1000
        return {
            "name": name,
            "url": url,
            "query": query,
            "original_tokens": result.original_tokens,
            "refined_tokens": result.refined_tokens,
            "reduction_ratio": result.reduction_ratio,
            "fetch_ms": result.fetch_ms,
            "parse_ms": result.parse_ms,
            "total_ms": elapsed,
            "render_type": result.render_type,
            "bm25_confidence": result.bm25_confidence,
            "error": None,
        }
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        return {
            "name": name, "url": url, "query": query,
            "error": str(e), "total_ms": elapsed,
            "original_tokens": 0, "refined_tokens": 0,
            "reduction_ratio": 0, "fetch_ms": 0, "parse_ms": 0,
            "render_type": "error", "bm25_confidence": None,
        }


async def main():
    print(f"Running {len(CASES)} benchmarks (sequential to avoid rate limits)...\n")
    results = []
    for name, url, query in CASES:
        print(f"  → {name}...", end="", flush=True)
        r = await bench_one(name, url, query)
        results.append(r)
        if r["error"]:
            print(f" ERROR: {r['error'][:60]}")
        else:
            print(f" {r['original_tokens']:,} → {r['refined_tokens']:,} tokens "
                  f"({r['reduction_ratio']:.1%}) | fetch={r['fetch_ms']:.0f}ms parse={r['parse_ms']:.1f}ms | {r['render_type']}")

    print("\n" + "="*80)
    print(f"{'Site':<24} {'Raw':>8} {'Pruned':>8} {'Reduction':>10} {'Fetch':>8} {'Parse':>8} {'Mode'}")
    print("-"*80)
    total_orig = total_refined = 0
    good = [r for r in results if not r["error"]]
    for r in good:
        mode = "BM25" if r["bm25_confidence"] and r["bm25_confidence"] > 0 else "full"
        print(f"{r['name']:<24} {r['original_tokens']:>8,} {r['refined_tokens']:>8,} "
              f"{r['reduction_ratio']:>9.1%} {r['fetch_ms']:>7.0f}ms {r['parse_ms']:>7.1f}ms  {mode}")
        total_orig += r["original_tokens"]
        total_refined += r["refined_tokens"]

    if good:
        avg_reduction = 1 - total_refined / max(total_orig, 1)
        avg_fetch = sum(r["fetch_ms"] for r in good) / len(good)
        avg_parse = sum(r["parse_ms"] for r in good) / len(good)
        print("-"*80)
        print(f"{'Average':<24} {total_orig//len(good):>8,} {total_refined//len(good):>8,} "
              f"{avg_reduction:>9.1%} {avg_fetch:>7.0f}ms {avg_parse:>7.1f}ms")

    errors = [r for r in results if r["error"]]
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for r in errors:
            print(f"  {r['name']}: {r['error'][:80]}")


asyncio.run(main())

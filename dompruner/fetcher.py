from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_SSG_PATTERNS = [
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    r'window\.__NUXT__\s*=\s*(\{.*?\});',
    r'window\.page\s*=\s*(\{.*?\});',
]


@dataclass
class FetchResult:
    url: str
    html: str
    render_type: str          # "SSG" | "SSR" | "CSR"
    ssg_payload: Any | None   # parsed JSON if SSG


async def fetch_page(url: str) -> FetchResult:
    headers = {"User-Agent": _USER_AGENTS[0], "Accept-Language": "en-US,en;q=0.9"}

    html, final_url = await _fetch_with_fallback(url, headers)

    ssg_payload = _extract_ssg(html)
    if ssg_payload:
        return FetchResult(url=final_url, html=html, render_type="SSG", ssg_payload=ssg_payload)

    body_text = re.sub(r"<[^>]+>", " ", html)
    body_text = re.sub(r"\s+", " ", body_text)
    density = len(body_text.strip()) / max(len(html), 1)
    render_type = "SSR" if density >= 0.02 else "CSR"

    return FetchResult(url=final_url, html=html, render_type=render_type, ssg_payload=None)


async def _fetch_with_fallback(url: str, headers: dict) -> tuple[str, str]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        # L1: direct fetch
        try:
            r = await client.get(url, headers=headers)
            if r.status_code not in (403, 429):
                return r.text, str(r.url)
        except httpx.RequestError:
            pass

        # L2: UA rotation
        for ua in _USER_AGENTS[1:]:
            try:
                r = await client.get(url, headers={**headers, "User-Agent": ua})
                if r.status_code not in (403, 429):
                    return r.text, str(r.url)
            except httpx.RequestError:
                continue

    # L3: playwright fallback
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle")
            html = await page.content()
            final_url = page.url
            await browser.close()
            return html, final_url
    except ImportError:
        raise RuntimeError(
            "Page requires JavaScript rendering. "
            "Install playwright: pip install dompruner[playwright] && playwright install chromium"
        )


def _extract_ssg(html: str) -> Any | None:
    for pattern in _SSG_PATTERNS:
        m = re.search(pattern, html, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
    return None

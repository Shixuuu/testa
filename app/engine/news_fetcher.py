"""News fetcher — Forex Factory calendar + Google News RSS search."""
from __future__ import annotations
import asyncio
import html as _html_mod
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date

import httpx

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


@dataclass
class NewsItem:
    title: str
    source: str
    url: str = ""
    timestamp: str = ""
    snippet: str = ""
    impact: str = ""      # "HIGH" | "MEDIUM" | "LOW" | ""
    currency: str = ""


def web_search(query: str, max_results: int = 6) -> str:
    """
    Google News RSS search — free, no API key, always returns real headlines.
    Returns formatted text suitable for display or AI context.
    """
    try:
        params = urllib.parse.urlencode({
            "q": query,
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        })
        req = urllib.request.Request(
            f"https://news.google.com/rss/search?{params}",
            headers={"User-Agent": "FuturesBacktestTUI/1.0 (news reader)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml = resp.read().decode("utf-8", errors="replace")

        # Parse individual <item> blocks so ordering is preserved
        item_blocks = re.findall(r"<item>(.+?)</item>", xml, re.DOTALL)
        if not item_blocks:
            return f"No results for: {query}"

        parts = []
        for block in item_blocks[:max_results]:
            t = re.search(r"<title>(.+?)</title>", block)
            s = re.search(r"<source[^>]*>(.+?)</source>", block)
            d = re.search(r"<pubDate>(.+?)</pubDate>", block)
            if not t:
                continue
            title = _html_mod.unescape(t.group(1)).strip()
            src = s.group(1).strip() if s else ""
            dt = (d.group(1)[:16].strip() if d else "")
            meta = " · ".join(filter(None, [src, dt]))
            parts.append(f"{title}\n  {meta}" if meta else title)

        return "\n\n".join(parts) if parts else f"No results for: {query}"
    except Exception as exc:
        return f"Search error: {exc}"


def _rss_to_items(query: str, max_results: int = 10) -> list[NewsItem]:
    """
    Parse Google News RSS into NewsItem list.
    Called in a thread pool — do not await.
    """
    try:
        params = urllib.parse.urlencode({
            "q": query, "hl": "en-US", "gl": "US", "ceid": "US:en",
        })
        req = urllib.request.Request(
            f"https://news.google.com/rss/search?{params}",
            headers={"User-Agent": "FuturesBacktestTUI/1.0 (news reader)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml = resp.read().decode("utf-8", errors="replace")

        item_blocks = re.findall(r"<item>(.+?)</item>", xml, re.DOTALL)
        items: list[NewsItem] = []
        for block in item_blocks[:max_results]:
            t = re.search(r"<title>(.+?)</title>", block)
            l = re.search(r"<link>(.+?)</link>", block)
            s = re.search(r"<source[^>]*>(.+?)</source>", block)
            d = re.search(r"<pubDate>(.+?)</pubDate>", block)
            if not t:
                continue
            items.append(NewsItem(
                title=_html_mod.unescape(t.group(1)).strip(),
                source=s.group(1).strip() if s else "Google News",
                url=l.group(1).strip() if l else "",
                timestamp=d.group(1)[:16].strip() if d else "",
            ))
        return items
    except Exception as exc:
        return [NewsItem(title=f"RSS error: {exc}", source="Google News")]


async def fetch_forex_factory_calendar() -> list[NewsItem]:
    """
    Scrape the Forex Factory economic calendar for today.
    Falls back to Google News RSS if FF blocks the request.
    """
    today_str = date.today().strftime("%b%d.%Y").lower()
    url = f"https://www.forexfactory.com/calendar?day={today_str}"
    items: list[NewsItem] = []

    try:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            follow_redirects=True,
            timeout=10.0,
        ) as client:
            resp = await client.get(url)
            html = resp.text

        events = re.findall(
            r'class="calendar__event-title[^"]*"[^>]*>\s*([^<]+?)\s*<', html
        )
        impacts = re.findall(
            r'class="calendar__impact[^"]*"[^>]*title="([^"]+)"', html
        )
        times = re.findall(
            r'class="calendar__time[^"]*"[^>]*>\s*([^<]*?)\s*<', html
        )
        currencies = re.findall(
            r'class="calendar__currency[^"]*"[^>]*>\s*([^<]+?)\s*<', html
        )

        for i, event in enumerate(events[:20]):
            event = event.strip()
            if not event:
                continue
            impact_raw = impacts[i].strip() if i < len(impacts) else ""
            if "high" in impact_raw.lower():
                impact_level = "HIGH"
            elif "medium" in impact_raw.lower() or "moderate" in impact_raw.lower():
                impact_level = "MEDIUM"
            else:
                impact_level = "LOW"

            items.append(NewsItem(
                title=event,
                source="Forex Factory",
                url=url,
                timestamp=(times[i].strip() if i < len(times) else ""),
                impact=impact_level,
                currency=(currencies[i].strip() if i < len(currencies) else ""),
            ))
    except Exception:
        pass  # fall through to RSS fallback

    # Fallback: FF blocked or returned empty HTML — use Google News RSS
    if not items:
        loop = asyncio.get_event_loop()
        items = await loop.run_in_executor(
            None, _rss_to_items, "economic calendar USD Federal Reserve today", 10
        )

    return items


async def fetch_market_headlines(topic: str = "stock market futures news") -> list[NewsItem]:
    """Fetch market headlines via Google News RSS."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _rss_to_items, topic, 8)


async def fetch_company_background(ticker_or_name: str) -> str:
    """Return a brief company/instrument background."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, web_search, f"{ticker_or_name} company news today"
    )

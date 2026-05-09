"""News fetcher — Forex Factory economic calendar + DuckDuckGo web search."""
from __future__ import annotations
import asyncio
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Optional

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
    DuckDuckGo Instant Answer search — no API key required.
    Returns formatted text suitable for the AI context.
    """
    try:
        params = urllib.parse.urlencode({
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        })
        req = urllib.request.Request(
            f"https://api.duckduckgo.com/?{params}",
            headers={"User-Agent": "FuturesBacktestTUI/1.0"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())

        parts: list[str] = []
        if data.get("Abstract"):
            parts.append(f"[{data.get('AbstractSource', 'Web')}]\n{data['Abstract']}")
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                parts.append(topic["Text"])
        if data.get("Answer"):
            parts.insert(0, f"Answer: {data['Answer']}")

        return "\n\n".join(parts[:max_results]) if parts else f"No results for: {query}"
    except Exception as exc:
        return f"Search error: {exc}"


async def fetch_forex_factory_calendar() -> list[NewsItem]:
    """Scrape the Forex Factory economic calendar for today."""
    today_str = date.today().strftime("%b%d.%Y").lower()
    url = f"https://www.forexfactory.com/calendar?day={today_str}"
    items: list[NewsItem] = []

    try:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            follow_redirects=True,
            timeout=12.0,
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
    except Exception as exc:
        items.append(NewsItem(
            title=f"FF calendar unavailable: {exc}",
            source="Forex Factory",
            impact="LOW",
        ))

    return items


async def fetch_market_headlines(topic: str = "futures markets today") -> list[NewsItem]:
    """
    Fetch general market/futures headlines via DuckDuckGo.
    Runs the sync search in a thread pool to keep the event loop free.
    """
    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, web_search, topic, 8)

    items: list[NewsItem] = []
    for chunk in raw.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        lines = chunk.splitlines()
        title = lines[0][:100]
        snippet = " ".join(lines[1:])[:200] if len(lines) > 1 else ""
        items.append(NewsItem(title=title, source="DuckDuckGo", snippet=snippet))

    return items


async def fetch_company_background(ticker_or_name: str) -> str:
    """
    Return a brief company/instrument background from DuckDuckGo.
    Intended for the AI's web_search tool call.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, web_search, f"{ticker_or_name} company overview futures trading"
    )

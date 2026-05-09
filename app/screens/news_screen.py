"""News Screen — Forex Factory calendar + market headlines."""
from __future__ import annotations
import asyncio

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import Static, Input, Button
from rich.text import Text
from rich.table import Table
from rich import box

from ..engine.news_fetcher import (
    fetch_forex_factory_calendar,
    fetch_market_headlines,
    web_search,
    NewsItem,
)

_IMPACT_COLOR = {"HIGH": "bold red", "MEDIUM": "yellow", "LOW": "dim"}
_BB_ORANGE = "#ff8c00"


class NewsHeadlines(Static):
    DEFAULT_CSS = """
    NewsHeadlines {
        height: 1fr;
        border: solid #1e3a5f;
        padding: 1 2;
        overflow-y: auto;
        background: #070d18;
    }
    """

    def set_items(self, items: list[NewsItem], title: str = "HEADLINES"):
        text = Text()
        text.append(f" {title} ", style=f"bold black on {_BB_ORANGE}")
        text.append("\n\n")
        if not items:
            text.append("Loading…", style="dim")
        else:
            for item in items:
                impact_style = _IMPACT_COLOR.get(item.impact, "")
                if item.impact:
                    text.append(f"[{item.impact}] ", style=impact_style)
                if item.currency:
                    text.append(f"{item.currency} ", style="bold #00bfff")
                if item.timestamp:
                    text.append(f"{item.timestamp}  ", style="dim")
                text.append(item.title[:90], style="bold #e8e8e8")
                if item.snippet:
                    text.append(f"\n  {item.snippet[:120]}", style="dim #aabbcc")
                text.append("\n\n")
        self.update(text)


class SearchBar(Static):
    DEFAULT_CSS = """
    SearchBar {
        height: 3;
        border: solid #1e3a5f;
        background: #0d1520;
        padding: 0 1;
    }
    """


class NewsScreen(Screen):
    """Full-screen news view: FF economic calendar + market headlines + search."""

    BINDINGS = [
        Binding("escape,n", "dismiss", "Close"),
        Binding("r", "refresh", "Refresh"),
    ]

    CSS = """
    NewsScreen {
        background: #07101e;
        layout: vertical;
    }

    #news_header {
        background: #0a1628;
        color: #ff8c00;
        text-style: bold;
        height: 3;
        padding: 1 3;
        border-bottom: solid #ff8c00;
    }

    #news_columns {
        height: 1fr;
        layout: horizontal;
    }

    #ff_panel {
        width: 1fr;
        margin-right: 1;
    }

    #hl_panel {
        width: 1fr;
    }

    #search_row {
        height: 5;
        border: solid #1e3a5f;
        background: #0d1520;
        padding: 1 2;
        layout: horizontal;
    }

    #search_input {
        width: 1fr;
        background: #0d1520;
        color: #e8e8e8;
        border: solid #1e3a5f;
    }

    #search_btn {
        width: 12;
        background: #1e3a5f;
        color: #ff8c00;
        border: solid #ff8c00;
        margin-left: 1;
    }

    #search_results {
        height: 1fr;
        border: solid #1e3a5f;
        background: #070d18;
        padding: 1 2;
        overflow-y: auto;
    }

    #news_footer {
        height: 1;
        background: #0a1628;
        color: #4a6b8a;
        padding: 0 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "  MARKET NEWS & ECONOMIC CALENDAR  "
            "   [R]=Refresh  [ESC]=Close",
            id="news_header",
        )
        with Horizontal(id="news_columns"):
            yield NewsHeadlines(id="ff_panel")
            yield NewsHeadlines(id="hl_panel")
        with Horizontal(id="search_row"):
            yield Input(
                placeholder="Search: company background, ticker, news topic…",
                id="search_input",
            )
            yield Button("SEARCH", id="search_btn", variant="default")
        yield Static("Search results will appear here.", id="search_results")
        yield Static(
            "  Forex Factory economic calendar | DuckDuckGo web search | DeepSeek AI",
            id="news_footer",
        )

    def on_mount(self):
        self.query_one("#ff_panel", NewsHeadlines).set_items([], "FOREX FACTORY — LOADING…")
        self.query_one("#hl_panel", NewsHeadlines).set_items([], "HEADLINES — LOADING…")
        self.call_later(self._load_news)

    async def _load_news(self):
        ff_items, hl_items = await asyncio.gather(
            fetch_forex_factory_calendar(),
            fetch_market_headlines("futures markets ES NQ CL today"),
        )
        self.query_one("#ff_panel", NewsHeadlines).set_items(ff_items, "FOREX FACTORY CALENDAR")
        self.query_one("#hl_panel", NewsHeadlines).set_items(hl_items, "MARKET HEADLINES")
        footer = self.query_one("#news_footer", Static)
        footer.update(
            f"  FF: {len(ff_items)} events  |  Headlines: {len(hl_items)}  "
            "|  [R]=Refresh  [ESC]=Close"
        )

    def action_refresh(self):
        self.query_one("#ff_panel", NewsHeadlines).set_items([], "REFRESHING…")
        self.query_one("#hl_panel", NewsHeadlines).set_items([], "REFRESHING…")
        self.call_later(self._load_news)

    def action_dismiss(self):
        self.dismiss()

    async def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "search_btn":
            await self._do_search()

    async def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "search_input":
            await self._do_search()

    async def _do_search(self):
        query = self.query_one("#search_input", Input).value.strip()
        if not query:
            return
        results_widget = self.query_one("#search_results", Static)
        results_widget.update(Text(f"Searching: {query}…", style="dim"))
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, web_search, query, 8)
        text = Text()
        text.append(f" SEARCH RESULTS: {query} ", style=f"bold black on {_BB_ORANGE}")
        text.append("\n\n")
        text.append(raw, style="#c8d8e8")
        results_widget.update(text)

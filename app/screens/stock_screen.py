"""Stock analysis screen — Bloomberg-style equity research panel."""
from __future__ import annotations
import asyncio
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static, TabbedContent, TabPane
from rich.text import Text
from rich.table import Table
from rich import box

from ..engine.stock_fetcher import (
    CompanyProfile,
    OptionsSnapshot,
    StockBar,
    fetch_company_profile,
    fetch_options_snapshot,
    fetch_polygon_options_history,
    fetch_stock_history,
    format_stock_for_ai,
    get_polygon_api_key,
)
from ..engine.supply_chain import (
    SupplyChainResult,
    fetch_supply_chain,
    generate_company_report,
    render_degree_panel,
    render_supply_chain,
)
from ..engine.ai_client import get_api_key
from ..engine.news_fetcher import web_search

_HEADER = "bold black on #ff8c00"
_DIM = "dim #4a6b8a"
_CYAN = "#00bfff"
_ORANGE = "#ff8c00"
_GREEN = "#00cc44"
_RED = "#ff3030"
_FG = "#c8d8e8"

_CSS = """
StockScreen {
    background: #07101e;
    color: #c8d8e8;
}
#search_bar {
    height: 3;
    background: #0a1628;
    border-bottom: solid #1e3a5f;
    padding: 0 2;
}
#search_bar > Input {
    width: 30;
    background: #070d18;
    border: solid #1e3a5f;
    color: #e8e8e8;
}
#ticker_label {
    width: auto;
    color: #ff8c00;
    text-style: bold;
    padding: 0 1;
    content-align: left middle;
}
#price_label {
    width: auto;
    color: #00bfff;
    text-style: bold;
    padding: 0 1;
    content-align: left middle;
}
TabbedContent {
    height: 1fr;
}
TabbedContent ContentSwitcher {
    height: 1fr;
}
.tab-scroll {
    height: 1fr;
    overflow-y: auto;
    padding: 1 2;
}
#chart_static {
    height: 1fr;
}
#opts_calls {
    width: 1fr;
    border-right: solid #1e3a5f;
    padding: 0 1;
    overflow-y: auto;
}
#opts_puts {
    width: 1fr;
    padding: 0 1;
    overflow-y: auto;
}
#opts_meta {
    height: 5;
    background: #0a1628;
    border-bottom: solid #1e3a5f;
    padding: 0 2;
}
#sc_graph {
    width: 2fr;
    border-right: solid #1e3a5f;
    overflow-y: auto;
    padding: 1 1;
}
#sc_sidebar {
    width: 1fr;
    padding: 1 1;
    overflow-y: auto;
}
#sc_report {
    height: 1fr;
    border-top: solid #1e3a5f;
    overflow-y: auto;
    padding: 1 2;
}
#footer_bar {
    height: 3;
    background: #0a1628;
    border-top: solid #1e3a5f;
    padding: 0 2;
}
.loading {
    color: #4a6b8a;
    text-style: italic;
}
.action-btn {
    background: #0a1628;
    border: solid #1e3a5f;
    color: #ff8c00;
    margin: 0 1;
}
.action-btn:hover {
    background: #1e3a5f;
}
"""


class SendToAIChat(Message):
    """Posted when the user wants to send stock context to the AI chat panel."""
    def __init__(self, context: str, ticker: str):
        super().__init__()
        self.context = context
        self.ticker = ticker


class StockScreen(Screen):
    """Full-screen Bloomberg-style stock analysis panel."""

    CSS = _CSS
    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("ctrl+r", "refresh_data", "Refresh"),
    ]

    def __init__(self, ticker: str = "", **kwargs):
        super().__init__(**kwargs)
        self._ticker = ticker.upper().strip()
        self._profile: CompanyProfile | None = None
        self._bars: list[StockBar] = []
        self._options: OptionsSnapshot | None = None
        self._poly_history: list[dict] = []
        self._supply_chain: SupplyChainResult | None = None
        self._company_report: str = ""
        self._ai_key = get_api_key()
        self._poly_key = get_polygon_api_key()
        self._loading_sc = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="search_bar"):
            yield Input(
                placeholder="Enter ticker (e.g. AAPL, TSLA)…",
                id="ticker_input",
                value=self._ticker,
            )
            yield Button("Search", id="search_btn", variant="primary")
            yield Label("", id="ticker_label")
            yield Label("", id="price_label")

        with TabbedContent(id="tabs"):
            with TabPane("Overview", id="tab-overview"):
                yield Static("Enter a ticker above to load data.", id="chart_static", classes="tab-scroll")

            with TabPane("Options", id="tab-options"):
                yield Static("No options data.", id="opts_meta")
                with Horizontal():
                    yield ScrollableContainer(
                        Static("Calls will appear here.", id="opts_calls_content"),
                        id="opts_calls",
                    )
                    yield ScrollableContainer(
                        Static("Puts will appear here.", id="opts_puts_content"),
                        id="opts_puts",
                    )

            with TabPane("Company", id="tab-company"):
                yield ScrollableContainer(
                    Static("Company data will appear here.", id="company_content"),
                    classes="tab-scroll",
                )

            with TabPane("Supply Chain", id="tab-supplychain"):
                with Horizontal(id="sc_top"):
                    yield ScrollableContainer(
                        Static("", id="sc_graph_content"),
                        id="sc_graph",
                    )
                    with Vertical(id="sc_sidebar"):
                        yield Static("", id="sc_degree_content")
                        yield Button("Generate Graph + Report", id="sc_generate_btn", classes="action-btn")
                yield ScrollableContainer(
                    Static("", id="sc_report_content"),
                    id="sc_report",
                )

        with Horizontal(id="footer_bar"):
            yield Button("Send to AI Chat", id="send_ai_btn", classes="action-btn")
            yield Button("Next Expiry →", id="next_expiry_btn", classes="action-btn")
            yield Button("Close [Esc]", id="close_btn", variant="default")
            yield Label("", id="status_label")

    def on_mount(self):
        self.title = "STOCK ANALYSIS"
        if self._ticker:
            self.call_later(self._load_all)

    # ── Input handling ─────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed):
        btn = event.button.id
        if btn == "search_btn":
            self._do_search()
        elif btn == "close_btn":
            self.dismiss()
        elif btn == "send_ai_btn":
            self._send_to_ai()
        elif btn == "next_expiry_btn":
            self._next_expiry()
        elif btn == "sc_generate_btn":
            if not self._loading_sc:
                self.call_later(self._load_supply_chain)

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "ticker_input":
            self._do_search()

    def _do_search(self):
        inp = self.query_one("#ticker_input", Input)
        ticker = inp.value.strip().upper()
        if not ticker:
            return
        self._ticker = ticker
        self._reset_data()
        self.call_later(self._load_all)

    def action_refresh_data(self):
        if self._ticker:
            self._reset_data()
            self.call_later(self._load_all)

    def _reset_data(self):
        self._profile = None
        self._bars = []
        self._options = None
        self._poly_history = []
        self._supply_chain = None
        self._company_report = ""
        self.query_one("#chart_static", Static).update(Text("Loading…", style=_DIM))
        self.query_one("#company_content", Static).update(Text("Loading…", style=_DIM))
        self.query_one("#opts_calls_content", Static).update(Text("Loading…", style=_DIM))
        self.query_one("#opts_puts_content", Static).update(Text("Loading…", style=_DIM))
        self.query_one("#opts_meta", Static).update(Text("Loading options…", style=_DIM))
        self.query_one("#sc_graph_content", Static).update(Text(""))
        self.query_one("#sc_degree_content", Static).update(Text(""))
        self.query_one("#sc_report_content", Static).update(Text(""))
        self._set_status("Fetching data…")

    # ── Async loaders ──────────────────────────────────────────────────────────

    async def _load_all(self):
        ticker = self._ticker
        self._set_status(f"Loading {ticker}…")

        history_task = asyncio.create_task(fetch_stock_history(ticker, "3mo"))
        profile_task = asyncio.create_task(fetch_company_profile(ticker))
        options_task = asyncio.create_task(fetch_options_snapshot(ticker, 0))

        self._bars = await history_task
        self._profile = await profile_task
        self._options = await options_task

        # Polygon historical (best-effort)
        if self._poly_key:
            self._poly_history = await fetch_polygon_options_history(ticker, self._poly_key, 30)

        self._render_overview()
        self._render_options()
        self._render_company()
        self._update_header()
        self._set_status(f"Loaded {ticker}. [Tab] to switch sections.")

    async def _load_supply_chain(self):
        if not self._profile or not self._ai_key:
            self._set_status("Need ticker data + DeepSeek API key for supply chain.")
            return
        self._loading_sc = True
        self.query_one("#sc_graph_content", Static).update(
            Text("Asking AI to map supply chain…", style="italic #4a6b8a")
        )
        self.query_one("#sc_report_content", Static).update(
            Text("Generating company report…", style="italic #4a6b8a")
        )

        sc_task = asyncio.create_task(fetch_supply_chain(
            self._ticker, self._profile.name, self._ai_key, web_search
        ))

        financials = (
            f"Market Cap: ${self._profile.market_cap:,.0f}\n"
            f"Revenue TTM: ${self._profile.revenue_ttm:,.0f}\n"
            f"Net Income: ${self._profile.net_income_ttm:,.0f}\n"
            f"P/E: {self._profile.pe_ratio:.2f}  Beta: {self._profile.beta:.2f}\n"
            f"Debt/Equity: {self._profile.debt_to_equity:.2f}  ROE: {self._profile.roe:.2f}%"
        )
        report_task = asyncio.create_task(generate_company_report(
            self._ticker,
            self._profile.name,
            self._profile.sector,
            self._profile.description,
            financials,
            self._ai_key,
            web_search,
        ))

        self._supply_chain = await sc_task
        self._company_report = await report_task

        self._render_supply_chain()
        self._loading_sc = False
        self._set_status("Supply chain + report ready. Click 'Send to AI Chat' to discuss.")

    # ── Render helpers ─────────────────────────────────────────────────────────

    def _update_header(self):
        if not self._profile:
            return
        p = self._profile
        self.query_one("#ticker_label", Label).update(
            f"  {p.ticker}  {p.name}"
        )
        color = _GREEN if p.current_price >= p.week52_low else _RED
        self.query_one("#price_label", Label).update(
            f"  ${p.current_price:.2f}"
        )

    def _render_overview(self):
        txt = Text()
        txt.append(" OVERVIEW ", style=_HEADER)

        if self._profile:
            p = self._profile
            txt.append(f"  {p.ticker} — {p.name}", style=f"bold {_CYAN}")
            txt.append(f"  [{p.sector}]", style=_DIM)
            txt.append("\n\n")

            # Key stats grid
            stats = [
                ("Price",       f"${p.current_price:.2f}"),
                ("Market Cap",  _fmt_large(p.market_cap)),
                ("P/E Ratio",   f"{p.pe_ratio:.2f}"),
                ("EPS",         f"${p.eps:.2f}"),
                ("Beta",        f"{p.beta:.2f}"),
                ("Div Yield",   f"{p.dividend_yield:.2f}%"),
                ("52W High",    f"${p.week52_high:.2f}"),
                ("52W Low",     f"${p.week52_low:.2f}"),
                ("Revenue TTM", _fmt_large(p.revenue_ttm)),
                ("Net Income",  _fmt_large(p.net_income_ttm)),
                ("Debt/Equity", f"{p.debt_to_equity:.2f}"),
                ("ROE",         f"{p.roe:.2f}%"),
                ("Employees",   f"{p.employees:,}"),
                ("Country",     p.country),
            ]
            for i, (label, val) in enumerate(stats):
                if i % 2 == 0 and i > 0:
                    txt.append("\n")
                txt.append(f"  {label:<14}", style=_DIM)
                txt.append(f"{val:<18}", style=f"bold {_FG}")
            txt.append("\n")

        # ASCII price chart
        if self._bars:
            txt.append("\n")
            txt.append(" PRICE (3 months) ", style=_HEADER)
            txt.append("\n")
            txt.append_text(_render_ascii_chart(self._bars, width=70, height=12))
        else:
            txt.append("\n  No historical data available.\n", style=_DIM)

        self.query_one("#chart_static", Static).update(txt)

    def _render_options(self):
        if not self._options:
            return
        opts = self._options
        spot = opts.spot_price

        # Meta bar
        meta = Text()
        meta.append(f"  {opts.ticker}", style=f"bold {_ORANGE}")
        meta.append(f"  Spot ${spot:.2f}", style=f"bold {_CYAN}")
        meta.append(f"  Expiry: {opts.selected_expiry}", style=_FG)
        pcr_color = _RED if opts.put_call_ratio > 1 else _GREEN
        meta.append(f"  P/C Ratio: ", style=_DIM)
        meta.append(f"{opts.put_call_ratio:.3f}", style=f"bold {pcr_color}")
        if self._poly_history:
            meta.append(f"  (Polygon {len(self._poly_history)}d trend loaded)", style=_DIM)
        self.query_one("#opts_meta", Static).update(meta)

        # Filter to strikes near ATM (±20%)
        atm_range = 0.20
        calls = [r for r in opts.calls if abs(r.strike - spot) / max(spot, 1) <= atm_range]
        puts = [r for r in opts.puts if abs(r.strike - spot) / max(spot, 1) <= atm_range]
        calls = sorted(calls, key=lambda r: r.strike)
        puts = sorted(puts, key=lambda r: r.strike)

        # Max OI for bar scaling
        max_oi_calls = max((r.open_interest for r in calls), default=1) or 1
        max_oi_puts = max((r.open_interest for r in puts), default=1) or 1

        def build_table(rows: list, label: str, max_oi: int) -> Text:
            t = Text()
            t.append(f" {label} ", style=_HEADER)
            t.append("\n")
            hdr = f"{'Strike':>8}  {'Last':>6}  {'Bid':>6}  {'Ask':>6}  {'Vol':>7}  {'OI':>8}  {'IV':>6}  OI Bar\n"
            t.append(hdr, style=_DIM)
            t.append("─" * 70 + "\n", style="dim #2a4a6a")
            for r in rows:
                is_atm = abs(r.strike - spot) == min(abs(x.strike - spot) for x in rows)
                s = "bold " + _ORANGE if is_atm else _FG
                itm_mark = "●" if r.in_the_money else " "
                bar_len = int(r.open_interest / max_oi * 12)
                bar = "█" * bar_len + "░" * (12 - bar_len)
                itm_color = _GREEN if label == "CALLS" else _RED
                t.append(f"{itm_mark}", style=itm_color)
                t.append(
                    f"{r.strike:>8.1f}  {r.last_price:>6.2f}  {r.bid:>6.2f}  "
                    f"{r.ask:>6.2f}  {r.volume:>7,}  {r.open_interest:>8,}  "
                    f"{r.implied_volatility*100:>5.1f}%  ",
                    style=s,
                )
                t.append(bar + "\n", style=f"dim {'#00884a' if label=='CALLS' else '#660000'}")
            return t

        self.query_one("#opts_calls_content", Static).update(
            build_table(calls, "CALLS", max_oi_calls)
        )
        self.query_one("#opts_puts_content", Static).update(
            build_table(puts, "PUTS", max_oi_puts)
        )

    def _render_company(self):
        if not self._profile:
            return
        p = self._profile
        txt = Text()

        txt.append(" COMPANY PROFILE ", style=_HEADER)
        txt.append(f"  {p.name}  ({p.ticker})\n\n", style=f"bold {_CYAN}")

        # Description
        txt.append(" BUSINESS DESCRIPTION ", style="bold black on #1e3a5f")
        txt.append("\n")
        # Word-wrap description
        desc = p.description
        line_len = 0
        for word in desc.split():
            if line_len + len(word) + 1 > 76:
                txt.append("\n  ")
                line_len = 2
            elif line_len == 0:
                txt.append("  ")
                line_len = 2
            else:
                txt.append(" ")
                line_len += 1
            txt.append(word, style=_FG)
            line_len += len(word)
        txt.append("\n\n")

        # Financials
        txt.append(" KEY FINANCIALS ", style="bold black on #1e3a5f")
        txt.append("\n")
        fin_rows = [
            ("Market Cap",    _fmt_large(p.market_cap)),
            ("Revenue TTM",   _fmt_large(p.revenue_ttm)),
            ("Net Income",    _fmt_large(p.net_income_ttm)),
            ("Total Debt",    _fmt_large(p.total_debt)),
            ("Total Cash",    _fmt_large(p.total_cash)),
            ("P/E Ratio",     f"{p.pe_ratio:.2f}x"),
            ("EPS",           f"${p.eps:.2f}"),
            ("ROE",           f"{p.roe:.2f}%"),
            ("Debt/Equity",   f"{p.debt_to_equity:.2f}"),
            ("Beta",          f"{p.beta:.2f}"),
            ("Dividend Yld",  f"{p.dividend_yield:.2f}%"),
            ("52W High",      f"${p.week52_high:.2f}"),
            ("52W Low",       f"${p.week52_low:.2f}"),
            ("Employees",     f"{p.employees:,}"),
            ("Country",       p.country),
            ("Industry",      p.industry),
            ("Website",       p.website),
        ]
        for label, val in fin_rows:
            txt.append(f"  {label:<16}", style=_DIM)
            txt.append(f"{val}\n", style=f"bold {_FG}")

        # Major holders
        if p.major_holders:
            txt.append("\n")
            txt.append(" MAJOR HOLDERS ", style="bold black on #1e3a5f")
            txt.append("\n")
            for h in p.major_holders:
                txt.append(f"  {h}\n", style=_FG)

        # Institutional holders
        if p.institutional_holders:
            txt.append("\n")
            txt.append(" TOP INSTITUTIONAL HOLDERS ", style="bold black on #1e3a5f")
            txt.append("\n")
            hdr = f"  {'Institution':<36} {'Shares':>12}  {'% Out':>6}  {'Value':>14}\n"
            txt.append(hdr, style=_DIM)
            txt.append("  " + "─" * 72 + "\n", style="dim #2a4a6a")
            for h in p.institutional_holders:
                pct = h.get("pct", 0) * 100
                txt.append(
                    f"  {h.get('holder', ''):<36} {h.get('shares', 0):>12,}  "
                    f"{pct:>5.2f}%  ${h.get('value', 0):>13,.0f}\n",
                    style=_FG,
                )

        self.query_one("#company_content", Static).update(txt)

    def _render_supply_chain(self):
        if not self._supply_chain:
            self.query_one("#sc_graph_content", Static).update(
                Text("Click 'Generate Graph + Report' to start AI analysis.", style=_DIM)
            )
            return

        sc = self._supply_chain
        self.query_one("#sc_graph_content", Static).update(render_supply_chain(sc.root))
        self.query_one("#sc_degree_content", Static).update(
            render_degree_panel(sc.degree_to_major, sc.summary)
        )

        if self._company_report:
            report_txt = Text()
            report_txt.append(" AI COMPANY REPORT ", style=_HEADER)
            report_txt.append("\n\n")
            report_txt.append(self._company_report, style=_FG)
            self.query_one("#sc_report_content", Static).update(report_txt)

    # ── Actions ────────────────────────────────────────────────────────────────

    def _next_expiry(self):
        if not self._options or not self._options.expiries:
            return
        current_idx = self._options.expiries.index(self._options.selected_expiry)
        next_idx = (current_idx + 1) % len(self._options.expiries)
        self._set_status(f"Loading expiry {self._options.expiries[next_idx]}…")
        asyncio.create_task(self._reload_options(next_idx))

    async def _reload_options(self, expiry_index: int):
        self._options = await fetch_options_snapshot(self._ticker, expiry_index)
        self._render_options()
        self._set_status(f"Expiry: {self._options.selected_expiry}")

    def _send_to_ai(self):
        if not self._profile:
            self._set_status("Load a ticker first.")
            return
        context = format_stock_for_ai(
            self._profile,
            self._options,
            self._poly_history,
            supply_chain_report=(
                f"Connections: {', '.join(self._supply_chain.degree_to_major.keys())}"
                if self._supply_chain else ""
            ),
            company_report=self._company_report,
        )
        self.post_message(SendToAIChat(context=context, ticker=self._ticker))
        self._set_status("Stock context sent to AI Chat panel.")

    def _set_status(self, msg: str):
        try:
            self.query_one("#status_label", Label).update(f"  {msg}")
        except Exception:
            pass


# ── ASCII chart renderer ───────────────────────────────────────────────────────

def _render_ascii_chart(bars: list[StockBar], width: int = 70, height: int = 12) -> Text:
    if not bars:
        return Text("  No data.\n", style=_DIM)

    visible = bars[-min(len(bars), width // 2):]
    prices_all = [p for b in visible for p in (b.high, b.low)]
    price_min = min(prices_all)
    price_max = max(prices_all)
    price_range = price_max - price_min or 1.0

    chart_height = height
    canvas: list[list[tuple[str, str]]] = [[(" ", "")] * width for _ in range(chart_height)]
    bar_width = max(1, min(2, width // max(len(visible), 1)))

    def p2r(p: float) -> int:
        return int((price_max - p) / price_range * (chart_height - 1))

    for i, bar in enumerate(visible):
        col = i * bar_width
        if col >= width:
            break
        is_bull = bar.close >= bar.open
        color = "#00bfff" if i == len(visible) - 1 else ("#00cc44" if is_bull else "#ff3030")
        top_r = p2r(bar.high)
        bot_r = p2r(bar.low)
        open_r = p2r(bar.open)
        close_r = p2r(bar.close)
        body_top = min(open_r, close_r)
        body_bot = max(open_r, close_r)
        for r in range(max(0, top_r), min(chart_height, bot_r + 1)):
            if col < width:
                canvas[r][col] = ("│", "#6a8fb5")
        for r in range(max(0, body_top), min(chart_height, body_bot + 1)):
            for w in range(bar_width):
                if col + w < width:
                    canvas[r][col + w] = ("█", color)

    # Y-axis labels
    result = Text()
    for i, row in enumerate(canvas):
        if i % 3 == 0:
            price_at_row = price_max - (i / (chart_height - 1)) * price_range
            result.append(f"{price_at_row:>8.2f} ", style=_DIM)
        else:
            result.append("         ", style="")
        for char, style in row:
            from rich.style import Style
            result.append(char, style=Style.parse(style) if style else Style.null())
        result.append("\n")

    # X-axis: first and last date
    if visible:
        result.append(
            f"         {visible[0].timestamp:<30}{visible[-1].timestamp:>30}\n",
            style=_DIM,
        )

    return result


def _fmt_large(val: float) -> str:
    if val == 0:
        return "N/A"
    if abs(val) >= 1e12:
        return f"${val/1e12:.2f}T"
    if abs(val) >= 1e9:
        return f"${val/1e9:.2f}B"
    if abs(val) >= 1e6:
        return f"${val/1e6:.2f}M"
    return f"${val:,.0f}"

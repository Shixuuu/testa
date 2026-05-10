"""Stock analysis screen — Bloomberg-style equity research panel."""
from __future__ import annotations
import asyncio

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static, TabbedContent, TabPane
from rich.text import Text

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
from ..widgets.stock_chart_widget import StockChartWidget

# ── Time-frame presets ─────────────────────────────────────────────────────────
# (label, yfinance period, yfinance interval, default bars_visible)
TIMEFRAMES: list[tuple[str, str, str]] = [
    ("1D",  "1d",   "5m"),
    ("5D",  "5d",   "15m"),
    ("1M",  "1mo",  "1h"),
    ("3M",  "3mo",  "1d"),
    ("6M",  "6mo",  "1d"),
    ("1Y",  "1y",   "1d"),
    ("2Y",  "2y",   "1wk"),
    ("5Y",  "5y",   "1wk"),
]
DEFAULT_TF = "3M"

_HDR = "bold black on #ff8c00"
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
    layout: vertical;
}
#search_bar {
    height: 5;
    background: #0a1628;
    border-bottom: solid #ff8c00;
    padding: 1 2;
    layout: horizontal;
}
#back_btn {
    width: 10;
    background: #0a1628;
    border: solid #1e3a5f;
    color: #4a6b8a;
    margin-right: 1;
}
#back_btn:hover {
    color: #ff8c00;
    border: solid #ff8c00;
}
#search_bar Input {
    width: 28;
    background: #070d18;
    border: solid #4a6b8a;
    color: #e8e8e8;
}
#search_bar Input:focus {
    border: solid #ff8c00;
}
#search_btn {
    margin-left: 1;
    min-width: 10;
    background: #1e3a5f;
    border: solid #ff8c00;
    color: #ff8c00;
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
#search_hint {
    width: 1fr;
    content-align: right middle;
    color: #2a4a6a;
    padding: 0 1;
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
#overview_stats {
    height: auto;
    max-height: 8;
    background: #0a1628;
    border-bottom: solid #1e3a5f;
    padding: 0 2;
    overflow: hidden;
}
#tf_bar {
    height: 3;
    background: #0a1628;
    border-bottom: solid #1e3a5f;
    padding: 0 1;
}
.tf-btn {
    background: #070d18;
    border: solid #1e3a5f;
    color: #4a6b8a;
    margin: 0 0;
    min-width: 5;
}
.tf-btn:hover {
    background: #0d2040;
    color: #00bfff;
}
.tf-btn.-active {
    background: #0a2040;
    border: solid #ff8c00;
    color: #ff8c00;
    text-style: bold;
}
#opts_meta {
    height: 4;
    background: #0a1628;
    border-bottom: solid #1e3a5f;
    padding: 0 2;
}
#opts_body {
    height: 1fr;
    layout: horizontal;
}
#opts_calls {
    width: 1fr;
    border-right: solid #1e3a5f;
    overflow-y: auto;
    padding: 0 1;
}
#opts_puts {
    width: 1fr;
    overflow-y: auto;
    padding: 0 1;
}
#sc_top {
    height: 2fr;
    layout: horizontal;
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
    height: 3fr;
    border-top: solid #1e3a5f;
    overflow-y: auto;
    padding: 1 2;
}
#footer_bar {
    height: 3;
    background: #0a1628;
    border-top: solid #1e3a5f;
    padding: 0 2;
    layout: horizontal;
}
#status_label {
    width: 1fr;
    content-align: left middle;
    color: #4a6b8a;
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
        Binding("escape", "go_back",      "← Back",    priority=True),
        Binding("ctrl+r", "refresh_data", "Refresh",   priority=True),
        Binding("equals", "zoom_in",      "Zoom In"),
        Binding("minus",  "zoom_out",     "Zoom Out"),
        Binding("ctrl+home", "jump_start", "⇤ Start"),
        Binding("ctrl+end",  "jump_end",   "End ⇥"),
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
        self._current_tf = DEFAULT_TF
        self._expiry_index = 0

    # ── Compose ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        # ── Search bar ──
        with Horizontal(id="search_bar"):
            yield Button("← Back", id="back_btn")
            yield Input(
                placeholder="Enter ticker (AAPL, TSLA, SPY…)",
                id="ticker_input",
                value=self._ticker,
            )
            yield Button("SEARCH", id="search_btn")
            yield Label("", id="ticker_label")
            yield Label("", id="price_label")
            yield Label("[ESC] back  [Ctrl+R] refresh  [scroll] zoom  [drag] pan",
                        id="search_hint")

        with TabbedContent(id="tabs"):
            # ── Overview ──
            with TabPane("Overview", id="tab-overview"):
                yield Static("", id="overview_stats")
                with Horizontal(id="tf_bar"):
                    for label, _period, _interval in TIMEFRAMES:
                        active = "-active" if label == self._current_tf else ""
                        yield Button(label, id=f"tf_{label}", classes=f"tf-btn{' -active' if active else ''}")
                    yield Label("  scroll=zoom  drag=pan  =/- keys", id="chart_hint",
                                classes="", markup=False)
                yield StockChartWidget(id="stock_chart")

            # ── Options ──
            with TabPane("Options", id="tab-options"):
                yield Static("No options data.", id="opts_meta")
                with Container(id="opts_body"):
                    yield ScrollableContainer(
                        Static("", id="opts_calls_content"),
                        id="opts_calls",
                    )
                    yield ScrollableContainer(
                        Static("", id="opts_puts_content"),
                        id="opts_puts",
                    )

            # ── Company ──
            with TabPane("Company", id="tab-company"):
                yield ScrollableContainer(
                    Static("Enter a ticker to load company data.", id="company_content"),
                    classes="tab-scroll",
                )

            # ── Supply Chain ──
            with TabPane("Supply Chain", id="tab-supplychain"):
                with Horizontal(id="sc_top"):
                    yield ScrollableContainer(
                        Static("", id="sc_graph_content"),
                        id="sc_graph",
                    )
                    with Vertical(id="sc_sidebar"):
                        yield Static("", id="sc_degree_content")
                        yield Button(
                            "Generate Graph + Report [AI]",
                            id="sc_generate_btn",
                            classes="action-btn",
                        )
                yield ScrollableContainer(
                    Static("", id="sc_report_content"),
                    id="sc_report",
                )

        # ── Footer ──
        with Horizontal(id="footer_bar"):
            yield Button("Send to AI Chat", id="send_ai_btn", classes="action-btn")
            yield Button("Next Expiry →",   id="next_expiry_btn", classes="action-btn")
            yield Button("Close [Esc]",     id="close_btn", variant="default")
            yield Label("", id="status_label")

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def on_mount(self):
        self.title = "STOCK ANALYSIS"
        if self._ticker:
            self.call_later(self._load_all)

    # ── Input handling ─────────────────────────────────────────────────────────

    def action_go_back(self) -> None:
        self.dismiss()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "search_btn":
            self._do_search()
        elif bid in ("close_btn", "back_btn"):
            self.dismiss()
        elif bid == "send_ai_btn":
            self._send_to_ai()
        elif bid == "next_expiry_btn":
            self._next_expiry()
        elif bid == "sc_generate_btn":
            if not self._loading_sc:
                self.call_later(self._load_supply_chain)
        elif bid.startswith("tf_"):
            label = bid[3:]
            self._set_timeframe(label)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "ticker_input":
            self._do_search()

    # ── Key actions ────────────────────────────────────────────────────────────

    def action_zoom_in(self):
        try:
            self.query_one("#stock_chart", StockChartWidget).zoom_in()
        except Exception:
            pass

    def action_zoom_out(self):
        try:
            self.query_one("#stock_chart", StockChartWidget).zoom_out()
        except Exception:
            pass

    def action_jump_start(self):
        try:
            self.query_one("#stock_chart", StockChartWidget).jump_to_start()
        except Exception:
            pass

    def action_jump_end(self):
        try:
            self.query_one("#stock_chart", StockChartWidget).jump_to_end()
        except Exception:
            pass

    def action_refresh_data(self):
        if self._ticker:
            self._reset_data()
            self.call_later(self._load_all)

    # ── Internal: search / timeframe ───────────────────────────────────────────

    def _do_search(self):
        inp = self.query_one("#ticker_input", Input)
        ticker = inp.value.strip().upper()
        if not ticker:
            return
        self._ticker = ticker
        self._reset_data()
        self.call_later(self._load_all)

    def _set_timeframe(self, label: str):
        if label == self._current_tf or not self._ticker:
            return
        # Update button styles
        for tf_label, _, _ in TIMEFRAMES:
            try:
                btn = self.query_one(f"#tf_{tf_label}", Button)
                if tf_label == label:
                    btn.add_class("-active")
                else:
                    btn.remove_class("-active")
            except Exception:
                pass
        self._current_tf = label
        self.call_later(self._reload_chart_for_tf)

    async def _reload_chart_for_tf(self):
        tf_def = {lbl: (p, iv) for lbl, p, iv in TIMEFRAMES}
        period, interval = tf_def.get(self._current_tf, ("3mo", "1d"))
        self._set_status(f"Loading {self._ticker} {self._current_tf}…")
        self._bars = await fetch_stock_history(self._ticker, period, interval)
        chart = self.query_one("#stock_chart", StockChartWidget)
        chart.set_bars(self._bars, self._current_tf)
        self._set_status(f"{self._ticker} {self._current_tf} — {len(self._bars)} bars loaded.")

    def _reset_data(self):
        self._profile = None
        self._bars = []
        self._options = None
        self._poly_history = []
        self._supply_chain = None
        self._company_report = ""
        self._expiry_index = 0
        try:
            self.query_one("#stock_chart", StockChartWidget).set_bars([], "")
            self.query_one("#overview_stats", Static).update("")
            self.query_one("#company_content", Static).update(Text("Loading…", style=_DIM))
            self.query_one("#opts_calls_content", Static).update(Text("Loading…", style=_DIM))
            self.query_one("#opts_puts_content", Static).update(Text("Loading…", style=_DIM))
            self.query_one("#opts_meta", Static).update(Text("Loading options…", style=_DIM))
            self.query_one("#sc_graph_content", Static).update(Text(""))
            self.query_one("#sc_degree_content", Static).update(Text(""))
            self.query_one("#sc_report_content", Static).update(Text(""))
        except Exception:
            pass
        self._set_status("Fetching data…")

    # ── Async loaders ──────────────────────────────────────────────────────────

    async def _load_all(self):
        ticker = self._ticker
        self._set_status(f"Loading {ticker}…")

        tf_def = {lbl: (p, iv) for lbl, p, iv in TIMEFRAMES}
        period, interval = tf_def.get(self._current_tf, ("3mo", "1d"))

        history_task = asyncio.create_task(fetch_stock_history(ticker, period, interval))
        profile_task = asyncio.create_task(fetch_company_profile(ticker))
        options_task = asyncio.create_task(fetch_options_snapshot(ticker, 0))

        self._bars = await history_task
        self._profile = await profile_task
        self._options = await options_task

        if self._poly_key:
            self._poly_history = await fetch_polygon_options_history(ticker, self._poly_key, 30)

        self._render_overview()
        self._render_options()
        self._render_company()
        self._update_header()

        # Activate default TF button
        try:
            self.query_one(f"#tf_{self._current_tf}", Button).add_class("-active")
        except Exception:
            pass

        self._set_status(
            f"{ticker} loaded — {len(self._bars)} bars | "
            f"scroll=zoom  drag=pan  [=/−]=keys  Ctrl+Home/End=jump"
        )

    async def _load_supply_chain(self):
        if not self._profile or not self._ai_key:
            self._set_status("Need ticker data + DeepSeek API key for supply chain.")
            return
        self._loading_sc = True
        self.query_one("#sc_graph_content", Static).update(
            Text("AI mapping supply chain… (web search in progress)", style="italic #4a6b8a")
        )
        self.query_one("#sc_report_content", Static).update(
            Text("Generating equity research report…", style="italic #4a6b8a")
        )

        p = self._profile
        financials = (
            f"Market Cap: {_fmt_large(p.market_cap)}\n"
            f"Revenue TTM: {_fmt_large(p.revenue_ttm)}\n"
            f"Net Income: {_fmt_large(p.net_income_ttm)}\n"
            f"P/E: {p.pe_ratio:.2f}  Beta: {p.beta:.2f}\n"
            f"Debt/Equity: {p.debt_to_equity:.2f}  ROE: {p.roe:.2f}%"
        )

        sc_task = asyncio.create_task(fetch_supply_chain(
            self._ticker, p.name, self._ai_key, web_search
        ))
        report_task = asyncio.create_task(generate_company_report(
            self._ticker, p.name, p.sector,
            p.description, financials, self._ai_key, web_search,
        ))

        self._supply_chain = await sc_task
        self._company_report = await report_task

        self._render_supply_chain()
        self._loading_sc = False
        self._set_status("Supply chain + report ready. 'Send to AI Chat' to discuss.")

    # ── Renderers ──────────────────────────────────────────────────────────────

    def _update_header(self):
        if not self._profile:
            return
        p = self._profile
        self.query_one("#ticker_label", Label).update(f"  {p.ticker}  {p.name}")
        self.query_one("#price_label", Label).update(f"  ${p.current_price:.2f}")

    def _render_overview(self):
        if not self._profile:
            return
        p = self._profile

        # Stats strip (compact, 2-column)
        stats = Text()
        stats.append(" OVERVIEW ", style=_HDR)
        stats.append(f"  {p.ticker} — {p.name}", style=f"bold {_CYAN}")
        stats.append(f"  {p.sector}", style=_DIM)
        stats.append("\n")
        kvs = [
            ("Price",    f"${p.current_price:.2f}"),
            ("Mkt Cap",  _fmt_large(p.market_cap)),
            ("P/E",      f"{p.pe_ratio:.2f}"),
            ("EPS",      f"${p.eps:.2f}"),
            ("Beta",     f"{p.beta:.2f}"),
            ("Div%",     f"{p.dividend_yield:.2f}%"),
            ("52W H",    f"${p.week52_high:.2f}"),
            ("52W L",    f"${p.week52_low:.2f}"),
            ("Rev TTM",  _fmt_large(p.revenue_ttm)),
            ("Net Inc",  _fmt_large(p.net_income_ttm)),
            ("D/E",      f"{p.debt_to_equity:.2f}"),
            ("ROE",      f"{p.roe:.2f}%"),
        ]
        cols = 6
        for i, (label, val) in enumerate(kvs):
            if i % cols == 0 and i > 0:
                stats.append("\n")
            stats.append(f"  {label:<8}", style=_DIM)
            stats.append(f"{val:<12}", style=f"bold {_FG}")
        self.query_one("#overview_stats", Static).update(stats)

        # Chart
        chart = self.query_one("#stock_chart", StockChartWidget)
        chart.set_bars(self._bars, self._current_tf)

    def _render_options(self):
        if not self._options:
            return
        opts = self._options
        spot = opts.spot_price

        meta = Text()
        meta.append(f"  {opts.ticker}", style=f"bold {_ORANGE}")
        meta.append(f"  Spot ${spot:.2f}", style=f"bold {_CYAN}")
        meta.append(f"  Expiry: {opts.selected_expiry}", style=_FG)
        meta.append(f"  {len(opts.expiries)} expiries available", style=_DIM)
        pcr_c = _RED if opts.put_call_ratio > 1 else _GREEN
        meta.append(f"  P/C Ratio: ", style=_DIM)
        meta.append(f"{opts.put_call_ratio:.3f}", style=f"bold {pcr_c}")
        if self._poly_history:
            meta.append(f"  Polygon {len(self._poly_history)}d trend ✓", style=_DIM)
        self.query_one("#opts_meta", Static).update(meta)

        atm_range = 0.25
        calls = sorted(
            [r for r in opts.calls if abs(r.strike - spot) / max(spot, 1) <= atm_range],
            key=lambda r: r.strike,
        )
        puts = sorted(
            [r for r in opts.puts if abs(r.strike - spot) / max(spot, 1) <= atm_range],
            key=lambda r: r.strike,
        )
        max_oi_c = max((r.open_interest for r in calls), default=1) or 1
        max_oi_p = max((r.open_interest for r in puts), default=1) or 1

        def build_table(rows, label: str, max_oi: int) -> Text:
            t = Text()
            t.append(f" {label} ", style=_HDR)
            t.append("\n")
            t.append(
                f"{'':1}{'Strike':>7}  {'Last':>6}  {'Bid':>6}  {'Ask':>6}"
                f"  {'Vol':>7}  {'OI':>8}  {'IV':>6}  OI Bar\n",
                style=_DIM,
            )
            t.append("─" * 66 + "\n", style="dim #1e3a5f")
            atm_strike = min(rows, key=lambda r: abs(r.strike - spot)).strike if rows else None
            for r in rows:
                is_atm = (r.strike == atm_strike)
                s = f"bold {_ORANGE}" if is_atm else _FG
                itm = "●" if r.in_the_money else " "
                itm_c = _GREEN if label == "CALLS" else _RED
                bar_len = int(r.open_interest / max_oi * 14)
                bar = "█" * bar_len + "░" * (14 - bar_len)
                t.append(itm, style=itm_c)
                t.append(
                    f"{r.strike:>7.1f}  {r.last_price:>6.2f}  {r.bid:>6.2f}  {r.ask:>6.2f}"
                    f"  {r.volume:>7,}  {r.open_interest:>8,}  {r.implied_volatility*100:>5.1f}%  ",
                    style=s,
                )
                bc = "#00884a" if label == "CALLS" else "#661122"
                t.append(bar + "\n", style=f"dim {bc}")
            return t

        self.query_one("#opts_calls_content", Static).update(build_table(calls, "CALLS", max_oi_c))
        self.query_one("#opts_puts_content", Static).update(build_table(puts, "PUTS", max_oi_p))

    def _render_company(self):
        if not self._profile:
            return
        p = self._profile
        txt = Text()

        txt.append(" COMPANY PROFILE ", style=_HDR)
        txt.append(f"  {p.name}  ({p.ticker})\n\n", style=f"bold {_CYAN}")

        txt.append(" BUSINESS DESCRIPTION ", style="bold black on #1e3a5f")
        txt.append("\n")
        line_len = 0
        for word in p.description.split():
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

        txt.append(" KEY FINANCIALS ", style="bold black on #1e3a5f")
        txt.append("\n")
        for label, val in [
            ("Market Cap",   _fmt_large(p.market_cap)),
            ("Revenue TTM",  _fmt_large(p.revenue_ttm)),
            ("Net Income",   _fmt_large(p.net_income_ttm)),
            ("Total Debt",   _fmt_large(p.total_debt)),
            ("Total Cash",   _fmt_large(p.total_cash)),
            ("P/E Ratio",    f"{p.pe_ratio:.2f}x"),
            ("EPS",          f"${p.eps:.2f}"),
            ("ROE",          f"{p.roe:.2f}%"),
            ("Debt/Equity",  f"{p.debt_to_equity:.2f}"),
            ("Beta",         f"{p.beta:.2f}"),
            ("Div Yield",    f"{p.dividend_yield:.2f}%"),
            ("52W High",     f"${p.week52_high:.2f}"),
            ("52W Low",      f"${p.week52_low:.2f}"),
            ("Employees",    f"{p.employees:,}"),
            ("Country",      p.country),
            ("Industry",     p.industry),
            ("Website",      p.website),
        ]:
            txt.append(f"  {label:<16}", style=_DIM)
            txt.append(f"{val}\n", style=f"bold {_FG}")

        if p.major_holders:
            txt.append("\n")
            txt.append(" MAJOR HOLDERS ", style="bold black on #1e3a5f")
            txt.append("\n")
            for h in p.major_holders:
                txt.append(f"  {h}\n", style=_FG)

        if p.institutional_holders:
            txt.append("\n")
            txt.append(" TOP INSTITUTIONAL HOLDERS ", style="bold black on #1e3a5f")
            txt.append("\n")
            txt.append(
                f"  {'Institution':<36} {'Shares':>12}  {'% Out':>6}  {'Value':>14}\n",
                style=_DIM,
            )
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
            rt = Text()
            rt.append(" AI EQUITY RESEARCH REPORT ", style=_HDR)
            rt.append("\n\n")
            rt.append(self._company_report, style=_FG)
            self.query_one("#sc_report_content", Static).update(rt)

    # ── Footer actions ─────────────────────────────────────────────────────────

    def _next_expiry(self):
        if not self._options or not self._options.expiries:
            return
        self._expiry_index = (self._expiry_index + 1) % len(self._options.expiries)
        self._set_status(f"Loading expiry {self._options.expiries[self._expiry_index]}…")
        asyncio.create_task(self._reload_options())

    async def _reload_options(self):
        self._options = await fetch_options_snapshot(self._ticker, self._expiry_index)
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
                f"Supply chain nodes: {', '.join(self._supply_chain.degree_to_major.keys())}"
                if self._supply_chain else ""
            ),
            company_report=self._company_report,
        )
        self.post_message(SendToAIChat(context=context, ticker=self._ticker))
        self._set_status("Context sent to AI Chat panel.")

    def _set_status(self, msg: str):
        try:
            self.query_one("#status_label", Label).update(f"  {msg}")
        except Exception:
            pass


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fmt_large(val: float) -> str:
    if val == 0:
        return "N/A"
    if abs(val) >= 1e12:
        return f"${val / 1e12:.2f}T"
    if abs(val) >= 1e9:
        return f"${val / 1e9:.2f}B"
    if abs(val) >= 1e6:
        return f"${val / 1e6:.2f}M"
    return f"${val:,.0f}"

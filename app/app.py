"""
Futures Backtest TUI — Bloomberg-terminal-style main application.

Layout:
  [LEFT 22ch][   CHART / TPO          ][AI CHAT 42ch (toggle)]
  [         ][   TRADE LOG             ][                      ]
  [         ][   STATS PANEL           ][                      ]
  [STATUS BAR — full width                                     ]

New hotkeys vs v1:
  T  — toggle Candle ↔ TPO chart
  \  — toggle AI chat panel
  N  — open News & Calendar screen
  Ctrl+K — set DeepSeek API key
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static, Footer, Header
from textual.reactive import reactive

from .engine.backtrader_runner import BacktraderRunner
from .engine.replay_controller import ReplayController, ReplayState
from .engine.prop_rules import PropFirmProfile, PropRulesEngine
from .engine.events import BarEvent, TradeEvent, OrderEvent, RunCompleteEvent
from .engine.analytics import compute_analytics, AnalyticsReport
from .engine.instruments import get_instrument
from .engine.ai_client import get_api_key

from .widgets.chart_widget import CandlestickChart
from .widgets.trade_log import TradeLog
from .widgets.stats_panel import StatsPanel
from .widgets.prop_rules_panel import PropRulesPanel
from .widgets.strategy_panel import StrategyPanel
from .widgets.position_panel import PositionPanel
from .widgets.status_bar import StatusBar
from .widgets.ai_chat_panel import AIChatPanel

from .screens.hotkey_help import HotkeyHelp
from .screens.data_manager import DataManager, DataLoaded
from .screens.strategy_editor import StrategyEditor, StrategySelected
from .screens.prop_firm_config import PropFirmConfig, PropProfileSelected
from .screens.monte_carlo_view import MonteCarloView
from .screens.analytics_report import AnalyticsReportScreen
from .screens.news_screen import NewsScreen
from .screens.stock_screen import StockScreen, SendToAIChat

FIRM_PROFILES_DIR = Path(__file__).parent.parent / "firm_profiles"
DEMO_DATA = Path(__file__).parent.parent / "data" / "demo" / "es_demo_5m.csv"
DEMO_STRATEGY = Path(__file__).parent.parent / "strategies" / "sma_cross.py"

# ── Bloomberg terminal colour palette ──────────────────────────────────────────
_BB_CSS = """
/* ── Global ──────────────────────────────────────────── */
Screen {
    background: #07101e;
    color: #c8d8e8;
    layout: horizontal;
}

/* ── Left sidebar ────────────────────────────────────── */
#left_col {
    width: 22;
    layout: vertical;
    border-right: solid #1e3a5f;
    background: #070d18;
}

#strategy_panel {
    height: 1fr;
    border-bottom: solid #1e3a5f;
}

#position_panel {
    height: auto;
    max-height: 10;
    border-bottom: solid #1e3a5f;
}

#prop_rules_panel {
    height: 1fr;
}

/* ── Centre column ────────────────────────────────────── */
#centre_col {
    width: 1fr;
    layout: vertical;
}

#chart_panel {
    height: 2fr;
    border-bottom: solid #1e3a5f;
}

#trade_log_panel {
    height: 1fr;
    border-bottom: solid #1e3a5f;
}

#stats_panel {
    height: 1fr;
}

/* ── AI Chat panel (right sidebar — toggled) ─────────── */
AIChatPanel {
    width: 42;
    display: none;
    border-left: solid #ff8c00;
}

AIChatPanel.visible {
    display: block;
}

/* ── Status bar ──────────────────────────────────────── */
#status_bar {
    dock: bottom;
    height: 1;
    background: #0a1628;
    color: #6a8fb5;
}

/* ── Shared panel chrome ─────────────────────────────── */
StrategyPanel, PositionPanel, PropRulesPanel {
    background: #070d18;
    border: none;
}

StatsPanel {
    background: #070d18;
    border: none;
    padding: 0 1;
    overflow-y: auto;
}

TradeLog {
    background: #070d18;
    border: none;
}

/* ── Warning / breach CSS classes used by PropRulesPanel */
.warning {
    border: solid #ffcc00;
}
.breach {
    border: solid #ff3030;
}
"""


class FuturesBacktestTUI(App):
    """Futures Backtest TUI — Bloomberg-terminal-style platform."""

    CSS = _BB_CSS

    BINDINGS = [
        Binding("space", "toggle_play", "Play/Pause", priority=True),
        Binding("right", "step_forward", "Step →", priority=True),
        Binding("]", "step_forward", "Step →", priority=True),
        Binding("left", "step_backward", "Step ←", priority=True),
        Binding("[", "step_backward", "Step ←", priority=True),
        Binding("f", "speed_5x", "5×"),
        Binding("F", "speed_25x", "25×"),
        Binding("m", "speed_max", "Max"),
        Binding("r", "reset", "Reset"),
        Binding("t", "toggle_chart", "Candle/TPO"),
        Binding("backslash", "toggle_ai", "AI Chat"),
        Binding("n", "open_news", "News"),
        Binding("k", "open_stock", "Stock Lookup"),
        Binding("s", "open_strategy", "Strategy"),
        Binding("d", "open_data", "Data"),
        Binding("p", "open_prop", "Prop Firm"),
        Binding("a", "open_analytics", "Analytics"),
        Binding("c", "open_mc", "Monte Carlo"),
        Binding("e", "export", "Export"),
        Binding("i", "toggle_indicators", "Indicators"),
        Binding("question_mark", "show_help", "Help"),
        Binding("q", "quit", "Quit"),
        Binding("tab", "focus_next", "Focus"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._runner: BacktraderRunner | None = None
        self._controller: ReplayController | None = None
        self._prop_engine: PropRulesEngine | None = None
        self._prop_profile: PropFirmProfile | None = None
        self._prop_enabled: bool = False

        self._data_path: str = str(DEMO_DATA)
        self._strategy_path: str = str(DEMO_STRATEGY)
        self._instrument: str = "ES"
        self._initial_cash: float = 50000.0

        self._closed_trades: list[TradeEvent] = []
        self._equity_curve: list[tuple[int, float]] = [(0, 50000.0)]
        self._n_trades: int = 0
        self._net_pnl: float = 0.0
        self._win_count: int = 0
        self._mc_result = None
        self._current_bar: BarEvent | None = None

    # ------------------------------------------------------------------ #
    # Compose                                                              #
    # ------------------------------------------------------------------ #

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="left_col"):
            yield StrategyPanel(id="strategy_panel")
            yield PositionPanel(id="position_panel")
            yield PropRulesPanel(id="prop_rules_panel")
        with Container(id="centre_col"):
            yield CandlestickChart(id="chart_panel")
            yield TradeLog(id="trade_log_panel")
            yield StatsPanel(id="stats_panel")
        yield AIChatPanel(state_provider=self._build_ai_state, id="ai_chat_panel")
        yield StatusBar(id="status_bar")

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def on_mount(self):
        self.title = "FUTURES BACKTEST TUI"
        self.sub_title = "Bloomberg Terminal Edition v2.0"

        apex_path = FIRM_PROFILES_DIR / "apex_50k.toml"
        if apex_path.exists():
            try:
                self._prop_profile = PropFirmProfile.from_toml(str(apex_path))
                self._prop_engine = PropRulesEngine(self._prop_profile)
                self._prop_enabled = True
                self.query_one("#prop_rules_panel", PropRulesPanel).set_profile(self._prop_profile)
            except Exception:
                pass

        status = self.query_one("#status_bar", StatusBar)
        status.firm_name = self._prop_profile.name if self._prop_profile else "—"
        status.message = (
            "D=Data  S=Strategy  Space=Play  T=TPO  \\=AI Chat  N=News  K=Stock  ?=Help"
        )

        strat_panel = self.query_one("#strategy_panel", StrategyPanel)
        strat_panel.set_strategy("SMA Crossover", {"fast": 10, "slow": 30}, ["SMA(10)", "SMA(30)"])
        strat_panel.set_data_info(Path(self._data_path).name, self._instrument)

        if DEMO_DATA.exists():
            self.call_later(self._start_replay)

    # ------------------------------------------------------------------ #
    # Actions                                                              #
    # ------------------------------------------------------------------ #

    def action_toggle_play(self):
        if not self._controller:
            self.call_later(self._start_replay)
            return
        if self._controller.state.speed == 0:
            self._controller.play(speed=1)
            self.query_one("#status_bar", StatusBar).speed = 1
        else:
            self._controller.pause()
            self.query_one("#status_bar", StatusBar).speed = 0

    def action_step_forward(self):
        if not self._controller:
            return
        self._controller.pause()
        self._controller.step_forward()

    def action_step_backward(self):
        if self._controller:
            self._controller.step_backward()

    def action_speed_5x(self):
        if self._controller:
            self._controller.play(speed=5)
            self.query_one("#status_bar", StatusBar).speed = 5

    def action_speed_25x(self):
        if self._controller:
            self._controller.play(speed=25)
            self.query_one("#status_bar", StatusBar).speed = 25

    def action_speed_max(self):
        if self._controller:
            self._controller.play(speed=999)
            self.query_one("#status_bar", StatusBar).speed = 999

    def action_reset(self):
        self._reset_state()
        self.call_later(self._start_replay)

    def action_toggle_chart(self):
        chart = self.query_one("#chart_panel", CandlestickChart)
        chart.toggle_chart_mode()
        mode = chart.chart_mode.upper()
        self.query_one("#status_bar", StatusBar).message = f"Chart mode: {mode}"

    def action_toggle_ai(self):
        panel = self.query_one("#ai_chat_panel", AIChatPanel)
        panel.toggle()
        status = "OPEN" if panel.is_open else "CLOSED"
        self.query_one("#status_bar", StatusBar).message = f"AI Chat panel {status}"

    def action_open_news(self):
        self.push_screen(NewsScreen())

    def action_open_stock(self):
        self.push_screen(StockScreen())

    def action_open_data(self):
        self.push_screen(DataManager(default_dir=str(DEMO_DATA.parent)))

    def action_open_strategy(self):
        self.push_screen(StrategyEditor(strategies_dir=str(DEMO_STRATEGY.parent)))

    def action_open_prop(self):
        self.push_screen(PropFirmConfig(profile_dir=str(FIRM_PROFILES_DIR)))

    def action_open_analytics(self):
        self.push_screen(AnalyticsReportScreen(
            self._closed_trades,
            self._equity_curve,
            self._initial_cash,
        ))

    def action_open_mc(self):
        self.push_screen(MonteCarloView(
            self._closed_trades,
            self._initial_cash,
            self._prop_profile,
        ))

    def action_export(self):
        self.action_open_analytics()

    def action_toggle_indicators(self):
        chart = self.query_one("#chart_panel", CandlestickChart)
        chart.show_indicators = not chart.show_indicators

    def action_show_help(self):
        self.push_screen(HotkeyHelp())

    # ------------------------------------------------------------------ #
    # Screen messages                                                      #
    # ------------------------------------------------------------------ #

    def on_data_loaded(self, msg: DataLoaded):
        self._data_path = msg.data_path
        self._instrument = msg.instrument
        self._initial_cash = msg.initial_cash
        self.query_one("#strategy_panel", StrategyPanel).set_data_info(
            Path(self._data_path).name, self._instrument
        )
        self._reset_state()
        self.call_later(self._start_replay)

    def on_strategy_selected(self, msg: StrategySelected):
        self._strategy_path = msg.path
        name = Path(msg.path).stem.replace("_", " ").title()
        self.query_one("#strategy_panel", StrategyPanel).set_strategy(name, {})
        self._reset_state()
        self.call_later(self._start_replay)

    def on_send_to_ai_chat(self, msg: SendToAIChat):
        """Receive stock context from StockScreen and inject into AI chat."""
        panel = self.query_one("#ai_chat_panel", AIChatPanel)
        panel.inject_stock_context(msg.ticker, msg.context)
        if not panel.is_open:
            panel.toggle()
        self.pop_screen()

    def on_prop_profile_selected(self, msg: PropProfileSelected):
        self._prop_profile = msg.profile
        self._prop_enabled = msg.enabled
        self._prop_engine = PropRulesEngine(msg.profile) if msg.enabled else None
        self.query_one("#prop_rules_panel", PropRulesPanel).set_profile(msg.profile)
        self.query_one("#status_bar", StatusBar).firm_name = (
            msg.profile.name if msg.enabled else "—"
        )
        self.notify(f"Prop profile: {msg.profile.name} ({'ON' if msg.enabled else 'OFF'})")

    # ------------------------------------------------------------------ #
    # AI state builder                                                     #
    # ------------------------------------------------------------------ #

    def _build_ai_state(self) -> dict:
        """Snapshot all live app data for the AI context block."""
        state: dict = {
            "instrument": self._instrument,
            "initial_cash": self._initial_cash,
            "bar_index": self._controller.state.bar_index if self._controller else 0,
            "total_bars": self._controller.state.total_bars if self._controller else 0,
        }

        if self._current_bar:
            b = self._current_bar
            state["current_bar"] = {
                "open": b.open, "high": b.high, "low": b.low, "close": b.close,
            }

        # Analytics snapshot
        wr = self._win_count / self._n_trades if self._n_trades else 0
        wins_pnl = sum((t.pnl or 0) - t.commission for t in self._closed_trades if (t.pnl or 0) > t.commission)
        loss_pnl = abs(sum((t.pnl or 0) - t.commission for t in self._closed_trades if (t.pnl or 0) - t.commission < 0)) or 1e-9
        pf = wins_pnl / loss_pnl
        state["analytics"] = {
            "Net P&L": f"${self._net_pnl:+,.2f}",
            "Trades": str(self._n_trades),
            "Win Rate": f"{wr*100:.1f}%",
            "Profit Factor": f"{pf:.2f}",
            "Expectancy": f"${self._net_pnl / max(self._n_trades, 1):,.2f}",
        }

        # Prop firm
        if self._prop_engine and self._prop_enabled and self._prop_profile:
            ps = self._prop_engine.state
            daily_pnl = sum(ps.daily_pnl.values()) if ps.daily_pnl else 0
            state["prop"] = {
                "name": self._prop_profile.name,
                "is_breached": ps.is_breached,
                "breach_rule": ps.breach_rule or "",
                "daily_pnl": daily_pnl,
                "daily_limit": self._prop_profile.daily_loss_limit or 0,
                "trailing_floor": ps.trailing_floor,
                "peak_equity": ps.peak_equity,
                "net_pnl": self._net_pnl,
                "profit_target": self._prop_profile.profit_target or 0,
            }

        # Monte Carlo summary
        if self._mc_result:
            mc = self._mc_result
            state["monte_carlo"] = {
                "method": mc.method,
                "n_paths": mc.n_paths,
                "median_final": mc.median_final,
                "pct5_final": mc.pct5_final,
                "pct95_final": mc.pct95_final,
                "prob_ruin": mc.prob_ruin,
                "prob_target": mc.prob_target,
                "pass_rate": mc.pass_rate if mc.pass_rate else None,
            }

        # Recent trades (last 10)
        recent = self._closed_trades[-10:]
        state["recent_trades"] = [
            {
                "id": t.trade_id or i,
                "direction": t.direction,
                "entry": t.entry_price,
                "exit": t.exit_price or t.entry_price,
                "pnl": (t.pnl or 0) - t.commission,
            }
            for i, t in enumerate(recent)
        ]

        return state

    # ------------------------------------------------------------------ #
    # Replay engine                                                        #
    # ------------------------------------------------------------------ #

    async def _start_replay(self):
        if not Path(self._data_path).exists():
            self.notify(f"Data file not found: {self._data_path}", severity="error")
            return
        self._reset_state()

        if self._controller:
            await self._controller.stop()

        strategy_path = self._strategy_path if Path(self._strategy_path).exists() else None
        self._runner = BacktraderRunner(
            data_path=self._data_path,
            strategy_path=strategy_path,
            instrument=self._instrument,
            initial_cash=self._initial_cash,
        )
        try:
            self._runner.load()
        except Exception as e:
            self.notify(f"Load error: {e}", severity="error")
            return

        loop = asyncio.get_event_loop()
        self._controller = ReplayController(self._runner, loop)
        self._controller.on("bar", self._on_bar)
        self._controller.on("trade", self._on_trade)
        self._controller.on("complete", self._on_complete)
        self._controller.pause()
        self._controller.start()

        status = self.query_one("#status_bar", StatusBar)
        status.bar_index = 0
        status.speed = 0
        status.message = "Loaded. [Space]=Play  [T]=TPO  [\\]=AI Chat  [N]=News"

    def _reset_state(self):
        self._closed_trades.clear()
        self._equity_curve = [(0, self._initial_cash)]
        self._n_trades = 0
        self._net_pnl = 0.0
        self._win_count = 0
        self._current_bar = None
        self._mc_result = None

        self.query_one("#chart_panel", CandlestickChart).clear()
        self.query_one("#trade_log_panel", TradeLog).clear()
        self.query_one("#stats_panel", StatsPanel).update_live(0, 0, 0, 0, 0, 0, 0)

        if self._prop_profile and self._prop_enabled:
            self._prop_engine = PropRulesEngine(self._prop_profile)
            self.query_one("#prop_rules_panel", PropRulesPanel).set_profile(self._prop_profile)

    # ------------------------------------------------------------------ #
    # Event callbacks                                                      #
    # ------------------------------------------------------------------ #

    async def _on_bar(self, bar: BarEvent):
        self._current_bar = bar

        chart = self.query_one("#chart_panel", CandlestickChart)
        chart.push_bar(bar)

        spec = get_instrument(self._instrument)
        self.query_one("#position_panel", PositionPanel).update_bar(bar, spec.point_value)

        status = self.query_one("#status_bar", StatusBar)
        if self._controller:
            status.bar_index = bar.bar_index
            status.total_bars = self._controller.state.total_bars or bar.bar_index + 1

        if self._prop_engine and self._prop_enabled:
            self.query_one("#prop_rules_panel", PropRulesPanel).update_state(
                self._prop_engine.state
            )

    async def _on_trade(self, trade: TradeEvent):
        self.query_one("#chart_panel", CandlestickChart).push_trade(trade)

        if self._controller:
            self.query_one("#position_panel", PositionPanel).update_open_trades(
                self._controller.state.open_trades
            )

        if not trade.is_open:
            self._closed_trades.append(trade)
            net = (trade.pnl or 0) - trade.commission
            self._net_pnl += net
            self._n_trades += 1
            if net > 0:
                self._win_count += 1

            last_eq = self._equity_curve[-1][1] if self._equity_curve else self._initial_cash
            self._equity_curve.append((trade.bar_index, last_eq + net))

            wr = self._win_count / self._n_trades
            wins_pnl = sum((t.pnl or 0) - t.commission for t in self._closed_trades if (t.pnl or 0) > t.commission)
            loss_pnl = abs(sum((t.pnl or 0) - t.commission for t in self._closed_trades if (t.pnl or 0) - t.commission < 0)) or 1e-9
            pf = wins_pnl / loss_pnl

            import numpy as np
            equities = [e for _, e in self._equity_curve]
            eq_arr = np.array(equities)
            max_dd = float(np.max(np.maximum.accumulate(eq_arr) - eq_arr))

            self.query_one("#stats_panel", StatsPanel).update_live(
                n_trades=self._n_trades,
                net_pnl=self._net_pnl,
                win_rate=wr,
                profit_factor=pf,
                sharpe=0.0,
                max_dd=max_dd,
                expectancy=self._net_pnl / self._n_trades,
            )
            self.query_one("#trade_log_panel", TradeLog).add_trade(trade)

            if self._prop_engine and self._prop_enabled:
                violations = self._prop_engine.on_trade_close(trade, trade.bar_index)
                for v in violations:
                    self.notify(
                        f"[{v.level}] {v.rule}: {v.message}",
                        severity="warning" if v.level == "WARNING" else "error",
                        timeout=5,
                    )
                if self._prop_engine.state.is_breached and self._controller:
                    self._controller.pause()
                    self.query_one("#status_bar", StatusBar).message = (
                        f"BREACH: {self._prop_engine.state.breach_rule} — replay paused"
                    )

    async def _on_complete(self, event: RunCompleteEvent):
        status = self.query_one("#status_bar", StatusBar)
        status.speed = 0
        status.total_bars = event.total_bars
        status.message = (
            f"Done: {event.total_bars:,} bars | {self._n_trades} trades | "
            f"P&L: ${self._net_pnl:+,.2f}  [R]=Reset  [A]=Analytics  [C]=MC"
        )
        self.notify(
            f"Backtest complete — {event.total_bars:,} bars | "
            f"{self._n_trades} trades | P&L: ${self._net_pnl:+,.2f}",
            title="BACKTEST COMPLETE",
            timeout=10,
        )
        # Auto-push a context summary to AI chat if open
        ai_panel = self.query_one("#ai_chat_panel", AIChatPanel)
        if ai_panel.is_open:
            ai_panel.inject_context_message(
                f"Backtest complete — {self._n_trades} trades, "
                f"P&L ${self._net_pnl:+,.2f}, "
                f"Win rate {self._win_count/max(self._n_trades,1)*100:.1f}%"
            )

"""Main Textual application — FuturesBacktestTUI."""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, Grid
from textual.widgets import Static, Footer, Header
from textual.reactive import reactive

from .engine.backtrader_runner import BacktraderRunner
from .engine.replay_controller import ReplayController, ReplayState
from .engine.prop_rules import PropFirmProfile, PropRulesEngine
from .engine.events import BarEvent, TradeEvent, OrderEvent, RunCompleteEvent
from .engine.analytics import compute_analytics, AnalyticsReport
from .engine.instruments import get_instrument

from .widgets.chart_widget import CandlestickChart
from .widgets.trade_log import TradeLog
from .widgets.stats_panel import StatsPanel
from .widgets.prop_rules_panel import PropRulesPanel
from .widgets.strategy_panel import StrategyPanel
from .widgets.position_panel import PositionPanel
from .widgets.status_bar import StatusBar

from .screens.hotkey_help import HotkeyHelp
from .screens.data_manager import DataManager, DataLoaded
from .screens.strategy_editor import StrategyEditor, StrategySelected
from .screens.prop_firm_config import PropFirmConfig, PropProfileSelected
from .screens.monte_carlo_view import MonteCarloView
from .screens.analytics_report import AnalyticsReportScreen

# Default firm profiles directory
FIRM_PROFILES_DIR = Path(__file__).parent.parent / "firm_profiles"
DEMO_DATA = Path(__file__).parent.parent / "data" / "demo" / "es_demo_5m.csv"
DEMO_STRATEGY = Path(__file__).parent.parent / "strategies" / "sma_cross.py"


class FuturesBacktestTUI(App):
    """Futures Backtest TUI — terminal-based futures backtesting platform."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 3;
        grid-rows: 2fr 1fr 1fr;
        grid-columns: 22 1fr;
    }

    #left_col {
        row-span: 3;
        layout: vertical;
    }

    #strategy_panel {
        height: 1fr;
    }
    #position_panel {
        height: auto;
        max-height: 12;
    }
    #prop_rules_panel {
        height: 1fr;
    }

    #chart_panel {
        row-span: 1;
    }
    #trade_log_panel {
        row-span: 1;
    }
    #stats_panel {
        row-span: 1;
    }

    #status_bar {
        dock: bottom;
        height: 1;
    }
    """

    BINDINGS = [
        Binding("space", "toggle_play", "Play/Pause", priority=True),
        Binding("right,]", "step_forward", "Step →", priority=True),
        Binding("left,[", "step_backward", "Step ←", priority=True),
        Binding("f", "speed_5x", "5×"),
        Binding("F", "speed_25x", "25×"),
        Binding("m", "speed_max", "Max"),
        Binding("r", "reset", "Reset"),
        Binding("s", "open_strategy", "Strategy"),
        Binding("d", "open_data", "Data"),
        Binding("p", "open_prop", "Prop Firm"),
        Binding("a", "open_analytics", "Analytics"),
        Binding("c", "open_mc", "Monte Carlo"),
        Binding("e", "export", "Export"),
        Binding("i", "toggle_indicators", "Indicators"),
        Binding("question_mark,?", "show_help", "Help"),
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
        self._equity_curve: list[tuple[int, float]] = []
        self._n_trades: int = 0
        self._net_pnl: float = 0.0
        self._win_count: int = 0

    # ------------------------------------------------------------------ #
    # Compose                                                              #
    # ------------------------------------------------------------------ #

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="left_col"):
            yield StrategyPanel(id="strategy_panel")
            yield PositionPanel(id="position_panel")
            yield PropRulesPanel(id="prop_rules_panel")
        yield CandlestickChart(id="chart_panel")
        yield TradeLog(id="trade_log_panel")
        yield StatsPanel(id="stats_panel")
        yield StatusBar(id="status_bar")

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def on_mount(self):
        self.title = "Futures Backtest TUI"
        self.sub_title = "v1.0 — Prop-Firm Optimized"

        # Load default apex profile
        apex_path = FIRM_PROFILES_DIR / "apex_50k.toml"
        if apex_path.exists():
            try:
                self._prop_profile = PropFirmProfile.from_toml(str(apex_path))
                self._prop_engine = PropRulesEngine(self._prop_profile)
                self._prop_enabled = True
                prop_panel = self.query_one("#prop_rules_panel", PropRulesPanel)
                prop_panel.set_profile(self._prop_profile)
            except Exception:
                pass

        status = self.query_one("#status_bar", StatusBar)
        status.firm_name = self._prop_profile.name if self._prop_profile else "—"
        status.message = "Press D to load data, S for strategy, Space to run  |  ? for help"

        # Update strategy panel with default info
        strat_panel = self.query_one("#strategy_panel", StrategyPanel)
        strat_panel.set_strategy("SMA Crossover", {"fast": 10, "slow": 30}, ["SMA(10)", "SMA(30)"])
        strat_panel.set_data_info(Path(self._data_path).name, self._instrument)

        # Auto-start with demo data if it exists
        if DEMO_DATA.exists():
            self.call_later(self._start_replay)

    # ------------------------------------------------------------------ #
    # Actions                                                              #
    # ------------------------------------------------------------------ #

    def action_toggle_play(self):
        if not self._controller:
            self.call_later(self._start_replay)
            return
        state = self._controller.state
        if state.speed == 0:
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
        if not self._controller:
            return
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
    # Screen message handlers                                              #
    # ------------------------------------------------------------------ #

    def on_data_loaded(self, msg: DataLoaded):
        self._data_path = msg.data_path
        self._instrument = msg.instrument
        self._initial_cash = msg.initial_cash
        strat_panel = self.query_one("#strategy_panel", StrategyPanel)
        strat_panel.set_data_info(Path(self._data_path).name, self._instrument)
        self._reset_state()
        self.call_later(self._start_replay)

    def on_strategy_selected(self, msg: StrategySelected):
        self._strategy_path = msg.path
        name = Path(msg.path).stem.replace("_", " ").title()
        strat_panel = self.query_one("#strategy_panel", StrategyPanel)
        strat_panel.set_strategy(name, {})
        self._reset_state()
        self.call_later(self._start_replay)

    def on_prop_profile_selected(self, msg: PropProfileSelected):
        self._prop_profile = msg.profile
        self._prop_enabled = msg.enabled
        self._prop_engine = PropRulesEngine(msg.profile) if msg.enabled else None
        prop_panel = self.query_one("#prop_rules_panel", PropRulesPanel)
        prop_panel.set_profile(msg.profile)
        status = self.query_one("#status_bar", StatusBar)
        status.firm_name = msg.profile.name if msg.enabled else "—"
        self.notify(f"Prop profile: {msg.profile.name} ({'ON' if msg.enabled else 'OFF'})")

    # ------------------------------------------------------------------ #
    # Replay engine                                                        #
    # ------------------------------------------------------------------ #

    async def _start_replay(self):
        if not Path(self._data_path).exists():
            self.notify(f"Data file not found: {self._data_path}", severity="error")
            return

        self._reset_state()

        # Stop any existing runner
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
        status.message = "Data loaded. Press Space to start replay."

    def _reset_state(self):
        self._closed_trades.clear()
        self._equity_curve = [(0, self._initial_cash)]
        self._n_trades = 0
        self._net_pnl = 0.0
        self._win_count = 0

        self.query_one("#chart_panel", CandlestickChart).clear()
        self.query_one("#trade_log_panel", TradeLog).clear()
        self.query_one("#stats_panel", StatsPanel).update_live(0, 0, 0, 0, 0, 0, 0)

        if self._prop_profile and self._prop_enabled:
            self._prop_engine = PropRulesEngine(self._prop_profile)
            prop_panel = self.query_one("#prop_rules_panel", PropRulesPanel)
            prop_panel.set_profile(self._prop_profile)

    # ------------------------------------------------------------------ #
    # Event callbacks (called from async context)                          #
    # ------------------------------------------------------------------ #

    async def _on_bar(self, bar: BarEvent):
        chart = self.query_one("#chart_panel", CandlestickChart)
        chart.push_bar(bar)

        pos_panel = self.query_one("#position_panel", PositionPanel)
        spec = get_instrument(self._instrument)
        pos_panel.update_bar(bar, spec.point_value)

        status = self.query_one("#status_bar", StatusBar)
        if self._controller:
            status.bar_index = bar.bar_index
            status.total_bars = self._controller.state.total_bars or bar.bar_index + 1

        # Prop rules: update panel state
        if self._prop_engine and self._prop_enabled:
            prop_panel = self.query_one("#prop_rules_panel", PropRulesPanel)
            prop_panel.update_state(self._prop_engine.state)

    async def _on_trade(self, trade: TradeEvent):
        chart = self.query_one("#chart_panel", CandlestickChart)
        chart.push_trade(trade)

        pos_panel = self.query_one("#position_panel", PositionPanel)
        if self._controller:
            pos_panel.update_open_trades(self._controller.state.open_trades)

        if not trade.is_open:
            self._closed_trades.append(trade)
            net = (trade.pnl or 0) - trade.commission
            self._net_pnl += net
            self._n_trades += 1
            if net > 0:
                self._win_count += 1

            if self._equity_curve:
                last_eq = self._equity_curve[-1][1]
                self._equity_curve.append((trade.bar_index, last_eq + net))

            win_rate = self._win_count / self._n_trades if self._n_trades > 0 else 0
            gross_wins = sum((t.pnl or 0) for t in self._closed_trades if (t.pnl or 0) > 0)
            gross_loss = abs(sum((t.pnl or 0) for t in self._closed_trades if (t.pnl or 0) < 0)) or 1e-9
            pf = gross_wins / gross_loss

            # Simple running max drawdown
            equities = [e for _, e in self._equity_curve]
            if equities:
                import numpy as np
                eq_arr = np.array(equities)
                running_max = np.maximum.accumulate(eq_arr)
                max_dd = float(np.max(running_max - eq_arr))
            else:
                max_dd = 0.0

            self.query_one("#stats_panel", StatsPanel).update_live(
                n_trades=self._n_trades,
                net_pnl=self._net_pnl,
                win_rate=win_rate,
                profit_factor=pf,
                sharpe=0.0,
                max_dd=max_dd,
                expectancy=self._net_pnl / self._n_trades if self._n_trades > 0 else 0,
            )
            self.query_one("#trade_log_panel", TradeLog).add_trade(trade)

            # Prop rules
            if self._prop_engine and self._prop_enabled:
                violations = self._prop_engine.on_trade_close(trade, trade.bar_index)
                for v in violations:
                    level = v.level
                    self.notify(
                        f"[{level}] {v.rule}: {v.message}",
                        severity="warning" if level == "WARNING" else "error",
                        timeout=5,
                    )
                if self._prop_engine.state.is_breached and self._controller:
                    self._controller.pause()
                    status = self.query_one("#status_bar", StatusBar)
                    status.message = f"BREACH: {self._prop_engine.state.breach_rule} — replay paused"

    async def _on_complete(self, event: RunCompleteEvent):
        status = self.query_one("#status_bar", StatusBar)
        status.speed = 0
        status.total_bars = event.total_bars
        status.message = f"Backtest complete — {event.total_bars:,} bars, {event.total_trades} trades. Press R to reset."
        self.notify(
            f"Complete: {event.total_bars:,} bars | {self._n_trades} trades | P&L: ${self._net_pnl:+,.2f}",
            title="Backtest Done",
            timeout=10,
        )

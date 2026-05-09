"""AnalyticsReport screen — full quantitative summary, exportable."""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static, Button, TextArea, Label
from textual.containers import Vertical, Horizontal, ScrollableContainer

from ..engine.analytics import AnalyticsReport, format_report_text, compute_analytics
from ..engine.events import TradeEvent


class AnalyticsReportScreen(ModalScreen):
    DEFAULT_CSS = """
    AnalyticsReportScreen {
        align: center middle;
    }
    #ar_container {
        width: 65;
        height: 50;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #report_body {
        height: 1fr;
        border: solid $panel;
        overflow-y: auto;
    }
    #btn_row { margin-top: 1; height: auto; }
    """

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(
        self,
        trades: list[TradeEvent],
        equity_curve: list[tuple[int, float]],
        initial_equity: float = 50000.0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._trades = trades
        self._equity_curve = equity_curve
        self._initial_equity = initial_equity
        self._report: AnalyticsReport | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="ar_container"):
            yield Static("[bold cyan]Analytics Report[/bold cyan]")
            yield Static("", id="report_body")
            with Horizontal(id="btn_row"):
                yield Button("Export CSV", id="export_csv_btn", variant="default")
                yield Button("Export JSON", id="export_json_btn", variant="default")
                yield Button("Close", id="close_btn", variant="default")

    def on_mount(self):
        closed = [t for t in self._trades if not t.is_open]
        self._report = compute_analytics(
            closed,
            self._equity_curve,
            self._initial_equity,
        )
        text = format_report_text(self._report)
        self.query_one("#report_body", Static).update(text)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "close_btn":
            self.dismiss()
        elif event.button.id == "export_csv_btn":
            self._export_csv()
        elif event.button.id == "export_json_btn":
            self._export_json()

    def _export_csv(self):
        if not self._trades:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(f"backtest_trades_{ts}.csv")
        lines = ["#,time,direction,entry,exit,pnl,commission\n"]
        for i, t in enumerate(self._trades, 1):
            if not t.is_open:
                lines.append(
                    f"{i},{t.timestamp},{t.direction},"
                    f"{t.entry_price:.4f},{t.exit_price or ''},"
                    f"{t.pnl or 0:.2f},{t.commission:.2f}\n"
                )
        path.write_text("".join(lines))
        self.notify(f"Trades exported to {path}")

    def _export_json(self):
        if not self._report:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(f"backtest_analytics_{ts}.json")
        r = self._report
        data = {
            "net_pnl": r.net_pnl,
            "total_return_pct": r.total_return_pct,
            "cagr": r.cagr,
            "sharpe": r.sharpe,
            "sortino": r.sortino,
            "calmar": r.calmar,
            "omega": r.omega,
            "ulcer_index": r.ulcer_index,
            "upi": r.upi,
            "n_trades": r.n_trades,
            "win_rate": r.win_rate,
            "profit_factor": r.profit_factor,
            "expectancy": r.expectancy,
            "avg_win": r.avg_win,
            "avg_loss": r.avg_loss,
            "avg_rr": r.avg_rr,
            "avg_r_multiple": r.avg_r_multiple,
            "largest_win": r.largest_win,
            "largest_loss": r.largest_loss,
            "max_consecutive_wins": r.max_consecutive_wins,
            "max_consecutive_losses": r.max_consecutive_losses,
            "avg_mae": r.avg_mae,
            "avg_mfe": r.avg_mfe,
            "avg_etd": r.avg_etd,
            "max_drawdown": r.max_drawdown,
            "max_drawdown_pct": r.max_drawdown_pct,
            "recovery_factor": r.recovery_factor,
            "time_underwater_pct": r.time_underwater_pct,
            "t_statistic": r.t_statistic,
            "p_value": r.p_value,
            "psr": r.psr,
            "dsr": r.dsr,
            "n_adequate": r.n_adequate,
            "skewness": r.skewness,
            "kurtosis": r.kurtosis,
        }
        path.write_text(json.dumps(data, indent=2))
        self.notify(f"Analytics exported to {path}")

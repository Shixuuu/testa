"""StatsPanel — live portfolio stats display."""
from __future__ import annotations
from textual.widget import Widget
from textual.reactive import reactive
from rich.table import Table
from rich.text import Text
from rich import box

from ..engine.analytics import AnalyticsReport


class StatsPanel(Widget):
    DEFAULT_CSS = """
    StatsPanel {
        height: 1fr;
        border: solid $panel;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._report: AnalyticsReport | None = None
        self._n_trades: int = 0
        self._net_pnl: float = 0.0
        self._win_rate: float = 0.0
        self._profit_factor: float = 0.0
        self._sharpe: float = 0.0
        self._max_dd: float = 0.0
        self._expectancy: float = 0.0

    def update_live(
        self,
        n_trades: int,
        net_pnl: float,
        win_rate: float,
        profit_factor: float,
        sharpe: float,
        max_dd: float,
        expectancy: float,
    ):
        self._n_trades = n_trades
        self._net_pnl = net_pnl
        self._win_rate = win_rate
        self._profit_factor = profit_factor
        self._sharpe = sharpe
        self._max_dd = max_dd
        self._expectancy = expectancy
        self.refresh()

    def update_report(self, report: AnalyticsReport):
        self._report = report
        self.refresh()

    def render(self) -> Table:
        r = self._report
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("Metric", style="dim", no_wrap=True)
        table.add_column("Value", style="bold", justify="right", no_wrap=True)

        def row(label: str, value: str, style: str = ""):
            table.add_row(label, Text(value, style=style) if style else value)

        def pnl_style(v: float) -> str:
            return "bright_green" if v >= 0 else "bright_red"

        def grade(v: float, good: float, ok: float) -> str:
            if v >= good:
                return "bright_green"
            elif v >= ok:
                return "yellow"
            return "red"

        net = r.net_pnl if r else self._net_pnl
        wr = (r.win_rate if r else self._win_rate) * 100
        pf = r.profit_factor if r else self._profit_factor
        sh = r.sharpe if r else self._sharpe
        mdd = r.max_drawdown if r else self._max_dd
        exp = r.expectancy if r else self._expectancy
        n = r.n_trades if r else self._n_trades

        row("Trades", f"{n:,}")
        row("Net P&L", f"${net:+,.2f}", pnl_style(net))
        row("Win Rate", f"{wr:.1f}%", grade(wr, 55, 40))
        row("Profit Factor", f"{pf:.2f}", grade(pf, 1.5, 1.0))
        row("Expectancy", f"${exp:,.2f}", pnl_style(exp))
        row("Sharpe", f"{sh:.2f}", grade(sh, 2.0, 1.0))

        if r:
            row("Sortino", f"{r.sortino:.2f}", grade(r.sortino, 3.0, 1.5))
            row("Calmar", f"{r.calmar:.2f}", grade(r.calmar, 3.0, 0.5))
            row("Omega", f"{r.omega:.2f}", grade(r.omega, 2.0, 1.0))

        row("Max DD", f"${mdd:,.2f}", "red" if mdd > 0 else "green")

        if r:
            row("DD %", f"{r.max_drawdown_pct:.1f}%", "red" if r.max_drawdown_pct > 10 else "yellow")
            row("Recovery F.", f"{r.recovery_factor:.2f}")
            row("CAGR", f"{r.cagr * 100:.1f}%", pnl_style(r.cagr))
            row("PSR", f"{r.psr * 100:.1f}%", grade(r.psr * 100, 90, 70))
            row("Avg R", f"{r.avg_r_multiple:.2f}R")
            row("Avg MAE", f"${r.avg_mae:,.2f}")
            row("Avg MFE", f"${r.avg_mfe:,.2f}")
            row("Skewness", f"{r.skewness:.3f}")
            row("Kurtosis", f"{r.kurtosis:.3f}")

        return table

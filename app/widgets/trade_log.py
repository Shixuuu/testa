"""TradeLog widget — scrollable table of all closed trades."""
from __future__ import annotations
from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import DataTable
from textual.reactive import reactive
from rich.text import Text

from ..engine.events import TradeEvent


class TradeLog(Widget):
    DEFAULT_CSS = """
    TradeLog {
        height: 1fr;
        border: solid $panel;
    }
    TradeLog > DataTable {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        table = DataTable(id="trade_table", zebra_stripes=True, cursor_type="row")
        table.add_columns("#", "Time", "Dir", "Entry", "Exit", "P&L", "Comm", "R-Mult")
        yield table

    def on_mount(self):
        self._count = 0

    def add_trade(self, trade: TradeEvent):
        if trade.is_open:
            return
        table: DataTable = self.query_one("#trade_table")
        self._count += 1

        pnl = trade.pnl or 0.0
        net = pnl - trade.commission
        r_mult = ""
        if trade.mae is not None and trade.mae < 0:
            risk = abs(trade.mae)
            if risk > 0:
                r_mult = f"{net / risk:+.2f}R"

        pnl_style = "green" if net >= 0 else "red"
        dir_style = "bright_green" if trade.direction == "LONG" else "bright_red"

        table.add_row(
            str(self._count),
            trade.timestamp.strftime("%m/%d %H:%M"),
            Text(trade.direction, style=dir_style),
            f"{trade.entry_price:.2f}",
            f"{trade.exit_price:.2f}" if trade.exit_price else "—",
            Text(f"${net:+,.2f}", style=pnl_style),
            f"${trade.commission:.2f}",
            r_mult,
        )
        table.scroll_end(animate=False)

    def clear(self):
        table: DataTable = self.query_one("#trade_table")
        table.clear()
        self._count = 0

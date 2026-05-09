"""PositionPanel — current open position and unrealized P&L."""
from __future__ import annotations
from textual.widget import Widget
from rich.table import Table
from rich.text import Text
from rich import box

from ..engine.events import TradeEvent, BarEvent


class PositionPanel(Widget):
    DEFAULT_CSS = """
    PositionPanel {
        height: auto;
        border: solid $panel;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._open_trades: list[TradeEvent] = []
        self._current_price: float = 0.0
        self._point_value: float = 50.0
        self._cash: float = 0.0
        self._equity: float = 0.0

    def update_bar(self, bar: BarEvent, point_value: float = 50.0):
        self._current_price = bar.close
        self._point_value = point_value
        self.refresh()

    def update_open_trades(self, trades: list[TradeEvent]):
        self._open_trades = trades
        self.refresh()

    def update_account(self, cash: float, equity: float):
        self._cash = cash
        self._equity = equity
        self.refresh()

    def render(self) -> Table:
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("Field", style="dim", no_wrap=True)
        table.add_column("Value", justify="right", no_wrap=True)

        if not self._open_trades:
            table.add_row("Position", Text("FLAT", style="dim"))
        else:
            total_size = sum(t.size for t in self._open_trades)
            direction = self._open_trades[0].direction if self._open_trades else "FLAT"
            avg_entry = (
                sum(t.entry_price * t.size for t in self._open_trades) / total_size
                if total_size else 0
            )
            unreal = (
                (self._current_price - avg_entry) * total_size * self._point_value
                if direction == "LONG"
                else (avg_entry - self._current_price) * total_size * self._point_value
            )
            color = "bright_green" if direction == "LONG" else "bright_red"
            unreal_color = "bright_green" if unreal >= 0 else "bright_red"

            table.add_row("Direction", Text(direction, style=color))
            table.add_row("Size", f"{total_size:.0f} ct")
            table.add_row("Avg Entry", f"{avg_entry:.2f}")
            table.add_row("Current", f"{self._current_price:.2f}")
            table.add_row("Unreal P&L", Text(f"${unreal:+,.2f}", style=unreal_color))

        table.add_row("", "")
        table.add_row("Cash", f"${self._cash:,.2f}")
        table.add_row("Equity", f"${self._equity:,.2f}")
        return table

"""CandlestickChart — ASCII candlestick chart widget for Textual."""
from __future__ import annotations
from typing import Optional
from textual.widget import Widget
from textual.app import ComposeResult
from textual.reactive import reactive
from rich.text import Text
from rich.segment import Segment
from rich.style import Style

from ..engine.events import BarEvent, TradeEvent


BULL_COLOR = "bright_green"
BEAR_COLOR = "bright_red"
WICK_COLOR = "white"
ENTRY_LONG_COLOR = "green"
ENTRY_SHORT_COLOR = "red"
EXIT_PROFIT_COLOR = "bright_green"
EXIT_LOSS_COLOR = "bright_red"
SL_COLOR = "red"
TP_COLOR = "green"
CURRENT_BAR_COLOR = "bright_cyan"


class CandlestickChart(Widget):
    """
    Renders a simple ASCII candlestick chart using Rich markup.
    Supports trade entry/exit markers and SL/TP horizontal lines.
    """

    DEFAULT_CSS = """
    CandlestickChart {
        height: 1fr;
        border: solid $panel;
        background: $surface;
        padding: 1 2;
    }
    """

    bars_visible: reactive[int] = reactive(80)
    show_volume: reactive[bool] = reactive(True)
    show_indicators: reactive[bool] = reactive(True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._bars: list[BarEvent] = []
        self._trades: list[TradeEvent] = []
        self._open_trades: list[TradeEvent] = []
        self._indicators: dict[str, list[tuple[int, float]]] = {}  # name -> [(bar_idx, val)]

    def push_bar(self, bar: BarEvent):
        self._bars.append(bar)
        self.refresh()

    def push_trade(self, trade: TradeEvent):
        if trade.is_open:
            self._open_trades.append(trade)
        else:
            self._open_trades = [t for t in self._open_trades if t.trade_id != trade.trade_id]
            self._trades.append(trade)
        self.refresh()

    def clear(self):
        self._bars.clear()
        self._trades.clear()
        self._open_trades.clear()
        self._indicators.clear()
        self.refresh()

    def render(self) -> Text:
        if not self._bars:
            return Text("No data loaded. Press D to open Data Manager.", style="dim")

        width = self.size.width - 4
        height = self.size.height - 4
        if width < 10 or height < 5:
            return Text("Too small")

        visible_bars = self._bars[-self.bars_visible:]
        if not visible_bars:
            return Text("")

        # Reserve bottom rows for volume if enabled
        chart_height = height - 4 if self.show_volume else height - 1
        vol_height = 3 if self.show_volume else 0

        prices_all = []
        for b in visible_bars:
            prices_all.extend([b.high, b.low])
        if not prices_all:
            return Text("")

        price_min = min(prices_all)
        price_max = max(prices_all)
        price_range = price_max - price_min or 1.0

        # Build canvas: list of list of (char, style)
        canvas: list[list[tuple[str, str]]] = [
            [(" ", "")] * width for _ in range(height)
        ]

        bar_width = max(1, width // max(len(visible_bars), 1))
        bar_width = min(bar_width, 3)

        def price_to_row(p: float) -> int:
            return int((price_max - p) / price_range * (chart_height - 1))

        # Draw SL/TP lines for open trades
        for ot in self._open_trades:
            if ot.stop_loss:
                row = price_to_row(ot.stop_loss)
                if 0 <= row < chart_height:
                    for c in range(width):
                        canvas[row][c] = ("─", SL_COLOR)
            if ot.take_profit:
                row = price_to_row(ot.take_profit)
                if 0 <= row < chart_height:
                    for c in range(width):
                        canvas[row][c] = ("─", TP_COLOR)

        # Build trade markers indexed by bar
        entry_markers: dict[int, str] = {}  # bar_index -> "LONG"|"SHORT"
        exit_markers: dict[int, str] = {}   # bar_index -> "PROFIT"|"LOSS"
        entry_prices: dict[int, float] = {}
        exit_prices: dict[int, float] = {}

        for t in self._trades:
            entry_markers[t.bar_index] = t.direction
            entry_prices[t.bar_index] = t.entry_price
            if t.exit_price is not None:
                exit_markers[t.bar_index + 1] = "PROFIT" if (t.pnl or 0) >= 0 else "LOSS"
                exit_prices[t.bar_index + 1] = t.exit_price

        # Draw candlesticks
        volumes = [b.volume for b in visible_bars]
        max_vol = max(volumes) if any(v > 0 for v in volumes) else 1.0

        for i, bar in enumerate(visible_bars):
            col = i * bar_width
            if col >= width:
                break

            is_current = i == len(visible_bars) - 1
            is_bull = bar.close >= bar.open
            body_color = BULL_COLOR if is_bull else BEAR_COLOR
            if is_current:
                body_color = CURRENT_BAR_COLOR

            top_row = price_to_row(bar.high)
            bot_row = price_to_row(bar.low)
            open_row = price_to_row(bar.open)
            close_row = price_to_row(bar.close)
            body_top = min(open_row, close_row)
            body_bot = max(open_row, close_row)

            # Draw wick
            for r in range(max(0, top_row), min(chart_height, bot_row + 1)):
                if col < width:
                    canvas[r][col] = ("│", WICK_COLOR)

            # Draw body
            body_char = "█" if bar_width >= 2 else "▌"
            for r in range(max(0, body_top), min(chart_height, body_bot + 1)):
                for w in range(bar_width):
                    if col + w < width:
                        canvas[r][col + w] = (body_char, body_color)

            # Trade markers
            bidx = bar.bar_index
            if bidx in entry_markers:
                direction = entry_markers[bidx]
                price = entry_prices.get(bidx, bar.close)
                row = price_to_row(price)
                row = max(0, min(chart_height - 1, row))
                marker = "▲" if direction == "LONG" else "▼"
                color = ENTRY_LONG_COLOR if direction == "LONG" else ENTRY_SHORT_COLOR
                if col < width:
                    canvas[row][col] = (marker, color)

            if bidx in exit_markers:
                outcome = exit_markers[bidx]
                price = exit_prices.get(bidx, bar.close)
                row = price_to_row(price)
                row = max(0, min(chart_height - 1, row))
                color = EXIT_PROFIT_COLOR if outcome == "PROFIT" else EXIT_LOSS_COLOR
                if col < width:
                    canvas[row][col] = ("✕", color)

            # Volume bars
            if self.show_volume and bar.volume > 0:
                vol_row_height = int(bar.volume / max_vol * vol_height)
                for vr in range(vol_row_height):
                    row = height - 1 - vr
                    if 0 <= row < height and col < width:
                        canvas[row][col] = ("▄", "dim " + body_color)

        # Convert canvas to Rich Text
        lines = []
        for row in canvas:
            line = Text()
            for char, style in row:
                line.append(char, style=Style.parse(style) if style else Style.null())
            lines.append(line)

        result = Text()
        for i, line in enumerate(lines):
            result.append_text(line)
            if i < len(lines) - 1:
                result.append("\n")

        return result

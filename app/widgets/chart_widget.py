"""
CandlestickChart — ASCII candlestick + TPO/Market Profile chart widget.
Toggle between modes with `T`.
"""
from __future__ import annotations
from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text
from rich.style import Style

from ..engine.events import BarEvent, TradeEvent
from ..engine.tpo_chart import compute_tpo_profiles, TPOProfile

# ---------- colour palette (Bloomberg-dark) ----------
BULL_COLOR = "#00cc44"
BEAR_COLOR = "#ff3030"
WICK_COLOR = "#6a8fb5"
ENTRY_LONG_COLOR = "#00ff88"
ENTRY_SHORT_COLOR = "#ff6060"
EXIT_PROFIT_COLOR = "#00cc44"
EXIT_LOSS_COLOR = "#ff3030"
SL_COLOR = "#cc2222"
TP_COLOR = "#22aa44"
CURRENT_BAR_COLOR = "#00bfff"
POC_COLOR = "#ff8c00"      # Bloomberg orange
VAH_VAL_COLOR = "#00bfff"  # Bloomberg cyan
VA_FILL_COLOR = "#0d2a18"
SINGLE_COLOR = "#334455"
IB_COLOR = "#1e3a5f"
_HEADER_STYLE = "bold black on #ff8c00"


class CandlestickChart(Widget):
    """
    Renders ASCII candlestick or TPO Market Profile chart.
    Press T to toggle between chart modes.
    """

    DEFAULT_CSS = """
    CandlestickChart {
        height: 1fr;
        border: solid #1e3a5f;
        background: #070d18;
        padding: 0 1;
    }
    """

    bars_visible: reactive[int] = reactive(80)
    show_volume: reactive[bool] = reactive(True)
    show_indicators: reactive[bool] = reactive(True)
    chart_mode: reactive[str] = reactive("candle")   # "candle" | "tpo"
    tick_size: reactive[float] = reactive(0.25)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._bars: list[BarEvent] = []
        self._trades: list[TradeEvent] = []
        self._open_trades: list[TradeEvent] = []
        self._tpo_profiles: list[TPOProfile] = []
        self._tpo_dirty = False

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def push_bar(self, bar: BarEvent):
        self._bars.append(bar)
        self._tpo_dirty = True
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
        self._tpo_profiles.clear()
        self._tpo_dirty = False
        self.refresh()

    def toggle_chart_mode(self):
        self.chart_mode = "tpo" if self.chart_mode == "candle" else "candle"
        self.refresh()

    def set_tick_size(self, tick_size: float):
        self.tick_size = tick_size
        self._tpo_dirty = True
        self.refresh()

    # ------------------------------------------------------------------ #
    # Render dispatch                                                       #
    # ------------------------------------------------------------------ #

    def render(self) -> Text:
        if not self._bars:
            txt = Text()
            txt.append(" CHART ", style=_HEADER_STYLE)
            txt.append(
                "\n\n  No data loaded. Press [D] to open Data Manager.",
                style="dim #6a8fb5",
            )
            return txt

        if self.chart_mode == "tpo":
            return self._render_tpo()
        return self._render_candle()

    # ------------------------------------------------------------------ #
    # Candlestick rendering                                                #
    # ------------------------------------------------------------------ #

    def _render_candle(self) -> Text:
        width = max(self.size.width - 4, 10)
        height = max(self.size.height - 4, 5)

        visible_bars = self._bars[-self.bars_visible:]
        prices_all = [p for b in visible_bars for p in (b.high, b.low)]
        price_min = min(prices_all)
        price_max = max(prices_all)
        price_range = price_max - price_min or 1.0

        chart_height = height - 4 if self.show_volume else height - 1
        vol_height = 3 if self.show_volume else 0
        canvas: list[list[tuple[str, str]]] = [[(" ", "")] * width for _ in range(height)]

        bar_width = min(3, max(1, width // max(len(visible_bars), 1)))

        def p2r(p: float) -> int:
            return int((price_max - p) / price_range * (chart_height - 1))

        # SL / TP lines
        for ot in self._open_trades:
            if ot.stop_loss:
                row = p2r(ot.stop_loss)
                if 0 <= row < chart_height:
                    for c in range(width):
                        canvas[row][c] = ("─", SL_COLOR)
            if ot.take_profit:
                row = p2r(ot.take_profit)
                if 0 <= row < chart_height:
                    for c in range(width):
                        canvas[row][c] = ("─", TP_COLOR)

        entry_markers: dict[int, str] = {}
        exit_markers: dict[int, str] = {}
        entry_prices: dict[int, float] = {}
        exit_prices: dict[int, float] = {}
        for t in self._trades:
            entry_markers[t.bar_index] = t.direction
            entry_prices[t.bar_index] = t.entry_price
            if t.exit_price is not None:
                exit_markers[t.bar_index + 1] = "PROFIT" if (t.pnl or 0) >= 0 else "LOSS"
                exit_prices[t.bar_index + 1] = t.exit_price

        volumes = [b.volume for b in visible_bars]
        max_vol = max(volumes) if any(v > 0 for v in volumes) else 1.0

        for i, bar in enumerate(visible_bars):
            col = i * bar_width
            if col >= width:
                break
            is_current = i == len(visible_bars) - 1
            is_bull = bar.close >= bar.open
            body_color = CURRENT_BAR_COLOR if is_current else (BULL_COLOR if is_bull else BEAR_COLOR)

            top_r = p2r(bar.high)
            bot_r = p2r(bar.low)
            open_r = p2r(bar.open)
            close_r = p2r(bar.close)
            body_top = min(open_r, close_r)
            body_bot = max(open_r, close_r)

            for r in range(max(0, top_r), min(chart_height, bot_r + 1)):
                if col < width:
                    canvas[r][col] = ("│", WICK_COLOR)
            body_char = "█" if bar_width >= 2 else "▌"
            for r in range(max(0, body_top), min(chart_height, body_bot + 1)):
                for w in range(bar_width):
                    if col + w < width:
                        canvas[r][col + w] = (body_char, body_color)

            bidx = bar.bar_index
            if bidx in entry_markers:
                row = max(0, min(chart_height - 1, p2r(entry_prices.get(bidx, bar.close))))
                marker = "▲" if entry_markers[bidx] == "LONG" else "▼"
                color = ENTRY_LONG_COLOR if entry_markers[bidx] == "LONG" else ENTRY_SHORT_COLOR
                if col < width:
                    canvas[row][col] = (marker, color)
            if bidx in exit_markers:
                row = max(0, min(chart_height - 1, p2r(exit_prices.get(bidx, bar.close))))
                color = EXIT_PROFIT_COLOR if exit_markers[bidx] == "PROFIT" else EXIT_LOSS_COLOR
                if col < width:
                    canvas[row][col] = ("✕", color)

            if self.show_volume and bar.volume > 0:
                vol_rows = int(bar.volume / max_vol * vol_height)
                for vr in range(vol_rows):
                    row = height - 1 - vr
                    if 0 <= row < height and col < width:
                        canvas[row][col] = ("▄", "dim " + body_color)

        # Header row
        mode_label = "CANDLE [T=TPO]"
        last_bar = visible_bars[-1] if visible_bars else None
        header_info = ""
        if last_bar:
            bull = last_bar.close >= last_bar.open
            dir_sym = "▲" if bull else "▼"
            price_color = "#00cc44" if bull else "#ff3030"
            header_info = f" {dir_sym} {last_bar.close:.2f}"

        result = Text()
        result.append(f" {mode_label} ", style=_HEADER_STYLE)
        if header_info:
            result.append(header_info, style="bold " + ("#00cc44" if last_bar and last_bar.close >= last_bar.open else "#ff3030"))
        result.append("\n")
        for i, row in enumerate(canvas):
            line = Text()
            for char, style in row:
                line.append(char, style=Style.parse(style) if style else Style.null())
            result.append_text(line)
            if i < len(canvas) - 1:
                result.append("\n")
        return result

    # ------------------------------------------------------------------ #
    # TPO rendering                                                         #
    # ------------------------------------------------------------------ #

    def _render_tpo(self) -> Text:
        if self._tpo_dirty:
            self._tpo_profiles = compute_tpo_profiles(
                self._bars,
                tick_size=self.tick_size,
                period_minutes=30,
            )
            self._tpo_dirty = False

        if not self._tpo_profiles:
            txt = Text()
            txt.append(" TPO MARKET PROFILE ", style=_HEADER_STYLE)
            txt.append("\n\n  No session data to display.", style="dim #6a8fb5")
            return txt

        # Show the most recent session
        profile = self._tpo_profiles[-1]
        width = max(self.size.width - 6, 20)
        height = max(self.size.height - 4, 5)

        all_prices = sorted(profile.price_levels.keys(), reverse=True)

        # Only show as many rows as will fit
        visible_prices = all_prices[:height - 2]

        max_letters = max(len(profile.price_levels.get(p, "")) for p in visible_prices) if visible_prices else 1
        label_w = 10   # price label width
        bar_w = max(1, width - label_w - 4)

        result = Text()
        result.append(" TPO MARKET PROFILE ", style=_HEADER_STYLE)
        result.append(f" {profile.date} ", style="dim #4a6b8a")
        result.append(
            f"  POC={profile.poc:.2f}  VAH={profile.vah:.2f}  VAL={profile.val:.2f}",
            style=f"bold {POC_COLOR}",
        )
        result.append("\n")

        for price in visible_prices:
            letters = profile.price_levels.get(price, "")
            is_poc = abs(price - profile.poc) < self.tick_size * 0.5
            is_vah = abs(price - profile.vah) < self.tick_size * 0.5
            is_val = abs(price - profile.val) < self.tick_size * 0.5
            in_va = profile.val <= price <= profile.vah
            is_ib_high = abs(price - profile.initial_balance_high) < self.tick_size * 0.5
            is_ib_low = abs(price - profile.initial_balance_low) < self.tick_size * 0.5

            # Price label
            if is_poc:
                price_style = f"bold {POC_COLOR}"
                marker = "◆"
            elif is_vah or is_val:
                price_style = f"bold {VAH_VAL_COLOR}"
                marker = "─"
            elif is_ib_high or is_ib_low:
                price_style = f"bold {IB_COLOR}"
                marker = "·"
            else:
                price_style = "#4a6b8a"
                marker = " "

            result.append(f"{marker}{price:>8.2f} ", style=price_style)

            # TPO bar
            bar_len = int(len(letters) / max(max_letters, 1) * bar_w)
            bar_len = max(1, bar_len) if letters else 0

            if is_poc:
                bar_style = f"bold {POC_COLOR}"
                fill_char = "█"
            elif in_va:
                bar_style = "#00884a"
                fill_char = "█"
            else:
                bar_style = "#224433"
                fill_char = "▒"

            if letters:
                # Show actual letters up to bar_len, then block-fill
                display = (letters[:bar_len] if len(letters) <= bar_len
                           else letters[:bar_len - 1] + "+")
                result.append(display.ljust(bar_len, fill_char), style=bar_style)

            # Annotations
            annotations = []
            if is_poc:
                annotations.append(Text("←POC", style=f"bold {POC_COLOR}"))
            if is_vah:
                annotations.append(Text("←VAH", style=f"bold {VAH_VAL_COLOR}"))
            if is_val:
                annotations.append(Text("←VAL", style=f"bold {VAH_VAL_COLOR}"))
            if is_ib_high:
                annotations.append(Text("←IBH", style=f"{IB_COLOR}"))
            if is_ib_low:
                annotations.append(Text("←IBL", style=f"{IB_COLOR}"))

            for ann in annotations:
                result.append_text(ann)

            result.append("\n")

        # Legend
        result.append(
            f"  Sessions: {len(self._tpo_profiles)}  "
            f"| TPOs: {profile.tpo_count}  "
            f"| Singles: {len(profile.single_prints)}  "
            f"| Range: {profile.range_high:.2f}–{profile.range_low:.2f}  "
            f"[T=CANDLE]",
            style="dim #4a6b8a",
        )

        return result

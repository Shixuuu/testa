"""
CandlestickChart — ASCII candlestick + TPO/Market Profile chart widget.

Display-side timeframe aggregation: the widget receives raw bars from the
backtest engine and resamples them on-the-fly for any larger TF (e.g. 5m→1h).
No re-running of the backtest is needed; trade markers are remapped correctly.
Toggle between candle/TPO modes with `T`.
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
POC_COLOR = "#ff8c00"
VAH_VAL_COLOR = "#00bfff"
IB_COLOR = "#1e3a5f"
_HEADER_STYLE = "bold black on #ff8c00"

_TF_LABELS: dict[int, str] = {
    1: "1m", 2: "2m", 3: "3m", 5: "5m", 10: "10m", 15: "15m",
    30: "30m", 60: "1h", 120: "2h", 240: "4h", 480: "8h",
    1440: "1D", 10080: "1W",
}


class CandlestickChart(Widget):
    """
    Renders ASCII candlestick or TPO Market Profile chart.

    Key features:
    - set_base_timeframe(minutes) — called after data loads, locks minimum TF
    - set_display_timeframe(minutes) — aggregate bars for display (≥ base TF)
    - Mouse scroll → zoom in/out; click+drag → pan left/right through history
    - view_offset=0 follows the live bar; >0 pans into history
    - Press T to toggle candle ↔ TPO mode
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
    view_offset: reactive[int] = reactive(0)
    show_volume: reactive[bool] = reactive(True)
    show_indicators: reactive[bool] = reactive(True)
    chart_mode: reactive[str] = reactive("candle")
    tick_size: reactive[float] = reactive(0.25)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._bars: list[BarEvent] = []
        self._trades: list[TradeEvent] = []
        self._open_trades: list[TradeEvent] = []
        self._tpo_profiles: list[TPOProfile] = []
        self._tpo_dirty = False

        # Timeframe state
        self._base_tf_minutes: int = 1
        self._display_tf_minutes: int = 1
        self._display_bars_cache: list[BarEvent] | None = None
        self._cache_dirty: bool = True

        # Mouse state
        self._dragging = False
        self._drag_start_x = 0
        self._drag_offset_start = 0
        self._hover_col: int = -1

    # ------------------------------------------------------------------ #
    # Public API — data                                                    #
    # ------------------------------------------------------------------ #

    def push_bar(self, bar: BarEvent) -> None:
        self._bars.append(bar)
        self._tpo_dirty = True
        self._cache_dirty = True
        self.refresh()

    def push_trade(self, trade: TradeEvent) -> None:
        if trade.is_open:
            self._open_trades.append(trade)
        else:
            self._open_trades = [t for t in self._open_trades if t.trade_id != trade.trade_id]
            self._trades.append(trade)
        self.refresh()

    def clear(self) -> None:
        self._bars.clear()
        self._trades.clear()
        self._open_trades.clear()
        self._tpo_profiles.clear()
        self._display_bars_cache = None
        self._tpo_dirty = False
        self._cache_dirty = True
        self.refresh()

    def toggle_chart_mode(self) -> None:
        self.chart_mode = "tpo" if self.chart_mode == "candle" else "candle"
        self.refresh()

    def set_tick_size(self, tick_size: float) -> None:
        self.tick_size = tick_size
        self._tpo_dirty = True
        self.refresh()

    # ------------------------------------------------------------------ #
    # Public API — timeframe                                               #
    # ------------------------------------------------------------------ #

    def set_base_timeframe(self, minutes: int) -> None:
        """Called when new data is loaded to record the raw bar period."""
        self._base_tf_minutes = max(1, minutes)
        self._display_tf_minutes = max(1, minutes)
        self._cache_dirty = True
        self.view_offset = 0
        self.refresh()

    def set_display_timeframe(self, minutes: int) -> None:
        """Aggregate displayed bars to a larger timeframe (must be ≥ base TF)."""
        clamped = max(self._base_tf_minutes, minutes)
        if clamped == self._display_tf_minutes:
            return
        self._display_tf_minutes = clamped
        self._cache_dirty = True
        self.view_offset = 0   # jump back to live view on TF change
        self.refresh()

    @property
    def _tf_ratio(self) -> int:
        """How many raw bars make one display bar."""
        return max(1, self._display_tf_minutes // max(self._base_tf_minutes, 1))

    def _get_display_bars(self) -> list[BarEvent]:
        """Return bars aggregated to the current display TF, with a simple cache."""
        if not self._cache_dirty and self._display_bars_cache is not None:
            return self._display_bars_cache

        ratio = self._tf_ratio
        if ratio <= 1:
            self._display_bars_cache = self._bars
            self._cache_dirty = False
            return self._bars

        result: list[BarEvent] = []
        bars = self._bars
        for i in range(0, len(bars), ratio):
            group = bars[i : i + ratio]
            result.append(BarEvent(
                bar_index=len(result),
                timestamp=group[0].timestamp,
                open=group[0].open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=group[-1].close,
                volume=sum(b.volume for b in group),
            ))
        self._display_bars_cache = result
        self._cache_dirty = False
        return result

    # ------------------------------------------------------------------ #
    # Mouse zoom / pan                                                     #
    # ------------------------------------------------------------------ #

    def on_mouse_scroll_up(self, event) -> None:
        step = max(1, self.bars_visible // 8)
        self.bars_visible = max(10, self.bars_visible - step)
        event.stop()

    def on_mouse_scroll_down(self, event) -> None:
        step = max(1, self.bars_visible // 8)
        display_total = len(self._get_display_bars())
        self.bars_visible = min(max(display_total, 10), self.bars_visible + step)
        event.stop()

    def on_mouse_down(self, event) -> None:
        self._dragging = True
        self._drag_start_x = event.x
        self._drag_offset_start = self.view_offset
        self.capture_mouse()

    def on_mouse_move(self, event) -> None:
        if self._dragging and self._bars:
            width = max(self.size.width - 4, 10)
            bar_w = max(1, min(3, width // max(self.bars_visible, 1)))
            delta = int((self._drag_start_x - event.x) / max(bar_w, 1))
            display_total = len(self._get_display_bars())
            new_off = max(0, min(display_total - self.bars_visible, self._drag_offset_start + delta))
            if new_off != self.view_offset:
                self.view_offset = new_off
        self._hover_col = event.x
        self.refresh()

    def on_mouse_up(self, event) -> None:
        self._dragging = False
        self.release_mouse()

    def on_mouse_leave(self, event) -> None:
        self._hover_col = -1
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

        # ── Visible window (on display/aggregated bars) ────────────────
        all_display = self._get_display_bars()
        total = len(all_display)
        n_vis = min(self.bars_visible, total)

        if self.view_offset > 0:
            end_i = max(n_vis, total - self.view_offset)
            start_i = max(0, end_i - n_vis)
            visible_bars = all_display[start_i:end_i]
        else:
            visible_bars = all_display[-n_vis:]

        if not visible_bars:
            return Text()

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

        # ── SL / TP lines ─────────────────────────────────────────────
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

        # ── Trade markers — remap bar indices to display TF ───────────
        ratio = self._tf_ratio
        entry_markers: dict[int, str] = {}
        exit_markers: dict[int, str] = {}
        entry_prices: dict[int, float] = {}
        exit_prices: dict[int, float] = {}
        for t in self._trades:
            r_idx = t.bar_index // ratio
            entry_markers[r_idx] = t.direction
            entry_prices[r_idx] = t.entry_price
            if t.exit_price is not None:
                e_idx = (t.bar_index + 1) // ratio
                exit_markers[e_idx] = "PROFIT" if (t.pnl or 0) >= 0 else "LOSS"
                exit_prices[e_idx] = t.exit_price

        volumes = [b.volume for b in visible_bars]
        max_vol = max(volumes) if any(v > 0 for v in volumes) else 1.0

        for i, bar in enumerate(visible_bars):
            col = i * bar_width
            if col >= width:
                break
            is_current = (i == len(visible_bars) - 1) and self.view_offset == 0
            is_bull = bar.close >= bar.open
            body_color = (
                CURRENT_BAR_COLOR if is_current else
                (BULL_COLOR if is_bull else BEAR_COLOR)
            )

            top_r = p2r(bar.high)
            bot_r = p2r(bar.low)
            body_top = min(p2r(bar.open), p2r(bar.close))
            body_bot = max(p2r(bar.open), p2r(bar.close))

            for r in range(max(0, top_r), min(chart_height, bot_r + 1)):
                if col < width:
                    canvas[r][col] = ("│", WICK_COLOR)
            body_char = "█" if bar_width >= 2 else "▌"
            for r in range(max(0, body_top), min(chart_height, body_bot + 1)):
                for w in range(bar_width):
                    if col + w < width:
                        canvas[r][col + w] = (body_char, body_color)

            bidx = bar.bar_index  # display bar sequential index
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

        # ── Header ────────────────────────────────────────────────────
        tf_label = _TF_LABELS.get(self._display_tf_minutes, f"{self._display_tf_minutes}m")
        last_bar = visible_bars[-1] if visible_bars else None
        result = Text()
        result.append(f" CANDLE  {tf_label}  [T=TPO] ", style=_HEADER_STYLE)
        if last_bar:
            bull = last_bar.close >= last_bar.open
            sym = "▲" if bull else "▼"
            result.append(
                f" {sym} {last_bar.close:.2f}",
                style="bold " + (BULL_COLOR if bull else BEAR_COLOR),
            )
        if self.view_offset > 0:
            result.append(
                f"  ◀ -{self.view_offset}  scroll=zoom  drag=pan",
                style="dim #4a6b8a",
            )
        else:
            result.append(
                f"  {n_vis}/{total} bars  scroll=zoom  drag=pan",
                style="dim #2a4a6a",
            )
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
    # TPO rendering  (always uses raw bars)                               #
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

        profile = self._tpo_profiles[-1]
        width = max(self.size.width - 6, 20)
        height = max(self.size.height - 4, 5)
        all_prices = sorted(profile.price_levels.keys(), reverse=True)
        visible_prices = all_prices[:height - 2]
        max_letters = max(len(profile.price_levels.get(p, "")) for p in visible_prices) if visible_prices else 1
        label_w = 10
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

            if is_poc:
                price_style, marker = f"bold {POC_COLOR}", "◆"
            elif is_vah or is_val:
                price_style, marker = f"bold {VAH_VAL_COLOR}", "─"
            elif is_ib_high or is_ib_low:
                price_style, marker = f"bold {IB_COLOR}", "·"
            else:
                price_style, marker = "#4a6b8a", " "

            result.append(f"{marker}{price:>8.2f} ", style=price_style)

            bar_len = int(len(letters) / max(max_letters, 1) * bar_w)
            bar_len = max(1, bar_len) if letters else 0

            if is_poc:
                bar_style, fill_char = f"bold {POC_COLOR}", "█"
            elif in_va:
                bar_style, fill_char = "#00884a", "█"
            else:
                bar_style, fill_char = "#224433", "▒"

            if letters:
                display = (letters[:bar_len] if len(letters) <= bar_len
                           else letters[:bar_len - 1] + "+")
                result.append(display.ljust(bar_len, fill_char), style=bar_style)

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

        result.append(
            f"  Sessions: {len(self._tpo_profiles)}  "
            f"| TPOs: {profile.tpo_count}  "
            f"| Singles: {len(profile.single_prints)}  "
            f"| Range: {profile.range_high:.2f}–{profile.range_low:.2f}  "
            f"[T=CANDLE]",
            style="dim #4a6b8a",
        )
        return result

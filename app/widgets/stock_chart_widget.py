"""Interactive stock price chart with mouse drag-to-pan and scroll-to-zoom."""
from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from ..engine.stock_fetcher import StockBar

_Y_W = 9        # Y-axis label column width
_BULL = "#00cc44"
_BEAR = "#ff3030"
_WICK = "#6a8fb5"
_CURR = "#00bfff"   # current (latest) bar
_HOVR = "#ffffff"   # hovered bar
_DIM = "dim #4a6b8a"
_HDR = "bold black on #ff8c00"


class StockChartWidget(Widget):
    """
    Bloomberg-dark ASCII candlestick chart.
    - Scroll up/down  → zoom in / out
    - Click & drag    → pan left (older) / right (newer)
    - Reactive view_offset / bars_visible control the visible window
    """

    DEFAULT_CSS = """
    StockChartWidget {
        height: 1fr;
        background: #070d18;
        border: solid #1e3a5f;
    }
    """

    bars_visible: reactive[int] = reactive(60)
    view_offset: reactive[int] = reactive(0)   # bars from the right end to skip

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._bars: list[StockBar] = []
        self._tf_label: str = ""
        self._dragging = False
        self._drag_start_x = 0
        self._drag_offset_start = 0
        self._hover_col: int = -1

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_bars(self, bars: list[StockBar], tf_label: str = "") -> None:
        self._bars = bars
        self._tf_label = tf_label
        self.view_offset = 0
        self.bars_visible = min(max(len(bars), 10), 80)
        self.refresh()

    def zoom_in(self, factor: float = 0.85) -> None:
        step = max(1, int(self.bars_visible * (1 - factor)))
        self.bars_visible = max(10, self.bars_visible - step)

    def zoom_out(self, factor: float = 0.85) -> None:
        step = max(1, int(self.bars_visible / factor - self.bars_visible))
        self.bars_visible = min(max(len(self._bars), 10), self.bars_visible + step)

    def jump_to_start(self) -> None:
        total = len(self._bars)
        self.view_offset = max(0, total - self.bars_visible)

    def jump_to_end(self) -> None:
        self.view_offset = 0

    # ── Mouse events ───────────────────────────────────────────────────────────

    def on_mouse_scroll_up(self, event) -> None:
        self.zoom_in()
        event.stop()

    def on_mouse_scroll_down(self, event) -> None:
        self.zoom_out()
        event.stop()

    def on_mouse_down(self, event) -> None:
        self._dragging = True
        self._drag_start_x = event.x
        self._drag_offset_start = self.view_offset
        self.capture_mouse()

    def on_mouse_move(self, event) -> None:
        if self._dragging and self._bars:
            chart_w = max(self.size.width - _Y_W - 2, 10)
            bar_w = max(1, min(3, chart_w // max(self.bars_visible, 1)))
            delta = int((self._drag_start_x - event.x) / max(bar_w, 1))
            total = len(self._bars)
            new_off = max(0, min(total - self.bars_visible, self._drag_offset_start + delta))
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

    # ── Render ─────────────────────────────────────────────────────────────────

    def render(self) -> Text:
        if not self._bars:
            txt = Text()
            txt.append(" CHART ", style=_HDR)
            txt.append(
                "\n\n  Select a time-frame to load data.\n\n"
                "  scroll ↕ = zoom  ·  click & drag = pan",
                style=_DIM,
            )
            return txt

        # Dimensions
        width = max(self.size.width - 2, 22)
        height = max(self.size.height - 2, 8)
        chart_w = max(10, width - _Y_W)
        vol_h = min(3, max(1, (height - 5) // 5))
        price_h = max(4, height - 4 - vol_h)
        canvas_h = price_h + vol_h

        # Window slice
        total = len(self._bars)
        n_vis = max(2, min(self.bars_visible, total))
        if self.view_offset > 0:
            end_i = min(total, max(n_vis, total - self.view_offset))
            start_i = max(0, end_i - n_vis)
        else:
            start_i = max(0, total - n_vis)
            end_i = total
        visible = self._bars[start_i:end_i]
        if not visible:
            return Text("No visible bars.", style=_DIM)

        # Price / volume ranges
        prices = [p for b in visible for p in (b.high, b.low)]
        p_min, p_max = min(prices), max(prices)
        p_range = p_max - p_min or 1.0
        volumes = [b.volume for b in visible]
        max_vol = max(volumes) if any(v > 0 for v in volumes) else 1.0

        bar_w = max(1, min(3, chart_w // max(len(visible), 1)))

        # Allocate canvas
        canvas: list[list[tuple[str, str]]] = [
            [(" ", "")] * chart_w for _ in range(canvas_h)
        ]

        def p2r(p: float) -> int:
            """Price → row (0=top)."""
            return int((p_max - p) / p_range * (price_h - 1))

        # Hovered bar index
        hover_idx = -1
        if self._hover_col >= _Y_W:
            hover_idx = (self._hover_col - _Y_W) // max(bar_w, 1)

        # Draw each bar
        for i, bar in enumerate(visible):
            col = i * bar_w
            if col >= chart_w:
                break
            is_bull = bar.close >= bar.open
            is_last = (i == len(visible) - 1) and self.view_offset == 0
            color = (
                _HOVR if i == hover_idx else
                _CURR if is_last else
                (_BULL if is_bull else _BEAR)
            )

            # Wick
            top_r, bot_r = p2r(bar.high), p2r(bar.low)
            for r in range(max(0, top_r), min(price_h, bot_r + 1)):
                if col < chart_w:
                    canvas[r][col] = ("│", _WICK)

            # Body
            body_top = min(p2r(bar.open), p2r(bar.close))
            body_bot = max(p2r(bar.open), p2r(bar.close))
            body_ch = "█" if bar_w >= 2 else "▌"
            for r in range(max(0, body_top), min(price_h, body_bot + 1)):
                for w in range(bar_w):
                    if col + w < chart_w:
                        canvas[r][col + w] = (body_ch, color)

            # Volume
            if bar.volume > 0:
                v_rows = max(1, int(bar.volume / max_vol * vol_h))
                for vr in range(v_rows):
                    row = canvas_h - 1 - vr
                    if price_h <= row < canvas_h and col < chart_w:
                        canvas[row][col] = ("▄", f"dim {color}")

        # Hover crosshair vertical line
        if 0 <= hover_idx < len(visible):
            hc = hover_idx * bar_w
            for r in range(price_h):
                if hc < chart_w and canvas[r][hc][0] == " ":
                    canvas[r][hc] = ("┆", "dim #2a4060")

        # ── Assemble text ──────────────────────────────────────────────────────
        result = Text()

        # Header: chart label + OHLCV of hovered/last bar
        result.append(" CHART ", style=_HDR)
        result.append(f"  {self._tf_label}", style="bold #4a6b8a")
        info = visible[hover_idx] if 0 <= hover_idx < len(visible) else visible[-1]
        sym = "▲" if info.close >= info.open else "▼"
        pc = _BULL if info.close >= info.open else _BEAR
        result.append(
            f"  {info.timestamp}  {sym} C:{info.close:.2f}  "
            f"O:{info.open:.2f}  H:{info.high:.2f}  L:{info.low:.2f}"
            f"  V:{info.volume:,.0f}",
            style=f"bold {pc}",
        )
        result.append(f"  [{start_i + 1}–{end_i}/{total}]", style=_DIM)
        result.append("\n")

        # Canvas rows + Y-axis labels
        p_step = p_range / max(price_h - 1, 1)
        label_every = max(1, price_h // 6)
        for r_idx, row in enumerate(canvas):
            if r_idx < price_h:
                if r_idx % label_every == 0:
                    p_at = p_max - r_idx * p_step
                    result.append(f"{p_at:>8.2f} ", style=_DIM)
                else:
                    result.append(" " * _Y_W)
            elif r_idx == price_h:
                result.append("─" * _Y_W, style="dim #1e3a5f")
            else:
                result.append(" " * _Y_W)
            for ch, sty in row:
                result.append(ch, style=Style.parse(sty) if sty else Style.null())
            result.append("\n")

        # X-axis date labels
        result.append(" " * _Y_W)
        x_line = [" "] * chart_w
        n_labels = min(7, len(visible))
        step = max(1, len(visible) // max(n_labels, 1))
        for i in range(0, len(visible), step):
            col = i * bar_w
            # Show last 5 chars: MM-DD or HH:MM
            lbl = visible[i].timestamp[-5:]
            for j, ch in enumerate(lbl):
                if col + j < chart_w:
                    x_line[col + j] = ch
        result.append("".join(x_line), style=_DIM)
        result.append("\n")

        # Footer hint bar
        zoom_pct = n_vis / max(total, 1) * 100
        pan_ind = "◀ " if self.view_offset > 0 else "  "
        at_end = "" if self.view_offset > 0 else " ▶ LIVE"
        drag_tip = "DRAGGING" if self._dragging else "drag=pan"
        result.append(
            f"  {pan_ind}scroll=zoom  {drag_tip}  "
            f"zoom {zoom_pct:.0f}%  {n_vis}/{total} bars{at_end}",
            style="dim #1e3060",
        )
        return result

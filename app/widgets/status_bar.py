"""StatusBar — bottom status line showing bar index, speed, firm profile, etc."""
from __future__ import annotations
from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text


SPEED_LABELS = {0: "⏸ PAUSED", 1: "▶ 1x", 5: "⏩ 5x", 25: "⏩⏩ 25x", 100: "⏩⏩ 100x", 999: "⚡ MAX"}


class StatusBar(Widget):
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $panel;
        padding: 0 1;
        dock: bottom;
    }
    """

    bar_index: reactive[int] = reactive(0)
    total_bars: reactive[int] = reactive(0)
    speed: reactive[int] = reactive(0)
    firm_name: reactive[str] = reactive("—")
    open_size: reactive[float] = reactive(0.0)
    unreal_pnl: reactive[float] = reactive(0.0)
    message: reactive[str] = reactive("[?]=Help  [Space]=Play/Pause  [S]=Strategy  [D]=Data  [Q]=Quit")

    def render(self) -> Text:
        t = Text()
        t.append(f" Bar {self.bar_index:,}/{self.total_bars:,} ", style="dim")
        t.append(" │ ", style="dim")

        speed_label = SPEED_LABELS.get(self.speed, f"{self.speed}x")
        speed_style = "yellow" if self.speed == 0 else "bright_cyan"
        t.append(speed_label, style=speed_style)

        t.append(" │ ", style="dim")
        t.append(f"Firm: {self.firm_name}", style="cyan")

        if self.open_size > 0:
            t.append(" │ ", style="dim")
            t.append(f"Pos: {self.open_size:.0f}ct", style="white")
            unreal_style = "bright_green" if self.unreal_pnl >= 0 else "bright_red"
            t.append(f" ${self.unreal_pnl:+,.2f}", style=unreal_style)

        t.append("  │ ", style="dim")
        t.append(self.message, style="dim")
        return t

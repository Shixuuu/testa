"""HotkeyHelp overlay screen."""
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static, Button
from textual.containers import Center, Vertical
from rich.table import Table
from rich import box


HOTKEYS = [
    ("Space", "Play / Pause replay"),
    ("] / →", "Step one bar forward"),
    ("[ / ←", "Step one bar backward"),
    ("F", "5× fast forward"),
    ("Shift+F", "25× fast forward"),
    ("M", "Max speed (full backtest)"),
    ("R", "Reset replay to bar 0"),
    ("T", "Toggle Candlestick ↔ TPO chart"),
    ("", ""),
    ("\\", "Toggle AI Chat panel (DeepSeek)"),
    ("N", "Open News & Economic Calendar"),
    ("", ""),
    ("S", "Open strategy panel"),
    ("D", "Open data manager"),
    ("P", "Open prop firm config"),
    ("A", "Open analytics report"),
    ("C", "Open Monte Carlo view"),
    ("E", "Export report HTML/CSV"),
    ("I", "Toggle indicator visibility"),
    ("Tab", "Cycle panel focus"),
    ("?", "Show this help"),
    ("Q", "Quit"),
]


class HotkeyHelp(ModalScreen):
    DEFAULT_CSS = """
    HotkeyHelp {
        align: center middle;
    }
    #help_container {
        width: 66;
        height: auto;
        border: thick #ff8c00;
        background: #070d18;
        padding: 1 2;
    }
    """

    BINDINGS = [("escape", "dismiss", "Close"), ("?", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        table = Table(
            title="Keyboard Reference",
            box=box.SIMPLE,
            show_header=True,
            padding=(0, 2),
        )
        table.add_column("Key", style="bold cyan", no_wrap=True)
        table.add_column("Action", style="white")
        for key, action in HOTKEYS:
            table.add_row(key, action)

        with Vertical(id="help_container"):
            yield Static(table)
            with Center():
                yield Button("Close [Esc]", variant="default", id="close_btn")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "close_btn":
            self.dismiss()

"""DataManager screen — browse and load data files."""
from __future__ import annotations
from pathlib import Path
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static, Button, Input, Select, Label, ListView, ListItem
from textual.containers import Vertical, Horizontal, Center
from textual.message import Message
from rich.text import Text

from ..engine.instruments import INSTRUMENTS


class DataLoaded(Message):
    def __init__(self, data_path: str, instrument: str, initial_cash: float):
        self.data_path = data_path
        self.instrument = instrument
        self.initial_cash = initial_cash
        super().__init__()


class DataManager(ModalScreen):
    DEFAULT_CSS = """
    DataManager {
        align: center middle;
    }
    #dm_container {
        width: 70;
        height: auto;
        max-height: 40;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #dm_container Label {
        margin-top: 1;
    }
    #file_list {
        height: 10;
        border: solid $panel;
    }
    #btn_row {
        margin-top: 1;
        height: auto;
    }
    """

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, default_dir: str = ".", **kwargs):
        super().__init__(**kwargs)
        self._default_dir = default_dir
        self._selected_path: str = ""

    def compose(self) -> ComposeResult:
        instruments = [(sym, sym) for sym in INSTRUMENTS.keys()] + [("CUSTOM", "Custom")]

        with Vertical(id="dm_container"):
            yield Static("[bold cyan]Data Manager[/bold cyan]")
            yield Label("Data directory:")
            yield Input(value=self._default_dir, id="dir_input", placeholder="Path to data directory")
            yield Button("Browse / Refresh", id="browse_btn", variant="default")
            yield Label("Select file:")
            yield ListView(id="file_list")
            yield Label("Selected:")
            yield Static("—", id="selected_label")
            yield Label("Instrument:")
            yield Select(instruments, id="instrument_select", value="ES")
            yield Label("Initial cash ($):")
            yield Input(value="50000", id="cash_input", placeholder="50000")
            with Horizontal(id="btn_row"):
                yield Button("Load", id="load_btn", variant="primary")
                yield Button("Cancel", id="cancel_btn", variant="default")

    def on_mount(self):
        self._refresh_file_list()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "browse_btn":
            self._refresh_file_list()
        elif event.button.id == "load_btn":
            if self._selected_path:
                instrument = self.query_one("#instrument_select", Select).value or "ES"
                cash_str = self.query_one("#cash_input", Input).value
                try:
                    cash = float(cash_str)
                except ValueError:
                    cash = 50000.0
                self.post_message(DataLoaded(self._selected_path, str(instrument), cash))
                self.dismiss()
        elif event.button.id == "cancel_btn":
            self.dismiss()

    def on_list_view_selected(self, event: ListView.Selected):
        item = event.item
        label = item.query_one(Static)
        path_str = str(label.renderable)
        self._selected_path = path_str
        self.query_one("#selected_label", Static).update(path_str[-60:])

    def _refresh_file_list(self):
        dir_input = self.query_one("#dir_input", Input)
        directory = Path(dir_input.value).expanduser()
        list_view = self.query_one("#file_list", ListView)
        list_view.clear()

        if not directory.exists():
            return

        files = sorted(
            [f for f in directory.rglob("*") if f.suffix.lower() in (".csv", ".parquet")],
            key=lambda f: f.name,
        )
        for f in files[:100]:
            list_view.append(ListItem(Static(str(f))))

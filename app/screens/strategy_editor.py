"""StrategyEditor screen — select strategy file, set params, enable hot-reload."""
from __future__ import annotations
from pathlib import Path
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static, Button, Input, Label, Switch, ListView, ListItem
from textual.containers import Vertical, Horizontal
from textual.message import Message


class StrategySelected(Message):
    def __init__(self, path: str, hot_reload: bool):
        self.path = path
        self.hot_reload = hot_reload
        super().__init__()


class StrategyEditor(ModalScreen):
    DEFAULT_CSS = """
    StrategyEditor {
        align: center middle;
    }
    #se_container {
        width: 70;
        height: auto;
        max-height: 40;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #se_container Label {
        margin-top: 1;
    }
    #strategy_list {
        height: 10;
        border: solid $panel;
    }
    #btn_row {
        margin-top: 1;
        height: auto;
    }
    """

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, strategies_dir: str = "strategies", **kwargs):
        super().__init__(**kwargs)
        self._strategies_dir = strategies_dir
        self._selected_path: str = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="se_container"):
            yield Static("[bold cyan]Strategy Editor[/bold cyan]")
            yield Label("Strategy directory:")
            yield Input(value=self._strategies_dir, id="dir_input")
            yield Button("Refresh", id="refresh_btn", variant="default")
            yield Label("Select strategy file:")
            yield ListView(id="strategy_list")
            yield Label("Selected:")
            yield Static("—", id="selected_label")
            yield Label("Custom path:")
            yield Input(value="", id="custom_path", placeholder="or enter path directly")
            with Horizontal():
                yield Label("Hot-reload:")
                yield Switch(value=True, id="hot_reload_switch")
            with Horizontal(id="btn_row"):
                yield Button("Load Strategy", id="load_btn", variant="primary")
                yield Button("Cancel", id="cancel_btn", variant="default")

    def on_mount(self):
        self._refresh_list()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "refresh_btn":
            self._refresh_list()
        elif event.button.id == "load_btn":
            custom = self.query_one("#custom_path", Input).value.strip()
            path = custom if custom else self._selected_path
            if path:
                hot_reload = self.query_one("#hot_reload_switch", Switch).value
                self.post_message(StrategySelected(path, hot_reload))
                self.dismiss()
        elif event.button.id == "cancel_btn":
            self.dismiss()

    def on_list_view_selected(self, event: ListView.Selected):
        item = event.item
        label = item.query_one(Static)
        path_str = str(label.renderable)
        self._selected_path = path_str
        self.query_one("#selected_label", Static).update(path_str[-60:])

    def _refresh_list(self):
        dir_input = self.query_one("#dir_input", Input)
        directory = Path(dir_input.value).expanduser()
        list_view = self.query_one("#strategy_list", ListView)
        list_view.clear()
        if directory.exists():
            for f in sorted(directory.glob("*.py")):
                list_view.append(ListItem(Static(str(f))))

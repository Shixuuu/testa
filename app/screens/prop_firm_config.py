"""PropFirmConfig screen — select firm profile and toggle rules."""
from __future__ import annotations
from pathlib import Path
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static, Button, Select, Switch, Label, ListView, ListItem
from textual.containers import Vertical, Horizontal
from textual.message import Message

from ..engine.prop_rules import PropFirmProfile


PROFILE_DIR = Path(__file__).parent.parent.parent / "firm_profiles"


class PropProfileSelected(Message):
    def __init__(self, profile: PropFirmProfile, enabled: bool):
        self.profile = profile
        self.enabled = enabled
        super().__init__()


class PropFirmConfig(ModalScreen):
    DEFAULT_CSS = """
    PropFirmConfig {
        align: center middle;
    }
    #pf_container {
        width: 70;
        height: auto;
        max-height: 45;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #pf_container Label { margin-top: 1; }
    #profile_list { height: 8; border: solid $panel; }
    #btn_row { margin-top: 1; height: auto; }
    """

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, profile_dir: str = str(PROFILE_DIR), **kwargs):
        super().__init__(**kwargs)
        self._profile_dir = Path(profile_dir)
        self._selected_profile: PropFirmProfile | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="pf_container"):
            yield Static("[bold cyan]Prop Firm Configuration[/bold cyan]")
            yield Label("Select firm profile:")
            yield ListView(id="profile_list")
            yield Label("Selected profile info:")
            yield Static("—", id="profile_info")
            with Horizontal():
                yield Label("Enable rules engine:")
                yield Switch(value=True, id="enabled_switch")
            with Horizontal(id="btn_row"):
                yield Button("Apply Profile", id="apply_btn", variant="primary")
                yield Button("Cancel", id="cancel_btn", variant="default")

    def on_mount(self):
        self._refresh_profiles()

    def _refresh_profiles(self):
        list_view = self.query_one("#profile_list", ListView)
        list_view.clear()
        if self._profile_dir.exists():
            for f in sorted(self._profile_dir.glob("*.toml")):
                list_view.append(ListItem(Static(f.stem)))

    def on_list_view_selected(self, event: ListView.Selected):
        item = event.item
        label = item.query_one(Static)
        profile_name = str(label.renderable)
        toml_path = self._profile_dir / f"{profile_name}.toml"
        if toml_path.exists():
            try:
                self._selected_profile = PropFirmProfile.from_toml(str(toml_path))
                p = self._selected_profile
                info = (
                    f"[bold]{p.name}[/bold]  |  Account: ${p.account_size:,.0f}\n"
                    f"Trailing DD: ${p.trailing_drawdown or 0:,.0f}  "
                    f"Daily Limit: ${p.daily_loss_limit or 0:,.0f}  "
                    f"Target: ${p.profit_target or 0:,.0f}\n"
                    f"Min Days: {p.min_trading_days}  "
                    f"Consistency: {(p.consistency_pct or 0) * 100:.0f}%"
                )
                self.query_one("#profile_info", Static).update(info)
            except Exception as e:
                self.query_one("#profile_info", Static).update(f"Error: {e}")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "apply_btn":
            if self._selected_profile:
                enabled = self.query_one("#enabled_switch", Switch).value
                self.post_message(PropProfileSelected(self._selected_profile, enabled))
                self.dismiss()
        elif event.button.id == "cancel_btn":
            self.dismiss()

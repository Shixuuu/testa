"""Main menu / launcher — Neovim-style selection screen."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Static
from rich.text import Text

_LOGO_LINES = [
    "  ███████╗██╗   ██╗████████╗██╗   ██╗██████╗ ███████╗███████╗",
    "  ██╔════╝██║   ██║╚══██╔══╝██║   ██║██╔══██╗██╔════╝██╔════╝",
    "  █████╗  ██║   ██║   ██║   ██║   ██║██████╔╝█████╗  ███████╗",
    "  ██╔══╝  ██║   ██║   ██║   ██║   ██║██╔══██╗██╔══╝  ╚════██║",
    "  ██║     ╚██████╔╝   ██║   ╚██████╔╝██║  ██║███████╗███████║",
    "  ╚═╝      ╚═════╝    ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚══════╝╚══════╝",
]

_MENU_ITEMS = [
    ("1", "Futures Backtest",  "Replay engine · Prop firm · Analytics · Monte Carlo"),
    ("2", "Stock Lookup",      "yfinance · Options chain · AI supply chain analysis"),
    ("3", "News & Calendar",   "Forex Factory · Economic events · Market calendar"),
    ("q", "Quit",              ""),
]

_SEPARATOR_IDX = 3  # index of the "Quit" item — draw line before it


class _MenuPanel(Static):
    """Renders menu items with a movable vim-cursor."""

    cursor: reactive[int] = reactive(0, layout=True)

    def render(self) -> Text:
        t = Text()
        for i, (key, label, desc) in enumerate(_MENU_ITEMS):
            if i == _SEPARATOR_IDX:
                t.append("    " + "─" * 56 + "\n", style="#1e3a5f")

            selected = i == self.cursor
            if selected:
                pfx       = "  ▸ "
                key_sty   = "bold #ff8c00"
                lbl_sty   = "bold #ffa040"
                desc_sty  = "#8aaccc"
                bg        = " on #0d2040"
            else:
                pfx       = "    "
                key_sty   = "#4a6b8a"
                lbl_sty   = "#8aaccc"
                desc_sty  = "#2a4a6a"
                bg        = ""

            t.append(pfx,              style=key_sty + bg)
            t.append(f"[{key}]",       style=key_sty + bg)
            t.append(f"  {label:<28}", style=lbl_sty + bg)
            t.append(f"{desc}",        style=desc_sty + bg)
            t.append("\n")
        return t


class MainMenu(Screen):
    """Full-screen launch menu. Dismissed with a string result."""

    CSS = """
    MainMenu {
        background: #07101e;
        align: center middle;
    }
    #mm_wrap {
        width: 70;
        height: auto;
        layout: vertical;
        align: center middle;
    }
    #mm_logo {
        text-align: center;
        color: #ff8c00;
        height: auto;
        margin-bottom: 1;
    }
    #mm_title {
        text-align: center;
        height: auto;
        margin-bottom: 3;
    }
    #mm_menu {
        height: auto;
        margin: 0 0 2 0;
    }
    #mm_hint {
        text-align: center;
        color: #2a4a6a;
        height: auto;
    }
    #mm_ver {
        text-align: center;
        color: #1e3a5f;
        height: auto;
        margin-top: 2;
    }
    """

    BINDINGS = [
        Binding("j", "cursor_down", "↓", show=False),
        Binding("k", "cursor_up",   "↑", show=False),
        Binding("down",  "cursor_down", "↓", show=False),
        Binding("up",    "cursor_up",   "↑", show=False),
        Binding("enter", "select",      "Select", show=False),
        Binding("1",     "pick_1",      "", show=False),
        Binding("2",     "pick_2",      "", show=False),
        Binding("3",     "pick_3",      "", show=False),
        Binding("q",     "pick_q",      "", show=False),
        Binding("escape","pick_q",      "", show=False),
    ]

    def compose(self) -> ComposeResult:
        logo_text = "\n".join(_LOGO_LINES)
        with Static(id="mm_wrap"):
            yield Static(logo_text, id="mm_logo")
            yield Static(
                "[bold #4a6b8a]─────  [bold #c8d8e8]B A C K T E S T   T E R M I N A L"
                "[bold #4a6b8a]  ─────\n"
                "[#2a4a6a]            Futures · Options · AI Analysis",
                id="mm_title",
            )
            yield _MenuPanel(id="mm_menu")
            yield Static(
                "[#2a4a6a]  j[/#2a4a6a][#1e3a5f]/[/#1e3a5f][#2a4a6a]k[/#2a4a6a]  navigate"
                "    [#2a4a6a]Enter[/#2a4a6a]  select"
                "    [#2a4a6a]1 2 3[/#2a4a6a]  jump",
                id="mm_hint",
            )
            yield Static(
                "[#1e3a5f]v2.0  ·  Backtrader · yfinance · Textual · DeepSeek",
                id="mm_ver",
            )

    def on_mount(self) -> None:
        self.query_one("#mm_menu", _MenuPanel).focus()

    # ── navigation ────────────────────────────────────────────────────────

    def action_cursor_down(self) -> None:
        panel = self.query_one("#mm_menu", _MenuPanel)
        panel.cursor = (panel.cursor + 1) % len(_MENU_ITEMS)

    def action_cursor_up(self) -> None:
        panel = self.query_one("#mm_menu", _MenuPanel)
        panel.cursor = (panel.cursor - 1) % len(_MENU_ITEMS)

    def action_select(self) -> None:
        panel = self.query_one("#mm_menu", _MenuPanel)
        key = _MENU_ITEMS[panel.cursor][0]
        self._launch(key)

    def action_pick_1(self) -> None: self._launch("1")
    def action_pick_2(self) -> None: self._launch("2")
    def action_pick_3(self) -> None: self._launch("3")
    def action_pick_q(self) -> None: self._launch("q")

    def _launch(self, key: str) -> None:
        mapping = {"1": "backtest", "2": "stock", "3": "news", "q": "quit"}
        self.dismiss(mapping.get(key, "quit"))

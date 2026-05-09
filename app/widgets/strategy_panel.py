"""StrategyPanel — displays current strategy params and indicators."""
from __future__ import annotations
from textual.widget import Widget
from textual.reactive import reactive
from rich.table import Table
from rich.text import Text
from rich import box


class StrategyPanel(Widget):
    DEFAULT_CSS = """
    StrategyPanel {
        height: 1fr;
        border: solid $panel;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._strategy_name: str = "No strategy"
        self._params: dict = {}
        self._indicators: list[str] = []
        self._data_file: str = "—"
        self._instrument: str = "—"

    def set_strategy(self, name: str, params: dict, indicators: list[str] = None):
        self._strategy_name = name
        self._params = params
        self._indicators = indicators or []
        self.refresh()

    def set_data_info(self, data_file: str, instrument: str):
        self._data_file = data_file
        self._instrument = instrument
        self.refresh()

    def render(self) -> Table:
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("Key", style="dim", no_wrap=True)
        table.add_column("Value", no_wrap=True)

        table.add_row(Text("Strategy", style="bold cyan"), self._strategy_name)
        table.add_row("Instrument", self._instrument)
        table.add_row("Data", self._data_file[-20:] if len(self._data_file) > 20 else self._data_file)

        if self._params:
            table.add_row("", "")
            table.add_row(Text("Parameters", style="bold"), "")
            for k, v in self._params.items():
                table.add_row(f"  {k}", str(v))

        if self._indicators:
            table.add_row("", "")
            table.add_row(Text("Indicators", style="bold"), "")
            for ind in self._indicators:
                table.add_row(f"  {ind}", "")

        return table

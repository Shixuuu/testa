"""MonteCarloView screen — run simulations and display fan chart."""
from __future__ import annotations
import asyncio
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static, Button, Select, Input, Label, ProgressBar
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.worker import Worker, get_current_worker
from rich.text import Text
from rich.table import Table
from rich import box

from ..engine.monte_carlo import MCConfig, MCResults, run_monte_carlo, fan_chart_data, METHOD_NAMES
from ..engine.events import TradeEvent
from ..engine.prop_rules import PropFirmProfile


class MonteCarloView(ModalScreen):
    DEFAULT_CSS = """
    MonteCarloView {
        align: center middle;
    }
    #mc_container {
        width: 80;
        height: auto;
        max-height: 50;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #mc_container Label { margin-top: 1; }
    #fan_chart { height: 20; border: solid $panel; overflow: auto; }
    #mc_results { height: 15; border: solid $panel; overflow-y: auto; }
    #btn_row { margin-top: 1; }
    """

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(
        self,
        trades: list[TradeEvent],
        initial_equity: float,
        prop_profile: PropFirmProfile | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._trades = trades
        self._initial_equity = initial_equity
        self._prop_profile = prop_profile
        self._results: MCResults | None = None

    def compose(self) -> ComposeResult:
        method_opts = [(m.replace("_", " ").title(), m) for m in METHOD_NAMES]

        with Vertical(id="mc_container"):
            yield Static("[bold cyan]Monte Carlo Simulation[/bold cyan]")
            with Horizontal():
                with Vertical():
                    yield Label("Method:")
                    yield Select(method_opts, id="method_select", value="trade_shuffle")
                with Vertical():
                    yield Label("Paths (N):")
                    yield Input(value="10000", id="n_paths_input", placeholder="10000")
                with Vertical():
                    yield Label("Seed (0=random):")
                    yield Input(value="0", id="seed_input", placeholder="0")
            yield Button("▶ Run Simulation", id="run_btn", variant="primary")
            yield Static("", id="status_label")
            yield Label("Fan Chart (equity paths):")
            yield Static("Run simulation to see chart.", id="fan_chart")
            yield Label("Results:")
            yield Static("—", id="mc_results")
            with Horizontal(id="btn_row"):
                yield Button("Close", id="close_btn", variant="default")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "run_btn":
            self._start_simulation()
        elif event.button.id == "close_btn":
            self.dismiss()

    def _start_simulation(self):
        method = str(self.query_one("#method_select", Select).value or "trade_shuffle")
        n_paths_str = self.query_one("#n_paths_input", Input).value
        seed_str = self.query_one("#seed_input", Input).value
        try:
            n_paths = int(n_paths_str)
        except ValueError:
            n_paths = 10000
        try:
            seed = int(seed_str)
        except ValueError:
            seed = None
        seed = seed if seed and seed > 0 else None

        cfg = MCConfig(n_paths=n_paths, method=method, seed=seed)
        self.query_one("#status_label", Static).update(
            f"Running {n_paths:,} paths ({method})…"
        )
        self.run_worker(
            self._run_mc(cfg),
            exclusive=True,
            name="mc_worker",
        )

    async def _run_mc(self, cfg: MCConfig):
        import concurrent.futures
        loop = asyncio.get_event_loop()
        trades = self._trades
        initial = self._initial_equity
        profile = self._prop_profile

        def _compute():
            return run_monte_carlo(trades, initial, cfg, profile)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            results = await loop.run_in_executor(pool, _compute)

        self._results = results
        self._display_results(results)

    def _display_results(self, r: MCResults):
        self.query_one("#status_label", Static).update(
            f"[green]Done — {r.n_paths:,} paths computed.[/green]"
        )

        # ASCII fan chart (simplified)
        chart_width = 60
        chart_height = 15
        fan = fan_chart_data(r, n_display_paths=50)
        canvas = self._render_fan_chart(fan, chart_width, chart_height, r)
        self.query_one("#fan_chart", Static).update(canvas)

        # Results table
        table = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
        table.add_column("Metric", style="dim")
        table.add_column("Value", justify="right", style="bold")

        def dol(v): return f"${v:,.2f}"
        def pct(v): return f"{v * 100:.1f}%"

        rows = [
            ("Median Final Equity", dol(r.median_final)),
            ("5th Pct Final Equity", dol(r.pct5_final)),
            ("95th Pct Final Equity", dol(r.pct95_final)),
            ("Prob of Ruin (<50% acct)", pct(r.prob_ruin)),
            ("Prob of Hitting Target", pct(r.prob_target)),
            ("Median Max Drawdown", dol(r.median_max_dd)),
            ("95th Pct Max Drawdown", dol(r.pct95_max_dd)),
            ("Expected Payoff", dol(r.expected_payoff)),
            ("Drawdown at Risk 95%", dol(r.dar_95)),
        ]
        if r.pass_rate > 0 or r.most_common_failure_rule:
            rows += [
                ("", ""),
                ("Prop Firm Pass Rate", pct(r.pass_rate)),
                ("Avg Days to Pass", f"{r.avg_days_to_pass:.1f}"),
                ("Top Failure Rule", r.most_common_failure_rule or "—"),
            ]
        for label, val in rows:
            table.add_row(label, val)
        self.query_one("#mc_results", Static).update(table)

    def _render_fan_chart(
        self,
        fan: dict,
        width: int,
        height: int,
        r: MCResults,
    ) -> Text:
        if not fan["median"]:
            return Text("No data to chart.")

        median = fan["median"]
        lo = fan["lo_bound"]
        hi = fan["hi_bound"]
        samples = fan["sample_paths"]

        all_vals = median + lo + hi
        eq_min = min(all_vals)
        eq_max = max(all_vals)
        eq_range = eq_max - eq_min or 1.0

        steps = len(median)
        canvas = [[" "] * width for _ in range(height)]

        def to_col(step: int) -> int:
            return int(step / max(steps - 1, 1) * (width - 1))

        def to_row(val: float) -> int:
            return height - 1 - int((val - eq_min) / eq_range * (height - 1))

        # Draw sample paths (dim)
        for path in samples[:30]:
            for step in range(1, len(path)):
                c = to_col(step)
                r_idx = to_row(path[step])
                if 0 <= r_idx < height and 0 <= c < width:
                    canvas[r_idx][c] = "·"

        # Draw bounds
        for step in range(len(lo)):
            c = to_col(step)
            for val, char in [(lo[step], "▁"), (hi[step], "▔")]:
                r_idx = to_row(val)
                if 0 <= r_idx < height and 0 <= c < width:
                    canvas[r_idx][c] = char

        # Draw median
        for step in range(len(median)):
            c = to_col(step)
            r_idx = to_row(median[step])
            if 0 <= r_idx < height and 0 <= c < width:
                canvas[r_idx][c] = "━"

        # Build Text
        result = Text()
        result.append(f"  ${eq_max:,.0f}\n", style="dim")
        for row in canvas:
            result.append("  " + "".join(row) + "\n")
        result.append(f"  ${eq_min:,.0f}", style="dim")
        return result

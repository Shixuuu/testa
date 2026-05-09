"""PropRulesPanel — live prop firm rules status display."""
from __future__ import annotations
from textual.widget import Widget
from textual.reactive import reactive
from rich.table import Table
from rich.text import Text
from rich import box
from rich.panel import Panel

from ..engine.prop_rules import PropFirmProfile, PropRulesState


class PropRulesPanel(Widget):
    DEFAULT_CSS = """
    PropRulesPanel {
        height: 1fr;
        border: solid $panel;
        padding: 0 1;
        overflow-y: auto;
    }
    PropRulesPanel.warning {
        border: solid yellow;
    }
    PropRulesPanel.breach {
        border: solid red;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._profile: PropFirmProfile | None = None
        self._state: PropRulesState | None = None

    def set_profile(self, profile: PropFirmProfile):
        self._profile = profile
        self._state = None
        self.refresh()

    def update_state(self, state: PropRulesState):
        self._state = state
        # Update border class based on worst violation
        self.remove_class("warning", "breach")
        if state.is_breached:
            self.add_class("breach")
        elif state.warnings:
            self.add_class("warning")
        self.refresh()

    def render(self) -> Table:
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("Rule", style="dim", no_wrap=True)
        table.add_column("Status", justify="right", no_wrap=True)

        p = self._profile
        s = self._state

        if not p:
            table.add_row("No profile loaded", "—")
            return table

        table.add_row(
            Text(f"[{p.name}]", style="bold cyan"),
            Text(f"${p.account_size:,.0f}", style="dim"),
        )

        def status_text(label: str, current: float, limit: float, inverse: bool = False) -> tuple:
            if limit == 0:
                return label, Text("N/A", style="dim")
            pct = current / limit
            if inverse:
                pct = 1 - pct
            if pct >= 1.0:
                color = "bright_red"
                icon = "✗"
            elif pct >= 0.9:
                color = "yellow"
                icon = "⚠"
            else:
                color = "bright_green"
                icon = "✓"
            return label, Text(f"{icon} ${current:,.0f} / ${limit:,.0f}", style=color)

        eq = s.current_equity if s else p.account_size
        floor = s.trailing_floor if s else (p.account_size - (p.trailing_drawdown or 0))
        daily_pnl_today = 0.0
        if s and s.daily_pnl:
            last_date = max(s.daily_pnl.keys())
            daily_pnl_today = s.daily_pnl.get(last_date, 0.0)

        if p.trailing_drawdown:
            gap = eq - floor
            label, val = status_text("Trail DD", p.trailing_drawdown - gap, p.trailing_drawdown)
            table.add_row(label, val)

        if p.daily_loss_limit:
            loss_used = max(0, -daily_pnl_today)
            label, val = status_text("Daily Loss", loss_used, p.daily_loss_limit)
            table.add_row(label, val)

        if p.max_drawdown:
            dd = p.account_size - eq
            label, val = status_text("Max DD", dd, p.max_drawdown)
            table.add_row(label, val)

        if p.profit_target:
            net = (s.total_net_profit if s else 0.0)
            pct_done = net / p.profit_target
            color = "bright_green" if pct_done >= 1.0 else "cyan"
            table.add_row(
                "Profit Target",
                Text(f"${net:,.0f} / ${p.profit_target:,.0f}", style=color),
            )

        if p.min_trading_days:
            days = len(s.trading_days) if s else 0
            color = "bright_green" if days >= p.min_trading_days else "dim"
            table.add_row(
                "Trading Days",
                Text(f"{days} / {p.min_trading_days}", style=color),
            )

        if p.consistency_pct:
            score = s.best_day_profit / s.total_net_profit if s and s.total_net_profit > 0 else 0
            ok = score <= p.consistency_pct
            color = "bright_green" if ok else "bright_red"
            table.add_row(
                "Consistency",
                Text(f"{score * 100:.1f}% (≤{p.consistency_pct * 100:.0f}%)", style=color),
            )

        # Overall status
        if s and s.is_breached:
            table.add_row("", "")
            table.add_row(
                Text("STATUS", style="bold"),
                Text(f"✗ BREACHED ({s.breach_rule})", style="bold bright_red"),
            )
        elif s and s.total_net_profit >= (p.profit_target or float("inf")):
            table.add_row("", "")
            table.add_row(
                Text("STATUS", style="bold"),
                Text("✓ TARGET HIT", style="bold bright_green"),
            )

        return table

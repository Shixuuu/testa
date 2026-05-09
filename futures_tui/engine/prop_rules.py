"""
Prop firm rules engine.
Loads firm profiles from TOML and checks bar-by-bar rule compliance.
"""
from __future__ import annotations
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Dict, List, Optional, Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore


@dataclass
class RuleStatus:
    ok: bool
    warning: bool
    breach: bool
    rule_name: str
    current_value: float
    limit_value: float
    pct_consumed: float
    details: str


@dataclass
class PropProfile:
    name: str
    account_size: float
    trailing_drawdown: float
    daily_loss_limit: float
    profit_target: float
    min_trading_days: int
    max_contracts: int
    overnight_positions: bool
    consistency_rule: bool
    consistency_pct: Optional[float]


class PropRulesEngine:
    """
    Tracks and enforces prop firm rules during a backtest.
    """

    def __init__(self) -> None:
        self._profile: Optional[PropProfile] = None
        self._initial_equity: float = 0.0
        self._peak_equity: float = 0.0
        self._trailing_floor: float = 0.0
        self._daily_pnl: float = 0.0
        self._current_date: Optional[date] = None
        self._trading_days: set = set()
        self._all_daily_pnl: List[float] = []
        self._max_single_day_profit: float = 0.0
        self._status_cache: Dict[str, RuleStatus] = {}
        self._breached: bool = False

    def load_profile(self, toml_path: str) -> None:
        """Load prop firm rules from a TOML file."""
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        firm = data["firm"]
        self._profile = PropProfile(
            name=firm["name"],
            account_size=float(firm["account_size"]),
            trailing_drawdown=float(firm["trailing_drawdown"]),
            daily_loss_limit=float(firm["daily_loss_limit"]),
            profit_target=float(firm["profit_target"]),
            min_trading_days=int(firm["min_trading_days"]),
            max_contracts=int(firm["max_contracts"]),
            overnight_positions=bool(firm["overnight_positions"]),
            consistency_rule=bool(firm["consistency_rule"]),
            consistency_pct=firm.get("consistency_pct"),
        )
        self._initial_equity = self._profile.account_size
        self._peak_equity = self._profile.account_size
        self._trailing_floor = self._profile.account_size - self._profile.trailing_drawdown

    def load_profile_dict(self, profile_dict: Dict[str, Any]) -> None:
        """Load profile from a dictionary (e.g., from config.toml)."""
        firm = profile_dict.get("firm", profile_dict)
        self._profile = PropProfile(
            name=str(firm.get("name", "Unknown")),
            account_size=float(firm.get("account_size", 50000)),
            trailing_drawdown=float(firm.get("trailing_drawdown", 2500)),
            daily_loss_limit=float(firm.get("daily_loss_limit", 1000)),
            profit_target=float(firm.get("profit_target", 3000)),
            min_trading_days=int(firm.get("min_trading_days", 5)),
            max_contracts=int(firm.get("max_contracts", 10)),
            overnight_positions=bool(firm.get("overnight_positions", False)),
            consistency_rule=bool(firm.get("consistency_rule", False)),
            consistency_pct=firm.get("consistency_pct"),
        )
        self._initial_equity = self._profile.account_size
        self._peak_equity = self._profile.account_size
        self._trailing_floor = self._profile.account_size - self._profile.trailing_drawdown

    def reset(self) -> None:
        """Reset all tracking state."""
        if self._profile:
            self._initial_equity = self._profile.account_size
            self._peak_equity = self._profile.account_size
            self._trailing_floor = self._profile.account_size - self._profile.trailing_drawdown
        self._daily_pnl = 0.0
        self._current_date = None
        self._trading_days = set()
        self._all_daily_pnl = []
        self._max_single_day_profit = 0.0
        self._status_cache = {}
        self._breached = False

    def check_bar(
        self,
        equity: float,
        daily_pnl: float,
        open_positions: int,
        bar_time: datetime,
    ) -> List[RuleStatus]:
        """
        Check all rules at the current bar.
        Returns a list of RuleStatus objects.
        """
        if self._profile is None:
            return []

        bar_date = bar_time.date()

        # Track new trading day
        if self._current_date != bar_date:
            if self._current_date is not None and self._daily_pnl != 0:
                self._all_daily_pnl.append(self._daily_pnl)
                if self._daily_pnl > self._max_single_day_profit:
                    self._max_single_day_profit = self._daily_pnl
            self._current_date = bar_date
            self._daily_pnl = daily_pnl
            if open_positions > 0 or daily_pnl != 0:
                self._trading_days.add(bar_date)
        else:
            self._daily_pnl = daily_pnl
            if open_positions > 0 or daily_pnl != 0:
                self._trading_days.add(bar_date)

        # Update trailing floor (trailing drawdown tracks equity peak)
        if equity > self._peak_equity:
            self._peak_equity = equity
            new_floor = self._peak_equity - self._profile.trailing_drawdown
            if new_floor > self._trailing_floor:
                self._trailing_floor = new_floor

        statuses: List[RuleStatus] = []

        # Check daily loss limit
        daily_loss_pct = abs(min(0.0, daily_pnl)) / self._profile.daily_loss_limit
        daily_breach = daily_pnl < -self._profile.daily_loss_limit
        statuses.append(RuleStatus(
            ok=not daily_breach and daily_loss_pct < 0.8,
            warning=not daily_breach and daily_loss_pct >= 0.8,
            breach=daily_breach,
            rule_name="Daily Loss Limit",
            current_value=daily_pnl,
            limit_value=-self._profile.daily_loss_limit,
            pct_consumed=daily_loss_pct,
            details=f"Daily P&L: ${daily_pnl:,.0f} / Limit: ${-self._profile.daily_loss_limit:,.0f}",
        ))

        # Check trailing drawdown
        equity_vs_floor = equity - self._trailing_floor
        trail_breach = equity <= self._trailing_floor
        trail_pct = max(0.0, (self._trailing_floor - equity + self._profile.trailing_drawdown) / self._profile.trailing_drawdown)
        trail_consumed = 1.0 - (equity_vs_floor / self._profile.trailing_drawdown) if not trail_breach else 1.0
        statuses.append(RuleStatus(
            ok=not trail_breach and trail_consumed < 0.8,
            warning=not trail_breach and trail_consumed >= 0.8,
            breach=trail_breach,
            rule_name="Trailing Drawdown",
            current_value=equity,
            limit_value=self._trailing_floor,
            pct_consumed=max(0.0, min(1.0, trail_consumed)),
            details=f"Equity: ${equity:,.0f} / Floor: ${self._trailing_floor:,.0f} (Buffer: ${equity_vs_floor:,.0f})",
        ))

        # Check profit target progress
        total_pnl = equity - self._initial_equity
        target_pct = total_pnl / self._profile.profit_target
        target_reached = total_pnl >= self._profile.profit_target
        statuses.append(RuleStatus(
            ok=target_reached,
            warning=not target_reached and target_pct >= 0.8,
            breach=False,
            rule_name="Profit Target",
            current_value=total_pnl,
            limit_value=self._profile.profit_target,
            pct_consumed=max(0.0, min(1.0, target_pct)),
            details=f"P&L: ${total_pnl:,.0f} / Target: ${self._profile.profit_target:,.0f} ({'REACHED' if target_reached else f'{target_pct*100:.1f}%'})",
        ))

        # Min trading days
        days_count = len(self._trading_days)
        days_pct = days_count / self._profile.min_trading_days
        statuses.append(RuleStatus(
            ok=days_count >= self._profile.min_trading_days,
            warning=days_count < self._profile.min_trading_days,
            breach=False,
            rule_name="Min Trading Days",
            current_value=float(days_count),
            limit_value=float(self._profile.min_trading_days),
            pct_consumed=min(1.0, days_pct),
            details=f"Days: {days_count} / Required: {self._profile.min_trading_days}",
        ))

        # Overnight positions check
        bar_time_only = bar_time.time()
        is_after_close = bar_time_only >= time(16, 0) or bar_time_only < time(9, 30)
        if not self._profile.overnight_positions and open_positions > 0 and is_after_close:
            overnight_breach = True
        else:
            overnight_breach = False
        statuses.append(RuleStatus(
            ok=not overnight_breach,
            warning=False,
            breach=overnight_breach,
            rule_name="No Overnight Positions",
            current_value=float(open_positions),
            limit_value=0.0,
            pct_consumed=1.0 if overnight_breach else 0.0,
            details=f"Positions after close: {open_positions}" if overnight_breach else "OK - No overnight positions",
        ))

        # Consistency rule (if applicable)
        if self._profile.consistency_rule and self._profile.consistency_pct and self._all_daily_pnl:
            best_day = max(self._all_daily_pnl) if self._all_daily_pnl else 0.0
            total_gross = sum(p for p in self._all_daily_pnl if p > 0)
            consistency_pct_actual = best_day / total_gross if total_gross > 0 else 0.0
            consistency_breach = consistency_pct_actual > self._profile.consistency_pct
            statuses.append(RuleStatus(
                ok=not consistency_breach,
                warning=consistency_pct_actual > self._profile.consistency_pct * 0.85,
                breach=consistency_breach,
                rule_name="Consistency Rule",
                current_value=consistency_pct_actual,
                limit_value=self._profile.consistency_pct,
                pct_consumed=min(1.0, consistency_pct_actual / self._profile.consistency_pct),
                details=f"Best day: {consistency_pct_actual*100:.1f}% of profits / Max: {self._profile.consistency_pct*100:.1f}%",
            ))

        self._status_cache = {s.rule_name: s for s in statuses}
        self._breached = any(s.breach for s in statuses)
        return statuses

    def get_status_dict(self) -> Dict[str, Any]:
        """Return a clean dict of all rule statuses for AI/display injection."""
        if not self._profile:
            return {"error": "No profile loaded"}

        result: Dict[str, Any] = {
            "firm_name": self._profile.name,
            "account_size": self._profile.account_size,
            "breached": self._breached,
            "rules": {},
        }
        for name, status in self._status_cache.items():
            result["rules"][name] = {
                "ok": status.ok,
                "warning": status.warning,
                "breach": status.breach,
                "current": status.current_value,
                "limit": status.limit_value,
                "pct_consumed": round(status.pct_consumed * 100, 1),
                "details": status.details,
            }
        return result

    @property
    def profile(self) -> Optional[PropProfile]:
        return self._profile

    @property
    def is_breached(self) -> bool:
        return self._breached

    @property
    def trailing_floor(self) -> float:
        return self._trailing_floor

    @property
    def peak_equity(self) -> float:
        return self._peak_equity

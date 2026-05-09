"""Prop Firm Rules Engine — enforces daily loss, trailing DD, consistency, etc."""
from __future__ import annotations
import sys
from dataclasses import dataclass, field
from datetime import datetime, date, time as dtime
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

from .events import TradeEvent, BarEvent, PropViolationEvent


@dataclass
class PropFirmProfile:
    name: str
    account_size: float

    # Loss rules
    daily_loss_limit: Optional[float] = None           # absolute $
    trailing_drawdown: Optional[float] = None          # $ threshold
    max_drawdown: Optional[float] = None               # static floor $
    weekly_loss_limit: Optional[float] = None
    loss_per_trade: Optional[float] = None

    # Profit & consistency
    profit_target: Optional[float] = None
    consistency_pct: Optional[float] = None            # e.g. 0.40 = 40%
    min_trading_days: int = 0
    min_profit_days: int = 0
    max_lots_per_trade: Optional[int] = None
    max_open_lots: Optional[int] = None

    # Session rules
    overnight_ban: bool = False
    weekend_ban: bool = True
    session_close: str = "16:00"                       # HH:MM local

    # Rule toggles (each key matches a rule name)
    enabled_rules: set[str] = field(default_factory=lambda: {
        "daily_loss_limit", "trailing_drawdown", "max_drawdown",
        "profit_target", "consistency", "min_trading_days",
        "max_lots", "overnight_ban", "weekend_ban",
    })

    @classmethod
    def from_toml(cls, path: str) -> "PropFirmProfile":
        with open(path, "rb") as f:
            data = tomllib.load(f)
        p = data.get("profile", data)
        enabled = set(p.get("enabled_rules", [
            "daily_loss_limit", "trailing_drawdown", "max_drawdown",
            "profit_target", "consistency", "min_trading_days",
            "max_lots", "overnight_ban", "weekend_ban",
        ]))
        return cls(
            name=p.get("name", "Custom"),
            account_size=float(p.get("account_size", 50000)),
            daily_loss_limit=_opt_float(p, "daily_loss_limit"),
            trailing_drawdown=_opt_float(p, "trailing_drawdown"),
            max_drawdown=_opt_float(p, "max_drawdown"),
            weekly_loss_limit=_opt_float(p, "weekly_loss_limit"),
            loss_per_trade=_opt_float(p, "loss_per_trade"),
            profit_target=_opt_float(p, "profit_target"),
            consistency_pct=_opt_float(p, "consistency_pct"),
            min_trading_days=int(p.get("min_trading_days", 0)),
            min_profit_days=int(p.get("min_profit_days", 0)),
            max_lots_per_trade=_opt_int(p, "max_lots_per_trade"),
            max_open_lots=_opt_int(p, "max_open_lots"),
            overnight_ban=bool(p.get("overnight_ban", False)),
            weekend_ban=bool(p.get("weekend_ban", True)),
            session_close=p.get("session_close", "16:00"),
            enabled_rules=enabled,
        )


def _opt_float(d: dict, k: str) -> Optional[float]:
    v = d.get(k)
    return float(v) if v is not None else None


def _opt_int(d: dict, k: str) -> Optional[int]:
    v = d.get(k)
    return int(v) if v is not None else None


WARNING_THRESHOLD = 0.10  # 10% of limit remaining → WARNING


@dataclass
class PropRulesState:
    """Live state tracked by the rules engine."""
    account_size: float
    initial_balance: float
    current_equity: float
    peak_equity: float
    trailing_floor: float

    daily_pnl: dict[str, float] = field(default_factory=dict)
    weekly_pnl: float = 0.0
    trading_days: set[str] = field(default_factory=set)
    profit_days: int = 0
    total_net_profit: float = 0.0
    best_day_profit: float = 0.0

    violations: list[PropViolationEvent] = field(default_factory=list)
    is_breached: bool = False
    breach_rule: Optional[str] = None

    open_lots: int = 0

    # Rule warning state
    warnings: set[str] = field(default_factory=set)

    def day_str(self, ts: datetime) -> str:
        return ts.strftime("%Y-%m-%d")

    def record_daily_pnl(self, ts: datetime, pnl: float):
        ds = self.day_str(ts)
        self.daily_pnl[ds] = self.daily_pnl.get(ds, 0.0) + pnl
        if pnl != 0:
            self.trading_days.add(ds)
        if self.daily_pnl[ds] > 0:
            self.profit_days = sum(1 for v in self.daily_pnl.values() if v > 0)
        self.best_day_profit = max(self.best_day_profit, self.daily_pnl.get(ds, 0.0))


class PropRulesEngine:
    """
    Evaluates prop firm rules after each trade and bar.
    Emits PropViolationEvent (WARNING or BREACH) when rules are triggered.
    """

    def __init__(self, profile: PropFirmProfile):
        self.profile = profile
        self.state = PropRulesState(
            account_size=profile.account_size,
            initial_balance=profile.account_size,
            current_equity=profile.account_size,
            peak_equity=profile.account_size,
            trailing_floor=profile.account_size - (profile.trailing_drawdown or 0),
        )
        self._enabled = profile.enabled_rules

    def toggle_rule(self, rule: str, enabled: bool):
        if enabled:
            self._enabled.add(rule)
        else:
            self._enabled.discard(rule)

    def on_trade_close(self, trade: TradeEvent, bar_index: int) -> list[PropViolationEvent]:
        if self.state.is_breached:
            return []

        pnl = trade.pnl or 0.0
        comm = trade.commission or 0.0
        net = pnl - comm
        ts = trade.timestamp

        self.state.total_net_profit += net
        self.state.current_equity += net
        self.state.record_daily_pnl(ts, net)

        # Update peak and trailing floor
        if self.state.current_equity > self.state.peak_equity:
            self.state.peak_equity = self.state.current_equity
            if self.profile.trailing_drawdown:
                self.state.trailing_floor = (
                    self.state.peak_equity - self.profile.trailing_drawdown
                )

        violations = []
        violations += self._check_daily_loss(ts, bar_index)
        violations += self._check_trailing_dd(ts, bar_index)
        violations += self._check_max_dd(ts, bar_index)
        violations += self._check_loss_per_trade(trade, bar_index)
        violations += self._check_weekly_loss(ts, bar_index)

        self.state.violations.extend(violations)
        return violations

    def on_trade_open(self, trade: TradeEvent, bar_index: int) -> list[PropViolationEvent]:
        self.state.open_lots += int(trade.size)
        violations = []
        if "max_lots" in self._enabled and self.profile.max_lots_per_trade:
            if trade.size > self.profile.max_lots_per_trade:
                violations.append(PropViolationEvent(
                    bar_index=bar_index,
                    timestamp=trade.timestamp,
                    rule="max_lots_per_trade",
                    level="BREACH",
                    message=f"Trade size {trade.size} exceeds max {self.profile.max_lots_per_trade} lots.",
                    account_balance=self.state.current_equity,
                ))
                self.state.is_breached = True
                self.state.breach_rule = "max_lots_per_trade"
        return violations

    def on_bar(self, bar: BarEvent) -> list[PropViolationEvent]:
        return []  # bar-level checks (overnight/weekend) could go here

    def summary(self) -> dict:
        p = self.profile
        s = self.state
        days_traded = len(s.trading_days)
        total_days_needed = p.min_trading_days
        profit_target_hit = (
            s.total_net_profit >= (p.profit_target or 0)
            if p.profit_target else False
        )

        # Consistency score: best single day / total net profit
        consistency_score = (
            s.best_day_profit / s.total_net_profit
            if s.total_net_profit > 0 else 0.0
        )
        consistency_ok = (
            consistency_score <= (p.consistency_pct or 1.0)
            if p.consistency_pct else True
        )

        return {
            "is_breached": s.is_breached,
            "breach_rule": s.breach_rule,
            "current_equity": s.current_equity,
            "peak_equity": s.peak_equity,
            "trailing_floor": s.trailing_floor,
            "total_net_profit": s.total_net_profit,
            "daily_pnl": dict(s.daily_pnl),
            "trading_days": days_traded,
            "min_trading_days": total_days_needed,
            "profit_days": s.profit_days,
            "profit_target": p.profit_target,
            "profit_target_hit": profit_target_hit,
            "consistency_score": consistency_score,
            "consistency_ok": consistency_ok,
            "violations_count": len(s.violations),
            "violations": s.violations,
        }

    # ------------------------------------------------------------------ #
    # Private rule checkers                                                #
    # ------------------------------------------------------------------ #

    def _check_daily_loss(self, ts: datetime, bar_index: int) -> list[PropViolationEvent]:
        if "daily_loss_limit" not in self._enabled:
            return []
        limit = self.profile.daily_loss_limit
        if not limit:
            return []
        ds = self.state.day_str(ts)
        day_pnl = self.state.daily_pnl.get(ds, 0.0)
        if day_pnl <= -limit:
            self.state.is_breached = True
            self.state.breach_rule = "daily_loss_limit"
            return [PropViolationEvent(
                bar_index=bar_index, timestamp=ts,
                rule="daily_loss_limit", level="BREACH",
                message=f"Daily loss ${abs(day_pnl):.2f} exceeded limit ${limit:.2f}.",
                account_balance=self.state.current_equity,
            )]
        elif day_pnl <= -(limit * (1 - WARNING_THRESHOLD)):
            if "daily_loss_limit_warn" not in self.state.warnings:
                self.state.warnings.add("daily_loss_limit_warn")
                return [PropViolationEvent(
                    bar_index=bar_index, timestamp=ts,
                    rule="daily_loss_limit", level="WARNING",
                    message=f"Daily loss ${abs(day_pnl):.2f} approaching limit ${limit:.2f}.",
                    account_balance=self.state.current_equity,
                )]
        else:
            self.state.warnings.discard("daily_loss_limit_warn")
        return []

    def _check_trailing_dd(self, ts: datetime, bar_index: int) -> list[PropViolationEvent]:
        if "trailing_drawdown" not in self._enabled:
            return []
        if not self.profile.trailing_drawdown:
            return []
        floor = self.state.trailing_floor
        eq = self.state.current_equity
        if eq <= floor:
            self.state.is_breached = True
            self.state.breach_rule = "trailing_drawdown"
            return [PropViolationEvent(
                bar_index=bar_index, timestamp=ts,
                rule="trailing_drawdown", level="BREACH",
                message=f"Equity ${eq:.2f} breached trailing floor ${floor:.2f}.",
                account_balance=eq,
            )]
        gap = eq - floor
        threshold = self.profile.trailing_drawdown
        if gap <= threshold * WARNING_THRESHOLD:
            if "trailing_dd_warn" not in self.state.warnings:
                self.state.warnings.add("trailing_dd_warn")
                return [PropViolationEvent(
                    bar_index=bar_index, timestamp=ts,
                    rule="trailing_drawdown", level="WARNING",
                    message=f"Only ${gap:.2f} above trailing floor ${floor:.2f}.",
                    account_balance=eq,
                )]
        else:
            self.state.warnings.discard("trailing_dd_warn")
        return []

    def _check_max_dd(self, ts: datetime, bar_index: int) -> list[PropViolationEvent]:
        if "max_drawdown" not in self._enabled:
            return []
        if not self.profile.max_drawdown:
            return []
        floor = self.state.initial_balance - self.profile.max_drawdown
        eq = self.state.current_equity
        if eq <= floor:
            self.state.is_breached = True
            self.state.breach_rule = "max_drawdown"
            return [PropViolationEvent(
                bar_index=bar_index, timestamp=ts,
                rule="max_drawdown", level="BREACH",
                message=f"Equity ${eq:.2f} breached max drawdown floor ${floor:.2f}.",
                account_balance=eq,
            )]
        return []

    def _check_loss_per_trade(self, trade: TradeEvent, bar_index: int) -> list[PropViolationEvent]:
        if not self.profile.loss_per_trade:
            return []
        pnl = (trade.pnl or 0.0) - trade.commission
        if pnl < -self.profile.loss_per_trade:
            return [PropViolationEvent(
                bar_index=bar_index, timestamp=trade.timestamp,
                rule="loss_per_trade", level="BREACH",
                message=f"Trade loss ${abs(pnl):.2f} exceeded per-trade limit ${self.profile.loss_per_trade:.2f}.",
                account_balance=self.state.current_equity,
            )]
        return []

    def _check_weekly_loss(self, ts: datetime, bar_index: int) -> list[PropViolationEvent]:
        if not self.profile.weekly_loss_limit:
            return []
        # Sum current week
        week_start = ts.date() - __import__("datetime").timedelta(days=ts.weekday())
        week_pnl = sum(
            v for ds, v in self.state.daily_pnl.items()
            if datetime.strptime(ds, "%Y-%m-%d").date() >= week_start
        )
        if week_pnl <= -self.profile.weekly_loss_limit:
            self.state.is_breached = True
            self.state.breach_rule = "weekly_loss_limit"
            return [PropViolationEvent(
                bar_index=bar_index, timestamp=ts,
                rule="weekly_loss_limit", level="BREACH",
                message=f"Weekly loss ${abs(week_pnl):.2f} exceeded limit.",
                account_balance=self.state.current_equity,
            )]
        return []

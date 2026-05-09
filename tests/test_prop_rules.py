"""Tests for PropRulesEngine — 100% enforcement fidelity required."""
import pytest
from datetime import datetime
from app.engine.prop_rules import PropFirmProfile, PropRulesEngine
from app.engine.events import TradeEvent


def make_trade(pnl: float, commission: float = 2.0, ts: datetime = None, direction: str = "LONG") -> TradeEvent:
    ts = ts or datetime(2024, 1, 15, 10, 30)
    return TradeEvent(
        bar_index=1,
        timestamp=ts,
        direction=direction,
        entry_price=4500.0,
        exit_price=4500.0 + pnl / 50,
        size=1,
        pnl=pnl,
        commission=commission,
        is_open=False,
        trade_id=1,
    )


def make_profile(**kwargs) -> PropFirmProfile:
    defaults = dict(
        name="Test",
        account_size=50000.0,
        daily_loss_limit=1000.0,
        trailing_drawdown=2500.0,
        profit_target=3000.0,
        enabled_rules={"daily_loss_limit", "trailing_drawdown", "profit_target"},
    )
    defaults.update(kwargs)
    return PropFirmProfile(**defaults)


class TestDailyLossLimit:
    def test_no_breach_below_limit(self):
        profile = make_profile()
        engine = PropRulesEngine(profile)
        trade = make_trade(-800.0)  # Under $1000 limit
        violations = engine.on_trade_close(trade, 1)
        assert not engine.state.is_breached
        assert all(v.level != "BREACH" for v in violations)

    def test_breach_at_limit(self):
        profile = make_profile()
        engine = PropRulesEngine(profile)
        trade = make_trade(-1001.0)  # Over $1000 limit
        violations = engine.on_trade_close(trade, 1)
        assert engine.state.is_breached
        assert engine.state.breach_rule == "daily_loss_limit"
        assert any(v.level == "BREACH" and v.rule == "daily_loss_limit" for v in violations)

    def test_warning_at_90_pct(self):
        profile = make_profile()
        engine = PropRulesEngine(profile)
        trade = make_trade(-910.0)  # 91% of limit → warning
        violations = engine.on_trade_close(trade, 1)
        assert not engine.state.is_breached
        assert any(v.level == "WARNING" for v in violations)

    def test_multiple_trades_accumulate(self):
        profile = make_profile()
        engine = PropRulesEngine(profile)
        engine.on_trade_close(make_trade(-600.0), 1)
        assert not engine.state.is_breached
        violations = engine.on_trade_close(make_trade(-500.0), 2)
        assert engine.state.is_breached

    def test_different_days_separate_limits(self):
        profile = make_profile()
        engine = PropRulesEngine(profile)
        ts1 = datetime(2024, 1, 15, 10, 0)
        ts2 = datetime(2024, 1, 16, 10, 0)
        engine.on_trade_close(make_trade(-900.0, ts=ts1), 1)
        violations = engine.on_trade_close(make_trade(-900.0, ts=ts2), 2)
        # Each day separate — no breach
        assert not engine.state.is_breached

    def test_disabled_rule_no_breach(self):
        # Only trailing_drawdown enabled; lose $900 (< trailing DD of $2500) → no breach
        profile = make_profile(enabled_rules={"trailing_drawdown"})
        engine = PropRulesEngine(profile)
        engine.on_trade_close(make_trade(-900.0), 1)
        assert not engine.state.is_breached


class TestTrailingDrawdown:
    def test_no_breach_above_floor(self):
        # Only trailing_drawdown enabled; lose $2000 (net $2002 w/ commission)
        # floor = 50000 - 2500 = 47500; equity = 47998 > 47500. No breach.
        profile = make_profile(
            trailing_drawdown=2500.0,
            daily_loss_limit=None,
            enabled_rules={"trailing_drawdown"},
        )
        engine = PropRulesEngine(profile)
        engine.on_trade_close(make_trade(-2000.0), 1)
        assert not engine.state.is_breached

    def test_breach_at_floor(self):
        profile = make_profile(
            trailing_drawdown=2500.0,
            daily_loss_limit=None,
            enabled_rules={"trailing_drawdown"},
        )
        engine = PropRulesEngine(profile)
        # Equity drops to 47499 < floor 47500
        violations = engine.on_trade_close(make_trade(-2501.0), 1)
        assert engine.state.is_breached
        assert engine.state.breach_rule == "trailing_drawdown"

    def test_floor_rises_with_profit(self):
        # commission=$2 per trade, so net profit on $2000 trade = $1998
        profile = make_profile(
            trailing_drawdown=2500.0,
            daily_loss_limit=None,
            enabled_rules={"trailing_drawdown"},
        )
        engine = PropRulesEngine(profile)
        # Gain $2000 gross → net $1998; peak = 51998, floor = 51998 - 2500 = 49498
        engine.on_trade_close(make_trade(2000.0), 1)
        assert engine.state.peak_equity == pytest.approx(51998.0)
        assert engine.state.trailing_floor == pytest.approx(49498.0)

        # Lose $2350 gross → net $2352; equity = 51998 - 2352 = 49646 > floor 49498. OK.
        engine.on_trade_close(make_trade(-2350.0), 2)
        assert not engine.state.is_breached

        # Lose $200 more → equity = 49646 - 202 = 49444 < floor 49498. BREACH.
        engine.on_trade_close(make_trade(-200.0), 3)
        assert engine.state.is_breached

    def test_floor_does_not_move_down(self):
        profile = make_profile(
            trailing_drawdown=2500.0,
            daily_loss_limit=None,
            enabled_rules={"trailing_drawdown"},
        )
        engine = PropRulesEngine(profile)
        initial_floor = engine.state.trailing_floor
        engine.on_trade_close(make_trade(-500.0), 1)
        assert engine.state.trailing_floor == initial_floor  # floor doesn't decrease


class TestProfitTarget:
    def test_target_tracked(self):
        profile = make_profile(profit_target=3000.0, enabled_rules={"profit_target"})
        engine = PropRulesEngine(profile)
        engine.on_trade_close(make_trade(3100.0), 1)
        summary = engine.summary()
        assert summary["profit_target_hit"] is True

    def test_target_not_hit(self):
        profile = make_profile(profit_target=3000.0, enabled_rules={"profit_target"})
        engine = PropRulesEngine(profile)
        engine.on_trade_close(make_trade(2000.0), 1)
        summary = engine.summary()
        assert summary["profit_target_hit"] is False


class TestConsistencyRule:
    def test_consistency_violation(self):
        profile = make_profile(
            consistency_pct=0.40,
            enabled_rules={"consistency", "profit_target"},
        )
        engine = PropRulesEngine(profile)
        ts1 = datetime(2024, 1, 15, 10, 0)
        ts2 = datetime(2024, 1, 16, 10, 0)
        engine.on_trade_close(make_trade(400.0, ts=ts1), 1)
        engine.on_trade_close(make_trade(600.0, ts=ts2), 2)
        summary = engine.summary()
        # Best day = 600, total = 1000, ratio = 60% > 40% limit
        assert not summary["consistency_ok"]

    def test_consistency_ok(self):
        profile = make_profile(
            consistency_pct=0.40,
            enabled_rules={"consistency", "profit_target"},
        )
        engine = PropRulesEngine(profile)
        for i in range(5):
            ts = datetime(2024, 1, 15 + i, 10, 0)
            engine.on_trade_close(make_trade(200.0, ts=ts), i)
        summary = engine.summary()
        # Best day = 200, total = 1000, ratio = 20% < 40%
        assert summary["consistency_ok"]


class TestMinTradingDays:
    def test_days_tracked(self):
        profile = make_profile(min_trading_days=5, enabled_rules={"min_trading_days"})
        engine = PropRulesEngine(profile)
        for i in range(3):
            ts = datetime(2024, 1, 15 + i, 10, 0)
            engine.on_trade_close(make_trade(100.0, ts=ts), i)
        summary = engine.summary()
        assert summary["trading_days"] == 3
        assert summary["min_trading_days"] == 5

"""Tests for Monte Carlo simulation module."""
import pytest
import numpy as np
from datetime import datetime
from app.engine.monte_carlo import (
    MCConfig, run_monte_carlo, fan_chart_data, METHOD_NAMES,
    _extract_returns, _generate_paths, _returns_to_equity,
    _compute_max_drawdowns,
)
from app.engine.events import TradeEvent
from app.engine.prop_rules import PropFirmProfile


def make_trade(pnl: float, commission: float = 2.0, idx: int = 1) -> TradeEvent:
    return TradeEvent(
        bar_index=idx,
        timestamp=datetime(2024, 1, idx % 28 + 1, 10, 30),
        direction="LONG",
        entry_price=4500.0,
        exit_price=4510.0,
        size=1,
        pnl=pnl,
        commission=commission,
        is_open=False,
        trade_id=idx,
    )


def build_trades(pnls: list[float]) -> list[TradeEvent]:
    return [make_trade(p, idx=i + 1) for i, p in enumerate(pnls)]


class TestExtractReturns:
    def test_returns_exclude_commission(self):
        trades = build_trades([100.0, -50.0])
        returns = _extract_returns(trades)
        assert returns[0] == pytest.approx(98.0)
        assert returns[1] == pytest.approx(-52.0)

    def test_open_trades_excluded(self):
        closed = make_trade(100.0)
        open_trade = TradeEvent(1, datetime(2024, 1, 1), "LONG", 4500, None, 1, None, 0, True, 99)
        returns = _extract_returns([closed, open_trade])
        assert len(returns) == 1


class TestGeneratePaths:
    def setup_method(self):
        self.returns = np.array([100.0, -50.0, 200.0, -30.0, 150.0])
        self.rng = np.random.default_rng(42)

    def test_trade_shuffle_shape(self):
        paths = _generate_paths(self.returns, "trade_shuffle", 100, 10, self.rng)
        assert paths.shape == (100, 10)

    def test_bootstrap_shape(self):
        paths = _generate_paths(self.returns, "bootstrap", 50, 8, self.rng)
        assert paths.shape == (50, 8)

    def test_parametric_normal_shape(self):
        paths = _generate_paths(self.returns, "parametric_normal", 200, 20, self.rng)
        assert paths.shape == (200, 20)

    def test_parametric_t_shape(self):
        paths = _generate_paths(self.returns, "parametric_t", 100, 15, self.rng)
        assert paths.shape == (100, 15)

    def test_block_bootstrap_shape(self):
        paths = _generate_paths(self.returns, "block_bootstrap", 100, 10, self.rng)
        assert paths.shape == (100, 10)

    def test_invalid_method_raises(self):
        with pytest.raises(ValueError):
            _generate_paths(self.returns, "nonexistent", 10, 5, self.rng)


class TestEquityConversion:
    def test_equity_starts_at_initial(self):
        paths = np.array([[100.0, -50.0, 200.0]])
        equity = _returns_to_equity(paths, 50000.0)
        assert equity[0, 0] == 50000.0

    def test_equity_cumulative(self):
        paths = np.array([[100.0, -50.0]])
        equity = _returns_to_equity(paths, 1000.0)
        assert equity[0, 1] == pytest.approx(1100.0)
        assert equity[0, 2] == pytest.approx(1050.0)


class TestMaxDrawdowns:
    def test_monotone_increasing_no_dd(self):
        equity = np.array([[1000, 1100, 1200, 1300]])
        dd = _compute_max_drawdowns(equity)
        assert dd[0] == pytest.approx(0.0)

    def test_known_drawdown(self):
        equity = np.array([[1000, 1200, 900, 1100]])
        dd = _compute_max_drawdowns(equity)
        assert dd[0] == pytest.approx(300.0)


class TestRunMonteCarlo:
    def setup_method(self):
        self.trades = build_trades([100, -50, 200, -30, 150, 80, -60, 120, -40, 90] * 5)

    def test_basic_run(self):
        cfg = MCConfig(n_paths=100, method="trade_shuffle", seed=42)
        result = run_monte_carlo(self.trades, 50000.0, cfg)
        assert result.n_paths == 100
        assert result.equity_paths.shape[0] == 100
        assert 0 <= result.prob_ruin <= 1
        assert 0 <= result.prob_target <= 1

    def test_all_methods_run(self):
        for method in METHOD_NAMES:
            cfg = MCConfig(n_paths=50, method=method, seed=1)
            result = run_monte_carlo(self.trades, 50000.0, cfg)
            assert result.n_paths == 50

    def test_seed_reproducible(self):
        cfg1 = MCConfig(n_paths=100, method="trade_shuffle", seed=99)
        cfg2 = MCConfig(n_paths=100, method="trade_shuffle", seed=99)
        r1 = run_monte_carlo(self.trades, 50000.0, cfg1)
        r2 = run_monte_carlo(self.trades, 50000.0, cfg2)
        assert np.allclose(r1.final_equities, r2.final_equities)

    def test_empty_trades(self):
        cfg = MCConfig(n_paths=100, seed=42)
        result = run_monte_carlo([], 50000.0, cfg)
        assert result.n_paths == 0

    def test_prop_integration(self):
        profile = PropFirmProfile(
            name="Test",
            account_size=50000.0,
            trailing_drawdown=2500.0,
            profit_target=3000.0,
            enabled_rules={"trailing_drawdown", "profit_target"},
        )
        cfg = MCConfig(n_paths=200, method="trade_shuffle", seed=42)
        result = run_monte_carlo(self.trades, 50000.0, cfg, profile)
        assert 0.0 <= result.pass_rate <= 1.0

    def test_percentile_order(self):
        cfg = MCConfig(n_paths=500, seed=42)
        r = run_monte_carlo(self.trades, 50000.0, cfg)
        assert r.pct5_final <= r.median_final <= r.pct95_final


class TestFanChartData:
    def test_fan_chart_keys(self):
        trades = build_trades([100, -50, 80, -20] * 10)
        cfg = MCConfig(n_paths=50, seed=42)
        result = run_monte_carlo(trades, 50000.0, cfg)
        fan = fan_chart_data(result)
        assert "sample_paths" in fan
        assert "median" in fan
        assert "lo_bound" in fan
        assert "hi_bound" in fan

    def test_fan_chart_lengths_equal(self):
        trades = build_trades([100, -50, 80] * 5)
        cfg = MCConfig(n_paths=100, seed=42)
        result = run_monte_carlo(trades, 50000.0, cfg)
        fan = fan_chart_data(result)
        assert len(fan["median"]) == len(fan["lo_bound"]) == len(fan["hi_bound"])

    def test_bounds_ordering(self):
        trades = build_trades([100, -50, 80] * 5)
        cfg = MCConfig(n_paths=200, seed=42)
        result = run_monte_carlo(trades, 50000.0, cfg)
        fan = fan_chart_data(result)
        for lo, med, hi in zip(fan["lo_bound"], fan["median"], fan["hi_bound"]):
            assert lo <= hi  # lo <= hi always

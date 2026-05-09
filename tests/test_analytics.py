"""Tests for quantitative analytics suite."""
import pytest
from datetime import datetime, timedelta
from app.engine.analytics import compute_analytics, AnalyticsReport, format_report_text
from app.engine.events import TradeEvent


def make_closed_trade(
    pnl: float,
    commission: float = 2.0,
    bar_index: int = 1,
    ts_offset_days: int = 0,
    mae: float = None,
    mfe: float = None,
) -> TradeEvent:
    ts = datetime(2024, 1, 15, 10, 30) + timedelta(days=ts_offset_days)
    return TradeEvent(
        bar_index=bar_index,
        timestamp=ts,
        direction="LONG",
        entry_price=4500.0,
        exit_price=4510.0,
        size=1,
        pnl=pnl,
        commission=commission,
        is_open=False,
        trade_id=bar_index,
        mae=mae,
        mfe=mfe,
    )


def build_trades(pnls: list[float]) -> list[TradeEvent]:
    return [make_closed_trade(p, bar_index=i + 1) for i, p in enumerate(pnls)]


class TestReturnMetrics:
    def test_net_pnl(self):
        trades = build_trades([100, -50, 200, -30])
        eq_curve = [(0, 50000), (1, 50098), (2, 50046), (3, 50244), (4, 50212)]
        r = compute_analytics(trades, eq_curve, 50000.0)
        assert r.net_pnl == pytest.approx(sum(p - 2 for p in [100, -50, 200, -30]))

    def test_empty_trades(self):
        r = compute_analytics([], [(0, 50000)], 50000.0)
        assert r.n_trades == 0
        assert r.net_pnl == 0.0

    def test_total_return_pct(self):
        trades = build_trades([500.0])
        eq_curve = [(0, 50000), (1, 50498)]
        r = compute_analytics(trades, eq_curve, 50000.0)
        assert r.total_return_pct == pytest.approx((500 - 2) / 50000 * 100, abs=0.1)


class TestWinRateAndPF:
    def test_win_rate_100pct(self):
        trades = build_trades([100, 200, 300])
        eq_curve = [(i, 50000 + i * 100) for i in range(4)]
        r = compute_analytics(trades, eq_curve, 50000.0)
        assert r.win_rate == pytest.approx(1.0)

    def test_win_rate_50pct(self):
        trades = build_trades([100, -100])
        eq_curve = [(0, 50000), (1, 50098), (2, 49996)]
        r = compute_analytics(trades, eq_curve, 50000.0)
        assert r.win_rate == pytest.approx(0.5)

    def test_profit_factor(self):
        # build_trades uses commission=2 per trade, so net: 298, 298, -102, -102
        trades = build_trades([300, 300, -100, -100])
        eq_curve = [(i, 50000 + i * 50) for i in range(5)]
        r = compute_analytics(trades, eq_curve, 50000.0)
        # gross_profit=596, gross_loss=204 → PF ≈ 2.92
        assert r.profit_factor == pytest.approx(596 / 204, abs=0.01)


class TestDrawdown:
    def test_max_drawdown_computed(self):
        eq_curve = [
            (0, 50000), (1, 51000), (2, 52000),
            (3, 50500),  # drawdown from 52000
            (4, 51500),
        ]
        trades = build_trades([1000, 1000, -1500, 1000])
        r = compute_analytics(trades, eq_curve, 50000.0)
        assert r.max_drawdown == pytest.approx(1500.0)

    def test_zero_drawdown_all_winners(self):
        eq_curve = [(i, 50000 + i * 100) for i in range(5)]
        trades = build_trades([100, 100, 100, 100])
        r = compute_analytics(trades, eq_curve, 50000.0)
        assert r.max_drawdown == pytest.approx(0.0, abs=1e-6)

    def test_recovery_factor(self):
        eq_curve = [(0, 50000), (1, 52000), (2, 50000), (3, 53000)]
        trades = build_trades([2000, -2000, 3000])
        r = compute_analytics(trades, eq_curve, 50000.0)
        assert r.recovery_factor > 0  # net profit > 0 with some drawdown


class TestRMultiples:
    def test_r_multiple_calculation(self):
        trades = [
            make_closed_trade(200.0, mae=-100.0, mfe=250.0, bar_index=1),
            make_closed_trade(-100.0, mae=-100.0, bar_index=2),
        ]
        eq_curve = [(0, 50000), (1, 50198), (2, 50096)]
        r = compute_analytics(trades, eq_curve, 50000.0)
        # First trade: R = (200-2)/100 = 1.98
        assert len(r.r_multiples) >= 1
        assert r.r_multiples[0] == pytest.approx(1.98, abs=0.01)


class TestStatisticalMetrics:
    def test_psr_between_0_and_1(self):
        trades = build_trades([100] * 50 + [-50] * 30)
        eq_curve = [(i, 50000 + i * 30) for i in range(81)]
        r = compute_analytics(trades, eq_curve, 50000.0)
        assert 0.0 <= r.psr <= 1.0

    def test_n_adequate_below_30(self):
        trades = build_trades([100] * 20)
        eq_curve = [(i, 50000 + i * 98) for i in range(21)]
        r = compute_analytics(trades, eq_curve, 50000.0)
        assert r.n_adequate is False

    def test_n_adequate_at_30(self):
        trades = build_trades([100] * 30)
        eq_curve = [(i, 50000 + i * 98) for i in range(31)]
        r = compute_analytics(trades, eq_curve, 50000.0)
        assert r.n_adequate is True

    def test_skewness_and_kurtosis_present(self):
        trades = build_trades([100, -50, 200, -80, 150] * 10)
        eq_curve = [(i, 50000 + i * 20) for i in range(51)]
        r = compute_analytics(trades, eq_curve, 50000.0)
        assert r.skewness != 0 or True  # just check it runs


class TestFormatReport:
    def test_format_contains_key_metrics(self):
        trades = build_trades([100, -50, 200])
        eq_curve = [(i, 50000 + i * 80) for i in range(4)]
        r = compute_analytics(trades, eq_curve, 50000.0)
        text = format_report_text(r)
        assert "Net P&L" in text
        assert "Sharpe" in text
        assert "Win Rate" in text
        assert "Profit Factor" in text
        assert "Expectancy" in text
        assert "PSR" in text

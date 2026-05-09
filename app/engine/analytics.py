"""Quantitative analytics suite — 30+ metrics including PSR, DSR, MAE/MFE."""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import numpy as np
from scipy import stats

from .events import TradeEvent


@dataclass
class AnalyticsReport:
    # Return metrics
    net_pnl: float = 0.0
    total_return_pct: float = 0.0
    cagr: float = 0.0
    daily_returns: list[float] = field(default_factory=list)

    # Risk-adjusted
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    omega: float = 0.0
    ulcer_index: float = 0.0
    upi: float = 0.0
    kappa3: float = 0.0

    # Trade-level
    n_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_rr: float = 0.0
    avg_r_multiple: float = 0.0
    r_multiples: list[float] = field(default_factory=list)
    largest_win: float = 0.0
    largest_loss: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    avg_trade_duration_bars: float = 0.0
    avg_mae: float = 0.0
    avg_mfe: float = 0.0
    avg_etd: float = 0.0

    # Drawdown
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    recovery_factor: float = 0.0
    time_underwater_pct: float = 0.0

    # Statistical validity
    t_statistic: float = 0.0
    p_value: float = 1.0
    sharpe_t_stat: float = 0.0
    psr: float = 0.0
    dsr: float = 0.0
    n_adequate: bool = False
    ljung_box_pvalue: float = 1.0
    skewness: float = 0.0
    kurtosis: float = 0.0

    # Equity curve data
    equity_curve: list[tuple[int, float]] = field(default_factory=list)
    initial_equity: float = 0.0


def compute_analytics(
    trades: list[TradeEvent],
    equity_curve: list[tuple[int, float]],
    initial_equity: float = 50000.0,
    risk_free_rate: float = 0.0,
    trading_days_per_year: int = 252,
    n_strategies_tested: int = 1,
) -> AnalyticsReport:
    """Compute the full analytics suite from closed trades and equity curve."""
    closed = [t for t in trades if not t.is_open and t.pnl is not None]
    report = AnalyticsReport(initial_equity=initial_equity, equity_curve=equity_curve)

    if not closed:
        return report

    pnls = np.array([t.pnl - t.commission for t in closed], dtype=float)
    report.n_trades = len(closed)
    report.net_pnl = float(np.sum(pnls))
    report.total_return_pct = report.net_pnl / initial_equity * 100

    final_equity = initial_equity + report.net_pnl
    report.cagr = _compute_cagr(initial_equity, final_equity, closed)

    # Win/loss
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    report.win_rate = len(wins) / len(pnls)
    report.avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
    report.avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0.0
    report.largest_win = float(np.max(wins)) if len(wins) > 0 else 0.0
    report.largest_loss = float(np.min(losses)) if len(losses) > 0 else 0.0

    gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0.0
    gross_loss = float(abs(np.sum(losses))) if len(losses) > 0 else 1e-9
    report.profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    loss_rate = 1 - report.win_rate
    report.expectancy = (report.win_rate * report.avg_win) + (loss_rate * report.avg_loss)
    report.avg_rr = abs(report.avg_win / report.avg_loss) if report.avg_loss != 0 else 0.0

    # R-multiples
    r_mults = _compute_r_multiples(closed)
    report.r_multiples = r_mults
    if r_mults:
        report.avg_r_multiple = float(np.mean(r_mults))

    # Consecutive runs
    report.max_consecutive_wins, report.max_consecutive_losses = _consecutive_runs(pnls)

    # MAE/MFE/ETD
    maes = [t.mae for t in closed if t.mae is not None]
    mfes = [t.mfe for t in closed if t.mfe is not None]
    report.avg_mae = float(np.mean(maes)) if maes else 0.0
    report.avg_mfe = float(np.mean(mfes)) if mfes else 0.0
    if mfes and len(pnls):
        etds = [mfe - pnl for mfe, pnl in zip(mfes, pnls)]
        report.avg_etd = float(np.mean(etds))

    # Daily returns from equity curve
    daily_rets = _equity_to_daily_returns(equity_curve, initial_equity)
    report.daily_returns = daily_rets

    if len(daily_rets) >= 2:
        dr = np.array(daily_rets)
        _fill_risk_adjusted(report, dr, risk_free_rate, trading_days_per_year)
        _fill_statistical(report, dr, n_strategies_tested)

    # Drawdown analysis
    if equity_curve:
        _fill_drawdown(report, equity_curve, initial_equity)

    return report


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _compute_cagr(initial: float, final: float, trades: list[TradeEvent]) -> float:
    if not trades:
        return 0.0
    first_ts = trades[0].timestamp
    last_ts = trades[-1].timestamp
    days = max(1, (last_ts - first_ts).days)
    years = days / 365.25
    if final <= 0 or initial <= 0:
        return 0.0
    return (final / initial) ** (1 / years) - 1 if years > 0 else 0.0


def _equity_to_daily_returns(
    equity_curve: list[tuple[int, float]], initial: float
) -> list[float]:
    """Convert indexed equity curve to bar-by-bar returns."""
    if len(equity_curve) < 2:
        return []
    vals = [eq for _, eq in equity_curve]
    returns = [(vals[i] - vals[i - 1]) / vals[i - 1] for i in range(1, len(vals))]
    return returns


def _fill_risk_adjusted(
    report: AnalyticsReport,
    dr: np.ndarray,
    rf: float,
    tdy: int,
):
    mean_r = float(np.mean(dr))
    std_r = float(np.std(dr, ddof=1)) or 1e-9
    downside = dr[dr < rf]
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 1e-9

    report.sharpe = (mean_r - rf / tdy) / std_r * math.sqrt(tdy)
    report.sortino = (mean_r - rf / tdy) / downside_std * math.sqrt(tdy)

    # Calmar = CAGR / Max Drawdown
    if report.max_drawdown > 0:
        report.calmar = report.cagr / (report.max_drawdown / report.initial_equity)

    # Omega ratio (threshold = 0)
    gains = dr[dr > 0].sum()
    losses_sum = abs(dr[dr < 0].sum())
    report.omega = gains / losses_sum if losses_sum > 0 else float("inf")

    # Ulcer Index
    equity_vals = [e for _, e in report.equity_curve] or [report.initial_equity]
    eq = np.array(equity_vals)
    running_max = np.maximum.accumulate(eq)
    dd_pct = (running_max - eq) / running_max * 100
    report.ulcer_index = float(np.sqrt(np.mean(dd_pct ** 2)))

    # UPI (Martin Ratio)
    if report.ulcer_index > 0:
        report.upi = report.cagr * 100 / report.ulcer_index

    # Kappa-3
    lpm3 = float(np.mean(np.maximum(0 - dr, 0) ** 3))
    if lpm3 > 0:
        report.kappa3 = (mean_r - rf / tdy) / (lpm3 ** (1 / 3))


def _fill_statistical(
    report: AnalyticsReport,
    dr: np.ndarray,
    k: int,
):
    """t-stat, p-value, PSR, DSR, Ljung-Box, skewness, kurtosis."""
    n = len(dr)
    report.n_adequate = n >= 30

    if n < 2:
        return

    t_stat, p_val = stats.ttest_1samp(dr, 0)
    report.t_statistic = float(t_stat)
    report.p_value = float(p_val)

    # Sharpe t-stat
    sr = report.sharpe / math.sqrt(252)  # per-observation Sharpe
    se_sr = math.sqrt((1 + 0.5 * sr ** 2) / n)
    report.sharpe_t_stat = sr / se_sr if se_sr > 0 else 0.0

    # PSR — Probabilistic Sharpe Ratio
    sk = float(stats.skew(dr))
    ku = float(stats.kurtosis(dr))  # excess kurtosis
    report.skewness = sk
    report.kurtosis = ku + 3  # raw kurtosis

    sr_hat = report.sharpe / math.sqrt(252)
    sr_star = 0.0  # benchmark
    denom_inner = 1 - sk * sr_hat + (ku + 1) / 4 * sr_hat ** 2
    if denom_inner > 0 and n > 1:
        psr_z = (sr_hat - sr_star) * math.sqrt(n - 1) / math.sqrt(denom_inner)
        report.psr = float(stats.norm.cdf(psr_z))
    else:
        report.psr = 0.5

    # DSR — Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014)
    if k > 1 and n > 1:
        e_max_sr = (1 - 0.5772) * stats.norm.ppf(1 - 1 / k) + 0.5772 * stats.norm.ppf(1 - 1 / (k * math.e))
        dsr_z = (sr_hat - e_max_sr) * math.sqrt(n - 1) / math.sqrt(denom_inner if denom_inner > 0 else 1)
        report.dsr = float(stats.norm.cdf(dsr_z))
    else:
        report.dsr = report.psr

    # Ljung-Box autocorrelation test (lag 1)
    try:
        from statsmodels.stats.diagnostic import acorr_ljungbox
        lb = acorr_ljungbox(dr, lags=1, return_df=True)
        report.ljung_box_pvalue = float(lb["lb_pvalue"].iloc[0])
    except Exception:
        # Manual lag-1 autocorrelation test
        if n > 2:
            ac1 = float(np.corrcoef(dr[:-1], dr[1:])[0, 1])
            q_stat = n * (n + 2) * (ac1 ** 2) / (n - 1)
            report.ljung_box_pvalue = float(1 - stats.chi2.cdf(q_stat, df=1))


def _fill_drawdown(
    report: AnalyticsReport,
    equity_curve: list[tuple[int, float]],
    initial: float,
):
    vals = np.array([e for _, e in equity_curve])
    if len(vals) < 2:
        return

    running_max = np.maximum.accumulate(vals)
    dd = running_max - vals

    report.max_drawdown = float(np.max(dd))
    report.max_drawdown_pct = report.max_drawdown / initial * 100
    report.avg_drawdown = float(np.mean(dd[dd > 0])) if np.any(dd > 0) else 0.0

    if report.max_drawdown > 0:
        report.recovery_factor = report.net_pnl / report.max_drawdown

    # Time underwater
    report.time_underwater_pct = float(np.mean(dd > 0)) * 100

    # Max drawdown duration (consecutive bars underwater)
    in_dd = dd > 0
    max_dur = 0
    cur_dur = 0
    for x in in_dd:
        if x:
            cur_dur += 1
            max_dur = max(max_dur, cur_dur)
        else:
            cur_dur = 0
    report.max_drawdown_duration = max_dur

    # Calmar needs CAGR / MDD
    if report.max_drawdown_pct > 0:
        report.calmar = report.cagr / (report.max_drawdown_pct / 100)


def _compute_r_multiples(trades: list[TradeEvent]) -> list[float]:
    """Estimate R-multiple for each trade using MAE as initial risk proxy."""
    r_mults = []
    for t in trades:
        if t.mae is not None and t.mae < 0 and t.pnl is not None:
            risk = abs(t.mae)
            if risk > 0:
                r_mults.append((t.pnl - t.commission) / risk)
    return r_mults


def _consecutive_runs(pnls: np.ndarray) -> tuple[int, int]:
    max_wins = max_losses = 0
    cur_wins = cur_losses = 0
    for p in pnls:
        if p > 0:
            cur_wins += 1
            cur_losses = 0
        elif p < 0:
            cur_losses += 1
            cur_wins = 0
        else:
            cur_wins = cur_losses = 0
        max_wins = max(max_wins, cur_wins)
        max_losses = max(max_losses, cur_losses)
    return max_wins, max_losses


def format_report_text(report: AnalyticsReport) -> str:
    """Return a formatted multi-line text summary of the analytics report."""
    def pct(v): return f"{v:+.2f}%"
    def dol(v): return f"${v:,.2f}"
    def flt(v): return f"{v:.4f}"
    def int_(v): return f"{v:,}"

    lines = [
        "═" * 56,
        " QUANTITATIVE ANALYTICS REPORT",
        "═" * 56,
        "",
        "── RETURN METRICS ──────────────────────────────────",
        f"  Net P&L:                {dol(report.net_pnl)}",
        f"  Total Return:           {pct(report.total_return_pct)}",
        f"  CAGR:                   {pct(report.cagr * 100)}",
        "",
        "── RISK-ADJUSTED RETURNS ───────────────────────────",
        f"  Sharpe Ratio:           {flt(report.sharpe)}",
        f"  Sortino Ratio:          {flt(report.sortino)}",
        f"  Calmar Ratio:           {flt(report.calmar)}",
        f"  Omega Ratio:            {flt(report.omega)}",
        f"  Ulcer Index:            {flt(report.ulcer_index)}",
        f"  UPI (Martin Ratio):     {flt(report.upi)}",
        f"  Kappa-3:                {flt(report.kappa3)}",
        "",
        "── TRADE STATISTICS ────────────────────────────────",
        f"  Total Trades:           {int_(report.n_trades)}",
        f"  Win Rate:               {pct(report.win_rate * 100)}",
        f"  Profit Factor:          {flt(report.profit_factor)}",
        f"  Expectancy:             {dol(report.expectancy)}",
        f"  Avg Win / Avg Loss:     {dol(report.avg_win)} / {dol(report.avg_loss)}",
        f"  Avg R/R:                {flt(report.avg_rr)}",
        f"  Avg R-Multiple:         {flt(report.avg_r_multiple)}",
        f"  Largest Win:            {dol(report.largest_win)}",
        f"  Largest Loss:           {dol(report.largest_loss)}",
        f"  Max Consec. Wins:       {report.max_consecutive_wins}",
        f"  Max Consec. Losses:     {report.max_consecutive_losses}",
        "",
        "── MAE / MFE ───────────────────────────────────────",
        f"  Avg MAE:                {dol(report.avg_mae)}",
        f"  Avg MFE:                {dol(report.avg_mfe)}",
        f"  Avg ETD (left on tbl):  {dol(report.avg_etd)}",
        "",
        "── DRAWDOWN ANALYSIS ───────────────────────────────",
        f"  Max Drawdown:           {dol(report.max_drawdown)} ({pct(report.max_drawdown_pct)})",
        f"  Avg Drawdown:           {dol(report.avg_drawdown)}",
        f"  Max DD Duration:        {report.max_drawdown_duration} bars",
        f"  Recovery Factor:        {flt(report.recovery_factor)}",
        f"  Time Underwater:        {pct(report.time_underwater_pct)}",
        "",
        "── STATISTICAL VALIDITY ────────────────────────────",
        f"  N Trades (≥30 ok?):     {report.n_trades} → {'✓' if report.n_adequate else '✗'}",
        f"  t-Statistic:            {flt(report.t_statistic)}",
        f"  p-Value:                {report.p_value:.4f}",
        f"  Sharpe t-stat:          {flt(report.sharpe_t_stat)}",
        f"  PSR (prob SR > 0):      {pct(report.psr * 100)}",
        f"  DSR (multi-test adj):   {pct(report.dsr * 100)}",
        f"  Ljung-Box p-Value:      {report.ljung_box_pvalue:.4f}",
        f"  Skewness:               {flt(report.skewness)}",
        f"  Kurtosis:               {flt(report.kurtosis)}",
        "═" * 56,
    ]
    return "\n".join(lines)

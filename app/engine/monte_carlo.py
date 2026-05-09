"""Monte Carlo simulation module — 5 resampling methods + prop firm integration."""
from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
from scipy import stats

from .prop_rules import PropFirmProfile, PropRulesEngine
from .events import TradeEvent


@dataclass
class MCConfig:
    n_paths: int = 10_000
    method: str = "trade_shuffle"   # see METHOD_NAMES
    confidence_lo: float = 0.05
    confidence_hi: float = 0.95
    seed: Optional[int] = None
    path_length: Optional[int] = None  # None = same as trade count


METHOD_NAMES = [
    "trade_shuffle",
    "bootstrap",
    "parametric_normal",
    "parametric_t",
    "block_bootstrap",
]


@dataclass
class MCResults:
    method: str
    n_paths: int
    initial_equity: float

    # Shape: (n_paths, path_length+1) — cumulative equity
    equity_paths: np.ndarray = field(default_factory=lambda: np.array([]))

    # Summary stats
    median_final: float = 0.0
    pct5_final: float = 0.0
    pct95_final: float = 0.0
    prob_ruin: float = 0.0
    prob_target: float = 0.0
    median_max_dd: float = 0.0
    pct95_max_dd: float = 0.0
    expected_payoff: float = 0.0
    dar_95: float = 0.0

    # Prop firm integration
    pass_rate: float = 0.0
    avg_days_to_pass: float = 0.0
    most_common_failure_rule: str = ""

    # Raw per-path stats for histogram display
    final_equities: np.ndarray = field(default_factory=lambda: np.array([]))
    max_drawdowns: np.ndarray = field(default_factory=lambda: np.array([]))


def run_monte_carlo(
    trades: list[TradeEvent],
    initial_equity: float,
    cfg: MCConfig,
    prop_profile: Optional[PropFirmProfile] = None,
) -> MCResults:
    """
    Generate `cfg.n_paths` Monte Carlo equity paths from historical trades.
    Returns MCResults with fan chart data and summary statistics.
    """
    if not trades:
        return MCResults(method=cfg.method, n_paths=0, initial_equity=initial_equity)

    rng = np.random.default_rng(cfg.seed if cfg.seed else None)
    returns = _extract_returns(trades)
    n = len(returns)
    path_len = cfg.path_length or n

    paths = _generate_paths(returns, cfg.method, cfg.n_paths, path_len, rng)

    # Convert return sequences to equity curves
    equity_paths = _returns_to_equity(paths, initial_equity)

    final_equities = equity_paths[:, -1]
    max_drawdowns = _compute_max_drawdowns(equity_paths)

    # Ruin threshold = breach of max drawdown (use 50% of initial as ruin)
    ruin_threshold = initial_equity * 0.5
    prob_ruin = float(np.mean(final_equities < ruin_threshold))

    profit_target = (
        prop_profile.profit_target
        if prop_profile and prop_profile.profit_target
        else initial_equity * 0.1
    )
    prob_target = float(np.mean(final_equities >= initial_equity + profit_target))

    dar_95 = float(np.percentile(max_drawdowns, 95))

    result = MCResults(
        method=cfg.method,
        n_paths=cfg.n_paths,
        initial_equity=initial_equity,
        equity_paths=equity_paths,
        median_final=float(np.median(final_equities)),
        pct5_final=float(np.percentile(final_equities, 5)),
        pct95_final=float(np.percentile(final_equities, 95)),
        prob_ruin=prob_ruin,
        prob_target=prob_target,
        median_max_dd=float(np.median(max_drawdowns)),
        pct95_max_dd=float(np.percentile(max_drawdowns, 95)),
        expected_payoff=float(np.mean(final_equities)),
        dar_95=dar_95,
        final_equities=final_equities,
        max_drawdowns=max_drawdowns,
    )

    if prop_profile:
        result = _run_prop_integration(result, equity_paths, trades, prop_profile, initial_equity, rng)

    return result


def _extract_returns(trades: list[TradeEvent]) -> np.ndarray:
    """Extract net P&L per trade as a numpy array."""
    returns = []
    for t in trades:
        if not t.is_open and t.pnl is not None:
            returns.append(t.pnl - t.commission)
    return np.array(returns, dtype=float)


def _generate_paths(
    returns: np.ndarray,
    method: str,
    n_paths: int,
    path_len: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Returns shape (n_paths, path_len) of return sequences.
    """
    n = len(returns)
    if method == "trade_shuffle":
        idx = rng.choice(n, size=(n_paths, path_len), replace=True)
        return returns[idx]

    elif method == "bootstrap":
        idx = rng.choice(n, size=(n_paths, path_len), replace=True)
        return returns[idx]

    elif method == "parametric_normal":
        mu = float(np.mean(returns))
        sigma = float(np.std(returns, ddof=1)) or 1e-9
        return rng.normal(mu, sigma, size=(n_paths, path_len))

    elif method == "parametric_t":
        df, loc, scale = stats.t.fit(returns)
        samples = stats.t.rvs(df, loc=loc, scale=scale, size=(n_paths, path_len),
                               random_state=int(rng.integers(0, 2**31)))
        return samples

    elif method == "block_bootstrap":
        block_size = max(1, int(np.sqrt(n)))
        all_blocks = np.array([
            returns[i: i + block_size]
            for i in range(n - block_size + 1)
        ])
        n_blocks_needed = max(1, path_len // block_size + 1)
        block_idx = rng.integers(0, len(all_blocks), size=(n_paths, n_blocks_needed))
        # all_blocks[block_idx] has shape (n_paths, n_blocks_needed, block_size)
        paths = all_blocks[block_idx].reshape(n_paths, n_blocks_needed * block_size)[:, :path_len]
        return paths

    else:
        raise ValueError(f"Unknown MC method: {method}")


def _returns_to_equity(paths: np.ndarray, initial: float) -> np.ndarray:
    """Convert (n_paths, path_len) returns -> (n_paths, path_len+1) equity."""
    cum = np.cumsum(paths, axis=1)
    equity = np.hstack([
        np.full((paths.shape[0], 1), initial),
        initial + cum,
    ])
    return equity


def _compute_max_drawdowns(equity_paths: np.ndarray) -> np.ndarray:
    """Compute max drawdown for each path. Returns shape (n_paths,)."""
    running_max = np.maximum.accumulate(equity_paths, axis=1)
    drawdowns = running_max - equity_paths
    return np.max(drawdowns, axis=1)


def _run_prop_integration(
    result: MCResults,
    equity_paths: np.ndarray,
    original_trades: list[TradeEvent],
    profile: PropFirmProfile,
    initial_equity: float,
    rng: np.random.Generator,
) -> MCResults:
    """Evaluate each MC path against prop firm rules."""
    n_paths = equity_paths.shape[0]
    pass_count = 0
    days_to_pass_list = []
    failure_rules: dict[str, int] = {}

    target = profile.profit_target or 0
    trailing_dd = profile.trailing_drawdown or 0
    daily_limit = profile.daily_loss_limit or 0
    max_dd = profile.max_drawdown or 0

    for path in equity_paths:
        peak = initial_equity
        floor = initial_equity - trailing_dd if trailing_dd else 0
        static_floor = initial_equity - max_dd if max_dd else 0
        passed = False
        failed = False
        fail_rule = None

        for step_i, eq in enumerate(path[1:], start=1):
            # Update trailing floor
            if trailing_dd and eq > peak:
                peak = eq
                floor = peak - trailing_dd

            # Trailing DD breach
            if trailing_dd and "trailing_drawdown" in profile.enabled_rules:
                if eq < floor:
                    failed = True
                    fail_rule = "trailing_drawdown"
                    break

            # Static max DD
            if max_dd and "max_drawdown" in profile.enabled_rules:
                if eq < static_floor:
                    failed = True
                    fail_rule = "max_drawdown"
                    break

            # Profit target hit
            if target and eq >= initial_equity + target:
                passed = True
                days_to_pass_list.append(step_i)
                break

        if failed and fail_rule:
            failure_rules[fail_rule] = failure_rules.get(fail_rule, 0) + 1
        elif passed:
            pass_count += 1

    result.pass_rate = pass_count / n_paths if n_paths else 0.0
    result.avg_days_to_pass = (
        float(np.mean(days_to_pass_list)) if days_to_pass_list else 0.0
    )
    if failure_rules:
        result.most_common_failure_rule = max(failure_rules, key=failure_rules.get)

    return result


def fan_chart_data(
    result: MCResults,
    n_display_paths: int = 200,
    conf_lo: float = 0.05,
    conf_hi: float = 0.95,
) -> dict:
    """
    Prepare fan chart data for display.
    Returns dict with keys: sample_paths, median, lo_bound, hi_bound
    Each is a list of equity values indexed by step.
    """
    paths = result.equity_paths
    if paths.size == 0:
        return {"sample_paths": [], "median": [], "lo_bound": [], "hi_bound": []}

    n = min(n_display_paths, paths.shape[0])
    idx = np.linspace(0, paths.shape[0] - 1, n, dtype=int)
    sample = paths[idx].tolist()

    median = np.median(paths, axis=0).tolist()
    lo = np.percentile(paths, conf_lo * 100, axis=0).tolist()
    hi = np.percentile(paths, conf_hi * 100, axis=0).tolist()

    return {
        "sample_paths": sample,
        "median": median,
        "lo_bound": lo,
        "hi_bound": hi,
    }

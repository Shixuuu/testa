"""Generate a synthetic ES-like OHLCV demo dataset for testing."""
import numpy as np
import pandas as pd
from pathlib import Path


def generate_es_demo(
    n_bars: int = 2000,
    start_price: float = 4500.0,
    seed: int = 42,
    filename: str = "es_demo_5m.csv",
):
    rng = np.random.default_rng(seed)
    out_path = Path(__file__).parent / filename

    # Simulate GBM-like price with mean reversion
    log_returns = rng.normal(0.00005, 0.0008, n_bars)
    prices = np.exp(np.cumsum(log_returns)) * start_price

    opens = prices.copy()
    closes = prices * np.exp(rng.normal(0, 0.0003, n_bars))
    highs = np.maximum(opens, closes) * (1 + rng.uniform(0.0001, 0.0008, n_bars))
    lows = np.minimum(opens, closes) * (1 - rng.uniform(0.0001, 0.0008, n_bars))
    volumes = rng.integers(500, 8000, n_bars).astype(float)

    # Round to 0.25 tick size
    def round_tick(arr, tick=0.25):
        return np.round(arr / tick) * tick

    opens = round_tick(opens)
    highs = round_tick(highs)
    lows = round_tick(lows)
    closes = round_tick(closes)

    # Generate timestamps (5-minute bars, RTH only: 09:30–16:00 EST)
    timestamps = []
    dt = pd.Timestamp("2023-01-03 09:30:00")
    bars_per_day = 78  # 6.5 hours * 12 bars/hr
    bar_count = 0
    while bar_count < n_bars:
        # Skip weekends
        if dt.weekday() < 5:
            for _ in range(bars_per_day):
                if bar_count >= n_bars:
                    break
                timestamps.append(dt)
                dt += pd.Timedelta(minutes=5)
                bar_count += 1
        dt = dt.replace(hour=9, minute=30, second=0)
        dt += pd.Timedelta(days=1)

    df = pd.DataFrame({
        "datetime": timestamps[:n_bars],
        "open": opens[:n_bars],
        "high": highs[:n_bars],
        "low": lows[:n_bars],
        "close": closes[:n_bars],
        "volume": volumes[:n_bars],
    })
    df.to_csv(out_path, index=False)
    print(f"Generated {len(df)} bars → {out_path}")
    return str(out_path)


if __name__ == "__main__":
    generate_es_demo()

"""TPO (Time Price Opportunity) / Market Profile calculation engine."""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Optional

from .events import BarEvent

PERIOD_LETTERS = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789!@#$%^&*()"
)
VALUE_AREA_PCT = 0.70


@dataclass
class TPOProfile:
    """Market Profile for a single session."""
    date: str
    price_levels: dict[float, str]   # price -> letters at that price
    poc: float                        # Point of Control (most letters)
    vah: float                        # Value Area High
    val: float                        # Value Area Low
    tick_size: float
    initial_balance_high: float = 0.0
    initial_balance_low: float = 0.0
    single_prints: list[float] = field(default_factory=list)
    range_high: float = 0.0
    range_low: float = 0.0

    @property
    def profile_width(self) -> int:
        return max((len(v) for v in self.price_levels.values()), default=0)

    @property
    def tpo_count(self) -> int:
        return sum(len(v) for v in self.price_levels.values())


def compute_tpo_profiles(
    bars: list[BarEvent],
    tick_size: float = 0.25,
    period_minutes: int = 30,
) -> list[TPOProfile]:
    """
    Compute TPO Market Profiles from bar events.
    Each bar's timestamp determines its session; each period_minutes block
    within a session gets a letter.
    """
    if not bars:
        return []

    days: dict[str, list[BarEvent]] = defaultdict(list)
    for bar in bars:
        if bar.timestamp:
            days[bar.timestamp.strftime("%Y-%m-%d")].append(bar)

    profiles = []
    for date_key in sorted(days.keys()):
        day_bars = sorted(days[date_key], key=lambda b: b.timestamp)
        if not day_bars:
            continue

        session_start = day_bars[0].timestamp
        period_map: dict[int, list[BarEvent]] = defaultdict(list)
        for bar in day_bars:
            elapsed = int((bar.timestamp - session_start).total_seconds() / 60)
            period_map[elapsed // period_minutes].append(bar)

        price_levels: dict[float, str] = defaultdict(str)
        ib_high = 0.0
        ib_low = float("inf")

        for period_idx in sorted(period_map.keys()):
            letter = PERIOD_LETTERS[period_idx] if period_idx < len(PERIOD_LETTERS) else "?"
            for bar in period_map[period_idx]:
                lo = _round_tick(bar.low, tick_size)
                hi = _round_tick(bar.high, tick_size)
                p = lo
                while p <= hi + tick_size * 0.5:
                    price_levels[round(p, 8)] += letter
                    p = round(p + tick_size, 8)
                if period_idx < 2:
                    ib_high = max(ib_high, bar.high)
                    ib_low = min(ib_low, bar.low)

        if not price_levels:
            continue

        poc = max(price_levels, key=lambda p: len(price_levels[p]))
        vah, val = _value_area(price_levels, poc)
        single_prints = [p for p, letters in price_levels.items() if len(letters) == 1]
        all_prices = sorted(price_levels.keys())

        profiles.append(TPOProfile(
            date=date_key,
            price_levels=dict(price_levels),
            poc=poc,
            vah=vah,
            val=val,
            tick_size=tick_size,
            initial_balance_high=ib_high,
            initial_balance_low=ib_low if ib_low != float("inf") else all_prices[0],
            single_prints=single_prints,
            range_high=all_prices[-1],
            range_low=all_prices[0],
        ))

    return profiles


def _round_tick(price: float, tick_size: float) -> float:
    return round(round(price / tick_size) * tick_size, 8)


def _value_area(price_levels: dict[float, str], poc: float) -> tuple[float, float]:
    """Expand from POC outward until 70% of TPO count is captured."""
    total = sum(len(v) for v in price_levels.values())
    target = total * VALUE_AREA_PCT
    prices = sorted(price_levels.keys())

    if poc not in prices:
        mid = len(prices) // 2
        return prices[-1], prices[0]

    poc_i = prices.index(poc)
    captured = len(price_levels[poc])
    hi_i = poc_i
    lo_i = poc_i

    while captured < target:
        hi_next = hi_i + 1
        lo_next = lo_i - 1
        hi_add = len(price_levels.get(prices[hi_next], "")) if hi_next < len(prices) else 0
        lo_add = len(price_levels.get(prices[lo_next], "")) if lo_next >= 0 else 0

        if hi_add == 0 and lo_add == 0:
            break
        if hi_add >= lo_add:
            hi_i = hi_next
            captured += hi_add
        else:
            lo_i = lo_next
            captured += lo_add

    return prices[hi_i], prices[lo_i]

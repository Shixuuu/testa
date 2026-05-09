"""Event dataclasses emitted by the BacktraderRunner to the TUI."""
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime


@dataclass
class BarEvent:
    bar_index: int
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    indicators: dict[str, float] = field(default_factory=dict)


@dataclass
class TradeEvent:
    bar_index: int
    timestamp: datetime
    direction: str          # "LONG" | "SHORT"
    entry_price: float
    exit_price: Optional[float]
    size: float
    pnl: Optional[float]
    commission: float
    is_open: bool
    trade_id: int
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    mae: Optional[float] = None
    mfe: Optional[float] = None


@dataclass
class OrderEvent:
    bar_index: int
    timestamp: datetime
    order_type: str         # "BUY" | "SELL" | "CANCEL"
    price: float
    size: float
    status: str             # "SUBMITTED" | "ACCEPTED" | "COMPLETED" | "CANCELLED"


@dataclass
class IndicatorEvent:
    bar_index: int
    name: str
    value: Any


@dataclass
class PropViolationEvent:
    bar_index: int
    timestamp: datetime
    rule: str
    level: str              # "WARNING" | "BREACH"
    message: str
    account_balance: float


@dataclass
class RunCompleteEvent:
    total_bars: int
    total_trades: int
    final_equity: float
    message: str = ""

"""BacktraderRunner: runs Backtrader in a thread, emits events to a queue."""
import queue
import threading
import importlib.util
import inspect
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Any
import pandas as pd
import backtrader as bt
import backtrader.feeds as btfeeds

from .events import (
    BarEvent, TradeEvent, OrderEvent, IndicatorEvent,
    PropViolationEvent, RunCompleteEvent,
)
from .instruments import get_instrument, make_commission, InstrumentSpec


# Control signals sent to the runner thread
SIGNAL_PAUSE = "PAUSE"
SIGNAL_STEP = "STEP"
SIGNAL_FAST_FORWARD = "FAST_FORWARD"
SIGNAL_RESET = "RESET"
SIGNAL_STOP = "STOP"


class _TUIObserver(bt.Observer):
    """Backtrader observer that captures every bar into the event queue."""
    lines = ("cash", "value")
    plotinfo = dict(plot=False)


class _EventEmitterStrategy(bt.Strategy):
    """
    Wraps user strategy; intercepts bar/trade/order notifications and
    drains them into the shared event queue.
    """
    params = (
        ("user_strategy_cls", None),
        ("event_queue", None),
        ("control_queue", None),
        ("bar_delay", 0.0),
        ("instrument_spec", None),
    )

    def __init__(self):
        self._user_strategy = None
        self._trade_id = 0
        self._open_trades: dict[int, dict] = {}
        self._bar_index = 0
        self._paused = False
        self._speed = 1

        if self.p.user_strategy_cls:
            self._user_strategy = self.p.user_strategy_cls(self.env)

    def prenext(self):
        self.next()

    def next(self):
        # Check control signals
        ctrl_q: queue.Queue = self.p.control_queue
        while not ctrl_q.empty():
            sig = ctrl_q.get_nowait()
            if sig == SIGNAL_PAUSE:
                self._paused = True
            elif sig == SIGNAL_STEP:
                self._paused = False  # run one bar, re-pause handled by replay controller
            elif sig == SIGNAL_STOP:
                self.env.runstop()
                return

        bar_dt = self.data.datetime.datetime(0)
        evt = BarEvent(
            bar_index=self._bar_index,
            timestamp=bar_dt,
            open=float(self.data.open[0]),
            high=float(self.data.high[0]),
            low=float(self.data.low[0]),
            close=float(self.data.close[0]),
            volume=float(self.data.volume[0]),
        )
        self.p.event_queue.put(evt)
        self._bar_index += 1

    def notify_trade(self, trade):
        eq: queue.Queue = self.p.event_queue
        if trade.justopened:
            self._trade_id += 1
            self._open_trades[trade.ref] = {
                "id": self._trade_id,
                "direction": "LONG" if trade.size > 0 else "SHORT",
                "entry_price": trade.price,
                "size": abs(trade.size),
                "entry_bar": self._bar_index,
                "min_price": trade.price,
                "max_price": trade.price,
            }
            evt = TradeEvent(
                bar_index=self._bar_index,
                timestamp=self.data.datetime.datetime(0),
                direction="LONG" if trade.size > 0 else "SHORT",
                entry_price=trade.price,
                exit_price=None,
                size=abs(trade.size),
                pnl=None,
                commission=trade.commission,
                is_open=True,
                trade_id=self._trade_id,
            )
            eq.put(evt)

        if trade.isclosed:
            info = self._open_trades.pop(trade.ref, {})
            direction = info.get("direction", "LONG")
            entry_price = info.get("entry_price", trade.price)
            size = info.get("size", abs(trade.size))
            mae = None
            mfe = None
            if "min_price" in info and "max_price" in info:
                if direction == "LONG":
                    mae = (info["min_price"] - entry_price) * size * (self.p.instrument_spec.point_value if self.p.instrument_spec else 1)
                    mfe = (info["max_price"] - entry_price) * size * (self.p.instrument_spec.point_value if self.p.instrument_spec else 1)
                else:
                    mae = (entry_price - info["max_price"]) * size * (self.p.instrument_spec.point_value if self.p.instrument_spec else 1)
                    mfe = (entry_price - info["min_price"]) * size * (self.p.instrument_spec.point_value if self.p.instrument_spec else 1)

            evt = TradeEvent(
                bar_index=self._bar_index,
                timestamp=self.data.datetime.datetime(0),
                direction=direction,
                entry_price=entry_price,
                exit_price=trade.price,
                size=size,
                pnl=trade.pnl,
                commission=trade.commission,
                is_open=False,
                trade_id=info.get("id", self._trade_id),
                mae=mae,
                mfe=mfe,
            )
            eq.put(evt)

        # Update intrabar high/low for MAE/MFE tracking
        for ref, info in self._open_trades.items():
            curr = float(self.data.close[0])
            info["min_price"] = min(info["min_price"], float(self.data.low[0]))
            info["max_price"] = max(info["max_price"], float(self.data.high[0]))

    def notify_order(self, order):
        eq: queue.Queue = self.p.event_queue
        status_map = {
            bt.Order.Submitted: "SUBMITTED",
            bt.Order.Accepted: "ACCEPTED",
            bt.Order.Completed: "COMPLETED",
            bt.Order.Canceled: "CANCELLED",
            bt.Order.Margin: "MARGIN",
            bt.Order.Rejected: "REJECTED",
        }
        evt = OrderEvent(
            bar_index=self._bar_index,
            timestamp=self.data.datetime.datetime(0),
            order_type="BUY" if order.isbuy() else "SELL",
            price=order.executed.price or order.created.price,
            size=order.size,
            status=status_map.get(order.status, "UNKNOWN"),
        )
        eq.put(evt)

    def stop(self):
        evt = RunCompleteEvent(
            total_bars=self._bar_index,
            total_trades=self._trade_id,
            final_equity=float(self.broker.getvalue()),
            message="Backtest complete",
        )
        self.p.event_queue.put(evt)


def load_strategy_from_file(path: str) -> type:
    """Import a Backtrader Strategy subclass from a Python file."""
    spec = importlib.util.spec_from_file_location("user_strategy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, bt.Strategy) and obj is not bt.Strategy:
            return obj
    raise ValueError(f"No bt.Strategy subclass found in {path}")


def load_dataframe(path: str) -> pd.DataFrame:
    """Load OHLCV data from CSV or Parquet, returning a normalised DataFrame."""
    p = Path(path)
    if p.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)

    # Normalise column names
    df.columns = [c.lower().strip() for c in df.columns]
    rename = {}
    for col in df.columns:
        if col in ("date", "time", "ts", "timestamp", "datetime"):
            rename[col] = "datetime"
        elif col in ("o", "open"):
            rename[col] = "open"
        elif col in ("h", "high"):
            rename[col] = "high"
        elif col in ("l", "low"):
            rename[col] = "low"
        elif col in ("c", "close"):
            rename[col] = "close"
        elif col in ("v", "vol", "volume"):
            rename[col] = "volume"
    df = df.rename(columns=rename)

    if "datetime" not in df.columns:
        raise ValueError("Data file must contain a datetime column.")
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    if "volume" not in df.columns:
        df["volume"] = 0.0
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df


class PandasOHLCV(btfeeds.PandasData):
    params = (
        ("datetime", None),
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", "volume"),
        ("openinterest", -1),
    )


class BacktraderRunner:
    """
    Runs Backtrader cerebro in a background thread.
    Emits events via `event_queue`; accepts control signals via `control_queue`.
    """

    def __init__(
        self,
        data_path: str,
        strategy_path: Optional[str],
        instrument: str = "ES",
        initial_cash: float = 50000.0,
        instrument_spec: Optional[InstrumentSpec] = None,
    ):
        self.data_path = data_path
        self.strategy_path = strategy_path
        self.instrument_name = instrument
        self.initial_cash = initial_cash
        self.instrument_spec = instrument_spec or get_instrument(instrument)

        self.event_queue: queue.Queue = queue.Queue(maxsize=0)
        self.control_queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._df: Optional[pd.DataFrame] = None
        self._strategy_cls: Optional[type] = None

    @property
    def base_timeframe_minutes(self) -> int:
        """Detect the bar period from loaded data's timestamp differences."""
        if self._df is None or len(self._df) < 2:
            return 1440  # assume daily if not loaded
        diffs = self._df["datetime"].diff().dropna()
        if diffs.empty:
            return 1440
        # Use mode to handle market-open gaps (overnight, weekends)
        most_common = diffs.mode().iloc[0]
        minutes = max(1, int(most_common.total_seconds() / 60))
        return minutes

    def load(self):
        """Load data and strategy (call before start)."""
        self._df = load_dataframe(self.data_path)
        if self.strategy_path:
            self._strategy_cls = load_strategy_from_file(self.strategy_path)

    def start(self):
        """Start Backtrader in a background thread."""
        if self._df is None:
            self.load()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def send(self, signal: str):
        self.control_queue.put(signal)

    def stop(self):
        self.control_queue.put(SIGNAL_STOP)
        if self._thread:
            self._thread.join(timeout=5.0)

    def _run(self):
        try:
            cerebro = bt.Cerebro(stdstats=False)
            cerebro.broker.setcash(self.initial_cash)

            comm = make_commission(self.instrument_spec)
            cerebro.broker.addcommissioninfo(comm)

            df = self._df.copy()
            df = df.set_index("datetime")
            feed = PandasOHLCV(dataname=df)
            cerebro.adddata(feed)

            user_cls = self._strategy_cls
            cerebro.addstrategy(
                _EventEmitterStrategy,
                user_strategy_cls=user_cls,
                event_queue=self.event_queue,
                control_queue=self.control_queue,
                instrument_spec=self.instrument_spec,
            )
            cerebro.run(runonce=False, preload=False)
        except Exception as exc:
            self.event_queue.put(RunCompleteEvent(
                total_bars=0,
                total_trades=0,
                final_equity=self.initial_cash,
                message=f"Error: {exc}",
            ))

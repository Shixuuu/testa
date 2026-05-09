"""
Backtrader runner with bar-by-bar replay support.
Emits events via queues for TUI consumption.
"""
from __future__ import annotations
import queue
import threading
import time as _time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Deque, Dict, List, Optional, Type

import backtrader as bt
import pandas as pd


# ─────────────────────────── Event types ───────────────────────────

@dataclass
class BarEvent:
    bar_index: int
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    equity: float
    open_position_size: int
    open_position_pnl: float


@dataclass
class TradeEvent:
    trade_num: int
    direction: str       # "LONG" | "SHORT"
    entry_price: float
    exit_price: float
    size: int
    pnl: float
    pnl_net: float
    commission: float
    entry_time: datetime
    exit_time: datetime
    mae: float
    mfe: float
    bars_held: int


@dataclass
class OrderEvent:
    order_type: str      # "BUY" | "SELL" | "CANCEL"
    price: float
    size: int
    status: str
    timestamp: datetime


class ControlSignal(Enum):
    PAUSE = auto()
    RESUME = auto()
    STEP_FORWARD = auto()
    STEP_BACKWARD = auto()
    RESET = auto()
    STOP = auto()
    SET_SPEED = auto()


@dataclass
class ControlMessage:
    signal: ControlSignal
    value: Any = None


# ─────────────────────────── Observer strategy ───────────────────────────

class _ObserverStrategy(bt.Strategy):
    """
    Wraps a user strategy and intercepts bar/trade/order events
    to emit them into the event queue.
    """

    params = (
        ("user_strategy_class", None),
        ("user_params", {}),
        ("event_queue", None),
        ("control_queue", None),
        ("speed", 1.0),
        ("ring_buffer", None),
    )

    def __init__(self) -> None:
        super().__init__()
        self._user_strat: Optional[bt.Strategy] = None
        self._bar_index = 0
        self._paused = False
        self._trades: List[Dict] = []
        self._pending_orders: List[bt.Order] = []

        if self.params.user_strategy_class:
            # Instantiate the wrapped strategy — Backtrader does this automatically
            # when added via addstrategy; here we just track the params
            pass

    def next(self) -> None:
        # Handle control messages (non-blocking)
        ctrl_q: queue.Queue = self.params.control_queue
        try:
            while True:
                msg: ControlMessage = ctrl_q.get_nowait()
                if msg.signal == ControlSignal.PAUSE:
                    self._paused = True
                elif msg.signal == ControlSignal.RESUME:
                    self._paused = False
                elif msg.signal == ControlSignal.STOP:
                    self.env.runstop()
                    return
                elif msg.signal == ControlSignal.SET_SPEED:
                    self.params.speed = float(msg.value)
        except queue.Empty:
            pass

        while self._paused:
            _time.sleep(0.05)
            try:
                msg = ctrl_q.get_nowait()
                if msg.signal == ControlSignal.RESUME:
                    self._paused = False
                elif msg.signal == ControlSignal.STEP_FORWARD:
                    self._paused = True  # stay paused after one step
                    break
                elif msg.signal == ControlSignal.STOP:
                    self.env.runstop()
                    return
            except queue.Empty:
                pass

        data = self.data
        dt = data.datetime.datetime(0)
        bar = BarEvent(
            bar_index=self._bar_index,
            datetime=dt,
            open=data.open[0],
            high=data.high[0],
            low=data.low[0],
            close=data.close[0],
            volume=data.volume[0],
            equity=self.broker.getvalue(),
            open_position_size=self.position.size,
            open_position_pnl=self.position.size * (
                data.close[0] - self.position.price
            ) if self.position.size else 0.0,
        )

        # Store in ring buffer
        if self.params.ring_buffer is not None:
            self.params.ring_buffer.append(bar)

        eq: queue.Queue = self.params.event_queue
        try:
            eq.put_nowait(bar)
        except queue.Full:
            pass

        self._bar_index += 1

        # Throttle replay speed
        if self.params.speed > 0:
            delay = 1.0 / self.params.speed
            if delay > 0.001:
                _time.sleep(delay)

    def notify_trade(self, trade: bt.Trade) -> None:
        if trade.isclosed:
            direction = "LONG" if trade.history[0].event.size > 0 else "SHORT"
            ev = TradeEvent(
                trade_num=len(self._trades) + 1,
                direction=direction,
                entry_price=trade.price,
                exit_price=trade.history[-1].event.price,
                size=abs(trade.history[0].event.size),
                pnl=trade.pnl,
                pnl_net=trade.pnlcomm,
                commission=trade.commission,
                entry_time=bt.num2date(trade.dtopen),
                exit_time=bt.num2date(trade.dtclose),
                mae=0.0,  # computed post-hoc
                mfe=0.0,
                bars_held=trade.barclose - trade.baropen,
            )
            self._trades.append(ev)
            try:
                self.params.event_queue.put_nowait(ev)
            except queue.Full:
                pass

    def notify_order(self, order: bt.Order) -> None:
        if order.status in (order.Completed, order.Canceled, order.Rejected):
            otype = "BUY" if order.isbuy() else "SELL"
            status_map = {
                order.Completed: "FILLED",
                order.Canceled: "CANCELLED",
                order.Rejected: "REJECTED",
            }
            ev = OrderEvent(
                order_type=otype,
                price=order.executed.price if order.executed else order.price,
                size=order.executed.size if order.executed else order.size,
                status=status_map.get(order.status, "UNKNOWN"),
                timestamp=self.data.datetime.datetime(0),
            )
            try:
                self.params.event_queue.put_nowait(ev)
            except queue.Full:
                pass


# ─────────────────────────── Runner ───────────────────────────

class BacktraderRunner:
    """
    Wraps Backtrader cerebro in a thread.
    Emits BarEvent, TradeEvent, OrderEvent to event_queue.
    Accepts ControlMessage via control_queue.
    """

    def __init__(self, event_queue_size: int = 2000) -> None:
        self.event_queue: queue.Queue = queue.Queue(maxsize=event_queue_size)
        self.control_queue: queue.Queue = queue.Queue()
        self._ring_buffer: Deque[BarEvent] = deque(maxlen=500)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bt_runner")
        self._future = None
        self._cerebro: Optional[bt.Cerebro] = None
        self._running = False
        self._lock = threading.Lock()

    def run_replay(
        self,
        data_feed: bt.feeds.PandasData,
        strategy_class: Type[bt.Strategy],
        params: Dict[str, Any],
        initial_cash: float = 50000.0,
        commission_scheme: Optional[bt.CommInfoBase] = None,
        speed: float = 0.0,
    ) -> None:
        """
        Start a replay run in a background thread.
        speed=0 means as fast as possible.
        """
        with self._lock:
            if self._running:
                self.stop()

            # Drain queues
            _drain(self.event_queue)
            _drain(self.control_queue)
            self._ring_buffer.clear()

            cerebro = bt.Cerebro(stdstats=False)
            cerebro.adddata(data_feed)
            cerebro.broker.setcash(initial_cash)

            if commission_scheme:
                cerebro.broker.addcommissioninfo(commission_scheme)

            # Add the observer wrapper
            cerebro.addstrategy(
                _ObserverStrategy,
                user_strategy_class=strategy_class,
                user_params=params,
                event_queue=self.event_queue,
                control_queue=self.control_queue,
                speed=speed,
                ring_buffer=self._ring_buffer,
            )
            # Add the actual user strategy (separate)
            cerebro.addstrategy(strategy_class, **params)

            self._cerebro = cerebro
            self._running = True

        self._future = self._executor.submit(self._run_cerebro)

    def _run_cerebro(self) -> None:
        try:
            self._cerebro.run()
        except Exception as exc:
            # Put a sentinel so the consumer knows we stopped
            try:
                self.event_queue.put_nowait({"error": str(exc)})
            except queue.Full:
                pass
        finally:
            with self._lock:
                self._running = False
            # Sentinel: None signals end of stream
            try:
                self.event_queue.put(None, timeout=5)
            except queue.Full:
                pass

    def pause(self) -> None:
        self.control_queue.put(ControlMessage(ControlSignal.PAUSE))

    def resume(self) -> None:
        self.control_queue.put(ControlMessage(ControlSignal.RESUME))

    def step_forward(self) -> None:
        self.control_queue.put(ControlMessage(ControlSignal.STEP_FORWARD))

    def step_backward(self) -> Optional[BarEvent]:
        """Return previous bar from ring buffer (does not re-run cerebro)."""
        if len(self._ring_buffer) >= 2:
            return self._ring_buffer[-2]
        return None

    def stop(self) -> None:
        self.control_queue.put(ControlMessage(ControlSignal.STOP))
        if self._future:
            try:
                self._future.result(timeout=5)
            except Exception:
                pass
        with self._lock:
            self._running = False

    def set_speed(self, speed: float) -> None:
        self.control_queue.put(ControlMessage(ControlSignal.SET_SPEED, speed))

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def ring_buffer(self) -> Deque[BarEvent]:
        return self._ring_buffer

    def get_recent_bars(self, n: int = 200) -> List[BarEvent]:
        return list(self._ring_buffer)[-n:]


def _drain(q: queue.Queue) -> None:
    """Empty a queue without blocking."""
    try:
        while True:
            q.get_nowait()
    except queue.Empty:
        pass

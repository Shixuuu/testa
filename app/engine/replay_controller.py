"""ReplayController: orchestrates bar-by-bar replay with speed control."""
import asyncio
import queue
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .events import (
    BarEvent, TradeEvent, OrderEvent, PropViolationEvent, RunCompleteEvent,
)
from .backtrader_runner import BacktraderRunner, SIGNAL_STOP


SPEED_MAP = {
    "0x": 0,
    "1x": 1,
    "5x": 5,
    "25x": 25,
    "100x": 100,
    "max": 999,
}

SPEED_DELAY = {
    0: None,       # paused
    1: 1.0,        # 1 bar per second (configurable)
    5: 0.2,
    25: 0.04,
    100: 0.01,
    999: 0.0,
}


@dataclass
class ReplayState:
    bar_index: int = 0
    total_bars: int = 0
    speed: int = 0           # 0 = paused
    is_complete: bool = False
    current_bar: Optional[BarEvent] = None
    open_trades: list = field(default_factory=list)
    closed_trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)   # [(bar_index, equity)]
    daily_pnl: dict = field(default_factory=dict)      # date_str -> float
    cash: float = 0.0
    bookmarks: list = field(default_factory=list)


class ReplayController:
    """
    Controls playback of a BacktraderRunner's event stream.
    Subscribers receive events via registered callbacks.
    """

    RING_BUFFER_SIZE = 500

    def __init__(self, runner: BacktraderRunner, loop: asyncio.AbstractEventLoop):
        self._runner = runner
        self._loop = loop
        self._state = ReplayState(cash=runner.initial_cash)
        self._state.equity_curve = [(0, runner.initial_cash)]

        self._ring: deque[BarEvent] = deque(maxlen=self.RING_BUFFER_SIZE)
        self._bar_history: list[BarEvent] = []

        self._callbacks: dict[str, list[Callable]] = {
            "bar": [],
            "trade": [],
            "order": [],
            "violation": [],
            "complete": [],
            "state_change": [],
        }

        self._poll_task: Optional[asyncio.Task] = None
        self._running = False
        self._step_once = False

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @property
    def state(self) -> ReplayState:
        return self._state

    def on(self, event: str, cb: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(cb)

    def pause(self):
        self._state.speed = 0
        self._notify_state()

    def play(self, speed: int = 1):
        self._state.speed = speed
        self._notify_state()

    def step_forward(self):
        """Advance exactly one bar."""
        if self._state.speed != 0:
            return
        self._step_once = True
        self._notify_state()

    def step_backward(self):
        """Rewind one bar using ring buffer."""
        if len(self._ring) < 2:
            return
        self._ring.pop()  # discard current
        if self._ring:
            prev = self._ring[-1]
            self._state.bar_index = max(0, self._state.bar_index - 1)
            self._state.current_bar = prev
            for cb in self._callbacks["bar"]:
                self._schedule(cb, prev)
            self._notify_state()

    def set_bookmark(self):
        self._state.bookmarks.append(self._state.bar_index)

    def jump_to_bookmark(self):
        if self._state.bookmarks:
            _ = self._state.bookmarks[-1]  # jump not fully implemented without seek

    def toggle_speed(self, speed_label: str):
        self._state.speed = SPEED_MAP.get(speed_label, 0)
        self._notify_state()

    def start(self):
        """Start the runner and begin polling events."""
        self._runner.start()
        self._running = True
        self._poll_task = self._loop.create_task(self._poll_loop())

    async def stop(self):
        self._running = False
        self._runner.send(SIGNAL_STOP)
        if self._poll_task:
            self._poll_task.cancel()

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    async def _poll_loop(self):
        """Drain the runner's event queue at the current playback speed."""
        while self._running:
            speed = self._state.speed
            delay = SPEED_DELAY.get(speed, 0.0)

            if speed == 0 and not self._step_once:
                await asyncio.sleep(0.05)
                continue

            # Try to get one event
            try:
                event = self._runner.event_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)
                continue

            self._step_once = False
            await self._dispatch(event)

            if delay and delay > 0:
                await asyncio.sleep(delay)

    async def _dispatch(self, event):
        if isinstance(event, BarEvent):
            self._state.bar_index = event.bar_index
            self._state.current_bar = event
            self._ring.append(event)
            self._bar_history.append(event)
            # Update equity curve (approximation; true equity from broker state)
            for cb in self._callbacks["bar"]:
                await self._acall(cb, event)
        elif isinstance(event, TradeEvent):
            if event.is_open:
                self._state.open_trades.append(event)
            else:
                self._state.open_trades = [
                    t for t in self._state.open_trades
                    if t.trade_id != event.trade_id
                ]
                self._state.closed_trades.append(event)
                # Update equity
                if self._state.equity_curve:
                    last_eq = self._state.equity_curve[-1][1]
                    new_eq = last_eq + (event.pnl or 0) - event.commission
                    self._state.equity_curve.append((event.bar_index, new_eq))
                # Track daily P&L
                date_str = event.timestamp.strftime("%Y-%m-%d")
                self._state.daily_pnl[date_str] = (
                    self._state.daily_pnl.get(date_str, 0.0)
                    + (event.pnl or 0.0)
                )
            for cb in self._callbacks["trade"]:
                await self._acall(cb, event)
        elif isinstance(event, OrderEvent):
            for cb in self._callbacks["order"]:
                await self._acall(cb, event)
        elif isinstance(event, PropViolationEvent):
            for cb in self._callbacks["violation"]:
                await self._acall(cb, event)
        elif isinstance(event, RunCompleteEvent):
            self._state.is_complete = True
            self._state.total_bars = event.total_bars
            for cb in self._callbacks["complete"]:
                await self._acall(cb, event)
            self._running = False

    def _notify_state(self):
        for cb in self._callbacks["state_change"]:
            self._schedule(cb, self._state)

    def _schedule(self, cb: Callable, *args):
        if asyncio.iscoroutinefunction(cb):
            self._loop.create_task(cb(*args))
        else:
            self._loop.call_soon_threadsafe(cb, *args)

    async def _acall(self, cb: Callable, *args):
        if asyncio.iscoroutinefunction(cb):
            await cb(*args)
        else:
            cb(*args)

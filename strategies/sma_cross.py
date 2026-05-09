"""
SMA Crossover strategy — simple 20/50 SMA cross for demo purposes.
Works as a standard Backtrader Strategy subclass with no modifications.
"""
import backtrader as bt


class SmaCross(bt.Strategy):
    """Simple dual-SMA crossover: go long on fast-over-slow, short on cross-under."""

    # Metadata displayed in TUI strategy panel
    _meta = {
        "name": "SMA Crossover",
        "description": "Long on fast SMA cross above slow SMA; short on cross below.",
        "params": {
            "fast": "Fast SMA period",
            "slow": "Slow SMA period",
            "risk_pct": "% of equity risked per trade",
            "stop_atr_mult": "Stop loss = ATR * this multiplier",
        },
    }

    params = (
        ("fast", 10),
        ("slow", 30),
        ("risk_pct", 0.01),
        ("stop_atr_mult", 1.5),
        ("atr_period", 14),
        ("size", 1),
    )

    def __init__(self):
        self.fast_ma = bt.indicators.SMA(self.data.close, period=self.p.fast)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=self.p.slow)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:
            if self.crossover > 0:
                self.order = self.buy(size=self.p.size)
            elif self.crossover < 0:
                self.order = self.sell(size=self.p.size)
        else:
            if self.position.size > 0 and self.crossover < 0:
                self.order = self.close()
            elif self.position.size < 0 and self.crossover > 0:
                self.order = self.close()

    def notify_order(self, order):
        if order.status in (order.Completed, order.Canceled, order.Margin):
            self.order = None

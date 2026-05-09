"""
RSI Mean Reversion strategy — buy oversold, sell overbought.
Works as a standard Backtrader Strategy subclass with no modifications.
"""
import backtrader as bt


class RsiMeanRevert(bt.Strategy):
    _meta = {
        "name": "RSI Mean Reversion",
        "description": "Buy when RSI < oversold; sell when RSI > overbought.",
        "params": {
            "rsi_period": "RSI lookback period",
            "oversold": "RSI level to go long",
            "overbought": "RSI level to go short",
            "size": "Contracts per trade",
        },
    }

    params = (
        ("rsi_period", 14),
        ("oversold", 30),
        ("overbought", 70),
        ("size", 1),
        ("exit_rsi", 50),
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:
            if self.rsi < self.p.oversold:
                self.order = self.buy(size=self.p.size)
            elif self.rsi > self.p.overbought:
                self.order = self.sell(size=self.p.size)
        else:
            if self.position.size > 0 and self.rsi > self.p.exit_rsi:
                self.order = self.close()
            elif self.position.size < 0 and self.rsi < self.p.exit_rsi:
                self.order = self.close()

    def notify_order(self, order):
        if order.status in (order.Completed, order.Canceled, order.Margin):
            self.order = None

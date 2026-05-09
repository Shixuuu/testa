"""
Futures Backtest TUI - Bloomberg Terminal Style
Main entry point.
"""
from futures_tui.app import FuturesBacktestApp
import sys


if __name__ == "__main__":
    app = FuturesBacktestApp()
    app.run()

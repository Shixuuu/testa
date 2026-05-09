#!/usr/bin/env python3
"""
Futures Backtest TUI — entry point.

Usage:
    python main.py
    python main.py --data data/demo/es_demo_5m.csv --strategy strategies/sma_cross.py
    python main.py --help
"""
import sys
import argparse
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Futures Backtest TUI — terminal-based backtesting platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py
  python main.py --data mydata.csv --strategy strategies/sma_cross.py --instrument ES
  python main.py --cash 100000 --firm firm_profiles/apex_100k.toml

Keyboard shortcuts (in app):
  Space   Play/Pause       ]  Step forward    [  Step backward
  F       5x speed         Shift+F  25x       M  Max speed
  D       Data manager     S  Strategy        P  Prop firm config
  A       Analytics        C  Monte Carlo     R  Reset
  ?       Help             Q  Quit
        """,
    )
    parser.add_argument("--data", "-d", default=None, help="Path to OHLCV CSV or Parquet file")
    parser.add_argument("--strategy", "-s", default=None, help="Path to Backtrader strategy .py file")
    parser.add_argument("--instrument", "-i", default="ES", help="Futures symbol (ES, NQ, CL, GC, ...)")
    parser.add_argument("--cash", "-c", type=float, default=50000.0, help="Initial account cash")
    parser.add_argument("--firm", "-f", default=None, help="Path to prop firm TOML profile")
    parser.add_argument("--generate-demo", action="store_true", help="Generate demo data and exit")
    parser.add_argument("--version", action="version", version="Futures Backtest TUI 1.0.0")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.generate_demo:
        from data.demo.generate_demo import generate_es_demo
        path = generate_es_demo()
        print(f"Demo data written to: {path}")
        sys.exit(0)

    from app.app import FuturesBacktestTUI

    app = FuturesBacktestTUI()

    # Apply CLI overrides
    if args.data:
        app._data_path = args.data
    if args.strategy:
        app._strategy_path = args.strategy
    if args.instrument:
        app._instrument = args.instrument.upper()
    if args.cash:
        app._initial_cash = args.cash

    if args.firm:
        from app.engine.prop_rules import PropFirmProfile
        from app.engine.prop_rules import PropRulesEngine
        try:
            profile = PropFirmProfile.from_toml(args.firm)
            app._prop_profile = profile
            app._prop_engine = PropRulesEngine(profile)
            app._prop_enabled = True
        except Exception as e:
            print(f"Warning: could not load firm profile: {e}", file=sys.stderr)

    app.run()


if __name__ == "__main__":
    main()

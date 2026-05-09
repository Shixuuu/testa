# FUTURES BACKTEST TUI
## Product Requirements Document

> **Version:** 1.0.0 | **Status:** Draft | **Domain:** Futures / Prop | **Engine:** Backtrader

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Product Vision & Goals](#2-product-vision--goals)
3. [User Personas](#3-user-personas)
4. [System Architecture](#4-system-architecture)
5. [Core Engine — Backtrader Bridge](#5-core-engine--backtrader-bridge)
6. [Bar Replay Module](#6-bar-replay-module)
7. [TUI Layout & Navigation](#7-tui-layout--navigation)
8. [Prop Firm Rules Engine](#8-prop-firm-rules-engine)
9. [Monte Carlo Simulation Module](#9-monte-carlo-simulation-module)
10. [Quantitative Analytics Suite](#10-quantitative-analytics-suite)
11. [Strategy Management](#11-strategy-management)
12. [Data Management](#12-data-management)
13. [Hotkeys & UX](#13-hotkeys--ux)
14. [Configuration & Persistence](#14-configuration--persistence)
15. [Non-Functional Requirements](#15-non-functional-requirements)
16. [Development Phases & Milestones](#16-development-phases--milestones)
17. [Appendix — Metric Definitions](#17-appendix--metric-definitions)

---

## 1. Executive Summary

Futures Backtest TUI is a keyboard-driven, terminal-based backtesting and strategy-analysis platform targeting individual futures traders who operate under prop firm evaluation programs (FTMO, TopstepTrader, Apex, Earn2Trade, etc.). It combines the battle-tested Backtrader execution engine with an interactive bar-replay experience inspired by FX Replay, a rich quantitative analytics layer, and a purpose-built Prop Firm Rules Engine that enforces daily loss limits, trailing drawdown thresholds, consistency rules, and position-size constraints — all configurable per firm profile.

The TUI is built with Textual, delivering a full-featured interface entirely inside a terminal — no browser, no Electron, no GUI dependencies. Users can load historical tick or OHLCV data, step through bars one-at-a-time as if trading live, inspect every decision their strategy made in context, run thousands of Monte Carlo paths to stress-test equity curves, and generate publication-quality quantitative reports — without ever leaving the terminal.

> **Why TUI?** Professional traders spend their lives in terminals. A TUI means zero latency, scriptable CI integration, SSH-native operation, and focus — no distractions from browser tabs or notification overlays.

---

## 2. Product Vision & Goals

### 2.1 Vision Statement

To give prop firm traders the most honest, friction-free window into their strategy's real-world behavior — including firm-specific constraints — so they can identify edge, fix failure modes, and pass evaluations with confidence.

### 2.2 Strategic Goals

| Goal | Success Metric | Priority |
|------|---------------|----------|
| Full prop firm rule enforcement | Zero rule violations slip through in replay or backtest mode | P0 |
| Bar replay fidelity | Step-by-step replay matches live trading perception within 1 tick | P0 |
| Monte Carlo robustness scoring | Generate 10,000-path simulation in < 5 seconds | P0 |
| Quantitative completeness | All 30+ metrics computed and displayed in a single session | P1 |
| Zero external dependencies at runtime | Works in a plain Python 3.10+ venv, no Docker | P1 |
| Strategy hot-reload | Modify strategy file on disk, reload without restarting app | P2 |
| Multi-instrument support | ES, NQ, CL, GC, 6E and any custom contract in one session | P2 |

---

## 3. User Personas

### Persona A — The Prop Firm Candidate

Intermediate-to-advanced retail futures trader. Paid for an evaluation account (typically $5K–$150K simulated account). Their primary anxiety is rule violations: blowing the daily loss limit on day 3, or being disqualified by a consistency rule they didn't fully understand. They need to know their strategy's worst drawdown behavior under realistic market conditions before they risk evaluation fees.

### Persona B — The Systematic Quant

Builds rule-based strategies in Python using Backtrader. Cares about Sharpe, Sortino, Calmar, profit factor, and distribution of returns more than the chart. Needs Monte Carlo to understand if their edge is real or a product of in-sample overfitting. SSH access to a VPS is their primary workflow.

### Persona C — The Discretionary Researcher

Uses bar replay to study past price action and annotate where a strategy fired versus where a human would have traded. Uses the tool as a research journal, not just a backtest runner. Needs fine-grained bar stepping and the ability to bookmark moments in a replay session.

---

## 4. System Architecture

### 4.1 High-Level Component Diagram

```
┌─────────────────────────────────────────────────────┐
│              TEXTUAL TUI LAYER                      │
│  ChartWidget  TradeLog  StatsPanel  PropRulesPanel  │
└──────────────┬──────────────────────────────────────┘
               │ events / reactive state
┌──────────────▼──────────────────────────────────────┐
│         REPLAY CONTROLLER  (engine.py)              │
│  BarQueue  |  PropRulesEngine  |  StateEmitter      │
└──────┬────────────────────────┬─────────────────────┘
       │                        │
┌──────▼──────────┐    ┌────────▼──────────────────────┐
│ BACKTRADER CORE  │    │  ANALYTICS ENGINE              │
│ Strategy         │    │  MonteCarlo | Metrics | Reports│
│ Broker sim       │    │                               │
└──────┬──────────┘    └───────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────┐
│  DATA LAYER   CSV | Parquet | IB / CQG / Rithmic    │
└─────────────────────────────────────────────────────┘
```

### 4.2 Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| TUI Framework | Textual 0.60+ | Async-native, CSS-like layout, reactive state, rich widget library |
| Backtest Engine | Backtrader 1.9.78 | Mature, extensible, handles futures commissions/margin natively |
| Data Processing | pandas + numpy | Standard. Parquet support for fast large-dataset loading |
| Terminal Charts | plotext + custom Textual canvas | plotext for sparklines; custom canvas for full candlestick rendering |
| Stats / Monte Carlo | numpy, scipy.stats | Vectorized path generation, distribution fitting |
| Config | TOML (tomllib stdlib) | Human-editable prop firm profiles, strategy params |
| Export | rich console export, CSV | Shareable HTML reports; CSV for external analysis |

---

## 5. Core Engine — Backtrader Bridge

### 5.1 Overview

The Backtrader Bridge is the adapter layer between Textual's async event loop and Backtrader's synchronous cerebro run loop. It runs Backtrader in a separate thread or process, draining bar events into a queue that the TUI consumes incrementally — enabling step-by-step replay without blocking the UI.

### 5.2 Key Components

#### BacktraderRunner
- Wraps `cerebro.run()` in a thread-safe context
- Emits `BarEvent`, `TradeEvent`, `OrderEvent`, `IndicatorEvent` after each bar
- Accepts control signals: `PAUSE`, `STEP`, `FAST_FORWARD`, `RESET`, `STOP`

#### ReplayController
- Manages playback speed: 0x (paused), 1x, 5x, 25x, 100x, MAX
- Supports step-forward and step-backward (caches last N bars in a ring buffer)
- Bar bookmarking: mark any bar as a checkpoint, jump back to it
- Exposes `current_bar_index`, `total_bars`, `playback_speed` as reactive state

#### FuturesCommissionScheme
Custom Backtrader commission scheme handling:
- Per-contract round-trip commissions (e.g. $4.00 RT for ES)
- Exchange fees + NFA fees separated
- Margin requirements per contract (initial and maintenance)
- Point value and tick size per instrument

### 5.3 Supported Instruments (Initial)

| Symbol | Exchange | Point Value | Tick Size | Default Margin |
|--------|----------|-------------|-----------|----------------|
| ES | CME | $50 | 0.25 | $12,500 |
| NQ | CME | $20 | 0.25 | $16,500 |
| CL | NYMEX | $1,000 | 0.01 | $6,000 |
| GC | COMEX | $100 | 0.10 | $9,500 |
| 6E | CME | $125,000 | 0.00005 | $2,800 |
| MES | CME | $5 | 0.25 | $1,250 |
| MNQ | CME | $2 | 0.25 | $1,650 |
| Custom | User-defined | Configurable | Configurable | Configurable |

---

## 6. Bar Replay Module

### 6.1 Concept

Bar Replay is the core interactive feature, directly inspired by FX Replay's workflow. The user loads a dataset and a strategy, then watches bars build from left to right exactly as they would in a live session. The strategy fires signals, orders get placed and filled, and the P&L updates in real-time — but the user is in control of time.

### 6.2 Replay Modes

| Mode | Description | Hotkey |
|------|-------------|--------|
| Paused | No bars advance. User inspects current state. | `Space` |
| Step Forward | Advances exactly one bar. Works at any timeframe. | `]` or `→` |
| Step Backward | Rewinds one bar using ring buffer cache. | `[` or `←` |
| Play 1x | Real-time simulation at 1 bar per configured interval. | `P` |
| Fast Forward 5x | 5x playback speed. | `F` |
| Fast Forward 25x | 25x playback speed. | `Shift+F` |
| Max Speed | Runs as fast as CPU allows. For full backtest runs. | `M` |
| Jump to Bar | Enter a bar index or timestamp to jump to. | `G` |
| Jump to Trade | Cycle through entries/exits. | `N` / `B` |
| Jump to Bookmark | Return to a previously set checkpoint. | `Ctrl+B` |

### 6.3 Visual Replay Behavior

- Candlesticks build left-to-right; rightmost candle is always the current bar
- Entry markers: green triangle up (long), red triangle down (short)
- Exit markers: X with color matching trade P&L (green = profit, red = loss)
- Stop loss and take profit levels drawn as horizontal dashed lines on the chart
- Indicators (MA, BB bands, VWAP, etc.) build progressively — no look-ahead
- Current bar highlighted with a contrasting border
- Sidebar shows OHLCV of current bar, timestamp, and bar index

### 6.4 Tick Replay (Phase 2)

When tick data is provided, the replay module will step through individual ticks within a bar, showing intrabar price action. This is critical for strategies that place intrabar stop orders or have partial fills. Tick replay sources: Rithmic historical tick feed, IQFeed, or user-supplied CSV with millisecond timestamps.

---

## 7. TUI Layout & Navigation

### 7.1 Screen Layout

```
╔══════════════╦═══════════════════════════════════════════════╗
║ STRATEGY     ║              CHART PANEL                     ║
║ PANEL        ║   Candlesticks + Indicators                  ║
║ Params       ║   Trade Markers + SL/TP lines                ║
║ Indicators   ║   Volume histogram (bottom)                  ║
╠══════════════╬═══════════════════════════════════════════════╣
║ POSITION     ║              TRADE LOG                       ║
║ Open PnL     ║  #  | Time | Dir | Entry | Exit | PnL | R   ║
║ Margin used  ║  Scrollable, filterable by date or direction ║
╠══════════════╬═══════════════════════════════════════════════╣
║ PROP RULES   ║              PORTFOLIO STATS                 ║
║ Daily Loss   ║  Sharpe | Sortino | Calmar | Win Rate | PF  ║
║ Drawdown     ║  Max DD | Expectancy | R-multiple dist       ║
╠══════════════╩═══════════════════════════════════════════════╣
║  STATUS BAR: Bar 1247/3500  |  Speed: 1x  |  [Space]=Pause ║
╚═════════════════════════════════════════════════════════════╝
```

### 7.2 Screens / Views

- **Main View** — the layout above. Default on launch.
- **Data Manager** (`D`) — browse, load, and normalize data files
- **Strategy Editor** (`S`) — configure params, select strategy file, hot-reload
- **Prop Firm Config** (`P`) — select firm profile, toggle rules, set account size
- **Monte Carlo View** (`C`) — run simulations, view equity curve fan chart
- **Analytics Report** (`A`) — full quantitative summary, exportable
- **Hotkey Help** (`?`) — full keyboard reference overlay

---

## 8. Prop Firm Rules Engine

### 8.1 Overview

The Prop Firm Rules Engine is a toggleable constraint layer that runs in parallel with the backtest engine. It tracks every rule a prop firm imposes and surfaces violations in real-time — both as warnings before breach and hard stops at breach. Each rule can be individually toggled on or off to test strategy behavior without specific constraints.

> **Design Intent:** The engine is profile-based. A TOML file defines a firm profile (e.g. `apex_50k.toml`). Users can clone and customize profiles. Switching profiles is a hotkey away. All rules default to the most restrictive interpretation when ambiguous.

### 8.2 Rule Categories

#### 8.2.1 Loss Rules

| Rule | Description | Toggle | Configurable |
|------|-------------|--------|-------------|
| Daily Loss Limit | Maximum net P&L loss allowed in a single trading day. Breach = disqualification. | Yes | Dollar amount, % of account |
| Trailing Drawdown | Account equity must never fall below a trailing high watermark minus the drawdown threshold. The trail follows profits upward but never moves down. | Yes | Threshold $, trail resets on payout |
| Maximum Drawdown | Static. Account cannot breach a fixed floor below starting balance. | Yes | Dollar amount |
| Weekly Loss Limit | Some firms impose a weekly cap in addition to daily. | Yes | Dollar amount |
| Loss Per Trade | Cap on loss from any single trade. Forces a stop-loss discipline. | Yes | Dollar amount or % of balance |

#### 8.2.2 Profit & Consistency Rules

| Rule | Description | Toggle | Configurable |
|------|-------------|--------|-------------|
| Minimum Trading Days | Must trade on N distinct days before qualifying for payout. | Yes | Day count |
| Profit Target | Must reach a specified profit target to pass evaluation phase. | Yes | Dollar amount |
| Consistency Rule | No single trading day's profit can exceed X% of total net profit. Prevents a single lucky day from passing. | Yes | Percentage (common: 30–40%) |
| Minimum Profit Days | Requires a minimum number of profitable trading days. | Yes | Day count |
| Max Lots per Trade | Limits contracts per order. | Yes | Contract count |
| Max Open Lots | Limits aggregate open contracts across all positions. | Yes | Contract count |
| News Trading Ban | Disallows entries within N minutes of high-impact news events. | Yes | Minutes window |
| Overnight Position Ban | All positions must be flat at end-of-session. | Yes | Session close time |
| Weekend Position Ban | No positions held over Friday close. | Yes | Toggle |

### 8.3 Pre-Built Firm Profiles

| Profile | Trailing DD | Daily Limit | Profit Target | Consistency | Min Days |
|---------|------------|-------------|---------------|-------------|----------|
| Apex 50K | $2,500 | $1,000 | $3,000 | None | 5 |
| Apex 100K | $3,000 | $1,000 | $6,000 | None | 5 |
| TopstepTrader 50K | $2,000 | $1,000 | $3,000 | None | 5 |
| FTMO 100K | Static 10% | 5% / day | 10% | None | 4 |
| Earn2Trade 50K | $2,000 | $1,100 | $3,000 | 40% | 5 |
| MyFundedFutures 50K | $2,500 | $1,100 | $3,000 | None | 5 |
| Custom | User-defined | User-defined | User-defined | User-defined | User-defined |

### 8.4 Rule Violation Behavior

- **WARNING state:** P&L within 10% of any limit. Panel border turns amber, warning pops in status bar.
- **BREACH state:** Limit crossed. Hard stop issued to strategy. Panel border turns red. Breach logged with timestamp and cause.
- Backtest completion report includes: total breaches, breach type, bar at breach, account balance at breach, and trading days remaining.
- Toggle violations off to run the strategy unrestricted and compare equity curves side by side.

---

## 9. Monte Carlo Simulation Module

### 9.1 Purpose

A single backtest on a fixed sequence of trades is not sufficient to evaluate a strategy. The Monte Carlo module generates thousands of alternative equity curves by resampling the trade return distribution, enabling the user to understand the range of outcomes their strategy could produce — including worst-case scenarios that the historical backtest may have never surfaced.

### 9.2 Simulation Methods

| Method | Description | When to Use |
|--------|-------------|-------------|
| Trade Shuffling | Randomly reorders the historical trade sequence N times. Preserves the empirical return distribution but randomizes sequencing. | General robustness testing |
| Return Sampling with Replacement | Bootstraps individual trade returns to create synthetic trade sequences of equal or variable length. | Testing longer or shorter time horizons |
| Parametric (Normal) | Fits a Normal distribution to trade returns, then samples from it. Faster but assumes normality. | Quick sensitivity check |
| Parametric (Student-t) | Fits a Student-t distribution — heavier tails than Normal. More realistic for futures. | Tail risk assessment |
| Block Bootstrap | Resamples contiguous blocks of trades to preserve autocorrelation structure. | Mean-reverting or trend strategies with clustered returns |

### 9.3 Outputs

#### Equity Curve Fan Chart
Displays all N simulated equity paths as a faded fan, with the median path highlighted in white and the 5th/95th percentile bounds in amber and red respectively. The historical equity curve is overlaid in cyan.

#### Summary Statistics Table

| Metric | Description |
|--------|-------------|
| Median Final Equity | 50th percentile ending account value across all paths |
| 5th Percentile Final Equity | Worst-case bound (1-in-20 outcome) |
| Probability of Ruin | % of paths that breach the maximum drawdown or daily loss limit |
| Probability of Hitting Target | % of paths that reach the prop firm profit target before drawdown breach |
| Median Max Drawdown | 50th percentile of maximum drawdown across all paths |
| 95th Percentile Max Drawdown | Tail drawdown — what a bad-luck run looks like |
| Expected Payoff | Average final equity across all paths, accounting for path dependency |
| Drawdown at Risk (DaR 95%) | The drawdown level exceeded only 5% of the time |
| Time to Ruin Distribution | Histogram of how many bars/days until ruin, for paths that ruined |

### 9.4 Prop Firm Integration

When a prop firm profile is active, Monte Carlo simulates the full rule set on every generated path — not just drawdown. Each path is evaluated against daily loss limits, trailing drawdown, consistency rules, and minimum trading days. Output includes:

- **Pass rate:** % of Monte Carlo paths that successfully pass the evaluation
- **Average days to pass** (for passing paths)
- **Most common failure rule** across all failing paths
- **Sensitivity analysis:** which rule is binding most often

### 9.5 Configuration

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| Number of paths (N) | 10,000 | 100–100,000 | More paths = better convergence, slower computation |
| Simulation method | Trade Shuffling | All 5 methods | Selected in UI before run |
| Confidence interval | 5% / 95% | 1–49% | Percentile bounds shown on fan chart |
| Seed | Random | Any integer | Fixed seed for reproducible results |
| Path length | Same as backtest | 1–10,000 trades | Can extend beyond historical trade count |

---

## 10. Quantitative Analytics Suite

### 10.1 Return Metrics

| Metric | Formula / Notes | Interpretation |
|--------|----------------|---------------|
| Net P&L | Sum of all closed trade P&L minus commissions | Absolute profitability |
| CAGR | Annualized geometric return | Growth rate normalized to 1 year |
| Total Return % | (Final equity / Initial equity - 1) × 100 | Percentage gain on starting capital |
| Daily Return Distribution | Histogram of daily P&L | Shape reveals return clustering |

### 10.2 Risk-Adjusted Return Metrics

| Metric | Formula | Target Range |
|--------|---------|-------------|
| Sharpe Ratio | (Mean daily return − Rf) / StdDev × √252 | > 1.0 acceptable, > 2.0 excellent |
| Sortino Ratio | Same as Sharpe but denominator uses downside deviation only | > 1.5 acceptable, > 3.0 excellent |
| Calmar Ratio | CAGR / Maximum Drawdown | > 0.5 acceptable, > 3.0 excellent |
| Omega Ratio | Integral of gains above threshold / integral of losses below threshold | > 1.0 required (> 2.0 excellent) |
| Ulcer Index | RMS of all drawdown depths over period | Lower is better; < 5% excellent |
| UPI (Martin Ratio) | Annualized return / Ulcer Index | Higher is better; > 2.0 excellent |
| Kappa-3 | Excess return / cube root of 3rd lower partial moment | Tail-sensitive, > 1.0 acceptable |

### 10.3 Trade-Level Metrics

| Metric | Description |
|--------|-------------|
| Win Rate | % of trades closed with positive P&L |
| Profit Factor | Gross profit / Gross loss. > 1.5 is generally considered tradeable. |
| Expectancy | (Win Rate × Avg Win) − (Loss Rate × Avg Loss). The true measure of edge. |
| Average Win / Average Loss | Reward-to-risk ratio in raw dollar terms |
| Average R-Multiple | Each trade's P&L normalized to its initial risk. Mean R > 0.3 is meaningful. |
| R-Multiple Distribution | Histogram of R-multiples. Should have positive skew for robust strategies. |
| Largest Win / Largest Loss | Flags outlier trades that may be dominating results |
| Consecutive Wins / Losses | Max run of winners and losers. Long loss streaks expose psychological risk. |
| Trade Duration (Avg/Max/Min) | Time in market per trade. Relevant for overnight/news exposure. |
| MAE (Max Adverse Excursion) | Largest intrabar move against position before exit. Validates stop placement. |
| MFE (Max Favorable Excursion) | Largest intrabar move in favor before exit. Reveals if exits are too early. |
| ETD (Edge-to-Trade Draw) | MFE minus actual P&L. Quantifies profit left on the table per trade. |

### 10.4 Drawdown Analysis

| Metric | Description |
|--------|-------------|
| Maximum Drawdown (MDD) | Largest peak-to-trough equity decline (absolute and %) |
| Average Drawdown | Mean depth of all drawdown periods |
| Drawdown Duration | Length of longest drawdown (bars and calendar days) |
| Recovery Factor | Net Profit / Maximum Drawdown. > 3.0 is a healthy buffer. |
| Time Underwater % | % of time the strategy was below its previous equity high |
| Drawdown at Risk 95% (DaR) | 95th percentile drawdown from Monte Carlo paths |

### 10.5 Statistical Validity Metrics

| Metric | Description | Why It Matters |
|--------|-------------|---------------|
| t-Statistic on Returns | Tests if mean return is statistically different from zero | Prevents confusing luck with edge |
| p-Value | Probability of observed results under null hypothesis of no edge | < 0.05 is standard threshold |
| Sharpe t-stat | Sharpe ratio / its standard error, accounts for sample size | Corrects Sharpe for short backtests |
| Probabilistic Sharpe Ratio (PSR) | Probability that true Sharpe > benchmark Sharpe, given sample size | Quantifies confidence in Sharpe estimate |
| Deflated Sharpe Ratio (DSR) | PSR adjusted for multiple testing / selection bias | Essential if you tested many strategies |
| Number of Trades (N adequacy) | Flags if N < 30 (insufficient for reliable stats) | Prevents overfitting on small samples |
| Autocorrelation (Ljung-Box) | Tests if returns are serially correlated | Autocorrelation inflates Sharpe artificially |
| Skewness of returns | Positive = right tail; Negative = crash-prone | Negative skew is dangerous at leverage |
| Kurtosis of returns | Excess kurtosis > 3 indicates fat tails | Fat-tail strategies can blow up |
| Variance Inflation (VIF) | Checks for collinearity in factor exposures | Relevant for multi-factor strategies |

### 10.6 Prop Firm Pass/Fail Analytics

| Metric | Description |
|--------|-------------|
| Days to Target | How many trading days until profit target reached (historical and MC median) |
| Daily Loss Proximity | Each trading day: how close did the strategy come to the daily limit (% of limit consumed) |
| Trailing Drawdown Path | Chart showing how the trailing drawdown level moved over time vs. equity |
| Consistency Score | Best single day's profit as % of total net profit (lower = more consistent) |
| Evaluation Pass Probability | From Monte Carlo: % of paths that pass all firm rules without violation |

---

## 11. Strategy Management

### 11.1 Strategy File Format

Strategies are standard Backtrader `Strategy` subclasses, with no modifications required to the class definition. The only addition is an optional `metadata` dict at the class level for the TUI to display param descriptions.

### 11.2 Loading & Hot-Reload

- Strategies are loaded from a user-specified Python file via `importlib`
- File watcher (`watchdog`) monitors the strategy file for changes on disk
- On change: the replay resets to bar 0, the new strategy class is compiled, and replay restarts automatically with the same dataset and firm profile
- Hot-reload can be toggled off to prevent accidental restarts during active replay

### 11.3 Parameter Tuning Panel

The Strategy Panel exposes all Backtrader `params` for live editing. Changes take effect on the next replay reset. Parameters are type-aware (int, float, bool, string). Boolean params render as toggles; enums render as dropdowns; numerics show a slider with min/max bounds defined in the strategy metadata.

### 11.4 Multi-Strategy Comparison (Phase 2)

Run two strategies on the same dataset simultaneously and compare their equity curves, trade logs, and analytics side-by-side in a split-screen view. Enables A/B testing of parameter variations or entirely different approaches.

---

## 12. Data Management

### 12.1 Supported Formats

| Format | Timeframes | Notes |
|--------|-----------|-------|
| CSV (OHLCV) | Any (auto-detected from timestamps) | Must have: datetime, open, high, low, close, volume columns |
| Parquet | Any | Preferred for large datasets. Load time is ~10x faster than CSV. |
| Rithmic Historical | Tick, 1m, 5m, daily | Phase 2. Requires Rithmic API credentials. |
| Interactive Brokers | 1m and above | Phase 2. Via ib_insync integration. |
| CQG | Tick and above | Phase 2. |
| Yahoo Finance (yfinance) | Daily only | For index/ETF research, not futures |

### 12.2 Data Preprocessing

- Gap detection and flagging (overnight gaps, weekend gaps, rollover gaps)
- Session filtering: restrict data to RTH (Regular Trading Hours) or include ETH
- Rollover handling: detect contract expiry and adjust or stitch continuous contracts using backward/forward adjustment
- Missing bar interpolation or drop — user configurable
- Normalization report: shows data quality summary before replay starts

---

## 13. Hotkeys & UX

### 13.1 Global Hotkeys

| Key | Action | Context |
|-----|--------|---------|
| `Space` | Play / Pause replay | Global |
| `]` / `→` | Step one bar forward | Global |
| `[` / `←` | Step one bar backward | Global |
| `F` | 5x fast forward | Global |
| `Shift+F` | 25x fast forward | Global |
| `M` | Max speed (full backtest run) | Global |
| `G` | Go to bar / timestamp (opens prompt) | Global |
| `N` / `B` | Jump to next / previous trade | Global |
| `R` | Reset replay to bar 0 | Global |
| `Ctrl+B` | Set / jump to bookmark | Global |
| `S` | Open strategy panel | Global |
| `D` | Open data manager | Global |
| `P` | Open prop firm config | Global |
| `A` | Open analytics report | Global |
| `C` | Open Monte Carlo view | Global |
| `E` | Export current report to HTML/CSV | Global |
| `Q` | Quit | Global |
| `?` | Show hotkey help overlay | Global |
| `Tab` | Cycle focus between panels | Global |
| `1`–`6` | Zoom chart to 1m/5m/15m/1h/4h/Daily | Chart panel focused |
| `Z+drag` | Zoom chart to selection (Phase 2) | Chart panel focused |
| `I` | Toggle indicator visibility | Chart panel focused |

### 13.2 UX Design Principles

- Everything keyboard-first. Mouse support is additive, not primary.
- Status bar always shows current state: bar index, total bars, speed, active firm profile, open position size, unrealized P&L.
- Color conventions: green = profit/long, red = loss/short, amber = warning/approaching limit, cyan = neutral highlight, white = current bar.
- No modal dialogs that block the chart. All config panels are sidebar overlays that slide in and out without interrupting playback.
- All numeric fields support vim-style increment: `+`/`-` or `j`/`k` to adjust by step.

---

## 14. Configuration & Persistence

### 14.1 Config File Structure

```toml
# ~/.config/backtest_tui/config.toml

[app]
default_data_dir = "~/data/futures"
default_strategy = "strategies/sma_cross.py"
hot_reload = true

[firm]
profile = "apex_50k"
enabled = true

[monte_carlo]
n_paths = 10000
method = "trade_shuffle"
confidence_interval = 0.95
seed = null  # null = random
```

### 14.2 Session Persistence

- Last-used dataset, strategy, and firm profile are remembered between sessions
- Bookmarks are serialized to a JSON sidecar file per dataset
- Trade log can be exported to CSV at any point during or after replay
- Analytics reports export to styled HTML (using Rich) or plain JSON

---

## 15. Non-Functional Requirements

| Category | Requirement | Metric |
|----------|-------------|--------|
| Performance | Full backtest on 500K bars | < 60 seconds on modern hardware |
| Performance | Monte Carlo 10,000 paths | < 5 seconds (vectorized numpy) |
| Performance | TUI frame rate during 1x replay | 60 fps (Textual default) |
| Performance | App startup time | < 2 seconds to interactive |
| Reliability | No crashes on malformed data | Graceful error display, never exit |
| Reliability | Rule violations must never be missed | 100% enforcement fidelity in test suite |
| Compatibility | Python versions | 3.10, 3.11, 3.12 |
| Compatibility | Operating systems | Linux, macOS, Windows (WSL2) |
| Compatibility | Terminal emulators | iTerm2, kitty, Alacritty, Windows Terminal |
| Usability | First-run experience | Demo dataset + example strategy bundled; runs out of the box |
| Extensibility | Custom prop firm profiles | Add new TOML file, zero code changes |
| Extensibility | Custom strategies | Any valid Backtrader Strategy subclass |
| Extensibility | Custom indicators | Any valid Backtrader Indicator subclass |
| Testing | Unit test coverage | > 80% for rules engine and analytics |
| Testing | Integration tests | Full replay test on reference dataset with known expected output |

---

## 16. Development Phases & Milestones

| Phase | Scope | Key Deliverables |
|-------|-------|-----------------|
| Phase 1 — Core | Backtrader bridge, CSV loader, basic chart widget, trade log, static stats panel, keyboard controls | Runnable TUI with bar replay on CSV data. No prop rules. No Monte Carlo. |
| Phase 2 — Prop Rules | Prop firm rules engine, all rule types, 6 pre-built profiles, warning/breach UI, prop analytics | Full rule enforcement with Apex, FTMO, TopstepTrader profiles. |
| Phase 3 — Monte Carlo | All 5 simulation methods, fan chart, MC summary stats, MC + prop firm integration | 10,000-path simulation with pass rate output. |
| Phase 4 — Full Analytics | All quantitative metrics, MAE/MFE analysis, statistical validity, PSR, DSR, R-multiple distribution | Complete analytics report, exportable. |
| Phase 5 — Advanced | Hot-reload, tick replay, multi-strategy comparison, live data feeds, Rithmic/IB integration | Production-grade feature set. |

---

## 17. Appendix — Metric Definitions

### Sharpe Ratio

`(Rp - Rf) / σp × √252`

Where `Rp` is the mean daily portfolio return, `Rf` is the daily risk-free rate (typically 0 for futures), and `σp` is the standard deviation of daily portfolio returns. Annualized by multiplying by √252.

### Sortino Ratio

`(Rp - Rf) / σd × √252`

Where `σd` is the downside deviation — the standard deviation of only negative daily returns. Penalizes downside volatility exclusively, which is more appropriate for asymmetric return distributions.

### Probabilistic Sharpe Ratio (PSR)

```
PSR(SR*) = Φ( (SR_hat - SR*) × √(T-1) / √(1 - skew×SR_hat + (kurtosis-1)/4 × SR_hat²) )
```

Where `SR_hat` is the observed Sharpe, `SR*` is the benchmark Sharpe (typically 0), `T` is the number of return observations, and `Φ` is the normal CDF. PSR quantifies confidence in the observed Sharpe given sample size, skewness, and kurtosis.

### Deflated Sharpe Ratio (DSR)

Applies a multiple-testing correction to PSR when the strategy is one of K strategies tested. Accounts for the increased probability of observing a high Sharpe by chance when many strategies are evaluated. Introduced by Bailey & Lopez de Prado (2014).

### Trailing Drawdown (Prop Firm)

The trailing drawdown floor is calculated as: `floor = max_equity_ever_reached - drawdown_threshold`. When account equity exceeds its previous maximum, the floor rises with it. The floor never moves down. A breach occurs when `current_equity < floor`. Note that most prop firms trail from the initial balance high — unrealized gains may or may not move the trail depending on the firm.

### Expectancy

`E = (Win Rate × Average Win) - (Loss Rate × Average Loss)`

Expectancy is the average dollar amount expected per trade over a large sample. It is the single most important metric for evaluating edge. A strategy with a 30% win rate and 3:1 average reward-to-risk has expectancy of `0.3×3 - 0.7×1 = +0.20` per dollar risked.

### R-Multiple

Each trade's P&L expressed in units of the initial risk taken (1R = the dollar amount risked on the trade). A trade that risked $200 and made $600 is a +3R trade. A trade that risked $200 and lost $200 is a -1R trade. The distribution of R-multiples removes position-size variation and reveals the underlying edge in risk-adjusted terms.

### MAE / MFE / ETD

**MAE (Max Adverse Excursion):** The largest intrabar move against a position before it was closed. Used to validate whether stops are placed appropriately — if MAE consistently exceeds the stop, fills are slipping. If MAE is much smaller than the stop, the stop may be too wide.

**MFE (Max Favorable Excursion):** The largest intrabar move in favor of a position before it was closed. Comparing MFE to actual exit P&L reveals whether exits are premature.

**ETD (Edge-to-Trade Draw):** `MFE - Actual P&L`. The average ETD across all trades quantifies how much potential profit the exit logic is giving back. High ETD suggests the exit is the weak point of the strategy.

---

*Futures Backtest TUI — PRD v1.0 | Draft*

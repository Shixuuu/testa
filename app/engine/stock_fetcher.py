"""Stock data fetcher: yfinance for live/historical data, Polygon for EOD options history."""
from __future__ import annotations
import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date


@dataclass
class StockBar:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class OptionRow:
    strike: float
    expiry: str
    last_price: float
    bid: float
    ask: float
    volume: int
    open_interest: int
    implied_volatility: float
    in_the_money: bool


@dataclass
class OptionsSnapshot:
    ticker: str
    spot_price: float
    expiries: list[str]
    calls: list[OptionRow]
    puts: list[OptionRow]
    put_call_ratio: float
    selected_expiry: str


@dataclass
class CompanyProfile:
    ticker: str
    name: str
    sector: str
    industry: str
    description: str
    website: str
    country: str
    employees: int
    market_cap: float
    pe_ratio: float
    eps: float
    dividend_yield: float
    beta: float
    week52_high: float
    week52_low: float
    revenue_ttm: float
    net_income_ttm: float
    total_debt: float
    total_cash: float
    debt_to_equity: float
    roe: float
    current_price: float = 0.0
    institutional_holders: list[dict] = field(default_factory=list)
    major_holders: list[str] = field(default_factory=list)


def get_polygon_api_key() -> str:
    key = os.environ.get("POLYGON_API_KEY", "")
    if key:
        return key
    cfg = os.path.expanduser("~/.config/backtest_tui/config.toml")
    if os.path.exists(cfg):
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore
            except ImportError:
                return ""
        with open(cfg, "rb") as f:
            data = tomllib.load(f)
        return data.get("data", {}).get("polygon_api_key", "")
    return ""


# ── Stock history ──────────────────────────────────────────────────────────────

async def fetch_stock_history(
    ticker: str, period: str = "3mo", interval: str = "1d"
) -> list[StockBar]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_fetch_history, ticker, period, interval)


def _sync_fetch_history(ticker: str, period: str, interval: str = "1d") -> list[StockBar]:
    try:
        import yfinance as yf  # type: ignore
        df = yf.Ticker(ticker).history(period=period, interval=interval)
        is_intraday = interval not in ("1d", "5d", "1wk", "1mo", "3mo")
        bars = []
        for ts, row in df.iterrows():
            if is_intraday:
                # Show HH:MM for intraday; strip seconds/tz
                try:
                    ts_label = ts.strftime("%m-%d %H:%M")
                except Exception:
                    ts_label = str(ts)
            else:
                try:
                    ts_label = str(ts.date())
                except Exception:
                    ts_label = str(ts)[:10]
            bars.append(StockBar(
                timestamp=ts_label,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row.get("Volume", 0) or 0),
            ))
        return bars
    except Exception:
        return []


# ── Company profile ────────────────────────────────────────────────────────────

async def fetch_company_profile(ticker: str) -> CompanyProfile:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_fetch_company, ticker)


def _sync_fetch_company(ticker: str) -> CompanyProfile:
    try:
        import yfinance as yf  # type: ignore
        t = yf.Ticker(ticker)
        info = t.info or {}

        inst_holders: list[dict] = []
        try:
            ih = t.institutional_holders
            if ih is not None and not ih.empty:
                for _, row in ih.head(10).iterrows():
                    inst_holders.append({
                        "holder": str(row.get("Holder", "")),
                        "shares": int(row.get("Shares", 0) or 0),
                        "pct": float(row.get("% Out", 0) or 0),
                        "value": float(row.get("Value", 0) or 0),
                    })
        except Exception:
            pass

        major_holders: list[str] = []
        try:
            mh = t.major_holders
            if mh is not None and not mh.empty:
                for _, row in mh.iterrows():
                    major_holders.append(f"{str(row.iloc[0]):>8}  {row.iloc[1]}")
        except Exception:
            pass

        spot = float(
            info.get("regularMarketPrice") or info.get("currentPrice") or
            info.get("previousClose") or 0
        )

        return CompanyProfile(
            ticker=ticker.upper(),
            name=info.get("longName") or info.get("shortName") or ticker.upper(),
            sector=info.get("sector") or "N/A",
            industry=info.get("industry") or "N/A",
            description=info.get("longBusinessSummary") or "No description available.",
            website=info.get("website") or "",
            country=info.get("country") or "N/A",
            employees=int(info.get("fullTimeEmployees") or 0),
            market_cap=float(info.get("marketCap") or 0),
            pe_ratio=float(info.get("trailingPE") or 0),
            eps=float(info.get("trailingEps") or 0),
            dividend_yield=float(info.get("dividendYield") or 0) * 100,
            beta=float(info.get("beta") or 0),
            week52_high=float(info.get("fiftyTwoWeekHigh") or 0),
            week52_low=float(info.get("fiftyTwoWeekLow") or 0),
            revenue_ttm=float(info.get("totalRevenue") or 0),
            net_income_ttm=float(info.get("netIncomeToCommon") or 0),
            total_debt=float(info.get("totalDebt") or 0),
            total_cash=float(info.get("totalCash") or 0),
            debt_to_equity=float(info.get("debtToEquity") or 0),
            roe=float(info.get("returnOnEquity") or 0) * 100,
            current_price=spot,
            institutional_holders=inst_holders,
            major_holders=major_holders,
        )
    except Exception as exc:
        return CompanyProfile(
            ticker=ticker.upper(), name=ticker.upper(),
            sector="N/A", industry="N/A",
            description=f"Error fetching data: {exc}",
            website="", country="N/A",
            employees=0, market_cap=0, pe_ratio=0, eps=0,
            dividend_yield=0, beta=0, week52_high=0, week52_low=0,
            revenue_ttm=0, net_income_ttm=0, total_debt=0, total_cash=0,
            debt_to_equity=0, roe=0,
        )


# ── Options chain ──────────────────────────────────────────────────────────────

async def fetch_options_snapshot(ticker: str, expiry_index: int = 0) -> OptionsSnapshot:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_fetch_options, ticker, expiry_index)


def _sync_fetch_options(ticker: str, expiry_index: int) -> OptionsSnapshot:
    import math as _math

    def _f(val) -> float:
        try:
            v = float(val)
            return 0.0 if _math.isnan(v) or _math.isinf(v) else v
        except (TypeError, ValueError):
            return 0.0

    def _i(val) -> int:
        return int(_f(val))

    empty = OptionsSnapshot(
        ticker=ticker.upper(), spot_price=0.0,
        expiries=[], calls=[], puts=[],
        put_call_ratio=0.0, selected_expiry="",
    )
    try:
        import yfinance as yf  # type: ignore
        t = yf.Ticker(ticker)
        info = t.info or {}
        spot = _f(
            info.get("regularMarketPrice") or info.get("currentPrice") or
            info.get("previousClose") or 0
        )
        expiries = list(t.options or [])
        if not expiries:
            return empty

        idx = min(expiry_index, len(expiries) - 1)
        chain = t.option_chain(expiries[idx])

        def parse_df(df, expiry: str) -> list[OptionRow]:
            rows: list[OptionRow] = []
            for _, r in df.iterrows():
                try:
                    rows.append(OptionRow(
                        strike=_f(r.get("strike")),
                        expiry=expiry,
                        last_price=_f(r.get("lastPrice")),
                        bid=_f(r.get("bid")),
                        ask=_f(r.get("ask")),
                        volume=_i(r.get("volume")),
                        open_interest=_i(r.get("openInterest")),
                        implied_volatility=_f(r.get("impliedVolatility")),
                        in_the_money=bool(r.get("inTheMoney", False)),
                    ))
                except Exception:
                    pass  # skip malformed row
            return rows

        calls = parse_df(chain.calls, expiries[idx])
        puts = parse_df(chain.puts, expiries[idx])
        call_vol = sum(r.volume for r in calls)
        put_vol = sum(r.volume for r in puts)

        return OptionsSnapshot(
            ticker=ticker.upper(),
            spot_price=spot,
            expiries=expiries,
            calls=calls,
            puts=puts,
            put_call_ratio=put_vol / max(call_vol, 1),
            selected_expiry=expiries[idx],
        )
    except Exception:
        return empty


# ── Polygon historical options ─────────────────────────────────────────────────

async def fetch_polygon_options_history(
    ticker: str, api_key: str, days_back: int = 30
) -> list[dict]:
    if not api_key:
        return []
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_polygon_options, ticker, api_key, days_back)


def _sync_polygon_options(ticker: str, api_key: str, days_back: int) -> list[dict]:
    try:
        import urllib.request
        import json

        to_dt = date.today()
        from_dt = to_dt - timedelta(days=days_back)

        url = (
            f"https://api.polygon.io/v3/reference/options/contracts"
            f"?underlying_ticker={ticker.upper()}&limit=10&sort=open_interest"
            f"&apiKey={api_key}"
        )
        with urllib.request.urlopen(url, timeout=10) as r:
            contracts = json.loads(r.read())

        results = contracts.get("results", [])
        if not results:
            return []

        contract_ticker = results[0].get("ticker", "")
        if not contract_ticker:
            return []

        agg_url = (
            f"https://api.polygon.io/v2/aggs/ticker/{contract_ticker}/range/1/day"
            f"/{from_dt}/{to_dt}?adjusted=true&sort=asc&limit=50&apiKey={api_key}"
        )
        with urllib.request.urlopen(agg_url, timeout=10) as r:
            agg_data = json.loads(r.read())

        history = []
        for bar in agg_data.get("results", []):
            ts = datetime.fromtimestamp(bar["t"] / 1000).strftime("%Y-%m-%d")
            history.append({
                "date": ts,
                "open": bar.get("o", 0),
                "high": bar.get("h", 0),
                "low": bar.get("l", 0),
                "close": bar.get("c", 0),
                "volume": bar.get("v", 0),
                "vwap": bar.get("vw", 0),
                "contract": contract_ticker,
            })
        return history
    except Exception:
        return []


# ── AI context serialiser ──────────────────────────────────────────────────────

def format_stock_for_ai(
    profile: CompanyProfile,
    options: OptionsSnapshot | None,
    poly_history: list[dict],
    supply_chain_report: str = "",
    company_report: str = "",
) -> str:
    lines = [f"=== STOCK ANALYSIS: {profile.ticker} — {profile.name} ==="]
    lines += [
        f"Sector        : {profile.sector}",
        f"Industry      : {profile.industry}",
        f"Country       : {profile.country}",
        f"Employees     : {profile.employees:,}",
        f"Current Price : ${profile.current_price:.2f}",
        f"Market Cap    : ${profile.market_cap:,.0f}",
        f"P/E Ratio     : {profile.pe_ratio:.2f}",
        f"EPS           : ${profile.eps:.2f}",
        f"Beta          : {profile.beta:.2f}",
        f"52W Range     : ${profile.week52_low:.2f} – ${profile.week52_high:.2f}",
        f"Div Yield     : {profile.dividend_yield:.2f}%",
        f"Revenue TTM   : ${profile.revenue_ttm:,.0f}",
        f"Net Income    : ${profile.net_income_ttm:,.0f}",
        f"Total Debt    : ${profile.total_debt:,.0f}",
        f"Total Cash    : ${profile.total_cash:,.0f}",
        f"Debt/Equity   : {profile.debt_to_equity:.2f}",
        f"ROE           : {profile.roe:.2f}%",
        f"Website       : {profile.website}",
    ]

    if profile.major_holders:
        lines.append("\n--- MAJOR HOLDERS ---")
        for h in profile.major_holders[:6]:
            lines.append(f"  {h}")

    if profile.institutional_holders:
        lines.append("\n--- TOP INSTITUTIONAL HOLDERS ---")
        for h in profile.institutional_holders[:8]:
            lines.append(
                f"  {h['holder']:<35} {h['shares']:>12,} shares  "
                f"{h['pct']*100:.2f}%  ${h['value']:,.0f}"
            )

    if options:
        lines += [
            "\n--- OPTIONS SNAPSHOT ---",
            f"Spot Price    : ${options.spot_price:.2f}",
            f"Expiry        : {options.selected_expiry}",
            f"Put/Call Ratio: {options.put_call_ratio:.3f}",
            f"Total Call Vol: {sum(r.volume for r in options.calls):,}",
            f"Total Put  Vol: {sum(r.volume for r in options.puts):,}",
            f"Total Call OI : {sum(r.open_interest for r in options.calls):,}",
            f"Total Put  OI : {sum(r.open_interest for r in options.puts):,}",
        ]
        # Show strikes near ATM
        spot = options.spot_price
        atm_calls = sorted(options.calls, key=lambda r: abs(r.strike - spot))[:5]
        if atm_calls:
            lines.append("  ATM Calls (nearest 5):")
            for r in sorted(atm_calls, key=lambda x: x.strike):
                lines.append(
                    f"    Strike={r.strike}  IV={r.implied_volatility*100:.1f}%"
                    f"  Vol={r.volume:,}  OI={r.open_interest:,}"
                )
        atm_puts = sorted(options.puts, key=lambda r: abs(r.strike - spot))[:5]
        if atm_puts:
            lines.append("  ATM Puts (nearest 5):")
            for r in sorted(atm_puts, key=lambda x: x.strike):
                lines.append(
                    f"    Strike={r.strike}  IV={r.implied_volatility*100:.1f}%"
                    f"  Vol={r.volume:,}  OI={r.open_interest:,}"
                )

    if poly_history:
        lines.append(f"\n--- POLYGON OPTIONS TREND ({len(poly_history)} days) ---")
        lines.append(f"  Contract: {poly_history[0].get('contract', 'N/A')}")
        lines.append(f"  Date range: {poly_history[0]['date']} → {poly_history[-1]['date']}")
        vols = [b["volume"] for b in poly_history]
        lines.append(
            f"  Avg daily vol: {sum(vols)/max(len(vols),1):,.0f}  "
            f"Max: {max(vols):,.0f}  Min: {min(vols):,.0f}"
        )

    if supply_chain_report:
        lines += ["\n--- SUPPLY CHAIN ---", supply_chain_report]

    if company_report:
        lines += ["\n--- AI COMPANY REPORT ---", company_report]

    lines.append("\n" + "=" * 52)
    return "\n".join(lines)

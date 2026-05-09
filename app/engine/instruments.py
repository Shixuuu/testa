"""Futures instrument definitions and commission schemes."""
from dataclasses import dataclass, field
from typing import Optional
import backtrader as bt


@dataclass
class InstrumentSpec:
    symbol: str
    exchange: str
    point_value: float
    tick_size: float
    default_margin: float
    commission_rt: float = 4.00  # round-trip commission USD
    exchange_fee: float = 1.18
    nfa_fee: float = 0.02

    @property
    def tick_value(self) -> float:
        return self.tick_size * self.point_value


INSTRUMENTS: dict[str, InstrumentSpec] = {
    "ES": InstrumentSpec("ES", "CME", 50.0, 0.25, 12500.0, 4.00),
    "NQ": InstrumentSpec("NQ", "CME", 20.0, 0.25, 16500.0, 4.00),
    "CL": InstrumentSpec("CL", "NYMEX", 1000.0, 0.01, 6000.0, 4.00),
    "GC": InstrumentSpec("GC", "COMEX", 100.0, 0.10, 9500.0, 4.00),
    "6E": InstrumentSpec("6E", "CME", 125000.0, 0.00005, 2800.0, 4.00),
    "MES": InstrumentSpec("MES", "CME", 5.0, 0.25, 1250.0, 0.62),
    "MNQ": InstrumentSpec("MNQ", "CME", 2.0, 0.25, 1650.0, 0.62),
}


class FuturesCommission(bt.CommInfoBase):
    """Commission scheme for futures: flat per-contract round-trip."""

    params = (
        ("commission", 4.00),
        ("stocklike", False),
        ("commtype", bt.CommInfoBase.COMM_FIXED),
        ("point_value", 50.0),
    )

    def getsize(self, price, cash):
        return self.p.stocklike and cash // price or cash // self.p.point_value

    def getcommission(self, size, price):
        return abs(size) * self.p.commission / 2  # half RT per fill

    def getvaluesize(self, size, price):
        return abs(size) * price * self.p.point_value


def make_commission(spec: InstrumentSpec) -> FuturesCommission:
    return FuturesCommission(
        commission=spec.commission_rt,
        point_value=spec.point_value,
    )


def get_instrument(symbol: str, custom: Optional[InstrumentSpec] = None) -> InstrumentSpec:
    if custom:
        return custom
    sym = symbol.upper()
    if sym in INSTRUMENTS:
        return INSTRUMENTS[sym]
    return InstrumentSpec(sym, "CUSTOM", 1.0, 0.01, 0.0)

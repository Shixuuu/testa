"""
Futures commission scheme for Backtrader.
Supports ES, NQ, CL, GC, 6E, MES, MNQ.
"""
from __future__ import annotations
from typing import Dict, NamedTuple
import backtrader as bt


class InstrumentSpec(NamedTuple):
    point_value: float      # $ per point
    tick_size: float        # minimum price increment
    tick_value: float       # $ per tick
    margin: float           # initial margin per contract ($)
    rt_commission: float    # round-trip commission ($)


INSTRUMENT_SPECS: Dict[str, InstrumentSpec] = {
    "ES": InstrumentSpec(
        point_value=50.0,
        tick_size=0.25,
        tick_value=12.50,
        margin=14500.0,
        rt_commission=4.10,
    ),
    "NQ": InstrumentSpec(
        point_value=20.0,
        tick_size=0.25,
        tick_value=5.00,
        margin=21000.0,
        rt_commission=4.10,
    ),
    "CL": InstrumentSpec(
        point_value=1000.0,
        tick_size=0.01,
        tick_value=10.00,
        margin=6500.0,
        rt_commission=4.10,
    ),
    "GC": InstrumentSpec(
        point_value=100.0,
        tick_size=0.10,
        tick_value=10.00,
        margin=8500.0,
        rt_commission=4.10,
    ),
    "6E": InstrumentSpec(
        point_value=125000.0,
        tick_size=0.0001,
        tick_value=12.50,
        margin=2500.0,
        rt_commission=4.10,
    ),
    "MES": InstrumentSpec(
        point_value=5.0,
        tick_size=0.25,
        tick_value=1.25,
        margin=1450.0,
        rt_commission=0.62,
    ),
    "MNQ": InstrumentSpec(
        point_value=2.0,
        tick_size=0.25,
        tick_value=0.50,
        margin=2100.0,
        rt_commission=0.62,
    ),
}


class FuturesCommissionScheme(bt.CommInfoBase):
    """
    Commission scheme for futures contracts.
    Charges a flat round-trip commission per contract.
    """

    params = (
        ("instrument", "ES"),
        ("commission", None),  # override RT commission if desired
        ("stocklike", False),
        ("commtype", bt.CommInfoBase.COMM_FIXED),
    )

    def __init__(self) -> None:
        super().__init__()
        instrument = self.params.instrument.upper()
        if instrument not in INSTRUMENT_SPECS:
            raise ValueError(
                f"Unknown instrument '{instrument}'. "
                f"Available: {list(INSTRUMENT_SPECS.keys())}"
            )
        self._spec = INSTRUMENT_SPECS[instrument]
        self._rt_comm = (
            self.params.commission
            if self.params.commission is not None
            else self._spec.rt_commission
        )

    def getcommission(self, size: float, price: float) -> float:
        """Return half round-trip commission per trade leg."""
        return abs(size) * (self._rt_comm / 2.0)

    def getsize(self, price: float, cash: float) -> float:
        """Return max contracts for given cash (based on margin)."""
        return int(cash / self._spec.margin)

    def getvalue(self, size: float, price: float) -> float:
        """Return notional value of position."""
        return abs(size) * price * self._spec.point_value

    @property
    def spec(self) -> InstrumentSpec:
        return self._spec

    @property
    def point_value(self) -> float:
        return self._spec.point_value

    @property
    def tick_size(self) -> float:
        return self._spec.tick_size

    @property
    def tick_value(self) -> float:
        return self._spec.tick_value

    @property
    def margin(self) -> float:
        return self._spec.margin


def get_commission_scheme(instrument: str, **kwargs) -> FuturesCommissionScheme:
    """Factory function to create a commission scheme for an instrument."""
    return FuturesCommissionScheme(instrument=instrument.upper(), **kwargs)

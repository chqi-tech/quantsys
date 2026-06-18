"""Event types that flow through the engine.

The loop is: MarketEvent -> Strategy -> SignalEvent -> Portfolio -> OrderEvent
-> ExecutionHandler -> FillEvent -> Portfolio. Same event vocabulary will be
reused in paper/live: only the producer of MarketEvents (live feed) and the
consumer of OrderEvents (broker) change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class MarketEvent:
    """A new bar is available for `dt`. Producer: DataHandler."""

    dt: datetime


@dataclass
class SignalEvent:
    """A strategy's desired exposure to one symbol, as a target weight in [0, 1].

    target_weight = 0.0 means "exit". The Portfolio turns target weights into
    orders. Carrying a weight (not BUY/SELL) keeps strategy code identical
    across backtest/paper/live and makes rebalancing trivial.
    """

    dt: datetime
    symbol: str
    target_weight: float


@dataclass
class OrderEvent:
    """An instruction to trade `quantity` shares (signed: + buy, - sell).

    Orders are queued and filled at the NEXT bar's open (see ExecutionHandler).
    """

    dt: datetime
    symbol: str
    quantity: int

    @property
    def direction(self) -> int:
        return 1 if self.quantity >= 0 else -1


@dataclass
class FillEvent:
    """A completed trade. Producer: ExecutionHandler."""

    dt: datetime
    symbol: str
    quantity: int          # signed
    fill_price: float      # includes slippage
    commission: float

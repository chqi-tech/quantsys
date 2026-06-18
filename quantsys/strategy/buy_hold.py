"""Buy & hold a single symbol (default SPY).

Two jobs: (1) bring the engine up end-to-end with the simplest possible strategy,
and (2) serve as the reconciliation oracle — a correct engine's buy&hold result
must match an independent total-return calculation (see tests + report).
"""

from __future__ import annotations

from ..core.events import SignalEvent
from .base import Strategy


class BuyHoldStrategy(Strategy):
    def __init__(self, data_handler, symbol: str = "SPY"):
        super().__init__(data_handler)
        self.symbol = symbol
        self._entered = False

    def calculate_signals(self) -> list[SignalEvent]:
        # Enter once, on the first bar the symbol actually trades.
        if self._entered:
            return []
        if not self.dh.has_bar_today(self.symbol):
            return []
        self._entered = True
        return [SignalEvent(self.dh.current_dt, self.symbol, target_weight=1.0)]

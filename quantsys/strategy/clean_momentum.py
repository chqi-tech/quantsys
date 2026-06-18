"""CleanMomentum — port of the user's QuantConnect strategy to a FIXED universe.

Faithful to the QC original (reference-clean-momentum-qc.py):
  - 12-1 cross-sectional momentum: return from `lookback` ago to `skip` ago
  - risk-adjusted score = momentum / annualized vol
  - hold the top_n names
  - volatility targeting: scale gross exposure to hit `target_vol`
  - monthly rebalance

The ONE thing intentionally replaced: QC's dynamic `coarse_selection` (top-100 by
dollar volume, point-in-time) becomes a fixed `universe` list. That dynamic,
survivorship-bias-free universe is the hard part to reproduce on free data and is
deferred to phase 1.5 (see the design doc). Results here carry survivorship bias.
"""

from __future__ import annotations

from ..core.events import SignalEvent
from .base import Strategy
from .momentum_logic import momentum_target_weights


class CleanMomentumStrategy(Strategy):
    def __init__(
        self,
        data_handler,
        universe: list[str],
        lookback: int = 252,
        skip: int = 21,
        top_n: int = 10,
        target_vol: float = 0.15,
        vol_window: int = 60,
    ):
        super().__init__(data_handler)
        self.universe = [s for s in universe]
        self.lookback = lookback
        self.skip = skip
        self.top_n = top_n
        self.target_vol = target_vol
        self.vol_window = vol_window
        self._last_month: tuple[int, int] | None = None
        self._held: set[str] = set()

    def _is_rebalance_day(self) -> bool:
        dt = self.dh.current_dt
        ym = (dt.year, dt.month)
        if ym != self._last_month:
            self._last_month = ym
            return True
        return False

    def _closes(self) -> dict[str, "object"]:
        """Collect each symbol's lookback window of closes from the DataHandler."""
        out = {}
        for s in self.universe:
            bars = self.dh.get_latest_bars(s, self.lookback)
            if len(bars) >= self.lookback:
                out[s] = bars["close"]
        return out

    def calculate_signals(self) -> list[SignalEvent]:
        if not self._is_rebalance_day():
            return []
        # Same brain as the live Alpaca rebalance: shared momentum_target_weights.
        targets = momentum_target_weights(
            self._closes(),
            lookback=self.lookback,
            skip=self.skip,
            top_n=self.top_n,
            target_vol=self.target_vol,
            vol_window=self.vol_window,
        )
        if not targets:
            return []
        dt = self.dh.current_dt
        winners = set(targets)

        signals: list[SignalEvent] = []
        for s in self._held - winners:            # exit names no longer winners
            signals.append(SignalEvent(dt, s, target_weight=0.0))
        for s, weight in targets.items():          # target the winners
            signals.append(SignalEvent(dt, s, target_weight=weight))

        self._held = winners
        return signals

"""DataHandler — replays cached bars one trading day at a time.

This is where look-ahead bias is prevented STRUCTURALLY: a strategy is only ever
handed this object, and `get_latest_bars` physically cannot return a row dated
after the current bar. There is no method to fetch the future. Swap this class
for a live feed in the paper/live phase; the Strategy code does not change.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime

import numpy as np
import pandas as pd

from .events import MarketEvent


class HistoricDataHandler:
    def __init__(self, data: dict[str, pd.DataFrame], events: deque):
        self.data = data
        self.events = events
        self.symbols = list(data.keys())
        # Master timeline = sorted union of every symbol's dates.
        all_dates = sorted(set().union(*[df.index for df in data.values()]))
        self.timeline: list[pd.Timestamp] = list(all_dates)
        self._i = -1
        # Precompute each symbol's index as int64 ns for fast searchsorted.
        self._idx_values = {s: df.index.values.astype("datetime64[ns]") for s, df in data.items()}

    # ---- timeline control -------------------------------------------------
    @property
    def current_dt(self) -> datetime | None:
        if 0 <= self._i < len(self.timeline):
            return self.timeline[self._i].to_pydatetime()
        return None

    def update_bars(self) -> bool:
        """Advance one day and emit a MarketEvent. False when the run is done."""
        self._i += 1
        if self._i >= len(self.timeline):
            return False
        self.events.append(MarketEvent(self.current_dt))
        return True

    # ---- safe accessors (current + past only) -----------------------------
    def _pos(self, symbol: str) -> int:
        """Index position of the latest bar at/<= current_dt, or -1 if none yet."""
        cur = np.datetime64(self.timeline[self._i])
        return int(self._idx_values[symbol].searchsorted(cur, side="right")) - 1

    def get_latest_bars(self, symbol: str, n: int = 1) -> pd.DataFrame:
        """Last `n` bars up to and INCLUDING the current bar. Never the future."""
        if symbol not in self.data:
            return pd.DataFrame()
        pos = self._pos(symbol)
        if pos < 0:
            return pd.DataFrame()
        lo = max(0, pos - n + 1)
        return self.data[symbol].iloc[lo : pos + 1]

    def get_latest_value(self, symbol: str, field: str = "close"):
        bars = self.get_latest_bars(symbol, 1)
        if bars.empty:
            return None
        return float(bars.iloc[-1][field])

    def has_bar_today(self, symbol: str) -> bool:
        """True if this symbol trades on the current date (not just a past date)."""
        if symbol not in self.data:
            return False
        pos = self._pos(symbol)
        if pos < 0:
            return False
        return self.data[symbol].index[pos] == self.timeline[self._i]

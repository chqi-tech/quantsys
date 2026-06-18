"""The headline guardrails: no look-ahead, fills at next-bar-open."""

from collections import deque

import numpy as np
import pandas as pd
import pytest

from quantsys.core.data_handler import HistoricDataHandler
from quantsys.core.engine import BacktestEngine
from quantsys.core.events import SignalEvent
from quantsys.strategy.base import Strategy


def make_data(symbol, closes, opens=None):
    idx = pd.bdate_range("2020-01-01", periods=len(closes))
    closes = np.array(closes, dtype=float)
    opens = np.array(opens, dtype=float) if opens is not None else closes.copy()
    df = pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, closes),
            "low": np.minimum(opens, closes),
            "close": closes,
            "adj_close": closes,
            "volume": np.full(len(closes), 1_000_000),
        },
        index=idx,
    )
    return df


def test_get_latest_bars_never_returns_future():
    data = {
        "AAA": make_data("AAA", [10, 11, 12, 13, 14, 15]),
        "BBB": make_data("BBB", [20, 21, 22, 23, 24, 25]),
    }
    dh = HistoricDataHandler(data, deque())
    seen_dates = []
    while dh.update_bars():
        cur = pd.Timestamp(dh.current_dt)
        seen_dates.append(cur)
        for sym in data:
            bars = dh.get_latest_bars(sym, 1000)
            assert bars.index.max() <= cur, "leaked a future bar!"
    # advanced through every date exactly once
    assert len(seen_dates) == 6


def test_cheating_strategy_cannot_reach_the_future():
    """A strategy only has the DataHandler; there is no future accessor at all."""
    data = {"AAA": make_data("AAA", list(range(10, 30)))}
    dh = HistoricDataHandler(data, deque())
    dh.update_bars()  # land on bar 0
    # No method exposes future bars.
    assert not hasattr(dh, "get_future_bars")
    # And the only accessor caps at the current bar.
    bars = dh.get_latest_bars("AAA", 1000)
    assert bars.index.max() == pd.Timestamp(dh.current_dt)
    assert len(bars) == 1  # only the current bar exists so far


class _OneShotBuy(Strategy):
    """Buys 100% on a specific date, then nothing."""

    def __init__(self, dh, buy_on):
        super().__init__(dh)
        self.buy_on = pd.Timestamp(buy_on)
        self.done = False

    def calculate_signals(self):
        if self.done:
            return []
        if pd.Timestamp(self.dh.current_dt) == self.buy_on:
            self.done = True
            return [SignalEvent(self.dh.current_dt, "AAA", 1.0)]
        return []


def test_fill_happens_at_next_bar_open():
    # distinct opens so we can tell which bar filled the order
    closes = [100, 100, 100, 100, 100]
    opens = [100, 101, 102, 103, 104]
    data = {"AAA": make_data("AAA", closes, opens)}
    dates = pd.bdate_range("2020-01-01", periods=5)
    buy_date = dates[1]  # signal on bar 1 (close=100)

    engine = BacktestEngine(
        data=data,
        strategy_factory=lambda dh: _OneShotBuy(dh, buy_date),
        initial_capital=100_000.0,
        slippage_bps=5.0,
        commission_bps=0.0,
        max_weight=1.0,
        benchmark_symbol="AAA",
    )
    engine.run()

    # signal on bar1 (close 100) -> shares = floor(100000/100) = 1000
    # filled at bar2 OPEN (102), NOT bar1 close(100) or bar1 open(101)
    expected_shares = 1000
    expected_fill = 102 * (1 + 5e-4)
    expected_cash = 100_000.0 - expected_shares * expected_fill
    assert engine.portfolio.positions.get("AAA") == expected_shares
    assert engine.portfolio.cash == pytest.approx(expected_cash, abs=0.01)

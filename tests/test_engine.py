"""Reconciliation: a buy&hold run must match an independent calculation exactly."""

import math
from collections import deque

import numpy as np
import pandas as pd
import pytest

from quantsys.core.engine import BacktestEngine
from quantsys.strategy.buy_hold import BuyHoldStrategy
from quantsys.report import metrics as M


def make_data(closes, opens):
    idx = pd.bdate_range("2020-01-01", periods=len(closes))
    closes = np.array(closes, dtype=float)
    opens = np.array(opens, dtype=float)
    return pd.DataFrame(
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


def test_buy_and_hold_reconciles_exactly():
    # open[t] = close[t-1] so the entry fills at the prior close (clean math)
    n = 30
    closes = list(100.0 * np.cumprod(1 + np.full(n, 0.001)))  # steady +0.1%/day
    opens = [closes[0]] + closes[:-1]
    data = {"SPY": make_data(closes, opens)}

    cap = 100_000.0
    slip = 5e-4
    engine = BacktestEngine(
        data=data,
        strategy_factory=lambda dh: BuyHoldStrategy(dh, "SPY"),
        initial_capital=cap,
        slippage_bps=5.0,
        commission_bps=0.0,
        max_weight=1.0,
        benchmark_symbol="SPY",
    )
    result = engine.run()

    # independent replication of the exact mechanics
    shares = math.floor(cap / closes[0])     # sized at bar0 close
    fill = opens[1] * (1 + slip)             # filled at bar1 OPEN
    cash = cap - shares * fill
    expected_final = cash + shares * closes[-1]

    final = result.equity["equity"].iloc[-1]
    assert final == pytest.approx(expected_final, abs=0.01)


def test_metrics_conventions():
    # 252 trading days of exactly +0.05%/day, no slippage, single entry
    n = 252
    closes = list(100.0 * np.cumprod(1 + np.full(n, 0.0005)))
    opens = [closes[0]] + closes[:-1]
    data = {"SPY": make_data(closes, opens)}

    engine = BacktestEngine(
        data=data,
        strategy_factory=lambda dh: BuyHoldStrategy(dh, "SPY"),
        initial_capital=100_000.0,
        slippage_bps=0.0,
        commission_bps=0.0,
        max_weight=1.0,
        benchmark_symbol="SPY",
    )
    result = engine.run()
    eq = result.equity["equity"]
    s = M.summarize(eq)
    # positive return, finite Sharpe, drawdown <= 0
    assert s["total_return"] > 0
    assert s["sharpe"] > 0
    assert s["max_drawdown"] <= 0

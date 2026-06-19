"""Absolute-momentum gate (D2): only positive-momentum names are held."""

import numpy as np
import pandas as pd

from quantsys.strategy.momentum_logic import momentum_target_weights


def _series(trend_per_day: float, phase: float = 0.0, n: int = 300) -> pd.Series:
    """Deterministic price path: exponential trend + small sine wiggle.

    The trend fixes the 12-1 momentum SIGN unambiguously; the wiggle gives a
    nonzero volatility (vol==0 names are skipped by the scorer). Phase varies
    the path per name without changing the sign.
    """
    t = np.arange(n)
    prices = 100.0 * np.exp(trend_per_day * t) * (1 + 0.02 * np.sin(0.3 * t + phase))
    return pd.Series(prices, index=pd.bdate_range("2023-01-01", periods=n))


def test_filter_drops_negative_momentum():
    closes = {
        "UP1": _series(0.0020, phase=0.0),
        "UP2": _series(0.0018, phase=1.0),
        "UP3": _series(0.0016, phase=2.0),
        "DN1": _series(-0.0020, phase=0.5),
        "DN2": _series(-0.0018, phase=1.5),
    }
    w = momentum_target_weights(closes, lookback=252, skip=21, top_n=10)
    assert set(w) == {"UP1", "UP2", "UP3"}      # only the up-trending names held
    assert "DN1" not in w and "DN2" not in w    # negative momentum → dropped


def test_all_negative_goes_to_cash():
    closes = {s: _series(-0.0020, phase=i) for i, s in enumerate(("A", "B", "C"))}
    w = momentum_target_weights(closes, lookback=252, skip=21, top_n=10)
    assert w == {}      # nothing positive → all cash


def test_bull_case_holds_all_positive():
    closes = {s: _series(0.0018, phase=i) for i, s in enumerate(("A", "B", "C"))}
    w = momentum_target_weights(closes, lookback=252, skip=21, top_n=10)
    assert set(w) == {"A", "B", "C"}            # all positive → all held
    assert 0 < sum(w.values()) <= 1.0 + 1e-9    # exposure capped at 1 (no leverage)

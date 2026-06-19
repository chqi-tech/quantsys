"""Pure momentum signal logic — the strategy's BRAIN, shared by two runtimes.

The backtest (event-driven engine, replaying history) and the live Alpaca paper
rebalance both call `momentum_target_weights()`. So the alpha logic is literally
the same code in both places; only the execution differs (engine fills vs broker
orders). This is the honest version of "same strategy code, backtest → live".

Input `closes`: {symbol: chronological close-price Series (latest last)}.
Output: {symbol: target_weight} for the winners (others implicitly 0).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def momentum_scores(closes: dict[str, pd.Series], lookback: int = 252, skip: int = 21) -> dict[str, float]:
    """12-1 risk-adjusted momentum: return(lookback→skip ago) / annualized vol."""
    scores: dict[str, float] = {}
    for s, series in closes.items():
        prices = series.dropna().tail(lookback)
        if len(prices) < lookback:
            continue
        end = -skip if skip > 0 else -1
        mom = prices.iloc[end] / prices.iloc[0] - 1.0
        rets = prices.pct_change().dropna()
        vol = rets.std() * np.sqrt(252)
        if vol == 0 or np.isnan(vol):
            continue
        scores[s] = mom / vol
    return scores


def target_exposure(
    closes: dict[str, pd.Series], winners: list[str], target_vol: float = 0.15, vol_window: int = 60
) -> float:
    """Scale gross exposure so the equal-weight basket's recent vol ≈ target_vol."""
    recent = pd.DataFrame({s: closes[s].tail(vol_window + 1) for s in winners})
    port_ret = recent.pct_change().dropna().mean(axis=1)
    port_vol = port_ret.std() * np.sqrt(252)
    if port_vol and port_vol > 0:
        return float(min(1.0, target_vol / port_vol))
    return 1.0


def momentum_target_weights(
    closes: dict[str, pd.Series],
    lookback: int = 252,
    skip: int = 21,
    top_n: int = 10,
    target_vol: float = 0.15,
    vol_window: int = 60,
) -> dict[str, float]:
    """Full pipeline: score → pick top_n → vol-target → equal-weight the winners."""
    scores = momentum_scores(closes, lookback, skip)
    if not scores:
        return {}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    # Absolute-momentum gate (D2): only hold names with positive momentum.
    # score = mom / vol and vol > 0, so score > 0 is exactly mom > 0. Names that
    # fail the gate are dropped → held as cash. In a downturn this can hold fewer
    # than top_n (or nothing), de-risking automatically.
    winners = [s for s, sc in ranked[:top_n] if sc > 0]
    if not winners:
        return {}  # nothing has positive momentum → all cash
    exposure = target_exposure(closes, winners, target_vol, vol_window)
    weight = exposure / len(winners)
    return {s: weight for s in winners}

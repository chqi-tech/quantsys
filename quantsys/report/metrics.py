"""Performance metrics with pinned conventions (per design Success Criteria).

Conventions, so two people get the same numbers:
  - Sharpe:  risk-free rate = 0, annualization factor = 252
  - CAGR:    geometric, over the calendar span
  - Max DD:  peak-to-trough on the equity curve
  - Yearly:  geometric return per calendar year (first/last may be partial)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def daily_returns(equity: pd.Series) -> pd.Series:
    return equity.pct_change().dropna()


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    if years <= 0:
        return 0.0
    return (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1


def sharpe(equity: pd.Series, rf: float = 0.0) -> float:
    r = daily_returns(equity)
    if r.std() == 0 or len(r) < 2:
        return 0.0
    excess = r - rf / TRADING_DAYS
    return float(excess.mean() / r.std() * np.sqrt(TRADING_DAYS))


def annual_vol(equity: pd.Series) -> float:
    r = daily_returns(equity)
    return float(r.std() * np.sqrt(TRADING_DAYS)) if len(r) > 1 else 0.0


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def drawdown_series(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1.0


def total_return(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    return float(equity.iloc[-1] / equity.iloc[0] - 1)


def yearly_returns(equity: pd.Series) -> pd.Series:
    """Geometric return per calendar year (first/last may be partial)."""
    year_end = equity.groupby(equity.index.year).last()
    starts = equity.groupby(equity.index.year).first()
    out = {}
    prev = None
    for yr in year_end.index:
        base = prev if prev is not None else starts.loc[yr]
        out[yr] = year_end.loc[yr] / base - 1.0
        prev = year_end.loc[yr]
    return pd.Series(out)


def summarize(equity: pd.Series) -> dict:
    return {
        "start": equity.index[0].date().isoformat(),
        "end": equity.index[-1].date().isoformat(),
        "initial": float(equity.iloc[0]),
        "final": float(equity.iloc[-1]),
        "total_return": total_return(equity),
        "cagr": cagr(equity),
        "sharpe": sharpe(equity),
        "annual_vol": annual_vol(equity),
        "max_drawdown": max_drawdown(equity),
    }

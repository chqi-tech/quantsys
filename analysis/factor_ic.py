"""IC analysis of OUR 12-1 risk-adjusted momentum factor, via Alphalens.

This does NOT build a strategy or trade. It takes the SAME factor the live/
backtest brain uses (`momentum_scores` = mom/vol) and asks one question:
**does ranking stocks by this factor actually sort future winners from losers?**

Pipeline:
  Tiingo daily closes (cached) -> compute the factor on each month-end ->
  Alphalens get_clean_factor_and_forward_returns -> IC + quantile returns ->
  save 4 PNG charts + a text summary to analysis/factor_report/.

Run:  uv run --with alphalens-reloaded --with matplotlib --with scipy \
          python analysis/factor_ic.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: save PNGs, never pop a window
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quantsys.data.provider import TiingoProvider  # noqa: E402
from quantsys.run import _load_dotenv  # noqa: E402
from quantsys.strategy.momentum_logic import momentum_scores  # noqa: E402

import alphalens as al  # noqa: E402

OUT = ROOT / "analysis" / "factor_report"
OUT.mkdir(parents=True, exist_ok=True)

START, END = "2010-01-01", "2025-12-31"
LOOKBACK, SKIP = 252, 21
PERIODS = (1, 5, 21)  # forward-return horizons in trading days
QUANTILES = 5

# ~45 liquid large caps with long history, spread across sectors so the
# momentum factor has real cross-sectional dispersion to rank.
# NOTE: this is a curated survivor list (teaching demo) -> mild survivorship
# bias. Fine for showing IC mechanics; not a clean research universe.
UNIVERSE = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "ORCL", "CSCO", "INTC",
    "ADBE", "CRM", "IBM", "QCOM", "TXN", "NFLX",
    "JPM", "BAC", "WFC", "GS", "V", "MA",
    "JNJ", "PFE", "MRK", "ABT", "UNH",
    "WMT", "COST", "HD", "MCD", "NKE", "SBUX", "DIS",
    "KO", "PEP", "PG",
    "XOM", "CVX", "COP",
    "CAT", "BA", "HON", "GE", "MMM",
    "T", "VZ",
]


def load_closes() -> dict[str, pd.Series]:
    _load_dotenv(ROOT / ".env")
    prov = TiingoProvider(cache_dir=str(ROOT / "data_cache"))
    data = prov.get_history(UNIVERSE, START, END)
    closes = {s: df["close"].dropna() for s, df in data.items() if not df.empty}
    print(f"  loaded {len(closes)}/{len(UNIVERSE)} symbols")
    return closes


def build_factor(px: pd.DataFrame) -> pd.Series:
    """12-1 risk-adjusted momentum (mom/vol), computed DAILY, vectorized.

    Faithful to quantsys.strategy.momentum_logic.momentum_scores:
      over a trailing `lookback` window, mom = close[t-(skip-1)] / close[t-(lookback-1)] - 1,
      vol = std(daily returns over the window) * sqrt(252), score = mom / vol.
    We use the RAW score (no D2 >0 gate) so IC sees the full cross-section.
    Daily sampling is alphalens' canonical input and avoids its month-end
    frequency-inference bug.
    """
    mom = px.shift(SKIP - 1) / px.shift(LOOKBACK - 1) - 1.0
    vol = px.pct_change().rolling(LOOKBACK - 1).std() * np.sqrt(252)
    score = (mom / vol).replace([np.inf, -np.inf], np.nan)
    fac = score.stack().dropna()
    fac.index.set_names(["date", "asset"], inplace=True)
    fac = fac.sort_index()
    print(f"  factor: {len(fac)} obs over {fac.index.get_level_values(0).nunique()} trading days")
    return fac


def summarize(ic: pd.DataFrame) -> str:
    lines = ["Factor: 12-1 risk-adjusted momentum (mom/vol)  —  Rank IC analysis", ""]
    lines.append(f"{'horizon':>8} | {'mean IC':>8} | {'IC std':>7} | {'ICIR':>6} | {'t-stat':>7} | {'% > 0':>6}")
    lines.append("-" * 60)
    for col in ic.columns:
        s = ic[col].dropna()
        mean, std = s.mean(), s.std()
        icir = mean / std if std else float("nan")
        tstat = mean / std * np.sqrt(len(s)) if std else float("nan")
        pos = (s > 0).mean() * 100
        lines.append(f"{col:>8} | {mean:>8.4f} | {std:>7.4f} | {icir:>6.2f} | {tstat:>7.2f} | {pos:>5.1f}%")
    lines += [
        "",
        "Read it:  mean IC ~0.03-0.05 = decent for equities; ICIR = consistency",
        "(a factor's 'Sharpe'); t-stat > ~2 = unlikely to be luck; %>0 = how",
        "often the signal pointed the right way.",
    ]
    return "\n".join(lines)


def main() -> None:
    print("[1/4] loading closes (Tiingo, cached)...")
    closes = load_closes()
    print("[2/4] building factor (daily, vectorized)...")
    prices = pd.DataFrame({s: ser for s, ser in closes.items()}).sort_index()
    factor = build_factor(prices)

    print("[3/4] alphalens: cleaning factor + forward returns...")
    fd = al.utils.get_clean_factor_and_forward_returns(
        factor, prices, periods=PERIODS, quantiles=QUANTILES, max_loss=0.5
    )
    ic = al.performance.factor_information_coefficient(fd)  # Rank IC per date
    mean_q_ret, _ = al.performance.mean_return_by_quantile(fd, by_date=False)
    q_ret_bydate = al.performance.mean_return_by_quantile(fd, by_date=True)[0]

    # pick the ~1-month horizon column name (e.g. '21D')
    col = [c for c in ic.columns if c.endswith("D")][-1]

    summary = summarize(ic)
    (OUT / "summary.txt").write_text(summary)
    print("\n" + summary + "\n")

    print("[4/4] plotting -> analysis/factor_report/*.png")

    # 1) IC time series + rolling mean
    fig, ax = plt.subplots(figsize=(11, 4.5))
    s = ic[col].dropna()
    ax.bar(s.index, s.values, width=20, color=np.where(s > 0, "#4C9F70", "#C0504D"), alpha=0.6)
    ax.plot(s.index, s.rolling(12).mean(), color="#1f3b73", lw=2, label="12M rolling mean IC")
    ax.axhline(0, color="k", lw=0.8)
    ax.axhline(s.mean(), color="#1f3b73", ls="--", lw=1, label=f"mean IC = {s.mean():.3f}")
    ax.set_title(f"1) IC over time  ({col} forward)  —  does the signal predict, and stay predictive?")
    ax.set_ylabel("Rank IC"); ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout(); fig.savefig(OUT / "1_ic_timeseries.png", dpi=130); plt.close(fig)

    # 2) mean return by quantile (the staircase)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    q = mean_q_ret[col] * 10000  # bps
    ax.bar(q.index.astype(int), q.values, color="#4C72B0")
    ax.axhline(0, color="k", lw=0.8)
    ax.set_title(f"2) Mean forward return by factor quantile ({col})\nmonotonic staircase = healthy factor")
    ax.set_xlabel("factor quantile (1 = lowest momentum, 5 = highest)")
    ax.set_ylabel("mean forward return (bps)")
    fig.tight_layout(); fig.savefig(OUT / "2_quantile_returns.png", dpi=130); plt.close(fig)

    # 3) cumulative IC (regime view)
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(s.index, s.cumsum(), color="#7B3FA0", lw=2)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_title(f"3) Cumulative IC ({col})  —  rising = factor working; flat/falling = it stopped")
    ax.set_ylabel("cumulative Rank IC")
    fig.tight_layout(); fig.savefig(OUT / "3_cumulative_ic.png", dpi=130); plt.close(fig)

    # 4) top-minus-bottom cumulative spread — use the 1D horizon so daily
    # compounding is on NON-overlapping returns (compounding overlapping 21D
    # returns daily would massively distort the curve).
    col_1d = [c for c in ic.columns if c.endswith("D")][0]
    fig, ax = plt.subplots(figsize=(11, 4.5))
    qd = q_ret_bydate[col_1d].unstack("factor_quantile")
    spread = (qd[qd.columns.max()] - qd[qd.columns.min()]).dropna()
    cum = (1 + spread).cumprod()
    ax.plot(cum.index, cum.values, color="#2B7A4B", lw=2)
    ax.axhline(1, color="k", lw=0.8)
    ax.set_title(f"4) Long top quantile / short bottom, daily-rebalanced — cumulative ({col_1d})\nthe pure factor return, market beta stripped out")
    ax.set_ylabel("growth of 1")
    fig.tight_layout(); fig.savefig(OUT / "4_long_short_spread.png", dpi=130); plt.close(fig)

    print("done. open analysis/factor_report/ to view the 4 charts + summary.txt")


if __name__ == "__main__":
    main()

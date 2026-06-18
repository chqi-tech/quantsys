"""Reconcile quantsys vs QuantConnect on the LOCKED fixed universe.

Usage
-----
1. Run reconciliation/clean_momentum_fixed_qc.py in QuantConnect, export its
   equity curve to CSV (see RECONCILE.md).
2. uv run python reconciliation/reconcile.py --qc-csv path/to/qc_equity.csv \
       --provider tiingo --start 2010-01-01 --end 2024-12-31

What it does: runs quantsys momentum on the SAME fixed universe, aligns both
equity curves, normalizes them, and reports how closely they track. Because the
universe and rules are identical, the remaining differences come from (a) data
vendor (QC data vs Tiingo) and (b) fill-timing assumptions — NOT universe. A
high correlation + small final gap = your engine mechanics are validated.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantsys.core.engine import BacktestEngine
from quantsys.data.provider import (
    AlpacaProvider,
    SampleProvider,
    TiingoProvider,
    load_universe,
)
from quantsys.run import ROOT, _load_dotenv
from quantsys.strategy.clean_momentum import CleanMomentumStrategy

DATE_HINTS = ["time", "date", "timestamp", "datetime"]
VALUE_HINTS = ["equity", "value", "strategy equity", "close", "portfolio"]


def run_quantsys(provider_name, start, end, universe_path, benchmark="SPY", capital=100_000.0) -> pd.Series:
    _load_dotenv(ROOT / ".env")
    universe = load_universe(universe_path)
    symbols = sorted(set(universe) | {benchmark})
    provider = {
        "sample": SampleProvider,
        "tiingo": TiingoProvider,
        "alpaca": AlpacaProvider,
    }[provider_name]()
    data = {s: df for s, df in provider.get_history(symbols, start, end).items() if not df.empty}
    mom_universe = [s for s in universe if s != benchmark]
    engine = BacktestEngine(
        data=data,
        strategy_factory=lambda dh: CleanMomentumStrategy(dh, universe=mom_universe),
        initial_capital=capital,
        max_weight=0.20,
        benchmark_symbol=benchmark,
    )
    eq = engine.run().equity["equity"]
    eq.index = pd.to_datetime(eq.index).normalize()
    return eq


def load_qc_csv(path: str) -> pd.Series:
    df = pd.read_csv(path)
    cols_lower = {c.lower().strip(): c for c in df.columns}

    date_col = next((cols_lower[h] for h in DATE_HINTS if h in cols_lower), df.columns[0])
    val_col = next((cols_lower[h] for h in VALUE_HINTS if h in cols_lower), None)
    if val_col is None:
        numeric = df.select_dtypes("number").columns
        if len(numeric) == 0:
            raise SystemExit(f"No numeric value column found in {path}. Columns: {list(df.columns)}")
        val_col = numeric[-1]

    idx = pd.to_datetime(df[date_col], errors="coerce", utc=True)
    s = pd.Series(pd.to_numeric(df[val_col], errors="coerce").values,
                  index=idx.dt.tz_localize(None).dt.normalize())
    s = s.dropna().sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if s.empty:
        raise SystemExit(f"Parsed an empty series from {path} (date='{date_col}', value='{val_col}').")
    return s


def cagr(eq: pd.Series) -> float:
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else 0.0


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qc-csv", required=True, help="QC-exported equity curve CSV")
    ap.add_argument("--provider", default="tiingo", choices=["sample", "tiingo", "alpaca"])
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--universe", default=str(ROOT / "universe.csv"))
    args = ap.parse_args(argv)

    print(f"[reconcile] running quantsys momentum ({args.provider}, fixed universe)...")
    q = run_quantsys(args.provider, args.start, args.end, args.universe)
    c = load_qc_csv(args.qc_csv)

    # Align on the overlapping daily range; ffill QC onto quantsys dates.
    lo, hi = max(q.index[0], c.index[0]), min(q.index[-1], c.index[-1])
    q = q.loc[lo:hi]
    c = c.reindex(q.index, method="ffill").dropna()
    q = q.loc[c.index]
    if len(q) < 30:
        raise SystemExit(f"Only {len(q)} overlapping days — check the QC CSV dates / range.")

    # Normalize both to 1.0 at the first common date.
    qn, cn = q / q.iloc[0], c / c.iloc[0]
    rq, rc = qn.pct_change().dropna(), cn.pct_change().dropna()
    common = rq.index.intersection(rc.index)
    corr = float(np.corrcoef(rq.loc[common], rc.loc[common])[0, 1])
    tracking_err = float((rq.loc[common] - rc.loc[common]).std() * np.sqrt(252))
    div = (qn / cn - 1).abs()
    max_div, max_div_date = float(div.max()), div.idxmax().date()
    final_gap = float(qn.iloc[-1] / cn.iloc[-1] - 1)

    print("\n========== RECONCILIATION ==========")
    print(f"  overlap         {q.index[0].date()} → {q.index[-1].date()}  ({len(q)} days)")
    print(f"  quantsys CAGR   {cagr(q)*100:6.2f}%   final x{qn.iloc[-1]:.2f}")
    print(f"  QC       CAGR   {cagr(c)*100:6.2f}%   final x{cn.iloc[-1]:.2f}")
    print(f"  final gap       {final_gap*100:+.2f}%")
    print(f"  daily-ret corr  {corr:.4f}")
    print(f"  tracking error  {tracking_err*100:.2f}% / yr")
    print(f"  max divergence  {max_div*100:.2f}%  (on {max_div_date})")
    print("====================================")

    if corr >= 0.95 and abs(final_gap) <= 0.15:
        print("VERDICT: ✅ engine mechanics validated — curves track closely.")
        print("         Residual差异 consistent with data-vendor + fill-timing, not bugs.")
    elif corr >= 0.90:
        print("VERDICT: ⚠️ mostly aligned but notable drift. Inspect around the max-divergence")
        print("         date — likely a fill-timing or rebalance-day difference, possibly a bug.")
    else:
        print("VERDICT: ❌ curves diverge structurally (corr < 0.90). Likely an ENGINE BUG.")
        print("         Check: rebalance trigger, momentum window indices, fill timing, accounting.")


if __name__ == "__main__":
    main()

"""CLI entry point.

Examples
--------
# Runs immediately, no account needed (synthetic data):
python -m quantsys.run --strategy momentum
python -m quantsys.run --strategy buyhold

# Real data once you have free Alpaca keys in .env:
python -m quantsys.run --strategy momentum --provider alpaca --start 2014-01-01 --end 2024-01-01
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .core.engine import BacktestEngine
from .data.provider import AlpacaProvider, SampleProvider, TiingoProvider, load_universe
from .report.metrics import summarize
from .report.report import write_html_report
from .strategy.buy_hold import BuyHoldStrategy
from .strategy.clean_momentum import CleanMomentumStrategy

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Tiny zero-dependency .env loader: KEY=VALUE lines into os.environ."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="quantsys")
    p.add_argument("--strategy", choices=["buyhold", "momentum"], default="momentum")
    p.add_argument("--provider", choices=["sample", "alpaca", "tiingo"], default="sample")
    p.add_argument("--start", default="2015-01-01")
    p.add_argument("--end", default="2024-12-31")
    p.add_argument("--capital", type=float, default=100_000.0)
    p.add_argument("--benchmark", default="SPY")
    p.add_argument("--universe", default=str(ROOT / "universe.csv"))
    p.add_argument("--out", default=str(ROOT / "reports" / "report.html"))
    p.add_argument("--equity-csv", default=None, help="also dump the equity curve to this CSV")
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument("--commission-bps", type=float, default=0.0)
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    _load_dotenv(ROOT / ".env")

    universe = load_universe(args.universe)
    symbols = sorted(set(universe) | {args.benchmark})

    if args.provider == "sample":
        provider = SampleProvider()
    elif args.provider == "tiingo":
        provider = TiingoProvider()
    else:
        provider = AlpacaProvider()
    print(f"[quantsys] provider={args.provider} strategy={args.strategy} "
          f"{args.start}..{args.end} symbols={len(symbols)}")
    data = provider.get_history(symbols, args.start, args.end)
    data = {s: df for s, df in data.items() if not df.empty}
    if not data:
        raise SystemExit("No data returned. Check provider/keys/date range.")

    if args.strategy == "buyhold":
        factory = lambda dh: BuyHoldStrategy(dh, symbol=args.benchmark)
        max_weight = 1.0  # a single-name buy&hold needs full exposure
    else:
        mom_universe = [s for s in universe if s != args.benchmark]
        factory = lambda dh: CleanMomentumStrategy(dh, universe=mom_universe)
        max_weight = 0.20  # single-name cap per the design risk rule

    engine = BacktestEngine(
        data=data,
        strategy_factory=factory,
        initial_capital=args.capital,
        slippage_bps=args.slippage_bps,
        commission_bps=args.commission_bps,
        max_weight=max_weight,
        benchmark_symbol=args.benchmark,
    )
    result = engine.run()

    s = summarize(result.equity["equity"])
    print("\n=== Result ===")
    print(f"  period      {s['start']} → {s['end']}")
    print(f"  final       ${s['final']:,.0f}  (init ${s['initial']:,.0f})")
    print(f"  total ret   {s['total_return']*100:,.1f}%")
    print(f"  CAGR        {s['cagr']*100:,.2f}%")
    print(f"  Sharpe      {s['sharpe']:,.2f}")
    print(f"  ann vol     {s['annual_vol']*100:,.1f}%")
    print(f"  max DD      {s['max_drawdown']*100:,.1f}%")
    print(f"  fills       {result.n_fills:,}")

    note = "synthetic data" if args.provider == "sample" else ""
    out = write_html_report(result, args.out, note=note)
    print(f"\n[quantsys] report -> {out}")

    if args.equity_csv:
        result.equity[["equity"]].to_csv(args.equity_csv)
        print(f"[quantsys] equity csv -> {args.equity_csv}")


if __name__ == "__main__":
    main()

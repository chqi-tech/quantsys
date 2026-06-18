"""Live (paper) rebalance — run THIS strategy forward in the real market on Alpaca.

This is NOT a backtest. It computes today's target portfolio from the SAME
momentum brain the backtest uses (momentum_target_weights), reads your live
Alpaca paper account, and places the orders to reach the target. Run it monthly
(manually or via cron / GitHub Actions). Between runs your positions sit in the
real market and their value moves day to day — a forward, out-of-sample P&L curve
you can show on the Alpaca dashboard.

Signal data: Tiingo (clean) by default. Execution: Alpaca PAPER.

Safety: DRY-RUN by default — it prints the plan and places NO orders. Add --live
to actually submit paper orders (still no real money; it's the paper account).

Usage:
    uv run python live/rebalance.py              # dry run (no orders)
    uv run python live/rebalance.py --live       # actually place paper orders
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantsys.data.provider import AlpacaProvider, TiingoProvider, load_universe
from quantsys.run import ROOT, _load_dotenv
from quantsys.strategy.momentum_logic import momentum_target_weights

MIN_ORDER_USD = 1.0       # skip dust orders
LOG_PATH = ROOT / "live" / "rebalance_log.csv"


def get_signal_closes(provider_name: str, universe: list[str], lookback: int) -> dict[str, pd.Series]:
    end = pd.Timestamp.today().normalize()
    start = end - timedelta(days=int(lookback * 1.7) + 40)  # enough calendar days for `lookback` trading days
    provider = TiingoProvider() if provider_name == "tiingo" else AlpacaProvider()
    data = provider.get_history(universe, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    return {s: df["close"] for s, df in data.items() if not df.empty}


def log_rows(rows: list[dict]) -> None:
    new = not LOG_PATH.exists()
    with open(LOG_PATH, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ts", "mode", "action", "symbol", "usd", "note"])
        if new:
            w.writeheader()
        w.writerows(rows)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="actually submit paper orders (default: dry run)")
    ap.add_argument("--monthly", action="store_true",
                    help="only rebalance on the first trading day of the month (or if the account is empty). "
                         "Makes a daily cron safe — other days are a no-op.")
    ap.add_argument("--provider", default="tiingo", choices=["tiingo", "alpaca"], help="signal data source")
    ap.add_argument("--universe", default=str(ROOT / "universe.csv"))
    ap.add_argument("--lookback", type=int, default=252)
    ap.add_argument("--skip", type=int, default=21)
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--target-vol", type=float, default=0.15)
    ap.add_argument("--vol-window", type=int, default=60)
    args = ap.parse_args(argv)

    _load_dotenv(ROOT / ".env")
    mode = "LIVE" if args.live else "DRY-RUN"
    universe = load_universe(args.universe)

    # 1. signal — same brain as the backtest
    closes = get_signal_closes(args.provider, universe, args.lookback)
    targets = momentum_target_weights(
        closes, args.lookback, args.skip, args.top_n, args.target_vol, args.vol_window
    )
    if not targets:
        print("No targets (not enough data?). Aborting.")
        return

    # 2. Alpaca paper account
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    import os
    client = TradingClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"], paper=True)
    account = client.get_account()
    equity = float(account.equity)
    positions = {p.symbol: float(p.market_value) for p in client.get_all_positions()}
    clock = client.get_clock()

    # Monthly guard: skip unless it's the first trading day of the month
    # (or the account is empty — the initial build).
    if args.monthly and positions:
        import pandas_market_calendars as mcal
        today = pd.Timestamp.today().normalize()
        nyse = mcal.get_calendar("NYSE")
        sched = nyse.schedule(start_date=today.replace(day=1), end_date=today)
        first_session = sched.index[0].date() if not sched.empty else None
        if today.date() != first_session:
            print(f"[{mode}] --monthly: today is not the first trading day of the month "
                  f"and account is not empty. No-op.")
            return

    target_value = {s: w * equity for s, w in targets.items()}

    print(f"\n========== REBALANCE [{mode}] ==========")
    print(f"  market open: {clock.is_open}   equity: ${equity:,.2f}   cash: ${float(account.cash):,.2f}")
    print(f"  signal: {args.provider}   winners: {len(targets)}   target weight each: {list(targets.values())[0]*100:.1f}%")
    print(f"  current positions: {len(positions)}")

    sells, buys = [], []
    # exits: held but not a winner -> close
    for sym, mv in positions.items():
        if sym not in target_value and mv > 0:
            sells.append(("CLOSE", sym, mv))
    # adjustments toward targets
    for sym, tv in target_value.items():
        cur = positions.get(sym, 0.0)
        delta = tv - cur
        if delta > MIN_ORDER_USD:
            buys.append(("BUY", sym, delta))
        elif delta < -MIN_ORDER_USD:
            sells.append(("SELL", sym, -delta))

    plan = sells + buys
    print("\n  PLAN:")
    for action, sym, usd in plan:
        print(f"    {action:5s} {sym:6s} ${usd:,.2f}")
    if not plan:
        print("    (already at target — nothing to do)")

    rows = []
    if args.live:
        if not clock.is_open:
            print("\n  ⚠️ Market is CLOSED — fractional/notional orders need regular hours. "
                  "Run 09:30–16:00 ET. Submitting anyway; some may be rejected.")
        print("\n  SUBMITTING paper orders...")
        # sells/closes first to free buying power, then buys
        for action, sym, usd in sells:
            try:
                if action == "CLOSE":
                    client.close_position(sym)
                else:
                    client.submit_order(MarketOrderRequest(
                        symbol=sym, notional=round(usd, 2), side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
                print(f"    ✅ {action} {sym} ${usd:,.2f}")
                rows.append({"ts": str(pd.Timestamp.now()), "mode": mode, "action": action, "symbol": sym, "usd": round(usd, 2), "note": "ok"})
            except Exception as e:
                print(f"    ❌ {action} {sym}: {e}")
                rows.append({"ts": str(pd.Timestamp.now()), "mode": mode, "action": action, "symbol": sym, "usd": round(usd, 2), "note": f"ERR {e}"})
        for action, sym, usd in buys:
            try:
                client.submit_order(MarketOrderRequest(
                    symbol=sym, notional=round(usd, 2), side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
                print(f"    ✅ BUY {sym} ${usd:,.2f}")
                rows.append({"ts": str(pd.Timestamp.now()), "mode": mode, "action": "BUY", "symbol": sym, "usd": round(usd, 2), "note": "ok"})
            except Exception as e:
                print(f"    ❌ BUY {sym}: {e}")
                rows.append({"ts": str(pd.Timestamp.now()), "mode": mode, "action": "BUY", "symbol": sym, "usd": round(usd, 2), "note": f"ERR {e}"})
    else:
        print("\n  (dry run — no orders placed. Add --live to submit paper orders.)")
        rows = [{"ts": str(pd.Timestamp.now()), "mode": mode, "action": a, "symbol": s, "usd": round(u, 2), "note": "planned"} for a, s, u in plan]

    if rows:
        log_rows(rows)
        print(f"\n  logged -> {LOG_PATH}")
    print("==========================================")


if __name__ == "__main__":
    main()

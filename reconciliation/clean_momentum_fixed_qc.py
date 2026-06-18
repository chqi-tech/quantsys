# QC reconciliation script — SAME strategy, SAME fixed universe as quantsys.
#
# Purpose: run THIS in QuantConnect, export its equity curve, then run
# reconciliation/reconcile.py to compare against quantsys. Because the universe
# and rules are locked identical to quantsys, any large/structural divergence
# points at an ENGINE-MECHANICS bug — not a universe difference.
#
# The ONLY change vs your original CleanMomentum: the dynamic coarse_selection
# (top-100 by dollar volume) is replaced by the SAME fixed 30-name universe as
# quantsys/universe.csv. Everything else (12-1 momentum, risk-adjusted score,
# top-10, vol targeting, monthly rebalance) is identical.
#
# How to run: paste into a new QuantConnect Python algorithm, Backtest, then
# Results -> export the equity curve to CSV (see reconciliation/RECONCILE.md).

from AlgorithmImports import *
import numpy as np

# Must match quantsys/universe.csv exactly.
FIXED_UNIVERSE = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "JPM", "JNJ", "V",
    "PG", "HD", "MA", "BAC", "DIS", "ADBE", "CRM", "NFLX", "KO", "PEP",
    "CSCO", "INTC", "WMT", "XOM", "CVX", "PFE", "MRK", "ABT", "NKE", "MCD",
]


class CleanMomentumFixed(QCAlgorithm):

    def initialize(self):
        self.set_start_date(2010, 1, 1)
        self.set_end_date(2024, 12, 31)
        self.set_cash(100000)

        self.lookback = 252
        self.skip = 21
        self.top_n = 10
        self.target_vol = 0.15
        self.vol_window = 60

        self.universe_settings.resolution = Resolution.DAILY
        # FIXED universe instead of add_universe(coarse_selection).
        self.symbols = [self.add_equity(t, Resolution.DAILY).symbol for t in FIXED_UNIVERSE]
        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol

        self.set_warm_up(self.lookback + 30, Resolution.DAILY)
        self.schedule.on(self.date_rules.month_start(self.spy),
                         self.time_rules.after_market_open(self.spy, 30),
                         self.rebalance)

    def compute_scores(self):
        hist = self.history(self.symbols, self.lookback, Resolution.DAILY)
        if hist.empty or "close" not in hist.columns:
            return {}, None
        closes = hist["close"].unstack(level=0)
        scores = {}
        for s in self.symbols:
            if s not in closes.columns:
                continue
            prices = closes[s].dropna()
            if len(prices) < self.lookback:
                continue
            end = -self.skip if self.skip > 0 else -1
            mom = prices.iloc[end] / prices.iloc[0] - 1
            rets = prices.pct_change().dropna()
            vol = rets.std() * np.sqrt(252)
            if vol == 0:
                continue
            scores[s] = mom / vol
        return scores, closes

    def rebalance(self):
        if self.is_warming_up:
            return
        scores, closes = self.compute_scores()
        if not scores:
            return
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        winners = [s for s, _ in ranked[:self.top_n]]

        for kvp in self.portfolio:
            sym = kvp.key
            if self.portfolio[sym].invested and sym not in winners:
                self.liquidate(sym)

        tradable = [s for s in winners if self.securities[s].price > 0]
        if not tradable:
            return

        recent = closes[tradable].pct_change().dropna().tail(self.vol_window)
        port_ret = recent.mean(axis=1)
        port_vol = port_ret.std() * np.sqrt(252)
        exposure = min(1.0, self.target_vol / port_vol) if port_vol > 0 else 1.0

        weight = exposure / len(tradable)
        for sym in tradable:
            self.set_holdings(sym, weight)

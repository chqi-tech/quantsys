# QC backtest of the CURRENT strategy = original CleanMomentum + D2 absolute-momentum filter.
#
# This is the best way to see the strategy's TRUE historical behavior: QC supplies a
# point-in-time, survivorship-bias-free, FULL-MARKET dynamic universe (top-100 by dollar
# volume each month, including names later delisted) — exactly what free data can't give
# the quantsys backtest.
#
# Difference vs your LIVE quantsys: live uses the S&P 500 list (a clean free approximation)
# + Alpaca/Tiingo data; this QC version uses QC's full-market coarse universe + QC data.
# Same strategy LOGIC (12-1 risk-adjusted momentum, top-10, vol-target, monthly, + D2);
# the universe source differs, so it's the more faithful/complete backtest, not identical
# to a quantsys run.
#
# TIP: flip USE_ABS_MOMENTUM_FILTER to compare the strategy WITH vs WITHOUT the D2 gate —
# you'll see the filter move to cash in 2008 / 2020 / 2022 (the bear-market defense).
#
# How to run: paste into a new QuantConnect Python algorithm (replace main.py), Backtest.

from AlgorithmImports import *
import numpy as np

USE_ABS_MOMENTUM_FILTER = True   # D2. Set False to reproduce the original (no bear defense).


class CleanMomentumDynamic(QCAlgorithm):

    def initialize(self):
        self.set_start_date(2008, 1, 1)
        self.set_end_date(2025, 12, 31)
        self.set_cash(100000)

        self.lookback = 252
        self.skip = 21
        self.top_n = 10
        self.coarse_count = 100
        self.target_vol = 0.15
        self.vol_window = 60

        self.universe_settings.resolution = Resolution.DAILY
        self.add_universe(self.coarse_selection)
        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol

        self.set_warm_up(self.lookback + 30, Resolution.DAILY)
        self.schedule.on(self.date_rules.month_start(self.spy),
                         self.time_rules.after_market_open(self.spy, 30),
                         self.rebalance)

    def coarse_selection(self, coarse):
        filtered = [c for c in coarse if c.has_fundamental_data and c.price > 5]
        ranked = sorted(filtered, key=lambda c: c.dollar_volume, reverse=True)
        return [c.symbol for c in ranked[:self.coarse_count]]

    def compute_scores(self, symbols):
        hist = self.history(symbols, self.lookback, Resolution.DAILY)
        if hist.empty or "close" not in hist.columns:
            return {}, None
        closes = hist["close"].unstack(level=0)
        scores = {}
        for s in symbols:
            if s not in closes.columns:
                continue
            prices = closes[s].dropna()
            if len(prices) < self.lookback:
                continue
            end = -self.skip if self.skip > 0 else -1
            mom = prices.iloc[end] / prices.iloc[0] - 1          # 12-1 momentum
            rets = prices.pct_change().dropna()
            vol = rets.std() * np.sqrt(252)
            if vol == 0:
                continue
            scores[s] = mom / vol                                # risk-adjusted
        return scores, closes

    def rebalance(self):
        if self.is_warming_up:
            return
        symbols = [x.key for x in self.active_securities if x.key != self.spy]
        if not symbols:
            return
        scores, closes = self.compute_scores(symbols)
        if not scores:
            return
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # D2: absolute-momentum gate. score = mom/vol and vol>0, so sc>0 == mom>0.
        if USE_ABS_MOMENTUM_FILTER:
            winners = [s for s, sc in ranked[:self.top_n] if sc > 0]
        else:
            winners = [s for s, _ in ranked[:self.top_n]]

        # Liquidate anything not a winner — including EVERYTHING when winners is empty
        # (no positive momentum → all cash, the bear-market defense).
        for kvp in self.portfolio:
            sym = kvp.key
            if self.portfolio[sym].invested and sym not in winners:
                self.liquidate(sym)

        if not winners:
            return  # all cash

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

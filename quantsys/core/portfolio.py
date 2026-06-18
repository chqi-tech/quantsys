"""Portfolio — holdings/equity accounting + position sizing + simple risk.

Sizing rule (phase 1, deliberately simple per the design): target-weight in,
integer shares out, single-name cap, no leverage, sells before buys, reject the
part of a buy that exceeds cash. That's it — no fancy risk model yet.
"""

from __future__ import annotations

import math

import pandas as pd

from .data_handler import HistoricDataHandler
from .events import FillEvent, OrderEvent, SignalEvent


class Portfolio:
    def __init__(
        self,
        data_handler: HistoricDataHandler,
        initial_capital: float = 100_000.0,
        max_weight: float = 0.20,
    ):
        self.dh = data_handler
        self.initial_capital = float(initial_capital)
        self.max_weight = max_weight

        self.cash = float(initial_capital)
        self.positions: dict[str, int] = {}
        self.equity_curve: list[tuple] = []  # (dt, equity, cash)

    # ---- accounting -------------------------------------------------------
    def market_value(self) -> float:
        mv = 0.0
        for sym, qty in self.positions.items():
            if qty == 0:
                continue
            px = self.dh.get_latest_value(sym, "close")
            if px is not None:
                mv += qty * px
        return mv

    def equity(self) -> float:
        return self.cash + self.market_value()

    def mark_to_market(self) -> None:
        self.equity_curve.append((self.dh.current_dt, self.equity(), self.cash))

    def on_fill(self, fill: FillEvent) -> None:
        self.positions[fill.symbol] = self.positions.get(fill.symbol, 0) + fill.quantity
        self.cash -= fill.quantity * fill.fill_price  # signed: buys cost, sells add
        self.cash -= fill.commission
        if self.positions[fill.symbol] == 0:
            del self.positions[fill.symbol]

    # ---- order generation from target weights -----------------------------
    def generate_orders(self, signals: list[SignalEvent]) -> list[OrderEvent]:
        if not signals:
            return []
        equity = self.equity()
        dt = self.dh.current_dt

        deltas: dict[str, int] = {}
        for sig in signals:
            w = max(0.0, min(sig.target_weight, self.max_weight))
            px = self.dh.get_latest_value(sig.symbol, "close")
            if px is None or px <= 0:
                continue
            target_shares = int(math.floor(w * equity / px))
            current = self.positions.get(sig.symbol, 0)
            delta = target_shares - current
            if delta != 0:
                deltas[sig.symbol] = delta

        orders: list[OrderEvent] = []
        # Sells first to free up cash.
        for sym, delta in deltas.items():
            if delta < 0:
                orders.append(OrderEvent(dt, sym, delta))

        # Buys, constrained by a running cash estimate (priced at last close).
        projected_cash = self.cash + sum(
            -delta * self.dh.get_latest_value(sym, "close")
            for sym, delta in deltas.items()
            if delta < 0
        )
        for sym, delta in deltas.items():
            if delta <= 0:
                continue
            px = self.dh.get_latest_value(sym, "close")
            affordable = int(math.floor(projected_cash / px)) if px > 0 else 0
            qty = min(delta, max(0, affordable))
            if qty > 0:
                orders.append(OrderEvent(dt, sym, qty))
                projected_cash -= qty * px
        return orders

    # ---- results ----------------------------------------------------------
    def equity_dataframe(self) -> pd.DataFrame:
        df = pd.DataFrame(self.equity_curve, columns=["dt", "equity", "cash"])
        return df.set_index("dt")

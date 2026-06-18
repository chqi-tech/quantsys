"""ExecutionHandler — fills orders at the NEXT bar's open.

This is the命根子 of the "no look-ahead" promise: an order decided on bar T (from
T's close) is filled at T+1's OPEN, never at T's close. Orders queue here and are
filled at the start of the next bar's processing. Slippage and commission are
modeled honestly. Swap this for a broker adapter in the live phase.
"""

from __future__ import annotations

from .data_handler import HistoricDataHandler
from .events import FillEvent, OrderEvent


class SimulatedExecutionHandler:
    def __init__(
        self,
        data_handler: HistoricDataHandler,
        slippage_bps: float = 5.0,
        commission_bps: float = 0.0,
    ):
        self.dh = data_handler
        self.slippage_bps = slippage_bps
        self.commission_bps = commission_bps
        self._pending: list[OrderEvent] = []

    def queue(self, orders: list[OrderEvent]) -> None:
        self._pending.extend(orders)

    def fill_pending(self) -> list[FillEvent]:
        """Called at the start of each bar: fill queued orders at THIS bar's open."""
        if not self._pending:
            return []
        fills: list[FillEvent] = []
        still_pending: list[OrderEvent] = []
        dt = self.dh.current_dt
        for order in self._pending:
            if not self.dh.has_bar_today(order.symbol):
                # Symbol doesn't trade today — keep the order for the next bar.
                still_pending.append(order)
                continue
            open_px = self.dh.get_latest_value(order.symbol, "open")
            if open_px is None or open_px <= 0:
                still_pending.append(order)
                continue
            slip = self.slippage_bps / 10_000.0 * order.direction
            fill_price = open_px * (1 + slip)
            commission = abs(order.quantity) * fill_price * self.commission_bps / 10_000.0
            fills.append(
                FillEvent(dt, order.symbol, order.quantity, fill_price, commission)
            )
        self._pending = still_pending
        return fills

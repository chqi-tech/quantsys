"""Backtest engine — the bar-synchronous event loop.

Per bar T the pipeline is strictly:
  1. fill orders queued on T-1  -> at T's OPEN   (next-bar-open, no look-ahead)
  2. mark portfolio to market   -> at T's CLOSE
  3. strategy emits signals      -> using data up to T's CLOSE
  4. portfolio turns signals into orders -> queued for T+1

Swap the data_handler for a live feed and the execution for a broker, and the
same strategy/portfolio run live. That is the whole point of the architecture.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import pandas as pd

from .data_handler import HistoricDataHandler
from .events import MarketEvent
from .execution import SimulatedExecutionHandler
from .portfolio import Portfolio


@dataclass
class BacktestResult:
    equity: pd.DataFrame
    benchmark: pd.Series | None
    initial_capital: float
    n_fills: int
    strategy_name: str


class BacktestEngine:
    def __init__(
        self,
        data: dict[str, pd.DataFrame],
        strategy_factory,
        initial_capital: float = 100_000.0,
        slippage_bps: float = 5.0,
        commission_bps: float = 0.0,
        max_weight: float = 0.20,
        benchmark_symbol: str = "SPY",
    ):
        self.events: deque = deque()
        self.data = data
        self.dh = HistoricDataHandler(data, self.events)
        self.portfolio = Portfolio(self.dh, initial_capital, max_weight)
        self.execution = SimulatedExecutionHandler(self.dh, slippage_bps, commission_bps)
        # strategy_factory(data_handler) -> Strategy
        self.strategy = strategy_factory(self.dh)
        self.benchmark_symbol = benchmark_symbol
        self.n_fills = 0

    def run(self) -> BacktestResult:
        while self.dh.update_bars():
            while self.events:
                ev = self.events.popleft()
                if isinstance(ev, MarketEvent):
                    self._on_market()
        return self._result()

    def _on_market(self) -> None:
        # 1. fill yesterday's orders at today's open
        for fill in self.execution.fill_pending():
            self.portfolio.on_fill(fill)
            self.n_fills += 1
        # 2. mark to market at today's close
        self.portfolio.mark_to_market()
        # 3. strategy decides on today's close
        signals = self.strategy.calculate_signals()
        # 4. size and queue orders for tomorrow's open
        orders = self.portfolio.generate_orders(signals)
        self.execution.queue(orders)

    def _result(self) -> BacktestResult:
        equity = self.portfolio.equity_dataframe()
        benchmark = None
        if self.benchmark_symbol in self.data and not equity.empty:
            bench = self.data[self.benchmark_symbol]["adj_close"].reindex(
                equity.index, method="ffill"
            )
            benchmark = bench / bench.iloc[0] * self.portfolio.initial_capital
            benchmark.name = f"{self.benchmark_symbol} buy&hold"
        return BacktestResult(
            equity=equity,
            benchmark=benchmark,
            initial_capital=self.portfolio.initial_capital,
            n_fills=self.n_fills,
            strategy_name=type(self.strategy).__name__,
        )

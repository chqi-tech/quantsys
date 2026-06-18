"""Strategy base class — the ONE interface that runs in backtest/paper/live.

A strategy only ever sees the DataHandler, and the DataHandler only exposes
current-and-past bars. So a strategy literally cannot read the future: look-ahead
is prevented by construction, not by discipline.

Implement `calculate_signals()` to return a list of SignalEvent (target weights).
Return [] on bars where you don't want to change anything.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.data_handler import HistoricDataHandler
from ..core.events import SignalEvent


class Strategy(ABC):
    def __init__(self, data_handler: HistoricDataHandler):
        self.dh = data_handler

    @abstractmethod
    def calculate_signals(self) -> list[SignalEvent]:
        raise NotImplementedError

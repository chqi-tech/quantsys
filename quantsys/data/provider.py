"""Data layer (取数 + 缓存).

`DataProvider` is the swap point the design calls for: same backtest code, any
source. Three implementations:

- SampleProvider:  deterministic synthetic bars. No account, no network. This is
                   what makes `quantsys` run the instant you clone it.
- AlpacaProvider:  real daily adjusted bars (adjustment='all'), parquet-cached.
                   Needs free Alpaca keys in .env. Imported lazily so the sample
                   path has zero heavy deps.

Every provider returns: dict[symbol] -> DataFrame indexed by tz-naive date with
columns [open, high, low, close, adj_close, volume]. `close` is already the
adjusted close — strategies and accounting use it directly.
"""

from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
import pandas as pd

BAR_COLUMNS = ["open", "high", "low", "close", "adj_close", "volume"]


def load_universe(path: str | Path) -> list[str]:
    """Read the fixed universe (Option A) from a one-column CSV."""
    df = pd.read_csv(path)
    return [s.strip().upper() for s in df["symbol"].tolist() if str(s).strip()]


class DataProvider(ABC):
    @abstractmethod
    def get_history(
        self, symbols: list[str], start: str, end: str
    ) -> dict[str, pd.DataFrame]:
        """Return {symbol: bars}. Called ONCE before the backtest loop."""
        raise NotImplementedError


class SampleProvider(DataProvider):
    """Deterministic synthetic daily bars — a seeded geometric random walk.

    Some symbols are given a persistent drift so the momentum strategy has real
    cross-sectional dispersion to rank. Reproducible: same symbols+dates always
    give the same data (seeded off the symbol name).
    """

    def __init__(self, annual_drift: float = 0.07, annual_vol: float = 0.25):
        self.annual_drift = annual_drift
        self.annual_vol = annual_vol

    def _seed(self, symbol: str) -> int:
        # Stable across processes — builtin hash() is randomized per run
        # (PYTHONHASHSEED), which would make backtests non-reproducible.
        return int.from_bytes(hashlib.md5(symbol.encode()).digest()[:4], "little")

    def get_history(
        self, symbols: list[str], start: str, end: str
    ) -> dict[str, pd.DataFrame]:
        dates = pd.bdate_range(start=start, end=end)
        n = len(dates)
        dt = 1.0 / 252.0
        out: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            rng = np.random.default_rng(self._seed(sym))
            # Give each symbol its own persistent drift so momentum can rank them.
            sym_drift = self.annual_drift + rng.normal(0, 0.12)
            sym_vol = max(0.08, self.annual_vol + rng.normal(0, 0.05))
            shocks = rng.normal(
                (sym_drift - 0.5 * sym_vol**2) * dt,
                sym_vol * np.sqrt(dt),
                size=n,
            )
            close = 100.0 * np.exp(np.cumsum(shocks))
            # Build O/H/L around the close with small intrabar noise.
            prev_close = np.concatenate([[close[0]], close[:-1]])
            gap = rng.normal(0, 0.002, size=n)
            open_ = prev_close * (1 + gap)
            high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
            low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
            volume = rng.integers(1_000_000, 10_000_000, size=n)
            df = pd.DataFrame(
                {
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "adj_close": close,
                    "volume": volume,
                },
                index=dates,
            )
            out[sym] = df
        return out


class TiingoProvider(DataProvider):
    """Clean, consolidated, split+dividend-adjusted daily EOD bars from Tiingo.

    Much better than the free IEX feed for long cross-sectional backtests:
    consolidated (not single-venue), complete daily series, decades of history.
    Free token at https://www.tiingo.com/account/api/token (TIINGO_API_KEY).
    Uses the adjusted fields (adjOpen/High/Low/Close) so `close` is total-return
    adjusted, consistent with AlpacaProvider's adjustment='all'.
    """

    def __init__(self, cache_dir: str | Path = "data_cache", token=None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.token = token or os.environ.get("TIINGO_API_KEY")

    def _cache_path(self, symbol: str, start: str, end: str) -> Path:
        return self.cache_dir / f"tiingo_{symbol}_{start}_{end}.parquet"

    def get_history(
        self, symbols: list[str], start: str, end: str
    ) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            p = self._cache_path(sym, start, end)
            if p.exists():
                out[sym] = pd.read_parquet(p)
                continue
            df = self._fetch_one(sym, start, end)
            if not df.empty:
                df.to_parquet(p)
                out[sym] = df
        return out

    def _fetch_one(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        if not self.token:
            raise RuntimeError(
                "Tiingo token missing. Set TIINGO_API_KEY in .env "
                "(get one free at https://www.tiingo.com/account/api/token)."
            )
        import requests

        url = f"https://api.tiingo.com/tiingo/daily/{symbol}/prices"
        params = {
            "startDate": start,
            "endDate": end,
            "format": "json",
            "resampleFreq": "daily",
            "token": self.token,
        }
        r = requests.get(url, params=params, headers={"Content-Type": "application/json"})
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        df = df.set_index("date").sort_index()
        out = pd.DataFrame(index=df.index)
        out["open"] = df["adjOpen"]
        out["high"] = df["adjHigh"]
        out["low"] = df["adjLow"]
        out["close"] = df["adjClose"]
        out["adj_close"] = df["adjClose"]
        out["volume"] = df["adjVolume"]
        return out[BAR_COLUMNS]


class AlpacaProvider(DataProvider):
    """Real daily adjusted bars from Alpaca, parquet-cached.

    Uses adjustment='all' (split + dividend) so `close` is total-return adjusted
    — that is what makes the buy&hold reconciliation check meaningful. Keys come
    from the environment (load a .env yourself or export them).
    """

    def __init__(self, cache_dir: str | Path = "data_cache", api_key=None, secret_key=None, feed: str = "iex"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key or os.environ.get("ALPACA_API_KEY")
        self.secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY")
        # Free (Basic) accounts only get the IEX feed; SIP needs a paid plan.
        self.feed = feed

    def _cache_path(self, symbol: str, start: str, end: str) -> Path:
        return self.cache_dir / f"{symbol}_{start}_{end}.parquet"

    def get_history(
        self, symbols: list[str], start: str, end: str
    ) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        to_fetch: list[str] = []
        for sym in symbols:
            p = self._cache_path(sym, start, end)
            if p.exists():
                out[sym] = pd.read_parquet(p)
            else:
                to_fetch.append(sym)

        if to_fetch:
            fetched = self._fetch(to_fetch, start, end)
            for sym, df in fetched.items():
                df.to_parquet(self._cache_path(sym, start, end))
                out[sym] = df
        return out

    def _fetch(self, symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
        if not self.api_key or not self.secret_key:
            raise RuntimeError(
                "Alpaca keys missing. Set ALPACA_API_KEY / ALPACA_SECRET_KEY "
                "(copy .env.example -> .env), or use SampleProvider."
            )
        # Lazy import so the sample path never needs alpaca-py installed.
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import Adjustment, DataFeed

        feed = DataFeed.IEX if self.feed.lower() == "iex" else DataFeed.SIP
        client = StockHistoricalDataClient(self.api_key, self.secret_key)
        req = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=pd.Timestamp(start),
            end=pd.Timestamp(end),
            adjustment=Adjustment.ALL,
            feed=feed,
        )
        bars = client.get_stock_bars(req).df  # MultiIndex (symbol, timestamp)
        out: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            if sym not in bars.index.get_level_values(0):
                continue
            sdf = bars.xs(sym, level=0).copy()
            sdf.index = pd.to_datetime(sdf.index).tz_localize(None).normalize()
            df = pd.DataFrame(index=sdf.index)
            df["open"] = sdf["open"]
            df["high"] = sdf["high"]
            df["low"] = sdf["low"]
            df["close"] = sdf["close"]
            df["adj_close"] = sdf["close"]  # adjustment='all' already applied
            df["volume"] = sdf["volume"]
            out[sym] = df[BAR_COLUMNS]
        return out

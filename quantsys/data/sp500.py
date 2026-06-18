"""S&P 500 universe resolver — Wikipedia (live) with committed-CSV fallback.

Per docs/REQUIREMENTS.md R1: the trading source of truth is data/sp500.csv.
Wikipedia is a best-effort refresh; on any failure we fall back to the CSV so an
unattended live run never breaks just because Wikipedia changed or blocked us.

Note: Wikipedia blocks the default urllib user-agent (HTTP 403), so we fetch with
a browser UA via requests, then parse with pandas.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}


def fetch_sp500_wikipedia(timeout: int = 30) -> list[str]:
    import requests

    r = requests.get(WIKI_URL, headers=_UA, timeout=timeout)
    r.raise_for_status()
    df = pd.read_html(io.StringIO(r.text))[0]
    col = next(c for c in df.columns if str(c).lower() in ("symbol", "ticker"))
    syms = [str(s).strip().upper() for s in df[col] if str(s).strip()]
    if len(syms) < 400:
        raise ValueError(f"Wikipedia returned only {len(syms)} tickers — looks wrong")
    return syms


def load_sp500_csv(csv_path: str | Path) -> list[str]:
    df = pd.read_csv(csv_path)
    return [str(s).strip().upper() for s in df["symbol"].tolist() if str(s).strip()]


def get_sp500(csv_path: str | Path, refresh_csv: bool = False) -> tuple[list[str], str]:
    """Return (tickers, source). Wikipedia first; fall back to the committed CSV.

    If refresh_csv and Wikipedia succeeds, rewrite the CSV (the manual/scheduled
    refresh path). Returns the source used ('wikipedia' or 'csv') for logging.
    """
    try:
        syms = fetch_sp500_wikipedia()
        if refresh_csv:
            pd.DataFrame({"symbol": syms}).to_csv(csv_path, index=False)
        return syms, "wikipedia"
    except Exception as e:
        syms = load_sp500_csv(csv_path)
        return syms, f"csv (wikipedia failed: {type(e).__name__})"

# Requirements & Decisions

## R1 — Live universe: dynamic S&P 500 (Wikipedia + CSV fallback)

**Decision (2026-06-18):** The live/forward strategy trades a dynamic S&P 500
universe, not the fixed 30-name starter pool.

**Source of truth:** `data/sp500.csv` (committed to the repo).

**Resolution order at run time:**
1. Try to scrape the current S&P 500 list from Wikipedia
   (`List of S&P 500 companies`).
2. On any failure (network, table-format change, parse error) → fall back to
   `data/sp500.csv`.
3. Cross-validate tickers against Alpaca's tradable asset list; drop/normalize
   any that don't match (handles `BRK.B`-style class shares).

**Update cadence for `data/sp500.csv`:** monthly (or sooner on a major S&P 500
rebalance announcement). Manual or scripted.

**Rationale:** for a monthly-rebalanced, momentum-top-10 strategy, constituent
freshness is a second-order concern (S&P 500 changes ~20-25 names/year, and the
names entering/leaving are at the index margin — essentially never the momentum
top-10). Live order **stability** matters more than minute-level membership
accuracy, so a committed CSV is the trading source of truth and Wikipedia is a
best-effort refresh.

**Why this universe (vs the fixed 30):** the original QC strategy screened the
full market by dollar volume (top-100) — a broad, liquid, common-stock universe.
The fixed 30 collapsed breadth and tilted to correlated mega-caps. S&P 500 is the
clean, free, common-stock approximation of that intent (no ETF/leveraged-ETF
contamination, which Alpaca's raw asset list cannot filter out).

**Data:** Alpaca free (IEX) — verified complete for the trailing ~1 year
(275/275 bars in test), which is all the live 252-day momentum lookback needs.
Alpaca multi-symbol requests avoid Tiingo's 50-req/hour limit.

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

---

# Strategy decisions (meeting, 2026-06-18)

Each item discussed one at a time; recorded here once agreed. Implementation is
batched at the end (not as-we-go).

## D1 — Concentration / vol-target: ACCEPT, no change

The vol-target may deploy only ~24% of capital when the selected basket is high-vol
(today: a ~62% annualized semis basket → exposure = 0.15/0.62 ≈ 24%, rest cash), and
momentum may concentrate the 10 names in a single theme.

**Decision:** accept as-is, observe in paper first. No `target_vol` change, no sector
cap, no min-exposure floor.

**Rationale:** the vol-target is working as designed (high-vol basket → low exposure
is correct risk control); forcing diversification fights the momentum factor (its edge
partly comes from riding the hot theme); there is no evidence yet that this behavior is
bad — paper trading is the way to gather it. The deployed % is recomputed every
rebalance from that month's basket vol, so it self-adjusts (calmer months invest more).

## D2 — Absolute-momentum filter: ADD

Add a dual-momentum gate: after ranking and taking the top names by score (mom/vol),
**only hold names whose 12-1 momentum `mom` is positive (> 0)**. Names that don't
qualify are dropped → held as cash. So in a bear market the strategy can hold fewer
than `top_n` (or nothing), de-risking automatically.

**Open micro-detail (confirm at implementation):** threshold on raw `mom > 0`
(standard time-series / dual momentum — default) vs on the risk-adjusted score. Default
to raw `mom > 0`.

**Rationale:** the current strategy is pure cross-sectional (relative) momentum — in a
downturn it still buys the "least bad" losers and rides them down. The vol-target only
reacts to volatility, not direction (a low-vol grinding bear barely trips it). Absolute
momentum is the directional defense; the two are complementary. Cheap (a few lines).

## D3 — Regime filter (e.g., SPY < 200-day MA → de-risk): NO CHANGE for now

Deferred. May revisit later; D2 already provides directional defense.

## D4 — Universe params (`screen_top=100`, `top_n=10`): APPROVED

Keep the defaults: dollar-volume screen to top-100, then hold the momentum top-10.

## D5 — Backtest transaction-cost model: NO CHANGE

Live costs are real and shown by Alpaca automatically (commission-free US equities;
only the spread, baked into fills). A cost model only affects the *backtest* simulation
(our own report), not live. Current 5bps slippage / 0 commission is a fine approximation
for now; revisit when doing serious backtest evaluation.

## D6 — Backtest survivorship-free universe (Stooq/paid): NO CHANGE

Deferred (phase 1.5). Only relevant to backtesting full-market history; the live forward
system is unaffected.

---

## Implementation scope (this round)

Of D1–D6, only **D2** changes code. Everything else is "no change." D2 also requires the
"all-cash" path to actually sell: when no name passes the absolute-momentum gate, the
strategy must close positions and hold cash (not silently keep what it had). Applies to
both the backtest (`clean_momentum.py`) and live (`live/rebalance.py`), guarding against
liquidating on a *data failure* (empty price data → abort, do not trade).



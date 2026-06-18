# QC reconciliation — validate the quantsys engine against QuantConnect

**Goal:** prove the quantsys event-driven engine computes correctly, by running
the *same strategy on the same fixed universe* in QuantConnect (a mature, trusted
engine) and comparing the two equity curves.

**Why lock the universe:** if quantsys used its fixed 30-name pool and QC used its
dynamic top-100, the curves would differ for two mixed reasons (different stocks
*and* possibly different engine mechanics) and you couldn't tell them apart. By
forcing QC to use the *identical* fixed universe + identical rules, the only
remaining variables are **data vendor** (QC data vs Tiingo) and **fill timing** —
both small. So any *large or structural* divergence = a quantsys engine bug.

## Steps

1. **Run the QC side.** Open [QuantConnect](https://www.quantconnect.com), create
   a new Python algorithm, paste `clean_momentum_fixed_qc.py`, and Backtest
   (2010-01-01 → 2024-12-31, $100k). It uses the same 30-name fixed universe as
   `quantsys/universe.csv`.

2. **Export QC's equity curve to CSV.** After the backtest, in the Results page
   open the **Equity** chart and use its menu to **export / download CSV** (or in
   a QC Research notebook: `qb.read_backtest(...)` then save the equity series).
   You need a CSV with a date column and an equity/value column. Save it, e.g.,
   `reconciliation/qc_equity.csv`.

3. **Run the comparison:**
   ```bash
   uv run python reconciliation/reconcile.py \
       --qc-csv reconciliation/qc_equity.csv \
       --provider tiingo --start 2010-01-01 --end 2024-12-31
   ```

## Reading the result

The tool normalizes both curves and reports:

- **daily-ret corr** — how tightly the two move together day to day. This is the
  key number. **≥ 0.95 = engine validated.**
- **final gap** — difference in total growth. A few % is normal (data vendor +
  timing); large = investigate.
- **tracking error** — annualized std of the daily return differences.
- **max divergence + date** — if there's a bug, this date tells you *when* the
  curves split; go read what your engine did on that rebalance.

### What differences are NORMAL (not bugs)

- **Data vendor:** QC's prices ≠ Tiingo's prices (different adjustment timing,
  different vendors). Small, pervasive, ~unbiased.
- **Fill timing:** quantsys decides on the month's first close and fills the next
  open; QC's `schedule.on(month_start, after_market_open+30)` fills that morning.
  ~1-day lag → tiny tracking error, not a bug.
- **set_holdings rounding** vs quantsys integer-share sizing.

### What signals a REAL bug

- corr < 0.90, or curves that diverge *and never reconverge* after a specific
  date → suspect: rebalance trigger, the 12-1 momentum window indices
  (`iloc[end]/iloc[0]`), fill timing, or portfolio accounting. Start at the
  max-divergence date.

## To make data identical (optional, advanced)

To remove the data-vendor variable entirely, export your Tiingo bars to CSV and
feed them to QC/LEAN as a custom data source — then both engines eat byte-for-byte
the same prices and should match almost exactly. Heavy LEAN plumbing; only worth
it if the curves diverge in a way you can't explain.

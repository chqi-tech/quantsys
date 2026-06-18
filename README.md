# quantsys

A small **event-driven backtesting framework** for US equities. Personal
learning + portfolio project. Built so the *same* `Strategy` code runs in
backtest / paper / live — you only swap the data feed and the execution handler.

Design doc: `~/.gstack/projects/Downloads/ash-unknown-design-20260617-165215.md`

## What it does (phase 1)

- **Event-driven core** — bars flow `DataHandler → Strategy → Portfolio → Execution`.
- **No look-ahead, by construction** — a strategy can only ever see the current
  and past bars; orders fill at the **next bar's open**, never the same bar's close.
- **Two strategies** — `buyhold` (engine bring-up + reconciliation oracle) and
  `momentum` (a faithful port of a QuantConnect 12-1 risk-adjusted, vol-targeted
  cross-sectional momentum strategy, run on a fixed universe).
- **One-page HTML report** — equity curve, drawdown, Sharpe/CAGR/MaxDD, yearly table.
- **Runs with no account** — a synthetic `SampleProvider` means `quantsys` works
  the instant you clone it. Plug in free Alpaca keys for real data.

## Quick start

```bash
# install the toolchain once (already done if you see this)
curl -LsSf https://astral.sh/uv/install.sh | sh

# run on synthetic data — no API key needed
uv run python -m quantsys.run --strategy momentum
uv run python -m quantsys.run --strategy buyhold

# tests (look-ahead guard, next-bar-open fill, buy&hold reconciliation)
uv run pytest -q
```

The report is written to `reports/report.html`.

## Real data (when you're ready)

1. Get free keys at https://alpaca.markets and copy `.env.example` → `.env`.
2. `uv run python -m quantsys.run --strategy momentum --provider alpaca --start 2014-01-01 --end 2024-01-01`

Data is parquet-cached under `data_cache/` (gitignored).

## Known limitation (read this)

Phase 1 uses a **fixed universe** (`universe.csv` = today's survivors), so results
carry **survivorship bias** and are *illustrative, not predictive*. The real
point-in-time, survivorship-bias-free universe (what QuantConnect's `coarse`
selection gives you for free) is deferred to phase 1.5 — see the design doc.

## Layout

```
quantsys/
  data/        DataProvider (Sample + Alpaca), parquet cache
  core/        events, data_handler, portfolio, execution, engine
  strategy/    base, buy_hold, clean_momentum
  report/      metrics, html report (pure-Python SVG)
  run.py       CLI
tests/         look-ahead + reconciliation guardrails
universe.csv   fixed pool (Option A)
```

## Roadmap

- Phase 1 (now): trustworthy backtest engine + report. ✅
- Phase 1.5: point-in-time survivorship-free universe (Norgate/Sharadar, or self-built).
- Phase 2: paper trading (Alpaca real-time IEX feed + paper execution handler).
- Phase 3: small-capital live (same code, broker execution handler).

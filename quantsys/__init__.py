"""quantsys — a small event-driven backtesting framework.

Design doc: ~/.gstack/projects/Downloads/ash-unknown-design-20260617-165215.md

Core promise: the SAME Strategy code runs in backtest / paper / live; you only
swap the DataHandler and ExecutionHandler. Look-ahead bias is prevented
structurally (the strategy only ever sees the current and past bars) and fills
happen at the NEXT bar's open.
"""

__version__ = "0.1.0"

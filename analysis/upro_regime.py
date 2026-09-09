"""Honest backtest of a widely-promoted SPY/UPRO regime-timing strategy.

Core idea (Gayed 2016 "Leverage for the Long Run"): hold 3x leverage while a
trend filter says bull, de-risk when it says bear. The promoter's twist: use QQQ's
200-day SMA as the bull/bear line (tech leads). His "bear = 70% win-rate swing"
is unspecified and the least credible part, so we replace it with the
specifiable, standard alternatives: bear -> cash, or bear -> SPY (1x).

We simulate UPRO from SPY (3x daily return, daily-compounded, minus cost drag)
so we can test THROUGH 2000-02 (dot-com) and 2008 (GFC) -- the two acid tests
the promoter's 2010/2017 start dates conveniently skip. Real UPRO only exists from
2009-06.

Honesty notes:
- ANNUAL_DRAG (ER + financing on the levered portion) is an ESTIMATE; real cost
  is rate-dependent and in high-rate years (2000-07, 2022+) is higher -> our
  UPRO is if anything OPTIMISTIC.
- No taxes/slippage on regime switches modeled -> also optimistic.
- Signal is shifted 1 day (no lookahead).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from quantsys.data.provider import TiingoProvider
from quantsys.run import ROOT, _load_dotenv

ANNUAL_DRAG = 0.025          # 3x cost estimate (ER ~0.91% + financing); label as estimate
LEV = 3.0
SMA = 200
START = "1999-01-01"
END = "2026-07-12"
OUT_DIR = Path(__file__).resolve().parent / "upro_report"


def cagr(equity: pd.Series) -> float:
    yrs = (equity.index[-1] - equity.index[0]).days / 365.25
    return (equity.iloc[-1] / equity.iloc[0]) ** (1 / yrs) - 1


def max_dd(equity: pd.Series) -> float:
    return (equity / equity.cummax() - 1).min()


def sharpe(r: pd.Series) -> float:
    return (r.mean() / r.std()) * np.sqrt(252) if r.std() else float("nan")


def metrics(r: pd.Series) -> dict:
    r = r.dropna()
    eq = (1 + r).cumprod()
    c, dd = cagr(eq), max_dd(eq)
    return {
        "CAGR": c, "MaxDD": dd, "Vol": r.std() * np.sqrt(252),
        "Sharpe": sharpe(r), "MAR": (c / abs(dd)) if dd else float("nan"),
        "TotalRet": eq.iloc[-1] / eq.iloc[0] - 1,
    }


def run_window(rets: pd.DataFrame, start: str, end: str, label: str) -> None:
    w = rets.loc[start:end]
    print(f"\n{'='*78}\n窗口 {label}  ({w.index[0].date()} → {w.index[-1].date()})\n{'='*78}")
    print(f"{'策略':<26}{'年化':>9}{'最大回撤':>11}{'年化波动':>10}{'Sharpe':>9}{'MAR':>7}{'累计':>11}")
    for col in w.columns:
        m = metrics(w[col])
        print(f"{col:<26}{m['CAGR']*100:>8.1f}%{m['MaxDD']*100:>10.1f}%{m['Vol']*100:>9.1f}%"
              f"{m['Sharpe']:>9.2f}{m['MAR']:>7.2f}{m['TotalRet']*100:>10.0f}%")


def per_year(rets: pd.DataFrame, cols: list[str]) -> None:
    print(f"\n{'-'*78}\n分年度收益(%)—— 看 2000/2001/2002/2008 谁活下来\n{'-'*78}")
    hdr = "年份 " + "".join(f"{c[:14]:>16}" for c in cols)
    print(hdr)
    for yr, g in rets.groupby(rets.index.year):
        row = f"{yr} "
        for c in cols:
            ann = (1 + g[c].dropna()).prod() - 1
            row += f"{ann*100:>15.1f}%"
        print(row)


def main() -> None:
    _load_dotenv(ROOT / ".env")
    print("拉取 SPY / QQQ 日线(Tiingo,自带缓存)...")
    data = TiingoProvider().get_history(["SPY", "QQQ"], START, END)
    spy = data["SPY"]["close"].sort_index()
    qqq = data["QQQ"]["close"].sort_index()
    print(f"  SPY {spy.index[0].date()}→{spy.index[-1].date()} ({len(spy)}) | "
          f"QQQ {qqq.index[0].date()}→{qqq.index[-1].date()} ({len(qqq)})")

    df = pd.DataFrame({"spy": spy, "qqq": qqq}).dropna()
    r_spy = df["spy"].pct_change()
    r_qqq = df["qqq"].pct_change()
    # simulated UPRO: 3x daily SPY, compounded, minus daily cost drag
    r_upro = LEV * r_spy - ANNUAL_DRAG / 252

    # regime: bull if QQQ > its 200d SMA (signal shifted 1 day -> no lookahead)
    bull = (df["qqq"] > df["qqq"].rolling(SMA).mean()).shift(1)

    rets = pd.DataFrame(index=df.index)
    rets["SPY (1x 持有)"] = r_spy
    rets["QQQ (1x 持有)"] = r_qqq
    rets["UPRO (3x 持有)"] = r_upro
    rets["Regime: 熊→现金"] = np.where(bull, r_upro, 0.0)
    rets["Regime: 熊→SPY"] = np.where(bull, r_upro, r_spy)
    rets = rets.iloc[1:]
    rets = rets.loc[rets.index >= "2000-01-01"]  # after 200d warmup from QQQ 1999 start

    run_window(rets, "2000-01-01", END, "2000–2026(含 dot-com + 2008 两次大考)")
    run_window(rets, "2010-01-01", END, "2010–2026(博主的窗口)")
    run_window(rets, "2017-01-01", END, "2017–2026(博主的另一个窗口)")
    per_year(rets, ["UPRO (3x 持有)", "Regime: 熊→现金", "Regime: 熊→SPY"])

    # equity + drawdown plot
    import matplotlib
    matplotlib.use("Agg")
    # CJK font — without this the Chinese titles render as tofu boxes (DejaVu has no CJK).
    matplotlib.rcParams["font.sans-serif"] = [
        "PingFang SC", "Heiti SC", "Hiragino Sans GB", "Arial Unicode MS",
        "Noto Sans CJK SC", "Microsoft YaHei", "DejaVu Sans",
    ]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt
    w = rets.loc["2000-01-01":]
    eq = (1 + w).cumprod()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), height_ratios=[2, 1])
    for c in eq.columns:
        ax1.plot(eq.index, eq[c], label=c, lw=1.3)
    ax1.set_yscale("log"); ax1.legend(loc="upper left", fontsize=9)
    ax1.set_title("净值(对数轴)2000–2026 —— 诚实版:含 dot-com + 2008,模拟 UPRO 扣成本")
    for c in ["UPRO (3x 持有)", "Regime: 熊→现金", "Regime: 熊→SPY"]:
        d = eq[c] / eq[c].cummax() - 1
        ax2.plot(d.index, d * 100, label=c, lw=1.1)
    ax2.legend(loc="lower left", fontsize=9); ax2.set_ylabel("回撤 %")
    ax2.set_title("回撤对比")
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / "equity_drawdown.png"
    fig.tight_layout(); fig.savefig(out, dpi=130); plt.close(fig)
    print(f"\n图已存: {out}")
    print(f"\n[成本假设] 模拟 UPRO 用 3x 日收益 − {ANNUAL_DRAG*100:.1f}%/年 拖累(估计;真实含融资在高利率年份更高)。")


if __name__ == "__main__":
    # Tee stdout so the run both prints and persists a reproducible summary.txt
    # (mirrors what factor_ic.py does for its own report).
    import contextlib
    import io

    _buf = io.StringIO()

    class _Tee:
        def write(self, s):
            sys.__stdout__.write(s)
            _buf.write(s)

        def flush(self):
            sys.__stdout__.flush()

    with contextlib.redirect_stdout(_Tee()):
        main()

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "summary.txt").write_text(_buf.getvalue(), encoding="utf-8")
    print(f"结论已存: {OUT_DIR / 'summary.txt'}")

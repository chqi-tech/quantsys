"""One-page, self-contained HTML report (pure-Python inline SVG — no matplotlib).

Renders: headline metrics, an equity curve (with benchmark overlay), a drawdown
chart, and a per-year table. Always prints the survivorship-bias caveat, because
phase-1 uses a fixed (today's-survivors) universe.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import metrics as M


def _scale(vals, lo, hi, out_lo, out_hi):
    if hi == lo:
        return [(out_lo + out_hi) / 2 for _ in vals]
    return [out_lo + (v - lo) / (hi - lo) * (out_hi - out_lo) for v in vals]


def _line_chart(series: dict[str, pd.Series], w=820, h=300, pad=44) -> str:
    all_vals = pd.concat(list(series.values()))
    lo, hi = float(all_vals.min()), float(all_vals.max())
    n = max(len(next(iter(series.values()))), 2)
    xs = _scale(range(n), 0, n - 1, pad, w - 10)
    colors = ["#185FA5", "#888780", "#1D9E75"]
    paths = []
    for i, (name, s) in enumerate(series.items()):
        ys = _scale(list(s.values), lo, hi, h - pad, 10)
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
        c = colors[i % len(colors)]
        paths.append(f'<polyline fill="none" stroke="{c}" stroke-width="1.5" points="{pts}"/>')
        paths.append(
            f'<rect x="{pad + i*150}" y="{h-22}" width="11" height="11" fill="{c}"/>'
            f'<text x="{pad + i*150 + 16}" y="{h-12}" font-size="12" fill="#444">{name}</text>'
        )
    # y axis labels
    ylabs = []
    for frac in (0, 0.5, 1.0):
        val = lo + (hi - lo) * frac
        y = h - pad - frac * (h - pad - 10)
        ylabs.append(f'<text x="4" y="{y+4:.0f}" font-size="11" fill="#888">{val:,.0f}</text>')
        ylabs.append(f'<line x1="{pad}" y1="{y:.0f}" x2="{w-10}" y2="{y:.0f}" stroke="#eee"/>')
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px">'
        + "".join(ylabs) + "".join(paths) + "</svg>"
    )


def _drawdown_chart(dd: pd.Series, w=820, h=160, pad=44) -> str:
    n = max(len(dd), 2)
    xs = _scale(range(n), 0, n - 1, pad, w - 10)
    lo = float(dd.min())
    ys = _scale(list(dd.values), lo, 0.0, h - 20, 10)
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    base = h - 20
    area = f"{xs[0]:.1f},{base:.1f} " + pts + f" {xs[-1]:.1f},{base:.1f}"
    lab = f'<text x="4" y="20" font-size="11" fill="#888">{lo*100:,.1f}%</text>'
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px">'
        f'<polygon fill="#E24B4A22" stroke="none" points="{area}"/>'
        f'<polyline fill="none" stroke="#A32D2D" stroke-width="1.3" points="{pts}"/>'
        f"{lab}</svg>"
    )


def _metric_card(label, value) -> str:
    return (
        '<div style="background:#f6f5f1;border-radius:8px;padding:12px 16px;min-width:120px">'
        f'<div style="font-size:12px;color:#777">{label}</div>'
        f'<div style="font-size:22px;font-weight:500;color:#222">{value}</div></div>'
    )


def write_html_report(result, out_path: str | Path, note: str = "") -> Path:
    equity = result.equity["equity"]
    s = M.summarize(equity)
    dd = M.drawdown_series(equity)
    yearly = M.yearly_returns(equity)

    series = {result.strategy_name: equity}
    if result.benchmark is not None:
        series[result.benchmark.name] = result.benchmark

    cards = "".join([
        _metric_card("Total return", f"{s['total_return']*100:,.1f}%"),
        _metric_card("CAGR", f"{s['cagr']*100:,.2f}%"),
        _metric_card("Sharpe (rf=0)", f"{s['sharpe']:,.2f}"),
        _metric_card("Annual vol", f"{s['annual_vol']*100:,.1f}%"),
        _metric_card("Max drawdown", f"{s['max_drawdown']*100:,.1f}%"),
        _metric_card("Fills", f"{result.n_fills:,}"),
    ])

    yrows = "".join(
        f'<tr><td style="padding:4px 14px 4px 0">{yr}</td>'
        f'<td style="text-align:right;color:{"#1D9E75" if v>=0 else "#A32D2D"}">{v*100:,.1f}%</td></tr>'
        for yr, v in yearly.items()
    )

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>quantsys report — {result.strategy_name}</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#222;max-width:880px;margin:32px auto;padding:0 16px;line-height:1.6}}
h1{{font-size:24px;font-weight:600;margin:0 0 2px}}
h2{{font-size:16px;font-weight:600;margin:28px 0 8px}}
.sub{{color:#777;font-size:14px;margin-bottom:18px}}
.cards{{display:flex;flex-wrap:wrap;gap:10px}}
.caveat{{background:#FAEEDA;border-left:3px solid #BA7517;padding:10px 14px;border-radius:0 8px 8px 0;font-size:13px;color:#633806;margin:18px 0}}
table{{font-size:13px;border-collapse:collapse}}
</style></head><body>
<h1>{result.strategy_name}</h1>
<div class="sub">{s['start']} → {s['end']} &nbsp;·&nbsp; 初始 ${s['initial']:,.0f} → 期末 ${s['final']:,.0f}</div>
<div class="cards">{cards}</div>
<div class="caveat"><b>结果仅为示意,非预测。</b> 阶段1 使用固定股票池(今天还存活的公司),带<b>幸存者偏差</b>,历史收益会被系统性高估。真正的 point-in-time 无幸存者偏差股票池见设计文档阶段1.5。{(' · ' + note) if note else ''}</div>
<h2>净值曲线</h2>
{_line_chart(series)}
<h2>回撤</h2>
{_drawdown_chart(dd)}
<h2>分年收益</h2>
<table>{yrows}</table>
<p style="color:#aaa;font-size:12px;margin-top:28px">Generated by quantsys · Sharpe rf=0/252 · CAGR 几何 · 成交 next-bar-open</p>
</body></html>"""

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out

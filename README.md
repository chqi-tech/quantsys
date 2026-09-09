# quantsys

**一套从零构建的事件驱动美股回测 / 纸面交易系统 —— 以及一次对自己策略的严格证伪。**

> A hand-built event-driven backtesting & paper-trading system for US equities,
> and an honest, rigorous falsification of the strategy it was built to test.

![Python](https://img.shields.io/badge/Python-3.14-3776AB)
![Tests](https://img.shields.io/badge/tests-8%2F8%20passing-2f6f5f)
![Engine](https://img.shields.io/badge/engine-event--driven-16233a)
![No look-ahead](https://img.shields.io/badge/no%20look--ahead-by%20construction-16233a)
![Paper only](https://img.shields.io/badge/trading-PAPER%20only%20·%20no%20real%20money-b23b3b)

> **⚠️ 交易性质声明:本项目全程使用 Alpaca 纸面账户(paper trading),从未投入任何真实资金,
> 也从未进行过真实委托。** 所有"交易"均为模拟撮合,所有收益数字均来自回测或纸面模拟。

---

## 这个项目最重要的一句话

我从零构建了一套事件驱动回测系统,忠实实现并**严格评估**了一个横截面动量策略。
在**可信的回测**下(QuantConnect,2008–2026,无幸存者偏差),它对 SPY **没有可靠超额**
(信息比率 IR ≈ 0)。我据此**停用了它**,并定位了根因:波动率目标 + 绝对动量过滤把
组合 Beta 压到 0.55,一半资金常年趴在现金里,拖累了收益却没换来更高的夏普。

**所以这个项目展示的不是"一个赚钱的策略",而是量化研究里最稀缺的东西 —— 工程纪律、
引擎正确性的自我验证,以及拿证据否定自己想法的诚实。** 这恰好是量化研究员日常工作的
微缩版:大部分时间是在严谨地**证伪**假设,而不是庆祝一条过拟合的漂亮曲线。

---

## 为什么这个项目值得看(3 个差异点)

1. **防前视是结构性的,不是靠自觉。** 策略在任何时刻只能看到当前及过去的 bar;订单在
   **次日开盘**成交,永远不是当日收盘。这一点由**单元测试**守卫(见下),连"故意作弊
   的策略"都够不到未来数据。这是把大多数学生回测拉垮的头号陷阱(前视 / 幸存者偏差)。

2. **引擎正确性经过外部对账。** 我写了一套对账流程,把**同一策略、同一固定universe**
   同时跑在 quantsys 和成熟引擎 QuantConnect 上,比对两条净值曲线(判据:日收益相关性
   ≥ 0.95)。这保证"结果可信"不是自说自话。

3. **同一套策略代码贯穿 回测 → Alpaca 纸面交易。** `momentum_logic.py` 是唯一的"大脑",
   回测引擎和 Alpaca 纸面下单都调它;只替换数据源与执行层。这是研究到生产之间那条鸿沟
   的正确处理方式。

---

## 系统架构

```
                  bars flow →
  DataHandler ──▶ Strategy ──▶ Portfolio ──▶ Execution
   (行情)         (信号,唯一大脑)  (账户/仓位)   (次日开盘成交)

  quantsys/
    core/       事件、data_handler、portfolio、execution、engine
    strategy/   base / buy_hold / momentum_logic(共享大脑)/ clean_momentum(回测封装)
    data/       DataProvider(Sample 合成 + Tiingo + Alpaca)、parquet 缓存、S&P 500 选池
    report/     指标 + 纯 Python SVG 的一页 HTML 报告
    run.py      回测 CLI
  live/         rebalance.py —— Alpaca 纸面月度调仓
  reconciliation/  与 QuantConnect 对账,证明引擎算得对
  tests/        前视守卫 + 引擎对账 + 策略逻辑
```

**无账户也能跑**:内置合成数据 `SampleProvider`,`clone` 下来即可运行,插上免费的
Alpaca / Tiingo key 才用真实行情。

---

## 策略是什么

```
动态 S&P 500 池 → 成交额 top-100 粗筛 → 12-1 风险调整动量打分 → 取 top-10
   → 绝对动量过滤(只买正动量,否则转现金) → 波动率目标(15%)→ 等权 → 月度调仓
```

- **12-1 风险调整动量**:`score = 过去 12 个月(跳过最近 1 个月)收益 / 年化波动`。
- **绝对动量过滤(D2)**:top-10 里只保留 `mom > 0` 的名字,全负时**清仓持现金**,
  熊市自动降险。
- **波动率目标**:把等权组合近期波动缩放到 15% —— 高波动的篮子自动降低仓位。

参数:`lookback=252, skip=21, top_n=10, target_vol=0.15, vol_window=60, screen_top=100`。

---

## 结果(可信回测:QuantConnect,2008–2026,无幸存者偏差)

| 指标 | 策略 | 说明 |
|---|---:|---|
| 累计收益 | ~+591% | 略高于 SPY 的 ~+500% |
| 年化收益 (CAGR) | 11.33% | |
| 夏普 (Sharpe) | 0.50 | ≈ 大盘水平 |
| 最大回撤 | 29.6% | 含 2008;策略无回撤上限 |
| 年化波动 | 13.5% | |
| **Beta** | **0.55** | ← 病根:一半仓位常年现金 |
| Alpha | 2.9% | |
| **信息比率 (IR)** | **−0.017** | ← 对 SPY **没有可靠超额** |
| PSR | 2.6% | 夏普显著性极低 |

**一句话结论:本质是"≈ 大盘收益、约一半风险",而不是"跑赢大盘"。**

> ⚠️ 注:仓库内**回测引擎**默认用固定 30 只 universe,带幸存者偏差,仅供引擎打通/对账,
> **不可用于评估策略好坏**。上表的可信数字来自把真实策略跑在 QuantConnect 上
> (`reconciliation/clean_momentum_dynamic_qc.py`)。诚实区分"引擎跑得对"和"策略值不值",
> 是这个项目刻意保留的一条底线。

### 根因分析(为什么我停用它)

- **收益与回撤天生打架**:要收益得多投,要少回撤得少投。波动率目标 + D2 让它平均只投一半
  (Beta 0.55),于是收益被压、夏普没提升 —— 大盘股动量的 edge 本就很薄。
- 29.6% 的回撤主要来自 2008 与方向防御的滞后;`target_vol` 是**波动目标**,不是**回撤上限**。
- 结论:在不引入更强 alpha 来源的前提下,继续调这套 momentum 是投入产出最低的方向。**故停用,
  转向更广的策略家族学习。** 这个决定本身就是结果的一部分。

---

## 因子层面的独立验证:两条互不依赖的证据

上面"现金拖累"是**组合层面**的解释。为了不让结论悬在单一回测上,我又用 Alphalens
从**因子层面**独立查了一次([`analysis/factor_ic.py`](analysis/factor_ic.py)):把纸面交易与回测
共用的那个大脑(`momentum_scores`)拿出来,不建策略、不交易,只问 ——
**按这个因子排序,能不能把未来的赢家和输家分开?**

| 预测周期 | 平均 IC | ICIR | t 值 | 胜率 |
|---|---:|---:|---:|---:|
| 1 天 | 0.0204 | 0.07 | 4.46 | 53.6% |
| 5 天 | 0.0230 | 0.08 | 5.05 | 54.8% |
| 21 天 | 0.0168 | 0.06 | 3.90 | 53.2% |

- **t 值 3.9–5.0 → 不是运气**,因子确实携带信息。
- **但 IC 仅 0.017–0.023**(低于"还行"的经验区间 0.03–0.05)、**ICIR 0.06–0.08**、**胜率 53%**。
- 分位收益**不单调**:只有最高动量的第 5 分位为正(+8.7 bps / 21 天),1–4 分位为负且乱序 ——
  **预测力只存在于最顶部那一档**。

**结论:因子统计上真实,经济上极弱。** 这从一个完全独立的角度印证了组合层面的 IR ≈ 0:
不是仓位管理没调好,而是**这个 alpha 源本身就太薄**。交叉验证后的结论,比单一回测结果有力得多。

详见 [`analysis/README.md`](analysis/README.md)。

---

## 另一项独立研究:杠杆择时策略的诚实复现

[`analysis/upro_regime.py`](analysis/upro_regime.py) —— 对某财经博主推广的 SPY/UPRO 杠杆择时
(内核 Gayed 2016)的复现。我做了两件让它**可被证伪**的事:用 SPY 按 3 倍日收益复利扣成本
**模拟 UPRO**,把窗口拉回真实 UPRO 尚未存在的 **2000 年**(测穿 dot-com 与 2008 —— 博主的
2010/2017 起点恰好绕开);并把"胜率 70% 的波段"这类**无法证伪的表述**换成明确定义的
「熊→现金」「熊→SPY」。

| 窗口 | 3x 裸持年化 | 最大回撤 |
|---|---:|---:|
| 2010–2026(博主窗口) | 32.8% | −76.2% |
| **2000–2026(含两次崩盘)** | **10.7%** | **−97.1%** |

**最锋利的反证:在博主自己的 2010–2026 窗口里,不做择时(32.8%)反而跑赢做择时(26.3%)**
—— 他展示的窗口恰好是最不需要那套择时的窗口。而在完整样本里关系反转(16.2% vs 10.7%),
说明**择时的全部价值来自避开 2000 和 2008**,一个在他窗口里无法被观察到的价值。

---

## 决策记录(节选,完整见 [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md))

每个决策**先开会逐点讨论、记录,再统一实现**(不边做边改),留痕如下:

| # | 议题 | 决定 |
|---|---|---|
| D1 | 集中度 / 波动率目标 | 接受不改,先在纸面观察 |
| D2 | 绝对动量过滤 | **加**(方向性防御) |
| D3 | 择时过滤(SPY < 200 日线) | 暂不加(D2 已提供方向防御) |
| D4 | universe 参数(top-100 / top-10) | 保留 |
| D5 | 回测费用模型 | 不改(纸面成交价已含点差,Alpaca 直接反映) |
| D6 | 回测无幸存者偏差池 | 推迟到 phase 1.5 |

---

## 工程亮点:8 个测试守住底线

```
tests/test_lookahead.py
  ✓ latest_bars 永不返回未来的 bar
  ✓ 故意作弊的策略也够不到未来数据
  ✓ 成交发生在"次日开盘",不是当日收盘
tests/test_engine.py
  ✓ buy&hold 与手算净值精确对账(引擎正确性 oracle)
  ✓ 指标口径(Sharpe/CAGR/MaxDD)符合约定
tests/test_momentum_logic.py
  ✓ 绝对动量过滤能剔除负动量
  ✓ 全部负动量 → 清仓持现金
  ✓ 全部正动量 → 全持
```

---

## 怎么跑

```bash
# 一次性装工具链(uv)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 合成数据回测,无需任何 API key(秒级)
uv run python -m quantsys.run --strategy momentum
uv run python -m quantsys.run --strategy buyhold

# 全部测试(前视 / 对账 / 策略逻辑)
uv run pytest -q

# 纸面交易 dry-run(只打印计划,不下单)
uv run python live/rebalance.py --universe-mode sp500
```

报告写到 `reports/report.html`。真实行情:在 https://alpaca.markets 拿免费 key,
`.env.example` → `.env` 即可。

---

## 诚实的边界(这个作品**不**声称什么)

- **不是**一个盈利策略,也**不**证明我能找到 alpha(没有人指望一个学习项目做到)。
- 纯 Alpaca **纸面**账户,无真钱;单策略、单资产类别。
- 仓库内引擎回测带幸存者偏差(已知,phase 1.5 处理);可信评估用的是 QuantConnect。

把"我如何严谨地证伪了它"当作卖点,而不是把一条曲线包装成战绩 —— 这是本项目的立场。

---

## 技术栈

Python · uv · pandas / numpy · Tiingo(信号)· Alpaca(纸面执行 + 数据)·
pandas-market-calendars · QuantConnect(外部对账)· 纯 Python SVG 报告(零前端依赖)

## Roadmap

- **Phase 1(已完成)** ✅ 可信的事件驱动回测引擎 + 报告 + 纸面交易
- **Phase 1.5** 无幸存者偏差的 point-in-time universe(引擎侧回测也可信)
- **下一步** 跳出单一 momentum,系统性学习并评估更多策略家族(多因子 / 择时 / 相对价值)

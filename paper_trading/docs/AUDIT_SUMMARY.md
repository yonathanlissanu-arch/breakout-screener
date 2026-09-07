# Audit: C1-Slope-3.5 & LongRunner-2D (uploaded frozen script)

## What was uploaded
`C1_SLOPE_AND_LONGRUNNER2D_FROZEN.py` — two VWAP-residual mean-reversion
signal generators on the same SPY 5-min dataset used in prior sessions:
- **C1-Slope-3.5**: fade |z-score of price vs VWAP| >= 1.5, filtered by a VWAP
  slope condition, hold fixed 35 bars (~3 hours), max 1 trade/day, flat same day.
- **LongRunner-2D**: take the day's first z-score event; if it's an oversold
  (long) signal, enter next bar, hold through the close of the *second*
  subsequent trading session (~3 calendar days, including overnight/weekend).

Script ran as-is and reproduced the reported numbers exactly: C1-Slope
$11,082.97 / LongRunner-2D $23,714.34 on a stated $100k per signal.

## The core issue found
Both numbers are a **sum of `net_return x $100k` across all signals**, treating
every signal as an independent $100k allocation. That's valid for C1-Slope
(never more than 1 open trade). It is NOT valid for LongRunner-2D: with a
~3-day hold, **80 of 114 signals (70%) overlap a still-open prior trade**, and
up to **3 positions were open simultaneously**. The reported $23,714 implicitly
assumes up to $300k deployed on a $100k account at times — leverage disguised
as a clean per-signal sum.

## Honest, single-account re-backtest
Enforced max 1 concurrent position (new LongRunner-2D signals are skipped
while capital is tied up in a prior trade) → 114 raw signals become 64
tradeable trades. Full 252-day period, same cost assumption (2bp round trip):

| Strategy | CAGR | Sharpe | Max Drawdown |
|---|---|---|---|
| C1-Slope-3.5 | 11.5% | 1.82 | -3.2% |
| **LongRunner-2D (capital-constrained)** | **19.6%** | **1.66** | -7.2% |
| SPY Buy & Hold | 18.2% | 1.38 | -9.1% |

LongRunner-2D modestly beats SPY on return and more clearly on risk-adjusted
terms once the phantom leverage is removed. C1-Slope underperforms on raw
return but carries much less risk (flat/in-cash most of the time).

## Split by the same discovery (Sep'25-May'26) / test (May-Sep'26) cutoff used previously

| | Discovery CAGR | Test/OOS CAGR | Test/OOS Sharpe | Test trades |
|---|---|---|---|---|
| LongRunner-2D | 17.0% | **25.8%** | **2.26** | 19 |
| C1-Slope-3.5 | 9.3% | 14.4% | 2.58 | 72 |
| SPY Buy&Hold | 20.8% | 17.4% | 1.32 | — |

LongRunner-2D's edge held (and strengthened) in the untouched, more recent
period — encouraging, but built on only 19 out-of-sample trades.

## Caveats before trusting this
1. **LongRunner-2D is a multi-day swing strategy, not a day-trading strategy**
   — it holds through at least one overnight and often a weekend. Part of its
   edge may be capturing the well-documented overnight/weekend equity drift
   that a flat-by-close day-trading strategy structurally cannot access. That
   makes it a different (and reasonable) thing to trade, just not what "day
   trading" usually implies.
2. **Small sample.** 19-64 trades is thin for Sharpe/CAGR to be statistically
   reliable; a few bad trades would move these numbers a lot.
3. **Unknown provenance of the fixed parameters** (Z=1.5, slope floor=-3.5bp,
   35-bar hold, 2-session exit). If they were chosen using knowledge of this
   exact dataset, the "discovery" period numbers are still in-sample despite
   the temporal split. If they came from research done before this data
   existed, the full 252-day run is a genuine blind test. This matters a lot
   for how much to trust the result and should be confirmed before sizing
   any real capital to it.

## Files
- `honest_rebacktest.py` — capital-constrained re-backtest (fixes the overlap/leverage issue)
- `honest_full_period_results.csv`, `honest_split_results.csv` — full numeric output
- `honest_equity_curves.csv` — daily equity curves, all strategies vs SPY, full period

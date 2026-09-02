#!/usr/bin/env python3
"""
backtest_stringent_extended.py — Extended historical backtest of the stringent
triple-bottom scanner across three additional randomly-selected years.

Years selected: 2013, 2016, 2023
(seed=99, pool=2010-2023 excluding 2019 and 2024 which were already backtested)

Market regimes covered:
  2013 — Taper tantrum, strong bull (SPY +32%)
  2016 — Brexit + Trump rally (SPY +12%)
  2023 — AI-rally recovery (SPY +26%)

Along with the existing 2019 / 2024 runs this gives 5 years spanning:
  post-GFC bull, political shock/recovery, COVID aftermath bull, and
  a mild-correction bull — broad regime coverage.

Data: HISTORY_YEARS=18 (downloads from ~2008 onward) so 2013 cohorts
have ≥5 years of prior history for triple-bottom pattern detection.

Output
------
  results/backtest_extended_2013_detail.csv
  results/backtest_extended_2013_summary.csv
  (same for 2016, 2023)
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────
BACKTEST_CONFIGS = [
    {
        "year": 2013,
        "year_end": date(2013, 12, 31),
        "cohort_dates": [
            date(2013,  1,  2),   # Jan 1 = holiday
            date(2013,  2,  1),
            date(2013,  3,  1),
            date(2013,  4,  1),
            date(2013,  5,  1),
            date(2013,  6,  3),   # Jun 1 = Sat
            date(2013,  7,  1),
            date(2013,  8,  1),
            date(2013,  9,  3),   # Sep 2 = Labor Day
            date(2013, 10,  1),
            date(2013, 11,  1),
            date(2013, 12,  2),   # Dec 1 = Sun
        ],
    },
    {
        "year": 2016,
        "year_end": date(2016, 12, 31),
        "cohort_dates": [
            date(2016,  1,  4),   # Jan 1 = Fri holiday → Jan 4 (Mon)
            date(2016,  2,  1),
            date(2016,  3,  1),
            date(2016,  4,  4),   # Apr 1 = Good Friday (NYSE closed)
            date(2016,  5,  2),   # May 1 = Sun
            date(2016,  6,  1),
            date(2016,  7,  1),   # Fri, open (Jul 4 = Mon)
            date(2016,  8,  1),
            date(2016,  9,  1),   # Thu (Labor Day = Sep 5)
            date(2016, 10,  3),   # Oct 1 = Sat
            date(2016, 11,  1),
            date(2016, 12,  1),
        ],
    },
    {
        "year": 2023,
        "year_end": date(2023, 12, 31),
        "cohort_dates": [
            date(2023,  1,  3),   # Jan 1 = Sun, Jan 2 = New Years observed (closed)
            date(2023,  2,  1),
            date(2023,  3,  1),
            date(2023,  4,  3),   # Apr 1 = Sat; Good Friday = Apr 7, so Apr 3 (Mon) is open
            date(2023,  5,  1),
            date(2023,  6,  1),
            date(2023,  7,  3),   # Jul 1 = Sat → Jul 3 (Mon) open (Jul 4 = Tue holiday)
            date(2023,  8,  1),
            date(2023,  9,  1),   # Fri (Labor Day = Sep 4)
            date(2023, 10,  2),   # Oct 1 = Sun
            date(2023, 11,  1),
            date(2023, 12,  1),
        ],
    },
]

FORWARD_WINDOWS = {"1m": 21, "100d": 100, "3m": 63, "6m": 126}
TOP_N           = 7
SPY_TICKER      = "SPY"
RESULTS_DIR     = Path("results")
HISTORY_YEARS   = 18   # ~2008 → sufficient prior data for 2013 cohorts
BACKTEST_CACHE  = "data/backtest_extended_cache"

MIN_PCT_ABOVE_200SMA   = 20.0
MIN_VOLUME_RATIO       = 3.5
MIN_PCT_ABOVE_NECKLINE = 5.0


# ── Helpers (identical to backtest_stringent.py) ────────────────────────────

def _price_at(df: pd.DataFrame, target: date, direction: str = "on_or_before") -> Optional[float]:
    if direction == "on_or_before":
        ts = pd.Timestamp(target) + pd.Timedelta(hours=23, minutes=59)
        sub = df[df.index <= ts]
        return float(sub["Close"].iloc[-1]) if not sub.empty else None
    else:
        ts = pd.Timestamp(target)
        sub = df[df.index >= ts]
        return float(sub["Close"].iloc[0]) if not sub.empty else None


def _price_after_n_days(df: pd.DataFrame, as_of: date, n_trading_days: int) -> Optional[float]:
    ts = pd.Timestamp(as_of) + pd.Timedelta(hours=23, minutes=59)
    future = df[df.index > ts]["Close"].dropna()
    if future.empty:
        return None
    idx = min(n_trading_days - 1, len(future) - 1)
    return float(future.iloc[idx])


def _pct_return(entry: Optional[float], exit_: Optional[float]) -> Optional[float]:
    if entry is None or exit_ is None or entry == 0:
        return None
    return round((exit_ - entry) / entry * 100, 2)


def _passes_hard_gates(row: dict) -> bool:
    return (
        row.get("pattern_type") == "triple_bottom_breakout"
        and (row.get("pct_above_200sma") or 0) >= MIN_PCT_ABOVE_200SMA
        and (row.get("volume_ratio") or 0) >= MIN_VOLUME_RATIO
        and (row.get("pct_above_neckline") or 0) > MIN_PCT_ABOVE_NECKLINE
    )


def _stringent_score(row) -> float:
    get = row.get if hasattr(row, 'get') else lambda k: row[k]
    trend = min((get("pct_above_200sma") or 0) / 100, 1.0)
    vol   = min((get("volume_ratio") or 0) / 15, 1.0)
    neck  = min((get("pct_above_neckline") or 0) / 30, 1.0)
    tight = max(0.0, 1.0 - (get("bottom_variation_pct") or 5) / 10)
    return 0.50 * trend + 0.25 * vol + 0.15 * neck + 0.10 * tight


# ── Scan at a point in time ──────────────────────────────────────────────────

def scan_at_date(
    price_data_full: Dict[str, pd.DataFrame],
    universe: pd.DataFrame,
    as_of: date,
    top_n: int = TOP_N,
) -> pd.DataFrame:
    from indicators import analyse_ticker_triple_bottom

    ts_eod = pd.Timestamp(as_of) + pd.Timedelta(hours=23, minutes=59)
    candidates: List[dict] = []
    rejected = 0

    for ticker, df_full in tqdm(
        price_data_full.items(), desc=f"Scanning {as_of}", unit="ticker", leave=False
    ):
        df_slice = df_full[df_full.index <= ts_eod].copy()
        if len(df_slice) < 120:
            continue
        row = analyse_ticker_triple_bottom(ticker, df_slice)
        if row is None:
            continue
        if not _passes_hard_gates(row):
            rejected += 1
            continue
        candidates.append(row)

    if not candidates:
        logger.warning("No candidates passed gates for %s", as_of)
        return pd.DataFrame()

    df_res = pd.DataFrame(candidates)
    meta = universe[["ticker", "name", "indices", "region"]].copy()
    df_res = df_res.merge(meta, on="ticker", how="left")
    df_res["indices"] = df_res["indices"].fillna("Unknown")
    df_res["region"]  = df_res["region"].fillna("Unknown")
    df_res["score"] = df_res.apply(lambda r: _stringent_score(r), axis=1)
    df_res = df_res.sort_values("score", ascending=False).reset_index(drop=True)
    df_res.insert(0, "rank", df_res.index + 1)

    logger.info(
        "%s: %d passed gates (%d rejected)", as_of, len(candidates), rejected
    )
    return df_res.head(top_n)


# ── Forward returns ──────────────────────────────────────────────────────────

def compute_forward_returns(
    cohort_df: pd.DataFrame,
    price_data_full: Dict[str, pd.DataFrame],
    spy_df: pd.DataFrame,
    as_of: date,
    year_end: date,
) -> pd.DataFrame:
    spy_entry = _price_at(spy_df, as_of, "on_or_before")
    rows = []

    for _, row in cohort_df.iterrows():
        ticker = row["ticker"]
        df_full = price_data_full.get(ticker)
        rec = row.to_dict()
        rec["cohort_date"] = str(as_of)
        rec["entry_price"] = _price_at(df_full, as_of, "on_or_before") if df_full is not None else None

        for label, n_days in FORWARD_WINDOWS.items():
            exit_px  = _price_after_n_days(df_full, as_of, n_days) if df_full is not None else None
            spy_exit = _price_after_n_days(spy_df, as_of, n_days)
            stock_ret = _pct_return(rec["entry_price"], exit_px)
            spy_ret   = _pct_return(spy_entry, spy_exit)
            rec[f"price_{label}"]      = exit_px
            rec[f"return_{label}"]     = stock_ret
            rec[f"spy_return_{label}"] = spy_ret
            rec[f"alpha_{label}"]      = (
                round(stock_ret - spy_ret, 2)
                if stock_ret is not None and spy_ret is not None else None
            )

        ye_exit  = _price_at(df_full, year_end, "on_or_before") if df_full is not None else None
        spy_ye   = _price_at(spy_df, year_end, "on_or_before")
        ye_ret   = _pct_return(rec["entry_price"], ye_exit)
        spy_ye_r = _pct_return(spy_entry, spy_ye)
        rec["price_yearend"]      = ye_exit
        rec["return_yearend"]     = ye_ret
        rec["spy_return_yearend"] = spy_ye_r
        rec["alpha_yearend"]      = (
            round(ye_ret - spy_ye_r, 2)
            if ye_ret is not None and spy_ye_r is not None else None
        )
        rows.append(rec)

    return pd.DataFrame(rows)


# ── Summary ──────────────────────────────────────────────────────────────────

def summarise_cohorts(detail_df: pd.DataFrame) -> pd.DataFrame:
    summaries = []
    for cohort_date, grp in detail_df.groupby("cohort_date"):
        rec: dict = {"cohort_date": cohort_date, "n_stocks": len(grp)}
        for label in list(FORWARD_WINDOWS.keys()) + ["yearend"]:
            valid   = grp[f"return_{label}"].dropna()
            spy_val = grp[f"spy_return_{label}"].dropna()
            port_r  = round(valid.mean(), 2) if not valid.empty else None
            spy_r   = round(spy_val.mean(), 2) if not spy_val.empty else None
            rec[f"portfolio_return_{label}"] = port_r
            rec[f"spy_return_{label}"]       = spy_r
            rec[f"alpha_{label}"]            = (
                round(port_r - spy_r, 2) if port_r is not None and spy_r is not None else None
            )
            rec[f"pct_winners_{label}"]      = (
                round((valid > 0).sum() / len(valid) * 100, 1) if not valid.empty else None
            )
        summaries.append(rec)
    return pd.DataFrame(summaries)


def print_summary(summary_df: pd.DataFrame, year: int) -> None:
    from tabulate import tabulate

    print(f"\n{'═'*100}")
    print(f"  STRINGENT TRIPLE-BOTTOM BACKTEST — {year}  (Equal-weight, Top {TOP_N} picks)")
    print(f"  Gates: 200SMA ≥ {MIN_PCT_ABOVE_200SMA}% · Vol ≥ {MIN_VOLUME_RATIO}× · Neckline > {MIN_PCT_ABOVE_NECKLINE}%")
    print(f"{'═'*100}")

    display_cols = [
        "cohort_date", "n_stocks",
        "portfolio_return_1m",  "spy_return_1m",  "alpha_1m",
        "portfolio_return_3m",  "spy_return_3m",  "alpha_3m",
        "portfolio_return_6m",  "spy_return_6m",  "alpha_6m",
        "portfolio_return_yearend", "spy_return_yearend", "alpha_yearend",
    ]
    display_cols = [c for c in display_cols if c in summary_df.columns]
    df_disp = summary_df[display_cols].copy()

    for col in df_disp.columns:
        if "return" in col or "alpha" in col:
            df_disp[col] = df_disp[col].apply(
                lambda v: f"{v:+.2f}%"
                if v is not None and not (isinstance(v, float) and np.isnan(v))
                else "—"
            )

    print(tabulate(df_disp, headers="keys", tablefmt="rounded_outline", showindex=False))


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    os.makedirs(BACKTEST_CACHE, exist_ok=True)

    logger.info("Step 1: Building universe …")
    from universe import build_universe
    universe = build_universe(
        sp500=True, midcap400=True, russell2000=False,
        euronext=False, stoxx600=True, wilshire2000=True,
    )
    logger.info("Universe: %d tickers", len(universe))

    logger.info("Step 2: Downloading %d years of daily prices …", HISTORY_YEARS)
    from fetcher_yahoo import fetch_price_data_yahoo
    all_tickers = universe["ticker"].tolist() + [SPY_TICKER]
    price_data_full = fetch_price_data_yahoo(
        all_tickers,
        history_years=HISTORY_YEARS,
        cache_dir=BACKTEST_CACHE,
    )

    spy_df = price_data_full.pop(SPY_TICKER, None)
    if spy_df is None or spy_df.empty:
        logger.error("Could not fetch SPY — aborting.")
        return
    logger.info("Price data ready: %d tickers + SPY", len(price_data_full))

    for config in BACKTEST_CONFIGS:
        year     = config["year"]
        year_end = config["year_end"]
        dates    = config["cohort_dates"]

        logger.info("\n%s\n  YEAR %d  (%d cohorts)\n%s", "="*60, year, len(dates), "="*60)
        all_detail_frames: List[pd.DataFrame] = []

        for as_of in dates:
            logger.info("── Cohort %s ──", as_of)
            cohort_df = scan_at_date(price_data_full, universe, as_of, top_n=TOP_N)
            if cohort_df.empty:
                logger.warning("No candidates for %s — skipping.", as_of)
                continue

            logger.info("Found %d picks — computing forward returns …", len(cohort_df))
            detail_df = compute_forward_returns(
                cohort_df, price_data_full, spy_df, as_of, year_end
            )
            all_detail_frames.append(detail_df)

            print(f"\n  Top picks for {as_of}:")
            for _, r in detail_df.iterrows():
                yr  = r.get("return_yearend")
                sp  = r.get("spy_return_yearend")
                al  = r.get("alpha_yearend")
                sma = r.get("pct_above_200sma", 0)
                vol = r.get("volume_ratio", 0)
                if yr is not None and sp is not None and al is not None:
                    print(
                        f"    {r['ticker']:6}  ${r['entry_price'] or 0:>8.2f}  "
                        f"200SMA={sma:.0f}%  vol={vol:.1f}×  "
                        f"yearend={yr:+.1f}%  SPY={sp:+.1f}%  α={al:+.1f}%"
                    )
                else:
                    print(f"    {r['ticker']:6}  ${r['entry_price'] or 0:>8.2f}  (forward data unavailable)")

        if not all_detail_frames:
            print(f"\nNo results for {year}.")
            continue

        detail_all = pd.concat(all_detail_frames, ignore_index=True)
        summary_df = summarise_cohorts(detail_all)

        detail_path  = RESULTS_DIR / f"backtest_extended_{year}_detail.csv"
        summary_path = RESULTS_DIR / f"backtest_extended_{year}_summary.csv"
        detail_all.to_csv(detail_path,  index=False)
        summary_df.to_csv(summary_path, index=False)

        logger.info("Detail  → %s (%d rows)", detail_path, len(detail_all))
        logger.info("Summary → %s", summary_path)
        print_summary(summary_df, year)

        valid_alphas = summary_df["alpha_yearend"].dropna()
        if not valid_alphas.empty:
            print(f"\n  Average year-end alpha across {year} cohorts: {valid_alphas.mean():+.2f}%\n")

    print("\nExtended backtest complete. Run analyze_long_holds_all.py for combined results.\n")


if __name__ == "__main__":
    main()

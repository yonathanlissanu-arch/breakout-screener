#!/usr/bin/env python3
"""
backtest_2025.py — Historical backtest of the triple-bottom scanner for 2025.

Methodology
-----------
For each of four quarterly cohort dates (Jan 1, Apr 1, Jul 1, Oct 1 2025):
  1. Slice every ticker's price history to data visible ON that date only
     (no look-ahead bias — the scanner sees exactly what it would have seen live)
  2. Run the identical triple-bottom detection used in monthly_run.py
  3. Pick the top-10 confirmed breakout candidates by composite score
  4. Record entry price (last close on cohort date)
  5. Measure forward returns at +1 month, +3 months, +6 months, and Dec 31 2025
  6. Compare equal-weight portfolio return to SPY over the same windows

Survivorship-bias note
----------------------
The universe is the CURRENT index composition, not the 2025 one. Companies
delisted or removed since 2025 will be absent, which modestly flatters results.
Treat alpha figures as indicative, not exact.

Output
------
  results/backtest_2025_detail.csv   — one row per stock per cohort
  results/backtest_2025_summary.csv  — one row per cohort, aggregate vs SPY
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
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
AS_OF_DATES = [
    date(2025, 1, 2),   # Q1 — first trading day
    date(2025, 4, 1),   # Q2
    date(2025, 7, 1),   # Q3
    date(2025, 10, 1),  # Q4
]

FORWARD_WINDOWS = {"1m": 21, "3m": 63, "6m": 126}
YEAR_END        = date(2025, 12, 31)
TOP_N           = 10
HISTORY_YEARS   = 7      # covers 5y lookback at Jan 2025 + forward through 2025
SPY_TICKER      = "SPY"
RESULTS_DIR     = Path("results")
# Separate cache so 7-year history doesn't collide with the 1-year portfolio cache
BACKTEST_CACHE  = "data/backtest_cache"


# ── Helpers ────────────────────────────────────────────────────────────────

def _price_at(df: pd.DataFrame, target: date, direction: str = "on_or_before") -> Optional[float]:
    """Return the Close price on or before / on or after a target date."""
    if direction == "on_or_before":
        # Use end-of-day so intraday timestamps (e.g. 13:30 UTC) on target date are included
        ts = pd.Timestamp(target) + pd.Timedelta(hours=23, minutes=59)
        sub = df[df.index <= ts]
        return float(sub["Close"].iloc[-1]) if not sub.empty else None
    else:  # on_or_after
        ts = pd.Timestamp(target)
        sub = df[df.index >= ts]
        return float(sub["Close"].iloc[0]) if not sub.empty else None


def _price_after_n_days(df: pd.DataFrame, as_of: date, n_trading_days: int) -> Optional[float]:
    """Return Close price n trading days after as_of (using the full df)."""
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


# ── Core scan at a point in time ───────────────────────────────────────────

def scan_at_date(
    price_data_full: Dict[str, pd.DataFrame],
    universe: pd.DataFrame,
    as_of: date,
    top_n: int = TOP_N,
) -> pd.DataFrame:
    """
    Run the triple-bottom scanner as if today were `as_of`.
    Returns a DataFrame of top_n breakout candidates (may be fewer if not enough found).
    """
    from indicators import analyse_ticker_triple_bottom
    from screener_triple_bottom import _tb_composite_score

    ts = pd.Timestamp(as_of)
    results: List[dict] = []

    for ticker, df_full in tqdm(
        price_data_full.items(),
        desc=f"Scanning {as_of}",
        unit="ticker",
        leave=False,
    ):
        # Slice to only data visible on as_of — compare against end-of-day so
        # the as_of date's bar (timestamped at market open, e.g. 13:30 UTC) is included
        ts_eod = ts + pd.Timedelta(hours=23, minutes=59)
        df_slice = df_full[df_full.index <= ts_eod].copy()
        if len(df_slice) < 120:   # need at least 6 months of data
            continue

        row = analyse_ticker_triple_bottom(ticker, df_slice)
        if row is None:
            continue
        if row.get("pattern_type") != "triple_bottom_breakout":
            continue
        results.append(row)

    if not results:
        logger.warning("No breakout candidates found for %s", as_of)
        return pd.DataFrame()

    df_res = pd.DataFrame(results)
    meta = universe[["ticker", "name", "indices", "region"]].copy()
    df_res = df_res.merge(meta, on="ticker", how="left")
    df_res["indices"] = df_res["indices"].fillna("Unknown")
    df_res["region"]  = df_res["region"].fillna("Unknown")

    df_res["score"] = df_res.apply(_tb_composite_score, axis=1)
    df_res = df_res.sort_values("score", ascending=False).reset_index(drop=True)
    df_res.insert(0, "rank", df_res.index + 1)

    return df_res.head(top_n)


# ── Forward return computation ─────────────────────────────────────────────

def compute_forward_returns(
    cohort_df: pd.DataFrame,
    price_data_full: Dict[str, pd.DataFrame],
    spy_df: pd.DataFrame,
    as_of: date,
) -> pd.DataFrame:
    """
    Attach forward return columns to the cohort DataFrame.
    Also adds SPY return columns for the same windows.
    """
    rows = []

    spy_entry = _price_at(spy_df, as_of, "on_or_before")

    for _, row in cohort_df.iterrows():
        ticker = row["ticker"]
        df_full = price_data_full.get(ticker)

        rec = row.to_dict()
        rec["cohort_date"] = str(as_of)
        rec["entry_price"] = _price_at(df_full, as_of, "on_or_before") if df_full is not None else None

        # Forward windows
        for label, n_days in FORWARD_WINDOWS.items():
            exit_px  = _price_after_n_days(df_full, as_of, n_days) if df_full is not None else None
            spy_exit = _price_after_n_days(spy_df, as_of, n_days)
            stock_ret = _pct_return(rec["entry_price"], exit_px)
            spy_ret   = _pct_return(spy_entry, spy_exit)
            rec[f"price_{label}"]    = exit_px
            rec[f"return_{label}"]   = stock_ret
            rec[f"spy_return_{label}"] = spy_ret
            rec[f"alpha_{label}"]    = (
                round(stock_ret - spy_ret, 2)
                if stock_ret is not None and spy_ret is not None else None
            )

        # Year-end 2025
        ye_exit  = _price_at(df_full, YEAR_END, "on_or_before") if df_full is not None else None
        spy_ye   = _price_at(spy_df, YEAR_END, "on_or_before")
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


# ── Summary per cohort ─────────────────────────────────────────────────────

def summarise_cohorts(detail_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-stock detail into one row per cohort."""
    summaries = []
    for cohort_date, grp in detail_df.groupby("cohort_date"):
        rec: dict = {"cohort_date": cohort_date, "n_stocks": len(grp)}
        for label in list(FORWARD_WINDOWS.keys()) + ["yearend"]:
            ret_col = f"return_{label}"
            spy_col = f"spy_return_{label}"
            alp_col = f"alpha_{label}"
            valid = grp[ret_col].dropna()
            spy_val = grp[spy_col].dropna()
            rec[f"portfolio_return_{label}"] = round(valid.mean(), 2) if not valid.empty else None
            rec[f"spy_return_{label}"]       = round(spy_val.mean(), 2) if not spy_val.empty else None
            rec[f"alpha_{label}"]            = (
                round(rec[f"portfolio_return_{label}"] - rec[f"spy_return_{label}"], 2)
                if rec[f"portfolio_return_{label}"] is not None and rec[f"spy_return_{label}"] is not None
                else None
            )
            rec[f"pct_winners_{label}"]      = (
                round((valid > 0).sum() / len(valid) * 100, 1) if not valid.empty else None
            )
        summaries.append(rec)
    return pd.DataFrame(summaries)


# ── Pretty print ───────────────────────────────────────────────────────────

def print_summary(summary_df: pd.DataFrame) -> None:
    from tabulate import tabulate

    print(f"\n{'═'*100}")
    print("  TRIPLE-BOTTOM BACKTEST — 2025 QUARTERLY COHORTS  (Equal-weight $100k, Top 10 breakouts)")
    print(f"{'═'*100}")

    display_cols = ["cohort_date", "n_stocks",
                    "portfolio_return_1m", "spy_return_1m",   "alpha_1m",
                    "portfolio_return_3m", "spy_return_3m",   "alpha_3m",
                    "portfolio_return_6m", "spy_return_6m",   "alpha_6m",
                    "portfolio_return_yearend", "spy_return_yearend", "alpha_yearend"]
    display_cols = [c for c in display_cols if c in summary_df.columns]

    df_disp = summary_df[display_cols].copy()
    for col in df_disp.columns:
        if "return" in col or "alpha" in col:
            df_disp[col] = df_disp[col].apply(
                lambda v: f"{v:+.2f}%" if v is not None and not (isinstance(v, float) and np.isnan(v)) else "—"
            )

    print(tabulate(df_disp, headers="keys", tablefmt="rounded_outline", showindex=False))
    print()


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)

    # ── 1. Universe ──────────────────────────────────────────────────────────
    logger.info("Step 1: Building universe …")
    from universe import build_universe
    universe = build_universe(
        sp500=True, midcap400=True, russell2000=False,
        euronext=False, stoxx600=True, wilshire2000=True,
    )
    logger.info("Universe: %d tickers", len(universe))

    # ── 2. Download full price history ───────────────────────────────────────
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
        logger.error("Could not fetch SPY data — aborting.")
        return
    logger.info("Price data ready: %d tickers + SPY", len(price_data_full))

    # ── 3. Quarterly scans ───────────────────────────────────────────────────
    all_detail_frames: List[pd.DataFrame] = []

    for as_of in AS_OF_DATES:
        logger.info("── Cohort %s ──────────────────────", as_of)

        cohort_df = scan_at_date(price_data_full, universe, as_of, top_n=TOP_N)
        if cohort_df.empty:
            logger.warning("No candidates for %s — skipping.", as_of)
            continue

        n_breakouts = len(cohort_df)
        logger.info("Found %d breakout candidates — computing forward returns …", n_breakouts)

        detail_df = compute_forward_returns(cohort_df, price_data_full, spy_df, as_of)
        all_detail_frames.append(detail_df)

        # Quick preview
        print(f"\n  Top picks for {as_of}:")
        for _, r in detail_df.iterrows():
            yr = r.get("return_yearend")
            sp = r.get("spy_return_yearend")
            al = r.get("alpha_yearend")
            print(
                f"    {r['ticker']:6}  entry=${r['entry_price'] or 0:>8.2f}  "
                f"yearend={yr:+.1f}%  SPY={sp:+.1f}%  α={al:+.1f}%"
                if yr is not None and sp is not None and al is not None
                else f"    {r['ticker']:6}  entry=${r['entry_price'] or 0:>8.2f}  (forward data unavailable)"
            )

    if not all_detail_frames:
        print("\nNo backtest results generated.")
        return

    # ── 4. Save & summarise ──────────────────────────────────────────────────
    detail_all = pd.concat(all_detail_frames, ignore_index=True)
    summary_df = summarise_cohorts(detail_all)

    detail_path  = RESULTS_DIR / "backtest_2025_detail.csv"
    summary_path = RESULTS_DIR / "backtest_2025_summary.csv"
    detail_all.to_csv(detail_path,  index=False)
    summary_df.to_csv(summary_path, index=False)

    logger.info("Detail  → %s (%d rows)", detail_path, len(detail_all))
    logger.info("Summary → %s", summary_path)

    print_summary(summary_df)

    avg_alpha_yearend = summary_df["alpha_yearend"].dropna().mean()
    print(f"  Average alpha vs SPY (year-end 2025, across all cohorts): {avg_alpha_yearend:+.2f}%\n")


if __name__ == "__main__":
    main()

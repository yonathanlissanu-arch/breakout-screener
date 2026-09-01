#!/usr/bin/env python3
"""
backtest_stringent.py — Historical backtest of the stringent triple-bottom scanner.

Years selected: 2019 and 2024
(Randomly chosen with seed=42 from the pool 2019–2024, ensuring ≥5 years of
prior price history are available in the 12-year download window.)

Methodology
-----------
For each monthly cohort date (first trading day of each month):
  1. Slice each ticker's price history to data visible ON that date only
     (no look-ahead bias)
  2. Apply the exact same hard gates used in the live stringent screener:
       pct_above_200sma >= 20%
       volume_ratio     >= 3.5×
       pct_above_neckline > 5%
       pattern_type == triple_bottom_breakout
  3. Score with the stringent formula (50% trend · 25% vol · 15% neckline · 10% tight)
  4. Pick top-5 candidates by score
  5. Record entry price (last close on cohort date)
  6. Measure forward returns: +1m, +100d, +3m, +6m, year-end
  7. Compare equal-weight portfolio vs SPY over the same windows

Output
------
  results/backtest_stringent_2019_detail.csv
  results/backtest_stringent_2019_summary.csv
  results/backtest_stringent_2024_detail.csv
  results/backtest_stringent_2024_summary.csv
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
# Two randomly selected years (seed=42, pool=2019-2024)
BACKTEST_CONFIGS = [
    {
        "year": 2019,
        "year_end": date(2019, 12, 31),
        "cohort_dates": [
            date(2019,  1,  2),   # Jan 1 = holiday
            date(2019,  2,  1),
            date(2019,  3,  1),
            date(2019,  4,  1),
            date(2019,  5,  1),
            date(2019,  6,  3),   # Jun 1 = Saturday
            date(2019,  7,  1),
            date(2019,  8,  1),
            date(2019,  9,  3),   # Sep 2 = Labor Day
            date(2019, 10,  1),
            date(2019, 11,  1),
            date(2019, 12,  2),   # Dec 1 = Sunday
        ],
    },
    {
        "year": 2024,
        "year_end": date(2024, 12, 31),
        "cohort_dates": [
            date(2024,  1,  2),   # Jan 1 = holiday
            date(2024,  2,  1),
            date(2024,  3,  1),
            date(2024,  4,  1),
            date(2024,  5,  1),
            date(2024,  6,  3),   # Jun 1 = Saturday
            date(2024,  7,  1),
            date(2024,  8,  1),
            date(2024,  9,  3),   # Sep 2 = Labor Day
            date(2024, 10,  1),
            date(2024, 11,  1),
            date(2024, 12,  2),   # Dec 1 = Sunday
        ],
    },
]

FORWARD_WINDOWS = {"1m": 21, "100d": 100, "3m": 63, "6m": 126}
TOP_N           = 5
SPY_TICKER      = "SPY"
RESULTS_DIR     = Path("results")
HISTORY_YEARS   = 12   # from ~2026 back to ~2014; covers 5-year prior history for 2019
BACKTEST_CACHE  = "data/backtest_stringent_cache"

# Hard gates (must match screener_triple_bottom_stringent.py)
MIN_PCT_ABOVE_200SMA   = 20.0
MIN_VOLUME_RATIO       = 3.5
MIN_PCT_ABOVE_NECKLINE = 5.0


# ── Helpers ────────────────────────────────────────────────────────────────

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
    if isinstance(row, dict):
        get = row.get
    else:
        get = row.get
    trend  = min((get("pct_above_200sma") or 0) / 100, 1.0)
    vol    = min((get("volume_ratio") or 0) / 15, 1.0)
    neck   = min((get("pct_above_neckline") or 0) / 30, 1.0)
    tight  = max(0.0, 1.0 - (get("bottom_variation_pct") or 5) / 10)
    return 0.50 * trend + 0.25 * vol + 0.15 * neck + 0.10 * tight


# ── Core scan at a point in time ────────────────────────────────────────────

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
        "%s: %d passed gates (of ~%d with patterns), %d rejected",
        as_of, len(candidates), len(candidates) + rejected, rejected,
    )
    return df_res.head(top_n)


# ── Forward return computation ───────────────────────────────────────────────

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
            rec[f"price_{label}"]       = exit_px
            rec[f"return_{label}"]      = stock_ret
            rec[f"spy_return_{label}"]  = spy_ret
            rec[f"alpha_{label}"]       = (
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


# ── Summary per cohort ───────────────────────────────────────────────────────

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


# ── Pretty print ─────────────────────────────────────────────────────────────

def print_summary(summary_df: pd.DataFrame, year: int) -> None:
    from tabulate import tabulate

    print(f"\n{'═'*120}")
    print(f"  STRINGENT TRIPLE-BOTTOM BACKTEST — {year} MONTHLY COHORTS  (Equal-weight $100k, Top 5 picks)")
    print(f"  Gates: 200SMA ≥ {MIN_PCT_ABOVE_200SMA}% · Vol ≥ {MIN_VOLUME_RATIO}× · Neckline > {MIN_PCT_ABOVE_NECKLINE}%")
    print(f"{'═'*120}")

    display_cols = [
        "cohort_date", "n_stocks",
        "portfolio_return_1m",    "spy_return_1m",    "alpha_1m",
        "portfolio_return_100d",  "spy_return_100d",  "alpha_100d",
        "portfolio_return_3m",    "spy_return_3m",    "alpha_3m",
        "portfolio_return_6m",    "spy_return_6m",    "alpha_6m",
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
    print()


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)

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

        logger.info("\n%s\n  YEAR %d BACKTEST  (%d cohorts)\n%s", "="*60, year, len(dates), "="*60)

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
                        f"    {r['ticker']:6}  entry=${r['entry_price'] or 0:>8.2f}  "
                        f"200SMA={sma:.0f}%  vol={vol:.1f}×  "
                        f"yearend={yr:+.1f}%  SPY={sp:+.1f}%  α={al:+.1f}%"
                    )
                else:
                    print(f"    {r['ticker']:6}  entry=${r['entry_price'] or 0:>8.2f}  (forward data unavailable)")

        if not all_detail_frames:
            print(f"\nNo results for {year}.")
            continue

        detail_all = pd.concat(all_detail_frames, ignore_index=True)
        summary_df = summarise_cohorts(detail_all)

        detail_path  = RESULTS_DIR / f"backtest_stringent_{year}_detail.csv"
        summary_path = RESULTS_DIR / f"backtest_stringent_{year}_summary.csv"
        detail_all.to_csv(detail_path,  index=False)
        summary_df.to_csv(summary_path, index=False)

        logger.info("Detail  → %s (%d rows)", detail_path, len(detail_all))
        logger.info("Summary → %s", summary_path)

        print_summary(summary_df, year)

        valid_alphas = summary_df["alpha_yearend"].dropna()
        if not valid_alphas.empty:
            avg_alpha = valid_alphas.mean()
            print(f"  Average alpha vs SPY (year-end {year}, across all cohorts): {avg_alpha:+.2f}%\n")

    print("\nBacktest complete — results in results/backtest_stringent_*.csv\n")


if __name__ == "__main__":
    main()

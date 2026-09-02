#!/usr/bin/env python3
"""
analyze_long_holds.py — Test longer holding periods (12/18/24/36/48/60 months)
for the stringent triple-bottom screener cohorts across all backtested years.

Supports both the original 2019/2024 backtest and the extended 2013/2016/2023
backtest. Loads existing detail CSVs — no re-scan needed.

Hold windows
  12m = 252 trading days
  18m = 378 trading days
  24m = 504 trading days
  36m = 756 trading days
  48m = 1008 trading days
  60m = 1260 trading days

Data availability (today ≈ Sep 2026):
  2013: all windows through 60m fully available
  2016: all windows through 60m fully available
  2019: all windows through 60m fully available
  2023: 12m–24m available; 36m+ not yet reached
  2024: 12m–18m available; 24m partial; 36m+ not available
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from tabulate import tabulate

RESULTS_DIR   = Path("results")
SPY_TICKER    = "SPY"

LONG_WINDOWS = {
    "12m":  252,
    "18m":  378,
    "24m":  504,
    "36m":  756,
    "48m": 1008,
    "60m": 1260,
}

# Map each year to its cache dir and detail CSV prefix
YEAR_CONFIGS = [
    {"year": 2013, "cache": "data/backtest_extended_cache",  "prefix": "backtest_extended"},
    {"year": 2016, "cache": "data/backtest_extended_cache",  "prefix": "backtest_extended"},
    {"year": 2019, "cache": "data/backtest_stringent_cache", "prefix": "backtest_stringent"},
    {"year": 2023, "cache": "data/backtest_extended_cache",  "prefix": "backtest_extended"},
    {"year": 2024, "cache": "data/backtest_stringent_cache", "prefix": "backtest_stringent"},
]


# ── price helpers ────────────────────────────────────────────────────────────

def load_parquet(ticker: str, cache_dir: str = "data/backtest_stringent_cache") -> Optional[pd.DataFrame]:
    path = os.path.join(cache_dir, f"{ticker}.parquet")
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def price_at(df: pd.DataFrame, target: date) -> Optional[float]:
    ts = pd.Timestamp(target) + pd.Timedelta(hours=23, minutes=59)
    sub = df[df.index <= ts]
    return float(sub["Close"].iloc[-1]) if not sub.empty else None


def price_after_n_days(df: pd.DataFrame, as_of: date, n: int) -> Optional[float]:
    ts = pd.Timestamp(as_of) + pd.Timedelta(hours=23, minutes=59)
    future = df[df.index > ts]["Close"].dropna()
    if future.empty or len(future) < 1:
        return None
    idx = min(n - 1, len(future) - 1)
    # Only return if we actually reached (or nearly reached) the target day
    # Allow up to 10 days short (e.g. data ends slightly before the window)
    if idx < n - 11:
        return None
    return float(future.iloc[idx])


def pct_ret(entry: Optional[float], exit_: Optional[float]) -> Optional[float]:
    if entry is None or exit_ is None or entry == 0:
        return None
    return round((exit_ - entry) / entry * 100, 2)


# ── main ────────────────────────────────────────────────────────────────────

def main() -> None:
    all_summaries = []

    for cfg in YEAR_CONFIGS:
        year   = cfg["year"]
        cache  = cfg["cache"]
        prefix = cfg["prefix"]

        detail_path = RESULTS_DIR / f"{prefix}_{year}_detail.csv"
        if not detail_path.exists():
            print(f"Skipping {year}: {detail_path} not found (run the backtest first).")
            continue

        spy_df = load_parquet(SPY_TICKER, cache_dir=cache)
        if spy_df is None:
            # Fall back to either cache
            for alt in ["data/backtest_stringent_cache", "data/backtest_extended_cache"]:
                spy_df = load_parquet(SPY_TICKER, cache_dir=alt)
                if spy_df is not None:
                    break
        if spy_df is None:
            print(f"ERROR: SPY not in any cache — run a backtest first.")
            return

        detail = pd.read_csv(detail_path)
        print(f"\nLoaded {year} detail: {len(detail)} rows across {detail['cohort_date'].nunique()} cohorts")

        rows = []
        for _, rec in detail.iterrows():
            ticker      = rec["ticker"]
            cohort_date = date.fromisoformat(rec["cohort_date"])
            entry_price = rec["entry_price"]

            stock_df = load_parquet(ticker, cache_dir=cache)
            if stock_df is None:
                # try the other cache (some tickers cached in both)
                for alt in ["data/backtest_stringent_cache", "data/backtest_extended_cache"]:
                    if alt != cache:
                        stock_df = load_parquet(ticker, cache_dir=alt)
                        if stock_df is not None:
                            break

            row: dict = {
                "year":        year,
                "cohort_date": str(cohort_date),
                "ticker":      ticker,
                "entry_price": entry_price,
            }

            spy_entry = price_at(spy_df, cohort_date)

            for label, n_days in LONG_WINDOWS.items():
                exit_px  = price_after_n_days(stock_df, cohort_date, n_days) if stock_df is not None else None
                spy_exit = price_after_n_days(spy_df,  cohort_date, n_days)

                stock_ret = pct_ret(entry_price, exit_px)
                spy_ret   = pct_ret(spy_entry, spy_exit)
                row[f"return_{label}"]     = stock_ret
                row[f"spy_return_{label}"] = spy_ret
                row[f"alpha_{label}"]      = (
                    round(stock_ret - spy_ret, 2)
                    if stock_ret is not None and spy_ret is not None else None
                )

            rows.append(row)

        df_long = pd.DataFrame(rows)
        out_path = RESULTS_DIR / f"longhold_{year}.csv"
        df_long.to_csv(out_path, index=False)
        print(f"  Saved → {out_path}")

        # Cohort-level summary
        cohort_summaries = []
        for cohort_date, grp in df_long.groupby("cohort_date"):
            s: dict = {"year": year, "cohort_date": cohort_date, "n": len(grp)}
            for label in LONG_WINDOWS:
                valid = grp[f"return_{label}"].dropna()
                spy_v = grp[f"spy_return_{label}"].dropna()
                port_r = round(valid.mean(), 2) if not valid.empty else None
                spy_r  = round(spy_v.mean(), 2) if not spy_v.empty else None
                s[f"port_{label}"] = port_r
                s[f"spy_{label}"]  = spy_r
                s[f"alpha_{label}"] = (
                    round(port_r - spy_r, 2)
                    if port_r is not None and spy_r is not None else None
                )
                s[f"coverage_{label}"] = int(len(valid))
            cohort_summaries.append(s)

        sum_df = pd.DataFrame(cohort_summaries)
        all_summaries.append(sum_df)
        _print_cohort_table(sum_df, year)

    # ── Cross-year aggregate ────────────────────────────────────────────────
    if all_summaries:
        all_df = pd.concat(all_summaries, ignore_index=True)
        years_loaded = sorted(all_df["year"].unique().tolist())
        print(f"\n{'═'*110}")
        print(f"  AGGREGATE ALPHA vs SPY BY HOLD PERIOD — years: {years_loaded}")
        print(f"{'═'*110}")
        print(f"  {'Hold':>5}  {'Port avg':>10}  {'SPY avg':>10}  {'Alpha avg':>10}  "
              f"{'Avg winners%':>14}  {'Coverage':>10}")
        print(f"  {'-'*5}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*14}  {'-'*10}")

        for label in LONG_WINDOWS:
            all_alphas   = []
            all_port     = []
            all_spy      = []
            all_coverage = []

            for year in years_loaded:
                year_df = all_df[all_df["year"] == year]
                col_alpha = f"alpha_{label}"
                col_port  = f"port_{label}"
                col_spy   = f"spy_{label}"
                col_cov   = f"coverage_{label}"
                if col_alpha not in year_df.columns:
                    continue
                valid_rows = year_df.dropna(subset=[col_alpha])
                all_alphas.extend(valid_rows[col_alpha].tolist())
                all_port.extend(valid_rows.dropna(subset=[col_port])[col_port].tolist())
                all_spy.extend(valid_rows.dropna(subset=[col_spy])[col_spy].tolist())
                if col_cov in year_df.columns:
                    all_coverage.extend(year_df[col_cov].tolist())

            avg_alpha = round(np.mean(all_alphas), 2) if all_alphas else None
            avg_port  = round(np.mean(all_port), 2) if all_port else None
            avg_spy   = round(np.mean(all_spy), 2) if all_spy else None
            n_cohorts = len(all_alphas)

            alpha_str = f"{avg_alpha:+.2f}%" if avg_alpha is not None else "  —   "
            port_str  = f"{avg_port:+.2f}%"  if avg_port  is not None else "  —   "
            spy_str   = f"{avg_spy:+.2f}%"   if avg_spy   is not None else "  —   "

            print(f"  {label:>5}  {port_str:>10}  {spy_str:>10}  {alpha_str:>10}  "
                  f"{'n/a':>14}  {n_cohorts:>10} cohorts")

        print()
        _print_stock_level_alpha(all_summaries)

    # Also load existing short-hold results for comparison
    _print_comparison_table()


def _print_cohort_table(sum_df: pd.DataFrame, year: int) -> None:
    print(f"\n{'─'*110}")
    print(f"  {year} — Cohort alpha by hold period (portfolio avg vs SPY, %)  [n = stocks with data]")
    print(f"{'─'*110}")

    disp_cols = ["cohort_date", "n"]
    for label in LONG_WINDOWS:
        if f"alpha_{label}" in sum_df.columns:
            disp_cols += [f"port_{label}", f"spy_{label}", f"alpha_{label}", f"coverage_{label}"]

    disp = sum_df[[c for c in disp_cols if c in sum_df.columns]].copy()

    # Format return/alpha columns
    for col in disp.columns:
        if col.startswith("port_") or col.startswith("spy_") or col.startswith("alpha_"):
            disp[col] = disp[col].apply(
                lambda v: f"{v:+.1f}%" if v is not None and not (isinstance(v, float) and np.isnan(v)) else "—"
            )

    print(tabulate(disp, headers="keys", tablefmt="rounded_outline", showindex=False))


def _print_stock_level_alpha(all_summaries) -> None:
    """Print average per-stock alpha across all individual positions."""
    print(f"\n{'═'*80}")
    print("  PER-STOCK ALPHA (median & mean across all individual positions, all years)")
    print(f"{'═'*80}")
    print(f"  {'Hold':>5}  {'Mean alpha':>12}  {'Median alpha':>14}  {'N stocks':>10}  {'% positive':>12}")
    print(f"  {'-'*5}  {'-'*12}  {'-'*14}  {'-'*10}  {'-'*12}")

    dfs = []
    for cfg in YEAR_CONFIGS:
        p = RESULTS_DIR / f"longhold_{cfg['year']}.csv"
        if p.exists():
            dfs.append(pd.read_csv(p))

    if not dfs:
        return

    combined = pd.concat(dfs, ignore_index=True)

    for label in LONG_WINDOWS:
        col = f"alpha_{label}"
        if col not in combined.columns:
            continue
        vals = combined[col].dropna()
        if vals.empty:
            print(f"  {label:>5}  {'—':>12}  {'—':>14}  {'0':>10}  {'—':>12}")
            continue
        mean_a   = vals.mean()
        median_a = vals.median()
        pct_pos  = (vals > 0).mean() * 100
        print(f"  {label:>5}  {mean_a:>+11.2f}%  {median_a:>+13.2f}%  {len(vals):>10}  {pct_pos:>11.1f}%")
    print()


def _print_comparison_table() -> None:
    """Side-by-side: aggregate short-hold vs long-hold alpha across all years with full data."""
    print(f"\n{'═'*90}")
    print("  SHORT-HOLD vs LONG-HOLD ALPHA — aggregate across all years with complete data")
    print(f"{'═'*90}")

    # Use all years that have both a short-hold summary and a long-hold CSV
    short_alphas: dict = {w: [] for w in ["1m", "100d", "3m", "6m", "yearend"]}
    long_alphas: dict  = {w: [] for w in LONG_WINDOWS}

    for cfg in YEAR_CONFIGS:
        year   = cfg["year"]
        prefix = cfg["prefix"]
        short_path = RESULTS_DIR / f"{prefix}_{year}_summary.csv"
        long_path  = RESULTS_DIR / f"longhold_{year}.csv"
        if short_path.exists():
            s = pd.read_csv(short_path)
            for w in ["1m", "100d", "3m", "6m", "yearend"]:
                col = f"alpha_{w}"
                if col in s.columns:
                    short_alphas[w].extend(s[col].dropna().tolist())
        if long_path.exists():
            l = pd.read_csv(long_path)
            for w in LONG_WINDOWS:
                col = f"alpha_{w}"
                if col in l.columns:
                    long_alphas[w].extend(l[col].dropna().tolist())

    rows = []
    short_df = pd.DataFrame()  # placeholder
    long_df  = pd.DataFrame()  # placeholder

    for w in ["1m", "100d", "3m", "6m", "yearend"]:
        vals = short_alphas[w]
        rows.append({
            "hold":         w,
            "mean_alpha":   round(np.mean(vals), 2) if vals else None,
            "median_alpha": round(np.median(vals), 2) if vals else None,
            "n":            len(vals),
            "source":       "short-hold",
        })

    for w in LONG_WINDOWS:
        vals = long_alphas[w]
        rows.append({
            "hold":         w,
            "mean_alpha":   round(np.mean(vals), 2) if vals else None,
            "median_alpha": round(np.median(vals), 2) if vals else None,
            "n":            len(vals),
            "source":       "long-hold",
        })

    tbl = pd.DataFrame(rows)
    for col in ["mean_alpha", "median_alpha"]:
        tbl[col] = tbl[col].apply(
            lambda v: f"{v:+.2f}%" if v is not None else "—"
        )

    print(tabulate(tbl, headers="keys", tablefmt="rounded_outline", showindex=False))
    print()


if __name__ == "__main__":
    main()

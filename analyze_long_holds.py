#!/usr/bin/env python3
"""
analyze_long_holds.py — Test longer holding periods (12/18/24/36/48/60 months)
for the stringent triple-bottom screener cohorts (2019 and 2024).

Uses the already-cached price data and existing detail CSVs — no re-scan needed.

Hold windows
  12m = 252 trading days
  18m = 378 trading days
  24m = 504 trading days
  36m = 756 trading days
  48m = 1008 trading days
  60m = 1260 trading days

Caveat: 2024 cohorts have limited future data (today ≈ Sep 2026).
  12m available  · 18m mostly available  · 24m+ mostly unavailable
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
CACHE_DIR     = "data/backtest_stringent_cache"
SPY_TICKER    = "SPY"

LONG_WINDOWS = {
    "12m":  252,
    "18m":  378,
    "24m":  504,
    "36m":  756,
    "48m": 1008,
    "60m": 1260,
}

YEARS = [2019, 2024]


# ── price helpers ────────────────────────────────────────────────────────────

def load_parquet(ticker: str) -> Optional[pd.DataFrame]:
    path = os.path.join(CACHE_DIR, f"{ticker}.parquet")
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
    spy_df = load_parquet(SPY_TICKER)
    if spy_df is None:
        print("ERROR: SPY not found in cache. Run backtest_stringent.py first.")
        return

    all_summaries = []

    for year in YEARS:
        detail_path = RESULTS_DIR / f"backtest_stringent_{year}_detail.csv"
        if not detail_path.exists():
            print(f"Missing {detail_path} — run backtest_stringent.py first.")
            continue

        detail = pd.read_csv(detail_path)
        print(f"\nLoaded {year} detail: {len(detail)} rows across {detail['cohort_date'].nunique()} cohorts")

        rows = []
        for _, rec in detail.iterrows():
            ticker      = rec["ticker"]
            cohort_date = date.fromisoformat(rec["cohort_date"])
            entry_price = rec["entry_price"]

            stock_df = load_parquet(ticker)

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
        out_path = RESULTS_DIR / f"backtest_stringent_{year}_longhold.csv"
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
        print(f"\n{'═'*110}")
        print("  AGGREGATE ALPHA vs SPY BY HOLD PERIOD (all cohorts, equal-weight average)")
        print(f"{'═'*110}")
        print(f"  {'Hold':>5}  {'Port avg':>10}  {'SPY avg':>10}  {'Alpha avg':>10}  "
              f"{'Avg winners%':>14}  {'Coverage':>10}")
        print(f"  {'-'*5}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*14}  {'-'*10}")

        for label in LONG_WINDOWS:
            all_alphas   = []
            all_port     = []
            all_spy      = []
            all_coverage = []

            for year in YEARS:
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
    print("  PER-STOCK ALPHA (median & mean across all individual positions)")
    print(f"{'═'*80}")
    print(f"  {'Hold':>5}  {'Mean alpha':>12}  {'Median alpha':>14}  {'N stocks':>10}  {'% positive':>12}")
    print(f"  {'-'*5}  {'-'*12}  {'-'*14}  {'-'*10}  {'-'*12}")

    for year in YEARS:
        detail_path = RESULTS_DIR / f"backtest_stringent_{year}_longhold.csv"
        if not detail_path.exists():
            continue
        df = pd.read_csv(detail_path)

        if year == YEARS[0]:
            dfs = [df]
        else:
            try:
                dfs.append(df)
            except NameError:
                dfs = [df]

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
    """Side-by-side short vs long hold alpha for context."""
    print(f"\n{'═'*90}")
    print("  SHORT-HOLD (from original backtest) vs LONG-HOLD ALPHA — 2019 cohorts only")
    print("  (2019 gives the most complete long-hold data — all windows through 60m available)")
    print(f"{'═'*90}")

    short_path = RESULTS_DIR / "backtest_stringent_2019_summary.csv"
    long_path  = RESULTS_DIR / "backtest_stringent_2019_longhold.csv"

    if not short_path.exists() or not long_path.exists():
        print("  (summary CSVs not found)")
        return

    short_df = pd.read_csv(short_path)
    long_df  = pd.read_csv(long_path)

    short_windows = ["1m", "100d", "3m", "6m", "yearend"]
    long_windows  = list(LONG_WINDOWS.keys())

    rows = []

    for w in short_windows:
        col = f"alpha_{w}"
        if col in short_df.columns:
            vals = short_df[col].dropna()
            rows.append({
                "hold":         w,
                "mean_alpha":   round(vals.mean(), 2) if not vals.empty else None,
                "median_alpha": round(vals.median(), 2) if not vals.empty else None,
                "n_cohorts":    len(vals),
                "source":       "short-hold",
            })

    for w in long_windows:
        col = f"alpha_{w}"
        if col in long_df.columns:
            vals = long_df[col].dropna()
            rows.append({
                "hold":         w,
                "mean_alpha":   round(vals.mean(), 2) if not vals.empty else None,
                "median_alpha": round(vals.median(), 2) if not vals.empty else None,
                "n_cohorts":    len(vals),
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

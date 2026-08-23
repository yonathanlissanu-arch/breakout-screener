"""
Main screening pipeline: apply filters, rank, output results.

Composite ranking score (higher = better candidate)
----------------------------------------------------
  recency_score    = 1 / (days_since_breakout + 1)         [most recent = best]
  volume_score     = min(volume_ratio / 1.5, 3.0) / 3.0    [normalized 0-1]
  extension_score  = 1 / (pct_above_200sma / 100 + 0.05)   [less extended = best]

composite = 0.45 * recency + 0.30 * volume + 0.25 * extension
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
from tabulate import tabulate

from config import CFG
from indicators import analyse_ticker, analyse_ticker_short

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #

def _composite_score(row: pd.Series) -> float:
    recency = 1.0 / (row["days_since_breakout"] + 1)
    volume = min(row["volume_ratio"] / 1.5, 3.0) / 3.0
    extension = 1.0 / (row["pct_above_200sma"] / 100.0 + 0.05)
    # Normalise extension to ~0-1 range (typical range 0-40% above 200-day)
    extension_norm = min(extension / 20.0, 1.0)
    return 0.45 * recency + 0.30 * volume + 0.25 * extension_norm


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #

def run_screen(
    price_data: Dict[str, pd.DataFrame],
    universe: pd.DataFrame,
    top_n: int = CFG.top_n,
    results_dir: str = CFG.results_dir,
) -> pd.DataFrame:
    """
    Screen all tickers, rank the results, persist to CSV, print the top N.

    Parameters
    ----------
    price_data : dict  { ticker → OHLCV DataFrame }
    universe   : DataFrame with columns [ticker, name, indices, region]
    top_n      : number of candidates to show in the summary table
    results_dir: where to save CSV output

    Returns
    -------
    Full results DataFrame (all candidates that passed every filter).
    """
    os.makedirs(results_dir, exist_ok=True)

    results: List[dict] = []
    tickers = list(price_data.keys())
    total = len(tickers)

    logger.info("Analysing %d tickers …", total)
    from tqdm import tqdm

    for i, ticker in enumerate(tqdm(tickers, desc="Screening", unit="ticker")):
        df = price_data[ticker]
        row = analyse_ticker(ticker, df)
        if row:
            results.append(row)

    if not results:
        print("\nNo breakout candidates found with the current filter settings.")
        return pd.DataFrame()

    df_results = pd.DataFrame(results)

    # Merge index/name metadata
    meta = universe[["ticker", "name", "indices", "region"]].copy()
    df_results = df_results.merge(meta, on="ticker", how="left")

    # Fill missing metadata for tickers not found in universe lookup
    df_results["indices"] = df_results["indices"].fillna("Unknown")
    df_results["region"] = df_results["region"].fillna("Unknown")

    # Composite score → rank
    df_results["score"] = df_results.apply(_composite_score, axis=1)
    df_results = df_results.sort_values("score", ascending=False).reset_index(drop=True)
    df_results.insert(0, "rank", df_results.index + 1)

    # ── Persist full results ──────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = os.path.join(results_dir, f"breakout_scan_{ts}.csv")
    df_results.to_csv(csv_path, index=False)
    logger.info("Full results (%d rows) saved → %s", len(df_results), csv_path)

    # ── Print top-N summary ───────────────────────────────────────────────────
    print_cols = [
        "rank", "ticker", "indices", "region",
        "price", "breakout_date", "days_since_breakout",
        "pct_above_resistance", "volume_ratio", "rsi14",
        "pct_above_200sma", "score",
    ]
    top = df_results.head(top_n)[print_cols].copy()
    top["breakout_date"] = top["breakout_date"].astype(str).str[:10]
    top["pct_above_resistance"] = top["pct_above_resistance"].map("{:.1f}%".format)
    top["volume_ratio"] = top["volume_ratio"].map("{:.1f}×".format)
    top["score"] = top["score"].map("{:.3f}".format)

    print(f"\n{'═'*110}")
    print(f"  BREAKOUT SCREENER — Top {top_n} candidates   "
          f"({len(df_results)} total passed all filters)   "
          f"[{datetime.now().strftime('%Y-%m-%d')}]")
    print(f"{'═'*110}")
    print(tabulate(top, headers="keys", tablefmt="rounded_outline", showindex=False))
    print(f"\nFull results → {csv_path}")
    print(
        "\nScore weights: 45% recency · 30% volume surge · 25% nearness to 200-day SMA\n"
    )

    return df_results


# --------------------------------------------------------------------------- #
# Breakdown screener (bearish mirror)
# --------------------------------------------------------------------------- #

def _composite_score_short(row: pd.Series) -> float:
    recency = 1.0 / (row["days_since_breakout"] + 1)
    volume = min(row["volume_ratio"] / 1.5, 3.0) / 3.0
    # Less extended below 200 SMA = better short entry (not exhausted downside)
    extension = 1.0 / (row["pct_below_200sma"] / 100.0 + 0.05)
    extension_norm = min(extension / 20.0, 1.0)
    return 0.45 * recency + 0.30 * volume + 0.25 * extension_norm


def run_screen_breakdown(
    price_data: Dict[str, pd.DataFrame],
    universe: pd.DataFrame,
    top_n: int = CFG.top_n,
    results_dir: str = CFG.results_dir,
) -> pd.DataFrame:
    """
    Screen all tickers for breakdown candidates (bearish mirror of run_screen).
    Saves to results/breakdown_scan_*.csv.
    """
    os.makedirs(results_dir, exist_ok=True)

    results: List[dict] = []
    from tqdm import tqdm

    logger.info("Screening %d tickers for breakdowns …", len(price_data))
    for ticker in tqdm(list(price_data.keys()), desc="Breakdown screen", unit="ticker"):
        row = analyse_ticker_short(ticker, price_data[ticker])
        if row:
            results.append(row)

    if not results:
        print("\nNo breakdown candidates found with the current filter settings.")
        return pd.DataFrame()

    df_results = pd.DataFrame(results)

    meta = universe[["ticker", "name", "indices", "region"]].copy()
    df_results = df_results.merge(meta, on="ticker", how="left")
    df_results["indices"] = df_results["indices"].fillna("Unknown")
    df_results["region"] = df_results["region"].fillna("Unknown")

    df_results["score"] = df_results.apply(_composite_score_short, axis=1)
    df_results = df_results.sort_values("score", ascending=False).reset_index(drop=True)
    df_results.insert(0, "rank", df_results.index + 1)

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = os.path.join(results_dir, f"breakdown_scan_{ts}.csv")
    df_results.to_csv(csv_path, index=False)
    logger.info("Breakdown results (%d rows) saved → %s", len(df_results), csv_path)

    print_cols = [
        "rank", "ticker", "indices", "region",
        "price", "breakout_date", "days_since_breakout",
        "pct_below_support", "volume_ratio", "rsi14",
        "pct_below_200sma", "score",
    ]
    top = df_results.head(top_n)[print_cols].copy()
    top["breakout_date"] = top["breakout_date"].astype(str).str[:10]
    top["pct_below_support"] = top["pct_below_support"].map("{:.1f}%".format)
    top["volume_ratio"] = top["volume_ratio"].map("{:.1f}×".format)
    top["score"] = top["score"].map("{:.3f}".format)

    print(f"\n{'═'*110}")
    print(f"  BREAKDOWN SCREENER — Top {top_n} candidates   "
          f"({len(df_results)} total passed all filters)   "
          f"[{datetime.now().strftime('%Y-%m-%d')}]")
    print(f"{'═'*110}")
    print(tabulate(top, headers="keys", tablefmt="rounded_outline", showindex=False))
    print(f"\nFull results → {csv_path}")
    print(
        "\nScore weights: 45% recency · 30% volume surge · 25% nearness to 200-day SMA\n"
    )

    return df_results

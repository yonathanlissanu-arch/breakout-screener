"""
Triple-bottom screener: detect multi-year triple-bottom patterns and rank results.

Composite score (higher = better candidate)
-------------------------------------------
Breakout patterns (price already above neckline):
  recency_score     = 1 / (days_since_breakout + 1)
  volume_score      = min(volume_ratio / 1.5, 3.0) / 3.0
  tightness_score   = max(0, 1 - bottom_variation_pct / 10)   [tighter = higher quality]
  longevity_score   = min(pattern_span_days / (252 * 3), 1.0) [longer = more significant]

  composite = 0.40 * recency + 0.25 * volume + 0.20 * tightness + 0.15 * longevity

Setup patterns (pattern formed, no breakout yet):
  Scored at 0.5 × max_breakout_score — ranked below breakouts.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Dict, List

import pandas as pd
from tabulate import tabulate

from config import CFG
from indicators import analyse_ticker_triple_bottom

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #

def _tb_composite_score(row: pd.Series) -> float:
    if row["pattern_type"] == "triple_bottom_breakout":
        days  = row.get("days_since_breakout") or 0
        recency    = 1.0 / (days + 1)
        vol_ratio  = row.get("volume_ratio") or 0.0
        volume     = min(vol_ratio / 1.5, 3.0) / 3.0
        var_pct    = row.get("bottom_variation_pct") or 5.0
        tightness  = max(0.0, 1.0 - var_pct / 10.0)
        span       = row.get("pattern_span_days") or 252
        longevity  = min(span / (252 * 3), 1.0)
        return 0.40 * recency + 0.25 * volume + 0.20 * tightness + 0.15 * longevity
    else:
        # Setup: score is lower so breakouts rank first
        pct_to_nl = row.get("pct_to_neckline") or 50.0
        proximity  = max(0.0, 1.0 - pct_to_nl / 30.0)
        var_pct    = row.get("bottom_variation_pct") or 5.0
        tightness  = max(0.0, 1.0 - var_pct / 10.0)
        span       = row.get("pattern_span_days") or 252
        longevity  = min(span / (252 * 3), 1.0)
        raw = 0.50 * proximity + 0.30 * tightness + 0.20 * longevity
        return raw * 0.50   # cap setup scores below breakout scores


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #

def run_triple_bottom_screen(
    price_data: Dict[str, pd.DataFrame],
    universe: pd.DataFrame,
    top_n: int = CFG.top_n,
    results_dir: str = CFG.results_dir,
    include_setups: bool = True,
) -> pd.DataFrame:
    """
    Screen all tickers for multi-year triple-bottom patterns, rank, persist to CSV,
    and print the top-N summary.

    Parameters
    ----------
    price_data    : { ticker → OHLCV DataFrame }
    universe      : DataFrame with columns [ticker, name, indices, region]
    top_n         : how many candidates to display in the summary table
    results_dir   : directory for CSV output
    include_setups: if True, include setups (pattern formed, not yet broken out)
                    alongside confirmed breakouts

    Returns
    -------
    Full results DataFrame (all candidates that passed the pattern filter).
    """
    os.makedirs(results_dir, exist_ok=True)

    results: List[dict] = []
    tickers = list(price_data.keys())
    logger.info("Scanning %d tickers for triple-bottom patterns …", len(tickers))

    from tqdm import tqdm

    for ticker in tqdm(tickers, desc="Triple-bottom scan", unit="ticker"):
        df = price_data[ticker]
        row = analyse_ticker_triple_bottom(ticker, df)
        if row is None:
            continue
        if not include_setups and row.get("pattern_type") == "triple_bottom_setup":
            continue
        results.append(row)

    if not results:
        print("\nNo triple-bottom candidates found with the current settings.")
        return pd.DataFrame()

    df_res = pd.DataFrame(results)

    # Merge index / name metadata
    meta = universe[["ticker", "name", "indices", "region"]].copy()
    df_res = df_res.merge(meta, on="ticker", how="left")
    df_res["indices"] = df_res["indices"].fillna("Unknown")
    df_res["region"]  = df_res["region"].fillna("Unknown")

    # Score and rank
    df_res["score"] = df_res.apply(_tb_composite_score, axis=1)
    df_res = df_res.sort_values("score", ascending=False).reset_index(drop=True)
    df_res.insert(0, "rank", df_res.index + 1)

    # Persist
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = os.path.join(results_dir, f"triple_bottom_scan_{ts}.csv")
    df_res.to_csv(csv_path, index=False)
    logger.info("Triple-bottom results (%d rows) saved → %s", len(df_res), csv_path)

    # Print summary
    breakouts = (df_res["pattern_type"] == "triple_bottom_breakout").sum()
    setups    = (df_res["pattern_type"] == "triple_bottom_setup").sum()

    print_cols = [
        "rank", "ticker", "pattern_type", "indices", "region",
        "price", "avg_bottom", "neckline",
        "bottom_variation_pct", "pattern_span_days",
        "breakout_date", "days_since_breakout",
        "pct_above_neckline", "pct_to_neckline",
        "volume_ratio", "rsi14", "score",
    ]
    # Keep only columns that exist in the result
    print_cols = [c for c in print_cols if c in df_res.columns]

    top = df_res.head(top_n)[print_cols].copy()

    # Format for display
    for col, fmt in [
        ("bottom_variation_pct", "{:.1f}%"),
        ("pct_above_neckline",   "{:.1f}%"),
        ("pct_to_neckline",      "{:.1f}%"),
        ("volume_ratio",         "{:.1f}×"),
        ("score",                "{:.3f}"),
    ]:
        if col in top.columns:
            top[col] = top[col].apply(
                lambda v: fmt.format(v) if v is not None and not (
                    isinstance(v, float) and pd.isna(v)
                ) else "—"
            )

    if "breakout_date" in top.columns:
        top["breakout_date"] = top["breakout_date"].apply(
            lambda v: str(v)[:10] if v is not None else "—"
        )

    if "pattern_span_days" in top.columns:
        top["pattern_span_days"] = top["pattern_span_days"].apply(
            lambda v: f"{v//252}y {(v%252)//21}m" if v else "—"
        )

    print(f"\n{'═'*120}")
    print(
        f"  TRIPLE-BOTTOM SCANNER — Top {top_n} candidates   "
        f"({breakouts} breakouts · {setups} setups)   "
        f"[{datetime.now().strftime('%Y-%m-%d')}]"
    )
    print(f"{'═'*120}")
    print(tabulate(top, headers="keys", tablefmt="rounded_outline", showindex=False))
    print(f"\nFull results → {csv_path}")
    print(
        "\nScore weights (breakout): 40% recency · 25% volume · 20% bottom tightness · 15% pattern age\n"
    )

    return df_res

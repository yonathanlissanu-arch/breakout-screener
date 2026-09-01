"""
Triple-bottom *stringent* screener — higher-conviction filter layer on top of
the base triple-bottom pattern detector.

What makes it stringent vs the standard screener
-------------------------------------------------
Hard gates (all must pass — no score-based workaround):
  1. pct_above_200sma  >= 20   — stock must be in a real uptrend
  2. volume_ratio      >= 3.5  — breakout volume must be genuinely elevated
  3. pct_above_neckline > 5    — price must have cleared the neckline convincingly
  4. Only confirmed breakouts (pattern_type == triple_bottom_breakout) — no setups

Composite score (reweighted from 2025 backtest correlations)
-------------------------------------------------------------
  trend_score    = min(pct_above_200sma / 100, 1.0)       [r=+0.25 with yr-end alpha]
  volume_score   = min(volume_ratio / 15, 1.0)             [r=+0.14]
  neck_score     = min(pct_above_neckline / 30, 1.0)      [r=+0.14]
  tight_score    = max(0, 1 - bottom_variation_pct / 10)  [r=+0.11]

  composite = 0.50 * trend + 0.25 * volume + 0.15 * neck + 0.10 * tight

Default: top 5 picks per cohort (tight portfolio = sized at $20k each).
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

# Hard-gate thresholds (data-driven from 2025 backtest)
MIN_PCT_ABOVE_200SMA  = 20.0
MIN_VOLUME_RATIO      = 3.5
MIN_PCT_ABOVE_NECKLINE = 5.0
DEFAULT_TOP_N = 5


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

def _stringent_score(row: pd.Series) -> float:
    trend  = min((row.get("pct_above_200sma") or 0) / 100, 1.0)
    vol    = min((row.get("volume_ratio") or 0) / 15, 1.0)
    neck   = min((row.get("pct_above_neckline") or 0) / 30, 1.0)
    tight  = max(0.0, 1.0 - (row.get("bottom_variation_pct") or 5) / 10)
    return 0.50 * trend + 0.25 * vol + 0.15 * neck + 0.10 * tight


def _passes_hard_gates(row: dict) -> bool:
    return (
        row.get("pattern_type") == "triple_bottom_breakout"
        and (row.get("pct_above_200sma") or 0) >= MIN_PCT_ABOVE_200SMA
        and (row.get("volume_ratio") or 0) >= MIN_VOLUME_RATIO
        and (row.get("pct_above_neckline") or 0) > MIN_PCT_ABOVE_NECKLINE
    )


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #

def run_stringent_screen(
    price_data: Dict[str, pd.DataFrame],
    universe: pd.DataFrame,
    top_n: int = DEFAULT_TOP_N,
    results_dir: str = "results",
) -> pd.DataFrame:
    """
    Screen all tickers with hard gates + stringent scoring.

    Returns the full passing DataFrame (not just top_n); caller can .head(top_n).
    """
    os.makedirs(results_dir, exist_ok=True)

    from tqdm import tqdm

    candidates: List[dict] = []
    rejected_gates = 0

    for ticker in tqdm(list(price_data.keys()), desc="Stringent scan", unit="ticker"):
        df = price_data[ticker]
        row = analyse_ticker_triple_bottom(ticker, df)
        if row is None:
            continue
        if not _passes_hard_gates(row):
            rejected_gates += 1
            continue
        candidates.append(row)

    logger.info(
        "Gate results: %d passed · %d rejected · %d had no pattern",
        len(candidates), rejected_gates,
        len(price_data) - len(candidates) - rejected_gates,
    )

    if not candidates:
        print("\nNo candidates passed all stringent gates this run.")
        return pd.DataFrame()

    df_res = pd.DataFrame(candidates)

    meta = universe[["ticker", "name", "indices", "region"]].copy()
    df_res = df_res.merge(meta, on="ticker", how="left")
    df_res["indices"] = df_res["indices"].fillna("Unknown")
    df_res["region"]  = df_res["region"].fillna("Unknown")

    df_res["score"] = df_res.apply(_stringent_score, axis=1)
    df_res = df_res.sort_values("score", ascending=False).reset_index(drop=True)
    df_res.insert(0, "rank", df_res.index + 1)

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = os.path.join(results_dir, f"triple_bottom_stringent_{ts}.csv")
    df_res.to_csv(csv_path, index=False)
    logger.info("Stringent results (%d rows) → %s", len(df_res), csv_path)

    _print_results(df_res, top_n, csv_path)
    return df_res


def _print_results(df_res: pd.DataFrame, top_n: int, csv_path: str) -> None:
    print_cols = [
        "rank", "ticker", "indices", "region",
        "price", "neckline", "pct_above_200sma",
        "bottom_variation_pct", "pattern_span_days",
        "breakout_date", "days_since_breakout",
        "pct_above_neckline", "volume_ratio", "rsi14", "score",
    ]
    print_cols = [c for c in print_cols if c in df_res.columns]
    top = df_res.head(top_n)[print_cols].copy()

    for col, fmt in [
        ("pct_above_200sma",    "{:.1f}%"),
        ("bottom_variation_pct", "{:.1f}%"),
        ("pct_above_neckline",  "{:.1f}%"),
        ("volume_ratio",        "{:.1f}×"),
        ("score",               "{:.3f}"),
    ]:
        if col in top.columns:
            top[col] = top[col].apply(
                lambda v: fmt.format(v)
                if v is not None and not (isinstance(v, float) and pd.isna(v))
                else "—"
            )

    if "breakout_date" in top.columns:
        top["breakout_date"] = top["breakout_date"].apply(
            lambda v: str(v)[:10] if v is not None else "—"
        )
    if "pattern_span_days" in top.columns:
        top["pattern_span_days"] = top["pattern_span_days"].apply(
            lambda v: f"{v//252}y {(v%252)//21}m" if v else "—"
        )

    total = len(df_res)
    print(f"\n{'═'*120}")
    print(
        f"  TRIPLE-BOTTOM STRINGENT — Top {top_n} of {total} qualifying candidates   "
        f"[{datetime.now().strftime('%Y-%m-%d')}]"
    )
    print(f"  Gates: 200SMA ≥{MIN_PCT_ABOVE_200SMA}% · Vol ≥{MIN_VOLUME_RATIO}× · Neckline >{MIN_PCT_ABOVE_NECKLINE}%")
    print(f"{'═'*120}")
    print(tabulate(top, headers="keys", tablefmt="rounded_outline", showindex=False))
    print(f"\nFull results → {csv_path}")
    print(
        "\nScore weights: 50% trend (200SMA) · 25% volume · 15% neckline confirmation · 10% bottom tightness\n"
    )

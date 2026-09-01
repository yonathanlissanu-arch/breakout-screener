#!/usr/bin/env python3
"""
monthly_run_stringent.py — Monthly orchestrator for the stringent triple-bottom scanner.

Runs on the 1st of every month (GitHub Actions cron or manual trigger).

Universe: S&P 500 · S&P MidCap 400 · STOXX Europe 600 · Wilshire US Small-Cap 2000

Hard gates applied before scoring:
  pct_above_200sma >= 20%   (in a real uptrend)
  volume_ratio     >= 3.5×  (elevated conviction volume)
  pct_above_neckline > 5%   (confirmed past neckline, not a false break)

Score: 50% trend · 25% volume · 15% neckline · 10% tightness
Positions: top 5 qualifying picks at $20k each ($100k total)

Environment variables (all optional)
-------------------------------------
TOP_N=5           Top picks to take (default 5)
HISTORY_YEARS=5   Years of OHLCV history (default 5)
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    top_n         = int(os.getenv("TOP_N", "5"))
    history_years = int(os.getenv("HISTORY_YEARS", "5"))
    date_str      = datetime.now().strftime("%Y-%m-%d")

    logger.info("═══ Monthly Stringent Triple-Bottom Scan  —  %s ═══", date_str)

    # ── 1. Build universe ──────────────────────────────────────────────────────
    logger.info("Step 1: Building universe …")
    from universe import build_universe
    universe = build_universe(
        sp500=True, midcap400=True, russell2000=False,
        euronext=False, stoxx600=True, wilshire2000=True,
    )
    logger.info("Universe: %d tickers", len(universe))

    # ── 2. Fetch price data ────────────────────────────────────────────────────
    logger.info("Step 2: Downloading %d years of daily prices …", history_years)
    from fetcher_yahoo import fetch_price_data_yahoo
    price_data = fetch_price_data_yahoo(
        universe["ticker"].tolist(), history_years=history_years
    )
    logger.info("Price data: %d tickers", len(price_data))

    # ── 3. Stringent scan ─────────────────────────────────────────────────────
    logger.info("Step 3: Running stringent triple-bottom scan …")
    from screener_triple_bottom_stringent import run_stringent_screen
    results_df = run_stringent_screen(
        price_data, universe, top_n=top_n, results_dir="results"
    )

    # ── 4. Summary output ─────────────────────────────────────────────────────
    logger.info("Step 4: Writing summary …")
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")

    if results_df is None or results_df.empty:
        summary_md = (
            f"## Stringent Triple-Bottom Scanner — {date_str}\n\n"
            f"Universe: {len(universe):,} tickers\n\n"
            "_No candidates passed all hard gates this month._\n\n"
            "_Gates: 200SMA ≥ 20% · Volume ≥ 3.5× · Neckline > 5%_\n"
        )
    else:
        picks = results_df.head(top_n)
        lines = [
            f"## Stringent Triple-Bottom Scanner — {date_str}",
            "",
            f"Universe: **{len(universe):,}** tickers  ·  "
            f"**{len(results_df)}** passed all gates  ·  Top **{len(picks)}** selected",
            "",
            "_Gates: 200SMA ≥ 20% · Volume ≥ 3.5× · Neckline > 5% above neckline_",
            "_Score: 50% trend · 25% volume · 15% neckline · 10% tightness_",
            "",
            f"### Top {len(picks)} Picks",
            "| Rank | Ticker | Region | Price | 200SMA gap | Vol ratio | Neckline ↑ | Span | Score |",
            "|------|--------|--------|-------|------------|-----------|------------|------|-------|",
        ]
        for _, row in picks.iterrows():
            span_days = row.get("pattern_span_days") or 0
            span_str  = f"{span_days//252}y{(span_days%252)//21}m"
            lines.append(
                f"| {int(row['rank'])} | **{row['ticker']}** | {row.get('region','?')} "
                f"| ${row['price']:.2f} "
                f"| {row.get('pct_above_200sma',0):.1f}% "
                f"| {row.get('volume_ratio',0):.1f}× "
                f"| {row.get('pct_above_neckline',0):.1f}% "
                f"| {span_str} "
                f"| {row.get('score',0):.3f} |"
            )
        lines.append("")
        lines.append("_Results → `results/triple_bottom_stringent_*.csv`_")
        summary_md = "\n".join(lines)

    print("\n" + summary_md)
    if summary_path:
        Path(summary_path).write_text(summary_md, encoding="utf-8")
        logger.info("Summary → %s", summary_path)

    # ── 5. Paper portfolio ─────────────────────────────────────────────────────
    if results_df is not None and not results_df.empty:
        logger.info("Step 5: Updating paper portfolio …")
        from portfolio_tb_stringent import (
            add_monthly_cohort, update_all_cohorts, generate_report
        )
        add_monthly_cohort(results_df, top_n=top_n)
        update_all_cohorts()
        generate_report()
        logger.info("Portfolio updated.")
    else:
        logger.info("Step 5: No candidates — skipping portfolio update.")


if __name__ == "__main__":
    main()

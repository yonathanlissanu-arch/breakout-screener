#!/usr/bin/env python3
"""
weekly_run.py — One-shot orchestrator for the Sunday-night cron job.

Steps:
  1. Fetch universe (S&P 500 + MidCap 400, no EU to keep runtime under 30 min)
  2. Download price data via Yahoo Finance (cookie+crumb, no API key)
  3. Run the breakout screen → saves results/breakout_scan_*.csv
  4. Add this week's cohort to the paper portfolio
  5. Update all active cohorts with current prices
  6. Regenerate portfolio/report.html
  7. Print a Markdown summary suitable for a GitHub Actions step summary

Run locally:
    python weekly_run.py

Environment variables (all optional):
    NO_EURONEXT=1   Skip European indices (faster)
    TOP_N=10        Number of top picks (default 10)
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
    no_euronext = os.getenv("NO_EURONEXT", "").strip() in ("1", "true", "yes")
    top_n       = int(os.getenv("TOP_N", "10"))

    from config import CFG
    CFG.top_n = top_n

    # ── 1. Build universe ─────────────────────────────────────────────────────
    logger.info("=== Step 1: Building universe ===")
    from universe import build_universe
    universe = build_universe(
        sp500=True,
        midcap400=True,
        russell2000=True,
        euronext=not no_euronext,
    )
    logger.info("Universe: %d tickers", len(universe))

    # ── 2. Fetch price data ───────────────────────────────────────────────────
    logger.info("=== Step 2: Downloading prices ===")
    from fetcher_yahoo import fetch_price_data_yahoo
    tickers = universe["ticker"].tolist()
    price_data = fetch_price_data_yahoo(tickers, history_years=CFG.history_years)

    # ── 3a. Run breakout screen (long) ────────────────────────────────────────
    logger.info("=== Step 3a: Breakout screen (long) ===")
    from screener import run_screen
    results_df = run_screen(price_data, universe, top_n=top_n)

    # ── 3b. Run breakdown screen (short) ─────────────────────────────────────
    logger.info("=== Step 3b: Breakdown screen (short) ===")
    from screener import run_screen_breakdown
    results_short_df = run_screen_breakdown(price_data, universe, top_n=top_n)

    # ── 4. Add cohorts ────────────────────────────────────────────────────────
    logger.info("=== Step 4: Adding portfolio cohorts ===")
    from portfolio import cmd_add, cmd_add_short
    cmd_add()        # long cohort from breakout scan
    cmd_add_short()  # short cohort from breakdown scan

    # ── 5. Update all active cohorts ──────────────────────────────────────────
    logger.info("=== Step 5: Updating cohort prices ===")
    from portfolio import cmd_update
    cmd_update()

    # ── 6. Generate HTML report ───────────────────────────────────────────────
    logger.info("=== Step 6: Generating report ===")
    from portfolio import cmd_report
    cmd_report()

    # ── 7. GitHub Actions step summary ───────────────────────────────────────
    logger.info("=== Step 7: Writing summary ===")
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    date_str = datetime.now().strftime("%Y-%m-%d")
    lines = [f"## Breakout/Breakdown Screener — {date_str}", "",
             f"Universe: {len(universe):,} tickers", ""]

    if results_df is not None and not results_df.empty:
        lines += [
            f"### Long (Breakout) — {len(results_df)} candidates",
            "| Rank | Ticker | Price | RSI | Vol | Days |",
            "|------|--------|-------|-----|-----|------|",
        ]
        for _, row in results_df.head(top_n).iterrows():
            lines.append(
                f"| {int(row['rank'])} | **{row['ticker']}** "
                f"| ${row['price']:.2f} | {row['rsi14']:.1f} "
                f"| {row['volume_ratio']:.2f}x | {int(row['days_since_breakout'])} |"
            )
        lines.append("")

    if results_short_df is not None and not results_short_df.empty:
        lines += [
            f"### Short (Breakdown) — {len(results_short_df)} candidates",
            "| Rank | Ticker | Price | RSI | Vol | Days |",
            "|------|--------|-------|-----|-----|------|",
        ]
        for _, row in results_short_df.head(top_n).iterrows():
            lines.append(
                f"| {int(row['rank'])} | **{row['ticker']}** "
                f"| ${row['price']:.2f} | {row['rsi14']:.1f} "
                f"| {row['volume_ratio']:.2f}x | {int(row['days_since_breakout'])} |"
            )
        lines.append("")

    lines.append("_Results → `results/` · Portfolio → `portfolio/report.html`_")
    summary_md = "\n".join(lines)
    print("\n" + summary_md)
    if summary_path:
        Path(summary_path).write_text(summary_md)


if __name__ == "__main__":
    main()

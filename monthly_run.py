#!/usr/bin/env python3
"""
monthly_run.py — Monthly orchestrator for the triple-bottom scanner.

Designed to run on the 1st of every month (via GitHub Actions cron or cron job).

Universe: S&P 500 · S&P MidCap 400 · STOXX Europe 600 · Wilshire US Small-Cap 2000

Steps
-----
1. Build universe
2. Download 5-year daily OHLCV via Yahoo Finance
3. Detect multi-year triple-bottom patterns (breakouts + setups)
4. Save ranked CSV to results/
5. Write a Markdown summary (GitHub Actions step summary if GITHUB_STEP_SUMMARY is set)

Environment variables (all optional)
-------------------------------------
TOP_N=20          Number of top results to display (default 20)
INCLUDE_SETUPS=1  Also show setup patterns — not yet broken out (default 1)
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
    top_n           = int(os.getenv("TOP_N", "20"))
    include_setups  = os.getenv("INCLUDE_SETUPS", "1").strip() not in ("0", "false", "no")
    history_years   = int(os.getenv("HISTORY_YEARS", "5"))

    from config import CFG
    CFG.top_n          = top_n
    CFG.history_years  = history_years

    date_str = datetime.now().strftime("%Y-%m-%d")
    logger.info("═══ Monthly Triple-Bottom Scan  —  %s ═══", date_str)

    # ── 1. Build universe ─────────────────────────────────────────────────────
    logger.info("Step 1: Building universe "
                "(S&P 500 + MidCap 400 + STOXX 600 + Wilshire 2000) …")
    from universe import build_universe
    universe = build_universe(
        sp500=True,
        midcap400=True,
        russell2000=False,   # replaced by Wilshire 2000
        euronext=False,      # replaced by STOXX 600
        stoxx600=True,
        wilshire2000=True,
    )
    logger.info("Universe: %d unique tickers", len(universe))

    n        = len(universe)
    batch    = CFG.fetch_batch_size
    batches  = (n + batch - 1) // batch
    est_min  = batches * CFG.fetch_delay_seconds / 60
    print(
        f"\nUniverse: {n:,} tickers   "
        f"Batches: {batches} × {batch}   "
        f"Est. download: ~{est_min:.0f} min\n"
    )

    # ── 2. Fetch price data ───────────────────────────────────────────────────
    logger.info("Step 2: Downloading %d years of daily prices …", history_years)
    from fetcher_yahoo import fetch_price_data_yahoo
    tickers    = universe["ticker"].tolist()
    price_data = fetch_price_data_yahoo(tickers, history_years=history_years)
    logger.info("Price data fetched: %d tickers with data", len(price_data))

    # ── 3. Triple-bottom scan ─────────────────────────────────────────────────
    logger.info(
        "Step 3: Running triple-bottom scan (setups included: %s) …",
        include_setups,
    )
    from screener_triple_bottom import run_triple_bottom_screen
    results_df = run_triple_bottom_screen(
        price_data,
        universe,
        top_n=top_n,
        include_setups=include_setups,
    )

    # ── 4. Summary output ─────────────────────────────────────────────────────
    logger.info("Step 4: Writing summary …")
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")

    if results_df is None or results_df.empty:
        summary_md = (
            f"## Triple-Bottom Scanner — {date_str}\n\n"
            f"Universe: {len(universe):,} tickers\n\n"
            "_No triple-bottom patterns found this month._\n"
        )
    else:
        breakouts = results_df[results_df["pattern_type"] == "triple_bottom_breakout"]
        setups    = results_df[results_df["pattern_type"] == "triple_bottom_setup"]

        lines = [
            f"## Triple-Bottom Scanner — {date_str}",
            "",
            f"Universe: **{len(universe):,}** tickers "
            f"(S&P 500 · MidCap 400 · STOXX 600 · Wilshire 2000)",
            "",
            f"Found **{len(breakouts)}** breakout patterns · **{len(setups)}** setups",
            "",
        ]

        if not breakouts.empty:
            lines += [
                f"### Breakout Patterns (top {min(top_n, len(breakouts))})",
                "| Rank | Ticker | Region | Price | Neckline | % Above | Span | Days | Vol | RSI |",
                "|------|--------|--------|-------|----------|---------|------|------|-----|-----|",
            ]
            for _, row in breakouts.head(top_n).iterrows():
                span_days = row.get("pattern_span_days") or 0
                span_str  = f"{span_days//252}y{(span_days%252)//21}m"
                pct_above = row.get("pct_above_neckline")
                pct_str   = f"{pct_above:.1f}%" if pct_above is not None else "—"
                days      = row.get("days_since_breakout")
                days_str  = str(int(days)) if days is not None else "—"
                vol_r     = row.get("volume_ratio") or 0.0
                rsi       = row.get("rsi14")
                rsi_str   = f"{rsi:.1f}" if rsi is not None else "—"
                lines.append(
                    f"| {int(row['rank'])} | **{row['ticker']}** | {row.get('region','?')} "
                    f"| ${row['price']:.2f} | ${row['neckline']:.2f} | {pct_str} "
                    f"| {span_str} | {days_str} | {vol_r:.1f}× | {rsi_str} |"
                )
            lines.append("")

        if include_setups and not setups.empty:
            lines += [
                f"### Setup Patterns (top {min(top_n, len(setups))} — neckline not yet broken)",
                "| Rank | Ticker | Region | Price | Neckline | % To NL | Span | RSI |",
                "|------|--------|--------|-------|----------|---------|------|-----|",
            ]
            for _, row in setups.head(top_n).iterrows():
                span_days = row.get("pattern_span_days") or 0
                span_str  = f"{span_days//252}y{(span_days%252)//21}m"
                pct_to    = row.get("pct_to_neckline")
                pct_str   = f"{pct_to:.1f}%" if pct_to is not None else "—"
                rsi       = row.get("rsi14")
                rsi_str   = f"{rsi:.1f}" if rsi is not None else "—"
                lines.append(
                    f"| {int(row['rank'])} | **{row['ticker']}** | {row.get('region','?')} "
                    f"| ${row['price']:.2f} | ${row['neckline']:.2f} | {pct_str} "
                    f"| {span_str} | {rsi_str} |"
                )
            lines.append("")

        lines.append("_Results → `results/triple_bottom_scan_*.csv`_")
        summary_md = "\n".join(lines)

    print("\n" + summary_md)
    if summary_path:
        Path(summary_path).write_text(summary_md, encoding="utf-8")
        logger.info("Summary written → %s", summary_path)

    # ── 5. Paper portfolio ────────────────────────────────────────────────────
    if results_df is not None and not results_df.empty:
        logger.info("Step 5: Updating paper portfolio …")
        from portfolio_tb import add_monthly_cohort, update_all_cohorts, generate_report
        add_monthly_cohort(results_df)
        update_all_cohorts()
        report_path = generate_report()
        logger.info("Portfolio report → %s", report_path)
    else:
        logger.info("Step 5: No results — skipping portfolio update.")


if __name__ == "__main__":
    main()

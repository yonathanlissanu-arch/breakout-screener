"""
Monday morning orchestrator for the paper portfolio.

Run order each Monday:
  1. Close last week's open positions using Friday's closing prices.
  2. Run the breakout + breakdown scans on fresh data.
  3. Open new positions for the current week.
  4. Save portfolio state.
  5. Print weekly + cumulative summary.

Usage:
  python weekly_run.py                        # full universe
  python weekly_run.py --no-russell2000       # skip Russell 2000
  python weekly_run.py --dry-run              # scan only, no state update
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime

import pandas as pd

from config import CFG
from fetcher_yahoo import fetch_price_data_yahoo
from portfolio import Portfolio
from screener import run_screen, run_screen_short
from universe import build_universe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _get_latest_prices(price_data: dict) -> dict[str, float]:
    """Extract the most recent closing price for each ticker."""
    result = {}
    for ticker, df in price_data.items():
        if df is not None and not df.empty and "Close" in df.columns:
            val = df["Close"].dropna().iloc[-1]
            result[ticker] = float(val)
    return result


def _get_benchmark_price(price_data: dict, ticker: str) -> float:
    df = price_data.get(ticker)
    if df is not None and not df.empty:
        return float(df["Close"].dropna().iloc[-1])
    logger.warning("%s not in price cache — fetching standalone", ticker)
    data = fetch_price_data_yahoo([ticker], history_years=1)
    df2 = data.get(ticker)
    if df2 is not None and not df2.empty:
        return float(df2["Close"].dropna().iloc[-1])
    logger.error("Could not obtain %s price", ticker)
    return 0.0


# --------------------------------------------------------------------------- #
# Main run
# --------------------------------------------------------------------------- #

def weekly_run(
    sp500: bool = True,
    midcap400: bool = True,
    russell2000: bool = True,
    euronext: bool = False,
    top_n: int = 10,
    dry_run: bool = False,
):
    today = date.today().isoformat()
    logger.info("=== Weekly run started: %s ===", today)

    # ── 1. Build universe ────────────────────────────────────────────────────
    universe = build_universe(
        sp500=sp500,
        midcap400=midcap400,
        russell2000=russell2000,
        euronext=euronext,
    )

    tickers = universe["ticker"].tolist()
    # Always include benchmarks
    for bm in ("SPY", "VTI"):
        if bm not in tickers:
            tickers.append(bm)

    # ── 2. Fetch / refresh price data ────────────────────────────────────────
    logger.info("Fetching price data for %d tickers …", len(tickers))
    price_data = fetch_price_data_yahoo(tickers, history_years=CFG.history_years)

    # ── 3. Close last week's positions ───────────────────────────────────────
    portfolio = Portfolio()
    latest_prices = _get_latest_prices(price_data)
    spy_price = _get_benchmark_price(price_data, "SPY")
    vti_price = _get_benchmark_price(price_data, "VTI")

    if portfolio.state.open_long or portfolio.state.open_short:
        logger.info("Closing week %d positions …", portfolio.state.current_week)
        if not dry_run:
            result = portfolio.close_week(
                close_date=today,
                price_lookup=latest_prices,
                spy_close_price=spy_price,
                vti_close_price=vti_price,
            )
            print(
                f"\nWeek {result.week} closed:  "
                f"Long P&L ${result.long_pnl:+,.0f}  |  "
                f"Short P&L ${result.short_pnl:+,.0f}  |  "
                f"Combined ${result.combined_pnl:+,.0f}  |  "
                f"SPY ${result.spy_pnl:+,.0f}  |  "
                f"VTI ${result.vti_pnl:+,.0f}  |  "
                f"Alpha vs SPY ${result.combined_pnl - result.spy_pnl:+,.0f}"
            )

    # ── 4. Run scans ─────────────────────────────────────────────────────────
    logger.info("Running breakout scan …")
    long_results = run_screen(price_data, universe, top_n=top_n)

    logger.info("Running breakdown scan …")
    short_results = run_screen_short(price_data, universe, top_n=top_n)

    if dry_run:
        logger.info("Dry run — no state update.")
        return long_results, short_results

    # ── 5. Open new positions ────────────────────────────────────────────────
    next_week = portfolio.state.current_week + 1
    logger.info("Opening week %d positions …", next_week)
    portfolio.open_week(
        week=next_week,
        open_date=today,
        long_df=long_results,
        short_df=short_results,
        spy_price=spy_price,
        vti_price=vti_price,
        top_n=top_n,
    )

    portfolio.save()

    # ── 6. Print cumulative summary ──────────────────────────────────────────
    summary = portfolio.cumulative_summary()
    if summary:
        print(f"\n{'═'*70}")
        print(f"  CUMULATIVE PERFORMANCE  (through week {summary['weeks_completed']})")
        print(f"{'═'*70}")
        print(f"  Long portfolio :  ${summary['total_long_pnl']:>+10,.0f}  "
              f"({summary['long_return_pct']:+.1f}%)")
        print(f"  Short portfolio:  ${summary['total_short_pnl']:>+10,.0f}  "
              f"({summary['short_return_pct']:+.1f}%)")
        print(f"  Combined       :  ${summary['total_combined_pnl']:>+10,.0f}  "
              f"({summary['combined_return_pct']:+.1f}%)")
        print(f"  SPY (benchmark):  ${summary['total_spy_pnl']:>+10,.0f}  "
              f"({summary['spy_return_pct']:+.1f}%)")
        print(f"  VTI (benchmark):  ${summary['total_vti_pnl']:>+10,.0f}  "
              f"({summary['vti_return_pct']:+.1f}%)")
        print(f"  Alpha vs SPY   :  ${summary['alpha_vs_spy']:>+10,.0f}")
        print(f"  Alpha vs VTI   :  ${summary['alpha_vs_vti']:>+10,.0f}")
        print(f"{'═'*70}\n")

        # Weekly table
        wt = portfolio.weekly_table()
        if not wt.empty:
            print("Weekly breakdown:")
            print(wt.to_string(index=False))

    logger.info("=== Weekly run complete ===")
    return long_results, short_results


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _parse_args():
    p = argparse.ArgumentParser(description="Monday morning portfolio run")
    p.add_argument("--no-sp500", action="store_true")
    p.add_argument("--no-midcap400", action="store_true")
    p.add_argument("--no-russell2000", action="store_true", default=True,
                   help="Skip Russell 2000 (default: skip — very slow)")
    p.add_argument("--russell2000", action="store_true",
                   help="Include Russell 2000")
    p.add_argument("--euronext", action="store_true",
                   help="Include European indices")
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--dry-run", action="store_true",
                   help="Run scans but don't update portfolio state")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    weekly_run(
        sp500=not args.no_sp500,
        midcap400=not args.no_midcap400,
        russell2000=args.russell2000,
        euronext=args.euronext,
        top_n=args.top_n,
        dry_run=args.dry_run,
    )

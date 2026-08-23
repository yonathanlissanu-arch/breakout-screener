#!/usr/bin/env python3
"""
Breakout Screener — entry point.

Usage examples
--------------
# Full universe (US + Euronext), default config:
  python main.py

# US only (faster):
  python main.py --no-euronext

# Choose data source (default: yfinance — free, no key):
  python main.py --source fmp       # needs FMP_API_KEY env var
  python main.py --source polygon   # needs POLYGON_API_KEY env var

# Quick test on a handful of tickers:
  python main.py --tickers DELL MPC NVDA AAPL TSM

# Force re-download (ignore cache):
  python main.py --refresh

# Widen RSI ceiling (catch more extended names):
  python main.py --rsi-max 80

# Raise max-days-since-breakout window:
  python main.py --max-days 15
"""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from config import CFG
from screener import run_screen
from universe import build_universe


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Multi-year breakout screener (S&P 500 + MidCap 400 + "
                    "Russell 2000 + Euronext / EU indices)"
    )

    # Universe selection
    g = p.add_argument_group("Universe")
    g.add_argument("--no-sp500",       action="store_true", help="Exclude S&P 500")
    g.add_argument("--no-midcap400",   action="store_true", help="Exclude S&P MidCap 400")
    g.add_argument("--no-russell2000", action="store_true", help="Exclude Russell 2000")
    g.add_argument("--no-euronext",    action="store_true", help="Exclude European indices")
    g.add_argument(
        "--tickers", nargs="+", metavar="TICK",
        help="Override: screen only these tickers (space-separated)"
    )

    # Data
    d = p.add_argument_group("Data")
    d.add_argument("--source", choices=["yfinance", "fmp", "polygon"],
                   default="yfinance",
                   help="Data backend (default: yfinance — free, no key needed)")
    d.add_argument("--years",   type=int,   default=CFG.history_years,
                   help=f"Years of history to fetch (default {CFG.history_years})")
    d.add_argument("--refresh", action="store_true",
                   help="Ignore disk cache and re-download everything")

    # Filter overrides
    f = p.add_argument_group("Filter overrides")
    f.add_argument("--max-days", type=int, default=CFG.max_days_since_breakout,
                   help=f"Max trading days since breakout (default {CFG.max_days_since_breakout})")
    f.add_argument("--rsi-min",  type=float, default=CFG.rsi_min,
                   help=f"RSI lower bound (default {CFG.rsi_min})")
    f.add_argument("--rsi-max",  type=float, default=CFG.rsi_max,
                   help=f"RSI upper bound (default {CFG.rsi_max})")
    f.add_argument("--vol-thresh", type=float, default=CFG.volume_surge_threshold,
                   help=f"Volume surge minimum (default {CFG.volume_surge_threshold})")
    f.add_argument("--top",     type=int,   default=CFG.top_n,
                   help=f"Number of top results to display (default {CFG.top_n})")

    # Verbosity
    p.add_argument("-v", "--verbose", action="store_true")

    return p.parse_args()


def main() -> None:
    args = _parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )

    # Apply CLI overrides to config
    CFG.history_years = args.years
    CFG.max_days_since_breakout = args.max_days
    CFG.rsi_min = args.rsi_min
    CFG.rsi_max = args.rsi_max
    CFG.volume_surge_threshold = args.vol_thresh
    CFG.top_n = args.top

    if args.refresh:
        CFG.cache_max_age_hours = 0

    # ── Build universe ────────────────────────────────────────────────────────
    if args.tickers:
        # Ad-hoc list: construct a minimal universe frame
        import pandas as pd
        universe = pd.DataFrame({
            "ticker":  [t.upper() for t in args.tickers],
            "name":    [""] * len(args.tickers),
            "indices": ["Custom"] * len(args.tickers),
            "region":  ["US"] * len(args.tickers),
        })
    else:
        universe = build_universe(
            sp500=not args.no_sp500,
            midcap400=not args.no_midcap400,
            russell2000=not args.no_russell2000,
            euronext=not args.no_euronext,
        )

    # ── Rate / cost advisory ──────────────────────────────────────────────────
    n = len(universe)
    batch = CFG.fetch_batch_size
    batches = (n + batch - 1) // batch
    est_min = batches * CFG.fetch_delay_seconds / 60
    print(
        f"\nUniverse: {n} tickers   "
        f"Batches: {batches} × {batch}   "
        f"Est. download time: ~{est_min:.0f} min "
        f"(yfinance, free, no key required)\n"
    )

    # ── Fetch price data ──────────────────────────────────────────────────────
    tickers = universe["ticker"].tolist()
    if args.source == "fmp":
        from fetcher_fmp import fetch_price_data_fmp
        price_data = fetch_price_data_fmp(tickers, history_years=CFG.history_years)
    elif args.source == "polygon":
        from fetcher_polygon import fetch_price_data_polygon
        price_data = fetch_price_data_polygon(tickers, history_years=CFG.history_years)
    else:
        from fetcher import fetch_price_data
        price_data = fetch_price_data(tickers, history_years=CFG.history_years)

    # ── Screen and rank ───────────────────────────────────────────────────────
    run_screen(price_data, universe, top_n=CFG.top_n)


if __name__ == "__main__":
    main()

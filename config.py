"""
Central configuration for the breakout screener.
Edit values here or override via environment variables / CLI flags.
"""
import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class ScreenerConfig:
    # ── Universe ──────────────────────────────────────────────────────────────
    include_sp500: bool = True
    include_midcap400: bool = True
    include_russell2000: bool = True
    include_euronext: bool = True       # European indices (CAC40, AEX, DAX, MIB, …)

    # ── Data / Cache ──────────────────────────────────────────────────────────
    history_years: int = 5              # years of daily OHLCV to pull
    cache_dir: str = "data/cache"       # parquet files stored here
    results_dir: str = "results"
    cache_max_age_hours: int = 20       # re-fetch if cached data is older than this

    # ── Moving Averages ───────────────────────────────────────────────────────
    sma_periods: List[int] = field(default_factory=lambda: [20, 50, 100, 200])
    ma_rising_lookback: int = 10        # compare SMA today vs N days ago to confirm rising

    # ── Resistance / Breakout ─────────────────────────────────────────────────
    resistance_exclusion_days: int = 10  # exclude last N days from resistance high calc
    resistance_lookback_days: int = 756  # ~3 years of trading days for resistance window
    max_days_since_breakout: int = 10    # only flag breakouts within last N trading days

    # ── Volume ────────────────────────────────────────────────────────────────
    volume_ma_period: int = 50
    volume_surge_threshold: float = 1.5  # breakout-day volume ≥ X × 50-day avg

    # ── RSI ───────────────────────────────────────────────────────────────────
    rsi_period: int = 14
    rsi_min: float = 50.0               # confirmed breakout zone
    rsi_max: float = 75.0               # above this = extended / risky

    # ── Output ────────────────────────────────────────────────────────────────
    top_n: int = 20

    # ── Fetch tuning ──────────────────────────────────────────────────────────
    fetch_batch_size: int = 100         # tickers per yfinance download call
    fetch_delay_seconds: float = 2.0    # pause between batches


CFG = ScreenerConfig()

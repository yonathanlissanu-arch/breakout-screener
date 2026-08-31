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
    # New universe options for triple-bottom scanner
    include_stoxx600: bool = True       # STOXX Europe 600 (broad European)
    include_wilshire2000: bool = True   # Wilshire US Small-Cap 2000

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
    rsi_min: float = 50.0               # confirmed breakout zone (long)
    rsi_max: float = 75.0               # above this = extended / risky (long)
    rsi_short_min: float = 25.0         # breakdown zone (short)
    rsi_short_max: float = 50.0         # above this = recovering, not a short (short)

    # ── Triple Bottom Pattern ─────────────────────────────────────────────────
    tb_lookback_years: int = 5          # years of history to search for the pattern
    tb_tolerance_pct: float = 5.0       # bottoms must all be within this % of each other
    tb_min_separation: int = 40         # min trading days between any two bottoms
    tb_min_pattern_span: int = 252      # min days from first to third bottom (~1 year)
    tb_max_pattern_span: int = 1260     # max days from first to third bottom (~5 years)
    tb_pivot_order: int = 10            # sensitivity: pivot must be local min over ±N bars
    tb_neckline_break_days: int = 60    # flag breakouts above neckline within this window
    tb_vol_surge: float = 1.2           # volume ratio on neckline breakout day

    # ── Output ────────────────────────────────────────────────────────────────
    top_n: int = 20

    # ── Fetch tuning ──────────────────────────────────────────────────────────
    fetch_batch_size: int = 100         # tickers per yfinance download call
    fetch_delay_seconds: float = 2.0    # pause between batches


CFG = ScreenerConfig()

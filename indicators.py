"""
Technical indicator calculations.

All functions take a single ticker's OHLCV DataFrame (auto-adjusted)
and return scalar values or dicts.  Nothing here raises — callers receive
None on any failure and can skip the ticker.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from config import CFG

logger = logging.getLogger(__name__)

MIN_BARS = 220  # need at least this many rows to compute 200-day SMA reliably


# --------------------------------------------------------------------------- #
# Moving averages
# --------------------------------------------------------------------------- #

def compute_smas(closes: pd.Series, periods: list[int] = CFG.sma_periods) -> dict[str, float]:
    result = {}
    for p in periods:
        if len(closes) >= p:
            result[f"sma{p}"] = closes.rolling(p).mean().iloc[-1]
        else:
            result[f"sma{p}"] = float("nan")
    return result


def smas_are_stacked(smas: dict[str, float]) -> bool:
    """20 > 50 > 100 > 200."""
    try:
        return (
            smas["sma20"] > smas["sma50"] > smas["sma100"] > smas["sma200"]
            and not any(np.isnan(v) for v in smas.values())
        )
    except KeyError:
        return False


def smas_are_rising(closes: pd.Series, smas_now: dict[str, float],
                    lookback: int = CFG.ma_rising_lookback) -> bool:
    """Each SMA is higher than its value N days ago."""
    for p in CFG.sma_periods:
        key = f"sma{p}"
        if len(closes) < p + lookback:
            return False
        past_val = closes.iloc[: -lookback].rolling(p).mean().iloc[-1]
        if np.isnan(past_val) or smas_now[key] <= past_val:
            return False
    return True


def smas_are_bearish_stacked(smas: dict[str, float]) -> bool:
    """200 > 100 > 50 > 20 (bearish order)."""
    try:
        return (
            smas["sma200"] > smas["sma100"] > smas["sma50"] > smas["sma20"]
            and not any(np.isnan(v) for v in smas.values())
        )
    except KeyError:
        return False


def smas_are_falling(closes: pd.Series, smas_now: dict[str, float],
                     lookback: int = CFG.ma_rising_lookback) -> bool:
    """Each SMA is lower than its value N days ago."""
    for p in CFG.sma_periods:
        key = f"sma{p}"
        if len(closes) < p + lookback:
            return False
        past_val = closes.iloc[: -lookback].rolling(p).mean().iloc[-1]
        if np.isnan(past_val) or smas_now[key] >= past_val:
            return False
    return True


# --------------------------------------------------------------------------- #
# RSI (Wilder's smoothing)
# --------------------------------------------------------------------------- #

def compute_rsi(closes: pd.Series, period: int = CFG.rsi_period) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder's EMA (alpha = 1/period)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    last_loss = avg_loss.iloc[-1]
    if last_loss == 0:
        return 100.0
    rs = avg_gain.iloc[-1] / last_loss
    return float(100 - 100 / (1 + rs))


# --------------------------------------------------------------------------- #
# Breakout detection
# --------------------------------------------------------------------------- #

def detect_breakout(
    df: pd.DataFrame,
    exclusion_days: int = CFG.resistance_exclusion_days,
    lookback_days: int = CFG.resistance_lookback_days,
    max_days_since: int = CFG.max_days_since_breakout,
    vol_ma_period: int = CFG.volume_ma_period,
    volume_surge_threshold: float = CFG.volume_surge_threshold,
) -> Optional[dict]:
    """
    Detect a multi-year resistance breakout.

    Returns a dict with breakout metrics, or None if no valid breakout found.

    Algorithm
    ---------
    1. resistance = max(close) over the window ending exclusion_days ago
       (multi-year ceiling that price was unable to hold).
    2. A breakout is the first bar where close > resistance, within
       the most recent (exclusion_days + max_days_since) trading days.
    3. The most recent close must still be above resistance (not reversed).
    4. Volume on the breakout bar must be >= surge_threshold × 50-day avg.
    """
    if len(df) < MIN_BARS:
        return None

    closes = df["Close"]
    volumes = df["Volume"]
    n = len(closes)

    # ── Resistance level ─────────────────────────────────────────────────────
    resistance_start = max(0, n - lookback_days)
    resistance_end = n - exclusion_days          # index exclusive upper bound
    if resistance_end <= resistance_start:
        return None

    resistance_level = float(closes.iloc[resistance_start:resistance_end].max())

    # Current bar must be above resistance
    current_close = float(closes.iloc[-1])
    if current_close <= resistance_level:
        return None

    # ── Find the breakout bar ─────────────────────────────────────────────────
    # Scan the "recent window" = last (exclusion_days + max_days_since) bars
    scan_start = max(resistance_end - 1, n - exclusion_days - max_days_since)
    breakout_idx: Optional[int] = None

    for i in range(scan_start, n):
        if closes.iloc[i] > resistance_level:
            # Confirm it's a crossover (previous bar was at or below resistance)
            prev_close = float(closes.iloc[i - 1]) if i > 0 else resistance_level
            if prev_close <= resistance_level:
                breakout_idx = i
            break   # stop at the earliest crossing in the scan window

    if breakout_idx is None:
        # Price entered the window already above resistance — skip; breakout is stale
        return None

    days_since_breakout = n - 1 - breakout_idx
    if days_since_breakout > max_days_since:
        return None

    # ── Volume ratio on breakout day ─────────────────────────────────────────
    vol_window_start = max(0, breakout_idx - vol_ma_period)
    avg_vol_50 = float(volumes.iloc[vol_window_start:breakout_idx].mean())
    if avg_vol_50 == 0:
        return None
    breakout_volume = float(volumes.iloc[breakout_idx])
    volume_ratio = breakout_volume / avg_vol_50

    if volume_ratio < volume_surge_threshold:
        return None

    return {
        "resistance_level": resistance_level,
        "breakout_date": df.index[breakout_idx],
        "days_since_breakout": days_since_breakout,
        "pct_above_resistance": (current_close - resistance_level) / resistance_level * 100,
        "volume_ratio": volume_ratio,
        "breakout_volume": breakout_volume,
        "avg_vol_50": avg_vol_50,
    }


# --------------------------------------------------------------------------- #
# Breakdown detection (bearish mirror of detect_breakout)
# --------------------------------------------------------------------------- #

def detect_breakdown(
    df: pd.DataFrame,
    exclusion_days: int = CFG.resistance_exclusion_days,
    lookback_days: int = CFG.resistance_lookback_days,
    max_days_since: int = CFG.max_days_since_breakout,
    vol_ma_period: int = CFG.volume_ma_period,
    volume_surge_threshold: float = CFG.volume_surge_threshold,
) -> Optional[dict]:
    """
    Detect a multi-year support breakdown (bearish mirror of detect_breakout).

    Algorithm
    ---------
    1. support = min(close) over the window ending exclusion_days ago.
    2. A breakdown is the first bar where close < support, within
       the most recent (exclusion_days + max_days_since) trading days.
    3. The most recent close must still be below support (not reversed).
    4. Volume on the breakdown bar must be >= surge_threshold × 50-day avg.
    """
    if len(df) < MIN_BARS:
        return None

    closes = df["Close"]
    volumes = df["Volume"]
    n = len(closes)

    support_start = max(0, n - lookback_days)
    support_end = n - exclusion_days
    if support_end <= support_start:
        return None

    support_level = float(closes.iloc[support_start:support_end].min())

    current_close = float(closes.iloc[-1])
    if current_close >= support_level:
        return None

    scan_start = max(support_end - 1, n - exclusion_days - max_days_since)
    breakdown_idx: Optional[int] = None

    for i in range(scan_start, n):
        if closes.iloc[i] < support_level:
            prev_close = float(closes.iloc[i - 1]) if i > 0 else support_level
            if prev_close >= support_level:
                breakdown_idx = i
            break

    if breakdown_idx is None:
        return None

    days_since_breakdown = n - 1 - breakdown_idx
    if days_since_breakdown > max_days_since:
        return None

    vol_window_start = max(0, breakdown_idx - vol_ma_period)
    avg_vol_50 = float(volumes.iloc[vol_window_start:breakdown_idx].mean())
    if avg_vol_50 == 0:
        return None
    breakdown_volume = float(volumes.iloc[breakdown_idx])
    volume_ratio = breakdown_volume / avg_vol_50

    if volume_ratio < volume_surge_threshold:
        return None

    return {
        "support_level": support_level,
        "breakout_date": df.index[breakdown_idx],   # reuse field name for portfolio compat
        "days_since_breakout": days_since_breakdown,
        "pct_below_support": (support_level - current_close) / support_level * 100,
        "volume_ratio": volume_ratio,
        "breakout_volume": breakdown_volume,
        "avg_vol_50": avg_vol_50,
    }


# --------------------------------------------------------------------------- #
# All-in-one analysis for one ticker
# --------------------------------------------------------------------------- #

def analyse_ticker(ticker: str, df: pd.DataFrame) -> Optional[dict]:
    """
    Run the full analysis pipeline on one ticker's OHLCV DataFrame.
    Returns a result dict on success, None if any filter fails.
    """
    try:
        closes = df["Close"].dropna()
        if len(closes) < MIN_BARS:
            return None

        current_price = float(closes.iloc[-1])

        # ── SMAs ─────────────────────────────────────────────────────────────
        smas = compute_smas(closes)
        if not smas_are_stacked(smas):
            return None

        # Price must be above all SMAs
        if not all(current_price > v and not np.isnan(v) for v in smas.values()):
            return None

        if not smas_are_rising(closes, smas):
            return None

        # ── Breakout ──────────────────────────────────────────────────────────
        bo = detect_breakout(df)
        if bo is None:
            return None

        # ── RSI ───────────────────────────────────────────────────────────────
        rsi = compute_rsi(closes)
        if rsi is None or not (CFG.rsi_min <= rsi <= CFG.rsi_max):
            return None

        # ── Distance from 200-day SMA (extension proxy) ───────────────────────
        pct_above_200 = (current_price - smas["sma200"]) / smas["sma200"] * 100

        return {
            "ticker": ticker,
            "price": round(current_price, 2),
            "sma20": round(smas["sma20"], 2),
            "sma50": round(smas["sma50"], 2),
            "sma100": round(smas["sma100"], 2),
            "sma200": round(smas["sma200"], 2),
            "pct_above_200sma": round(pct_above_200, 1),
            "rsi14": round(rsi, 1),
            **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in bo.items()},
        }

    except Exception:
        logger.debug("Analysis failed for %s", ticker, exc_info=True)
        return None


def analyse_ticker_short(ticker: str, df: pd.DataFrame) -> Optional[dict]:
    """
    Bearish mirror of analyse_ticker — identifies breakdown candidates for paper shorting.
    Requires bearish MA stack (200>100>50>20, all falling), price below all SMAs,
    fresh support breakdown with volume, RSI 25-50.
    """
    try:
        closes = df["Close"].dropna()
        if len(closes) < MIN_BARS:
            return None

        current_price = float(closes.iloc[-1])

        smas = compute_smas(closes)
        if not smas_are_bearish_stacked(smas):
            return None

        if not all(current_price < v and not np.isnan(v) for v in smas.values()):
            return None

        if not smas_are_falling(closes, smas):
            return None

        bd = detect_breakdown(df)
        if bd is None:
            return None

        rsi = compute_rsi(closes)
        if rsi is None or not (CFG.rsi_short_min <= rsi <= CFG.rsi_short_max):
            return None

        pct_below_200 = (smas["sma200"] - current_price) / smas["sma200"] * 100

        return {
            "ticker": ticker,
            "price": round(current_price, 2),
            "sma20": round(smas["sma20"], 2),
            "sma50": round(smas["sma50"], 2),
            "sma100": round(smas["sma100"], 2),
            "sma200": round(smas["sma200"], 2),
            "pct_below_200sma": round(pct_below_200, 1),
            "rsi14": round(rsi, 1),
            **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in bd.items()},
        }

    except Exception:
        logger.debug("Short analysis failed for %s", ticker, exc_info=True)
        return None

"""
LongRunner-2D signal engine.

This reproduces the exact math from the audited C1_SLOPE_AND_LONGRUNNER2D_FROZEN.py
for the LongRunner-2D leg only (no slope filter -- that's a C1-Slope-only rule).
Do not tweak the math here without re-running it through the full discovery/test
backtest first; this file is meant to be a faithful live port, not a place to
iterate on new ideas.

Signal rule per day:
  - Compute intraday VWAP, residual = close/vwap - 1, rolling-12-bar z-score of residual.
  - Scan bars from index 12 (10:30am ET) onward for the FIRST bar where |z| >= Z_THRESHOLD.
  - If that first event is oversold (z <= -Z_THRESHOLD) -> LONG signal for the day.
  - If that first event is overbought (z > -Z_THRESHOLD, i.e. positive) -> no trade that day
    (LongRunner-2D is long-only).
  - If no |z| >= threshold event occurs that day -> no trade.
Entry is the OPEN of the bar immediately after the signal bar (same day).
Exit is the CLOSE of the 2nd subsequent trading session's last bar.
"""
import numpy as np
import pandas as pd
import config as C


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Adds vwap, residual, z, to a multi-day 5-min bar DataFrame (columns:
    date, open, high, low, close, volume, bar). Computed per-day (VWAP and the
    rolling z-score both reset at each day's open), matching the frozen script."""
    df = df.copy().sort_values(["date", "bar"]).reset_index(drop=True)
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    df["vwap"] = (
        (typical * df["volume"]).groupby(df["date"]).cumsum()
        / df["volume"].groupby(df["date"]).cumsum()
    )
    df["residual"] = df["close"] / df["vwap"] - 1.0
    df["sigma"] = (
        df.groupby("date")["residual"]
          .rolling(C.SIGMA_WINDOW, min_periods=C.SIGMA_WINDOW)
          .std(ddof=0)
          .reset_index(level=0, drop=True)
    )
    df["z"] = df["residual"] / df["sigma"]
    return df


def find_signal_for_date(df: pd.DataFrame, target_date) -> dict | None:
    """Scans `target_date`'s bars for the first LongRunner-2D long signal.
    Returns None if no signal, or a dict with signal_bar/entry_bar/entry_price
    if a tradeable long signal fired and its entry bar already exists in the
    fetched data (i.e. the signal did not occur on the very last bar of the day)."""
    g = df[df["date"] == target_date].reset_index(drop=True)
    if len(g) < C.MIN_SIGNAL_BAR + 2:
        return None

    signal_bar = None
    for j in range(C.MIN_SIGNAL_BAR, len(g) - 1):
        z = g.loc[j, "z"]
        if np.isfinite(z) and abs(z) >= C.Z_THRESHOLD:
            signal_bar = j
            break

    if signal_bar is None:
        return None

    z = float(g.loc[signal_bar, "z"])
    if z > -C.Z_THRESHOLD:
        return None  # first event was overbought -> LongRunner-2D skips the day (long-only)

    entry_bar = signal_bar + 1
    if entry_bar >= len(g):
        return None  # signal fired on the last available bar; nothing to enter on yet

    return {
        "signal_date": target_date,
        "signal_bar": signal_bar,
        "signal_time_et": g.loc[signal_bar, "timestamp_et"],
        "z": z,
        "entry_bar": entry_bar,
        "entry_time_et": g.loc[entry_bar, "timestamp_et"],
        "entry_price": float(g.loc[entry_bar, "open"]),
    }

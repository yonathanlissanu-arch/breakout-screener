"""
Download daily OHLCV data via yfinance, cache to parquet.

Cache strategy
--------------
One parquet file per ticker lives in <cache_dir>/<ticker>.parquet.
A file is considered stale if its mtime is older than cache_max_age_hours.
On the next run only stale/missing tickers are re-fetched.
"""

import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf
from tqdm import tqdm

from config import CFG

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Cache helpers
# --------------------------------------------------------------------------- #

def _cache_path(ticker: str, cache_dir: str) -> Path:
    safe = ticker.replace("/", "_").replace("\\", "_")
    return Path(cache_dir) / f"{safe}.parquet"


def _is_stale(path: Path, max_age_hours: int) -> bool:
    if not path.exists():
        return True
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age > timedelta(hours=max_age_hours)


def _load_cached(ticker: str, cache_dir: str) -> Optional[pd.DataFrame]:
    p = _cache_path(ticker, cache_dir)
    if p.exists():
        try:
            return pd.read_parquet(p)
        except Exception:
            pass
    return None


def _save_cache(ticker: str, df: pd.DataFrame, cache_dir: str) -> None:
    os.makedirs(cache_dir, exist_ok=True)
    p = _cache_path(ticker, cache_dir)
    df.to_parquet(p)


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #

def _download_batch(tickers: List[str], period: str) -> Dict[str, pd.DataFrame]:
    """
    Download a batch of tickers in one yfinance call.
    Returns { ticker: ohlcv_df } for successful downloads.
    """
    if not tickers:
        return {}

    if len(tickers) == 1:
        raw = yf.download(
            tickers[0],
            period=period,
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
        if raw.empty:
            return {}
        return {tickers[0]: raw}

    raw = yf.download(
        tickers,
        period=period,
        interval="1d",
        auto_adjust=True,
        group_by="ticker",
        progress=False,
        threads=True,
    )
    if raw.empty:
        return {}

    result: Dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        try:
            df = raw[ticker].dropna(how="all")
            if not df.empty and len(df) >= 60:
                result[ticker] = df
        except (KeyError, TypeError):
            pass
    return result


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def fetch_price_data(
    tickers: List[str],
    history_years: int = CFG.history_years,
    cache_dir: str = CFG.cache_dir,
    cache_max_age_hours: int = CFG.cache_max_age_hours,
    batch_size: int = CFG.fetch_batch_size,
    delay: float = CFG.fetch_delay_seconds,
) -> Dict[str, pd.DataFrame]:
    """
    Return OHLCV DataFrames for every ticker that has sufficient history.
    Uses disk cache to avoid re-downloading on repeated runs.
    """
    os.makedirs(cache_dir, exist_ok=True)
    period = f"{history_years}y"

    fresh: Dict[str, pd.DataFrame] = {}
    to_download: List[str] = []

    # Serve from cache where possible
    for ticker in tickers:
        p = _cache_path(ticker, cache_dir)
        if not _is_stale(p, cache_max_age_hours):
            df = _load_cached(ticker, cache_dir)
            if df is not None and not df.empty:
                fresh[ticker] = df
                continue
        to_download.append(ticker)

    logger.info(
        "%d tickers cached, %d to download", len(fresh), len(to_download)
    )

    # Batch-download the rest
    batches = [
        to_download[i : i + batch_size]
        for i in range(0, len(to_download), batch_size)
    ]

    for batch in tqdm(batches, desc="Downloading", unit="batch"):
        downloaded = _download_batch(batch, period)
        for ticker, df in downloaded.items():
            _save_cache(ticker, df, cache_dir)
            fresh[ticker] = df
        # Log skipped tickers
        skipped = set(batch) - set(downloaded)
        for t in skipped:
            logger.debug("No data for %s", t)
        if delay > 0 and batch != batches[-1]:
            time.sleep(delay)

    logger.info(
        "Price data ready for %d / %d tickers", len(fresh), len(tickers)
    )
    return fresh

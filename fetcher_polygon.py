"""
Polygon.io data fetcher.

Free tier:  5 calls/min, unlimited historical daily bars
            → 2,700 tickers takes ~9 hours (one-off; cached after that)
Starter ~$29/mo: unlimited calls/min → full scan in ~3-5 min

Sign up free: https://polygon.io/

Set your key:
    export POLYGON_API_KEY=your_key_here
or add to .env:
    POLYGON_API_KEY=your_key_here

Note: Polygon's free tier has end-of-day data delayed by 15 min.
      European / Euronext tickers are sparse on Polygon — use FMP for EU.
"""

import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests
from tqdm import tqdm

from config import CFG

logger = logging.getLogger(__name__)

_BASE = "https://api.polygon.io/v2"
_SESSION = requests.Session()
_SESSION.verify = os.environ.get("REQUESTS_CA_BUNDLE", True)


def _get_key() -> str:
    key = os.environ.get("POLYGON_API_KEY", "")
    if not key:
        raise ValueError(
            "POLYGON_API_KEY not set. Export it or add to .env:\n"
            "  export POLYGON_API_KEY=your_key_here"
        )
    return key


def _cache_path(ticker: str, cache_dir: str) -> Path:
    safe = ticker.replace("/", "_").replace("\\", "_")
    return Path(cache_dir) / f"{safe}.parquet"


def _is_stale(path: Path, max_age_hours: int) -> bool:
    if not path.exists():
        return True
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age > timedelta(hours=max_age_hours)


def _fetch_one(ticker: str, from_date: str, to_date: str, api_key: str) -> Optional[pd.DataFrame]:
    """
    Fetch daily OHLCV from Polygon for one ticker.
    Handles pagination (Polygon returns max 5000 bars per call).
    """
    url = f"{_BASE}/aggs/ticker/{ticker}/range/1/day/{from_date}/{to_date}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 5000,
        "apiKey": api_key,
    }
    all_results = []
    try:
        while url:
            r = _SESSION.get(url, params=params, timeout=30)
            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", 60))
                logger.warning("Polygon rate limit — sleeping %ds", retry_after)
                time.sleep(retry_after)
                r = _SESSION.get(url, params=params, timeout=30)
            if r.status_code == 404:
                return None  # ticker not found
            r.raise_for_status()
            data = r.json()
            results = data.get("results", [])
            all_results.extend(results)
            # Follow next_url for pagination
            url = data.get("next_url")
            params = {"apiKey": api_key}  # next_url already has other params baked in
        if not all_results:
            return None
        df = pd.DataFrame(all_results)
        df["date"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_localize(None)
        df = df.set_index("date").sort_index()
        df = df.rename(columns={
            "o": "Open", "h": "High", "l": "Low",
            "c": "Close", "v": "Volume",
        })
        return df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    except Exception as exc:
        logger.debug("Polygon fetch failed for %s: %s", ticker, exc)
        return None


def fetch_price_data_polygon(
    tickers: List[str],
    history_years: int = CFG.history_years,
    cache_dir: str = CFG.cache_dir,
    cache_max_age_hours: int = CFG.cache_max_age_hours,
    delay: float = 12.0,          # 12s between calls = 5/min (free tier limit)
                                  # Set to 0.1 on Starter/paid tier
) -> Dict[str, pd.DataFrame]:
    """
    Same interface as fetcher.fetch_price_data() but uses Polygon.io.
    """
    os.makedirs(cache_dir, exist_ok=True)
    api_key = _get_key()
    today = datetime.today()
    from_date = (today - timedelta(days=365 * history_years)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    fresh: Dict[str, pd.DataFrame] = {}
    to_download: List[str] = []

    for ticker in tickers:
        p = _cache_path(ticker, cache_dir)
        if not _is_stale(p, cache_max_age_hours):
            try:
                df = pd.read_parquet(p)
                if not df.empty:
                    fresh[ticker] = df
                    continue
            except Exception:
                pass
        to_download.append(ticker)

    logger.info("%d cached, %d to download via Polygon", len(fresh), len(to_download))
    if to_download and delay >= 12:
        est_hours = len(to_download) * delay / 3600
        logger.info(
            "Free tier: ~%.1f hours for initial download. "
            "Run overnight; cached after that.",
            est_hours,
        )

    for ticker in tqdm(to_download, desc="Polygon download", unit="ticker"):
        # Polygon uses plain ticker (no exchange suffix) for US stocks
        poly_ticker = ticker.split(".")[0]
        df = _fetch_one(poly_ticker, from_date, to_date, api_key)
        if df is not None and len(df) >= 60:
            p = _cache_path(ticker, cache_dir)
            df.to_parquet(p)
            fresh[ticker] = df
        if delay > 0 and ticker != to_download[-1]:
            time.sleep(delay)

    logger.info("Polygon: data ready for %d / %d tickers", len(fresh), len(tickers))
    return fresh

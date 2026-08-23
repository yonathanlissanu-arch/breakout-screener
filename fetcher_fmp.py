"""
FMP (Financial Modeling Prep) data fetcher.

Free tier: ~250 API calls/day   → initial scan takes ~11 days (one-off; cached after)
Basic tier ~$14/mo: 300 calls/min → full 2,700-ticker universe in ~9 min

Sign up free: https://financialmodelingprep.com/developer/docs/

Set your key:
    export FMP_API_KEY=your_key_here
or add to .env:
    FMP_API_KEY=your_key_here
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

_BASE = "https://financialmodelingprep.com/api/v3"
_SESSION = requests.Session()
_SESSION.verify = os.environ.get("REQUESTS_CA_BUNDLE", True)


def _get_key() -> str:
    key = os.environ.get("FMP_API_KEY", "")
    if not key:
        raise ValueError(
            "FMP_API_KEY not set. Export it or add to .env:\n"
            "  export FMP_API_KEY=your_key_here"
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


def _fetch_one(ticker: str, from_date: str, api_key: str) -> Optional[pd.DataFrame]:
    """Fetch full daily OHLCV for one ticker from FMP."""
    url = f"{_BASE}/historical-price-full/{ticker}"
    params = {"from": from_date, "apikey": api_key}
    try:
        r = _SESSION.get(url, params=params, timeout=30)
        if r.status_code == 429:
            logger.warning("FMP rate limit hit — sleeping 60s")
            time.sleep(60)
            r = _SESSION.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        hist = data.get("historical", [])
        if not hist:
            return None
        df = pd.DataFrame(hist)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        df = df.rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "adjClose": "Adj Close", "volume": "Volume",
        })
        # Use adjusted close for Close (consistent with yfinance auto_adjust)
        if "Adj Close" in df.columns:
            df["Close"] = df["Adj Close"]
        return df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    except Exception as exc:
        logger.debug("FMP fetch failed for %s: %s", ticker, exc)
        return None


def fetch_price_data_fmp(
    tickers: List[str],
    history_years: int = CFG.history_years,
    cache_dir: str = CFG.cache_dir,
    cache_max_age_hours: int = CFG.cache_max_age_hours,
    delay: float = 0.25,          # 0.25s → ~240 calls/min on paid; ~4/min free
) -> Dict[str, pd.DataFrame]:
    """
    Same interface as fetcher.fetch_price_data() but uses FMP.
    """
    os.makedirs(cache_dir, exist_ok=True)
    api_key = _get_key()
    from_date = (datetime.today() - timedelta(days=365 * history_years)).strftime("%Y-%m-%d")

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

    logger.info("%d cached, %d to download via FMP", len(fresh), len(to_download))

    for ticker in tqdm(to_download, desc="FMP download", unit="ticker"):
        df = _fetch_one(ticker, from_date, api_key)
        if df is not None and len(df) >= 60:
            p = _cache_path(ticker, cache_dir)
            df.to_parquet(p)
            fresh[ticker] = df
        if delay > 0:
            time.sleep(delay)

    logger.info("FMP: data ready for %d / %d tickers", len(fresh), len(tickers))
    return fresh

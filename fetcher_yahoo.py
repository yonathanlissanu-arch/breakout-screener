"""
Yahoo Finance fetcher using cookie+crumb authentication.
No API key needed. Works through the proxy CA bundle.

Uses the v8/finance/chart endpoint directly (same data as yfinance
but bypasses curl_cffi's TLS stack that clashes with the proxy).
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

_CCR_CA = "/root/.ccr/ca-bundle.crt"
_CA = os.environ.get("REQUESTS_CA_BUNDLE") or (
    _CCR_CA if os.path.exists(_CCR_CA) else True
)
_CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
_CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
_HOME_URL  = "https://finance.yahoo.com/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.6367.82 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class _YahooSession:
    """Manages a cookie+crumb authenticated session for Yahoo Finance."""

    def __init__(self):
        self._session = requests.Session()
        self._session.verify = _CA
        self._session.headers.update(_HEADERS)
        self._crumb: Optional[str] = None
        self._crumb_ts: float = 0.0

    def _refresh(self) -> bool:
        """Get a fresh cookie set and crumb. Returns True on success."""
        try:
            r = self._session.get(_HOME_URL, timeout=20)
            r.raise_for_status()
            time.sleep(2)
            r2 = self._session.get(
                _CRUMB_URL, timeout=15,
                headers={"Accept": "*/*", "Referer": _HOME_URL},
            )
            if r2.status_code == 200 and r2.text.strip():
                self._crumb = r2.text.strip()
                self._crumb_ts = time.time()
                logger.debug("Yahoo crumb refreshed: %s…", self._crumb[:6])
                return True
        except Exception as exc:
            logger.warning("Yahoo session refresh failed: %s", exc)
        return False

    def get_crumb(self) -> Optional[str]:
        age = time.time() - self._crumb_ts
        if self._crumb is None or age > 3600:  # refresh every hour
            self._refresh()
        return self._crumb

    def fetch_ticker(
        self,
        ticker: str,
        history_years: int,
        max_retries: int = 3,
    ) -> Optional[pd.DataFrame]:
        crumb = self.get_crumb()
        if crumb is None:
            return None

        params = {
            "interval": "1d",
            "range": f"{history_years}y",
            "crumb": crumb,
            "includePrePost": "false",
        }
        headers = {"Referer": f"https://finance.yahoo.com/quote/{ticker}/"}

        for attempt in range(max_retries):
            try:
                url = _CHART_URL.format(ticker=ticker)
                r = self._session.get(url, params=params, headers=headers, timeout=20)

                if r.status_code == 429:
                    wait = 30 * (attempt + 1)
                    logger.debug("429 on %s — sleeping %ds", ticker, wait)
                    time.sleep(wait)
                    continue

                if r.status_code == 401:
                    # Crumb expired; refresh and retry
                    logger.debug("401 on %s — refreshing crumb", ticker)
                    self._crumb = None
                    crumb = self.get_crumb()
                    params["crumb"] = crumb
                    continue

                if r.status_code in (404, 400):
                    return None  # ticker not found

                r.raise_for_status()
                data = r.json()
                result = data.get("chart", {}).get("result")
                if not result:
                    return None

                meta       = result[0]["meta"]
                timestamps = result[0].get("timestamp", [])
                quotes     = result[0]["indicators"]["quote"][0]
                adj_close_list = result[0].get("indicators", {}).get("adjclose", [{}])
                adj_closes = adj_close_list[0].get("adjclose", []) if adj_close_list else []

                if not timestamps:
                    return None

                df = pd.DataFrame({
                    "Open":   quotes.get("open",   []),
                    "High":   quotes.get("high",   []),
                    "Low":    quotes.get("low",    []),
                    "Close":  adj_closes if adj_closes else quotes.get("close", []),
                    "Volume": quotes.get("volume", []),
                }, index=pd.to_datetime(timestamps, unit="s", utc=True).tz_localize(None))
                df.index.name = "Date"
                df = df.dropna(how="all").dropna(subset=["Close"])
                return df if len(df) >= 60 else None

            except Exception as exc:
                logger.debug("Attempt %d failed for %s: %s", attempt + 1, ticker, exc)
                time.sleep(5 * (attempt + 1))

        return None


# Module-level session (reused across all calls)
_YAHOO = _YahooSession()


def _cache_path(ticker: str, cache_dir: str) -> Path:
    safe = ticker.replace("/", "_").replace("\\", "_")
    return Path(cache_dir) / f"{safe}.parquet"


def _is_stale(path: Path, max_age_hours: int) -> bool:
    if not path.exists():
        return True
    return datetime.now() - datetime.fromtimestamp(path.stat().st_mtime) > timedelta(
        hours=max_age_hours
    )


def fetch_price_data_yahoo(
    tickers: List[str],
    history_years: int = CFG.history_years,
    cache_dir: str = CFG.cache_dir,
    cache_max_age_hours: int = CFG.cache_max_age_hours,
    delay: float = 0.35,
) -> Dict[str, pd.DataFrame]:
    """
    Same interface as fetcher.fetch_price_data() but uses direct Yahoo
    Finance API calls (no curl_cffi — works through the proxy CA bundle).
    """
    os.makedirs(cache_dir, exist_ok=True)

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

    logger.info("%d cached, %d to download", len(fresh), len(to_download))

    for ticker in tqdm(to_download, desc="Yahoo download", unit="ticker"):
        df = _YAHOO.fetch_ticker(ticker, history_years)
        if df is not None:
            _cache_path(ticker, cache_dir).parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(_cache_path(ticker, cache_dir))
            fresh[ticker] = df
        time.sleep(delay)

    logger.info("Yahoo: data ready for %d / %d tickers", len(fresh), len(tickers))
    return fresh

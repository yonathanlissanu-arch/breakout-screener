"""
Build the ticker universe from multiple index sources.

Sources (all free / no API key required):
  S&P 500       – Wikipedia table
  S&P MidCap400 – Wikipedia table
  Russell 2000  – iShares IWM holdings CSV (free download)
  Euronext/EU   – Wikipedia tables for CAC40, AEX, DAX, FTSE MIB,
                   IBEX 35, BEL 20, PSI 20, OMX indices, OBX
"""

import io
import os
import time
import logging
from typing import Dict, List, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_CCR_CA = "/root/.ccr/ca-bundle.crt"
_CA = os.environ.get("REQUESTS_CA_BUNDLE") or (
    _CCR_CA if os.path.exists(_CCR_CA) else True
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_SESSION = requests.Session()
_SESSION.verify = _CA
_SESSION.headers.update(_HEADERS)


def _get(url: str, **kwargs) -> requests.Response:
    resp = _SESSION.get(url, timeout=30, **kwargs)
    resp.raise_for_status()
    return resp


def _wiki_tables(url: str) -> List[pd.DataFrame]:
    """Fetch Wikipedia page via requests (respects proxy CA), then parse HTML."""
    html = _get(url).text
    return pd.read_html(io.StringIO(html), flavor="lxml")


# --------------------------------------------------------------------------- #
# S&P 500
# --------------------------------------------------------------------------- #

def fetch_sp500() -> pd.DataFrame:
    """Return DataFrame with columns: ticker, name, index."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    tables = _wiki_tables(url)
    df = tables[0]
    # Wikipedia column is 'Symbol'
    df = df.rename(columns={"Symbol": "ticker", "Security": "name"})
    df["ticker"] = df["ticker"].str.replace(".", "-", regex=False)  # BRK.B → BRK-B
    df["index"] = "S&P 500"
    return df[["ticker", "name", "index"]].dropna(subset=["ticker"])


# --------------------------------------------------------------------------- #
# S&P MidCap 400
# --------------------------------------------------------------------------- #

def fetch_midcap400() -> pd.DataFrame:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
    tables = _wiki_tables(url)
    # Find table with a 'Ticker symbol' or 'Symbol' column
    for t in tables:
        cols = [c.lower() for c in t.columns]
        if any("tick" in c or "symbol" in c for c in cols):
            col_map = {c: c.lower() for c in t.columns}
            t = t.rename(columns=col_map)
            tick_col = next(c for c in t.columns if "tick" in c or "symbol" in c)
            name_col = next((c for c in t.columns if "compan" in c or "secur" in c or "name" in c), None)
            df = t.rename(columns={tick_col: "ticker"})
            if name_col:
                df = df.rename(columns={name_col: "name"})
            else:
                df["name"] = ""
            df["ticker"] = df["ticker"].str.replace(".", "-", regex=False)
            df["index"] = "S&P MidCap 400"
            return df[["ticker", "name", "index"]].dropna(subset=["ticker"])
    raise ValueError("Could not find ticker column in S&P MidCap 400 Wikipedia page")


# --------------------------------------------------------------------------- #
# Russell 2000  (via iShares IWM holdings CSV)
# --------------------------------------------------------------------------- #

def fetch_russell2000() -> pd.DataFrame:
    """
    Fetch Russell 2000 constituents.

    Strategy (tries in order):
    1. iShares IWM holdings CSV (requires cookie acceptance — often fails headlessly)
    2. Wikipedia Russell 2000 Index page (lists a subset of notable members)

    The Russell 2000 has ~2,000 components; Wikipedia only lists a sample.
    For the full list, sign up for a free FTSE Russell data account or use
    a paid API (Polygon/FMP both have constituent endpoints).
    """
    # ── Attempt 1: iShares CSV ────────────────────────────────────────────────
    iwm_url = (
        "https://www.ishares.com/us/products/239710/"
        "ishares-russell-2000-etf/1467271812596.ajax"
        "?fileType=csv&fileName=IWM_holdings&dataType=fund"
    )
    try:
        resp = _get(iwm_url, allow_redirects=True)
        if "<html" not in resp.text[:200].lower():
            # Skip the two header lines with fund metadata
            lines = resp.text.splitlines()
            # Find the line that starts with 'Name,' or 'Ticker,'
            data_start = next(
                (i for i, l in enumerate(lines) if l.startswith(("Name,", "Ticker,", '"Name"'))),
                2,
            )
            csv_body = "\n".join(lines[data_start:])
            df = pd.read_csv(io.StringIO(csv_body))
            if "Asset Class" in df.columns:
                df = df[df["Asset Class"] == "Equity"]
            tick_col = next(
                (c for c in df.columns if c.lower() in ("ticker", "symbol")), None
            )
            name_col = next((c for c in df.columns if "name" in c.lower()), None)
            if tick_col:
                df = df.rename(columns={tick_col: "ticker"})
                df["name"] = df[name_col] if name_col else ""
                df["ticker"] = (
                    df["ticker"].astype(str).str.strip().str.replace(".", "-", regex=False)
                )
                df = df[df["ticker"].str.match(r"^[A-Z0-9\-]+$")]
                df["index"] = "Russell 2000"
                result = df[["ticker", "name", "index"]].dropna(subset=["ticker"])
                if len(result) > 100:
                    logger.info("  Russell 2000 (iShares): %d tickers", len(result))
                    return result
    except Exception as exc:
        logger.debug("iShares IWM fetch failed: %s", exc)

    # ── Attempt 2: Wikipedia (partial list of ~100 notable names) ────────────
    try:
        tables = _wiki_tables("https://en.wikipedia.org/wiki/Russell_2000_Index")
        for t in tables:
            cols_lower = [c.lower() for c in t.columns]
            if any("tick" in c or "symbol" in c for c in cols_lower):
                tick_col = next(c for c in t.columns if "tick" in c.lower() or "symbol" in c.lower())
                name_col = next((c for c in t.columns if "name" in c.lower() or "compan" in c.lower()), None)
                df = t.rename(columns={tick_col: "ticker"})
                df["name"] = df[name_col] if name_col else ""
                df["ticker"] = df["ticker"].astype(str).str.strip().str.replace(".", "-", regex=False)
                df = df[df["ticker"].str.match(r"^[A-Z0-9\-]+$")]
                df["index"] = "Russell 2000"
                result = df[["ticker", "name", "index"]].dropna(subset=["ticker"])
                if not result.empty:
                    logger.warning(
                        "Russell 2000: only %d tickers from Wikipedia (partial). "
                        "For full ~2000-name list, use Polygon or FMP API.",
                        len(result),
                    )
                    return result
    except Exception as exc:
        logger.debug("Wikipedia Russell 2000 fetch failed: %s", exc)

    logger.warning("Russell 2000: could not fetch constituent list. Skipping.")
    return pd.DataFrame(columns=["ticker", "name", "index"])


# --------------------------------------------------------------------------- #
# European / Euronext indices
# --------------------------------------------------------------------------- #

# (wikipedia_url, yfinance_suffix, index_label, ticker_col_hint)
_EU_INDICES: List[Tuple[str, str, str, str]] = [
    # Euronext markets
    ("https://en.wikipedia.org/wiki/CAC_40",       ".PA", "CAC 40",          "Ticker"),
    ("https://en.wikipedia.org/wiki/AEX_index",    ".AS", "AEX",             "Ticker"),
    ("https://en.wikipedia.org/wiki/BEL_20",       ".BR", "BEL 20",          "Ticker"),
    ("https://en.wikipedia.org/wiki/PSI-20",       ".LS", "PSI 20",          "Ticker"),
    ("https://en.wikipedia.org/wiki/OBX_Index",    ".OL", "OBX (Oslo)",      "Ticker"),
    # Euronext Milan (acquired 2021)
    ("https://en.wikipedia.org/wiki/FTSE_MIB",     ".MI", "FTSE MIB",        "Ticker"),
    # Major non-Euronext but important European exchanges
    ("https://en.wikipedia.org/wiki/DAX",          ".DE", "DAX",             "Ticker"),
    ("https://en.wikipedia.org/wiki/IBEX_35",      ".MC", "IBEX 35",         "Ticker"),
    ("https://en.wikipedia.org/wiki/OMX_Stockholm_30", ".ST", "OMX Stockholm 30", "Ticker"),
    ("https://en.wikipedia.org/wiki/OMX_Copenhagen_25", ".CO", "OMX Copenhagen 25", "Ticker"),
    ("https://en.wikipedia.org/wiki/OMX_Helsinki_25", ".HE", "OMX Helsinki 25", "Ticker"),
]

# Hand-corrected overrides where Wikipedia ticker ≠ Yahoo Finance ticker
# Format: { "WIKI_TICKER.SUFFIX": "YAHOO_TICKER" }
_TICKER_OVERRIDES: Dict[str, str] = {
    "BNP.PA": "BNP.PA",
    "GLEN.DE": "GLEN.L",    # Glencore trades on London, not Frankfurt
    "SHEL.DE": "SHELL.AS",  # Shell moved primary listing to Amsterdam
    "RDSA.AS": "SHELL.AS",
    "RDSB.AS": "SHELL.AS",
    "AIR.PA": "AIR.PA",     # Airbus – confirmed
}


def _find_ticker_col(df: pd.DataFrame, hint: str) -> str | None:
    """Return the column name that most likely holds ticker symbols."""
    for candidate in [hint, "Ticker", "Symbol", "ISIN", "Code", "Abbr."]:
        for col in df.columns:
            if isinstance(col, str) and candidate.lower() in col.lower():
                return col
    return None


def _find_name_col(df: pd.DataFrame) -> str | None:
    for candidate in ["Company", "Name", "Security", "Issuer"]:
        for col in df.columns:
            if isinstance(col, str) and candidate.lower() in col.lower():
                return col
    return None


def fetch_eu_index(url: str, suffix: str, label: str, hint: str) -> pd.DataFrame:
    try:
        tables = _wiki_tables(url)
    except Exception as exc:
        logger.warning("Could not fetch %s (%s)", label, exc)
        return pd.DataFrame(columns=["ticker", "name", "index"])

    for table in tables:
        tick_col = _find_ticker_col(table, hint)
        if tick_col is None:
            continue
        name_col = _find_name_col(table)
        df = table.copy()
        df["_ticker"] = df[tick_col].astype(str).str.strip()
        df["name"] = df[name_col] if name_col else ""
        # Drop rows that look like headers or notes
        df = df[df["_ticker"].str.match(r"^[A-Z][A-Z0-9\.]{0,9}$")]
        if df.empty:
            continue
        # Append exchange suffix
        df["ticker"] = df["_ticker"].apply(
            lambda t: _TICKER_OVERRIDES.get(f"{t}{suffix}", f"{t}{suffix}")
        )
        df["index"] = label
        return df[["ticker", "name", "index"]]

    logger.warning("No usable table found for %s at %s", label, url)
    return pd.DataFrame(columns=["ticker", "name", "index"])


def fetch_euronext() -> pd.DataFrame:
    frames = []
    for url, suffix, label, hint in _EU_INDICES:
        df = fetch_eu_index(url, suffix, label, hint)
        if not df.empty:
            logger.info("  %s: %d tickers", label, len(df))
        frames.append(df)
        time.sleep(0.5)   # be polite to Wikipedia
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["ticker", "name", "index"]
    )


# --------------------------------------------------------------------------- #
# Combined universe
# --------------------------------------------------------------------------- #

def build_universe(
    sp500: bool = True,
    midcap400: bool = True,
    russell2000: bool = True,
    euronext: bool = True,
) -> pd.DataFrame:
    """
    Return deduplicated DataFrame: ticker | name | index | region.
    If a ticker appears in multiple indices, the first occurrence wins
    for 'index' but all memberships are captured in 'index_list'.
    """
    frames = []
    if sp500:
        logger.info("Fetching S&P 500 …")
        frames.append(fetch_sp500())
    if midcap400:
        logger.info("Fetching S&P MidCap 400 …")
        frames.append(fetch_midcap400())
    if russell2000:
        logger.info("Fetching Russell 2000 …")
        frames.append(fetch_russell2000())
    if euronext:
        logger.info("Fetching European indices …")
        frames.append(fetch_euronext())

    if not frames:
        raise ValueError("No universe selected.")

    combined = pd.concat(frames, ignore_index=True)
    combined["ticker"] = combined["ticker"].str.upper().str.strip()

    # Aggregate index memberships, deduplicate on ticker
    membership = (
        combined.groupby("ticker")["index"]
        .apply(lambda s: " / ".join(s.unique()))
        .reset_index()
        .rename(columns={"index": "indices"})
    )
    first_occ = combined.drop_duplicates("ticker")[["ticker", "name"]]
    universe = first_occ.merge(membership, on="ticker")
    universe["region"] = universe["indices"].apply(
        lambda s: "Europe" if any(
            x in s for x in ("CAC", "AEX", "DAX", "MIB", "IBEX", "BEL", "PSI",
                             "OMX", "OBX", "Euronext")
        ) else "US"
    )

    logger.info(
        "Universe: %d unique tickers  (US=%d, EU=%d)",
        len(universe),
        (universe["region"] == "US").sum(),
        (universe["region"] == "Europe").sum(),
    )
    return universe.reset_index(drop=True)

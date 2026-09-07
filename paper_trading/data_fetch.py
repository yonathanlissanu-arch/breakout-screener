"""
Fetch recent 5-min RTH bars for the paper trading engine.

Uses yfinance. Intraday 5-min data from Yahoo is only available for a
recent rolling window (last ~60 days), which is more than enough buffer
for LongRunner-2D's short (~3 trading day) hold period.
"""
import pandas as pd
import yfinance as yf
import config as C


def fetch_recent_bars(ticker: str = C.TICKER, lookback: str = C.YFINANCE_LOOKBACK) -> pd.DataFrame:
    """Returns a DataFrame of 5-min RTH bars with columns:
    timestamp_et (tz-aware, America/New_York), date, open, high, low, close, volume
    Raises RuntimeError if no data is returned (e.g. network issue, bad ticker)."""
    raw = yf.download(
        tickers=ticker,
        period=lookback,
        interval=C.YFINANCE_INTERVAL,
        prepost=False,
        auto_adjust=False,
        progress=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker} (lookback={lookback})")

    # yfinance sometimes returns a MultiIndex column frame even for a single ticker
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] for c in raw.columns]

    df = raw.reset_index()
    ts_col = "Datetime" if "Datetime" in df.columns else df.columns[0]
    df = df.rename(columns={
        ts_col: "timestamp", "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume"
    })[["timestamp", "open", "high", "low", "close", "volume"]]

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["timestamp_et"] = df["timestamp"].dt.tz_convert("America/New_York")
    df["date"] = df["timestamp_et"].dt.date

    # Keep RTH only (yfinance 5m data should already be RTH-only for equities, but filter defensively)
    df = df[(df["timestamp_et"].dt.time >= pd.Timestamp("09:30").time()) &
            (df["timestamp_et"].dt.time <= pd.Timestamp("16:00").time())]

    df = df.sort_values("timestamp_et").reset_index(drop=True)
    df["bar"] = df.groupby("date").cumcount()
    return df

# Breakout Screener

Screen S&P 500, S&P MidCap 400, Russell 2000, and major European indices
for stocks that have **just broken out above multi-year resistance** with:

- Fully bullish MA stack (20 > 50 > 100 > 200, all rising)
- Volume ≥ 1.5× 50-day average on the breakout day
- RSI(14) between 50 and 75 (confirmed but not exhausted)
- Breakout within the last 10 trading days

Results are ranked by a composite score weighting recency, volume surge,
and nearness to the 200-day SMA (earlier-stage = higher score).

## Quick start

```bash
pip install -r requirements.txt

# Full scan — US + European indices (~30–60 min on first run, cached after)
python main.py

# US only (faster — ~15 min first run)
python main.py --no-euronext

# Test a specific list of tickers instantly
python main.py --tickers DELL MPC NVDA AAPL MSFT META

# Widen the window — catch breakouts up to 15 days ago, RSI up to 80
python main.py --max-days 15 --rsi-max 80

# Force re-download (bypass 20-hour cache)
python main.py --refresh
```

## Data source

**yfinance** (Yahoo Finance wrapper) — free, no API key required.
Data is cached as Parquet files in `data/cache/` and reused for 20 hours.

### When to upgrade to a paid API

| Tier | Situation |
|------|-----------|
| yfinance (free) | Development, daily personal scans |
| Polygon Starter ~$29/mo | Need reliable intraday or real-time data |
| FMP Basic ~$29/mo | Need bulk constituent lists via API + cleaner EU coverage |

To switch backends, implement a `fetcher_fmp.py` or `fetcher_polygon.py`
with the same `fetch_price_data()` signature and swap the import in `main.py`.

## Universe

| Index | Count | Source |
|-------|-------|--------|
| S&P 500 | ~500 | Wikipedia |
| S&P MidCap 400 | ~400 | Wikipedia |
| Russell 2000 | ~2000 | iShares IWM holdings CSV |
| European (CAC 40, AEX, DAX, FTSE MIB, IBEX 35, BEL 20, PSI 20, OMX, OBX) | ~300 | Wikipedia |

> **Note on "Wilshire 2000" vs "Russell 2000":** The Russell 2000 is the
> standard US small-cap benchmark. The Wilshire US Small-Cap is a related
> but separate index. The screener uses Russell 2000 (IWM proxy).

## Euronext / European coverage

Wikipedia tables are scraped for each major index.  Exchange suffixes are
added automatically so yfinance can find the right listings:

| Suffix | Exchange |
|--------|----------|
| `.PA` | Euronext Paris (CAC 40) |
| `.AS` | Euronext Amsterdam (AEX) |
| `.BR` | Euronext Brussels (BEL 20) |
| `.LS` | Euronext Lisbon (PSI 20) |
| `.OL` | Euronext Oslo (OBX) |
| `.MI` | Euronext Milan / Borsa Italiana (FTSE MIB) |
| `.DE` | XETRA Frankfurt (DAX) |
| `.MC` | Bolsa Madrid (IBEX 35) |
| `.ST` | Nasdaq Stockholm (OMX 30) |
| `.CO` | Nasdaq Copenhagen (OMX 25) |
| `.HE` | Nasdaq Helsinki (OMX 25) |

> Polygon.io and FMP both have **thin Euronext coverage** on free tiers.
> For production Euronext scans, Euronext's own market data API or
> EODHD (~$20/month) gives better coverage than Polygon/FMP.

## Output

Every run produces:
- **Console table** — top N candidates ranked by composite score
- **`results/breakout_scan_YYYYMMDD_HHMM.csv`** — full list of all tickers
  that passed every filter

## Filter parameters (all overridable via CLI)

| Parameter | Default | CLI flag |
|-----------|---------|----------|
| Max days since breakout | 10 | `--max-days` |
| RSI range | 50–75 | `--rsi-min` / `--rsi-max` |
| Volume surge minimum | 1.5× | `--vol-thresh` |
| History years | 5 | `--years` |
| Top N displayed | 20 | `--top` |

## Ranking score

```
recency_score  = 1 / (days_since_breakout + 1)
volume_score   = min(volume_ratio / 1.5, 3) / 3
extension_norm = min(1 / (pct_above_200sma/100 + 0.05) / 20, 1)

composite = 0.45 × recency + 0.30 × volume + 0.25 × extension
```

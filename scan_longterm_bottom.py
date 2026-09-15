#!/usr/bin/env python3
"""
Long-Term Triple Bottom Scanner
================================
Scans S&P 500, S&P MidCap 400, NASDAQ 100, Euro STOXX 600, and Wilshire 2000
for triple-bottom formations visible on 10-15 year charts.

The screen targets stocks that are currently AT or near the multi-year support
zone — no confirmed neckline breakout is required.  This is a setup/base screen,
not a momentum screen.

Pattern criteria
----------------
- Three distinct pivot lows at approximately the same price level
- Pattern spans at least 2 years (first bottom → third bottom)
- Pattern spans at most 14 years
- All three bottoms within 8% of each other
- Third bottom (most recent touch of support) within the last 3 years
- Current price is below the neckline (still in the base)
- Current price is within 50% above the average bottom (truly at the bottom)

Usage
-----
  python scan_longterm_bottom.py
  python scan_longterm_bottom.py --top 60
  python scan_longterm_bottom.py --tickers INTC WBA PFE BTI VOD
  python scan_longterm_bottom.py --refresh          # ignore disk cache
  python scan_longterm_bottom.py --no-stoxx600      # skip Euro STOXX 600
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from tabulate import tabulate

# ── Config overrides (must happen before importing anything that reads CFG) ──
from config import CFG

CFG.history_years        = 15          # 15 years of daily OHLCV
CFG.cache_dir            = "data/cache_15y"   # separate cache for 15yr data
CFG.tb_lookback_years    = 15          # search the full 15-year window
CFG.tb_min_pattern_span  = 504         # first→third bottom: at least 2 years
CFG.tb_max_pattern_span  = 3528        # first→third bottom: at most 14 years
CFG.tb_pivot_order       = 20          # wider pivot detection for long-term charts
CFG.tb_tolerance_pct     = 8.0         # bottoms within 8% of each other
CFG.tb_neckline_break_days = 756       # 3rd bottom must be within last ~3 years
CFG.tb_vol_surge         = 0.5         # very light volume filter for setups
CFG.top_n                = 50


# --------------------------------------------------------------------------- #
# Scoring — "at the bottom" relevance
# --------------------------------------------------------------------------- #

_MAX_BOTTOM_PCT  = 50.0   # ignore setups where price has risen >50% off avg bottom
_MAX_BELOW_PCT   = 10.0   # ignore setups where price has fallen >10% below avg bottom (support broke)

def _score_at_bottom(row: pd.Series) -> float:
    """
    Rank candidates by how compelling a long-term base they represent.

    Factors (higher = better candidate):
      longevity  : pattern spans closer to 10 years (more significant support)
      tightness  : three bottoms are very close together
      proximity  : current price is close to the average bottom
      freshness  : third bottom was touched recently
    """
    span      = row.get("pattern_span_days") or 252
    var_pct   = row.get("bottom_variation_pct") or 8.0
    prox_pct  = row.get("pct_above_avg_bottom") or 50.0
    b3_days   = row.get("days_since_b3") or 756

    longevity  = min(span / (252 * 10), 1.0)              # full credit at 10yr span
    tightness  = max(0.0, 1.0 - var_pct / 8.0)
    proximity  = max(0.0, 1.0 - prox_pct / _MAX_BOTTOM_PCT)
    freshness  = max(0.0, 1.0 - b3_days / 756.0)

    return 0.30 * longevity + 0.25 * tightness + 0.25 * proximity + 0.20 * freshness


# --------------------------------------------------------------------------- #
# Detection wrapper with post-filter
# --------------------------------------------------------------------------- #

def _analyse_for_bottom(ticker: str, df: pd.DataFrame) -> Optional[dict]:
    """
    Run triple-bottom detection and return a result only if the stock is
    genuinely AT the multi-year support level (setup, not broken out).
    """
    from indicators import analyse_ticker_triple_bottom, compute_rsi, compute_smas

    row = analyse_ticker_triple_bottom(ticker, df)
    if row is None:
        return None

    # Keep only setup patterns (not confirmed neckline breakouts)
    if row.get("pattern_type") != "triple_bottom_setup":
        return None

    # Pattern must span at least 2 years
    if (row.get("pattern_span_days") or 0) < CFG.tb_min_pattern_span:
        return None

    # Current price must be within _MAX_BOTTOM_PCT above avg bottom
    avg_bot = row.get("avg_bottom") or 0
    price   = row.get("price") or 0
    if avg_bot <= 0 or price <= 0:
        return None
    pct_above = (price - avg_bot) / avg_bot * 100
    # Too far above support (has already recovered)
    if pct_above > _MAX_BOTTOM_PCT:
        return None
    # Significantly below support (support zone broke — not a setup)
    if pct_above < -_MAX_BELOW_PCT:
        return None

    # Compute days since third bottom
    b3_date = row.get("bottom3_date")
    if b3_date is not None:
        try:
            days_since_b3 = (pd.Timestamp.today() - pd.Timestamp(b3_date)).days
        except Exception:
            days_since_b3 = None
    else:
        days_since_b3 = None

    row["pct_above_avg_bottom"] = round(pct_above, 1)
    row["days_since_b3"]        = days_since_b3

    return row


# --------------------------------------------------------------------------- #
# Main scan
# --------------------------------------------------------------------------- #

def run_longterm_bottom_scan(
    price_data: Dict[str, pd.DataFrame],
    universe: pd.DataFrame,
    top_n: int = CFG.top_n,
    results_dir: str = CFG.results_dir,
) -> pd.DataFrame:
    os.makedirs(results_dir, exist_ok=True)

    from tqdm import tqdm

    results: List[dict] = []
    tickers = list(price_data.keys())
    logging.getLogger(__name__).info(
        "Scanning %d tickers for long-term triple-bottom setups …", len(tickers)
    )

    for ticker in tqdm(tickers, desc="Long-term bottom scan", unit="ticker"):
        df = price_data[ticker]
        row = _analyse_for_bottom(ticker, df)
        if row is not None:
            results.append(row)

    if not results:
        print("\nNo long-term triple-bottom setups found.")
        return pd.DataFrame()

    df_res = pd.DataFrame(results)

    # Merge index / name metadata
    meta = universe[["ticker", "name", "indices", "region"]].copy()
    df_res = df_res.merge(meta, on="ticker", how="left")
    df_res["indices"] = df_res["indices"].fillna("Unknown")
    df_res["region"]  = df_res["region"].fillna("Unknown")

    # Score and rank
    df_res["score"] = df_res.apply(_score_at_bottom, axis=1)
    df_res = df_res.sort_values("score", ascending=False).reset_index(drop=True)
    df_res.insert(0, "rank", df_res.index + 1)

    # Save CSV
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = os.path.join(results_dir, f"longterm_bottom_scan_{ts}.csv")
    df_res.to_csv(csv_path, index=False)

    # ── Console summary ───────────────────────────────────────────────────────
    print_cols = [
        "rank", "ticker", "name", "indices", "region",
        "price", "avg_bottom", "neckline",
        "bottom1_date", "bottom2_date", "bottom3_date",
        "bottom_variation_pct", "pattern_span_days",
        "pct_above_avg_bottom", "pct_to_neckline",
        "days_since_b3", "rsi14", "score",
    ]
    print_cols = [c for c in print_cols if c in df_res.columns]
    top = df_res.head(top_n)[print_cols].copy()

    # Format columns
    for col, fmt in [
        ("bottom_variation_pct",  "{:.1f}%"),
        ("pct_above_avg_bottom",  "{:.1f}%"),
        ("pct_to_neckline",       "{:.1f}%"),
        ("score",                 "{:.3f}"),
    ]:
        if col in top.columns:
            top[col] = top[col].apply(
                lambda v, f=fmt: f.format(v)
                if v is not None and not (isinstance(v, float) and pd.isna(v)) else "—"
            )

    for date_col in ("bottom1_date", "bottom2_date", "bottom3_date"):
        if date_col in top.columns:
            top[date_col] = top[date_col].apply(
                lambda v: str(v)[:7] if v is not None else "—"  # show YYYY-MM
            )

    if "pattern_span_days" in top.columns:
        top["pattern_span_days"] = top["pattern_span_days"].apply(
            lambda v: f"{v // 252}y {(v % 252) // 21}m" if v else "—"
        )

    if "days_since_b3" in top.columns:
        top["days_since_b3"] = top["days_since_b3"].apply(
            lambda v: f"{int(v) // 30}mo" if v is not None else "—"
        )

    n_found = len(df_res)
    print(f"\n{'═' * 130}")
    print(
        f"  LONG-TERM TRIPLE-BOTTOM SCREEN — {n_found} setups found · "
        f"showing top {min(top_n, n_found)}   "
        f"[{datetime.now().strftime('%Y-%m-%d')}]"
    )
    print(f"  Universe: S&P 500 · MidCap 400 · NASDAQ 100 · Euro STOXX 600 · Wilshire 2000")
    print(f"  Pattern: 3 bottoms within 8% of each other · spanning 2–14 years · 3rd bottom ≤ 3 yrs ago")
    print(f"{'═' * 130}")
    print(tabulate(top, headers="keys", tablefmt="rounded_outline", showindex=False))
    print(f"\nFull results ({n_found} rows) → {csv_path}")
    print(
        "\nScore weights: 30% pattern age · 25% bottom tightness · "
        "25% proximity to support · 20% recency of last touch\n"
    )

    # ── HTML report ───────────────────────────────────────────────────────────
    _write_html_report(df_res, top_n, ts, results_dir)

    return df_res


# --------------------------------------------------------------------------- #
# HTML report
# --------------------------------------------------------------------------- #

def _write_html_report(df: pd.DataFrame, top_n: int, ts: str, results_dir: str) -> None:
    html_path = os.path.join(results_dir, f"longterm_bottom_{ts}.html")

    rows_html = ""
    for _, r in df.head(top_n).iterrows():
        span_str = ""
        span_days = r.get("pattern_span_days")
        if span_days:
            y = int(span_days) // 252
            m = (int(span_days) % 252) // 21
            span_str = f"{y}y {m}m"

        b3_days = r.get("days_since_b3")
        b3_str = f"{int(b3_days) // 30}mo ago" if b3_days else "—"

        def _d(v):
            return str(v)[:7] if v is not None else "—"

        pct_ab = r.get("pct_above_avg_bottom")
        pct_ab_str = f"+{pct_ab:.1f}%" if pct_ab is not None else "—"

        pct_nl = r.get("pct_to_neckline")
        pct_nl_str = f"{pct_nl:.1f}% below" if pct_nl is not None else "—"

        var = r.get("bottom_variation_pct")
        var_str = f"{var:.1f}%" if var is not None else "—"

        score = r.get("score")
        score_str = f"{score:.3f}" if score is not None else "—"

        rows_html += f"""
        <tr>
          <td class="rank">{int(r.get('rank', 0))}</td>
          <td class="ticker"><strong>{r.get('ticker', '')}</strong></td>
          <td class="name">{r.get('name', '')}</td>
          <td>{r.get('indices', '')}</td>
          <td class="num">${r.get('price', 0):.2f}</td>
          <td class="num">${r.get('avg_bottom', 0):.2f}</td>
          <td class="num pct-above">{pct_ab_str}</td>
          <td class="num">${r.get('neckline', 0):.2f}</td>
          <td class="num pct-nl">{pct_nl_str}</td>
          <td>{_d(r.get('bottom1_date'))} · {_d(r.get('bottom2_date'))} · {_d(r.get('bottom3_date'))}</td>
          <td class="num">{span_str}</td>
          <td class="num">{b3_str}</td>
          <td class="num">{var_str}</td>
          <td class="num">{r.get('rsi14', '—')}</td>
          <td class="num score">{score_str}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Long-Term Triple Bottom Screen · {ts[:8]}</title>
<style>
  :root {{
    --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3e;
    --text: #e2e8f0; --muted: #94a3b8; --accent: #38bdf8;
    --green: #4ade80; --amber: #fbbf24; --red: #f87171;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'SF Mono', 'Cascadia Code', monospace; font-size: 13px; padding: 24px; }}
  h1 {{ font-size: 20px; color: var(--accent); margin-bottom: 4px; }}
  .subtitle {{ color: var(--muted); font-size: 12px; margin-bottom: 16px; }}
  .criteria {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; color: var(--muted); font-size: 11px; line-height: 1.6; }}
  .criteria strong {{ color: var(--text); }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{ background: var(--surface); color: var(--muted); font-weight: 600; text-transform: uppercase; font-size: 10px; letter-spacing: 0.05em; padding: 8px 10px; border-bottom: 2px solid var(--border); text-align: left; white-space: nowrap; }}
  tbody tr:hover {{ background: rgba(56,189,248,0.04); }}
  td {{ padding: 7px 10px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
  td.rank {{ color: var(--muted); font-size: 11px; width: 30px; }}
  td.ticker {{ font-weight: 700; color: var(--accent); white-space: nowrap; }}
  td.name {{ color: var(--muted); max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  td.num {{ text-align: right; white-space: nowrap; }}
  td.pct-above {{ color: var(--green); }}
  td.pct-nl {{ color: var(--amber); }}
  td.score {{ color: var(--accent); font-weight: 700; }}
  .footer {{ margin-top: 20px; color: var(--muted); font-size: 11px; }}
</style>
</head>
<body>
<h1>Long-Term Triple Bottom Screen</h1>
<p class="subtitle">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · Top {min(top_n, len(df))} of {len(df)} setups found</p>
<div class="criteria">
  <strong>Universe:</strong> S&amp;P 500 · S&amp;P MidCap 400 · NASDAQ 100 · Euro STOXX 600 · Wilshire 2000
  &nbsp;|&nbsp; <strong>Chart period:</strong> 10–15 years
  &nbsp;|&nbsp; <strong>Pattern:</strong> 3 bottoms within 8% of each other, spanning 2–14 years
  &nbsp;|&nbsp; <strong>Filter:</strong> 3rd bottom ≤ 3 yrs ago · still below neckline · price ≤ +50% of avg support
  <br/>
  <strong>Score:</strong> 30% pattern age · 25% bottom tightness · 25% proximity to support · 20% recency of last touch
</div>
<table>
<thead>
<tr>
  <th>#</th><th>Ticker</th><th>Name</th><th>Index</th>
  <th>Price</th><th>Avg Bottom</th><th>% Above Spt</th><th>Neckline</th><th>To Neckline</th>
  <th>Bottom Dates</th><th>Span</th><th>Last Touch</th><th>Variation</th><th>RSI14</th><th>Score</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
<p class="footer">Avg Bottom = mean of 3 pivot lows · % Above Spt = how far current price is above the support zone · To Neckline = distance to neckline (breakout target)</p>
</body>
</html>"""

    with open(html_path, "w") as f:
        f.write(html)
    print(f"HTML report → {html_path}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Long-term triple-bottom scanner (10-15 year charts)"
    )
    p.add_argument("--tickers", nargs="+", metavar="TICK",
                   help="Screen only these tickers (override universe)")
    p.add_argument("--no-sp500",      action="store_true", help="Exclude S&P 500")
    p.add_argument("--no-midcap400",  action="store_true", help="Exclude MidCap 400")
    p.add_argument("--no-nasdaq100",  action="store_true", help="Exclude NASDAQ 100")
    p.add_argument("--no-stoxx600",   action="store_true", help="Exclude Euro STOXX 600")
    p.add_argument("--no-wilshire",   action="store_true", help="Exclude Wilshire 2000")
    p.add_argument("--top",     type=int,   default=CFG.top_n,
                   help=f"Number of results to display (default {CFG.top_n})")
    p.add_argument("--refresh", action="store_true", help="Ignore disk cache")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.refresh:
        CFG.cache_max_age_hours = 0

    CFG.top_n = args.top

    # ── Build universe ────────────────────────────────────────────────────────
    if args.tickers:
        universe = pd.DataFrame({
            "ticker":  [t.upper() for t in args.tickers],
            "name":    [""] * len(args.tickers),
            "indices": ["Custom"] * len(args.tickers),
            "region":  ["US"] * len(args.tickers),
        })
    else:
        from universe import build_universe
        universe = build_universe(
            sp500      =not args.no_sp500,
            midcap400  =not args.no_midcap400,
            russell2000=False,          # not requested
            euronext   =False,          # covered by stoxx600
            stoxx600   =not args.no_stoxx600,
            wilshire2000=not args.no_wilshire,
            nasdaq100  =not args.no_nasdaq100,
        )

    n = len(universe)
    print(f"\nUniverse: {n} tickers · fetching up to 15 years of daily data …")
    print("(First run may take 30-90 min for large universes; subsequent runs use cache)\n")

    # ── Fetch price data ──────────────────────────────────────────────────────
    from fetcher_yahoo import fetch_price_data_yahoo
    price_data = fetch_price_data_yahoo(
        universe["ticker"].tolist(),
        history_years=CFG.history_years,
        cache_dir=CFG.cache_dir,
        cache_max_age_hours=CFG.cache_max_age_hours,
        delay=0.4,
    )

    # ── Screen ────────────────────────────────────────────────────────────────
    run_longterm_bottom_scan(price_data, universe, top_n=args.top)


if __name__ == "__main__":
    main()

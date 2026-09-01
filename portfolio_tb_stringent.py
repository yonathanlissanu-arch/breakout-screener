"""
Paper portfolio tracker for the monthly triple-bottom STRINGENT cohorts.

Identical in structure to portfolio_tb.py but:
  - Storage: portfolio/tb_stringent_cohorts.json
  - Default capital $100k / top-5 picks = $20k per position
  - Only picks that passed the hard gates (pre-filtered by the screener)

Public API (mirrors portfolio_tb)
----------------------------------
  add_monthly_cohort(results_df, cohort_date, capital, top_n)
  update_all_cohorts()
  generate_report() → str
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

PORTFOLIO_DIR   = Path("portfolio")
COHORTS_FILE    = PORTFOLIO_DIR / "tb_stringent_cohorts.json"
REPORT_FILE     = PORTFOLIO_DIR / "tb_stringent_report.html"
BENCHMARKS      = ["SPY", "VTI"]
DEFAULT_CAPITAL = 100_000
DEFAULT_TOP_N   = 7          # stringent = fewer, higher-conviction picks


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #

def _load() -> dict:
    PORTFOLIO_DIR.mkdir(exist_ok=True)
    if COHORTS_FILE.exists():
        return json.loads(COHORTS_FILE.read_text(encoding="utf-8"))
    return {"cohorts": []}


def _save(data: dict) -> None:
    PORTFOLIO_DIR.mkdir(exist_ok=True)
    COHORTS_FILE.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Price fetching
# --------------------------------------------------------------------------- #

def _fetch_latest_prices(tickers: List[str]) -> Dict[str, float]:
    from fetcher_yahoo import fetch_price_data_yahoo
    price_data = fetch_price_data_yahoo(tickers, history_years=1)
    return {
        t: float(df["Close"].dropna().iloc[-1])
        for t, df in price_data.items()
        if not df.empty and not df["Close"].dropna().empty
    }


# --------------------------------------------------------------------------- #
# Add cohort
# --------------------------------------------------------------------------- #

def add_monthly_cohort(
    results_df: pd.DataFrame,
    cohort_date: Optional[date] = None,
    capital: int = DEFAULT_CAPITAL,
    top_n: int = DEFAULT_TOP_N,
) -> Optional[dict]:
    """
    Add a new monthly cohort from the stringent screener results.
    The results_df is already pre-filtered — every row passed the hard gates.
    """
    cohort_date = cohort_date or date.today()
    cohort_id   = cohort_date.strftime("%Y-%m")

    data = _load()
    if any(c["id"] == cohort_id for c in data["cohorts"]):
        logger.info("Cohort %s already exists — skipping.", cohort_id)
        return None

    picks = results_df.head(top_n)
    if picks.empty:
        logger.warning("No stringent candidates for cohort %s.", cohort_id)
        return None

    tickers     = picks["ticker"].tolist()
    all_tickers = tickers + BENCHMARKS
    logger.info("Cohort %s: fetching entry prices for %d picks + benchmarks …",
                cohort_id, len(tickers))
    prices = _fetch_latest_prices(all_tickers)

    per_stock = capital / len(tickers)
    holdings: List[dict] = []
    for _, row in picks.iterrows():
        ticker = row["ticker"]
        ep     = prices.get(ticker)
        if not ep or ep <= 0:
            logger.warning("No entry price for %s — excluded.", ticker)
            continue
        shares = per_stock / ep
        holdings.append({
            "ticker":               ticker,
            "name":                 str(row.get("name", "")),
            "region":               str(row.get("region", "")),
            "indices":              str(row.get("indices", "")),
            "entry_price":          round(ep, 4),
            "shares":               round(shares, 6),
            "entry_value":          round(per_stock, 2),
            "current_price":        round(ep, 4),
            "current_value":        round(per_stock, 2),
            "pnl_pct":              0.0,
            "pct_above_200sma":     round(float(row.get("pct_above_200sma") or 0), 1),
            "volume_ratio":         round(float(row.get("volume_ratio") or 0), 2),
            "pct_above_neckline":   round(float(row.get("pct_above_neckline") or 0), 1),
            "pattern_span_days":    int(row.get("pattern_span_days") or 0),
            "neckline":             round(float(row["neckline"]), 2) if row.get("neckline") else None,
            "bottom_variation_pct": round(float(row["bottom_variation_pct"]), 2)
                                    if row.get("bottom_variation_pct") is not None else None,
        })

    benchmarks: Dict[str, dict] = {}
    for bm in BENCHMARKS:
        ep = prices.get(bm)
        benchmarks[bm] = {
            "entry_price":   round(ep, 4) if ep else None,
            "current_price": round(ep, 4) if ep else None,
            "return_pct":    0.0,
        }

    cohort = {
        "id":               cohort_id,
        "date":             str(cohort_date),
        "capital":          capital,
        "holdings":         holdings,
        "benchmarks":       benchmarks,
        "portfolio_return": 0.0,
        "spy_return":       0.0,
        "vti_return":       0.0,
        "alpha_vs_spy":     0.0,
        "alpha_vs_vti":     0.0,
        "last_updated":     str(datetime.now().date()),
    }

    data["cohorts"].append(cohort)
    _save(data)
    logger.info("Stringent cohort %s added (%d holdings).", cohort_id, len(holdings))
    return cohort


# --------------------------------------------------------------------------- #
# Update all cohorts
# --------------------------------------------------------------------------- #

def update_all_cohorts() -> None:
    data = _load()
    if not data["cohorts"]:
        logger.info("No cohorts to update.")
        return

    all_tickers: set = set(BENCHMARKS)
    for c in data["cohorts"]:
        for h in c["holdings"]:
            all_tickers.add(h["ticker"])

    prices = _fetch_latest_prices(list(all_tickers))

    for cohort in data["cohorts"]:
        total_entry   = sum(h["entry_value"] for h in cohort["holdings"])
        total_current = 0.0

        for h in cohort["holdings"]:
            cur = prices.get(h["ticker"])
            if cur and cur > 0:
                h["current_price"] = round(cur, 4)
                h["current_value"] = round(h["shares"] * cur, 2)
                h["pnl_pct"]       = round((cur - h["entry_price"]) / h["entry_price"] * 100, 2)
            total_current += h.get("current_value", h["entry_value"])

        port_ret = (total_current - total_entry) / total_entry * 100 if total_entry else 0.0
        cohort["portfolio_return"] = round(port_ret, 2)

        for bm in BENCHMARKS:
            bm_d = cohort["benchmarks"].get(bm, {})
            cur  = prices.get(bm)
            if cur and bm_d.get("entry_price"):
                bm_d["current_price"] = round(cur, 4)
                bm_d["return_pct"]    = round(
                    (cur - bm_d["entry_price"]) / bm_d["entry_price"] * 100, 2
                )

        cohort["spy_return"]   = cohort["benchmarks"].get("SPY", {}).get("return_pct") or 0.0
        cohort["vti_return"]   = cohort["benchmarks"].get("VTI", {}).get("return_pct") or 0.0
        cohort["alpha_vs_spy"] = round(cohort["portfolio_return"] - cohort["spy_return"], 2)
        cohort["alpha_vs_vti"] = round(cohort["portfolio_return"] - cohort["vti_return"], 2)
        cohort["last_updated"] = str(datetime.now().date())

    _save(data)
    logger.info("All stringent cohorts updated.")


# --------------------------------------------------------------------------- #
# HTML report (lightweight — the main artifact is the published dashboard)
# --------------------------------------------------------------------------- #

def _color(val: float) -> str:
    return "color:#22c55e" if val > 0 else ("color:#ef4444" if val < 0 else "color:#94a3b8")


def _fmt(val) -> str:
    if val is None:
        return "—"
    try:
        v = float(val)
        return f"{'+' if v>0 else ''}{v:.2f}%"
    except (TypeError, ValueError):
        return "—"


def generate_report() -> str:
    data    = _load()
    cohorts = data.get("cohorts", [])
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    import json as _json

    chart_labels = _json.dumps([c["id"] for c in sorted(cohorts, key=lambda x: x["date"])])
    chart_port   = _json.dumps([c.get("portfolio_return", 0) for c in sorted(cohorts, key=lambda x: x["date"])])
    chart_spy    = _json.dumps([c.get("spy_return", 0)       for c in sorted(cohorts, key=lambda x: x["date"])])
    chart_vti    = _json.dumps([c.get("vti_return", 0)       for c in sorted(cohorts, key=lambda x: x["date"])])

    summary_rows = ""
    for c in sorted(cohorts, key=lambda x: x["date"], reverse=True):
        pr  = c.get("portfolio_return", 0.0) or 0.0
        spy = c.get("spy_return",       0.0) or 0.0
        vti = c.get("vti_return",       0.0) or 0.0
        asp = c.get("alpha_vs_spy",     0.0) or 0.0
        avt = c.get("alpha_vs_vti",     0.0) or 0.0
        n   = len(c.get("holdings", []))
        summary_rows += f"""
        <tr>
          <td>{c['date']}</td><td>${c['capital']:,}</td><td>{n}</td>
          <td style="{_color(pr)};font-weight:600">{_fmt(pr)}</td>
          <td style="{_color(spy)}">{_fmt(spy)}</td>
          <td style="{_color(vti)}">{_fmt(vti)}</td>
          <td style="{_color(asp)};font-weight:600">{_fmt(asp)}</td>
          <td style="{_color(avt)};font-weight:600">{_fmt(avt)}</td>
          <td>{c.get('last_updated','—')}</td>
        </tr>"""

    detail_sections = ""
    for c in sorted(cohorts, key=lambda x: x["date"], reverse=True):
        rows = ""
        for h in sorted(c.get("holdings", []), key=lambda x: x.get("pnl_pct", 0), reverse=True):
            pnl = h.get("pnl_pct", 0.0) or 0.0
            span = h.get("pattern_span_days", 0)
            span_str = f"{span//252}y {(span%252)//21}m" if span else "—"
            rows += f"""
            <tr>
              <td><strong>{h['ticker']}</strong></td>
              <td>{h.get('region','')}</td>
              <td>${h['entry_price']:,.2f}</td>
              <td>${h.get('current_price', h['entry_price']):,.2f}</td>
              <td>${h.get('current_value', h['entry_value']):,.0f}</td>
              <td style="{_color(pnl)};font-weight:600">{_fmt(pnl)}</td>
              <td>{h.get('pct_above_200sma','—')}%</td>
              <td>{h.get('volume_ratio','—')}×</td>
              <td>{span_str}</td>
            </tr>"""

        pr  = c.get("portfolio_return", 0.0) or 0.0
        spy = c.get("spy_return",       0.0) or 0.0
        vti = c.get("vti_return",       0.0) or 0.0
        total_val = sum(h.get("current_value", h["entry_value"]) for h in c.get("holdings", []))

        detail_sections += f"""
        <section class="cohort-card">
          <h2>Cohort {c['id']} <span class="cohort-date">({c['date']})</span></h2>
          <div class="kpi-row">
            <div class="kpi"><span class="kpi-label">Portfolio</span><span class="kpi-value" style="{_color(pr)}">{_fmt(pr)}</span></div>
            <div class="kpi"><span class="kpi-label">α vs SPY</span><span class="kpi-value" style="{_color(c.get('alpha_vs_spy',0) or 0)}">{_fmt(c.get('alpha_vs_spy',0))}</span></div>
            <div class="kpi"><span class="kpi-label">α vs VTI</span><span class="kpi-value" style="{_color(c.get('alpha_vs_vti',0) or 0)}">{_fmt(c.get('alpha_vs_vti',0))}</span></div>
            <div class="kpi"><span class="kpi-label">SPY</span><span class="kpi-value" style="{_color(spy)}">{_fmt(spy)}</span></div>
            <div class="kpi"><span class="kpi-label">VTI</span><span class="kpi-value" style="{_color(vti)}">{_fmt(vti)}</span></div>
            <div class="kpi"><span class="kpi-label">Value</span><span class="kpi-value">${total_val:,.0f}</span></div>
          </div>
          <table>
            <thead><tr>
              <th>Ticker</th><th>Region</th><th>Entry</th><th>Current</th>
              <th>Value</th><th>P&L</th><th>200SMA gap</th><th>Vol ratio</th><th>Pattern</th>
            </tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </section>"""

    html = f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stringent Triple-Bottom Portfolio</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root {{--bg:#0f172a;--surface:#1e293b;--surface2:#334155;--text:#f1f5f9;--muted:#94a3b8;--border:#334155;}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:var(--bg);color:var(--text);font-family:system-ui,sans-serif;padding:1.5rem;}}
h1{{font-size:1.6rem;font-weight:700;margin-bottom:.25rem;}}
.subtitle{{color:var(--muted);font-size:.85rem;margin-bottom:2rem;}}
h2{{font-size:1.15rem;font-weight:600;margin-bottom:1rem;}}
.cohort-date{{font-size:.85rem;font-weight:400;color:var(--muted);}}
section{{background:var(--surface);border-radius:.75rem;padding:1.5rem;margin-bottom:1.5rem;border:1px solid var(--border);}}
.kpi-row{{display:flex;flex-wrap:wrap;gap:1rem;margin-bottom:1.25rem;}}
.kpi{{background:var(--surface2);border-radius:.5rem;padding:.75rem 1.25rem;min-width:110px;}}
.kpi-label{{display:block;font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:.2rem;}}
.kpi-value{{font-size:1.25rem;font-weight:700;}}
table{{width:100%;border-collapse:collapse;font-size:.85rem;overflow-x:auto;display:block;}}
th{{text-align:left;padding:.5rem .75rem;color:var(--muted);font-weight:500;border-bottom:1px solid var(--border);font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;}}
td{{padding:.5rem .75rem;border-bottom:1px solid var(--border);}}
tr:last-child td{{border-bottom:none;}}
.chart-wrap{{background:var(--surface);border-radius:.75rem;padding:1.5rem;margin-bottom:1.5rem;border:1px solid var(--border);}}
canvas{{max-height:300px;}}
@media(prefers-color-scheme:light){{:root{{--bg:#f8fafc;--surface:#fff;--surface2:#f1f5f9;--text:#0f172a;--muted:#64748b;--border:#e2e8f0;}}}}
</style></head><body>
<h1>Triple-Bottom Stringent Portfolio</h1>
<p class="subtitle">$100k/cohort · Top 5 high-conviction picks · 200SMA≥20% · Vol≥3.5× · Neckline>5% · vs SPY &amp; VTI · {now_str}</p>

<div class="chart-wrap">
  <h2>Monthly Cohort Returns</h2>
  <canvas id="chart"></canvas>
</div>
<script>
new Chart(document.getElementById("chart").getContext("2d"), {{
  type:"bar",
  data:{{
    labels:{chart_labels},
    datasets:[
      {{label:"Portfolio",data:{chart_port},backgroundColor:"rgba(59,130,246,.7)",borderRadius:4}},
      {{label:"SPY",      data:{chart_spy}, backgroundColor:"rgba(245,158,11,.7)", borderRadius:4}},
      {{label:"VTI",      data:{chart_vti}, backgroundColor:"rgba(148,163,184,.5)",borderRadius:4}}
    ]
  }},
  options:{{responsive:true,
    plugins:{{legend:{{labels:{{color:"#94a3b8"}}}}}},
    scales:{{
      x:{{ticks:{{color:"#94a3b8"}},grid:{{color:"rgba(255,255,255,.05)"}}}},
      y:{{ticks:{{color:"#94a3b8",callback:v=>v+"%"}},grid:{{color:"rgba(255,255,255,.05)"}}}}
    }}
  }}
}});
</script>

<section>
  <h2>All Cohorts — Summary</h2>
  <table><thead><tr>
    <th>Date</th><th>Capital</th><th>Picks</th>
    <th>Portfolio</th><th>SPY</th><th>VTI</th>
    <th>α vs SPY</th><th>α vs VTI</th><th>Updated</th>
  </tr></thead>
  <tbody>{summary_rows or "<tr><td colspan=9 style='color:var(--muted);padding:1rem'>No cohorts yet.</td></tr>"}</tbody>
  </table>
</section>

{detail_sections}
</body></html>"""

    PORTFOLIO_DIR.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html, encoding="utf-8")
    logger.info("Stringent report → %s", REPORT_FILE)
    return str(REPORT_FILE)

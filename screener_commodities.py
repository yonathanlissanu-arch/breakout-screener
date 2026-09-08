"""
Commodities Bull Market Phase Screener
=======================================
Identifies commodity ETFs in the beginning or middle of a structural bull market.

Phase classification:
  Bear          – 200-day MA declining or price well below 200-day MA
  Recovery      – price near but below 200-day MA; trend not yet confirmed
  Early Bull    – 200-day MA recently turned up after decline; price just above
  Mid Bull      – 200-day MA rising steadily 1+ years; price well above
  Late Bull     – price very extended (>50% above 200-day MA) or RSI > 80
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from fetcher_yahoo import fetch_price_data_yahoo
from indicators import compute_rsi

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ── Commodity universe ────────────────────────────────────────────────────────
# (ticker, name, sector)
COMMODITY_UNIVERSE: list[tuple[str, str, str]] = [
    # Precious Metals
    ("GLD",  "Gold",                      "Precious Metals"),
    ("SLV",  "Silver",                    "Precious Metals"),
    ("PPLT", "Platinum",                  "Precious Metals"),
    ("PALL", "Palladium",                 "Precious Metals"),
    # Industrial / Base Metals
    ("CPER", "Copper",                    "Industrial Metals"),
    ("COPX", "Copper Miners",             "Industrial Metals"),
    ("SLX",  "Steel",                     "Industrial Metals"),
    ("PICK", "Metals & Mining",           "Industrial Metals"),
    ("REMX", "Rare Earth Metals",         "Industrial Metals"),
    # Energy
    ("USO",  "WTI Crude Oil",             "Energy"),
    ("BNO",  "Brent Crude Oil",           "Energy"),
    ("UNG",  "Natural Gas",               "Energy"),
    ("XLE",  "Energy Sector",             "Energy"),
    # Agricultural
    ("WEAT", "Wheat",                     "Agriculture"),
    ("CORN", "Corn",                      "Agriculture"),
    ("SOYB", "Soybeans",                  "Agriculture"),
    ("CANE", "Sugar",                     "Agriculture"),
    ("JO",   "Coffee",                    "Agriculture"),
    ("NIB",  "Cocoa",                     "Agriculture"),
    ("BAL",  "Cotton",                    "Agriculture"),
    # Uranium / Nuclear
    ("URA",  "Uranium ETF",               "Uranium"),
    ("URNM", "Uranium Miners",            "Uranium"),
    ("CCJ",  "Cameco",                    "Uranium"),
    # Battery Metals / Clean-Energy Transition
    ("LIT",  "Lithium & Battery Tech",    "Battery Metals"),
    # Broad Commodity
    ("DBC",  "Broad Commodities",         "Broad"),
    ("PDBC", "Optimum Yield Commodities", "Broad"),
    ("GSG",  "Commodities GSCI",          "Broad"),
]

PHASE_ORDER = {
    "Early Bull": 0,
    "Early-Mid Bull": 1,
    "Mid Bull": 2,
    "Late Bull": 3,
    "Recovery": 4,
    "Bear / Bouncing": 5,
    "Bear": 6,
}

PHASE_COLOR = {
    "Early Bull":     "#22c55e",   # green
    "Early-Mid Bull": "#84cc16",   # lime
    "Mid Bull":       "#3b82f6",   # blue
    "Late Bull":      "#f59e0b",   # amber
    "Recovery":       "#94a3b8",   # slate
    "Bear / Bouncing":"#f87171",   # red-ish
    "Bear":           "#ef4444",   # red
}


# ── Core analysis ─────────────────────────────────────────────────────────────

def _sma200_n_ago(closes: pd.Series, n: int) -> Optional[float]:
    """200-day MA computed on data ending n bars before the last bar."""
    idx = len(closes) - 1 - n
    if idx < 199:
        return None
    val = closes.iloc[: idx + 1].rolling(200).mean().iloc[-1]
    return None if np.isnan(val) else float(val)


def _days_above_200(closes: pd.Series, sma200_series: pd.Series) -> int:
    """Consecutive trading days price has stayed above its 200-day MA."""
    n = len(closes)
    count = 0
    for i in range(n - 1, -1, -1):
        s = sma200_series.iloc[i]
        if np.isnan(s):
            break
        if closes.iloc[i] > s:
            count += 1
        else:
            break
    return count


def classify_bull_phase(
    pct_above_200: float,
    slope_1y: Optional[float],
    slope_6m: Optional[float],
    slope_2y: Optional[float],
    days_above_200: int,
    rsi: Optional[float],
    ma_bullish_stack: bool,
) -> tuple[str, int, str]:
    """
    Return (phase_label, maturity_score_0_to_100, note_string).

    Maturity score: 0 = deep bear, 50 = neutral/recovery,
                    60 = early bull, 75 = mid bull, 90+ = late bull.
    """
    notes: list[str] = []

    # ── Bear: price meaningfully below 200-day MA ──────────────────────────
    if pct_above_200 < -5:
        return "Bear", max(5, 30 + int(pct_above_200 / 2)), f"Price {abs(pct_above_200):.0f}% below 200MA"

    # ── Recovery: price at or just below 200-day MA ────────────────────────
    if pct_above_200 < 0:
        return "Recovery", 38, "Price just below 200MA; trend unconfirmed"

    # ── Price above 200-day MA: check MA direction ─────────────────────────
    if slope_1y is not None and slope_1y < -2:
        return "Bear / Bouncing", 32, f"200MA declining {slope_1y:.1f}% YoY despite price bounce"

    # ── Late Bull: very extended or overbought ─────────────────────────────
    is_late = pct_above_200 > 55 or (rsi is not None and rsi > 80)
    if is_late:
        sc = min(98, 85 + int(pct_above_200 / 8))
        return "Late Bull", sc, f"Price {pct_above_200:.0f}% above 200MA" + (f", RSI {rsi:.0f}" if rsi else "")

    # ── Distinguish Early vs Mid bull ──────────────────────────────────────
    early_pts = 0
    mid_pts = 0

    # 2-year MA slope: if small/negative, trend just started
    if slope_2y is not None:
        if slope_2y < 2:
            early_pts += 3
            notes.append(f"200MA flat/down over 2y ({slope_2y:.1f}%)")
        elif slope_2y < slope_1y * 0.4 if slope_1y else False:
            early_pts += 1   # trend recently accelerated — still early
        else:
            mid_pts += 2

    # Days continuously above 200-day MA
    if days_above_200 < 180:
        early_pts += 3
        notes.append(f"Only {days_above_200}d above 200MA")
    elif days_above_200 < 400:
        early_pts += 1
        mid_pts += 1
    else:
        mid_pts += 3
        notes.append(f"{days_above_200}d above 200MA")

    # Distance above 200-day MA
    if pct_above_200 < 12:
        early_pts += 2
    elif pct_above_200 < 35:
        mid_pts += 1
    # 35-55% handled above for mid/late boundary

    # 1-year MA slope
    if slope_1y is not None:
        if 0 <= slope_1y < 6:
            early_pts += 2
        elif 6 <= slope_1y < 18:
            mid_pts += 2
        else:
            mid_pts += 3

    # RSI
    if rsi is not None:
        if rsi < 58:
            early_pts += 1
        elif rsi < 72:
            mid_pts += 1

    # MA stack
    if not ma_bullish_stack:
        early_pts += 1
    else:
        mid_pts += 1

    total = early_pts + mid_pts
    early_ratio = early_pts / total if total > 0 else 0.5

    if early_ratio >= 0.62:
        score = 55 + int(10 * (1 - early_ratio))
        phase = "Early Bull"
    elif early_ratio <= 0.38:
        score = 68 + int(15 * (1 - early_ratio))
        if score > 82 or pct_above_200 > 40:
            phase = "Late Bull"
        else:
            phase = "Mid Bull"
    else:
        score = 63
        phase = "Early-Mid Bull"

    if not notes:
        if slope_1y is not None:
            notes.append(f"200MA +{slope_1y:.1f}%/yr")
    return phase, min(95, score), " · ".join(filter(None, notes))


def analyse_commodity(ticker: str, df: pd.DataFrame) -> Optional[dict]:
    MIN_BARS = 520  # ~2 years of history required

    closes = df["Close"].dropna()
    if len(closes) < MIN_BARS:
        return None

    try:
        current_price = float(closes.iloc[-1])

        sma200_s = closes.rolling(200).mean()
        sma100_s = closes.rolling(100).mean()
        sma50_s  = closes.rolling(50).mean()
        sma20_s  = closes.rolling(20).mean()

        sma200 = float(sma200_s.iloc[-1])
        sma100 = float(sma100_s.iloc[-1])
        sma50  = float(sma50_s.iloc[-1])
        sma20  = float(sma20_s.iloc[-1])

        if any(np.isnan(v) for v in [sma200, sma100, sma50, sma20]):
            return None

        pct_above_200 = (current_price - sma200) / sma200 * 100

        # MA slopes
        def slope(n: int) -> Optional[float]:
            past = _sma200_n_ago(closes, n)
            if past is None or past == 0:
                return None
            return (sma200 - past) / past * 100

        slope_1y = slope(252)
        slope_6m = slope(126)
        slope_2y = slope(504)

        days_ab200 = _days_above_200(closes, sma200_s)

        rsi = compute_rsi(closes)

        ma_stack = current_price > sma20 > sma50 > sma100 > sma200

        # 52-week / ATH metrics
        tail252 = closes.iloc[-252:]
        high_52w = float(tail252.max())
        low_52w  = float(tail252.min())
        ath      = float(closes.max())
        pct_from_ath  = (current_price - ath)  / ath  * 100
        pct_from_52wh = (current_price - high_52w) / high_52w * 100

        phase, score, note = classify_bull_phase(
            pct_above_200=pct_above_200,
            slope_1y=slope_1y,
            slope_6m=slope_6m,
            slope_2y=slope_2y,
            days_above_200=days_ab200,
            rsi=rsi,
            ma_bullish_stack=ma_stack,
        )

        return {
            "ticker":          ticker,
            "price":           round(current_price, 2),
            "sma20":           round(sma20, 2),
            "sma50":           round(sma50, 2),
            "sma100":          round(sma100, 2),
            "sma200":          round(sma200, 2),
            "pct_above_200":   round(pct_above_200, 1),
            "slope_200_6m":    round(slope_6m, 1) if slope_6m is not None else None,
            "slope_200_1y":    round(slope_1y, 1) if slope_1y is not None else None,
            "slope_200_2y":    round(slope_2y, 1) if slope_2y is not None else None,
            "days_above_200":  days_ab200,
            "rsi14":           round(rsi, 1) if rsi is not None else None,
            "high_52w":        round(high_52w, 2),
            "low_52w":         round(low_52w, 2),
            "pct_from_52w_high": round(pct_from_52wh, 1),
            "pct_from_ath":    round(pct_from_ath, 1),
            "ma_bullish_stack": ma_stack,
            "phase":           phase,
            "phase_score":     score,
            "phase_note":      note,
        }

    except Exception:
        logger.debug("Analysis failed for %s", ticker, exc_info=True)
        return None


# ── HTML report ───────────────────────────────────────────────────────────────

_HTML_STYLE = """
<title>Commodities — Bull Market Phases</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
  :root{--bg:#081322;--surface:#0f1e32;--surface2:#142538;--border:#1c3150;
        --accent:#f59e0b;--text:#d4e5f7;--muted:#4d718a;
        --gain:#22c55e;--mid:#3b82f6;--late:#f59e0b;--bear:#ef4444;--rec:#94a3b8;}
  @media(prefers-color-scheme:light){:root:not([data-theme="dark"]){
    --bg:#f1f5fb;--surface:#fff;--surface2:#f8faff;--border:#cad5e8;
    --accent:#d97706;--text:#0c1c2e;--muted:#527091;
    --gain:#16a34a;--mid:#2563eb;--late:#d97706;--bear:#dc2626;--rec:#64748b;}}
  :root[data-theme="dark"]{--bg:#081322;--surface:#0f1e32;--surface2:#142538;--border:#1c3150;
    --accent:#f59e0b;--text:#d4e5f7;--muted:#4d718a;
    --gain:#22c55e;--mid:#3b82f6;--late:#f59e0b;--bear:#ef4444;--rec:#94a3b8;}
  :root[data-theme="light"]{--bg:#f1f5fb;--surface:#fff;--surface2:#f8faff;--border:#cad5e8;
    --accent:#d97706;--text:#0c1c2e;--muted:#527091;
    --gain:#16a34a;--mid:#2563eb;--late:#d97706;--bear:#dc2626;--rec:#64748b;}
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:'Figtree',system-ui,sans-serif;
       font-size:14px;line-height:1.5;padding:24px}
  .wrap{max-width:1200px;margin:0 auto}
  .header{padding:28px 0 22px;border-bottom:1px solid var(--border);margin-bottom:24px}
  .eyebrow{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);
           font-weight:600;margin-bottom:8px}
  h1{font-size:clamp(22px,4vw,32px);font-weight:700;line-height:1.1}
  h1 span{color:var(--accent)}
  .sub{font-size:12px;color:var(--muted);margin-top:6px}
  .legend{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:22px;align-items:center}
  .legend-item{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted)}
  .dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
  .phase-legend{font-size:11px;border:1px solid var(--border);background:var(--surface);
                padding:12px 18px;border-radius:4px;margin-bottom:22px}
  .phase-legend h3{font-size:10px;letter-spacing:.1em;text-transform:uppercase;
                   color:var(--muted);margin-bottom:8px}
  .phase-legend p{margin-bottom:4px;font-size:12px}
  .phases-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:24px}
  @media(max-width:700px){.phases-grid{grid-template-columns:1fr}}
  .card{background:var(--surface);border:1px solid var(--border);padding:20px;margin-bottom:20px}
  h2{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);
     font-weight:600;margin-bottom:14px}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{text-align:left;padding:8px 12px;font-size:10px;letter-spacing:.06em;
     text-transform:uppercase;color:var(--muted);font-weight:600;
     border-bottom:1px solid var(--border);white-space:nowrap}
  td{padding:10px 12px;border-bottom:1px solid var(--border);vertical-align:middle;
     font-variant-numeric:tabular-nums;white-space:nowrap}
  tr:last-child td{border-bottom:none}
  tr:hover td{background:var(--surface2)}
  .badge{display:inline-block;padding:2px 8px;border-radius:3px;font-size:11px;
         font-weight:600;letter-spacing:.04em}
  .tick{font-family:'JetBrains Mono',monospace;font-weight:500}
  .pos{color:var(--gain)} .neg{color:var(--bear)} .neu{color:var(--muted)}
  .bar-wrap{width:80px;height:7px;background:var(--border);border-radius:3px;display:inline-block;vertical-align:middle}
  .bar-fill{height:100%;border-radius:3px;transition:width .3s}
  .foot{margin-top:32px;padding-top:16px;border-top:1px solid var(--border);
        font-size:11px;color:var(--muted);line-height:1.7}
  .overflow-x{overflow-x:auto}
  @media(max-width:600px){td,th{padding:8px 6px;font-size:12px}}
</style>
"""


def _phase_badge(phase: str) -> str:
    color_map = {
        "Early Bull":     "#22c55e",
        "Early-Mid Bull": "#84cc16",
        "Mid Bull":       "#3b82f6",
        "Late Bull":      "#f59e0b",
        "Recovery":       "#94a3b8",
        "Bear / Bouncing":"#f87171",
        "Bear":           "#ef4444",
    }
    bg = color_map.get(phase, "#94a3b8")
    return (
        f'<span class="badge" style="background:{bg}22;color:{bg};'
        f'border:1px solid {bg}55">{phase}</span>'
    )


def _score_bar(score: int) -> str:
    pct = min(100, max(0, score))
    # Color: green for low score (early), blue for mid, amber/red for high
    if pct < 45:
        color = "#ef4444"
    elif pct < 58:
        color = "#22c55e"
    elif pct < 75:
        color = "#3b82f6"
    else:
        color = "#f59e0b"
    return (
        f'<span class="bar-wrap"><span class="bar-fill" '
        f'style="width:{pct}%;background:{color}"></span></span>'
    )


def _fmt_pct(val: Optional[float], pos_prefix: str = "+") -> str:
    if val is None:
        return '<span class="neu">—</span>'
    cls = "pos" if val > 0 else ("neg" if val < 0 else "neu")
    prefix = pos_prefix if val > 0 else ""
    return f'<span class="{cls}">{prefix}{val:.1f}%</span>'


def generate_html_report(
    results: list[dict],
    meta: dict[str, tuple[str, str]],  # ticker -> (name, sector)
    out_path: str,
    run_ts: str,
) -> None:
    rows_by_phase: dict[str, list[dict]] = {p: [] for p in PHASE_ORDER}
    for r in results:
        rows_by_phase.setdefault(r["phase"], []).append(r)

    # Sorted sections we care about (only show non-empty)
    show_phases = ["Early Bull", "Early-Mid Bull", "Mid Bull", "Late Bull", "Recovery", "Bear / Bouncing", "Bear"]

    def _table_row(r: dict) -> str:
        name, sector = meta.get(r["ticker"], (r["ticker"], ""))
        slope_1y = r.get("slope_200_1y")
        slope_2y = r.get("slope_200_2y")
        days_ab  = r.get("days_above_200", 0)
        rsi      = r.get("rsi14")
        rsi_str  = f"{rsi:.0f}" if rsi else "—"
        rsi_cls  = "pos" if rsi and rsi > 60 else ("neg" if rsi and rsi < 40 else "neu")

        return (
            f"<tr>"
            f'<td><span class="tick">{r["ticker"]}</span></td>'
            f"<td>{name}</td>"
            f'<td style="color:var(--muted);font-size:12px">{sector}</td>'
            f'<td>{_phase_badge(r["phase"])}</td>'
            f'<td>{_score_bar(r["phase_score"])}</td>'
            f'<td class="tick">${r["price"]:.2f}</td>'
            f'<td>{_fmt_pct(r.get("pct_above_200"))}</td>'
            f'<td>{_fmt_pct(slope_1y)}</td>'
            f'<td>{_fmt_pct(slope_2y)}</td>'
            f"<td>{days_ab}d</td>"
            f'<td class="{rsi_cls}">{rsi_str}</td>'
            f'<td style="font-size:11px;color:var(--muted)">{r.get("phase_note","")}</td>'
            f"</tr>"
        )

    def _section(phase: str, rows: list[dict]) -> str:
        if not rows:
            return ""
        sorted_rows = sorted(rows, key=lambda r: r.get("pct_above_200", 0))
        color_map = {
            "Early Bull": "var(--gain)", "Early-Mid Bull": "#84cc16",
            "Mid Bull": "var(--mid)", "Late Bull": "var(--late)",
            "Recovery": "var(--rec)", "Bear / Bouncing": "var(--bear)",
            "Bear": "var(--bear)",
        }
        color = color_map.get(phase, "var(--muted)")
        body = "\n".join(_table_row(r) for r in sorted_rows)
        return f"""
<div class="card">
  <h2 style="color:{color}">{phase} <span style="color:var(--muted);font-weight:400">({len(rows)})</span></h2>
  <div class="overflow-x">
  <table>
    <thead>
      <tr>
        <th>Ticker</th><th>Name</th><th>Sector</th><th>Phase</th>
        <th>Maturity</th><th>Price</th><th>vs 200MA</th>
        <th>200MA slope 1y</th><th>200MA slope 2y</th>
        <th>Days above 200MA</th><th>RSI 14</th><th>Note</th>
      </tr>
    </thead>
    <tbody>{body}</tbody>
  </table>
  </div>
</div>"""

    # Summary stats
    n_early = len(rows_by_phase.get("Early Bull", [])) + len(rows_by_phase.get("Early-Mid Bull", []))
    n_mid   = len(rows_by_phase.get("Mid Bull", []))
    n_late  = len(rows_by_phase.get("Late Bull", []))
    n_bear  = sum(len(rows_by_phase.get(p, [])) for p in ["Bear", "Bear / Bouncing", "Recovery"])
    n_total = len(results)

    stats_html = f"""
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
            gap:1px;background:var(--border);border:1px solid var(--border);margin-bottom:24px">
  <div style="background:var(--surface);padding:16px 18px">
    <div style="font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:6px">Screened</div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:500">{n_total}</div>
    <div style="font-size:10px;color:var(--muted);margin-top:4px">commodity ETFs</div>
  </div>
  <div style="background:var(--surface);padding:16px 18px">
    <div style="font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:6px">Early Bull</div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:500;color:var(--gain)">{n_early}</div>
    <div style="font-size:10px;color:var(--muted);margin-top:4px">beginning of bull</div>
  </div>
  <div style="background:var(--surface);padding:16px 18px">
    <div style="font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:6px">Mid Bull</div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:500;color:var(--mid)">{n_mid}</div>
    <div style="font-size:10px;color:var(--muted);margin-top:4px">middle of bull</div>
  </div>
  <div style="background:var(--surface);padding:16px 18px">
    <div style="font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:6px">Late Bull</div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:500;color:var(--late)">{n_late}</div>
    <div style="font-size:10px;color:var(--muted);margin-top:4px">extended / risky</div>
  </div>
  <div style="background:var(--surface);padding:16px 18px">
    <div style="font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:6px">Bear / Recovery</div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:500;color:var(--bear)">{n_bear}</div>
    <div style="font-size:10px;color:var(--muted);margin-top:4px">avoid / wait</div>
  </div>
</div>"""

    sections_html = "\n".join(
        _section(phase, rows_by_phase.get(phase, []))
        for phase in show_phases
    )

    phase_guide_html = """
<div class="card" style="margin-bottom:24px">
  <h2>Bull Market Phase Guide</h2>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;font-size:12px">
    <div><strong style="color:#22c55e">Early Bull</strong> — 200-day MA recently turned up after
    a prolonged decline or flat base. Price just crossed above 200-day MA (typically &lt;1 year ago).
    Not yet extended. Best risk/reward entry zone.</div>
    <div><strong style="color:#84cc16">Early-Mid Bull</strong> — Transitional: bull trend confirmed
    but 200-day MA slope still modest. Days above 200-day MA 6–18 months. Good entry.</div>
    <div><strong style="color:#3b82f6">Mid Bull</strong> — 200-day MA rising steadily for 1–3 years.
    Price 15–50% above 200-day MA. RSI healthy 55–70. Trend is established; pullbacks are
    buying opportunities.</div>
    <div><strong style="color:#f59e0b">Late Bull</strong> — Price &gt;50% above 200-day MA or RSI
    &gt;80. Parabolic or near-parabolic. Higher risk of mean-reversion. Reduce or wait for
    pullback.</div>
    <div><strong style="color:#94a3b8">Recovery</strong> — Price near or below 200-day MA; trend
    not yet confirmed. Watch for 200-day MA to flatten and turn up.</div>
    <div><strong style="color:#ef4444">Bear</strong> — 200-day MA declining, price below key
    support. Avoid.</div>
  </div>
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{_HTML_STYLE}
</head>
<body>
<div class="wrap">
  <div class="header">
    <div class="eyebrow">Commodity Macro Screener</div>
    <h1>Commodities <span>Bull Market Phases</span></h1>
    <div class="sub">Structural bull market phase analysis · {run_ts} UTC</div>
  </div>

  {stats_html}
  {phase_guide_html}
  {sections_html}

  <div class="foot">
    <p>Data: Yahoo Finance via direct API. 5-year daily OHLCV history required.</p>
    <p>Phase is determined by 200-day MA slope (6M, 1Y, 2Y), days price has been above 200-day MA,
    % extension above 200-day MA, and RSI(14). This is technical analysis only — not financial advice.</p>
    <p>Maturity bar: green=early, blue=mid, amber=late. Generated by breakout-screener.</p>
  </div>
</div>
</body>
</html>"""

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(html, encoding="utf-8")
    logger.info("HTML report written → %s", out_path)


# ── Main ──────────────────────────────────────────────────────────────────────

def run(
    history_years: int = 6,
    cache_dir: str = "data/cache_commodities",
    results_dir: str = "results",
) -> list[dict]:
    tickers  = [t for t, _, _ in COMMODITY_UNIVERSE]
    meta_map = {t: (n, s) for t, n, s in COMMODITY_UNIVERSE}

    logger.info("Fetching price data for %d commodity tickers …", len(tickers))
    price_data = fetch_price_data_yahoo(
        tickers,
        history_years=history_years,
        cache_dir=cache_dir,
        delay=0.4,
    )

    results: list[dict] = []
    for ticker in tickers:
        df = price_data.get(ticker)
        if df is None or df.empty:
            logger.info("  SKIP  %s — no data", ticker)
            continue
        r = analyse_commodity(ticker, df)
        if r is None:
            logger.info("  SKIP  %s — insufficient history (<520 bars)", ticker)
            continue
        name, sector = meta_map.get(ticker, (ticker, ""))
        r["name"]   = name
        r["sector"] = sector
        logger.info(
            "  %-6s  %-28s  %-16s  pct_above_200=%+.1f%%  slope1y=%s%%  days=%d",
            ticker, name, r["phase"],
            r["pct_above_200"],
            f"{r['slope_200_1y']:+.1f}" if r["slope_200_1y"] is not None else "n/a",
            r["days_above_200"],
        )
        results.append(r)

    # Sort: Early Bull first, then Mid, then Late, then Bear
    results.sort(key=lambda r: (PHASE_ORDER.get(r["phase"], 9), -r.get("pct_above_200", 0)))

    os.makedirs(results_dir, exist_ok=True)
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")

    # CSV
    csv_path = os.path.join(results_dir, f"commodities_bull_phases_{ts_str}.csv")
    df_out = pd.DataFrame(results)
    df_out.to_csv(csv_path, index=False)
    logger.info("CSV saved → %s", csv_path)

    # HTML
    html_path = os.path.join(results_dir, "commodities_bull_phases_latest.html")
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    generate_html_report(results, meta_map, html_path, run_ts)

    return results


if __name__ == "__main__":
    run()

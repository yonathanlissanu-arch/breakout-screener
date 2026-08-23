"""
demo.py — verify the breakout screener logic with synthetic data.

Generates realistic OHLCV series for 12 tickers, 3 of which have
DELL/MPC-style breakouts (strong MA stack, recent resistance breach,
volume surge).  Run with:

    python demo.py
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from indicators import analyse_ticker
from screener import run_screen

RNG = np.random.default_rng(42)


def _trading_dates(n: int, end: datetime | None = None) -> pd.DatetimeIndex:
    end = end or datetime(2026, 8, 22)
    dates = []
    d = end
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d -= timedelta(days=1)
    return pd.DatetimeIndex(sorted(dates))


def make_ohlcv(
    n: int = 1260,
    start_price: float = 50.0,
    trend_pct_annual: float = 0.08,
    vol_annual: float = 0.30,
    breakout: bool = False,
    breakout_days_ago: int = 5,
    resistance_mult: float = 1.15,
) -> pd.DataFrame:
    """
    Synthetic daily OHLCV.

    breakout=True models the real DELL/MPC pattern:
      Phase 1 (0..350):    stock climbs to a prior high (the future resistance)
      Phase 2 (350..700):  correction and consolidation — base building
      Phase 3 (700..n-bo): multi-month recovery uptrend — bullish MA stack forms
      Phase 4 (n-bo..n):   breakout above old high with volume surge
    """
    dates = _trading_dates(n)
    daily_vol = vol_annual / np.sqrt(252)

    prices = np.zeros(n, dtype=float)

    if breakout:
        # ── Phase 1 (bars 0-300): run up to prior high (future resistance) ──
        p1_end = 300
        p1_drift = 0.22 / 252
        prices[0] = start_price * 0.55
        for i in range(1, p1_end):
            prices[i] = prices[i - 1] * (1 + RNG.normal(p1_drift, daily_vol))
        resistance_price = float(np.percentile(prices[:p1_end], 95))

        # ── Phase 2 (bars 300-680): correction to ~60% of resistance ────────
        p2_end = 680
        base = resistance_price * 0.58
        # Smooth arc downward then flat
        for i in range(p1_end, p2_end):
            t = (i - p1_end) / (p2_end - p1_end)
            target = resistance_price * (0.95 - 0.38 * t)
            prices[i] = target + RNG.normal(0, resistance_price * 0.012)
        prices[p1_end:p2_end] = np.clip(
            prices[p1_end:p2_end], resistance_price * 0.50, resistance_price * 0.95
        )

        # ── Phase 3 (bars 680-n-bo): steady uptrend, MA stack forms ─────────
        # Price travels from ~60% to ~98% of resistance over this period.
        # Use a smooth linear ramp + noise so all SMAs are staggered properly.
        bo_idx = n - breakout_days_ago
        p3_len = bo_idx - p2_end
        p3_start = resistance_price * 0.60
        p3_end_target = resistance_price * 0.985
        for i in range(p2_end, bo_idx):
            t = (i - p2_end) / max(p3_len - 1, 1)
            # Ease-in curve for more realistic acceleration
            target = p3_start + (p3_end_target - p3_start) * (t ** 0.85)
            noise_scale = resistance_price * 0.008
            prices[i] = target + RNG.normal(0, noise_scale)
        prices[p2_end:bo_idx] = np.clip(
            prices[p2_end:bo_idx], resistance_price * 0.50, resistance_price * 0.988
        )

        # ── Phase 4 (n-bo..n): breakout with gentle continuation ────────────
        prices[bo_idx] = resistance_price * (1.0 + resistance_mult - 1.0) * 0.5
        prices[bo_idx] = max(prices[bo_idx], resistance_price * 1.015)
        for i in range(bo_idx + 1, n):
            prices[i] = prices[i - 1] * (1 + RNG.normal(0.0004, daily_vol * 0.5))

    else:
        daily_drift = trend_pct_annual / 252
        prices[0] = start_price
        for i in range(1, n):
            prices[i] = prices[i - 1] * (1 + RNG.normal(daily_drift, daily_vol))

    # ── OHLCV ────────────────────────────────────────────────────────────────
    opens = prices * (1 + RNG.normal(0, 0.003, n))
    highs = np.maximum(prices, opens) * (1 + np.abs(RNG.normal(0, 0.005, n)))
    lows  = np.minimum(prices, opens) * (1 - np.abs(RNG.normal(0, 0.005, n)))
    base_vol = 1_000_000 * (start_price / 50)
    volumes = RNG.integers(int(base_vol * 0.7), int(base_vol * 1.3), n).astype(float)

    if breakout:
        bo_idx = n - breakout_days_ago
        volumes[bo_idx] *= RNG.uniform(2.5, 4.0)

    df = pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": prices, "Volume": volumes},
        index=dates,
    )
    df.index.name = "Date"
    return df


# --------------------------------------------------------------------------- #
# Synthetic universe — 12 tickers, 3 genuine breakouts
# --------------------------------------------------------------------------- #

TICKERS = {
    # Genuine breakouts (DELL / MPC pattern)
    "SYNTH-A":  dict(start_price=85.0,  breakout=True, breakout_days_ago=2,  resistance_mult=1.12, trend_pct_annual=0.12),
    "SYNTH-B":  dict(start_price=120.0, breakout=True, breakout_days_ago=5,  resistance_mult=1.18, trend_pct_annual=0.10),
    "SYNTH-C":  dict(start_price=45.0,  breakout=True, breakout_days_ago=8,  resistance_mult=1.20, trend_pct_annual=0.09),
    # Near-miss: breakout too old (15 days ago > 10-day window)
    "SYNTH-D":  dict(start_price=95.0,  breakout=True, breakout_days_ago=15, resistance_mult=1.10, trend_pct_annual=0.08),
    # Extended: price far above 200-day (should still pass if RSI in range)
    "SYNTH-E":  dict(start_price=200.0, breakout=True, breakout_days_ago=3,  resistance_mult=1.30, trend_pct_annual=0.25),
    # No breakout — trending stocks that don't pass
    "SYNTH-F":  dict(start_price=60.0,  breakout=False, trend_pct_annual=0.08),
    "SYNTH-G":  dict(start_price=30.0,  breakout=False, trend_pct_annual=0.05),
    "SYNTH-H":  dict(start_price=150.0, breakout=False, trend_pct_annual=0.15),
    "SYNTH-I":  dict(start_price=75.0,  breakout=False, trend_pct_annual=0.06),
    "SYNTH-J":  dict(start_price=55.0,  breakout=False, trend_pct_annual=0.04),
    "SYNTH-K":  dict(start_price=90.0,  breakout=False, trend_pct_annual=0.07),
    "SYNTH-L":  dict(start_price=110.0, breakout=False, trend_pct_annual=0.09),
}


def main() -> None:
    print("\n" + "─" * 70)
    print("  BREAKOUT SCREENER — DEMO (synthetic data)")
    print("─" * 70)
    print(
        f"  Generating {len(TICKERS)} synthetic tickers … "
        "(3 with engineered DELL/MPC-style breakouts)"
    )

    price_data = {t: make_ohlcv(**params) for t, params in TICKERS.items()}

    universe = pd.DataFrame(
        [
            {"ticker": t, "name": f"Synthetic {t}", "indices": "Demo", "region": "US"}
            for t in TICKERS
        ]
    )

    results = run_screen(price_data, universe, top_n=10, results_dir="results")

    if results.empty:
        return

    print("\n── Per-ticker filter diagnostic ──")
    for t, df in price_data.items():
        row = analyse_ticker(t, df)
        status = "PASS ✓" if row else "FAIL  "
        print(f"  {status}  {t}")


if __name__ == "__main__":
    main()

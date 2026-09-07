"""
Sanity check: run this bundle's signal_engine.py against the SAME historical
CSV used in the original research (SPY_5min_...RTH_Massive.csv) and confirm
it reproduces the same LongRunner-2D signals as the frozen script did.

Usage:
    python tests/validate_against_backtest.py /path/to/SPY_5min_..._Massive.csv

This does not hit the network -- it's a pure math/logic check that the live
signal engine matches the audited backtest before you trust it with live data.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as C
from signal_engine import compute_features, find_signal_for_date


def main(csv_path):
    df = pd.read_csv(csv_path)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df["timestamp_et"] = df["timestamp_utc"].dt.tz_convert("America/New_York")
    df["date"] = df["timestamp_et"].dt.date
    df = df.sort_values("timestamp_et").reset_index(drop=True)
    df["bar"] = df.groupby("date").cumcount()

    feat = compute_features(df)
    dates = sorted(feat["date"].unique())

    signals = []
    for d in dates:
        sig = find_signal_for_date(feat, d)
        if sig is not None:
            signals.append(sig)

    print(f"Checked {len(dates)} historical days.")
    print(f"Live signal_engine.py found {len(signals)} LongRunner-2D long signals.")
    print("\nFirst 5 signals:")
    for s in signals[:5]:
        print(f"  {s['signal_date']}  z={s['z']:.2f}  entry={s['entry_time_et']} @ {s['entry_price']:.2f}")

    print("\nCompare this count to the frozen script's LongRunner-2D long-signal count")
    print("(filter LONGRUNNER_2D_FROZEN_ALL_SIGNALS.csv to rows where z <= -1.5, i.e. every")
    print("row it kept, since it already dropped short-first-event days). If the counts and")
    print("dates don't match, do not go live -- something in the port diverged from the original.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python tests/validate_against_backtest.py /path/to/SPY_5min_..._Massive.csv")
        sys.exit(1)
    main(sys.argv[1])

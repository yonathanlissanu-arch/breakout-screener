"""
Paper portfolio tracker for the breakout/breakdown screener.

Two weekly-rotation portfolios:
  Long  — top breakout candidates (buy Monday open, hold 1 week)
  Short — top breakdown candidates (sell short Monday open, hold 1 week)

Capital: $100,000 per side, equally weighted across positions.
Benchmark: SPY (fetched fresh each Monday alongside the scan).

State is persisted to portfolio_state.json in the repo root.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

STATE_FILE = os.path.join(os.path.dirname(__file__), "portfolio_state.json")
CAPITAL_PER_SIDE = 100_000.0


# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #

@dataclass
class Position:
    ticker: str
    side: str           # "long" or "short"
    week: int
    entry_date: str     # ISO date string
    entry_price: float
    shares: float       # fractional shares supported
    score: float = 0.0
    name: str = ""
    indices: str = ""


@dataclass
class ClosedTrade:
    ticker: str
    side: str
    week: int
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: float
    pnl: float
    pnl_pct: float


@dataclass
class WeeklyResult:
    week: int
    start_date: str
    end_date: str
    long_pnl: float
    short_pnl: float
    combined_pnl: float
    spy_pnl: float          # SPY $ gain on equivalent $100K
    spy_open: float
    spy_close: float
    vti_pnl: float = 0.0    # VTI $ gain on equivalent $100K
    vti_open: float = 0.0
    vti_close: float = 0.0
    long_tickers: List[str] = field(default_factory=list)
    short_tickers: List[str] = field(default_factory=list)


@dataclass
class PortfolioState:
    current_week: int = 0
    start_date: str = ""
    open_long: List[Position] = field(default_factory=list)
    open_short: List[Position] = field(default_factory=list)
    spy_entry_price: float = 0.0         # SPY Monday open when week was opened
    vti_entry_price: float = 0.0         # VTI Monday open when week was opened
    closed_trades: List[ClosedTrade] = field(default_factory=list)
    weekly_results: List[WeeklyResult] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Serialization helpers
# --------------------------------------------------------------------------- #

def _to_dict(obj) -> dict:
    return asdict(obj)


def _pos_from_dict(d: dict) -> Position:
    return Position(**d)


def _closed_from_dict(d: dict) -> ClosedTrade:
    return ClosedTrade(**d)


def _weekly_from_dict(d: dict) -> WeeklyResult:
    return WeeklyResult(**d)


# --------------------------------------------------------------------------- #
# Portfolio manager
# --------------------------------------------------------------------------- #

class Portfolio:
    def __init__(self, state_file: str = STATE_FILE):
        self.state_file = state_file
        self.state = self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> PortfolioState:
        if not os.path.exists(self.state_file):
            return PortfolioState()
        with open(self.state_file) as f:
            data = json.load(f)
        state = PortfolioState(
            current_week=data.get("current_week", 0),
            start_date=data.get("start_date", ""),
            spy_entry_price=data.get("spy_entry_price", 0.0),
            vti_entry_price=data.get("vti_entry_price", 0.0),
            open_long=[_pos_from_dict(p) for p in data.get("open_long", [])],
            open_short=[_pos_from_dict(p) for p in data.get("open_short", [])],
            closed_trades=[_closed_from_dict(t) for t in data.get("closed_trades", [])],
            weekly_results=[_weekly_from_dict(r) for r in data.get("weekly_results", [])],
        )
        return state

    def save(self):
        data = {
            "current_week": self.state.current_week,
            "start_date": self.state.start_date,
            "spy_entry_price": self.state.spy_entry_price,
            "vti_entry_price": self.state.vti_entry_price,
            "open_long": [_to_dict(p) for p in self.state.open_long],
            "open_short": [_to_dict(p) for p in self.state.open_short],
            "closed_trades": [_to_dict(t) for t in self.state.closed_trades],
            "weekly_results": [_to_dict(r) for r in self.state.weekly_results],
        }
        with open(self.state_file, "w") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info("Portfolio state saved → %s", self.state_file)

    # ── Week operations ───────────────────────────────────────────────────────

    def open_week(
        self,
        week: int,
        open_date: str,
        long_df: pd.DataFrame,
        short_df: pd.DataFrame,
        spy_price: float,
        vti_price: float = 0.0,
        top_n: int = 10,
    ):
        """Allocate $100K each side equally across top_n candidates."""
        self.state.current_week = week
        if not self.state.start_date:
            self.state.start_date = open_date
        self.state.spy_entry_price = spy_price
        self.state.vti_entry_price = vti_price

        def _build_positions(df: pd.DataFrame, side: str) -> List[Position]:
            if df.empty:
                return []
            top = df.head(top_n)
            per_position = CAPITAL_PER_SIDE / len(top)
            positions = []
            for _, row in top.iterrows():
                price = float(row["price"])
                if price <= 0:
                    continue
                positions.append(Position(
                    ticker=row["ticker"],
                    side=side,
                    week=week,
                    entry_date=open_date,
                    entry_price=price,
                    shares=per_position / price,
                    score=float(row.get("score", 0)),
                    name=str(row.get("name", "")),
                    indices=str(row.get("indices", "")),
                ))
            return positions

        self.state.open_long = _build_positions(long_df, "long")
        self.state.open_short = _build_positions(short_df, "short")

        logger.info(
            "Week %d opened: %d longs, %d shorts @ SPY %.2f",
            week, len(self.state.open_long), len(self.state.open_short), spy_price,
        )

    def close_week(
        self,
        close_date: str,
        price_lookup: Dict[str, float],
        spy_close_price: float,
        vti_close_price: float = 0.0,
    ) -> WeeklyResult:
        """
        Mark all open positions as closed at the given prices.
        price_lookup: {ticker → latest close price}
        """
        long_pnl = 0.0
        short_pnl = 0.0
        long_tickers = []
        short_tickers = []

        for pos in self.state.open_long:
            exit_price = price_lookup.get(pos.ticker, pos.entry_price)
            pnl = (exit_price - pos.entry_price) * pos.shares
            pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
            long_pnl += pnl
            long_tickers.append(pos.ticker)
            self.state.closed_trades.append(ClosedTrade(
                ticker=pos.ticker, side="long",
                week=pos.week,
                entry_date=pos.entry_date, exit_date=close_date,
                entry_price=pos.entry_price, exit_price=exit_price,
                shares=pos.shares, pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2),
            ))

        for pos in self.state.open_short:
            exit_price = price_lookup.get(pos.ticker, pos.entry_price)
            # Short: profit when price falls
            pnl = (pos.entry_price - exit_price) * pos.shares
            pnl_pct = (pos.entry_price - exit_price) / pos.entry_price * 100
            short_pnl += pnl
            short_tickers.append(pos.ticker)
            self.state.closed_trades.append(ClosedTrade(
                ticker=pos.ticker, side="short",
                week=pos.week,
                entry_date=pos.entry_date, exit_date=close_date,
                entry_price=pos.entry_price, exit_price=exit_price,
                shares=pos.shares, pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2),
            ))

        # Benchmark P&L: $100K long each benchmark
        spy_pnl = 0.0
        if self.state.spy_entry_price > 0:
            spy_shares = CAPITAL_PER_SIDE / self.state.spy_entry_price
            spy_pnl = (spy_close_price - self.state.spy_entry_price) * spy_shares

        vti_pnl = 0.0
        if self.state.vti_entry_price > 0 and vti_close_price > 0:
            vti_shares = CAPITAL_PER_SIDE / self.state.vti_entry_price
            vti_pnl = (vti_close_price - self.state.vti_entry_price) * vti_shares

        week_num = self.state.current_week
        result = WeeklyResult(
            week=week_num,
            start_date=self.state.open_long[0].entry_date if self.state.open_long else "",
            end_date=close_date,
            long_pnl=round(long_pnl, 2),
            short_pnl=round(short_pnl, 2),
            combined_pnl=round(long_pnl + short_pnl, 2),
            spy_pnl=round(spy_pnl, 2),
            spy_open=self.state.spy_entry_price,
            spy_close=spy_close_price,
            vti_pnl=round(vti_pnl, 2),
            vti_open=self.state.vti_entry_price,
            vti_close=vti_close_price,
            long_tickers=long_tickers,
            short_tickers=short_tickers,
        )
        self.state.weekly_results.append(result)

        # Clear open positions
        self.state.open_long = []
        self.state.open_short = []
        self.state.spy_entry_price = 0.0

        logger.info(
            "Week %d closed: long P&L $%.0f, short P&L $%.0f, SPY P&L $%.0f",
            week_num, long_pnl, short_pnl, spy_pnl,
        )
        return result

    # ── Summary helpers ───────────────────────────────────────────────────────

    def cumulative_summary(self) -> dict:
        if not self.state.weekly_results:
            return {}
        total_long = sum(r.long_pnl for r in self.state.weekly_results)
        total_short = sum(r.short_pnl for r in self.state.weekly_results)
        total_combined = sum(r.combined_pnl for r in self.state.weekly_results)
        total_spy = sum(r.spy_pnl for r in self.state.weekly_results)
        total_vti = sum(r.vti_pnl for r in self.state.weekly_results)
        weeks = len(self.state.weekly_results)
        return {
            "weeks_completed": weeks,
            "total_long_pnl": round(total_long, 2),
            "total_short_pnl": round(total_short, 2),
            "total_combined_pnl": round(total_combined, 2),
            "total_spy_pnl": round(total_spy, 2),
            "total_vti_pnl": round(total_vti, 2),
            "alpha_vs_spy": round(total_combined - total_spy, 2),
            "alpha_vs_vti": round(total_combined - total_vti, 2),
            "long_return_pct": round(total_long / CAPITAL_PER_SIDE * 100, 2),
            "short_return_pct": round(total_short / CAPITAL_PER_SIDE * 100, 2),
            "combined_return_pct": round(total_combined / (CAPITAL_PER_SIDE * 2) * 100, 2),
            "spy_return_pct": round(total_spy / CAPITAL_PER_SIDE * 100, 2),
            "vti_return_pct": round(total_vti / CAPITAL_PER_SIDE * 100, 2),
        }

    def weekly_table(self) -> pd.DataFrame:
        if not self.state.weekly_results:
            return pd.DataFrame()
        rows = []
        for r in self.state.weekly_results:
            rows.append({
                "week": r.week,
                "start": r.start_date,
                "end": r.end_date,
                "long_pnl": r.long_pnl,
                "short_pnl": r.short_pnl,
                "combined_pnl": r.combined_pnl,
                "spy_pnl": r.spy_pnl,
                "vti_pnl": r.vti_pnl,
                "alpha_spy": round(r.combined_pnl - r.spy_pnl, 2),
                "alpha_vti": round(r.combined_pnl - r.vti_pnl, 2),
            })
        return pd.DataFrame(rows)

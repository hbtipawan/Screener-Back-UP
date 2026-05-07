#!/usr/bin/env python3
"""
════════════════════════════════════════════════════════════════════════════════
earnings_phase.py — VPCI v4 Earnings Phase Layer
════════════════════════════════════════════════════════════════════════════════
Drop-in module that adds earnings-phase awareness to the existing VPCI v3 system.
Validated by backtest of 1,036 trades on 60 NSE stocks (2010-2026):
    - POST 1-30d window:  PF 5.74 vs system 2.52  (p=0.018, statistically sig)
    - PRE 5-10d window:   PF 4.35 (directional, n=14 small sample)
    - PRE 11-45d window:  PF 1.58 (weakest — discount this bucket)
    - POST 31-60d:        PF 1.77 (drift fading)

Usage:
    from earnings_phase import classify_phase, position_size_multiplier
    phase, days, ref = classify_phase("RELIANCE.NS")
    mult = position_size_multiplier(phase)
════════════════════════════════════════════════════════════════════════════════
"""
import warnings
from datetime import date
import pandas as pd
import yfinance as yf
import streamlit as st

warnings.filterwarnings("ignore")


# ─── Phase priority (lower = higher conviction signal) ──────────────────────
PHASE_PRIORITY = {
    "POST_SWEET":   1,   # ★★★ 16-30d after result | PF 7.18
    "POST_HOT":     2,   # ★★★ 1-15d after result  | PF 4.5-5.4
    "PRE_HOT":      3,   # ★★  5-10d before result | PF 4.35
    "PRE_IMMINENT": 4,   # ★★  0-4d before result  | PF 4.23 (gap risk)
    "STANDARD":     5,   # ★   >60d from any result| PF 2.27 baseline
    "POST_FADING":  6,   # ⚠   31-60d after result | PF 1.77
    "PRE_AVOID":    7,   # ⚠⚠  11-45d before result| PF 1.58 weakest
    "UNKNOWN":      8,
}

PHASE_LABELS = {
    "POST_SWEET":   "★★★ POST 16-30d",
    "POST_HOT":     "★★★ POST 1-15d",
    "PRE_HOT":      "★★ PRE 5-10d",
    "PRE_IMMINENT": "★★ PRE 0-4d (gap risk)",
    "STANDARD":     "★ STANDARD",
    "POST_FADING":  "⚠ POST 31-60d (fading)",
    "PRE_AVOID":    "⚠⚠ PRE 11-45d (weak)",
    "UNKNOWN":      "? No earnings data",
}

PHASE_EMOJI = {
    "POST_SWEET":   "🟢",
    "POST_HOT":     "🟢",
    "PRE_HOT":      "🟢",
    "PRE_IMMINENT": "🟡",
    "STANDARD":     "⚪",
    "POST_FADING":  "🟠",
    "PRE_AVOID":    "🔴",
    "UNKNOWN":      "⚫",
}

# Position sizing multiplier per phase (validated from backtest)
PHASE_SIZE_MULT = {
    "POST_SWEET":   1.0,    # full size — best bucket
    "POST_HOT":     1.0,    # full size
    "PRE_HOT":      1.0,    # full size
    "PRE_IMMINENT": 0.5,    # half (gap risk)
    "STANDARD":     1.0,    # full size baseline
    "POST_FADING":  0.75,   # reduced (drift fading)
    "PRE_AVOID":    0.5,    # half (weakest window)
    "UNKNOWN":      1.0,    # default to full when no data
}


# ─── Cached earnings fetcher (Streamlit-aware, 24h TTL) ─────────────────────
@st.cache_data(ttl=86400, show_spinner=False)
def get_earnings_dates(yf_symbol):
    """
    Fetch sorted list of past + upcoming earnings dates (date objects).
    Cached per-symbol for 24 hours via Streamlit's cache.
    Returns [] if data unavailable.
    """
    try:
        t = yf.Ticker(yf_symbol)
        ed = t.earnings_dates
        if ed is None or len(ed) == 0:
            return []
        dates = []
        for idx in ed.index:
            dt = idx.tz_localize(None) if idx.tz else pd.Timestamp(idx)
            dates.append(dt.date())
        return sorted(set(dates))
    except Exception:
        return []


def classify_phase_from_dates(entry_date, earnings_dates):
    """
    Pure function — classify a date relative to a list of earnings dates.
    Returns (phase_tag, days_value, ref_date).
    days_value is signed: negative = days BEFORE next, positive = days SINCE last.
    """
    if isinstance(entry_date, pd.Timestamp):
        entry = entry_date.date()
    elif hasattr(entry_date, 'date') and not isinstance(entry_date, date):
        entry = entry_date.date()
    else:
        entry = entry_date

    if not earnings_dates:
        return "UNKNOWN", None, None

    past   = [d for d in earnings_dates if d <= entry]
    future = [d for d in earnings_dates if d >  entry]

    days_since = (entry - past[-1]).days if past   else 9999
    days_until = (future[0] - entry).days if future else 9999

    # Whichever event is closer dominates classification
    if days_until <= days_since:
        d = days_until
        ref = future[0] if future else None
        if d <= 4:   return "PRE_IMMINENT", -d, ref
        if d <= 10:  return "PRE_HOT",      -d, ref
        if d <= 45:  return "PRE_AVOID",    -d, ref
        return "STANDARD", -d, ref
    else:
        d = days_since
        ref = past[-1] if past else None
        if d <= 15:  return "POST_HOT",     d, ref
        if d <= 30:  return "POST_SWEET",   d, ref
        if d <= 60:  return "POST_FADING",  d, ref
        return "STANDARD", d, ref


def classify_phase(yf_symbol, entry_date=None):
    """
    Convenience wrapper — fetch earnings + classify in one call.
    entry_date defaults to today.
    """
    if entry_date is None:
        entry_date = date.today()
    ed = get_earnings_dates(yf_symbol)
    return classify_phase_from_dates(entry_date, ed)


def position_size_multiplier(phase_tag):
    return PHASE_SIZE_MULT.get(phase_tag, 1.0)


def phase_priority(phase_tag):
    """Sort key — lower = higher priority."""
    return PHASE_PRIORITY.get(phase_tag, 99)


def phase_label(phase_tag):
    return PHASE_LABELS.get(phase_tag, phase_tag)


def phase_emoji(phase_tag):
    return PHASE_EMOJI.get(phase_tag, "")


def format_phase_days(phase_tag, days):
    """Human-readable days string for UI."""
    if days is None:        return "—"
    if abs(days) >= 9999:   return "no data"
    if days < 0:            return f"{abs(days)}d to result"
    return f"{days}d after result"


def to_yf_symbol(symbol, market_flag):
    """Convert plain symbol + market flag to Yahoo Finance ticker."""
    if market_flag == "NSE":  return f"{symbol}.NS"
    if market_flag == "BSE":  return f"{symbol}.BO"
    return symbol  # US/ETF

#!/usr/bin/env python3
"""
════════════════════════════════════════════════════════════════════════════════
earnings_phase.py — VPCI v4 Earnings Phase Layer (v2 — RATE-LIMIT HARDENED)
════════════════════════════════════════════════════════════════════════════════
Drop-in module that adds earnings-phase awareness to the existing VPCI v3 system.

CHANGES vs v1:
- yfinance.earnings_dates is rate-limited on Streamlit Cloud → was silently
  swallowed in v1, producing all-zero phase counts.
- v2 detects rate-limit, exposes diagnostics, and adds two fallbacks:
    Tier 1: yfinance.earnings_dates  (works locally; often blocked on cloud)
    Tier 2: yfinance.calendar.earningsDate  (single date, lighter API)
    Tier 3: User-provided earnings_overrides.csv  (manual quarter map)
- Returns proper diagnostics so UI can tell user WHY phase is UNKNOWN.

Usage:
    from earnings_phase import classify_phase, position_size_multiplier
    phase, days, ref = classify_phase("RELIANCE.NS")
    mult = position_size_multiplier(phase)
════════════════════════════════════════════════════════════════════════════════
"""
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
import pandas as pd
import yfinance as yf
import streamlit as st

warnings.filterwarnings("ignore")

# Counters for diagnostics — reset per scan via reset_diagnostics()
DIAGNOSTICS = {
    "tier1_ok":          0,
    "tier1_empty":       0,
    "tier1_ratelimited": 0,
    "tier1_error":       0,
    "tier2_ok":          0,
    "tier2_error":       0,
    "tier3_manual":      0,
    "total_unknown":     0,
}


def reset_diagnostics():
    """Call at the start of each scan so counters reflect that run only."""
    for k in DIAGNOSTICS:
        DIAGNOSTICS[k] = 0


def get_diagnostics():
    return dict(DIAGNOSTICS)


# ─── Phase priority (lower = higher conviction signal) ──────────────────────
PHASE_PRIORITY = {
    "POST_SWEET":   1,
    "POST_HOT":     2,
    "PRE_HOT":      3,
    "PRE_IMMINENT": 4,
    "STANDARD":     5,
    "POST_FADING":  6,
    "PRE_AVOID":    7,
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

PHASE_SIZE_MULT = {
    "POST_SWEET":   1.0,
    "POST_HOT":     1.0,
    "PRE_HOT":      1.0,
    "PRE_IMMINENT": 0.5,
    "STANDARD":     1.0,
    "POST_FADING":  0.75,
    "PRE_AVOID":    0.5,
    "UNKNOWN":      1.0,
}


# ─── Tier 3: optional manual override CSV ──────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _load_manual_overrides():
    """
    Load earnings_overrides.csv from repo root if it exists.
    Format:
        symbol,last_result,next_result
        RELIANCE,2026-04-24,2026-07-17
        TCS,2026-04-09,2026-07-09
    Used as Tier 3 fallback when Yahoo blocks earnings calls.
    Returns dict {SYMBOL: [date1, date2, ...]}
    """
    path = Path("earnings_overrides.csv")
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path)
        df.columns = [c.lower().strip() for c in df.columns]
        out = {}
        for _, row in df.iterrows():
            sym = str(row.get("symbol", "")).strip().upper()
            if not sym:
                continue
            dates = []
            for col in ["last_result", "next_result"]:
                v = row.get(col)
                if v and not pd.isna(v):
                    try:
                        dates.append(pd.Timestamp(v).date())
                    except Exception:
                        pass
            if dates:
                out[sym] = sorted(set(dates))
        return out
    except Exception:
        return {}


def _is_rate_limit_error(exc):
    """Detect Yahoo rate-limit error from various exception types."""
    msg = str(exc).lower()
    return any(s in msg for s in [
        "rate limit", "too many requests", "429",
        "yfratelimiterror", "rate limited"
    ])


# ─── Cached earnings fetcher (multi-tier with diagnostics) ─────────────────
@st.cache_data(ttl=86400, show_spinner=False)
def get_earnings_dates(yf_symbol):
    """
    Multi-tier earnings date fetcher.
    Returns sorted list of date objects, or [] if all tiers fail.
    Updates DIAGNOSTICS counters so UI can report blockage cause.
    """
    plain_sym = yf_symbol.replace(".NS", "").replace(".BO", "").upper()

    # ─── Tier 3 first (instant, never fails if user provided overrides) ───
    overrides = _load_manual_overrides()
    if plain_sym in overrides:
        DIAGNOSTICS["tier3_manual"] += 1
        return overrides[plain_sym]

    # ─── Tier 1: yfinance.earnings_dates (full history) ───
    try:
        t = yf.Ticker(yf_symbol)
        ed = t.earnings_dates
        if ed is not None and len(ed) > 0:
            dates = []
            for idx in ed.index:
                dt = idx.tz_localize(None) if idx.tz else pd.Timestamp(idx)
                dates.append(dt.date())
            DIAGNOSTICS["tier1_ok"] += 1
            return sorted(set(dates))
        else:
            DIAGNOSTICS["tier1_empty"] += 1
    except Exception as e:
        if _is_rate_limit_error(e):
            DIAGNOSTICS["tier1_ratelimited"] += 1
        else:
            DIAGNOSTICS["tier1_error"] += 1

    # ─── Tier 2: yfinance.calendar (lighter API, single event) ───
    try:
        t = yf.Ticker(yf_symbol)
        cal = t.calendar
        if cal is not None:
            ed_field = None
            if isinstance(cal, dict):
                ed_field = cal.get("Earnings Date") or cal.get("earningsDate")
            elif hasattr(cal, "loc"):
                try:
                    if "Earnings Date" in cal.index:
                        ed_field = cal.loc["Earnings Date"].iloc[0]
                except Exception:
                    pass
            if ed_field is not None:
                if isinstance(ed_field, list) and len(ed_field) > 0:
                    ed_field = ed_field[0]
                try:
                    next_dt = pd.Timestamp(ed_field).date()
                    DIAGNOSTICS["tier2_ok"] += 1
                    # Synthesise an estimated last earnings ~91 days back
                    # so phase classifier has both anchors
                    return [next_dt - timedelta(days=91), next_dt]
                except Exception:
                    pass
    except Exception:
        DIAGNOSTICS["tier2_error"] += 1

    DIAGNOSTICS["total_unknown"] += 1
    return []


def classify_phase_from_dates(entry_date, earnings_dates):
    """Pure classifier — returns (phase_tag, days_value, ref_date)."""
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
    if entry_date is None:
        entry_date = date.today()
    ed = get_earnings_dates(yf_symbol)
    return classify_phase_from_dates(entry_date, ed)


def position_size_multiplier(phase_tag):
    return PHASE_SIZE_MULT.get(phase_tag, 1.0)


def phase_priority(phase_tag):
    return PHASE_PRIORITY.get(phase_tag, 99)


def phase_label(phase_tag):
    return PHASE_LABELS.get(phase_tag, phase_tag)


def phase_emoji(phase_tag):
    return PHASE_EMOJI.get(phase_tag, "")


def format_phase_days(phase_tag, days):
    if days is None:        return "—"
    if abs(days) >= 9999:   return "no data"
    if days < 0:            return f"{abs(days)}d to result"
    return f"{days}d after result"


def to_yf_symbol(symbol, market_flag):
    if market_flag == "NSE":  return f"{symbol}.NS"
    if market_flag == "BSE":  return f"{symbol}.BO"
    return symbol

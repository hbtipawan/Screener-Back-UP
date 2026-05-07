#!/usr/bin/env python3
"""
════════════════════════════════════════════════════════════════════════════════
earnings_phase.py — VPCI v4.3 — NSE OFFICIAL API EDITION
════════════════════════════════════════════════════════════════════════════════
Drop-in earnings phase classifier with official NSE data as PRIMARY source.
 
DATA SOURCES (priority order):
  Tier 1: NSE corporate-announcements API   ← PRIMARY (96%+ coverage)
          Bulk fetch of past 4 months in ONE call. Cached 24h.
  Tier 2: NSE event-calendar API            ← UPCOMING results
          Bulk fetch of next ~30 days. Cached 24h.
  Tier 3: User-provided earnings_overrides.csv  ← MANUAL OVERRIDE
  Tier 4: yfinance                           ← Legacy fallback
 
KEY: Tier 1+2 fetch ALL data in just 2 API calls (cached). Per-symbol lookup
is then instant in-memory dict access. No per-stock fetches → no rate limits.
 
Usage:
    from earnings_phase import classify_phase, position_size_multiplier
    phase, days, ref = classify_phase("RELIANCE")
    mult = position_size_multiplier(phase)
════════════════════════════════════════════════════════════════════════════════
"""
import warnings
import requests
from datetime import date, datetime, timedelta
from pathlib import Path
import pandas as pd
import yfinance as yf
import streamlit as st
 
warnings.filterwarnings("ignore")
 
# ─── Diagnostics counters ───────────────────────────────────────────────────
DIAGNOSTICS = {
    "tier1_nse_resolved":   0,
    "tier2_nse_upcoming":   0,
    "tier3_csv_override":   0,
    "tier4_yfinance":       0,
    "total_unknown":        0,
    "nse_api_error":        None,
}
 
 
def reset_diagnostics():
    for k in list(DIAGNOSTICS.keys()):
        DIAGNOSTICS[k] = 0 if k != "nse_api_error" else None
 
 
def get_diagnostics():
    return dict(DIAGNOSTICS)
 
 
# ─── Phase priority & metadata ──────────────────────────────────────────────
PHASE_PRIORITY = {
    "POST_SWEET":1, "POST_HOT":2, "PRE_HOT":3, "PRE_IMMINENT":4,
    "STANDARD":5, "POST_FADING":6, "PRE_AVOID":7, "UNKNOWN":8,
}
PHASE_LABELS = {
    "POST_SWEET":"★★★ POST 16-30d", "POST_HOT":"★★★ POST 1-15d",
    "PRE_HOT":"★★ PRE 5-10d", "PRE_IMMINENT":"★★ PRE 0-4d (gap risk)",
    "STANDARD":"★ STANDARD", "POST_FADING":"⚠ POST 31-60d (fading)",
    "PRE_AVOID":"⚠⚠ PRE 11-45d (weak)", "UNKNOWN":"? No earnings data",
}
PHASE_EMOJI = {
    "POST_SWEET":"🟢", "POST_HOT":"🟢", "PRE_HOT":"🟢", "PRE_IMMINENT":"🟡",
    "STANDARD":"⚪", "POST_FADING":"🟠", "PRE_AVOID":"🔴", "UNKNOWN":"⚫",
}
PHASE_SIZE_MULT = {
    "POST_SWEET":1.0, "POST_HOT":1.0, "PRE_HOT":1.0, "PRE_IMMINENT":0.5,
    "STANDARD":1.0, "POST_FADING":0.75, "PRE_AVOID":0.5, "UNKNOWN":1.0,
}
 
 
# ─── HTTP session helpers ───────────────────────────────────────────────────
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.nseindia.com/",
}
 
 
def _make_nse_session():
    s = requests.Session()
    try:
        s.get("https://www.nseindia.com/", headers=NSE_HEADERS, timeout=8)
    except Exception:
        pass
    return s
 
 
def _is_results_announcement(entry):
    """Filter NSE announcements to only quarterly result entries."""
    desc = (entry.get("desc") or "").lower()
    text = (entry.get("attchmntText") or "").lower()
    if not ("board meeting" in desc or "financial result" in desc or "outcome" in desc):
        return False
    return any(kw in text for kw in [
        "financial result", "financial statement", "audited", "unaudited",
        "earnings", "quarter ended", "year ended", "approved the result",
    ])
 
 
# ─── TIER 1: bulk past results from NSE ────────────────────────────────────
@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_nse_past_results():
    """One API call → dict {SYMBOL: latest_result_date} for ~2,200 stocks."""
    today = date.today()
    from_date = (today - timedelta(days=120)).strftime("%d-%m-%Y")
    to_date   = today.strftime("%d-%m-%Y")
 
    s = _make_nse_session()
    try:
        r = s.get(
            "https://www.nseindia.com/api/corporate-announcements",
            params={"index": "equities", "from_date": from_date, "to_date": to_date},
            headers=NSE_HEADERS, timeout=60,
        )
        if not r.ok:
            DIAGNOSTICS["nse_api_error"] = f"HTTP {r.status_code}"
            return {}
        data = r.json()
    except Exception as e:
        DIAGNOSTICS["nse_api_error"] = f"{type(e).__name__}: {str(e)[:80]}"
        return {}
 
    latest = {}
    for entry in data:
        if not _is_results_announcement(entry):
            continue
        sym = (entry.get("symbol") or "").upper().strip()
        if not sym:
            continue
        dt_str = entry.get("an_dt") or entry.get("sort_date") or ""
        try:
            dt = datetime.strptime(dt_str.split()[0], "%d-%b-%Y").date()
        except Exception:
            try:
                dt = datetime.strptime(dt_str[:10], "%Y-%m-%d").date()
            except Exception:
                continue
        if dt > today:
            continue
        if sym not in latest or dt > latest[sym]:
            latest[sym] = dt
    return latest
 
 
# ─── TIER 2: bulk upcoming results from NSE ────────────────────────────────
@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_nse_upcoming_results():
    """One API call → dict {SYMBOL: next_result_date}."""
    s = _make_nse_session()
    try:
        r = s.get("https://www.nseindia.com/api/event-calendar",
                  headers=NSE_HEADERS, timeout=30)
        if not r.ok:
            return {}
        data = r.json()
    except Exception:
        return {}
 
    upcoming = {}
    today = date.today()
    for entry in data:
        purpose = (entry.get("purpose") or "").lower()
        bm_desc = (entry.get("bm_desc") or "").lower()
        if "financial result" not in purpose and "financial result" not in bm_desc:
            continue
        sym = (entry.get("symbol") or "").upper().strip()
        if not sym:
            continue
        try:
            dt = datetime.strptime(entry.get("date",""), "%d-%b-%Y").date()
        except Exception:
            continue
        if dt < today:
            continue
        if sym not in upcoming or dt < upcoming[sym]:
            upcoming[sym] = dt
    return upcoming
 
 
# ─── TIER 3: CSV overrides ──────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _load_manual_overrides():
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
 
 
# ─── Main entry: classify a symbol ──────────────────────────────────────────
def get_earnings_dates(symbol_or_yf):
    """Returns sorted list of earnings dates using all 4 tiers."""
    plain = symbol_or_yf.replace(".NS","").replace(".BO","").upper().strip()
 
    # Tier 3 — manual override wins
    overrides = _load_manual_overrides()
    if plain in overrides:
        DIAGNOSTICS["tier3_csv_override"] += 1
        return overrides[plain]
 
    dates = []
 
    # Tier 1
    past_map = _fetch_nse_past_results()
    if plain in past_map:
        dates.append(past_map[plain])
        DIAGNOSTICS["tier1_nse_resolved"] += 1
 
    # Tier 2
    upcoming_map = _fetch_nse_upcoming_results()
    if plain in upcoming_map:
        dates.append(upcoming_map[plain])
        DIAGNOSTICS["tier2_nse_upcoming"] += 1
 
    if dates:
        return sorted(set(dates))
 
    # Tier 4 — yfinance fallback
    yf_sym = symbol_or_yf if (".NS" in symbol_or_yf or ".BO" in symbol_or_yf) else f"{plain}.NS"
    try:
        t = yf.Ticker(yf_sym)
        ed = t.earnings_dates
        if ed is not None and len(ed) > 0:
            yf_dates = []
            for idx in ed.index:
                dt = idx.tz_localize(None) if idx.tz else pd.Timestamp(idx)
                yf_dates.append(dt.date())
            if yf_dates:
                DIAGNOSTICS["tier4_yfinance"] += 1
                return sorted(set(yf_dates))
    except Exception:
        pass
 
    DIAGNOSTICS["total_unknown"] += 1
    return []
 
 
# ─── Pure classifier ────────────────────────────────────────────────────────
def classify_phase_from_dates(entry_date, earnings_dates):
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
 
 
def classify_phase(symbol, entry_date=None):
    if entry_date is None:
        entry_date = date.today()
    return classify_phase_from_dates(entry_date, get_earnings_dates(symbol))
 
 
# ─── Helpers ────────────────────────────────────────────────────────────────
def position_size_multiplier(p): return PHASE_SIZE_MULT.get(p, 1.0)
def phase_priority(p):           return PHASE_PRIORITY.get(p, 99)
def phase_label(p):              return PHASE_LABELS.get(p, p)
def phase_emoji(p):              return PHASE_EMOJI.get(p, "")
 
def format_phase_days(phase_tag, days):
    if days is None:        return "—"
    if abs(days) >= 9999:   return "no data"
    if days < 0:            return f"{abs(days)}d to result"
    return f"{days}d after result"
 
 
def to_yf_symbol(symbol, market_flag):
    if market_flag == "NSE":  return f"{symbol}.NS"
    if market_flag == "BSE":  return f"{symbol}.BO"
    return symbol
 
 
# ─── Pre-warm: force-load both NSE caches up front ─────────────────────────
def prewarm_nse_cache():
    """Loads both bulk caches; returns (past_count, upcoming_count, error)."""
    try:
        past = _fetch_nse_past_results()
        upcoming = _fetch_nse_upcoming_results()
        return len(past), len(upcoming), DIAGNOSTICS.get("nse_api_error")
    except Exception as e:
        return 0, 0, f"prewarm failed: {e}"
 

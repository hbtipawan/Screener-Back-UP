# Screener — Sector Leadership, Weekly History & Resume Patch

This patch adds three professional capabilities to the existing VPCI screener
**without changing any of the core scoring or gate logic**:

1. **🏭 Sector Leadership tab** — counts stocks passing **G5 (VPCI accumulation) ∧ G6 (Leader RS) ∧ G7 (Above 40-week MA)** per Sector and per Industry, so you can see which corner of the market the institutional confirmation gates are firing in this week.
2. **📈 Sector Rotation tab** — week-over-week history of the leadership table, so you can spot sectors rotating in (count rising) or out (count falling).
3. **💾 Resume on disconnect** — periodic checkpointing of in-progress scans to `st.session_state` plus a downloadable JSON checkpoint. If your session drops, click *Run Market Scan* again and it picks up where it stopped.

---

## Files in this patch

| File | What it does |
|---|---|
| `app.py` | Modified — new tabs, checkpointing, recovery sidebar, schema-aware NSE loader |
| `sector_history.py` | **New module** — sector mapping, GitHub-backed history, checkpoint helpers |
| `EQUITY_L_2.csv` | **Replaced** — now uses your new file with `companyId, Name, Sector, Industry` |

Drop these three files into the root of your `Screener-Back-UP` repo, replacing the existing `app.py` and `EQUITY_L_2.csv`. No changes are needed to `vpci_engine.py`, `earnings_phase.py`, `vpci_ranker.py`, or `requirements.txt`.

---

## How the Sector Leadership tab works

After every scan, the new **🏭 Sector Leadership** tab joins your scan results to the Sector / Industry columns from `EQUITY_L_2.csv` and produces four ranked tables:

| Cut | What it tells you |
|---|---|
| Sectors — G5 ∧ G6 ∧ G7 (strict) | Where leadership is **fully confirmed** — VPCI accumulation AND RS positive AND price above 40w |
| Industries — G5 ∧ G6 ∧ G7 (strict) | The exact sub-theme inside the sector that's leading |
| Sectors — G5 ∨ G6 ∨ G7 (broad) | Sectors with breadth firing on at least one gate — early-rotation candidates |
| Industries — G5 ∨ G6 ∨ G7 (broad) | Same, drilled down |

Each row shows **stocks_passing**, **total_in_universe**, and **hit_rate_%**. Sort by `stocks_passing` for absolute leadership; sort by `hit_rate_%` for cleaner sectors (e.g., a sector with 4/5 passing is purer than one with 8/40).

A small stock-level table at the bottom lists every individual stock passing all three of G5, G6, and G7 with its sector tags — useful as a watchlist source.

---

## How week-over-week rotation works

At the bottom of the Sector Leadership tab is a **💾 Save snapshot** button. Each save:

- Always writes the snapshot to `st.session_state` (visible in the Sector Rotation tab during the same session).
- **If GitHub secrets are configured** (see below), also pushes a JSON file to your repo so the snapshot survives restarts and accumulates over weeks.

The **📈 Sector Rotation** tab pulls every saved snapshot for the current market and shows a Sector × Week grid plus week-over-week deltas (Rotating IN / Rotating OUT).

### Configuring GitHub persistence (one-time, ~3 minutes)

1. **Generate a GitHub Personal Access Token (fine-grained, recommended):**
   - GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.
   - Scope it to **only** the `Screener-Back-UP` repo.
   - Repository permissions: **Contents: Read and write**.
   - Copy the token (starts with `github_pat_…`).

2. **Add it to Streamlit Cloud secrets:**
   - On `share.streamlit.io`, open your app → **Settings** → **Secrets**.
   - Paste:
     ```toml
     [github]
     token  = "github_pat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
     repo   = "hbtipawan/Screener-Back-UP"
     branch = "main"
     folder = "history"
     ```
   - Save. Streamlit auto-restarts the app.

3. **Done.** The first time you click *Save snapshot*, a `history/` folder appears in your repo with a file like `sector_2026-05-09_NSE.json`. Future weeks add more files.

> If you skip this step the app still works perfectly — snapshots just stay in the current browser session and disappear when the container restarts. You can also use the **⬇ Download snapshot** button to save manually and version-control them yourself.

---

## How resume-on-disconnect works

The scan loop now checkpoints every **25 symbols** to `st.session_state`. The checkpoint stores: market, full symbol universe, partial results, failed symbols, and the list of completed symbols.

### What is and isn't covered

| Scenario | Recovery |
|---|---|
| Brief Wi-Fi blip, browser stays open | ✅ Streamlit auto-reconnects, scan continues |
| Streamlit reruns triggered by widget interaction | ✅ Click *Run Market Scan*, resumes |
| Browser tab refresh, same session id | ✅ Click *Run Market Scan*, resumes |
| Browser closed / different device / next day | ⚠️ Use the manual checkpoint download below |
| Streamlit Cloud container restart | ⚠️ Use the manual checkpoint download below |

### Manual checkpoint flow (covers the last two cases)

1. **During or after a scan:** open the sidebar → **💾 Resume & Recovery** → **⬇ Download checkpoint (.json)**.
2. **Next session:** sidebar → **💾 Resume & Recovery** → **Restore checkpoint** → upload the JSON.
3. Click **🚀 Run Market Scan** — it resumes from the uploaded checkpoint.

After a scan completes successfully the checkpoint is auto-cleared.

---

## Why this approach (engineering notes)

- **`st.cache_data` + `requests` for GitHub** instead of the heavier `PyGithub` library — keeps `requirements.txt` unchanged.
- **Checkpoints are session-scoped, not file-scoped** because Streamlit Community Cloud's filesystem is ephemeral. Writing to disk would give a false sense of safety.
- **GitHub Contents API** is used (not git operations), so no SSH keys, no git config, no merge conflicts — every snapshot is an atomic PUT with the previous file's SHA for safe updates.
- **Checkpoint validity check** compares the saved universe's first/last symbol and length against the current one — protects against accidentally resuming an NSE checkpoint on a BSE scan.
- **No core logic touched** — `vpci_engine.py`, `earnings_phase.py`, and `vpci_ranker.py` are untouched. The new tabs read from the existing `df_sorted` DataFrame.

---

## What the new EQUITY_L_2.csv changes

The new file replaces the legacy NSE master format (`SYMBOL, NAME OF COMPANY, SERIES, …`) with a leaner schema (`companyId, Name, Sector, Industry`). The updated `get_nse_stock_tickers()` function detects which schema is present and reads the right column, so both old and new files work — but only the new file enables the Sector tab.

Loaded universe: **1,787 NSE stocks**, **84 sectors**, **312 industries**.

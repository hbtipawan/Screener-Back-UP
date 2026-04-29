import streamlit as st
import pandas as pd
import warnings
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from vpci_engine import fetch_weekly_data, analyze_stock_v3, DEFAULT_PARAMS

warnings.filterwarnings("ignore")

# ─── PAGE CONFIGURATION ───
st.set_page_config(page_title="VPCI Quant Screener", page_icon="📈", layout="wide")

# ─── PROFESSIONAL HEADER ───
st.markdown("""
<div style='text-align: center; padding-top: 10px; padding-bottom: 20px;'>
    <h1 style='font-size: 3em; margin-bottom: 0px;'>📈 VPCI Quant Screener</h1>
    <p style='color: #888888; font-size: 1.2em;'>Advanced 7-Gate Momentum & Breakout Analysis System</p>
</div>
""", unsafe_allow_html=True)
st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
# LOCAL CSV FETCHERS (Dynamic & Bulletproof)
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data
def get_nse_stock_tickers():
    try:
        df = pd.read_csv("EQUITY_L_2.csv")
        df.columns = [str(c).strip().replace(" ", "_") for c in df.columns]
        if "SERIES" in df.columns:
            df = df[df["SERIES"] == "EQ"]
        return [str(t).strip() for t in df["SYMBOL"].tolist()]
    except Exception as e:
        st.error(f"🚨 Missing or broken EQUITY_L_2.csv: {e}")
        return ["RELIANCE","TCS","HDFCBANK"]

@st.cache_data
def get_bse_stock_tickers():
    try:
        df = pd.read_csv("bse_stocks.csv")
        if "Scrip Code" in df.columns:
            tickers = [str(t).strip() for t in df["Scrip Code"].tolist()]
        else:
            tickers = [str(t).strip() for t in df.iloc[:, 0].tolist()]
        return [t for t in tickers if t.isdigit()]
    except Exception as e:
        st.error(f"🚨 Missing or broken bse_stocks.csv: {e}")
        return ["500325", "532540", "500180"]

@st.cache_data
def fetch_us_symbols(min_price, min_mcap):
    try:
        df = pd.read_csv("us_stocks.csv", on_bad_lines="skip")
        df.columns = df.columns.str.strip().str.lower()
        
        sym_col = next((c for c in df.columns if 'symbol' in c or 'ticker' in c), df.columns[0])
        price_col = next((c for c in df.columns if 'sale' in c or 'price' in c or 'last' in c), None)
        mcap_col = next((c for c in df.columns if 'cap' in c or 'market' in c), None)
        
        symbols = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if not sym or "/" in sym or "^" in sym or len(sym) > 5 or sym.lower() == "nan" or sym.lower() == "symbol": 
                continue
            
            if price_col:
                try:
                    price = float(str(row[price_col]).replace("$", "").replace(",", ""))
                    if price < min_price: continue
                except: pass
                
            if mcap_col:
                try:
                    mcap = float(str(row[mcap_col]).replace(",", ""))
                    if mcap < min_mcap: continue
                except: pass
                
            symbols.append(sym)
            
        return symbols
    except Exception as e:
        st.error(f"🚨 Missing or broken us_stocks.csv: {e}")
        return ["AAPL","MSFT","GOOGL","AMZN"]

@st.cache_data
def fetch_etf_symbols(min_price):
    try:
        df = pd.read_csv("us_etfs.csv", on_bad_lines="skip")
        df.columns = df.columns.str.strip().str.lower()
        
        sym_col = next((c for c in df.columns if 'symbol' in c or 'ticker' in c), df.columns[0])
        price_col = next((c for c in df.columns if 'sale' in c or 'price' in c or 'last' in c), None)
        
        symbols = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if not sym or "/" in sym or len(sym) > 6 or sym.lower() == "nan" or sym.lower() == "symbol": 
                continue
                
            if price_col:
                try:
                    price = float(str(row[price_col]).replace("$", "").replace(",", ""))
                    if price < min_price: continue
                except: pass
                
            symbols.append(sym)
            
        return symbols
    except Exception as e:
        st.error(f"🚨 Missing or broken us_etfs.csv: {e}")
        return ["SPY","QQQ","IWM"]

# ═══════════════════════════════════════════════════════════════════════════════
# PROCESSING WORKER
# ═══════════════════════════════════════════════════════════════════════════════

def process_symbol(symbol, params, market_type):
    if market_type == "NSE":
        yf_sym = f"{symbol}.NS"
        df = fetch_weekly_data(yf_sym)
    elif market_type == "BSE":
        yf_sym = f"{symbol}.BO"
        df = fetch_weekly_data(yf_sym)
    else:
        df = fetch_weekly_data(symbol)
        
    if df is None: return None
    return analyze_stock_v3(symbol, df, params)

# ═══════════════════════════════════════════════════════════════════════════════
# UI SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════

st.sidebar.markdown("### ⚙️ Scan Configuration")
market_choice = st.sidebar.radio("🌐 Select Market", ["NSE Stocks", "BSE Stocks", "US Stocks", "US ETFs"])

st.sidebar.markdown("---")
st.sidebar.markdown("### 🎛️ Market Filters")

min_price, min_mcap = 5.0, 500000000.0
if market_choice == "US Stocks":
    min_price = st.sidebar.number_input("Min Price ($)", value=5.0)
    min_mcap = st.sidebar.number_input("Min Market Cap ($)", value=500000000.0)
elif market_choice == "US ETFs":
    min_price = st.sidebar.number_input("Min Price ($)", value=5.0)
else:
    st.sidebar.info("Standard filters automatically applied for Indian Markets.")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🎯 Algorithm Settings")
relaxed_mode = st.sidebar.toggle("Relaxed Mode (Allow 6/7 Gates)", value=False)

# Hide tech settings in an expander for a cleaner mobile experience
with st.sidebar.expander("🛠️ Advanced Settings"):
    workers = st.slider("Parallel Workers", min_value=5, max_value=30, value=15)
    test_limit = st.number_input("Limit Scan (0 = All)", min_value=0, max_value=10000, value=0)

st.sidebar.markdown("---")
# Full width primary button
run_scan = st.sidebar.button("🚀 Run Market Scan", type="primary", use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

if run_scan:
    params = {**DEFAULT_PARAMS, "relaxed": relaxed_mode, "av_key": "demo"}
    
    with st.spinner(f"Reading local database for {market_choice}..."):
        if market_choice == "NSE Stocks":
            symbols = get_nse_stock_tickers()
            market_flag = "NSE"
        elif market_choice == "BSE Stocks":
            symbols = get_bse_stock_tickers()
            market_flag = "BSE"
        elif market_choice == "US Stocks":
            symbols = fetch_us_symbols(min_price, min_mcap)
            market_flag = "US"
        else:
            symbols = fetch_etf_symbols(min_price)
            market_flag = "ETF"
            
    if test_limit > 0: symbols = symbols[:test_limit]
    
    st.info(f"📚 Loaded **{len(symbols)}** symbols. Commencing quantitative analysis...")

    results, failed = [], []
    progress_bar = st.progress(0)
    status_text = st.empty()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(process_symbol, s, params, market_flag): s for s in symbols}
        done = 0
        for f in as_completed(futs):
            done += 1
            progress_bar.progress(done / len(symbols))
            status_text.text(f"Scanning... {done} / {len(symbols)} processed")
            try:
                r = f.result()
                if r: results.append(r)
                else: failed.append(futs[f])
            except: failed.append(futs[f])

    status_text.empty()
    progress_bar.empty()

    # ─── VISUAL METRICS DASHBOARD ───
    st.markdown("### 📊 Scan Summary")
    met1, met2, met3 = st.columns(3)
    met1.metric("Total Symbols Analyzed", len(results) + len(failed))
    met2.metric("✅ Candidates Found", len(results))
    met3.metric("⚠️ Excluded / Insufficient Data", len(failed))
    st.divider()

    # ═══════════════════════════════════════════════════════════════════════════
    # DISPLAY & SMART MARKET CAP
    # ═══════════════════════════════════════════════════════════════════════════
    if results:
        df = pd.DataFrame(results)
        
        def status_label(row):
            if row.get("fresh_signal"): return "🔥 FRESH BUY"
            if row.get("fresh_ext_signal"): return "🔥 FRESH EXT"
            if row.get("full_entry"): return "★ BUYABLE (7/7)"
            if row.get("gates_ready_ext"): return "⚡ 7/7 EXTENDED"
            if row.get("relaxed_entry"): return "★ RELAXED (6/7)"
            if row.get("gate_count", 0) >= 6 and row.get("tier1_pass"): return "◉ WATCHLIST (6/7)"
            if row.get("gate_count", 0) >= 5: return "▲ MOMENTUM (5+)"
            return "Other"

        df["status"] = df.apply(status_label, axis=1)
        df_sorted = df.sort_values(["gate_count", "pct_near_52w"], ascending=[False, False])
        
        # SMART MCAP FETCH
        top_symbols = df_sorted[df_sorted["gate_count"] >= 5]["symbol"].tolist()
        mcap_dict = {}

        if top_symbols:
            with st.spinner(f"Fetching live Market Cap metadata..."):
                def fetch_mcap(sym):
                    try:
                        import yfinance as yf
                        yf_sym = f"{sym}.NS" if market_flag == "NSE" else f"{sym}.BO" if market_flag == "BSE" else sym
                        tkr = yf.Ticker(yf_sym)
                        try: return sym, tkr.fast_info['marketCap']
                        except:
                            try: return sym, tkr.fast_info.market_cap
                            except: return sym, tkr.info.get('marketCap', 0)
                    except: return sym, 0

                with ThreadPoolExecutor(max_workers=5) as executor:
                    for future in as_completed([executor.submit(fetch_mcap, s) for s in top_symbols]):
                        sym, mval = future.result()
                        mcap_dict[sym] = mval

        df_sorted['raw_mcap'] = df_sorted['symbol'].map(mcap_dict).fillna(0)

        def format_mcap(mcap):
            if not mcap or mcap == 0: return "N/A"
            if market_choice in ["NSE Stocks", "BSE Stocks"]:
                crores = mcap / 10000000
                if crores >= 1000: return f"{crores / 1000:.1f}K crore inr".replace(".0K", "K")
                return f"{crores:.0f} crore inr"
            else:
                if mcap >= 1e9: return f"${mcap / 1e9:.1f}B".replace(".0B", "B")
                return f"${mcap / 1e6:.1f}M"

        df_sorted["Market Cap"] = df_sorted["raw_mcap"].apply(format_mcap)
        
        # INJECT BSE COMPANY NAMES
        if market_flag == "BSE":
            try:
                bse_csv = pd.read_csv("bse_stocks.csv")
                name_col = "Scrip Name" if "Scrip Name" in bse_csv.columns else bse_csv.columns[2]
                code_col = "Scrip Code" if "Scrip Code" in bse_csv.columns else bse_csv.columns[0]
                bse_map = dict(zip(bse_csv[code_col].astype(str).str.strip(), bse_csv[name_col]))
                df_sorted.insert(1, "Company Name", df_sorted["symbol"].map(bse_map).fillna("Unknown"))
            except Exception as e:
                pass

        # UI COPY & FORMATTING
        df_ui = df_sorted.copy()
        cols = list(df_ui.columns)
        
        if "raw_mcap" in df_ui.columns: df_ui = df_ui.drop(columns=["raw_mcap"])
        
        # TradingView Links
        if market_choice == "NSE Stocks": df_ui["symbol"] = "https://in.tradingview.com/chart/?symbol=NSE:" + df_ui["symbol"]
        elif market_choice == "BSE Stocks": df_ui["symbol"] = "https://in.tradingview.com/chart/?symbol=BSE:" + df_ui["symbol"]
        else: df_ui["symbol"] = "https://www.tradingview.com/chart/?symbol=" + df_ui["symbol"]

        if "Market Cap" in cols:
            cols.remove("Market Cap")
            insert_idx = cols.index("Company Name") + 1 if "Company Name" in cols else (cols.index("symbol") + 1 if "symbol" in cols else 0)
            cols.insert(insert_idx, "Market Cap")
            df_ui = df_ui[[c for c in cols if c in df_ui.columns]]

        tv_config = {
            "symbol": st.column_config.LinkColumn("Symbol", display_text=r".*symbol=(?:NSE:|BSE:)?(.*)")
        }

        # ─── ORGANIZED RESULTS TABS ───
        tab1, tab2, tab3, tab4 = st.tabs(["🔥 Fresh Signals", "★ Buyable (7/7)", "◉ Watchlist (6/7)", "📋 All Results"])
        
        with tab1:
            fresh_df = df_ui[df_ui["status"].isin(["🔥 FRESH BUY", "🔥 FRESH EXT"])]
            if not fresh_df.empty: st.dataframe(fresh_df, use_container_width=True, column_config=tv_config, hide_index=True)
            else: st.info("No fresh breakout signals detected this week.")
        with tab2:
            buyable_df = df_ui[df_ui["status"] == "★ BUYABLE (7/7)"]
            if not buyable_df.empty: st.dataframe(buyable_df, use_container_width=True, column_config=tv_config, hide_index=True)
            else: st.info("No stocks passed all 7 criteria.")
        with tab3:
            watch_df = df_ui[df_ui["status"].isin(["★ RELAXED (6/7)", "◉ WATCHLIST (6/7)"])]
            if not watch_df.empty: st.dataframe(watch_df, use_container_width=True, column_config=tv_config, hide_index=True)
            else: st.info("No watchlist candidates found.")
        with tab4:
            st.dataframe(df_ui, use_container_width=True, column_config=tv_config, hide_index=True)
        
        st.write("") # Spacer
        if "raw_mcap" in df_sorted.columns: df_sorted = df_sorted.drop(columns=["raw_mcap"])
        
        # Centered Download Button
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            csv = df_sorted.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Full Results as CSV",
                data=csv,
                file_name=f"vpci_{market_flag.lower()}_results_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True
            )
    else:
        st.warning("⚠️ No stocks passed the minimum screener criteria.")
        
    if failed:
        with st.expander("⚠️ View Failed / Excluded Symbols"):
            st.write("These symbols were excluded due to insufficient trading history (< 42 weeks) or low volume.")
            st.write(", ".join(failed))

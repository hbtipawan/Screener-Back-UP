@st.cache_data
def fetch_us_symbols(min_price, min_mcap):
    try:
        df = pd.read_csv("us_stocks.csv", on_bad_lines="skip")
        df.columns = df.columns.str.strip().str.lower()
        
        # Dynamically find the symbol column, or default to the first column
        sym_col = next((c for c in df.columns if 'symbol' in c or 'ticker' in c), df.columns[0])
        price_col = next((c for c in df.columns if 'sale' in c or 'price' in c or 'last' in c), None)
        mcap_col = next((c for c in df.columns if 'cap' in c or 'market' in c), None)
        
        symbols = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if not sym or "/" in sym or "^" in sym or len(sym) > 5 or sym.lower() == "nan" or sym.lower() == "symbol": 
                continue
            
            # Only apply the Price filter if the column actually exists in your CSV
            if price_col:
                try:
                    price = float(str(row[price_col]).replace("$", "").replace(",", ""))
                    if price < min_price: continue
                except: pass
                
            # Only apply the Market Cap filter if the column actually exists in your CSV
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

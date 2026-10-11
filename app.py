import streamlit as st
import yfinance as yf
import pandas as pd
import math
import plotly.express as px
import os
import logging
import warnings
from datetime import datetime

logging.getLogger('yfinance').setLevel(logging.CRITICAL)
warnings.filterwarnings('ignore')

st.set_page_config(page_title="Bursa Robo-Advisor", layout="wide")
st.title("Bursa Robo-Advisor: Screener, Heatmap & Monitor")

@st.cache_data
def load_tickers():
    file_path = "shariah_list.csv"
    if os.path.exists(file_path):
        df = pd.read_csv(file_path)
        tickers = df['Ticker'].astype(str).str.strip().tolist()
        return [t for t in tickers if not t.startswith("030")]
    return []

SHARIAH_TICKERS = load_tickers()

def calculate_vpa_indicators(df):
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    df['SMA_200'] = df['Close'].rolling(window=200).mean()
    df['Vol_MA_20'] = df['Volume'].rolling(window=20).mean()
    df['Spread'] = df['High'] - df['Low']
    df['Avg_Spread'] = df['Spread'].rolling(window=20).mean()
    df['Close_Pos'] = (df['Close'] - df['Low']) / (df['Spread'] + 1e-6)
    
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, 0.00001)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    hl = df['High'] - df['Low']
    hc = (df['High'] - df['Close'].shift()).abs()
    lc = (df['Low'] - df['Close'].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(window=14).mean()
    return df

# Notice we removed vol_surge_mult from the inputs. This function now only fetches raw data!
@st.cache_data(ttl=14400, show_spinner=False)
def run_fast_market_scan(tickers):
    if not tickers:
        return [], [], datetime.now().strftime("%Y-%m-%d %H:%M")
        
    batch_data = yf.download(tickers, period="1y", group_by='ticker', threads=True, progress=False)
    
    candidates = []
    for ticker in tickers:
        try:
            if ticker in batch_data.columns.levels[0]:
                df = batch_data[ticker].dropna()
                if len(df) < 200:
                    continue
                
                df = calculate_vpa_indicators(df)
                latest = df.iloc[-1]
                
                if latest['Close'] < latest['SMA_200'] or latest['SMA_50'] < latest['SMA_200']:
                    continue
                    
                recent_5_days = df.iloc[-6:-1]
                
                # Calculate the MAXIMUM volume surge ratio over the last 5 days
                max_surge_ratio = 0
                for _, d in recent_5_days.iterrows():
                    if d['Spread'] > d['Avg_Spread'] * 1.2 and d['Close'] > d['Open'] and d['Vol_MA_20'] > 0:
                        ratio = d['Volume'] / d['Vol_MA_20']
                        if ratio > max_surge_ratio:
                            max_surge_ratio = ratio
                
                if max_surge_ratio > 0 and (latest['Volume'] < latest['Vol_MA_20']) and (latest['Close_Pos'] > 0.5):
                    candidates.append((ticker, latest, max_surge_ratio))
        except Exception:
            continue

    trade_setups = []
    heatmap_data = []
    
    for ticker, latest, max_surge_ratio in candidates:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info or {}
            
            company_name = info.get('longName', info.get('shortName', ticker))
            display_name = f"{ticker} ({company_name})"
            sector = info.get('sector', 'ETF / Unknown')
            mcap = info.get('marketCap', 1000000)
            pe = info.get('trailingPE', 0)
            roe = info.get('returnOnEquity', 0)
            
            heatmap_data.append({"Company": display_name, "Sector": sector, "Market Cap": mcap})
            
            fa_notes = []
            if pe > 0 and pe < 25:
                fa_notes.append(f"Fair P/E ({pe:.1f})")
            if roe and roe > 0.10:
                fa_notes.append(f"High ROE ({roe*100:.1f}%)")
            fa_verdict = " + ".join(fa_notes) if fa_notes else "General Setup"
            
            entry = float(latest['Close'])
            bursa_code = ticker.replace('.KL', '')
            
            trade_setups.append({
                "Company": display_name,
                "bursa_code": bursa_code,
                "Sector": sector,
                "entry": entry,
                "atr": float(latest['ATR']),
                "fa_notes": fa_notes,
                "fa_verdict": fa_verdict,
                "max_surge_ratio": max_surge_ratio # We save this in memory!
            })
        except Exception:
            continue

    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return trade_setups, heatmap_data, scan_time

tab1, tab2 = st.tabs(["🔍 1. Weekend Screener & Heatmap", "📈 2. Daily Portfolio Monitor"])

with tab1:
    st.write(f"Tracking **{len(SHARIAH_TICKERS)}** Shariah-compliant Main & ACE market assets.")
    
    st.sidebar.header("Rakuten Sizing")
    capital = st.sidebar.number_input("Capital per Trade (RM)", min_value=100, value=2000, step=100)
    
    st.sidebar.header("Robo-Advisor Parameters")
    strict_fa = st.sidebar.checkbox("Strict Mode: Require Good Fundamentals", value=True)
    vol_surge_multiplier = st.sidebar.slider("Volume Surge (Jump)", 1.5, 3.0, 2.0)
    risk_reward = st.sidebar.selectbox("Risk-to-Reward Ratio", ["1:2", "1:3"])

    col_btn, col_info = st.columns([1, 4])
    with col_btn:
        scan_button = st.button("⚡ Scan Market")
    
    if scan_button:
        with st.spinner("Running high-speed multi-threaded scan across Bursa..."):
            raw_setups, heatmap, last_run = run_fast_market_scan(SHARIAH_TICKERS)
            st.session_state['cached_setups'] = raw_setups
            st.session_state['cached_heatmap'] = heatmap
            st.session_state['last_run'] = last_run
            st.session_state['has_scanned'] = True

    if st.session_state.get('has_scanned', False):
        st.caption(f"🕒 Last scan completed: **{st.session_state.get('last_run', '')}** (Results cached for instant access)")
        
        filtered_setups = []
        multiplier = 2.0 if risk_reward == "1:2" else 3.0
        
        for item in st.session_state.get('cached_setups', []):
            # INSTANT FILTERING: Apply the slider rules on the fly!
            if item['max_surge_ratio'] < vol_surge_multiplier:
                continue
            if strict_fa and not item['fa_notes']:
                continue
                
            entry = item['entry']
            cost_per_lot = entry * 100
            lots = math.floor(capital / cost_per_lot) if cost_per_lot > 0 else 0
            stop_loss = max(0.01, entry - (1.5 * item['atr']))
            take_profit = entry + (multiplier * (entry - stop_loss))
            
            filtered_setups.append({
                "Company": item['Company'],
                "Chart": f"https://www.tradingview.com/chart/?symbol=MYX%3A{item['bursa_code']}",
                "News": f"https://www.bursamalaysia.com/trade/trading_resources/listing_directory/company-profile?stock_code={item['bursa_code']}",
                "Sector": item['Sector'],
                "Surge Jump": f"{item['max_surge_ratio']:.1f}x",
                "Entry (RM)": f"{entry:.3f}",
                "Lots to Buy": lots,
                "Stop Loss (RM)": f"{stop_loss:.3f}",
                "Take Profit (RM)": f"{take_profit:.3f}",
                "Robo's 'Why'": f"Wyckoff + {item['fa_verdict']}"
            })

        if st.session_state.get('cached_heatmap'):
            st.subheader("📊 Watchlist Sector Heatmap")
            df_heat = pd.DataFrame(st.session_state['cached_heatmap'])
            fig = px.treemap(df_heat, path=[px.Constant("Bursa Watchlist"), 'Sector', 'Company'], 
                             values='Market Cap', color='Sector')
            st.plotly_chart(fig, width="stretch")
            
        if filtered_setups:
            st.success(f"Found {len(filtered_setups)} High-Quality setup(s)!")
            st.dataframe(
                pd.DataFrame(filtered_setups),
                column_config={
                    "Chart": st.column_config.LinkColumn("TradingView", display_text="📈 Open Chart"),
                    "News": st.column_config.LinkColumn("Bursa Data", display_text="📰 Read News")
                },
                width="stretch",
                hide_index=True 
            )
        else:
            st.warning("No stocks passed your strict criteria today. Capital protected!")

with tab2:
    st.header("Daily Portfolio Monitor")
    st.write("Track the live status of trades executed on Rakuten.")
    
    col1, col2 = st.columns(2)
    with col1:
        my_ticker = st.text_input("Enter Ticker (e.g., 5183.KL)", "5183.KL")
    with col2:
        my_buy_price = st.number_input("Your Entry Price (RM)", min_value=0.01, value=1.50, step=0.05)
        
    if st.button("Check Live Status"):
        try:
            stock = yf.Ticker(my_ticker)
            info = stock.info or {}
            company_name = info.get('longName', my_ticker)
            bursa_code = my_ticker.replace('.KL', '')
            
            df = stock.history(period="6mo")
            if not df.empty:
                df = calculate_vpa_indicators(df)
                latest = df.iloc[-1]
                
                current_price = latest['Close']
                pnl = ((current_price - my_buy_price) / my_buy_price) * 100
                rsi = latest['RSI']
                
                if rsi > 70:
                    status = "🔴 OVERBOUGHT: Smart money distribution. Consider profit taking."
                elif latest['Close'] < latest['SMA_50']:
                    status = "⚠️ WARNING: Broken below 50-day moving average."
                elif pnl < -5.0:
                    status = "🛑 STOP LOSS: Down over 5%. Cut losses."
                else:
                    status = "🟢 UPTREND INTACT: Safe to hold."
                
                st.subheader(f"{company_name} ({my_ticker})")
                st.metric("Live Price", f"RM {current_price:.3f}", f"{pnl:.2f}%")
                st.info(status)
                st.markdown(f"**Quick Links:** [📈 TradingView Chart](https://www.tradingview.com/chart/?symbol=MYX%3A{bursa_code}) | [📰 Bursa News](https://www.bursamalaysia.com/trade/trading_resources/listing_directory/company-profile?stock_code={bursa_code})")
        except Exception:
            st.error("Error fetching live data.")


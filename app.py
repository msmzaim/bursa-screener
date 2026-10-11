import streamlit as st
import yfinance as yf
import pandas as pd
import math
import plotly.express as px
import os
import logging
import warnings

# Mute noisy yfinance terminal warnings
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
warnings.filterwarnings('ignore')

st.set_page_config(page_title="Bursa Robo-Advisor", layout="wide")
st.title("Bursa Robo-Advisor: Screener, Heatmap & Monitor")

# Initialize session state so switching tabs never wipes scan results
if 'scan_completed' not in st.session_state:
    st.session_state['scan_completed'] = False
    st.session_state['trade_setups'] = []
    st.session_state['heatmap_data'] = []

@st.cache_data
def load_tickers():
    file_path = "shariah_list.csv"
    if os.path.exists(file_path):
        df = pd.read_csv(file_path)
        tickers = df['Ticker'].astype(str).str.strip().tolist()
        return tickers
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

tab1, tab2 = st.tabs(["🔍 1. Weekend Screener & Heatmap", "📈 2. Daily Portfolio Monitor"])

# ==========================================
# TAB 1: SCREENER & HEATMAP
# ==========================================
with tab1:
    st.write(f"Currently tracking **{len(SHARIAH_TICKERS)}** Shariah-compliant assets.")
    
    st.sidebar.header("Rakuten Sizing")
    capital = st.sidebar.number_input("Capital per Trade (RM)", min_value=100, value=2000, step=100)
    
    st.sidebar.header("Robo-Advisor Parameters")
    strict_fa = st.sidebar.checkbox("Strict Mode: Require Good Fundamentals", value=True)
    vol_surge_multiplier = st.sidebar.slider("Volume Surge (Jump)", 1.5, 3.0, 2.0)
    risk_reward = st.sidebar.selectbox("Risk-to-Reward Ratio", ["1:2", "1:3"])

    if st.button("Scan Market Now"):
        if not SHARIAH_TICKERS:
            st.warning("No tickers found. Please check shariah_list.csv.")
        else:
            my_bar = st.progress(0, text="Scanning the market...")
            
            local_setups = []
            local_heatmap = []
            total_tickers = len(SHARIAH_TICKERS)
            
            for i, ticker in enumerate(SHARIAH_TICKERS):
                my_bar.progress(int(((i + 1) / total_tickers) * 100), text=f"Scanning {ticker}... ({i+1}/{total_tickers})")
                
                # Instantly skip LEAP market stocks as Yahoo Finance doesn't track them
                if ticker.startswith("030"):
                    continue
                    
                try:
                    stock = yf.Ticker(ticker)
                    
                    # Check trading history first to bypass inactive/delisted tickers (prevents 404 errors)
                    df = stock.history(period="1y")
                    if df.empty or len(df) < 200:
                        continue
                    
                    info = stock.info
                    if not info or 'regularMarketPrice' not in info:
                        continue
                         
                    company_name = info.get('longName', info.get('shortName', 'Unknown Company'))
                    display_name = f"{ticker} ({company_name})"
                    
                    sector = info.get('sector', 'ETF / Unknown')
                    mcap = info.get('marketCap', 1000000)
                    pe = info.get('trailingPE', 0)
                    roe = info.get('returnOnEquity', 0)
                    
                    local_heatmap.append({"Company": display_name, "Sector": sector, "Market Cap": mcap})
                    
                    fa_notes = []
                    if pe > 0 and pe < 25:
                        fa_notes.append(f"Fair P/E ({pe:.1f})")
                    if roe and roe > 0.10:
                        fa_notes.append(f"High ROE ({roe*100:.1f}%)")
                    
                    if strict_fa and not fa_notes:
                        continue
                    fa_verdict = " + ".join(fa_notes) if fa_notes else "Weak Fundamentals"
                    
                    df = calculate_vpa_indicators(df)
                    latest = df.iloc[-1]
                    
                    if latest['Close'] < latest['SMA_200'] or latest['SMA_50'] < latest['SMA_200']:
                        continue 
                        
                    recent_5_days = df.iloc[-6:-1] 
                    jump_found = False
                    for index, day in recent_5_days.iterrows():
                        if (day['Volume'] > day['Vol_MA_20'] * vol_surge_multiplier and 
                            day['Spread'] > day['Avg_Spread'] * 1.2 and day['Close'] > day['Open']):
                            jump_found = True
                            break
                            
                    if not jump_found:
                        continue
                        
                    if latest['Volume'] < latest['Vol_MA_20'] and latest['Close_Pos'] > 0.5:
                        entry = latest['Close']
                        cost_per_lot = entry * 100
                        lots_to_buy = math.floor(capital / cost_per_lot) if cost_per_lot > 0 else 0
                        
                        stop_loss = max(0.01, entry - (1.5 * latest['ATR']))
                        multiplier = 2.0 if risk_reward == "1:2" else 3.0
                        take_profit = entry + (multiplier * (entry - stop_loss))
                        
                        bursa_code = ticker.replace('.KL', '')
                        tv_url = f"https://www.tradingview.com/chart/?symbol=MYX%3A{bursa_code}"
                        bursa_url = f"https://www.bursamalaysia.com/trade/trading_resources/listing_directory/company-profile?stock_code={bursa_code}"
                        
                        local_setups.append({
                            "Company": display_name,
                            "Chart": tv_url,
                            "News": bursa_url,
                            "Sector": sector,
                            "Entry (RM)": f"{entry:.3f}",
                            "Lots to Buy": lots_to_buy,
                            "Stop Loss (RM)": f"{stop_loss:.3f}",
                            "Take Profit (RM)": f"{take_profit:.3f}",
                            "Robo's 'Why'": f"Wyckoff + {fa_verdict}"
                        })
                except Exception:
                    continue
            
            my_bar.empty()
            
            st.session_state['trade_setups'] = local_setups
            st.session_state['heatmap_data'] = local_heatmap
            st.session_state['scan_completed'] = True

    # Render results from memory
    if st.session_state['scan_completed']:
        if st.session_state['heatmap_data']:
            st.subheader("📊 Watchlist Sector Heatmap")
            df_heat = pd.DataFrame(st.session_state['heatmap_data'])
            fig = px.treemap(df_heat, path=[px.Constant("Bursa Watchlist"), 'Sector', 'Company'], 
                             values='Market Cap', color='Sector')
            
            # FIXED STREAMLIT WARNING HERE
            st.plotly_chart(fig, width="stretch")
            
        if st.session_state['trade_setups']:
            st.success(f"Found {len(st.session_state['trade_setups'])} High-Quality trade setup(s)!")
            st.dataframe(
                pd.DataFrame(st.session_state['trade_setups']),
                column_config={
                    "Chart": st.column_config.LinkColumn("TradingView", display_text="📈 Open Chart"),
                    "News": st.column_config.LinkColumn("Bursa Data", display_text="📰 Read News")
                },
                # FIXED STREAMLIT WARNING HERE
                width="stretch",
                hide_index=True 
            )
        else:
            st.warning("No stocks passed your strict criteria today. The robot protected your capital!")

# ==========================================
# TAB 2: PORTFOLIO MONITOR
# ==========================================
with tab2:
    st.header("Daily Portfolio Monitor")
    st.write("Track the live status of trades you executed on Rakuten.")
    
    col1, col2 = st.columns(2)
    with col1:
        my_ticker = st.text_input("Enter Ticker (e.g., 5183.KL)", "5183.KL")
    with col2:
        my_buy_price = st.number_input("Your Entry Price (RM)", min_value=0.01, value=1.50, step=0.05)
        
    if st.button("Check Live Status"):
        try:
            stock = yf.Ticker(my_ticker)
            info = stock.info
            company_name = info.get('longName', my_ticker)
            bursa_code_monitor = my_ticker.replace('.KL', '')
            
            df = stock.history(period="6mo")
            if not df.empty:
                df = calculate_vpa_indicators(df)
                latest = df.iloc[-1]
                
                current_price = latest['Close']
                pnl = ((current_price - my_buy_price) / my_buy_price) * 100
                rsi = latest['RSI']
                
                if rsi > 70:
                    status = "🔴 OVERBOUGHT: Smart money is selling. Consider taking profit."
                elif latest['Close'] < latest['SMA_50']:
                    status = "⚠️ WARNING: Broken below 50-day moving average."
                elif pnl < -5.0:
                    status = "🛑 STOP LOSS: You are down over 5%. Cut your losses."
                else:
                    status = "🟢 UPTREND INTACT: Safe to hold."
                
                st.subheader(f"{company_name} ({my_ticker})")
                st.metric("Live Price", f"RM {current_price:.3f}", f"{pnl:.2f}%")
                st.info(status)
                
                st.markdown(f"**Quick Links:** [📈 TradingView Chart](https://www.tradingview.com/chart/?symbol=MYX%3A{bursa_code_monitor}) | [📰 Bursa News](https://www.bursamalaysia.com/trade/trading_resources/listing_directory/company-profile?stock_code={bursa_code_monitor})")
                
        except Exception:
            st.error("Error fetching live data.")


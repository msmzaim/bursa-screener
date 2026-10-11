import streamlit as st
import yfinance as yf
import pandas as pd
import math
import os
import re
import logging
import warnings
import requests
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import quote
from datetime import datetime
from zoneinfo import ZoneInfo

logging.getLogger('yfinance').setLevel(logging.CRITICAL)
warnings.filterwarnings('ignore')

st.set_page_config(page_title="Bursa Robo-Advisor", layout="wide")
st.title("Bursa Robo-Advisor: Screener & Portfolio Monitor")

if 'has_scanned' not in st.session_state:
    st.session_state['has_scanned'] = False
if 'cached_setups' not in st.session_state:
    st.session_state['cached_setups'] = []
if 'my_portfolio' not in st.session_state:
    st.session_state['my_portfolio'] = []
if 'selected_stock' not in st.session_state:
    st.session_state['selected_stock'] = None

@st.cache_data
def load_tickers_and_names():
    file_path = "shariah_list.csv"
    stock_dict = {}
    if os.path.exists(file_path):
        df = pd.read_csv(file_path)
        
        name_col = None
        for col in df.columns:
            if any(k in col.lower() for k in ['name', 'nama', 'company', 'syarikat', 'stock', 'saham', 'counter']):
                name_col = col
                break
                
        ticker_col = None
        for col in df.columns:
            if any(k in col.lower() for k in ['ticker', 'code', 'symbol']):
                ticker_col = col
                break
        if not ticker_col:
            ticker_col = df.columns[0]
            
        for _, row in df.iterrows():
            t = str(row[ticker_col]).strip()
            if not t or t == 'nan':
                continue
            if t.isdigit() and len(t) < 4:
                t = t.zfill(4)
                
            if not t.endswith('.KL'):
                yf_ticker = f"{t}.KL"
            else:
                yf_ticker = t
                t = t.replace('.KL', '')
                
            if yf_ticker.startswith("030"): 
                continue 
                
            if name_col and pd.notna(row[name_col]):
                name = str(row[name_col]).strip()
                display = f"{t} - {name}"
            else:
                display = f"{t}"
            
            stock_dict[display] = yf_ticker
            
    return stock_dict

STOCK_DICT = load_tickers_and_names()
SHARIAH_TICKERS = list(STOCK_DICT.values())

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

@st.cache_data(ttl=14400, show_spinner=False)
def run_fast_market_scan(tickers):
    myt_zone = ZoneInfo("Asia/Kuala_Lumpur")
    if not tickers:
        return [], datetime.now(myt_zone).strftime("%Y-%m-%d %I:%M:%S %p (MYT)")
        
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
    for ticker, latest, max_surge_ratio in candidates:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info or {}
            
            company_name = info.get('longName', info.get('shortName', ticker))
            display_name = f"{ticker} ({company_name})"
            sector = info.get('sector', 'ETF / Unknown')
            pe = info.get('trailingPE', 0)
            roe = info.get('returnOnEquity', 0)
            
            fa_notes = []
            if pe > 0 and pe < 25:
                fa_notes.append(f"Fair P/E ({pe:.1f})")
            if roe and roe > 0.10:
                fa_notes.append(f"High ROE ({roe*100:.1f}%)")
            fa_verdict = " + ".join(fa_notes) if fa_notes else "General Setup"
            
            entry = float(latest['Close'])
            bursa_code = ticker.replace('.KL', '')
            
            trade_setups.append({
                "ticker": ticker,
                "Company": display_name,
                "bursa_code": bursa_code,
                "Sector": sector,
                "entry": entry,
                "atr": float(latest['ATR']),
                "fa_notes": fa_notes,
                "fa_verdict": fa_verdict,
                "max_surge_ratio": max_surge_ratio
            })
        except Exception:
            continue

    scan_time = datetime.now(myt_zone).strftime("%Y-%m-%d %I:%M:%S %p (MYT)")
    return trade_setups, scan_time

tab1, tab2, tab3 = st.tabs(["🔍 1. Market Screener", "🎯 2. Single Stock X-Ray", "📋 3. Active Portfolio"])

with tab1:
    st.write(f"Tracking **{len(SHARIAH_TICKERS)}** Shariah-compliant Main & ACE market assets.")
    
    st.sidebar.header("Rakuten Sizing")
    capital = st.sidebar.number_input("Capital per Trade (RM)", min_value=100, value=2000, step=100)
    
    st.sidebar.header("Robo-Advisor Parameters")
    strict_fa = st.sidebar.checkbox("Strict Mode: Require Good Fundamentals", value=True)
    vol_surge_multiplier = st.sidebar.slider("Volume Surge (Jump)", 1.5, 3.0, 2.0)
    
    st.sidebar.markdown("---")
    st.sidebar.header("Exit Strategy")
    atr_multiplier = st.sidebar.slider("Stop Loss (ATR Multiplier)", 1.0, 3.0, 1.5, step=0.1)
    risk_reward = st.sidebar.selectbox("Risk-to-Reward Ratio", ["1:1.5", "1:2", "1:3", "1:4", "1:5"], index=1)
    rr_multiplier = float(risk_reward.split(":")[1])

    col_btn, col_info = st.columns([1, 4])
    with col_btn:
        scan_button = st.button("⚡ Force Fresh Scan")
    
    if scan_button:
        run_fast_market_scan.clear()
        with st.spinner("Running high-speed multi-threaded scan across Bursa..."):
            raw_setups, last_run = run_fast_market_scan(SHARIAH_TICKERS)
            st.session_state['cached_setups'] = raw_setups
            st.session_state['last_run'] = last_run
            st.session_state['has_scanned'] = True

    if st.session_state.get('has_scanned', False):
        st.caption(f"🕒 Last scan completed: **{st.session_state.get('last_run', '')}**")
        
        filtered_setups = []
        raw_candidates_for_action = []
        
        for item in sorted(st.session_state.get('cached_setups', []), key=lambda x: x['max_surge_ratio'], reverse=True):
            if item['max_surge_ratio'] < vol_surge_multiplier:
                continue
            if strict_fa and not item['fa_notes']:
                continue
                
            entry = item['entry']
            cost_per_lot = entry * 100
            lots = math.floor(capital / cost_per_lot) if cost_per_lot > 0 else 0
            
            stop_loss = max(0.01, entry - (atr_multiplier * item['atr']))
            take_profit = entry + (rr_multiplier * (entry - stop_loss))
            
            raw_candidates_for_action.append({
                "ticker": item['ticker'],
                "bursa_code": item['bursa_code'],
                "Company": item['Company'],
                "entry": entry,
                "lots": lots,
                "stop_loss": stop_loss,
                "take_profit": take_profit
            })
            
            filtered_setups.append({
                "Company": item['Company'],
                "Sector": item['Sector'],
                "Surge Jump": f"{item['max_surge_ratio']:.1f}x",
                "Entry (RM)": f"{entry:.3f}",
                "Lots to Buy": lots,
                "Stop Loss (RM)": f"{stop_loss:.3f}",
                "Take Profit (RM)": f"{take_profit:.3f}",
                "Robo's 'Why'": f"Wyckoff + {item['fa_verdict']}"
            })

        if filtered_setups:
            st.success(f"Found {len(filtered_setups)} High-Quality setup(s)! **Click any row to instantly load it into Tab 2.**")
            
            df_display = pd.DataFrame(filtered_setups)
            selection_event = st.dataframe(
                df_display,
                on_select="rerun",
                selection_mode="single-row",
                use_container_width=True,
                hide_index=True 
            )
            
            if len(selection_event.selection.rows) > 0:
                selected_idx = selection_event.selection.rows[0]
                clicked_stock_ticker = raw_candidates_for_action[selected_idx]['ticker']
                st.session_state['selected_stock'] = clicked_stock_ticker
                st.success(f"✅ Loaded **{clicked_stock_ticker}**! Click **Tab 2** to view the Deep Dive and News.")
            
            st.markdown("### 📥 Plan to Buy? Send to Portfolio Monitor")
            c_select, c_add = st.columns([3, 1])
            with c_select:
                options = {s['Company']: s for s in raw_candidates_for_action}
                selected_choice = st.selectbox("Select a setup from above:", list(options.keys()))
            with c_add:
                st.write("")
                st.write("")
                if st.button("➕ Add to Portfolio (Tab 3)", use_container_width=True):
                    chosen = options[selected_choice]
                    existing_tickers = [p['ticker'] for p in st.session_state['my_portfolio']]
                    if chosen['ticker'] not in existing_tickers:
                        st.session_state['my_portfolio'].append(chosen)
                        st.success(f"Added {chosen['Company']} to Tab 3!")
                    else:
                        st.info(f"{chosen['ticker']} is already monitored in Tab 3.")
        else:
            st.warning("No stocks passed your strict criteria today. Capital protected!")


with tab2:
    st.header("🎯 Single Stock X-Ray & News")
    st.caption("Search for any Bursa stock by abbreviation, 4-digit code, or company name (e.g. PCHEM, Inari, 8893, Tenaga).")
    
    pre_filled_search = ""
    if st.session_state.get('selected_stock'):
        pre_filled_search = st.session_state['selected_stock']
    
    c_tick, c_run = st.columns([3, 1])
    with c_tick:
        web_query = st.text_input(
            "Search Bursa Stock:", 
            value=pre_filled_search,
            placeholder="Type code or name and press Enter..."
        )
        
    with c_run:
        st.write("")
        st.write("")
        run_deep = st.button("Deep Dive Analysis", use_container_width=True)

    if run_deep or web_query:
        if not web_query:
            st.warning("Please type a stock name or code first.")
            st.stop()
            
        deep_ticker = None
        display_name = None
        clean_query = web_query.strip()
        
        kl_match = re.search(r'(\d{4})\.KL', clean_query, re.IGNORECASE)
        digit_only_match = clean_query.isdigit() and len(clean_query) <= 4
        digit_start_match = re.match(r'^(\d{3,4})\b', clean_query)
        
        if kl_match:
            deep_ticker = f"{kl_match.group(1)}.KL"
        elif digit_only_match:
            deep_ticker = f"{clean_query.zfill(4)}.KL"
        elif digit_start_match:
            deep_ticker = f"{digit_start_match.group(1).zfill(4)}.KL"
        elif clean_query in STOCK_DICT:
            deep_ticker = STOCK_DICT[clean_query]
        else:
            clean_search_term = re.sub(r'\(.*?\)', '', clean_query).strip()
            with st.spinner(f"Web searching Yahoo Finance for '{clean_search_term}'..."):
                try:
                    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={clean_search_term}"
                    res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).json()
                    for q in res.get('quotes', []):
                        symbol = q.get('symbol', '')
                        if symbol.endswith('.KL'):
                            deep_ticker = symbol
                            display_name = f"{symbol.replace('.KL','')} - {q.get('shortname', symbol)}"
                            break
                except Exception:
                    pass
            
        if not deep_ticker:
            st.error(f"Could not find a Bursa stock matching '{web_query}' on Yahoo Finance. Try typing the 4-digit code directly.")
            st.stop()
            
        with st.spinner(f"Analyzing charts, volume, and news for {deep_ticker}..."):
            try:
                stock = yf.Ticker(deep_ticker)
                info = stock.info or {}
                bursa_code = deep_ticker.replace('.KL', '')
                
                if not display_name:
                    company_name = info.get('longName', info.get('shortName', deep_ticker))
                    display_name = f"{bursa_code} - {company_name}"
                
                df = stock.history(period="1y")
                if not df.empty:
                    df = calculate_vpa_indicators(df)
                    latest = df.iloc[-1]
                    
                    recent_5_days = df.iloc[-6:-1]
                    max_surge_ratio = 0
                    for _, d in recent_5_days.iterrows():
                        if d['Spread'] > d['Avg_Spread'] * 1.2 and d['Close'] > d['Open'] and d['Vol_MA_20'] > 0:
                            ratio = d['Volume'] / d['Vol_MA_20']
                            if ratio > max_surge_ratio:
                                max_surge_ratio = ratio
                                
                    pe = info.get('trailingPE', 0)
                    roe = info.get('returnOnEquity', 0)
                    
                    is_shariah = deep_ticker in SHARIAH_TICKERS
                    title_badge = "⭕ Shariah-Compliant" if is_shariah else "⚠️ Non-Shariah"
                    title_color = "green" if is_shariah else "red"
                    
                    st.markdown(f"### {display_name} :{title_color}[**[{title_badge}]**]")
                    st.metric("Live Price", f"RM {latest['Close']:.3f}")
                    
                    st.markdown(f"**Quick Links:** [📈 TradingView Chart](https://www.tradingview.com/chart/?symbol=MYX%3A{bursa_code}) | [📰 Bursa News](https://www.bursamalaysia.com/trade/trading_resources/listing_directory/company-profile?stock_code={bursa_code})")
                    
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.markdown("#### 📈 Trend (SMA)")
                        if latest['Close'] > latest['SMA_200'] and latest['SMA_50'] > latest['SMA_200']:
                            st.success("🟢 Strong Uptrend")
                        elif latest['Close'] > latest['SMA_200']:
                            st.warning("🟡 Weak Uptrend")
                        else:
                            st.error("🔴 Downtrend")
                            
                    with c2:
                        st.markdown("#### 🐋 Smart Money (VPA)")
                        if max_surge_ratio >= 2.0:
                            st.success(f"🟢 Buying ({max_surge_ratio:.1f}x Surge)")
                        elif max_surge_ratio > 1.2:
                            st.warning(f"🟡 Mild Surge ({max_surge_ratio:.1f}x)")
                        else:
                            st.error("🔴 Low Volume")
                            
                    with c3:
                        st.markdown("#### 🏢 Fundamentals")
                        fa_status = []
                        if pe > 0 and pe < 25: fa_status.append(f"Fair P/E")
                        if roe and roe > 0.10: fa_status.append(f"High ROE")
                        
                        if len(fa_status) == 2:
                            st.success("🟢 Good")
                        elif len(fa_status) == 1:
                            st.warning("🟡 Average")
                        else:
                            st.error(f"🔴 Weak FA")
                            
                    st.divider()
                    
                    st.markdown("### 🤖 Robo-Advisor Verdict")
                    rsi = latest['RSI']
                    
                    if rsi > 70:
                        st.info("⚠️ **OVERBOUGHT:** RSI is above 70. Smart money distribution likely. Avoid new entries.")
                    elif latest['Close'] < latest['SMA_200']:
                        st.info("🚫 **AVOID:** Stock is below 200-day moving average. Fails core trend safety check.")
                    elif max_surge_ratio >= 1.5 and latest['Volume'] < latest['Vol_MA_20'] and latest['Close_Pos'] > 0.5:
                        st.info("✅ **WYCKOFF SETUP DETECTED:** Recent volume surge followed by a quiet pullback. Valid entry zone.")
                    elif max_surge_ratio >= 1.5 and latest['Volume'] > latest['Vol_MA_20']:
                        st.info("⏳ **WAIT FOR PULLBACK:** Volume is still elevated. Wait for a low-volume resting day before entering.")
                    else:
                        st.info("⏳ **NEUTRAL / WAITING:** Stock is in an uptrend, but missing a clear institutional volume surge.")
                    
                    st.divider()
                    
                    # --- UPGRADED: GOOGLE NEWS RSS ENGINE ---
                    st.markdown("### 📰 Recent Headlines & News Feed")
                    try:
                        clean_comp_name = display_name.split('-')[-1].strip()
                        search_term = quote(f"{clean_comp_name} Bursa Malaysia")
                        rss_url = f"https://news.google.com/rss/search?q={search_term}&hl=en-MY&gl=MY&ceid=MY:en"
                        
                        req = urllib.request.Request(rss_url, headers={'User-Agent': 'Mozilla/5.0'})
                        with urllib.request.urlopen(req, timeout=5) as response:
                            xml_data = response.read()
                            
                        root = ET.fromstring(xml_data)
                        articles = root.findall('.//item')
                        
                        if articles:
                            for idx, item in enumerate(articles[:5]):
                                raw_title = item.find('title').text if item.find('title') is not None else 'No Title'
                                link = item.find('link').text if item.find('link') is not None else '#'
                                pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ''
                                source = item.find('source').text if item.find('source') is not None else 'Unknown Source'
                                
                                if " - " in raw_title:
                                    title = raw_title.rsplit(" - ", 1)[0]
                                else:
                                    title = raw_title
                                    
                                try:
                                    dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z")
                                    date_str = dt.strftime('%d %b %Y, %H:%M')
                                except:
                                    date_str = pub_date.replace(" GMT", "")

                                st.markdown(f"**{idx+1}. {title}**")
                                st.caption(f"🕒 {date_str} | 🔗 **Reference:** [{source}]({link})")
                                st.write("")
                        else:
                            st.info(f"No recent news found for {clean_comp_name} on Google News.")
                            
                    except Exception as e:
                        st.info("Could not retrieve local news feed at this time.")

                    st.divider()
                    
                    st.markdown("### 📥 Add to Portfolio Monitor (Tab 3)?")
                    add_col1, add_col2, add_col3, add_col4 = st.columns(4)
                    with add_col1:
                        manual_entry = st.number_input("Target Entry (RM)", value=float(latest['Close']), step=0.05, key="m_entry")
                    with add_col2:
                        manual_sl = st.number_input("Stop Loss (RM)", value=float(latest['Close'] * 0.9), step=0.05, key="m_sl")
                    with add_col3:
                        manual_tp = st.number_input("Take Profit (RM)", value=float(latest['Close'] * 1.2), step=0.05, key="m_tp")
                    with add_col4:
                        st.write("")
                        st.write("")
                        if st.button("➕ Add to Tab 3", key="m_add"):
                            manual_lots = math.floor(capital / (manual_entry * 100)) if manual_entry > 0 else 0
                            new_trade = {
                                "ticker": deep_ticker,
                                "bursa_code": bursa_code,
                                "Company": display_name,
                                "entry": manual_entry,
                                "lots": manual_lots,
                                "stop_loss": manual_sl,
                                "take_profit": manual_tp
                            }
                            existing_tickers = [p['ticker'] for p in st.session_state['my_portfolio']]
                            if deep_ticker not in existing_tickers:
                                st.session_state['my_portfolio'].append(new_trade)
                                st.success(f"Added {display_name} to Tab 3 Monitor!")
                            else:
                                st.info("Already monitored in Tab 3.")
            except Exception:
                st.error("Error analyzing ticker. Please try again.")


with tab3:
    st.header("📋 Active Monitored Portfolio")
    st.write("Track active positions added from the screener or manual search. Live P&L, stop-loss triggers, and take-profit targets update dynamically.")
    
    if not st.session_state['my_portfolio']:
        st.info("No active trades being monitored yet. Find stocks in Tab 1 or Tab 2 and add them to track here.")
    else:
        for idx, item in enumerate(st.session_state['my_portfolio']):
            ticker = item['ticker']
            entry = item['entry']
            sl = item['stop_loss']
            tp = item['take_profit']
            lots = item['lots']
            
            try:
                stock_data = yf.Ticker(ticker).history(period="1mo")
                current_price = stock_data['Close'].iloc[-1]
                pnl = ((current_price - entry) / entry) * 100
                
                if current_price <= sl:
                    status_badge = "🛑 STOP LOSS TRIGGERED: Cut loss immediately!"
                elif current_price >= tp:
                    status_badge = "🎯 TAKE PROFIT REACHED: Lock in gains!"
                else:
                    status_badge = "🟢 IN PLAY: Position progressing safely."
            except Exception:
                current_price = entry
                pnl = 0.0
                status_badge = "⚪ Data loading..."

            with st.container(border=True):
                m_col1, m_col2, m_col3, m_col4, m_col5 = st.columns([3, 2, 2, 2, 1])
                with m_col1:
                    st.markdown(f"**{item['Company']}**")
                    st.caption(f"Position: **{lots} board lots** | [📈 Chart](https://www.tradingview.com/chart/?symbol=MYX%3A{item['bursa_code']})")
                with m_col2:
                    st.metric("Live Price", f"RM {current_price:.3f}", f"{pnl:.2f}%")
                with m_col3:
                    st.markdown(f"**Entry:** RM {entry:.3f}")
                    st.markdown(f"**Stop Loss:** RM {sl:.3f}")
                with m_col4:
                    st.markdown(f"**Take Profit:** RM {tp:.3f}")
                    st.caption(status_badge)
                with m_col5:
                    st.write("")
                    if st.button("❌ Remove", key=f"del_{ticker}_{idx}"):
                        st.session_state['my_portfolio'].pop(idx)
                        st.rerun()


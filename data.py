"""Explicit Yahoo price policy and an offline demonstration dataset."""
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf


@st.cache_data(ttl=3600, show_spinner=False)
def history(ticker, demo=False):
    if demo:
        rng = np.random.default_rng(42 + int(ticker[:4]))
        dates = pd.bdate_range(end=pd.Timestamp.now(tz='Asia/Kuala_Lumpur').date(), periods=500)
        close = 2 * np.exp(np.cumsum(rng.normal(.001, .012, len(dates))))
        opening = close * (1 + rng.normal(0, .003, len(dates)))
        return pd.DataFrame({'Open': opening, 'High': np.maximum(opening, close) * 1.01,
                             'Low': np.minimum(opening, close) * .99, 'Close': close,
                             'Volume': rng.integers(200_000, 1_000_000, len(dates)),
                             'Stock Splits': 0}, index=dates)
    df = yf.Ticker(ticker).history(period='2y', interval='1d', auto_adjust=False,
                                   back_adjust=False, actions=True, raise_errors=True, timeout=15)
    if df is None or df.empty:
        raise ValueError(f'No history for {ticker}. Check code/provider availability.')
    return df


@st.cache_data(ttl=14400, show_spinner=False)
def company_info(ticker, demo=False):
    if demo:
        return {'longName': f'DEMO company {ticker}', 'sector': 'Industrials',
                'quoteType': 'EQUITY', 'trailingPE': 15, 'returnOnEquity': .13,
                'operatingCashflow': 40_000_000, 'debtToEquity': 45, 'revenueGrowth': .08}
    info = yf.Ticker(ticker).get_info()
    if not info:
        raise ValueError('Provider returned no fundamentals.')
    return info

"""Explicit Yahoo price policy and an offline demonstration dataset."""
import hashlib
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf


@st.cache_data(ttl=3600, show_spinner=False)
def history(ticker, demo=False, period="2y"):
    if demo:
        rng = np.random.default_rng(int(hashlib.sha256(ticker.encode()).hexdigest()[:8], 16))
        dates = pd.bdate_range(end=pd.Timestamp.now(tz='Asia/Kuala_Lumpur').date(), periods=1260 if period == "5y" else 500)
        close = 2 * np.exp(np.cumsum(rng.normal(.001, .012, len(dates))))
        opening = close * (1 + rng.normal(0, .003, len(dates)))
        return pd.DataFrame({'Open': opening, 'High': np.maximum(opening, close) * 1.01,
                             'Low': np.minimum(opening, close) * .99, 'Close': close,
                             'Volume': rng.integers(200_000, 1_000_000, len(dates)),
                             'Stock Splits': 0}, index=dates)
    df = yf.Ticker(ticker).history(period=period, interval='1d', auto_adjust=False,
                                   back_adjust=False, actions=True, raise_errors=True, timeout=15)
    if df is None or df.empty:
        raise ValueError(f'No history for {ticker}. Check code/provider availability.')
    return df


@st.cache_data(ttl=14400, show_spinner=False)
def company_info(ticker, demo=False):
    if demo:
        return {'longName': f'DEMO company {ticker}', 'sector': 'Industrials',
                'quoteType': 'EQUITY', 'industry': 'Demo manufacturing', 'currency': 'MYR', 'financialCurrency': 'MYR', 'trailingEps': .20, 'trailingPE': 15, 'returnOnEquity': .13,
                'operatingCashflow': 40_000_000, 'debtToEquity': 45, 'revenueGrowth': .08}
    info = yf.Ticker(ticker).get_info()
    if not info:
        raise ValueError('Provider returned no fundamentals.')
    return info


@st.cache_data(ttl=14400, show_spinner=False)
def financial_statements(ticker, demo=False):
    """Keep each statement's failure visible; never manufacture missing rows."""
    if demo:
        year = pd.Timestamp.now().year - 1
        columns = pd.to_datetime([f'{year-i}-12-31' for i in range(4)])
        return {
            'income': pd.DataFrame([[120,110,100,90],[15,13,11,9],[22,20,18,16],
                                    [27,25,23,21],[2,2,2,2]],
                                   index=['Total Revenue','Net Income','EBIT','EBITDA','Interest Expense'], columns=columns)*1e6,
            'cashflow': pd.DataFrame([[19,17,14,12],[-7,-6,-5,-5]],
                                     index=['Operating Cash Flow','Capital Expenditure'], columns=columns)*1e6,
            'balance': pd.DataFrame([[40,42,44,46],[20,18,16,14],[110,100,90,80]],
                                    index=['Total Debt','Cash And Cash Equivalents','Stockholders Equity'], columns=columns)*1e6,
            'errors': [], 'fetched_at': pd.Timestamp.now(tz='Asia/Kuala_Lumpur').isoformat()}
    stock = yf.Ticker(ticker)
    result = {'errors': [], 'fetched_at': pd.Timestamp.now(tz='Asia/Kuala_Lumpur').isoformat()}
    for label, method in [('income', stock.get_income_stmt), ('cashflow', stock.get_cash_flow), ('balance', stock.get_balance_sheet)]:
        try:
            result[label] = method(freq='yearly', pretty=True)
            if result[label] is None or result[label].empty:
                result[label] = pd.DataFrame()
                result['errors'].append(f'{label}: provider returned no annual statement')
        except Exception as exc:
            result[label] = pd.DataFrame()
            result['errors'].append(f'{label}: {exc}')
    return result

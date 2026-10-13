"""Pure research logic. No network, Streamlit, or claims of predictive accuracy."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import math
import re

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Rules:
    surge: float = 2.0
    min_turnover: float = 500_000.0
    min_price: float = 0.20
    max_rsi: float = 75.0
    atr_stop: float = 2.0
    reward_risk: float = 2.0


def ticker_code(value):
    value = str(value).strip().upper()
    value = re.sub(r'\.0$', '', value)
    value = value.removesuffix('.KL')
    if not re.fullmatch(r'\d{1,4}', value):
        raise ValueError(f'Expected a numeric Bursa ordinary-share code: {value!r}')
    return value.zfill(4) + '.KL'


def completed_bars(frame, now=None):
    """Conservatively omit ALL current-MYT-date bars, even after market close."""
    if frame is None or frame.empty:
        raise ValueError('No price history returned by provider.')
    df = frame.copy().sort_index()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert('Asia/Kuala_Lumpur').tz_localize(None)
    df.index = idx.normalize()
    df = df[~df.index.duplicated(keep='last')]
    now = pd.Timestamp.now(tz='Asia/Kuala_Lumpur') if now is None else pd.Timestamp(now)
    if now.tzinfo is None:
        now = now.tz_localize('Asia/Kuala_Lumpur')
    cutoff = now.tz_convert('Asia/Kuala_Lumpur').tz_localize(None).normalize()
    df = df.loc[df.index < cutoff].copy()
    required = ['Open', 'High', 'Low', 'Close', 'Volume']
    if not set(required).issubset(df.columns):
        raise ValueError('Provider response is missing OHLCV columns.')
    df[required] = df[required].apply(pd.to_numeric, errors='coerce')
    if df.empty or not np.isfinite(df[required].to_numpy()).all():
        raise ValueError('Missing or non-finite completed-session price data.')
    bad = ((df[['Open', 'High', 'Low', 'Close']] <= 0).any(axis=1)
           | (df.Volume < 0) | (df.High < df[['Open', 'Close', 'Low']].max(axis=1))
           | (df.Low > df[['Open', 'Close', 'High']].min(axis=1)))
    if bad.any():
        raise ValueError('Invalid price/volume rows; review provider data.')
    return df


def wilder(series, period=14):
    """Wilder smoothing seeded by the first period's arithmetic mean."""
    out = pd.Series(np.nan, index=series.index, dtype=float)
    valid = series.dropna()
    if len(valid) < period:
        return out
    seed_index = valid.index[period - 1]
    out.loc[seed_index] = valid.iloc[:period].mean()
    previous = out.loc[seed_index]
    for idx, value in valid.iloc[period:].items():
        previous = (previous * (period - 1) + value) / period
        out.loc[idx] = previous
    return out


def indicators(frame):
    df = frame.copy()
    df['SMA50'] = df.Close.rolling(50).mean()
    df['SMA200'] = df.Close.rolling(200).mean()
    df['VolumeBase'] = df.Volume.shift(1).rolling(20).mean()
    df['Turnover20'] = (df.Close * df.Volume).shift(1).rolling(20).mean()
    df['Spread'] = df.High - df.Low
    df['SpreadBase'] = df.Spread.shift(1).rolling(20).mean()
    df['ClosePosition'] = ((df.Close - df.Low) / df.Spread.replace(0, np.nan)).fillna(0.5)
    df['VolumeRatio'] = df.Volume / df.VolumeBase.replace(0, np.nan)
    change = df.Close.diff()
    gain = wilder(change.clip(lower=0))
    loss = wilder(-change.clip(upper=0))
    df['RSI'] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    df.loc[(loss == 0) & (gain > 0), 'RSI'] = 100
    df.loc[(gain == 0) & (loss > 0), 'RSI'] = 0
    df.loc[(gain == 0) & (loss == 0), 'RSI'] = 50
    tr = pd.concat([df.Spread, (df.High-df.Close.shift()).abs(),
                    (df.Low-df.Close.shift()).abs()], axis=1).max(axis=1)
    df['ATR'] = wilder(tr)
    df['PriorHigh20'] = df.High.shift(1).rolling(20).max()
    return df


def technical(frame, rules=Rules(), now=None):
    df = indicators(completed_bars(frame, now))
    if len(df) < 220:
        raise ValueError('Need at least 220 completed sessions for trend and indicator warm-up.')
    latest = df.iloc[-1]
    current = pd.Timestamp.now(tz='Asia/Kuala_Lumpur') if now is None else pd.Timestamp(now)
    if current.tzinfo is None:
        current = current.tz_localize('Asia/Kuala_Lumpur')
    age = (current.tz_convert('Asia/Kuala_Lumpur').date() - df.index[-1].date()).days
    recent = df.iloc[-6:-1]
    impulses = recent[(recent.VolumeRatio >= rules.surge)
                      & (recent.Spread >= 1.2 * recent.SpreadBase)
                      & (recent.Close > recent.Open)
                      & (recent.ClosePosition >= 0.65)]
    impulse = impulses.iloc[-1] if not impulses.empty else None
    checks = {
        'Data no more than 7 calendar days old': age <= 7,
        'Price above configured minimum': latest.Close >= rules.min_price,
        'Prior 20-session traded value meets minimum': latest.Turnover20 >= rules.min_turnover,
        'Close > SMA50 > SMA200': latest.Close > latest.SMA50 > latest.SMA200,
        'SMA200 rising over 20 sessions': latest.SMA200 > df.SMA200.iloc[-21],
        'RSI within 40 and configured maximum': 40 <= latest.RSI <= rules.max_rsi,
        'Bullish volume expansion in prior 5 sessions': impulse is not None,
        'Latest close lower than previous close': latest.Close < df.Close.iloc[-2],
        'Latest volume below prior 20-session average': latest.Volume < latest.VolumeBase,
        'Latest range narrower than prior average': latest.Spread < latest.SpreadBase,
        'Latest close in upper half of range': latest.ClosePosition > 0.5,
        'Pullback holds impulse low': impulse is not None and latest.Low >= impulse.Low,
    }
    if 'Stock Splits' in df:
        checks['No recent split requiring data review'] = not (df['Stock Splits'].tail(200).fillna(0) != 0).any()
    breakout = impulse is not None and impulse.Close > impulse.PriorHigh20
    return {'candidate': all(checks.values()), 'checks': checks, 'frame': df,
            'as_of': str(df.index[-1].date()), 'close': float(latest.Close),
            'atr': float(latest.ATR), 'rsi': float(latest.RSI),
            'turnover': float(latest.Turnover20),
            'surge': float(impulse.VolumeRatio) if impulse is not None else 0.0,
            'context': 'Impulse closed above prior 20-session high' if breakout else 'No confirmed 20-session breakout',
            'label': 'Price/volume pullback candidate' if all(checks.values()) else 'Criteria not met'}


def number(info, key):
    try:
        value = float(info.get(key))
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def fundamentals(info):
    """Generic ordinary-company filter; unknown data never silently passes."""
    definitions = [
        ('Trailing P/E', 'trailingPE', lambda x: 0 < x <= 25, '0 < P/E ≤ 25'),
        ('Return on equity', 'returnOnEquity', lambda x: x >= .10, 'ROE ≥ 10%'),
        ('Operating cash flow', 'operatingCashflow', lambda x: x > 0, 'Positive'),
        ('Debt/equity (%)', 'debtToEquity', lambda x: 0 <= x <= 100, '0–100%'),
        ('Revenue growth', 'revenueGrowth', lambda x: x > 0, 'Positive'),
    ]
    rows = []
    for label, key, predicate, threshold in definitions:
        value = number(info, key)
        rows.append({'Metric': label, 'Value': value, 'Requirement': threshold,
                     'Result': 'Unknown' if value is None else ('Pass' if predicate(value) else 'Fail')})
    results = [r['Result'] for r in rows]
    status = 'Fail' if 'Fail' in results else ('Incomplete' if 'Unknown' in results else 'Pass')
    sector = str(info.get('sector', 'Unknown'))
    special = sector in {'Financial Services', 'Real Estate'} or info.get('quoteType') not in {None, 'EQUITY'}
    if special:
        status = 'Sector review required'
    return {'status': status, 'rows': rows, 'sector': sector,
            'name': info.get('longName') or info.get('shortName') or '',
            'period': info.get('mostRecentQuarter')}


def tick_round(price, up=False):
    """Ordinary RM-denominated equities only; ETFs/other instruments excluded."""
    if not math.isfinite(price) or price <= 0:
        raise ValueError('Price must be positive and finite.')
    p = Decimal(str(price))
    tick = Decimal('0.005' if p < 1 else '0.01' if p < 10 else '0.02' if p < 100 else '0.10')
    return float((p / tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * tick)


def size_plan(entry, stop, target, equity, risk_pct, allocation, fee_pct, minimum_fee, slip_pct):
    values = [entry, stop, target, equity, risk_pct, allocation, fee_pct, minimum_fee, slip_pct]
    if not all(math.isfinite(x) for x in values):
        raise ValueError('All sizing inputs must be finite.')
    if not (0 < stop < entry < target and equity > 0 and 0 < risk_pct <= 100
            and allocation > 0 and fee_pct >= 0 and minimum_fee >= 0 and 0 <= slip_pct < 100):
        raise ValueError('Require 0 < stop < entry < target and valid positive budgets.')
    budget = equity * risk_pct / 100
    available = min(allocation, equity)
    buy = entry * (1 + slip_pct / 100)
    sell_stop = stop * (1 - slip_pct / 100)
    sell_target = target * (1 - slip_pct / 100)
    def fee(notional):
        return max(minimum_fee, notional * fee_pct / 100) if notional > 0 else 0
    def amounts(lots):
        shares = lots * 100
        cost = shares * buy + fee(shares * buy)
        loss = cost - (shares * sell_stop - fee(shares * sell_stop))
        profit = shares * sell_target - fee(shares * sell_target) - cost
        return cost, loss, profit
    # Binary search ensures both cash and estimated stop-loss budgets are respected.
    lo, hi = 0, int(available // (buy * 100))
    while lo < hi:
        mid = (lo + hi + 1) // 2
        cost, loss, _ = amounts(mid)
        if cost <= available and loss <= budget:
            lo = mid
        else:
            hi = mid - 1
    cost, loss, profit = amounts(lo)
    return {'lots': lo, 'shares': lo * 100, 'estimated_cash': cost,
            'estimated_stop_loss': loss, 'estimated_target_profit': profit,
            'net_reward_risk': profit / loss if loss > 0 else 0, 'risk_budget': budget}


def validate_portfolio(data):
    if not isinstance(data, list) or len(data) > 200:
        raise ValueError('Portfolio must be a list of up to 200 positions.')
    cleaned = []
    for row in data:
        ticker = ticker_code(row['ticker'])
        entry, stop, target = (float(row[k]) for k in ('entry', 'stop', 'target'))
        raw_shares = float(row['shares'])
        if not all(math.isfinite(x) for x in [entry, stop, target, raw_shares]):
            raise ValueError('Non-finite portfolio value.')
        if not (0 < stop < entry < target and raw_shares.is_integer() and 0 < raw_shares <= 1e9):
            raise ValueError('Invalid shares or price ordering in portfolio.')
        if ticker in [r['ticker'] for r in cleaned]:
            raise ValueError('Duplicate ticker in portfolio.')
        cleaned.append({'ticker': ticker, 'entry': entry, 'stop': stop, 'target': target,
                        'shares': int(raw_shares)})
    return cleaned

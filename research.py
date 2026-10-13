"""Evidence-led research and portfolio constraints. No predictive confidence score."""
from dataclasses import dataclass, asdict
import math
import numpy as np
import pandas as pd
from engine import completed_bars, indicators, number, tick_round, size_plan


@dataclass(frozen=True)
class RiskPolicy:
    equity: float = 10000
    allocation: float = 2000
    risk_pct: float = .5
    fee_pct: float = .20
    minimum_fee: float = 9
    slip_pct: float = .10
    position_cap_pct: float = 20
    sector_cap_pct: float = 35
    heat_cap_pct: float = 3
    participation_pct: float = 1
    min_net_rr: float = 1.5


def iso_date(value):
    return str(pd.Timestamp(value).date())


def market_context(stock, benchmark, now=None):
    a, b = completed_bars(stock, now), completed_bars(benchmark, now)
    if len(b) < 220:
        raise ValueError('Benchmark needs 220 completed sessions.')
    if a.index[-1] != b.index[-1]:
        raise ValueError('Stock and benchmark latest sessions differ; relative strength is unavailable.')
    now = pd.Timestamp.now(tz='Asia/Kuala_Lumpur') if now is None else pd.Timestamp(now)
    if (now.date() - b.index[-1].date()).days > 7:
        raise ValueError('Benchmark is stale.')
    b = indicators(b)
    last = b.iloc[-1]
    regime = ('Supportive' if last.Close > last.SMA50 > last.SMA200 and last.SMA200 > b.SMA200.iloc[-21]
              else 'Defensive' if last.Close < last.SMA200 else 'Mixed')
    aligned = pd.concat([a.Close.rename('Stock'), b.Close.rename('KLCI')], axis=1, join='inner').dropna()
    if len(aligned) < 127:
        raise ValueError('Need 127 shared observations for relative strength.')
    returns = {}
    for days in (21, 63, 126):
        changes = (aligned.iloc[-1] / aligned.iloc[-days-1] - 1) * 100
        returns[str(days)] = {'stock_pct': float(changes.Stock), 'benchmark_pct': float(changes.KLCI),
                              'excess_pp': float(changes.Stock - changes.KLCI)}
    normalized = aligned.tail(127) / aligned.tail(127).iloc[0] * 100
    return {'regime': regime, 'as_of': iso_date(aligned.index[-1]), 'returns': returns,
            'normalized': normalized, 'benchmark': '^KLSE (KLCI, price index)'}


def statement_value(frame, aliases, date):
    if frame is None or frame.empty or date not in frame.columns:
        return None
    for alias in aliases:
        if alias in frame.index:
            value = frame.loc[alias, date]
            if isinstance(value, pd.Series):
                value = value.iloc[0]
            try:
                value = float(value)
                if math.isfinite(value):
                    return value
            except (ValueError, TypeError):
                pass
    return None


def statement_review(statements, info, now=None):
    now = pd.Timestamp.now() if now is None else pd.Timestamp(now)
    definitions = {
        'revenue': ('income', ['Total Revenue']), 'net_income': ('income', ['Net Income']),
        'ebit': ('income', ['EBIT', 'Operating Income']), 'ebitda': ('income', ['EBITDA']),
        'interest': ('income', ['Interest Expense', 'Interest Expense Non Operating']),
        'cfo': ('cashflow', ['Operating Cash Flow', 'Total Cash From Operating Activities']),
        'capex': ('cashflow', ['Capital Expenditure']),
        'debt': ('balance', ['Total Debt']),
        'cash': ('balance', ['Cash And Cash Equivalents']),
        'equity': ('balance', ['Stockholders Equity', 'Total Stockholder Equity']),
    }
    income = statements.get('income', pd.DataFrame())
    dates = sorted([d for d in income.columns if pd.Timestamp(d).date() <= now.date()], reverse=True)[:4]
    records = []
    for date in dates:
        row = {'period_end': iso_date(date)}
        for key, (kind, aliases) in definitions.items():
            row[key] = statement_value(statements.get(kind), aliases, date)
        def ratio(top, bottom, positive=True):
            return top / bottom if top is not None and bottom is not None and (bottom > 0 if positive else bottom != 0) else None
        row['fcf'] = row['cfo'] - abs(row['capex']) if row['cfo'] is not None and row['capex'] is not None else None
        row['cash_conversion'] = ratio(row['cfo'], row['net_income'])
        row['operating_margin'] = ratio(row['ebit'], row['revenue'])
        row['net_debt_ebitda'] = ratio(row['debt']-row['cash'] if row['debt'] is not None and row['cash'] is not None else None, row['ebitda'])
        row['interest_cover'] = ratio(row['ebit'], abs(row['interest']) if row['interest'] is not None else None)
        records.append(row)
    checks = []
    def add(label, value, condition):
        checks.append({'Check': label, 'Value': value, 'Result': 'Unknown' if value is None else 'Pass' if condition(value) else 'Review'})
    if records:
        latest = records[0]
        age = (now.date()-pd.Timestamp(latest['period_end']).date()).days
        add('Annual period end no older than 550 days', age, lambda x: x <= 550)
        add('Positive latest annual earnings', latest['net_income'], lambda x: x > 0)
        add('Cash conversion ≥ 0.8× earnings', latest['cash_conversion'], lambda x: x >= .8)
        add('Positive free cash flow', latest['fcf'], lambda x: x > 0)
        add('Net debt / EBITDA ≤ 3×', latest['net_debt_ebitda'], lambda x: x <= 3)
        add('Interest cover ≥ 3× (zero interest remains unassessed)', latest['interest_cover'], lambda x: x >= 3)
        consecutive = len(records) >= 3 and all(300 <= (pd.Timestamp(records[i]['period_end'])-pd.Timestamp(records[i+1]['period_end'])).days <= 430 for i in range(2))
        profits = [r['net_income'] for r in records[:3]]
        add('Three consecutive profitable annual periods', sum(v > 0 for v in profits) if consecutive and all(v is not None for v in profits) else None, lambda x: x == 3)
        yoy = None
        if len(records) >= 2 and 300 <= (pd.Timestamp(records[0]['period_end'])-pd.Timestamp(records[1]['period_end'])).days <= 430:
            before, after = records[1]['revenue'], latest['revenue']
            yoy = (after/before-1)*100 if before and before > 0 and after is not None else None
        add('Annual revenue growth positive (%)', yoy, lambda x: x > 0)
    sector_special = info.get('sector') in ('Financial Services', 'Real Estate')
    status = ('Sector-specific review required' if sector_special else
              'Unavailable' if not records else
              'Review flags' if any(c['Result']=='Review' for c in checks) else
              'Incomplete' if any(c['Result']=='Unknown' for c in checks) else 'Checks passed')
    return {'status': status, 'periods': records, 'checks': checks, 'errors': statements.get('errors', []),
            'currency': info.get('financialCurrency', 'Unknown'), 'fetched_at': statements.get('fetched_at', 'Unknown')}


def structure_plan(frame, rules):
    """Causal daily trigger, support invalidation, and resistance-aware target."""
    last = frame.iloc[-1]
    if not math.isfinite(float(last.ATR)) or last.ATR <= 0:
        raise ValueError('Positive ATR is required.')
    trigger = tick_round(float(last.High) + .000001, up=True)
    support = float(frame.Low.tail(10).min())
    stop = tick_round(max(.005, min(support - .25 * last.ATR, trigger - rules.atr_stop * last.ATR)))
    if stop >= trigger:
        raise ValueError('No valid structural stop below the trigger.')
    risk = trigger - stop
    desired = tick_round(trigger + rules.reward_risk*risk, up=True)
    # Confirm pivots using two bars on each side, all within the known historical prefix.
    highs = frame.High.tail(120)
    pivots = [float(highs.iloc[i]) for i in range(2, len(highs)-2)
              if highs.iloc[i] > highs.iloc[i-2:i].max() and highs.iloc[i] >= highs.iloc[i+1:i+3].max()
              and highs.iloc[i] > trigger]
    resistance = min(pivots) if pivots else None
    target = min(desired, tick_round(resistance)) if resistance is not None else desired
    if target <= trigger:
        raise ValueError('Resistance leaves no room above the trigger.')
    return {'entry': trigger, 'stop': stop, 'target': target, 'support': support,
            'resistance': resistance, 'projected_target': desired,
            'max_entry': tick_round(trigger + .25*float(last.ATR)),
            'valid_sessions': 3, 'max_hold_sessions': 20,
            'target_basis': 'Nearest confirmed swing resistance caps target' if resistance is not None and target < desired else 'Projected risk multiple; no probability implied',
            'invalidation': 'Price breaches the lower of 10-session support minus 0.25 ATR and the configured ATR stop.',
            'as_of': iso_date(frame.index[-1])}


def portfolio_review(positions, histories, sectors, candidate_frame, now=None, policy=RiskPolicy()):
    rows, missing = [], []
    exposures = {}
    risk = 0.0
    for pos in positions:
        ticker = pos['ticker']
        try:
            frame = completed_bars(histories[ticker], now)
            current = pd.Timestamp.now(tz='Asia/Kuala_Lumpur') if now is None else pd.Timestamp(now)
            if (current.date()-frame.index[-1].date()).days > 7:
                raise ValueError('stale price')
            if 'Stock Splits' in frame and (frame['Stock Splits'].tail(200).fillna(0) != 0).any():
                raise ValueError('reported split: reconcile shares and stops')
            price = float(frame.Close.iloc[-1]); value = price * pos['shares']
            sector = sectors.get(ticker, 'Unknown')
            if sector == 'Unknown':
                missing.append(ticker + ': sector unavailable')
            exit_value = pos['stop']*(1-policy.slip_pct/100)*pos['shares']
            exit_fee = max(policy.minimum_fee, exit_value*policy.fee_pct/100)
            to_stop = max(0, value-exit_value+exit_fee)
            risk += to_stop; exposures[sector] = exposures.get(sector, 0) + value
            pair = pd.concat([candidate_frame.Close.pct_change().rename('candidate'), frame.Close.pct_change().rename('holding')], axis=1, join='inner').dropna().tail(120)
            correlation = float(pair.corr().iloc[0,1]) if len(pair) >= 60 else None
            if correlation is not None and not math.isfinite(correlation):
                correlation = None
            rows.append({'ticker': ticker, 'sector': sector, 'value': value, 'risk_to_stop': to_stop,
                         'correlation': correlation, 'as_of': iso_date(frame.index[-1])})
        except Exception as exc:
            missing.append(f'{ticker}: {exc}')
    gross = sum(r['value'] for r in rows)
    return {'rows': rows, 'missing': missing, 'sector_values': exposures, 'gross_value': gross,
            'risk_to_stop': risk, 'cash_estimate': max(0, policy.equity-gross),
            'heat_pct': risk/policy.equity*100, 'complete': not missing}


def constrained_plan(levels, frame, portfolio, sector, ticker, policy=RiskPolicy()):
    reasons = []
    if not portfolio['complete']:
        reasons.append('Portfolio price/sector coverage incomplete')
    if sector == 'Unknown':
        reasons.append('Candidate sector unavailable')
    if any(r['ticker'] == ticker for r in portfolio['rows']):
        reasons.append('Already held: review the existing position before adding')
    cash = min(policy.allocation, portfolio['cash_estimate'], policy.equity*policy.position_cap_pct/100,
               max(0, policy.equity*policy.sector_cap_pct/100-portfolio['sector_values'].get(sector,0)),
               float(frame.VolumeBase.iloc[-1])*policy.participation_pct/100*levels['entry'])
    risk_room = max(0, policy.equity*policy.heat_cap_pct/100-portfolio['risk_to_stop'])
    risk_pct = min(policy.risk_pct, risk_room/policy.equity*100)
    sizing = {'lots':0,'shares':0,'estimated_cash':0,'estimated_stop_loss':0,'estimated_target_profit':0,'net_reward_risk':0,'risk_budget':risk_room}
    if cash <= 0 or risk_pct <= 0:
        reasons.append('No cash, sector, liquidity, or portfolio-risk capacity')
    elif not reasons:
        sizing = size_plan(levels['entry'], levels['stop'], levels['target'], policy.equity, risk_pct, cash, policy.fee_pct, policy.minimum_fee, policy.slip_pct)
        if sizing['lots'] == 0:
            reasons.append('No 100-share lot fits all limits')
        if sizing['net_reward_risk'] < policy.min_net_rr:
            reasons.append('Net reward/risk below configured minimum')
    return {**levels, **sizing, 'constraints_pass': not reasons, 'reasons': reasons,
            'policy': asdict(policy)}


def peer_review(info, peers):
    """Peer P/E comparisons require exact provider industry and positive earnings."""
    rows=[]
    for ticker, peer in peers.items():
        pe=number(peer,'trailingPE')
        comparable=bool(info.get('industry') and peer.get('industry') == info['industry'] and pe is not None and pe > 0 and peer.get('quoteType') == 'EQUITY')
        rows.append({'Ticker':ticker,'Company':peer.get('longName',ticker),'Industry':peer.get('industry','Unknown'),
                     'P/E':pe,'ROE':number(peer,'returnOnEquity'),'Debt/equity %':number(peer,'debtToEquity'),
                     'Included in P/E median':comparable})
    pes=[r['P/E'] for r in rows if r['Included in P/E median']]
    median=float(np.median(pes)) if len(pes)>=3 else None
    own=number(info,'trailingPE')
    premium=(own/median-1)*100 if own is not None and own>0 and median is not None else None
    return {'rows':rows,'count':len(pes),'median_pe':median,'premium_pct':premium}


def valuation_scenarios(info, close, assumptions):
    eps=number(info,'trailingEps')
    if eps is None or eps <= 0:
        raise ValueError('Positive trailing EPS is required for this sensitivity model.')
    if info.get('currency') != 'MYR' or info.get('financialCurrency') != 'MYR':
        raise ValueError('This model requires confirmed MYR quote and financial currencies.')
    if info.get('sector') in ('Financial Services','Real Estate'):
        raise ValueError('Use a sector-specific valuation model for this company.')
    rows=[]
    for label,growth,multiple in assumptions:
        if growth <= -100 or multiple <= 0:
            raise ValueError('EPS change must exceed -100% and P/E must be positive.')
        forward=eps*(1+growth/100);value=forward*multiple
        rows.append({'Scenario':label,'Assumed EPS change %':growth,'Assumed P/E':multiple,
                     'Illustrative EPS':forward,'Illustrative value RM':value,'vs close %':(value/close-1)*100})
    return rows

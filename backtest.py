"""Daily-bar technical research simulator; current fundamentals are never used."""
from dataclasses import asdict, replace
import math
import pandas as pd
from engine import completed_bars, indicators, technical_from_indicators, size_plan
from research import structure_plan, RiskPolicy


def exit_on_bar(bar, stop, target, slip_pct):
    """Stops first when daily OHLC cannot resolve the intraday order."""
    slip = slip_pct / 100
    if bar.Open <= stop:
        return float(bar.Open)*(1-slip), 'Gap through stop'
    if bar.Open >= target:
        return float(target)*(1-slip), 'Target at open (no gap improvement)'
    if bar.Low <= stop:
        return float(stop)*(1-slip), 'Stop first; both touched' if bar.High >= target else 'Stop'
    if bar.High >= target:
        return float(target)*(1-slip), 'Target'
    return None, None


def simulate(df, rules, policy, start, end, signal_fn=None, plan_fn=None):
    """Signals at close; pending buy-stop valid for next three bars. One position."""
    if not 219 <= start <= end < len(df):
        raise ValueError('Invalid research interval.')
    signal_fn = signal_fn or (lambda prefix: technical_from_indicators(prefix, rules, now=prefix.index[-1]+pd.Timedelta(days=1))['candidate'])
    plan_fn = plan_fn or (lambda prefix: structure_plan(prefix, rules))
    cash = policy.equity
    pending = active = None
    trades,curve = [],[]
    skipped = 0
    def fee(notional):
        return max(policy.minimum_fee, notional*policy.fee_pct/100) if notional>0 else 0
    for i in range(start,end+1):
        bar=df.iloc[i];date=df.index[i]
        # Entitlement only for positions carried into the ex-dividend date.
        if active is not None:
            dividend=float(bar.get('Dividends',0) or 0)
            if math.isfinite(dividend) and dividend>0:
                amount=dividend*active['shares'];cash+=amount;active['dividends']+=amount
        if active is None and pending is not None:
            age=i-pending['signal_index']
            if age>pending['valid_sessions'] or bar.Open<=pending['stop']:
                pending=None;skipped+=1
            elif bar.High>=pending['entry']:
                raw_entry=max(float(bar.Open),pending['entry'])
                if raw_entry>pending['max_entry'] or raw_entry>=pending['target'] or bar.Volume<=0:
                    pending=None;skipped+=1
                else:
                    # Capacity uses only data available at the preceding close.
                    allocation=min(policy.allocation,cash*policy.position_cap_pct/100,
                                   cash*policy.sector_cap_pct/100,
                                   float(df.VolumeBase.iloc[i-1])*policy.participation_pct/100*raw_entry)
                    sizing=size_plan(raw_entry,pending['stop'],pending['target'],cash,
                                     min(policy.risk_pct,policy.heat_cap_pct),max(.001,allocation),
                                     policy.fee_pct,policy.minimum_fee,policy.slip_pct)
                    if sizing['lots']>0 and sizing['net_reward_risk']>=policy.min_net_rr:
                        active={**pending,'entry_index':i,'entry_date':str(date.date()),
                                'fill':raw_entry*(1+policy.slip_pct/100),'shares':sizing['shares'],
                                'cost':sizing['estimated_cash'],'initial_risk':sizing['estimated_stop_loss'],'dividends':0.0}
                        cash-=active['cost']
                    else:
                        skipped+=1
                    pending=None
            elif bar.Low<=pending['stop']:
                pending=None;skipped+=1
        exited=False
        if active is not None:
            price,reason=exit_on_bar(bar,active['stop'],active['target'],policy.slip_pct)
            # On trigger bars, high/low sequence is unknowable: the stop takes precedence.
            if i==active['entry_index'] and bar.Low<=active['stop']:
                price=active['stop']*(1-policy.slip_pct/100);reason='Entry-day stop (conservative ordering)'
            if price is None and (i-active['entry_index']+1>=active['max_hold_sessions'] or i==end):
                price=float(bar.Close)*(1-policy.slip_pct/100)
                reason='Window-end liquidation' if i==end else 'Time exit'
            if price is not None:
                proceeds=price*active['shares']-fee(price*active['shares']);cash+=proceeds
                pnl=proceeds+active['dividends']-active['cost']
                trades.append({'signal_date':active['as_of'],'entry_date':active['entry_date'],
                               'exit_date':str(date.date()),'entry_fill':active['fill'],'exit_fill':price,
                               'shares':active['shares'],'net_pnl':pnl,'net_R':pnl/active['initial_risk'],
                               'dividends':active['dividends'],'exit_reason':reason})
                active=None;exited=True
        mark=cash+(active['shares']*float(bar.Close) if active else 0)
        curve.append({'date':date,'equity':mark,'invested':active is not None})
        if active is None and pending is None and not exited and i<end:
            prefix=df.iloc[:i+1]
            if signal_fn(prefix):
                try:
                    pending={**plan_fn(prefix),'signal_index':i}
                except ValueError:
                    skipped+=1
    curve=pd.DataFrame(curve).set_index('date')
    equity_path=pd.concat([pd.Series([policy.equity]),curve.equity.reset_index(drop=True)],ignore_index=True)
    drawdown=equity_path/equity_path.cummax()-1
    winners=sum(t['net_pnl']>0 for t in trades)
    gains=sum(max(t['net_pnl'],0) for t in trades);losses=-sum(min(t['net_pnl'],0) for t in trades)
    summary={'trades':len(trades),'net_return_pct':(cash/policy.equity-1)*100,
             'max_drawdown_pct':float(drawdown.min()*100),
             'win_rate_pct':winners/len(trades)*100 if trades else None,
             'expectancy_R':sum(t['net_R'] for t in trades)/len(trades) if trades else None,
             'profit_factor':gains/losses if losses>0 else None,
             'skipped_entries':skipped,'exposure_pct':float(curve.invested.mean()*100),
             'start':str(df.index[start].date()),'end':str(df.index[end].date()),
             'sample_note':'Fewer than 30 trades: insufficient sample for a confident assessment' if len(trades)<30 else 'Sample size alone does not establish robustness'}
    return {'summary':summary,'trades':trades,'curve':curve}


def research_backtest(frame, rules, policy=RiskPolicy(), now=None):
    df=indicators(completed_bars(frame,now))
    if len(df)<500:
        raise ValueError('Need at least 500 completed bars for warm-up and two research windows.')
    if 'Stock Splits' in df and (df['Stock Splits'].fillna(0)!=0).any():
        raise ValueError('Reported split in history: backtest blocked until corporate actions are reconciled.')
    first=219;split=first+int((len(df)-first)*.70)
    development=simulate(df,rules,policy,first,split-1)
    holdout=simulate(df,rules,policy,split,len(df)-1)
    stress=simulate(df,rules,replace(policy,fee_pct=policy.fee_pct*2,
                                    minimum_fee=policy.minimum_fee*2,slip_pct=policy.slip_pct*2),split,len(df)-1)
    return {'development':development,'holdout':holdout,'cost_stress':stress,
            'rules':asdict(rules),'policy':asdict(policy),'split_date':str(df.index[split].date())}


def benchmark_window(frame, start, end, now=None):
    df=completed_bars(frame,now)
    if pd.Timestamp(start) not in df.index or pd.Timestamp(end) not in df.index:
        return None
    return float((df.loc[pd.Timestamp(end),'Close']/df.loc[pd.Timestamp(start),'Close']-1)*100)

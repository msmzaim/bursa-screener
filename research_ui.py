"""Streamlit presentation for evidence, scenarios, and historical research."""
import json
from datetime import date
from pathlib import Path
import pandas as pd
import streamlit as st
from data import history, company_info, financial_statements
from engine import completed_bars, indicators, number
from research import (market_context, statement_review, structure_plan, constrained_plan,
                      portfolio_review, peer_review, valuation_scenarios)
from backtest import research_backtest, benchmark_window


def reference_sectors():
    df=pd.read_csv(Path(__file__).with_name('shariah_reference.csv'),dtype=str)
    return {r.ticker+'.KL':r.sector for r in df.itertuples()}


def build_report(r, rules, demo, positions, peers, policy):
    errors=[]
    def attempt(label,fn,default):
        try:
            return fn()
        except Exception as exc:
            errors.append(f'{label}: {exc}')
            return default
    benchmark=attempt('KLCI',lambda:history('^KLSE',demo),None)
    context=attempt('Market context',lambda:market_context(r['frame'],benchmark),None) if benchmark is not None else None
    statements=financial_statements(r['ticker'],demo)
    quality=statement_review(statements,r['info'])
    errors.extend(quality['errors'])
    peer_info={};peer_trends=[]
    for ticker in peers:
        info=attempt(ticker+' fundamentals',lambda t=ticker:company_info(t,demo),None)
        if info:
            peer_info[ticker]=info
        frame=attempt(ticker+' price history',lambda t=ticker:indicators(completed_bars(history(t,demo))),None)
        if frame is not None and len(frame)>=200 and str(frame.index[-1].date()) == r['as_of']:
            peer_trends.append({'Ticker':ticker,'Above SMA50':bool(frame.Close.iloc[-1]>frame.SMA50.iloc[-1]),
                                'Above SMA200':bool(frame.Close.iloc[-1]>frame.SMA200.iloc[-1])})
    holdings={}
    for pos in positions:
        data=attempt(pos['ticker']+' holding',lambda t=pos['ticker']:history(t,demo),None)
        if data is not None:
            holdings[pos['ticker']]=data
    return {'context':context,'quality':quality,'peers':peer_review(r['info'],peer_info),
            'peer_trends':peer_trends,'holdings':holdings,'errors':errors,
            'fetched_at':pd.Timestamp.now(tz='Asia/Kuala_Lumpur').isoformat(timespec='seconds')}


def research_panel(r,rules,policy,demo,positions,universe):
    st.subheader('Research report and conditional trade plan')
    sectors=reference_sectors();sector=sectors.get(r['ticker'],'Unknown')
    st.caption(f'SC sector: {sector}. Benchmarked against KLCI; it is a broad-market reference, not a Shariah index.')
    same_sector=[t for t in universe.ticker if t != r['ticker'] and sectors.get(t)==sector]
    peers=st.multiselect('Sector peers to inspect (up to 6)',same_sector,default=same_sector[:3],max_selections=6,key='peers_'+r['ticker'])
    signature=(r['ticker'],r['as_of'],demo,tuple(peers),json.dumps(positions,sort_keys=True))
    if st.button('Build research report',key='build_research'):
        with st.spinner('Checking statements, market context, peers, and holdings…'):
            st.session_state.research_report={'signature':signature,'data':build_report(r,rules,demo,positions,peers,policy)}
    stored=st.session_state.get('research_report')
    if not stored or stored['signature'] != signature:
        st.info('Build the report after selecting peers. Rebuild after changing the stock, portfolio, or peer selection.')
        return
    report=stored['data'];context=report['context'];quality=report['quality']
    st.caption('Report fetched: '+report['fetched_at'])
    if report['errors']:
        with st.expander('Missing data and provider issues',expanded=True):
            for message in report['errors']:
                st.write(message)
    with st.expander('Market and sector evidence',expanded=True):
        if context:
            st.write('**KLCI regime: '+context['regime']+'**')
            st.dataframe(pd.DataFrame([{'Sessions':k,**v} for k,v in context['returns'].items()]),hide_index=True)
            st.line_chart(context['normalized'])
            st.caption('Price-only returns on shared sessions. Excess is percentage points, not alpha. Index starts at 100.')
        else:
            st.warning('Market context unavailable. No positive market conclusion can be drawn.')
        st.dataframe(pd.DataFrame(report['peer_trends']),hide_index=True)
        st.caption(f'Sector sample: {len(report["peer_trends"])} of {len(peers)} selected peers with matching dates. This is not full-sector breadth.')
        p=report['peers']
        st.dataframe(pd.DataFrame(p['rows']),hide_index=True)
        if p['median_pe'] is not None:
            st.write(f'Exact-industry sample median P/E: {p["median_pe"]:.1f}× across {p["count"]} peers.')
            if p['premium_pct'] is not None:
                st.write(f'Stock P/E versus sample median: {p["premium_pct"]:+.1f}%.')
        else:
            st.info('Fewer than 3 positive-P/E peers in the same provider industry. No valuation median is asserted.')
        st.caption('Peer selection is manual and may be unrepresentative. Similar P/E does not imply similar growth, risk, or fair value.')
    with st.expander('Financial-statement quality',expanded=True):
        st.write('**'+quality['status']+'**')
        st.dataframe(pd.DataFrame(quality['checks']),hide_index=True)
        st.dataframe(pd.DataFrame(quality['periods']),hide_index=True)
        st.caption(f'Annual statements in {quality["currency"]}; amounts are full currency units and ratios are decimals. Ratios join matching period ends only. Annual trends can lag recent quarters. Source is Yahoo, not an audit of Bursa filings. Thresholds are research assumptions; missing and zero-interest coverage remain explicit.')
    with st.expander('Valuation sensitivity — editable assumptions'):
        st.caption('Illustrative EPS × P/E values, not price forecasts or probabilities. Trailing EPS can include non-recurring items.')
        base_pe=number(r['info'],'trailingPE') or 15.0
        base_pe=min(200.0,max(1.0,base_pe))
        assumptions=[]
        for label,growth,multiple in [('Bear',-10.0,base_pe*.8),('Base',0.0,base_pe),('Bull',10.0,base_pe*1.2)]:
            a,b=st.columns(2)
            g=a.number_input(label+' EPS change (%)',min_value=-99.0,max_value=200.0,value=growth,key=r['ticker']+label+'g')
            m=b.number_input(label+' P/E multiple',min_value=.1,max_value=300.0,value=float(multiple),key=r['ticker']+label+'m')
            assumptions.append((label,g,m))
        try:
            scenario_rows=valuation_scenarios(r['info'],r['close'],assumptions)
            st.dataframe(pd.DataFrame(scenario_rows),hide_index=True)
        except ValueError as exc:
            scenario_rows=[];st.info(str(exc))
    exposure=portfolio_review(positions,report['holdings'],sectors,r['frame'],policy=policy)
    st.write('**Portfolio capacity**')
    a,b,c=st.columns(3)
    a.metric('Marked holdings',f'RM {exposure["gross_value"]:,.0f}')
    b.metric('Estimated available cash',f'RM {exposure["cash_estimate"]:,.0f}')
    c.metric('Mark-to-stop risk / equity',f'{exposure["heat_pct"]:.2f}%')
    st.caption('Cash is user-entered total equity minus marked holdings, not broker-confirmed cash. Mark-to-stop risk includes estimated exit costs; correlated gaps can exceed it.')
    if exposure['rows']:
        st.dataframe(pd.DataFrame(exposure['rows']),hide_index=True)
    for issue in exposure['missing']:
        st.warning(issue)
    correlations=[v['correlation'] for v in exposure['rows'] if v['correlation'] is not None and v['correlation']>=.75]
    if correlations:
        st.warning('At least one holding has return correlation ≥ 0.75 with this stock over up to 120 shared sessions. Review combined exposure; correlations can change.')
    st.write('**Catalyst and event review**')
    thesis=st.text_area('Your business thesis and catalyst',key=r['ticker']+'thesis',placeholder='What could improve earnings or change valuation? What evidence supports it?')
    source=st.text_input('Source link for your thesis / announcement',key=r['ticker']+'source',placeholder='https://…')
    reviewed=st.checkbox('I checked upcoming results and material company announcements',key=r['ticker']+'events')
    event_known=st.checkbox('A material event is scheduled',key=r['ticker']+'known_event')
    event=st.date_input('Next material event date',value=date.today(),key=r['ticker']+'eventdate') if event_known else None
    st.caption('These are your research notes; the app does not independently verify the source or supply a complete event calendar.')
    try:
        levels=structure_plan(r['frame'],rules)
        p=constrained_plan(levels,r['frame'],exposure,sector,r['ticker'],policy)
    except ValueError as exc:
        st.error('Plan unavailable: '+str(exc));return
    blockers=list(p['reasons'])
    if not r['candidate']: blockers.append('Technical screening criteria not met')
    if r['fa']['status'] != 'Pass': blockers.append('Snapshot FA has not passed')
    if quality['status'] != 'Checks passed': blockers.append('Annual-statement review is incomplete or has flags')
    if not context or context['regime'] != 'Supportive': blockers.append('KLCI market backdrop is not confirmed supportive')
    if context and context['returns']['63']['excess_pp'] <= 0: blockers.append('Stock has not outperformed KLCI over 63 shared sessions')
    if not reviewed: blockers.append('Upcoming-event review not recorded')
    if not thesis.strip() or not source.startswith(('https://','http://')): blockers.append('A sourced business thesis has not been recorded')
    today=pd.Timestamp.now(tz='Asia/Kuala_Lumpur').date()
    if (today-pd.Timestamp(r['as_of']).date()).days > 7: blockers.append('Price snapshot is stale')
    if len(pd.bdate_range(pd.Timestamp(r['as_of'])+pd.Timedelta(days=1), today)) > 3:
        blockers.append('Trigger window expired by weekday count; reanalyse (exchange holidays are not modelled)')
    if event and 0 <= (event-today).days <= 7: blockers.append('Material event within 7 days: reassess before entry')
    if event and event < today: blockers.append('Recorded event date is in the past: refresh event review')
    verdict='Watchlist — unresolved checks' if blockers else 'Conditional plan — wait for the trigger and recheck execution conditions'
    st.write('**'+verdict+'**')
    for reason in blockers: st.write('- '+reason)
    st.dataframe(pd.DataFrame([{k:p[k] for k in ['entry','max_entry','stop','support','resistance','target','lots','estimated_cash','estimated_stop_loss','net_reward_risk']}]),hide_index=True)
    st.caption('Lots shown are a sizing calculation, not approval to trade. Any unresolved check keeps the setup on the watchlist.')
    st.write(f'**Trigger:** trade above RM {p["entry"]:.3f} within the next 3 sessions after {p["as_of"]}. Do not chase above RM {p["max_entry"]:.3f}. Cancel if invalidated before entry; reanalyse after expiry.')
    st.write(f'**Invalidation:** RM {p["stop"]:.3f}. {p["invalidation"]}')
    st.write(f'**Target:** RM {p["target"]:.3f}. {p["target_basis"]}. Review or exit after 20 sessions if neither level is reached.')
    st.write('**Adverse scenario:** a gap through the stop can exceed planned loss. **No-trigger scenario:** stay uninvested and reassess. **Favourable scenario:** reassess at the target; the app assumes no guaranteed fill.')
    report_text='\n'.join([
        '# Bursa research report',f'Stock: {r["ticker"]}',f'Data mode: {"SYNTHETIC DEMO" if demo else "Yahoo provider data"}',
        f'Price as of: {r["as_of"]}',f'Fetched: {report["fetched_at"]}',f'SC sector: {sector}',
        'Shariah reference: SC Malaysia SAC, 29 May 2026 (dated snapshot).',
        f'Conclusion: {verdict}','\n## Unresolved checks',*[f'- {x}' for x in blockers],
        '\n## User-authored thesis',thesis,'Source supplied by user: '+source,
        f'Event review recorded: {reviewed}; next event: {event or "not supplied"}',
        '\n## Market',str(context['returns'] if context else 'Unavailable'),
        '\n## Statement checks',pd.DataFrame(quality['checks']).to_csv(index=False),
        '\n## Peer sample',pd.DataFrame(report['peers']['rows']).to_csv(index=False),
        '\n## Valuation assumptions',pd.DataFrame(scenario_rows).to_csv(index=False),
        '\n## Plan and risk policy',json.dumps(p,indent=2,default=str),
        '\n## Portfolio',pd.DataFrame(exposure['rows']).to_csv(index=False),
        '\n## Limits','No predictive win rate or independent event verification. Annual statements may lag. Stops and targets are conditional, not guaranteed executions. Backtesting is technical-only and separate from this current research report.'
    ])
    st.download_button('Download research report',report_text,r['ticker']+'-research.md','text/markdown')


def backtest_panel(rules,policy,demo):
    st.subheader('Historical strategy research')
    st.caption('Technical rules and structural trade plan only. Current FA, current peers, market gates and user event notes are not backtested. This is not a historical test of the full research verdict.')
    code=st.text_input('Stock code to backtest',value='5347',key='bt_code')
    from engine import ticker_code
    try:
        ticker=ticker_code(code)
    except ValueError as exc:
        st.info(str(exc));return
    signature=(ticker,rules,policy,demo)
    if st.button('Run 5-year research test',key='run_bt'):
        try:
            with st.spinner('Testing next-session triggers and conservative daily-bar execution…'):
                frame=history(ticker,demo,period='5y')
                result=research_backtest(frame,rules,policy)
                try:
                    benchmark=history('^KLSE',demo,period='5y')
                    for label in ('development','holdout','cost_stress'):
                        s=result[label]['summary'];s['KLCI price return %']=benchmark_window(benchmark,s['start'],s['end'])
                except Exception as exc:
                    result['benchmark_error']=str(exc)
                st.session_state.backtest_result={'signature':signature,'data':result}
        except Exception as exc:
            st.session_state.backtest_result=None;st.error(str(exc))
    stored=st.session_state.get('backtest_result')
    if not stored:return
    if stored['signature'] != signature:
        st.warning('Inputs changed. Run again to replace the earlier test.');return
    result=stored['data']
    st.warning('The last 30% of sessions is a chronological holdout, not guaranteed untouched data. Repeatedly tuning after viewing it contaminates the test. No automated parameter optimisation is performed.')
    summaries=[{'Window':label,**result[label]['summary']} for label in ('development','holdout','cost_stress')]
    st.dataframe(pd.DataFrame(summaries),hide_index=True)
    curves=pd.concat({label:result[label]['curve'].equity for label in ('holdout','cost_stress')},axis=1)
    st.line_chart(curves)
    st.dataframe(pd.DataFrame(result['holdout']['trades']),hide_index=True)
    st.download_button('Download holdout trades',pd.DataFrame(result['holdout']['trades']).to_csv(index=False),ticker+'-holdout.csv','text/csv')
    audit={'ticker':ticker,'mode':'synthetic demo' if demo else 'Yahoo','rules':result['rules'],'policy':result['policy'],'split_date':result['split_date'],'summaries':summaries}
    st.download_button('Download test assumptions and results',json.dumps(audit,indent=2,default=str),ticker+'-test.json','application/json')
    st.caption('Fees/slippage are doubled in the stress run. One position at a time, no leverage, 100-share lots, 3-session trigger validity, 20-session time exit. Gap stops use the opening price; both-hit bars use the stop first. The final bar is liquidated. Reported dividends are credited to positions carried into the ex-date; KLCI comparison is price-only and fully invested, unlike the strategy. Splits block the test. Rights issues, missing corporate actions, suspensions and daily execution remain limitations. A selected surviving stock does not establish a whole-universe edge.')

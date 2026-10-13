from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import io
import json

import pandas as pd
import streamlit as st

from data import history, company_info, financial_statements
from research import RiskPolicy, market_context
from research_ui import research_panel, backtest_panel
from engine import Rules, technical, fundamentals, ticker_code, tick_round, size_plan, validate_portfolio, completed_bars

st.set_page_config(page_title='Bursa Research Desk', page_icon='📊', layout='wide')
st.title('Bursa Research Desk')
st.caption('Research edition · market context, financial statements, conditional plans, portfolio risk and historical testing.')
st.info('Research signals are unvalidated hypotheses. Prices are provider daily bars, not live quotes. '
        'No orders are placed. Today’s MYT bar is always excluded, including after market close.')

for key, default in [('portfolio', []), ('scan', None), ('analysis', None)]:
    if key not in st.session_state:
        st.session_state[key] = default

with st.sidebar:
    st.header('Data & screening')
    demo = st.toggle('Offline demo — synthetic prices', value=False)
    uploaded = st.file_uploader('Stock universe CSV', type='csv')
    st.caption('Default: 849 Main/ACE stocks from the SC list dated 29 May 2026. Upload columns: ticker,name. LEAP entries are kept separately.')
    surge = st.slider('Minimum volume expansion', 1.5, 4.0, 2.0, .1)
    min_value = st.number_input('Minimum average daily traded value (RM)', min_value=0.0, value=500000.0, step=100000.0)
    min_price = st.number_input('Minimum share price (RM)', min_value=.005, value=.20, step=.05, format='%.3f')
    max_rsi = st.slider('Maximum RSI for candidate', 50, 90, 75)
    strict_fa = st.checkbox('Require all five snapshot FA checks to pass', value=True)
    require_market = st.checkbox('Require supportive KLCI and positive 63-session relative strength', value=True)
    st.header('Trade planner')
    equity = st.number_input('Portfolio equity (RM)', min_value=100.0, value=10000.0, step=1000.0)
    allocation = st.number_input('Maximum cash per position (RM)', min_value=100.0, value=2000.0, step=100.0)
    risk_pct = st.slider('Estimated risk per trade (% equity)', .1, 3.0, .5, .1)
    atr_mult = st.slider('Stop distance (ATR)', 1.0, 4.0, 2.0, .1)
    rr = st.slider('Gross reward/risk target', 1.0, 5.0, 2.0, .5)
    st.caption('Cost assumptions below are examples, not a broker fee schedule. Include brokerage, taxes and exchange charges in your estimate.')
    fee_pct = st.number_input('Estimated all-in fee per side (%)', min_value=0.0, value=.20, step=.01)
    minimum_fee = st.number_input('Minimum all-in fee per side (RM)', min_value=0.0, value=9.0, step=1.0)
    slip_pct = st.number_input('Slippage allowance per side (%)', min_value=0.0, max_value=10.0, value=.10, step=.05)
    with st.expander('Portfolio risk limits'):
        position_cap = st.slider('Maximum position (% equity)', 1, 100, 20)
        sector_cap = st.slider('Maximum sector (% equity)', 1, 100, 35)
        heat_cap = st.slider('Maximum portfolio mark-to-stop risk (%)', .5, 10.0, 3.0, .5)
        participation = st.slider('Maximum share of average daily volume (%)', .1, 5.0, 1.0, .1)
        min_net_rr = st.slider('Minimum reward/risk after estimated costs', 1.0, 4.0, 1.5, .1)
    if st.button('Refresh provider caches'):
        history.clear()
        company_info.clear()
        financial_statements.clear()
        st.session_state.research_report = None
        st.session_state.backtest_result = None
        st.session_state.scan = None
        st.session_state.analysis = None
        st.rerun()

rules = Rules(surge, min_value, min_price, max_rsi, atr_mult, rr)
policy = RiskPolicy(equity, allocation, risk_pct, fee_pct, minimum_fee, slip_pct, position_cap, sector_cap, heat_cap, participation, min_net_rr)
mode = 'DEMO' if demo else 'YAHOO'
if st.session_state.get('mode') != mode:
    st.session_state.update(mode=mode, scan=None, analysis=None, research_report=None, backtest_result=None)
if demo:
    st.warning('DEMO MODE: all prices and fundamentals are synthetic. Do not use them for trading.')


def load_universe():
    local = Path(__file__).with_name('tickers.csv')
    source = io.BytesIO(uploaded.getvalue()) if uploaded else local
    df = pd.read_csv(source, dtype=str).fillna('')
    df.columns = [c.strip().lower() for c in df.columns]
    if 'ticker' not in df:
        aliases = [c for c in df.columns if c in ('code', 'symbol', 'stock_code')]
        if not aliases:
            raise ValueError('CSV requires a ticker column (code and symbol are also accepted).')
        df = df.rename(columns={aliases[0]: 'ticker'})
    df['ticker'] = df.ticker.map(ticker_code)
    if 'name' not in df:
        df['name'] = df.ticker
    for c in ['shariah_status', 'shariah_as_of']:
        if c not in df:
            df[c] = ''
    return df.drop_duplicates('ticker').reset_index(drop=True)


try:
    universe = load_universe()
except Exception as exc:
    st.error(f'Cannot read universe: {exc}')
    st.stop()


def classification(ticker):
    reference = pd.read_csv(Path(__file__).with_name('shariah_reference.csv'), dtype=str).fillna('')
    code = ticker.removesuffix('.KL')
    rows = reference[reference.ticker == code]
    if not rows.empty:
        row = rows.iloc[0]
        return (f'Shariah-compliant in SC Malaysia SAC list dated 29 May 2026 · '
                f'{row.market} Market · printed page {row.source_page}. Later changes are not checked automatically.')
    return 'Not found in the bundled SC list dated 29 May 2026. Current Shariah status is unverified.'


def evaluate(ticker):
    result = technical(history(ticker, demo), rules)
    error = ''
    try:
        info = company_info(ticker, demo)
    except Exception as exc:
        info, error = {}, str(exc)
    fa = fundamentals(info)
    try:
        market = market_context(result['frame'], history('^KLSE', demo))
        market_error = ''
    except Exception as exc:
        market, market_error = None, str(exc)
    result.update(ticker=ticker, fa=fa, fa_error=error, info=info, market=market, market_error=market_error)
    return result


screen, detail, portfolio, testing, method = st.tabs(['Market screener', 'Stock analysis', 'Portfolio journal', 'Historical testing', 'Method & limits'])

with screen:
    st.write(f'{len(universe)} stock codes in the active universe.')
    if uploaded is None:
        st.caption('Source: SC Malaysia SAC Shariah list, 29 May 2026 — 642 Main + 207 ACE. The 37 LEAP entries are retained separately. This is a dated classification snapshot.')
    else:
        st.caption('Using your uploaded universe; inclusion alone does not verify Shariah status. Stock analysis checks membership in the bundled May 2026 reference.')
    st.caption('Ordinary RM-denominated shares only. Do not include ETFs, warrants, or other instruments with different tick/lot conventions.')
    max_scan = st.number_input('Maximum stocks in this scan', min_value=1, max_value=max(1, len(universe)), value=min(30, max(1, len(universe))))
    st.caption('Start with 30 stocks. Set the maximum to the universe size to scan the full list; a full scan can take several minutes.')
    if st.button('Run screen', type='primary'):
        records, errors = [], []
        chosen = universe.head(int(max_scan))
        progress = st.progress(0.0)
        for n, row in enumerate(chosen.itertuples(), start=1):
            try:
                r = evaluate(row.ticker)
                market_ok = r['market'] is not None and r['market']['regime'] == 'Supportive' and r['market']['returns']['63']['excess_pp'] > 0
                eligible = r['candidate'] and (not strict_fa or r['fa']['status'] == 'Pass') and (not require_market or market_ok)
                records.append({'Ticker': row.ticker, 'Company': r['fa']['name'] or row.name,
                                'As of': r['as_of'], 'Close (RM)': r['close'], 'RSI': round(r['rsi'], 1),
                                'Volume expansion': round(r['surge'], 2), 'FA': r['fa']['status'],
                                'KLCI': r['market']['regime'] if r['market'] else 'Unknown',
                                '63-session excess pp': round(r['market']['returns']['63']['excess_pp'], 2) if r['market'] else None,
                                'Statement review': 'Open Stock analysis for annual checks',
                                'Technical candidate': r['candidate'], 'Passes selected screen': eligible,
                                'Unmet technical checks': '; '.join(k for k, v in r['checks'].items() if not v)})
                if r['market_error']:
                    errors.append({'Ticker': row.ticker, 'Issue': 'Market context unavailable: ' + r['market_error']})
                if r['fa_error']:
                    errors.append({'Ticker': row.ticker, 'Issue': 'FA unavailable: ' + r['fa_error']})
            except Exception as exc:
                errors.append({'Ticker': row.ticker, 'Issue': str(exc)})
            progress.progress(n / max(1, len(chosen)), text=f'Checked {n}/{len(chosen)}')
        st.session_state.scan = {'records': records, 'errors': errors,
                                 'settings': (rules, strict_fa, require_market, universe.to_csv(index=False), max_scan),
                                 'time': datetime.now(ZoneInfo('Asia/Kuala_Lumpur')).isoformat(timespec='seconds')}
    scan = st.session_state.scan
    if scan:
        st.caption(f'Scan completed: {scan["time"]}')
        if scan['settings'] != (rules, strict_fa, require_market, universe.to_csv(index=False), max_scan):
            st.warning('Settings or universe changed. Run the screen again; the table below is the earlier result.')
        table = pd.DataFrame(scan['records'])
        if not table.empty:
            table = table.sort_values(['Passes selected screen', '63-session excess pp'], ascending=[False, False], na_position='last')
            st.write(f'{int(table["Passes selected screen"].sum())} candidates from {len(table)} successfully analysed stocks.')
            only = st.checkbox('Show only candidates', value=False)
            st.dataframe(table[table['Passes selected screen']] if only else table, hide_index=True)
            st.download_button('Download full screen CSV', table.to_csv(index=False), 'bursa-screen.csv', 'text/csv')
        if scan['errors']:
            with st.expander(f'Data issues ({len(scan["errors"])})', expanded=True):
                st.dataframe(pd.DataFrame(scan['errors']), hide_index=True)
        if table.empty:
            st.warning('No stocks could be analysed. Inspect data issues; this is not a no-opportunity conclusion.')

with detail:
    choices = {f'{r.ticker} — {r.name}': r.ticker for r in universe.itertuples()}
    chosen_name = st.selectbox('Choose from your stock universe', list(choices)) if choices else None
    override = st.text_input('Or enter a Bursa stock code', placeholder='5347 or 5347.KL')
    if st.button('Analyse stock', type='primary'):
        try:
            ticker = ticker_code(override) if override.strip() else choices[chosen_name]
            with st.spinner('Reading completed sessions and fundamentals…'):
                st.session_state.analysis = {'result': evaluate(ticker), 'rules': rules}
        except Exception as exc:
            st.session_state.analysis = None
            st.error(str(exc))
    stored = st.session_state.analysis
    if stored:
        r = stored['result']
        st.subheader(f'{r["ticker"]} — {r["fa"]["name"]}')
        st.caption(classification(r['ticker']))
        if stored['rules'] != rules:
            st.warning('Screening settings changed. Analyse again to update the technical result.')
        st.caption(f'Last completed provider session: {r["as_of"]}. Fundamental snapshot is fetched separately; reporting periods may differ.')
        a, b, c = st.columns(3)
        a.metric('Last completed close', f'RM {r["close"]:.3f}')
        b.metric('Wilder RSI (14)', f'{r["rsi"]:.1f}')
        c.metric('Prior average daily traded value', f'RM {r["turnover"]:,.0f}')
        st.write(f'**{r["label"]}** · {r["context"]}')
        fa_ok = not strict_fa or r['fa']['status'] == 'Pass'
        market_ok = r['market'] is not None and r['market']['regime'] == 'Supportive' and r['market']['returns']['63']['excess_pp'] > 0
        st.write('**Selected screen:** ' + ('Pass' if r['candidate'] and fa_ok and (not require_market or market_ok) else 'Does not pass'))
        st.line_chart(r['frame'][['Close', 'SMA50', 'SMA200']].tail(180))
        st.dataframe(pd.DataFrame([{'Technical requirement': k, 'Met': bool(v)} for k, v in r['checks'].items()]), hide_index=True)
        st.write(f'**Fundamentals: {r["fa"]["status"]}** · Sector: {r["fa"]["sector"]}')
        st.dataframe(pd.DataFrame(r['fa']['rows']), hide_index=True)
        st.caption('ROE and revenue growth are decimals: 0.10 means 10%. Debt/equity is a percentage. Thresholds are research defaults, not sector-relative fair values.')
        if r['fa_error']:
            st.warning('Fundamentals unavailable: ' + r['fa_error'])
        st.markdown(f'[Open chart](https://www.tradingview.com/chart/?symbol=MYX%3A{r["ticker"].removesuffix(".KL")}) · '
                    '[Check official Shariah lists](https://www.sc.com.my/development/islamic-capital-market/list-of-shariah-compliant-securities)')
        if stored['rules'] == rules:
            research_panel(r, rules, policy, demo, st.session_state.portfolio, universe)

with portfolio:
    st.subheader('Your manually recorded positions')
    st.caption('Session storage only: export JSON before closing or restarting. Import restores records. The journal is separate from demo data; quotes follow the current mode.')
    incoming = st.file_uploader('Restore portfolio JSON', type='json')
    if st.button('Import and replace current journal', disabled=incoming is None):
        try:
            if incoming.size > 1_000_000:
                raise ValueError('File is too large.')
            st.session_state.portfolio = validate_portfolio(json.loads(incoming.getvalue()))
            st.success('Portfolio restored.')
        except Exception as exc:
            st.error(f'Import rejected: {exc}')
    with st.form('position'):
        ticker_input = st.text_input('Actual position stock code', value='5347')
        x, y, z = st.columns(3)
        actual_entry = x.number_input('Actual average entry (RM)', min_value=.005, value=1.0, step=.005, format='%.3f')
        actual_stop = y.number_input('Planned stop (RM)', min_value=.005, value=.90, step=.005, format='%.3f')
        actual_target = z.number_input('Planned target (RM)', min_value=.005, value=1.20, step=.005, format='%.3f')
        shares = st.number_input('Actual shares held', min_value=1, value=100, step=100)
        if st.form_submit_button('Save / update actual position'):
            try:
                row = validate_portfolio([{'ticker': ticker_input, 'entry': actual_entry,
                                           'stop': actual_stop, 'target': actual_target, 'shares': shares}])[0]
                positions = [p for p in st.session_state.portfolio if p['ticker'] != row['ticker']] + [row]
                st.session_state.portfolio = validate_portfolio(positions)
                st.success('Position recorded. Export a backup below.')
            except Exception as exc:
                st.error(str(exc))
    st.download_button('Export portfolio JSON', json.dumps(st.session_state.portfolio, indent=2), 'portfolio.json', 'application/json')
    if st.session_state.portfolio:
        names = [p['ticker'] for p in st.session_state.portfolio]
        remove = st.selectbox('Position to remove', names)
        if st.button('Remove selected position'):
            st.session_state.portfolio = [p for p in st.session_state.portfolio if p['ticker'] != remove]
            st.rerun()
        if st.button('Refresh journal quotes'):
            history.clear()
        rows = []
        for pos in st.session_state.portfolio:
            row = dict(pos)
            try:
                df = completed_bars(history(pos['ticker'], demo))
                last = df.iloc[-1]
                age = (datetime.now(ZoneInfo('Asia/Kuala_Lumpur')).date() - df.index[-1].date()).days
                stop_touch, target_touch = last.Low <= pos['stop'], last.High >= pos['target']
                status = ('Both levels inside last bar — order unknown' if stop_touch and target_touch else
                          'Stop inside/beyond last bar range — review' if stop_touch else
                          'Target inside/beyond last bar range — review' if target_touch else 'Neither level touched in last bar')
                row.update(as_of=str(df.index[-1].date()), last_close=float(last.Close),
                           gross_pnl_rm=round((float(last.Close)-pos['entry'])*pos['shares'], 2),
                           gross_pnl_pct=round((float(last.Close)/pos['entry']-1)*100, 2),
                           status=('STALE DATA: ' if age > 7 else '') + status)
            except Exception as exc:
                row.update(last_close=None, gross_pnl_rm=None, status=f'Data unavailable: {exc}')
            rows.append(row)
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.caption('Gross P&L excludes fees, dividends and corporate actions. Range checks refer only to the last completed bar, may precede your entry, and do not establish that an order executed. No background alerts.')

with testing:
    backtest_panel(rules, policy, demo)

with method:
    st.markdown("""
**Research workflow**

The screener shortlists technical candidates using the same causal price/volume engine as stock analysis. Optional gates require snapshot FA, supportive KLCI trend and positive 63-session relative strength. Screening is not financial-statement approval. Open Stock analysis and build a report to inspect annual cash conversion, free cash flow, leverage, interest cover and earnings consistency.

**Conditional plan**

A buy-stop trigger sits above the latest completed bar's high. Invalidation is below 10-session support with a 0.25 ATR buffer, or the configured ATR distance, whichever is lower. Confirmed historical swing resistance can cap the target. Plans expire after three subsequent sessions; do not chase more than 0.25 ATR beyond the trigger. The historical model exits after 20 holding sessions. These rules are assumptions to evaluate, not a proven edge or a complete Wyckoff phase model.

**Risk and evidence**

Position size respects cash, per-trade risk, position/sector caps, total mark-to-stop risk and prior-volume participation. Portfolio equity is supplied by you; cash and holdings are not broker-verified. Missing holdings prices or sectors block sizing. Correlations use at least 60 shared daily returns and are warnings, not stable diversification guarantees. Business theses and upcoming-event reviews are user-authored; missing reviews and near-term events keep a report on the watchlist. Valuation scenarios are editable assumptions with no forecast probability.

**Data policy**

Prices are Yahoo daily bars, with today's MYT candle always excluded. Require 220 completed observations and latest data within seven calendar days; no exchange holiday calendar is included. Volume/range averages exclude the evaluated bar. RSI/ATR use arithmetic-seeded Wilder smoothing. Unadjusted OHLC is requested explicitly. Reported recent splits block screening and any reported split blocks historical testing; missing corporate actions remain a limitation. Fundamentals and annual periods may lag and are not independently audited filings. Shariah status is from the supplied SC snapshot dated 29 May 2026.

**Historical testing**

The technical-only simulator uses next-session conditional entries, costs, conservative daily-bar order, gap stops, a time exit and separate chronological development/holdout windows. It does not backtest current FA, peers, market gates, or manual events. A selected surviving stock and today's list cannot prove whole-market performance. Repeated inspection/tuning contaminates holdouts; a future paper-trading period remains necessary. No win-rate guarantee, trade execution, durable cloud storage or background monitoring is provided.
""")

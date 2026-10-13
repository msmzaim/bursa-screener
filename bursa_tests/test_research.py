import unittest
from dataclasses import replace
import numpy as np
import pandas as pd
from engine import Rules, indicators
from research import (RiskPolicy, market_context, statement_review, structure_plan, portfolio_review,
                      constrained_plan, peer_review, valuation_scenarios)
from backtest import simulate, research_backtest, exit_on_bar


def bars(n=300):
    dates=pd.bdate_range(end='2026-10-12',periods=n)
    close=2+np.arange(n)*.005+np.sin(np.arange(n))*.02
    return pd.DataFrame({'Open':close-.005,'High':close+.03,'Low':close-.03,
                         'Close':close,'Volume':1_000_000,'Stock Splits':0,'Dividends':0.0},index=dates)


class ResearchTests(unittest.TestCase):
    def test_market_shared_dates_and_relative_strength(self):
        df=bars();r=market_context(df,df,now='2026-10-13')
        self.assertEqual(r['regime'],'Supportive')
        self.assertEqual(r['returns']['63']['excess_pp'],0)
        with self.assertRaises(ValueError):market_context(df,df.iloc[:-1],now='2026-10-13')

    def test_statement_period_alignment_and_missing_data(self):
        dates=pd.to_datetime(['2025-12-31','2024-12-31','2023-12-31'])
        income=pd.DataFrame([[120,110,100],[10,9,8],[20,18,16],[25,23,20],[2,2,2]],
                            index=['Total Revenue','Net Income','EBIT','EBITDA','Interest Expense'],columns=dates)
        cash=pd.DataFrame([[14,12,10],[-5,-4,-3]],index=['Operating Cash Flow','Capital Expenditure'],columns=dates)
        balance=pd.DataFrame([[30,30,30],[10,10,10]],index=['Total Debt','Cash And Cash Equivalents'],columns=dates)
        s={'income':income,'cashflow':cash,'balance':balance}
        r=statement_review(s,{},now='2026-10-13')
        self.assertEqual(r['status'],'Checks passed')
        self.assertEqual(r['periods'][0]['fcf'],9)
        self.assertAlmostEqual(r['periods'][0]['cash_conversion'],1.4)
        s['cashflow']=cash.drop(columns=dates[0])
        r=statement_review(s,{},now='2026-10-13')
        self.assertIsNone(r['periods'][0]['cfo'])
        self.assertEqual(r['status'],'Incomplete')
        self.assertEqual(statement_review(s,{'sector':'Real Estate'},now='2026-10-13')['status'],'Sector-specific review required')

    def test_peers_require_same_industry_and_three_observations(self):
        info={'industry':'Manufacturing','trailingPE':15}
        peers={str(i):{'industry':'Manufacturing','trailingPE':10+i,'quoteType':'EQUITY'} for i in range(3)}
        self.assertEqual(peer_review(info,peers)['median_pe'],11)
        peers['2']['industry']='Software'
        self.assertIsNone(peer_review(info,peers)['median_pe'])

    def test_valuation_rejects_currency_mismatch(self):
        info={'trailingEps':.20,'currency':'MYR','financialCurrency':'USD'}
        with self.assertRaises(ValueError):valuation_scenarios(info,2,[('Base',0,10)])
        info['financialCurrency']='MYR'
        self.assertEqual(valuation_scenarios(info,2,[('Base',0,10)])[0]['Illustrative value RM'],2)

    def test_structural_plan_and_no_future_pivots(self):
        df=indicators(bars());p=structure_plan(df,Rules())
        self.assertGreater(p['entry'],df.High.iloc[-1])
        self.assertLess(p['stop'],df.Low.tail(10).min())
        self.assertGreater(p['target'],p['entry'])
        copy=df.copy();copy.iloc[-1,copy.columns.get_loc('Close')]*=1.001
        self.assertEqual(structure_plan(copy,Rules())['entry'],p['entry'])

    def test_portfolio_missing_quote_blocks_size(self):
        df=indicators(bars())
        positions=[{'ticker':'5347.KL','shares':100,'entry':3,'stop':2.8,'target':4}]
        policy=RiskPolicy(equity=10000)
        report=portfolio_review(positions,{}, {'5347.KL':'Utilities'},df,now='2026-10-13',policy=policy)
        p=constrained_plan(structure_plan(df,Rules()),df,report,'Industrials','7086.KL',policy)
        self.assertFalse(p['constraints_pass']);self.assertEqual(p['lots'],0)

    def test_sector_capacity_and_existing_holding(self):
        df=indicators(bars());policy=RiskPolicy(equity=10000)
        exposure={'complete':True,'rows':[],'cash_estimate':6000,'sector_values':{'Industrials':4000},'risk_to_stop':0}
        p=constrained_plan(structure_plan(df,Rules()),df,exposure,'Industrials','7086.KL',policy)
        self.assertEqual(p['lots'],0)
        exposure.update(sector_values={},rows=[{'ticker':'7086.KL'}])
        p=constrained_plan(structure_plan(df,Rules()),df,exposure,'Industrials','7086.KL',policy)
        self.assertFalse(p['constraints_pass'])


class BacktestTests(unittest.TestCase):
    def setup_sim(self):
        df=indicators(bars(230))
        for col in ['Open','High','Low','Close']:df[col]=100.0
        df['VolumeBase']=1_000_000.0
        policy=RiskPolicy(equity=100000,allocation=20000,risk_pct=3,fee_pct=0,minimum_fee=0,slip_pct=0,
                          position_cap_pct=100,sector_cap_pct=100,heat_cap_pct=10,min_net_rr=1)
        def plan(prefix):
            return {'entry':100,'stop':95,'target':110,'max_entry':102,'valid_sessions':3,
                    'max_hold_sessions':20,'as_of':str(prefix.index[-1].date())}
        return df,policy,plan

    def test_entry_is_after_signal_and_stop_first(self):
        df,policy,plan=self.setup_sim()
        df.loc[df.index[220],['Open','High','Low','Close']]=[100,111,94,100]
        r=simulate(df,Rules(),policy,219,229,lambda p:len(p)==220,plan)
        t=r['trades'][0]
        self.assertGreater(t['entry_date'],t['signal_date'])
        self.assertEqual(t['exit_fill'],95)
        self.assertLess(t['net_pnl'],0)

    def test_gap_stop_and_dividend_entitlement(self):
        df,policy,plan=self.setup_sim()
        df.loc[df.index[221],['Open','High','Low','Close']]=[90,92,88,91]
        df.loc[df.index[220],'Dividends']=1.0
        df.loc[df.index[221],'Dividends']=.5
        r=simulate(df,Rules(),policy,219,229,lambda p:len(p)==220,plan)
        t=r['trades'][0]
        self.assertEqual(t['exit_fill'],90)
        self.assertEqual(t['dividends'],t['shares']*.5)
        self.assertEqual(t['net_pnl'],t['shares']*(-10+.5))

    def test_chase_gap_is_not_filled(self):
        df,policy,plan=self.setup_sim()
        df.loc[df.index[220],['Open','High','Low','Close']]=[105,108,104,106]
        r=simulate(df,Rules(),policy,219,229,lambda p:len(p)==220,plan)
        self.assertEqual(r['summary']['trades'],0)
        self.assertEqual(r['summary']['skipped_entries'],1)

    def test_zero_signals_is_valid_not_profitability(self):
        df,policy,plan=self.setup_sim()
        r=simulate(df,Rules(),policy,219,229,lambda p:False,plan)
        self.assertEqual(r['summary']['net_return_pct'],0)
        self.assertIsNone(r['summary']['win_rate_pct'])

    def test_costs_reduce_returns_and_future_rows_do_not_change_prefix(self):
        df,policy,plan=self.setup_sim()
        df.loc[df.index[221],['Open','High','Low','Close']]=[110,112,110,111]
        signal=lambda p:len(p)==220
        free=simulate(df,Rules(),policy,219,225,signal,plan)
        paid=simulate(df,Rules(),replace(policy,fee_pct=.2,minimum_fee=9,slip_pct=.1),219,225,signal,plan)
        self.assertLess(paid['summary']['net_return_pct'],free['summary']['net_return_pct'])
        changed=df.copy();changed.iloc[226:,changed.columns.get_loc('Close')]=999
        self.assertEqual(simulate(changed,Rules(),policy,219,225,signal,plan)['trades'],free['trades'])

    def test_split_blocks_research(self):
        df=bars(600);df.loc[df.index[-10],'Stock Splits']=2
        with self.assertRaises(ValueError):research_backtest(df,Rules(),now='2026-10-13')

    def test_holdout_starts_after_development(self):
        result=research_backtest(bars(500),Rules(),now='2026-10-13')
        self.assertLess(result['development']['summary']['end'],result['holdout']['summary']['start'])
        self.assertEqual(result['holdout']['summary']['start'],result['cost_stress']['summary']['start'])

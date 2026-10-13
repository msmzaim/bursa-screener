import unittest
import numpy as np
import pandas as pd
from engine import completed_bars, indicators, fundamentals, size_plan, tick_round, ticker_code, validate_portfolio, wilder, technical, Rules


def prices(n=300):
    idx = pd.bdate_range(end='2026-10-12', periods=n)
    close = 2 + np.arange(n)*.005 + np.sin(np.arange(n))*.02
    return pd.DataFrame({'Open': close-.005, 'High': close+.03, 'Low': close-.03,
                         'Close': close, 'Volume': 1_000_000}, index=idx)


class EngineTests(unittest.TestCase):
    def test_current_date_always_excluded(self):
        df = prices()
        self.assertEqual(completed_bars(df, '2026-10-12 23:00').index[-1], pd.Timestamp('2026-10-09'))
        self.assertEqual(completed_bars(df, '2026-10-13').index[-1], pd.Timestamp('2026-10-12'))

    def test_wilder_seed_and_recursion(self):
        result = wilder(pd.Series(range(1, 17), dtype=float))
        self.assertEqual(result.iloc[13], 7.5)
        self.assertAlmostEqual(result.iloc[14], (7.5*13 + 15)/14)

    def test_flat_and_rising_rsi(self):
        df = prices()
        df['Close'] = 2.0
        self.assertEqual(indicators(df).RSI.iloc[-1], 50)
        df['Close'] = np.arange(len(df))+2.0
        self.assertEqual(indicators(df).RSI.iloc[-1], 100)

    def test_baseline_excludes_signal_candle(self):
        df = prices()
        df.loc[df.index[-1], 'Volume'] = 10_000_000
        self.assertEqual(indicators(df).VolumeRatio.iloc[-1], 10)

    def test_future_bars_do_not_change_past_indicators(self):
        df = prices()
        pd.testing.assert_frame_equal(indicators(df.iloc[:250]), indicators(df).iloc[:250])

    def test_missing_fa_does_not_pass(self):
        self.assertEqual(fundamentals({})['status'], 'Incomplete')
        self.assertEqual(fundamentals({'trailingPE': 12})['status'], 'Incomplete')
        self.assertEqual(fundamentals({'trailingPE': -2})['status'], 'Fail')

    def test_sector_override(self):
        info = dict(trailingPE=10, returnOnEquity=.15, operatingCashflow=1, debtToEquity=20, revenueGrowth=.1)
        self.assertEqual(fundamentals(info)['status'], 'Pass')
        info['sector'] = 'Financial Services'
        self.assertEqual(fundamentals(info)['status'], 'Sector review required')

    def test_sizing_respects_both_budgets(self):
        for entry in [.20, 1, 5, 10, 50]:
            for risk in [.1, .5, 2]:
                p = size_plan(entry, entry*.90, entry*1.20, 10000, risk, 2000, .2, 9, .1)
                self.assertLessEqual(p['estimated_cash'], 2000)
                self.assertLessEqual(p['estimated_stop_loss'], 10000*risk/100 + 1e-8)
                self.assertEqual(p['shares'] % 100, 0)
        self.assertEqual(size_plan(100, 90, 120, 1000, .1, 100, .2, 9, .1)['lots'], 0)

    def test_tick_boundaries(self):
        self.assertEqual(tick_round(.999, up=True), 1.0)
        self.assertEqual(tick_round(9.999, up=True), 10.0)
        self.assertEqual(tick_round(99.999, up=True), 100.0)
        self.assertEqual(tick_round(100.09), 100.0)

    def test_import_validation(self):
        self.assertEqual(ticker_code('166.0'), '0166.KL')
        row = dict(ticker='5347', entry=1, stop=.9, target=1.2, shares=100)
        self.assertEqual(validate_portfolio([row])[0]['ticker'], '5347.KL')
        for invalid in [dict(row, stop=2), dict(row, shares=1.5), dict(row, entry=float('nan'))]:
            with self.assertRaises(ValueError):
                validate_portfolio([invalid])
        with self.assertRaises(ValueError):
            validate_portfolio([row, row])

    def test_insufficient_stale_and_split_data(self):
        with self.assertRaises(ValueError):
            technical(prices(100), now='2026-10-13')
        r = technical(prices(), now='2026-11-13')
        self.assertFalse(r['checks']['Data no more than 7 calendar days old'])
        df = prices()
        df['Stock Splits'] = 0
        df.loc[df.index[-2], 'Stock Splits'] = 2
        r = technical(df, now='2026-10-13')
        self.assertFalse(r['checks']['No recent split requiring data review'])

    def test_positive_candidate_and_required_pullback(self):
        df = prices()
        df.loc[df.index[-2], ['Open','High','Low','Close','Volume']] = [3.48,3.65,3.45,3.63,3_000_000]
        df.loc[df.index[-1], ['Open','High','Low','Close','Volume']] = [3.60,3.62,3.58,3.61,500_000]
        rules = Rules(max_rsi=100)
        r = technical(df, rules, now='2026-10-13')
        self.assertTrue(r['candidate'], r['checks'])
        df.loc[df.index[-1], ['Open','High','Low','Close']] = [3.63,3.67,3.63,3.66]
        r = technical(df, rules, now='2026-10-13')
        self.assertFalse(r['candidate'])
        self.assertFalse(r['checks']['Latest close lower than previous close'])

if __name__ == '__main__':
    unittest.main()

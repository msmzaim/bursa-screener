import csv
import unittest
from collections import Counter
from pathlib import Path

class UniverseTests(unittest.TestCase):
    def test_source_reconciliation(self):
        root = Path(__file__).parents[1]
        with (root/'shariah_reference.csv').open() as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 886)
        self.assertEqual(len({r['ticker'] for r in rows}), 886)
        self.assertEqual(Counter(r['market'] for r in rows), {'Main':642, 'ACE':207, 'LEAP':37})
        expected = {'Industrial products and services':271,'Consumer products and services':184,
                    'Technology':98,'Property':86,'Construction':75,'Energy':37,'Plantation':35,
                    'Transportation and logistics':31,'Healthcare':27,'Telecommunications and media':24,
                    'Utilities':11,'Financial services':7}
        self.assertEqual(Counter(r['sector'] for r in rows), expected)
        with (root/'tickers.csv').open() as f:
            active = list(csv.DictReader(f))
        self.assertEqual(len(active), 849)
        self.assertTrue(all(len(r['ticker']) == 4 and r['market'] != 'LEAP' for r in active))
        codes = {r['ticker'] for r in active}
        self.assertTrue({'0166','5347','0452','0308'} <= codes)
        self.assertNotIn('1155', codes)
        self.assertNotIn('7022', codes)
        self.assertEqual({r['shariah_as_of'] for r in rows}, {'2026-05-29'})
        self.assertEqual((root/'tickers.csv').read_bytes(), (root/'shariah_list.csv').read_bytes())

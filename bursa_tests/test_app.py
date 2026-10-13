import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest

class AppTests(unittest.TestCase):
    def test_offline_user_journey(self):
        app = AppTest.from_file(str(Path(__file__).parents[1] / 'app.py'), default_timeout=30).run()
        self.assertFalse(app.exception)
        app.toggle[0].set_value(True).run()
        self.assertFalse(app.exception)
        next(n for n in app.number_input if n.label == 'Maximum stocks in this scan').set_value(4).run()
        next(b for b in app.button if b.label == 'Run screen').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state['scan']['records']), 4)
        next(b for b in app.button if b.label == 'Analyse stock').click().run()
        self.assertFalse(app.exception)
        self.assertIsNotNone(app.session_state['analysis'])
        next(b for b in app.button if b.label == 'Save / update actual position').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state['portfolio']), 1)
        next(b for b in app.button if b.label == 'Remove selected position').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['portfolio'], [])

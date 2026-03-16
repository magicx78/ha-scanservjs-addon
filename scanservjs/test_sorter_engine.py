import unittest
import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / 'sorter_engine.py'
spec = importlib.util.spec_from_file_location('sorter_engine', MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules['sorter_engine'] = mod
spec.loader.exec_module(mod)


class SorterEngineTests(unittest.TestCase):
    def test_build_tags_auto_and_manual(self):
        meta = {'document_type': 'Bank', 'datum': '2026-03-16'}
        auto = mod.build_tags(meta, manual_review=False)
        manual = mod.build_tags(meta, manual_review=True)
        self.assertIn('doctype:Bank', auto)
        self.assertIn('year:2026', auto)
        self.assertIn('month:2026-03', auto)
        self.assertIn('review:auto', auto)
        self.assertIn('review:manual', manual)

    def test_build_title_fallback(self):
        title = mod.build_title({'datum': None, 'absender': None, 'betreff': None, 'document_type': 'Arzt'})
        self.assertTrue(title.startswith('ohne-datum'))
        self.assertIn('Arzt', title)

    def test_pair_score_type_mismatch_penalty(self):
        p1 = {'document_type': 'Bank', 'referenz': 'AB-12345'}
        p2 = {'document_type': 'Arzt', 'referenz': 'AB-12345'}
        score = mod.pair_score(p1, p2)
        self.assertLess(score, 0.3)


if __name__ == '__main__':
    unittest.main()

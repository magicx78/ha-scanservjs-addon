import unittest
import importlib.util
import sys
import tempfile
import json
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

    def test_resolve_sources_supports_images_and_tiff(self):
        with tempfile.TemporaryDirectory(prefix="sorter_test_") as tmp:
            inbox = Path(tmp) / "inbox"
            inbox.mkdir(parents=True, exist_ok=True)
            for name in ["a.pdf", "b.tif", "c.jpg", "d.png", "ignore.txt", "REVIEW_x.pdf"]:
                (inbox / name).write_bytes(b"x")
            state_path = Path(tmp) / "state.json"
            state_path.write_text(json.dumps({"processed_sources": ["b.tif"], "reviews": {}}), encoding="utf-8")
            state = mod.load_state(state_path)
            settings = mod.Settings(
                sorter_enable=True,
                threshold=0.75,
                provider="openai",
                model="gpt-4o-mini",
                paperless_url="http://example",
                paperless_token="x",
                inbox_dir=inbox,
                review_dir=Path(tmp) / "review",
                processed_dir=Path(tmp) / "processed",
                state_dir=Path(tmp) / "state",
                ocr_lang="deu+eng",
            )
            files = mod.resolve_sources(settings, state)
            names = sorted([p.name for p in files])
            self.assertEqual(names, ["a.pdf", "c.jpg", "d.png"])


if __name__ == '__main__':
    unittest.main()

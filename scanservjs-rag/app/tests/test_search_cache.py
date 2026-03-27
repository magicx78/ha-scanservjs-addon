import tempfile
import time
import unittest
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.search_cache import PersistentSearchCache


class TestPersistentSearchCache(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(prefix="scanservjs-cache-", suffix=".sqlite")
        os.close(fd)
        self.db_path = path

    def tearDown(self):
        for _ in range(5):
            try:
                if os.path.exists(self.db_path):
                    os.remove(self.db_path)
                break
            except PermissionError:
                time.sleep(0.05)

    def test_hit_miss_and_expire(self):
        cache = PersistentSearchCache(self.db_path, ttl_seconds=1, max_entries=50)
        self.assertIsNone(cache.get("k1"))
        cache.set("k1", {"answer": "A"})
        self.assertEqual(cache.get("k1")["answer"], "A")
        time.sleep(1.05)
        self.assertIsNone(cache.get("k1"))

    def test_invalidation(self):
        cache = PersistentSearchCache(self.db_path, ttl_seconds=30, max_entries=50)
        cache.set("k1", {"answer": "A"})
        cache.set("k2", {"answer": "B"})
        self.assertIsNotNone(cache.get("k1"))
        cache.invalidate_all()
        self.assertIsNone(cache.get("k1"))
        self.assertIsNone(cache.get("k2"))


if __name__ == "__main__":
    unittest.main()

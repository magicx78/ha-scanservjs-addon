import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.state_machine import normalize_transition


class TestStateTransitions(unittest.TestCase):
    def test_new_happy_path_to_done(self):
        phase = "idle"
        for target in ("started", "retrieving", "reranking", "generating_answer", "done"):
            phase = normalize_transition(phase, target)
        self.assertEqual(phase, "done")

    def test_new_error_path(self):
        phase = "idle"
        phase = normalize_transition(phase, "started")
        phase = normalize_transition(phase, "retrieving")
        phase = normalize_transition(phase, "error")
        self.assertEqual(phase, "error")

    def test_happy_path_to_completed(self):
        phase = "completed"
        for target in ("started", "finding_hits", "building_answer", "expanding_result", "completed"):
            phase = normalize_transition(phase, target)
        self.assertEqual(phase, "completed")

    def test_cancelled_terminal_then_restart(self):
        phase = "started"
        phase = normalize_transition(phase, "cancelled")
        self.assertEqual(phase, "cancelled")
        phase = normalize_transition(phase, "started")
        self.assertEqual(phase, "started")

    def test_empty_and_error_paths(self):
        phase = "started"
        phase = normalize_transition(phase, "empty")
        self.assertEqual(phase, "empty")
        phase = normalize_transition(phase, "started")
        phase = normalize_transition(phase, "finding_hits")
        phase = normalize_transition(phase, "error")
        self.assertEqual(phase, "error")

    def test_invalid_transition_is_ignored(self):
        phase = "started"
        phase = normalize_transition(phase, "completed")
        self.assertEqual(phase, "started")


if __name__ == "__main__":
    unittest.main()

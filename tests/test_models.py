from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from encap.models import ChapterEntry


class ChapterEntryTest(unittest.TestCase):
    def test_runtime_ids_are_stable_unique_and_do_not_affect_equality(self) -> None:
        first = ChapterEntry(0.0, 1.0, 1, "Chapter 1")
        second = ChapterEntry(0.0, 1.0, 1, "Chapter 1")

        self.assertEqual(len(first.id), 32)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(first, second)
        self.assertEqual(first.id, first.id)


if __name__ == "__main__":
    unittest.main()

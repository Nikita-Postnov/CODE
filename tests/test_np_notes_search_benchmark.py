"""Functional checks for the synthetic NP Notes search benchmark."""
import importlib.util
from pathlib import Path
import unittest

FILE = Path(__file__).resolve().parents[1] / "tools" / "benchmark_np_notes_search.py"
SPEC = importlib.util.spec_from_file_location("np_notes_bench", FILE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BenchmarkTests(unittest.TestCase):
    def test_metadata_and_html_paths_agree(self):
        for size in (0, 1, 100):
            notes = MODULE.make_notes(size)
            for term in ("заметка", "работа", "дополнительная", "несуществующее"):
                self.assertEqual(
                    MODULE.legacy_search(notes, term),
                    MODULE.metadata_first_search(notes, term),
                )

    def test_html_parser_does_not_index_markup(self):
        self.assertEqual(MODULE.html_to_text("<b>Привет</b> мир"), "Привет  мир")
        self.assertNotIn("script", MODULE.html_to_text("<p>Обычный текст</p>"))

    def test_benchmark_does_not_read_actual_data(self):
        result = MODULE.run_case(10, repeats=1)
        self.assertEqual(result["legacy_count"], 10)
        self.assertEqual(result["metadata_first_count"], 10)


if __name__ == "__main__":
    unittest.main()

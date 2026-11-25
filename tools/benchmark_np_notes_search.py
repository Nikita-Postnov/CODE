"""NP Notes performance benchmark on synthetic data only.

Run: python tools/benchmark_np_notes_search.py --notes 100,1000,10000
Qt optional. No real user notes, filesystem reads, or telemetry.
"""
from __future__ import annotations

import argparse
from html import unescape
from html.parser import HTMLParser
from statistics import median
from time import perf_counter


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def html_to_text(html: str) -> str:
    parser = _PlainText()
    parser.feed(html)
    parser.close()
    return unescape(" ".join(parser.text))


def make_notes(count: int) -> list[dict]:
    if count < 0 or count > 100000:
        raise ValueError("count must be between 0 and 100000")
    notes = []
    for index in range(count):
        notes.append({
            "title": f"Заметка {index:05d}",
            "tags": ["работа"] if index % 5 == 0 else [],
            "reminder": "",
            "content": (
                "<html><body><p>Тестовый текст без персональных данных "
                f"номер {index:05d}</p><p>Дополнительная строка</p></body></html>"
            ),
        })
    return notes


def legacy_search(notes: list[dict], query: str) -> int:
    query = query.casefold()
    total = 0
    for note in notes:
        content = html_to_text(note["content"])
        if (query in note["title"].casefold() or
                query in " ".join(note["tags"]).casefold() or
                query in content.casefold()):
            total += 1
    return total


def metadata_first_search(notes: list[dict], query: str) -> int:
    query = query.casefold()
    total = 0
    for note in notes:
        if (query in note["title"].casefold() or
                query in " ".join(note["tags"]).casefold() or
                query in str(note["reminder"]).casefold()):
            total += 1
            continue
        if query in html_to_text(note["content"]).casefold():
            total += 1
    return total


def run_case(count: int, repeats: int = 3) -> dict:
    notes = make_notes(count)
    # A common metadata match measures the benefit of not parsing rich text.
    query = "заметка"
    results = {}
    for name, function in (("legacy", legacy_search), ("metadata_first", metadata_first_search)):
        times = []
        found = None
        for _ in range(repeats):
            start = perf_counter()
            current = function(notes, query)
            times.append((perf_counter() - start) * 1000)
            if found is not None and current != found:
                raise AssertionError("search result changed across benchmark runs")
            found = current
        results[name + "_ms"] = round(median(times), 3)
        results[name + "_count"] = found
    if results["legacy_count"] != results["metadata_first_count"]:
        raise AssertionError("Search implementations produced different result counts")
    results["notes"] = count
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes", default="100,1000,10000")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1 or args.repeats > 100:
        parser.error("repeats must be between 1 and 100")
    for raw in args.notes.split(","):
        try:
            count = int(raw.strip())
            result = run_case(count, args.repeats)
        except ValueError as error:
            parser.error(str(error))
        print(
            f"notes={count} matching={result['legacy_count']} "
            f"baseline_ms={result['legacy_ms']:.3f} "
            f"metadata_first_ms={result['metadata_first_ms']:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

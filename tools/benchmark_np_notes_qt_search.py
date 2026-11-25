"""Synthetic Qt-backed search benchmark (no real Data or telemetry).

Usage: python tools/benchmark_np_notes_qt_search.py --notes 100,1000,10000
"""
import argparse
import os
from statistics import median
from time import perf_counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QTextDocument


def make_notes(count):
    if not (0 <= count <= 100000):
        raise ValueError("note count out of range")
    return [
        {"title": f"Заметка {i:05d}", "tags": (), "reminder": "",
         "content": f"<p>Тестовая заметка {i} <b>Текст для индекса</b></p>"}
        for i in range(count)
    ]


def qt_plaintext(html):
    doc = QTextDocument()
    doc.setHtml(html)
    return doc.toPlainText()


def search(notes, query, metadata_first):
    query = query.casefold()
    count = 0
    for note in notes:
        if metadata_first and query in note["title"].casefold():
            count += 1
            continue
        text = qt_plaintext(note["content"])
        if query in note["title"].casefold() or query in text.casefold():
            count += 1
    return count


def measure(notes, query, fast, repeats=3):
    samples = []
    count = -1
    for _ in range(repeats):
        begin = perf_counter()
        found = search(notes, query, fast)
        samples.append((perf_counter() - begin) * 1000)
        if count >= 0 and count != found:
            raise AssertionError("inconsistent count")
        count = found
    return round(median(samples), 3), count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes", default="100,1000,10000")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not (1 <= args.repeats <= 100):
        parser.error("repeats out of range")
    for raw in args.notes.split(","):
        try:
            size = int(raw)
            notes = make_notes(size)
        except ValueError as error:
            parser.error(str(error))
        baseline_ms, before = measure(notes, "заметка", False, args.repeats)
        optimized_ms, after = measure(notes, "заметка", True, args.repeats)
        if before != after:
            raise AssertionError("search results changed")
        print(
            f"qt_notes={size} matching={before} baseline_ms={baseline_ms:.3f} "
            f"metadata_first_ms={optimized_ms:.3f}"
        )


if __name__ == "__main__":
    main()

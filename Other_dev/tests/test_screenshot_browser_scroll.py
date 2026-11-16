"""Интеграционная проверка длинного снимка в настоящем Chromium.

В тесте браузер отрисовывает страницу, выполняет реальную прокрутку
и отдаёт два PNG-кадра в QImage для алгоритма скриншотера.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QImage
from screenshot import _scroll_overlap, _stitch_scroll_frames, _scroll_body_unchanged
from playwright.sync_api import sync_playwright


class ChromiumScrollingTests(unittest.TestCase):
    def test_real_chrome_text_page_with_fixed_header_and_dynamic_block(self):
        sections = [
            "Избранная статья посвящена развитию научных исследований и истории.",
            "В энциклопедии размещаются открытые сведения о жизни и культуре.",
            "Раздел новых материалов содержит информацию о мировых событиях.",
            "Открытые источники помогают уточнять даты, имена и географию.",
            "Авторы продолжают расширять материалы и добавлять иллюстрации.",
            "Статьи объединяют исторические документы и современные данные.",
            "Исследователи обсуждают достоверность и проверяемость источников.",
            "Географические сведения перечисляют страны, столицы и регионы.",
            "Литературные обзоры описывают художественные произведения.",
            "Биографический раздел содержит подробности жизни исследователей.",
        ]
        blocks = "".join(
            f'<p><strong>{i:03d}.</strong> {sections[i % len(sections)]} '
            f'Для проверки указан номер записи {i:03d}, месяц {i % 12 + 1:02d} '
            f'и произвольный уникальный фрагмент {i * i + 37}.</p>'
            for i in range(80)
        )
        html = f"""
        <html lang="ru"><meta charset="UTF-8"/>
        <style>
        *{{box-sizing:border-box}}
        body{{margin:0;background:#fff;color:#202122;font:17px Arial,sans-serif}}
        header{{position:fixed;z-index:10;top:0;left:0;right:0;
                height:78px;background:#f5f6f7;border-bottom:1px solid #a2a9b1;
                padding:18px 28px;font-size:22px}}
        main{{padding:100px 32px 30px 32px;max-width:850px}}
        h1{{font-size:29px;font-weight:400}}
        p{{line-height:1.7;margin:0 0 18px}}
        aside{{position:fixed;right:12px;top:158px;width:170px;height:95px;
               padding:12px;background:#e9eef9;color:#233e7d}}
        </style>
        <header>Википедия — Свободная энциклопедия</header>
        <main><h1>Добро пожаловать в Википедию</h1>{blocks}</main>
        <aside id="dynamic">Сейчас в Википедии: обзор событий</aside>
        </html>"""
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page(viewport={"width": 1100, "height": 760},
                                        device_scale_factor=1)
                page.set_content(html, wait_until="load")
                def take():
                    image = QImage.fromData(page.screenshot(full_page=False), "PNG")
                    self.assertFalse(image.isNull())
                    return image
                first = take()
                page.evaluate("window.scrollBy(0, 125)")
                page.wait_for_timeout(180)
                scrolled = page.evaluate("window.scrollY")
                self.assertEqual(scrolled, 125)
                page.evaluate("""() => {
                    const a = document.getElementById('dynamic');
                    a.innerText = 'Сводка обновлена, новые статьи!';
                    a.style.background = '#f8d9b8';
                }""")
                second = take()
                self.assertFalse(_scroll_body_unchanged(first, second))
                offset1 = _scroll_overlap(first, second)
                self.assertEqual(offset1, 125)
                page.evaluate("window.scrollBy(0, 125)")
                page.wait_for_timeout(180)
                third = take()
                offset2 = _scroll_overlap(second, third)
                self.assertEqual(offset2, 125)
                assembled = _stitch_scroll_frames(
                    [first, second, third], [offset1, offset2])
                self.assertEqual(assembled.height(), first.height() + 250)
                self.assertEqual(assembled.width(), first.width())
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()

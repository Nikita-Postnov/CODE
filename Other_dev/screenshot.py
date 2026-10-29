from __future__ import annotations

import ctypes
import json
import logging
import math
import base64
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from array import array
from ctypes import wintypes
from enum import Enum, auto
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import (
    Qt,
    QRect,
    QRectF,
    QPoint,
    QPointF,
    QSize,
    QEvent,
    QTimer,
    QEventLoop,
    QAbstractNativeEventFilter,
    QObject,
    Slot,
    QProcess,
    QUrl,
    QMimeData,
    QStandardPaths,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QGuiApplication,
    QImage,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QFontMetrics,
    QRegion,
    QShortcut,
    QTransform,
    QFont,
    QWheelEvent,
    QClipboard,
    QIcon,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QToolBar,
    QColorDialog,
    QSlider,
    QFileDialog,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsItem,
    QInputDialog,
    QMessageBox,
    QToolButton,
    QSystemTrayIcon,
    QMenu,
    QSizePolicy,
    QComboBox,
)

log = logging.getLogger(__name__)


def _is_launcher_dir(p: Path) -> bool:
    # Choice.pyw — portable-лаунчер (может быть без Choice.exe, если вместо него Choice.bat)
    return any((p / n).exists() for n in ("launcher_config.json", "Choice.exe", "Choice.pyw"))


def _not_data_dir(p: Path) -> Path:
    """Если корнем оказалась сама папка Data — берём её родителя.

    Иначе при запуске с рабочей папкой Data (или LAUNCHER_ROOT=...\\Data)
    все файлы уезжали в Data\\Data, и, например, ffmpeg из Data не находился.
    """
    if p.name.lower() == "data" and _is_launcher_dir(p.parent):
        return p.parent
    return p


def launcher_root() -> Path:
    env = (os.environ.get("LAUNCHER_ROOT") or "").strip()
    if env:
        return _not_data_dir(Path(env).resolve())
    cwd = Path.cwd().resolve()
    if _is_launcher_dir(cwd):
        return _not_data_dir(cwd)
    if getattr(sys, "frozen", False):
        here = Path(sys.executable).resolve()
    else:
        here = Path(__file__).resolve()
    for p in [here.parent] + list(here.parents):
        if _is_launcher_dir(p):
            return _not_data_dir(p)
    return here.parent

ROOT_DIR = launcher_root()
DATA_DIR = ROOT_DIR / "Data"
NOTES_DIR = ROOT_DIR / "Notes"
PASSWORDS_DIR = ROOT_DIR / "Passwords"
SCREENSHOT_STATE_PATH = DATA_DIR / "screenshot_editor_state.json"


def qpixmap_from_qimage(img: QImage) -> QPixmap:
    return QPixmap.fromImage(img)


def _normalized_image(img: QImage) -> QImage:
    """ARGB32 с devicePixelRatio = 1.

    Снимок с HiDPI-экрана приходит с DPR 1.5/2. Редактор везде работает в
    пикселях картинки, поэтому DPR сбрасываем, чтобы Qt не масштабировал
    слои «за кадром».
    """
    out = img.convertToFormat(QImage.Format_ARGB32)
    if out.devicePixelRatio() != 1.0:
        out = out.copy()
        out.setDevicePixelRatio(1.0)
    return out


def draw_arrow(p: QPainter, start: QPointF, end: QPointF, color: QColor, width: int):
    p.save()
    pen = QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.drawLine(start, end)

    angle = math.atan2(-(end.y() - start.y()), end.x() - start.x())
    head_len = max(10, width * 3)
    a1 = angle + math.radians(25)
    a2 = angle - math.radians(25)
    p.drawLine(
        end,
        QPointF(end.x() - head_len * math.cos(a1), end.y() + head_len * math.sin(a1)),
    )
    p.drawLine(
        end,
        QPointF(end.x() - head_len * math.cos(a2), end.y() + head_len * math.sin(a2)),
    )
    p.restore()


def apply_pixelate(img: QImage, center: QPoint, radius: int, px_size: int = 8):
    r = max(2, radius)
    rect = QRect(center.x() - r, center.y() - r, 2 * r, 2 * r).intersected(img.rect())
    if rect.isEmpty():
        return
    region = img.copy(rect)
    small = region.scaled(
        max(1, region.width() // px_size),
        max(1, region.height() // px_size),
        Qt.IgnoreAspectRatio,
        Qt.FastTransformation,
    )
    pixelated = small.scaled(region.size(), Qt.IgnoreAspectRatio, Qt.FastTransformation)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
    painter.drawImage(rect.topLeft(), pixelated)
    painter.end()


def apply_gaussian_like_blur(img: QImage, center: QPoint, radius: int, kernel: int = 9):
    """Размытие круга радиуса radius средствами Qt (на C++, а не попиксельно в Python).

    Участок уменьшается в factor раз со сглаживанием (усреднение блоков) и
    растягивается обратно билинейно. По силе это примерно прежний двойной
    box-blur с ядром kernel, но работает за миллисекунды, а не секунды.
    """
    r = max(2, radius)
    rect = QRect(center.x() - r, center.y() - r, 2 * r, 2 * r).intersected(img.rect())
    if rect.isEmpty():
        return
    sub = img.copy(rect)
    factor = max(3, (kernel * 2) // 3)
    small = sub.scaled(
        max(1, sub.width() // factor),
        max(1, sub.height() // factor),
        Qt.IgnoreAspectRatio,
        Qt.SmoothTransformation,
    )
    blurred = small.scaled(sub.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    painter = QPainter(img)
    try:
        painter.setClipRect(rect, Qt.ReplaceClip)
        path = QPainterPath()
        path.addEllipse(QPointF(center), r, r)
        painter.setClipPath(path, Qt.IntersectClip)
        painter.drawImage(rect.topLeft(), blurred)
    finally:
        painter.end()


def flood_fill_into(
    sample: QImage, target: QImage, seed: QPoint, new_color: QColor, tol: int = 30
):
    """Заливка «ведром»: область похожих на seed пикселей sample закрашивается в target.

    Похожесть — как раньше: |ΔR|+|ΔG|+|ΔB| ≤ 3·tol (альфа не учитывается),
    пиксели target заменяются цветом new_color (вместе с его альфой).
    Работает по сырым 32-битным пикселям вместо QColor на каждую точку и
    пишет целые отрезки строк за раз — в разы быстрее на больших областях.
    """
    w, h = sample.width(), sample.height()
    sx, sy = seed.x(), seed.y()
    if not (0 <= sx < w and 0 <= sy < h):
        return
    if target.size() != sample.size():
        return
    if sample.format() != QImage.Format_ARGB32:
        sample = sample.convertToFormat(QImage.Format_ARGB32)
    if target.format() != QImage.Format_ARGB32:
        # Редактор держит слои в ARGB32; писать в другой формат напрямую нельзя.
        log.warning("flood_fill_into: unsupported target format %s", target.format())
        return

    src = memoryview(sample.constBits()).cast("I")       # 0xAARRGGBB, строка = w пикселей
    dst = memoryview(target.bits()).cast("I")
    v0 = src[sy * w + sx]
    r0, g0, b0 = (v0 >> 16) & 255, (v0 >> 8) & 255, v0 & 255
    lim = tol * 3
    fill_value = int(new_color.rgba()) & 0xFFFFFFFF
    visited = bytearray(w * h)

    def similar(i: int) -> bool:
        v = src[i]
        return (abs(((v >> 16) & 255) - r0) + abs(((v >> 8) & 255) - g0) + abs((v & 255) - b0)) <= lim

    stack = [(sx, sy)]
    while stack:
        x, y = stack.pop()
        row = y * w
        if visited[row + x] or not similar(row + x):
            continue
        xl = x
        while xl > 0 and not visited[row + xl - 1] and similar(row + xl - 1):
            xl -= 1
        xr = x
        while xr < w - 1 and not visited[row + xr + 1] and similar(row + xr + 1):
            xr += 1
        n = xr - xl + 1
        visited[row + xl:row + xr + 1] = b"\x01" * n
        dst[row + xl:row + xr + 1] = array("I", [fill_value]) * n
        for ny in (y - 1, y + 1):
            if not (0 <= ny < h):
                continue
            nrow = ny * w
            xi = xl
            while xi <= xr:
                if not visited[nrow + xi] and similar(nrow + xi):
                    stack.append((xi, ny))
                    while xi <= xr and not visited[nrow + xi] and similar(nrow + xi):
                        xi += 1
                xi += 1


def center_on_screen(win: QWidget, prefer_cursor: bool = True):
    screen = QGuiApplication.screenAt(QCursor.pos()) if prefer_cursor else None
    if screen is None:
        screen = win.screen() or QGuiApplication.primaryScreen()

    geo = screen.availableGeometry()
    fg = win.frameGeometry()
    if fg.isEmpty():
        win.ensurePolished()
        win.adjustSize()
        fg = win.frameGeometry()

    fg.moveCenter(geo.center())
    win.move(fg.topLeft())

class SelectionOverlay:
    """Затемнённый слой выбора области поверх всех мониторов.

    frozen=True (скриншот): экраны снимаются ДО показа слоя, слой показывает
    этот «замороженный» кадр, а картинка вырезается из него же. Так в снимок не
    попадает затемнение, а открытые меню и подсказки остаются на кадре.
    frozen=False: живой рабочий стол под слоем.

    switchable=True: сверху экрана панель «Скриншот | Запись экрана»; режим
    переключается кликом по ней или клавишей Tab. В режиме записи под слоем
    живой рабочий стол, выбранный режим — в атрибуте mode ("shot" / "record").

    ЛКМ — выделить, ПКМ или Esc — отмена. Клик без перетаскивания (в режиме
    frozen или switchable) берёт весь монитор под курсором.
    """

    _DIM = QColor(0, 0, 0, 150)
    # Открытый сейчас слой. Хук клавиатуры шлёт ему Esc/Tab напрямую: окно слоя
    # часто не получает фокус (Windows не отдаёт передний план), и обычные
    # keyPressEvent до него не доходят.
    active: Optional["SelectionOverlay"] = None
    MODE_SHOT = "shot"
    MODE_RECORD = "record"
    MODE_OCR = "ocr"
    _MODES = (MODE_SHOT, MODE_RECORD, MODE_OCR)
    _MODE_LABELS = {MODE_SHOT: "📷  Скриншот", MODE_RECORD: "⏺  Запись экрана", MODE_OCR: "🔤  Текст"}

    class _Pane(QWidget):
        def __init__(self, mgr: "SelectionOverlay", screen, frozen: Optional[QPixmap]):
            super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setMouseTracking(True)
            self.setCursor(Qt.CrossCursor)
            self.setFocusPolicy(Qt.StrongFocus)
            self.mgr = mgr
            self.scr = screen
            self._frozen = frozen
            self.has_bar = False
            self._bar_font = QFont(self.font())
            self._bar_font.setPointSize(max(10, self._bar_font.pointSize() + 1))
            self._bar_font.setBold(True)
            self._hint_font = QFont(self.font())
            self.setGeometry(screen.geometry())

        def showPane(self):
            self.show()
            self.raise_()

        # ── панель режимов ──
        def _bar_layout(self) -> Tuple[QRect, List[Tuple[str, QRect]], QRect]:
            """(вся панель, [(режим, кнопка)…], строка подсказки)."""
            fm = QFontMetrics(self._bar_font)
            fm_hint = QFontMetrics(self._hint_font)
            pad_x, pad_y, gap, margin = 16, 7, 4, 6
            labels = SelectionOverlay._MODE_LABELS
            modes = SelectionOverlay._MODES
            widths = [fm.horizontalAdvance(labels[m]) + 2 * pad_x for m in modes]
            h_btn = fm.height() + 2 * pad_y
            hint = self.mgr.bar_hint()
            buttons_w = sum(widths) + gap * (len(widths) - 1)
            inner_w = max(buttons_w, fm_hint.horizontalAdvance(hint) + 8)
            bar = QRect(0, 0, inner_w + 2 * margin, h_btn + fm_hint.height() + 3 * margin)
            bar.moveTopLeft(QPoint((self.width() - bar.width()) // 2, 16))
            x = bar.left() + margin + (inner_w - buttons_w) // 2
            buttons: List[Tuple[str, QRect]] = []
            for m, w in zip(modes, widths):
                buttons.append((m, QRect(x, bar.top() + margin, w, h_btn)))
                x += w + gap
            top = buttons[0][1].bottom() + margin // 2 + 1
            hint_rect = QRect(bar.left() + margin, top, inner_w, fm_hint.height() + 2)
            return bar, buttons, hint_rect

        def _bar_visible(self) -> bool:
            return self.has_bar and self.mgr.switchable and self.mgr._origin_g is None

        def _paint_bar(self, p: QPainter) -> None:
            bar, buttons, hint_rect = self._bar_layout()
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(32, 33, 36, 235))
            p.drawRoundedRect(bar, 10, 10)
            p.setFont(self._bar_font)
            for mode, rect in buttons:
                active = self.mgr.mode == mode
                enabled = self.mgr.mode_enabled(mode)
                bg = QColor(26, 115, 232) if active else QColor(60, 64, 67)
                if not enabled:
                    bg = QColor(48, 50, 53)
                p.setPen(Qt.NoPen)
                p.setBrush(bg)
                p.drawRoundedRect(rect, 7, 7)
                p.setPen(QColor(255, 255, 255) if enabled else QColor(130, 130, 130))
                p.drawText(rect, Qt.AlignCenter, SelectionOverlay._MODE_LABELS[mode])
            p.setFont(self._hint_font)
            p.setPen(QColor(200, 200, 200))
            p.drawText(hint_rect, Qt.AlignCenter, self.mgr.bar_hint())
            p.setRenderHint(QPainter.Antialiasing, False)

        def _bar_hit(self, pos: QPoint) -> Optional[str]:
            """Режим — клик по кнопке, 'bar' — по панели, None — мимо."""
            if not self._bar_visible():
                return None
            bar, buttons, _hint = self._bar_layout()
            for mode, rect in buttons:
                if rect.contains(pos):
                    return mode
            return "bar" if bar.contains(pos) else None

        # ── события ──
        def event(self, e):
            # Tab перехватываем до обработки фокуса: он переключает режим.
            if e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Tab, Qt.Key_Backtab):
                self.mgr.toggle_mode()
                return True
            return super().event(e)

        def mousePressEvent(self, e: QMouseEvent):
            if e.button() == Qt.LeftButton:
                hit = self._bar_hit(e.position().toPoint())
                if hit is not None:
                    if hit in SelectionOverlay._MODES:
                        self.mgr.set_mode(hit)
                    return
                g = e.globalPosition().toPoint()
                self.mgr._on_press(g)
                for p in self.mgr._panes:
                    p.update()
            elif e.button() == Qt.RightButton:
                self.mgr._cancel()

        def mouseMoveEvent(self, e: QMouseEvent):
            if self.mgr._origin_g is not None:
                g = e.globalPosition().toPoint()
                self.mgr._on_move(g)
                for p in self.mgr._panes:
                    p.update()
            elif self.has_bar:
                over_bar = self._bar_hit(e.position().toPoint()) is not None
                self.setCursor(Qt.ArrowCursor if over_bar else Qt.CrossCursor)

        def mouseReleaseEvent(self, e: QMouseEvent):
            if e.button() == Qt.LeftButton and self.mgr._origin_g is not None:
                g = e.globalPosition().toPoint()
                self.mgr._on_release(g)

        def keyPressEvent(self, e):
            if e.key() == Qt.Key_Escape:
                self.mgr._cancel()

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, False)
            r_global: Optional[QRect] = None
            r_local = QRect()
            inter = QRect()
            if self.mgr._origin_g is not None and self.mgr._current_g is not None:
                r_global = QRect(self.mgr._origin_g, self.mgr._current_g).normalized()
                r_local = r_global.translated(-self.geometry().topLeft())
                inter = r_local.intersected(self.rect())

            if self._frozen is not None and self.mgr.mode != SelectionOverlay.MODE_RECORD:
                p.drawPixmap(self.rect(), self._frozen)
                dim = QRegion(self.rect())
                if not inter.isEmpty():
                    dim = dim.subtracted(QRegion(inter))
                p.setClipRegion(dim)
                p.fillRect(self.rect(), SelectionOverlay._DIM)
                p.setClipping(False)
            else:
                # живой рабочий стол: полупрозрачное затемнение, выделение — «дырка»
                p.setCompositionMode(QPainter.CompositionMode_Source)
                p.fillRect(self.rect(), SelectionOverlay._DIM)
                if not inter.isEmpty():
                    p.fillRect(inter, Qt.transparent)
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)

            if r_global is not None and not inter.isEmpty():
                record = self.mgr.mode == SelectionOverlay.MODE_RECORD
                # направляющие от краёв выделения до краёв экрана
                p.setPen(QPen(QColor(255, 255, 255, 80), 1, Qt.DashLine))
                sr = self.rect()
                p.drawLine(r_local.left(), sr.top(), r_local.left(), sr.bottom())
                p.drawLine(r_local.right(), sr.top(), r_local.right(), sr.bottom())
                p.drawLine(sr.left(), r_local.top(), sr.right(), r_local.top())
                p.drawLine(sr.left(), r_local.bottom(), sr.right(), r_local.bottom())
                p.setPen(QPen(QColor(0, 0, 0, 200), 1))  # 1px, снаружи
                p.drawRect(r_local.adjusted(-1, -1, 1, 1))
                ocr = self.mgr.mode == SelectionOverlay.MODE_OCR
                frame = QColor(234, 67, 53) if record else (QColor(52, 168, 83) if ocr else QColor(255, 255, 255))
                p.setPen(QPen(frame, 1))
                p.drawRect(r_local)
                p.setBrush(Qt.NoBrush)
                info = f"{r_global.width()} x {r_global.height()}"
                if record:
                    info = "⏺ " + info
                elif ocr:
                    info = "🔤 " + info
                metrics = p.fontMetrics()
                label_h = metrics.height() + 8
                label_y = r_local.top() - label_h
                if label_y < sr.top():  # у верхнего края экрана — подпись внутрь выделения
                    label_y = r_local.top() + 2
                rect = QRect(r_local.left(), label_y, metrics.horizontalAdvance(info) + 12, label_h)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 200))
                p.drawRect(rect)
                p.setPen(QColor(255, 255, 255))
                p.drawText(rect.adjusted(6, 4, -6, -4), Qt.AlignLeft | Qt.AlignVCenter, info)

            if self._bar_visible():
                self._paint_bar(p)
            p.end()

    def __init__(
        self,
        frozen: bool = False,
        switchable: bool = False,
        mode: str = MODE_SHOT,
        record_available: bool = True,
        record_unavailable_reason: str = "",
    ):
        self._frozen = frozen
        self.switchable = switchable
        self.record_available = record_available
        self._record_unavailable_reason = record_unavailable_reason
        self.mode = mode if self.mode_enabled(mode) else self.MODE_SHOT
        self._shots: List[Tuple[QRect, QPixmap]] = []
        self._panes: List[SelectionOverlay._Pane] = []
        bar_screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        for screen in QGuiApplication.screens():
            shot: Optional[QPixmap] = None
            if frozen:
                pm = screen.grabWindow(0)
                if not pm.isNull():
                    shot = pm
                    self._shots.append((QRect(screen.geometry()), pm))
            pane = SelectionOverlay._Pane(self, screen, shot)
            pane.has_bar = screen is bar_screen
            self._panes.append(pane)
        if self._panes and not any(p.has_bar for p in self._panes):
            self._panes[0].has_bar = True
        self._origin_g: Optional[QPoint] = None
        self._current_g: Optional[QPoint] = None
        self.selection_made = lambda rect: None

    def bar_hint(self) -> str:
        if not self.record_available:
            reason = self._record_unavailable_reason or "запись недоступна"
            return f"{reason} · ПКМ / Esc — отмена"
        return "Tab — сменить режим · ПКМ / Esc — отмена"

    def mode_enabled(self, mode: str) -> bool:
        if mode == self.MODE_RECORD:
            return self.record_available
        if mode == self.MODE_OCR:
            return sys.platform.startswith("win")
        return mode == self.MODE_SHOT

    def set_mode(self, mode: str) -> None:
        if not self.mode_enabled(mode):
            return
        if mode != self.mode:
            self.mode = mode
            for p in self._panes:
                p.update()

    def toggle_mode(self) -> None:
        if self.switchable and self._origin_g is None:
            modes = self._MODES
            i = modes.index(self.mode) if self.mode in modes else 0
            for step in range(1, len(modes) + 1):
                candidate = modes[(i + step) % len(modes)]
                if self.mode_enabled(candidate):
                    self.set_mode(candidate)
                    return

    def shots(self) -> List[Tuple[QRect, QPixmap]]:
        """Замороженные кадры экранов: (логическая геометрия экрана, снимок)."""
        return list(self._shots)

    def begin(self):
        self._origin_g = self._current_g = None
        SelectionOverlay.active = self
        bar_pane = None
        for p in self._panes:
            p.showPane()
            if p.has_bar:
                bar_pane = p
        # Фокус (для Tab и Esc) — окну на экране под курсором.
        for p in ([bar_pane] if bar_pane is not None else self._panes[-1:]):
            p.activateWindow()
            p.setFocus(Qt.ActiveWindowFocusReason)

    def isVisible(self) -> bool:
        return any(p.isVisible() for p in self._panes)

    def hide(self):
        if SelectionOverlay.active is self:
            SelectionOverlay.active = None
        for p in self._panes:
            p.hide()

    def dispose(self) -> None:
        """Удаляет окна слоя, чтобы они не копились в памяти после каждого снимка."""
        if SelectionOverlay.active is self:
            SelectionOverlay.active = None
        for p in self._panes:
            p.hide()
            p.deleteLater()
        self._panes = []

    def _on_press(self, g: QPoint):
        self._origin_g = g
        self._current_g = g

    def _on_move(self, g: QPoint):
        self._current_g = g

    def _on_release(self, g: QPoint):
        self._current_g = g
        rect = QRect(self._origin_g, self._current_g).normalized()
        if (self._frozen or self.switchable) and rect.width() < 4 and rect.height() < 4:
            screen = QGuiApplication.screenAt(g)
            if screen is not None:
                rect = QRect(screen.geometry())  # клик без выделения — весь монитор
        self._origin_g = self._current_g = None
        self.hide()
        self.selection_made(rect)

    def _cancel(self):
        self._origin_g = self._current_g = None
        self.hide()
        self.selection_made(None)


class Tool(Enum):
    PAN = auto()
    PEN = auto()
    HIGHLIGHT = auto()
    RECT = auto()
    ARROW = auto()
    ELLIPSE = auto()
    TEXT = auto()
    BLUR = auto()
    PIXELATE = auto()
    CROP = auto()
    REDACT = auto()
    STEP = auto()
    FILL = auto()
    ERASER = auto()


class StickerItem(QGraphicsItem):
    HANDLE = 7

    def __init__(self, pix: QPixmap, max_size: QSize):
        super().__init__()
        self.setFlags(
            QGraphicsItem.ItemIsMovable
           | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
            | QGraphicsItem.ItemIsFocusable
        )
        self.setAcceptHoverEvents(True)
        self._pix = pix
        w, h = pix.width(), pix.height()
        scale = min(1.0, min(max_size.width() / max(1, w), max_size.height() / max(1, h)))
        self._rect = QRectF(0, 0, max(1, w * scale), max(1, h * scale))
        self._hover_handle = None
        self._resize_handle = None
        self._start_rect = QRectF()
        self._start_pos = QPointF()
        self._show_handles: bool = False
        self.setZValue(2)

    def boundingRect(self) -> QRectF:
        hs = self.HANDLE
        return self._rect.adjusted(-hs, -hs, hs, hs)

    def _handles(self):
        r = self._rect
        hs = self.HANDLE
        return {
            "tl": QRectF(r.left()-hs,  r.top()-hs,    2*hs, 2*hs),
            "tr": QRectF(r.right()-hs, r.top()-hs,    2*hs, 2*hs),
            "bl": QRectF(r.left()-hs,  r.bottom()-hs, 2*hs, 2*hs),
            "br": QRectF(r.right()-hs, r.bottom()-hs, 2*hs, 2*hs),
            "l":  QRectF(r.left()-hs,  r.center().y()-hs, 2*hs, 2*hs),
            "r":  QRectF(r.right()-hs, r.center().y()-hs, 2*hs, 2*hs),
            "t":  QRectF(r.center().x()-hs, r.top()-hs,    2*hs, 2*hs),
            "b":  QRectF(r.center().x()-hs, r.bottom()-hs, 2*hs, 2*hs),
        }

    def _cursor_for(self, h):
        return {
            "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
            "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
            "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
            "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor
        }.get(h, Qt.ArrowCursor)

    def paint(self, p: QPainter, opt, widget=None):
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(self._rect, self._pix, self._pix.rect())
        if self._show_handles:
            p.setPen(QPen(QColor(0, 0, 0, 160), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self._rect)
            p.setPen(QPen(QColor(255, 255, 255), 1))
            for rc in self._handles().values():
                p.setBrush(QColor(0, 0, 0))
                p.drawRect(rc)

    def hoverMoveEvent(self, e):
        pos = e.pos()
        self._hover_handle = None
        if self._show_handles:
            for name, rc in self._handles().items():
                if rc.contains(pos):
                    self._hover_handle = name
                    break
            self.setCursor(self._cursor_for(self._hover_handle))
        else:
            self.setCursor(Qt.ArrowCursor)
        super().hoverMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._show_handles:
            for name, rc in self._handles().items():
                if rc.contains(e.pos()):
                    self._resize_handle = name
                    self._start_rect = QRectF(self._rect)
                    self._start_pos = e.scenePos()
                    e.accept()
                    return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._resize_handle:
            delta = e.scenePos() - self._start_pos
            r = QRectF(self._start_rect)
            if "l" in self._resize_handle: r.setLeft(r.left() + delta.x())
            if "r" in self._resize_handle: r.setRight(r.right() + delta.x())
            if "t" in self._resize_handle: r.setTop(r.top() + delta.y())
            if "b" in self._resize_handle: r.setBottom(r.bottom() + delta.y())
            if QApplication.keyboardModifiers() & Qt.ShiftModifier:
                ar = self._pix.width() / max(1.0, self._pix.height())
                if r.width() / max(1.0, r.height()) > ar:
                    r.setWidth(max(1.0, r.height() * ar))
                else:
                    r.setHeight(max(1.0, r.width() / ar))
            if r.width() < 8:  r.setWidth(8)
            if r.height() < 8: r.setHeight(8)
            self.prepareGeometryChange()
            self._rect = r.normalized()
            self.update()
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._resize_handle and e.button() == Qt.LeftButton:
            self._resize_handle = None
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def rasterize_to(self, painter: QPainter):
        # _rect может начинаться не в (0,0) — после растяжения за левый или
        # верхний край. Раньше это смещение терялось и стикер «прыгал».
        target = self.mapRectToScene(self._rect)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(target, self._pix, QRectF(self._pix.rect()))


class _HandleMixin:
    HANDLE = 7

    def _cursor_for(self, h: str | None):
        return {
            "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
            "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
            "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
            "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor
        }.get(h, Qt.ArrowCursor)

    def _handles_for_rect(self, r: QRectF):
        hs = self.HANDLE
        return {
            "tl": QRectF(r.left()-hs,  r.top()-hs,    2*hs, 2*hs),
            "tr": QRectF(r.right()-hs, r.top()-hs,    2*hs, 2*hs),
            "bl": QRectF(r.left()-hs,  r.bottom()-hs, 2*hs, 2*hs),
            "br": QRectF(r.right()-hs, r.bottom()-hs, 2*hs, 2*hs),
            "l":  QRectF(r.left()-hs,  r.center().y()-hs, 2*hs, 2*hs),
            "r":  QRectF(r.right()-hs, r.center().y()-hs, 2*hs, 2*hs),
            "t":  QRectF(r.center().x()-hs, r.top()-hs,    2*hs, 2*hs),
            "b":  QRectF(r.center().x()-hs, r.bottom()-hs, 2*hs, 2*hs),
        }


class ResizableRectItem(QGraphicsItem, _HandleMixin):
    def __init__(self, rect: QRectF, pen: QPen, brush):
        super().__init__()
        self._rect = QRectF(rect).normalized()
        self._pen = QPen(pen)
        self._brush = brush
        self._hover_handle: str | None = None
        self._resize_handle: str | None = None
        self._start_rect = QRectF()
        self._start_pos = QPointF()
        self._show_handles: bool = False
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
            | QGraphicsItem.ItemIsFocusable
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(2)

    def boundingRect(self) -> QRectF:
        hs = self.HANDLE
        w = max(1.0, float(self._pen.widthF()))
        return self._rect.adjusted(-hs - w, -hs - w, hs + w, hs + w)

    def rasterize_to(self, painter: QPainter):
        tl = self.mapToScene(self._rect.topLeft())
        br = self.mapToScene(self._rect.bottomRight())
        target = QRectF(tl, br).normalized()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(self._pen)
        painter.setBrush(self._brush)
        painter.drawRect(target)

    def paint(self, p: QPainter, opt, widget=None):
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(self._pen)
        p.setBrush(self._brush)
        p.drawRect(self._rect)
        if self._show_handles:
            p.setPen(QPen(QColor(0, 0, 0, 160), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self._rect)
            p.setPen(QPen(QColor(255, 255, 255), 1))
            for rc in self._handles_for_rect(self._rect).values():
                p.setBrush(QColor(0, 0, 0))
                p.drawRect(rc)

    def hoverMoveEvent(self, e):
        if self._show_handles:
            self._hover_handle = None
            for name, rc in self._handles_for_rect(self._rect).items():
                if rc.contains(e.pos()):
                    self._hover_handle = name
                    break
            self.setCursor(self._cursor_for(self._hover_handle))
        else:
            self._hover_handle = None
            self.setCursor(Qt.ArrowCursor)
        super().hoverMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            for name, rc in self._handles_for_rect(self._rect).items():
                if rc.contains(e.pos()):
                    self._resize_handle = name
                    self._start_rect = QRectF(self._rect)
                    self._start_pos = e.scenePos()
                    e.accept()
                    return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._resize_handle:
            delta = e.scenePos() - self._start_pos
            r = QRectF(self._start_rect)
            if "l" in self._resize_handle:
                r.setLeft(r.left() + delta.x())
            if "r" in self._resize_handle:
                r.setRight(r.right() + delta.x())
            if "t" in self._resize_handle:
                r.setTop(r.top() + delta.y())
            if "b" in self._resize_handle:
                r.setBottom(r.bottom() + delta.y())

            if QApplication.keyboardModifiers() & Qt.ShiftModifier:
                side = max(1.0, min(abs(r.width()), abs(r.height())))
                sign_w = 1.0 if r.width() >= 0 else -1.0
                sign_h = 1.0 if r.height() >= 0 else -1.0
                r.setWidth(side * sign_w)
                r.setHeight(side * sign_h)

            if abs(r.width()) < 8:
                r.setWidth(8 if r.width() >= 0 else -8)
            if abs(r.height()) < 8:
                r.setHeight(8 if r.height() >= 0 else -8)

            self.prepareGeometryChange()
            self._rect = r.normalized()
            self.update()
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._resize_handle and e.button() == Qt.LeftButton:
            self._resize_handle = None
            e.accept()
            return
        super().mouseReleaseEvent(e)


class ResizableEllipseItem(ResizableRectItem):
    def paint(self, p: QPainter, opt, widget=None):
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(self._pen)
        p.setBrush(self._brush)
        p.drawEllipse(self._rect)
        if self._show_handles:
            p.setPen(QPen(QColor(0, 0, 0, 160), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(self._rect)
            p.setPen(QPen(QColor(255, 255, 255), 1))
            for rc in self._handles_for_rect(self._rect).values():
                p.setBrush(QColor(0, 0, 0))
                p.drawRect(rc)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addEllipse(self._rect)
        return path

    def rasterize_to(self, painter: QPainter):
        tl = self.mapToScene(self._rect.topLeft())
        br = self.mapToScene(self._rect.bottomRight())
        target = QRectF(tl, br).normalized()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(self._pen)
        painter.setBrush(self._brush)
        painter.drawEllipse(target)


class ResizableArrowItem(QGraphicsItem, _HandleMixin):
    def __init__(self, a: QPointF, b: QPointF, color: QColor, width: int):
        super().__init__()
        self._a = QPointF(a)
        self._b = QPointF(b)
        self._color = QColor(color)
        self._width = max(1, int(width))
        self._hover_handle: str | None = None
        self._resize_handle: str | None = None
        self._start_a = QPointF()
        self._start_b = QPointF()
        self._start_pos = QPointF()
        self._show_handles: bool = False
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
            | QGraphicsItem.ItemIsFocusable
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(2)

    def rasterize_to(self, painter: QPainter):
        a = self.mapToScene(self._a)
        b = self.mapToScene(self._b)
        painter.setRenderHint(QPainter.Antialiasing, True)
        draw_arrow(painter, a, b, self._color, self._width)

    def _line_rect(self) -> QRectF:
        return QRectF(self._a, self._b).normalized()

    def boundingRect(self) -> QRectF:
        r = self._line_rect()
        pad = float(self._width * 3 + self.HANDLE + 2)
        return r.adjusted(-pad, -pad, pad, pad)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.moveTo(self._a)
        path.lineTo(self._b)

        stroker = QPainterPathStroker()
        stroker.setWidth(max(6.0, float(self._width) + 6.0))
        stroker.setCapStyle(Qt.RoundCap)
        stroker.setJoinStyle(Qt.RoundJoin)
        return stroker.createStroke(path)

    def _handles(self):
        hs = self.HANDLE
        return {
            "a": QRectF(self._a.x()-hs, self._a.y()-hs, 2*hs, 2*hs),
            "b": QRectF(self._b.x()-hs, self._b.y()-hs, 2*hs, 2*hs),
        }

    def paint(self, p: QPainter, opt, widget=None):
        p.setRenderHint(QPainter.Antialiasing, True)
        draw_arrow(p, self._a, self._b, self._color, self._width)
        if self._show_handles:
            p.setPen(QPen(QColor(255, 255, 255), 1))
            for rc in self._handles().values():
                p.setBrush(QColor(0, 0, 0))
                p.drawRect(rc)

    def hoverMoveEvent(self, e):
        if self._show_handles:
            self._hover_handle = None
            for name, rc in self._handles().items():
                if rc.contains(e.pos()):
                    self._hover_handle = name
                    break
            self.setCursor(Qt.SizeAllCursor if self._hover_handle is None else Qt.CrossCursor)
        else:
            self._hover_handle = None
            self.setCursor(Qt.ArrowCursor)
        super().hoverMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            for name, rc in self._handles().items():
                if rc.contains(e.pos()):
                    self._resize_handle = name
                    self._start_a = QPointF(self._a)
                    self._start_b = QPointF(self._b)
                    self._start_pos = e.scenePos()
                    e.accept()
                    return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._resize_handle:
            delta = e.scenePos() - self._start_pos
            self.prepareGeometryChange()
            if self._resize_handle == "a":
                self._a = self._start_a + delta
                self._b = QPointF(self._start_b)
            else:
                self._b = self._start_b + delta
                self._a = QPointF(self._start_a)
            self.update()
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._resize_handle and e.button() == Qt.LeftButton:
            self._resize_handle = None
            e.accept()
            return
        super().mouseReleaseEvent(e)


class _CompositeItem(QGraphicsItem):
    """Готовая картинка «фон + слой рисования» в виде QPixmap-кэша.

    Раньше после каждого движения мыши пером вся картинка заново собиралась
    из двух слоёв и целиком конвертировалась в QPixmap — на 4K-скриншоте это
    десятки мегабайт на каждое движение. Теперь пересобирается только
    изменившийся прямоугольник, а при перерисовке выводится только видимая
    часть.
    """

    def __init__(self):
        super().__init__()
        self._pm = QPixmap()
        self.setFlag(QGraphicsItem.ItemUsesExtendedStyleOption, True)

    def size(self) -> QSize:
        return self._pm.size()

    def rebuild(self, bg: QImage, ov: QImage) -> None:
        out = QImage(bg.size(), QImage.Format_ARGB32_Premultiplied)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.drawImage(0, 0, bg)
        p.drawImage(0, 0, ov)
        p.end()
        if out.size() != self._pm.size():
            self.prepareGeometryChange()
        self._pm = QPixmap.fromImage(out)
        self.update()

    def refresh_region(self, bg: QImage, ov: QImage, rect: QRect) -> None:
        r = QRect(rect).intersected(QRect(QPoint(0, 0), self._pm.size()))
        if r.isEmpty():
            return
        p = QPainter(self._pm)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(r, Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.drawImage(r, bg, r)
        p.drawImage(r, ov, r)
        p.end()
        self.update(QRectF(r))

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._pm.width(), self._pm.height())

    def paint(self, p: QPainter, opt, widget=None):
        if self._pm.isNull():
            return
        full = QRect(0, 0, self._pm.width(), self._pm.height())
        r = opt.exposedRect.toAlignedRect().intersected(full)
        if r.isEmpty():
            r = full
        p.drawPixmap(r, self._pm, r)


class _ShapePreviewItem(QGraphicsItem):
    """Превью фигуры во время перетаскивания (прямоугольник, овал, стрелка, кадр обрезки).

    Раньше превью — это копия всей картинки с нарисованной фигурой,
    пересобиравшаяся на каждое движение мыши. Теперь рисуется только сама
    фигура, поверх всех объектов.
    """

    def __init__(self):
        super().__init__()
        self._draw: Optional[Callable[[QPainter], None]] = None
        self._rect = QRectF()
        self.setZValue(10)

    def set_shape(self, bounds: QRectF, draw: Callable[[QPainter], None]) -> None:
        self.prepareGeometryChange()
        self._rect = QRectF(bounds)
        self._draw = draw
        self.update()

    def clear(self) -> None:
        if self._draw is not None or not self._rect.isEmpty():
            self.prepareGeometryChange()
        self._draw = None
        self._rect = QRectF()

    def has_shape(self) -> bool:
        return self._draw is not None

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, p: QPainter, opt, widget=None):
        if self._draw is not None:
            p.setRenderHint(QPainter.Antialiasing, True)
            self._draw(p)


_UNDO_MAX_STEPS = 60
_UNDO_MAX_BYTES = 768 * 1024 * 1024
_STATE_SAVE_DELAY_MS = 400
_REDACT_COLOR = QColor(0, 0, 0, 255)  # непрозрачно: полупрозрачная заливка не скрывает текст


class CanvasView(QGraphicsView):
    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.setRenderHints(QPainter.Antialiasing)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.bg_img: QImage = _normalized_image(image)
        self.ov_img: QImage = QImage(self.bg_img.size(), QImage.Format_ARGB32)
        self.ov_img.fill(Qt.transparent)
        self.base_item = _CompositeItem()
        self.base_item.rebuild(self.bg_img, self.ov_img)
        self.preview_item = _ShapePreviewItem()
        self._scene.addItem(self.base_item)
        self._scene.addItem(self.preview_item)
        self.last_save_dir: str = ""
        self._state_timer = QTimer(self)
        self._state_timer.setSingleShot(True)
        self._state_timer.setInterval(_STATE_SAVE_DELAY_MS)
        self._state_timer.timeout.connect(self.flush_editor_state)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setMouseTracking(True)
        self.tool: Tool = Tool.PEN
        self.color: QColor = QColor(0, 0, 0)
        self.thickness: int = 4
        self.fill_enabled: bool = False
        self.fill_alpha: int = 80
        self.fill_color: QColor = QColor(0, 0, 0)
        self.fill_tolerance: int = 30
        self.step_counter: int = 1
        self._load_editor_state()
        self._drawing = False
        self._last_pos: Optional[QPoint] = None
        self._start_pos: Optional[QPoint] = None
        self.undo_stack: list[tuple[QImage, QImage, list[dict]]] = []
        self.redo_stack: list[tuple[QImage, QImage, list[dict]]] = []
        self._panning = False
        self._dragging_item: Optional[QGraphicsItem] = None
        self._drag_scene_start = QPointF()
        self._drag_item_start = QPointF()
        self._status_hook: Optional[Callable[[dict], None]] = None
        self._cursor_pos: Optional[QPoint] = None
        self._pan_start = QPoint()
        self._zoom = 1.0
        self._update_smoothing()
        self.update_scene_rect()
        self.stickers: List[StickerItem] = []
        self._dirty: bool = False
        self._dirty_hook: Optional[Callable[[bool], None]] = None
        self._scene_edit_pre: Optional[tuple[QImage, QImage, list[dict]]] = None
        self._scene_edit_items: list[tuple[QGraphicsItem, tuple]] = []

    def _load_editor_state(self) -> None:
        try:
            path = SCREENSHOT_STATE_PATH
            if not path.exists():
                return
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)

            tool_name = data.get("tool", None)
            if isinstance(tool_name, str) and hasattr(Tool, tool_name):
                self.tool = getattr(Tool, tool_name)

            line_rgba = data.get("line_rgba", None)
            if isinstance(line_rgba, int):
                self.color = QColor.fromRgba(int(line_rgba))

            thickness = data.get("thickness", None)
            if isinstance(thickness, int):
                self.thickness = max(1, min(200, int(thickness)))

            fill_enabled = data.get("fill_enabled", None)
            if isinstance(fill_enabled, bool):
                self.fill_enabled = bool(fill_enabled)

            fill_rgba = data.get("fill_rgba", None)
            if isinstance(fill_rgba, int):
                self.fill_color = QColor.fromRgba(int(fill_rgba))

            fill_alpha = data.get("fill_alpha", None)
            if isinstance(fill_alpha, int):
                self.fill_alpha = max(0, min(255, int(fill_alpha)))

            fill_tolerance = data.get("fill_tolerance", None)
            if isinstance(fill_tolerance, int):
                self.fill_tolerance = max(0, min(255, int(fill_tolerance)))

            last_dir = data.get("last_save_dir", None)
            if isinstance(last_dir, str) and last_dir and Path(last_dir).is_dir():
                self.last_save_dir = last_dir

        except Exception:
            log.debug("editor state load failed", exc_info=True)

    def focusOutEvent(self, e):
        if self._drawing:
            self._drawing = False
            self._last_pos = None

        if self._start_pos is not None:
            self._start_pos = None
            self.cancel_preview()

        if self._panning:
            self._panning = False

        if self._dragging_item is not None:
            self._commit_scene_edit_undo_if_changed()
            self._dragging_item = None

        super().focusOutEvent(e)

    def _item_state(self, it: QGraphicsItem) -> Optional[tuple]:
        if it in (self.base_item, self.preview_item):
            return None

        if isinstance(it, StickerItem):
            return (
                "sticker",
                float(it.pos().x()), float(it.pos().y()),
                float(it._rect.x()), float(it._rect.y()), float(it._rect.width()), float(it._rect.height()),
                float(it.zValue()),
            )

        if isinstance(it, ResizableEllipseItem):
            return (
                "ellipse",
                float(it.pos().x()), float(it.pos().y()),
                float(it._rect.x()), float(it._rect.y()), float(it._rect.width()), float(it._rect.height()),
                int(it._pen.color().rgba()), float(it._pen.widthF()),
                None if it._brush == Qt.NoBrush else int(QColor(it._brush).rgba()),
                float(it.zValue()),
            )

        if isinstance(it, ResizableRectItem):
            return (
                "rect",
                float(it.pos().x()), float(it.pos().y()),
                float(it._rect.x()), float(it._rect.y()), float(it._rect.width()), float(it._rect.height()),
                int(it._pen.color().rgba()), float(it._pen.widthF()),
                None if it._brush == Qt.NoBrush else int(QColor(it._brush).rgba()),
                float(it.zValue()),
            )

        if isinstance(it, ResizableArrowItem):
            return (
                "arrow",
                float(it.pos().x()), float(it.pos().y()),
                float(it._a.x()), float(it._a.y()),
                float(it._b.x()), float(it._b.y()),
                int(it._color.rgba()), int(it._width),
                float(it.zValue()),
            )

        return None


    def _active_shape_items(self) -> list:
        """Return items with visible handles (the user-selected shapes)."""
        return [it for it in self._resizable_items() if it._show_handles]

    def _begin_scene_edit_undo(self, target_item: Optional[QGraphicsItem]) -> None:
        if target_item is None or target_item in (self.base_item, self.preview_item):
            return
        st = self._item_state(target_item)
        if st is None:
            return
        self._scene_edit_pre = self._undo_entry()
        self._scene_edit_items = [(target_item, st)]


    def _commit_scene_edit_undo_if_changed(self) -> None:
        if self._scene_edit_pre is None:
            return

        changed = False
        for it, st0 in self._scene_edit_items:
            st1 = self._item_state(it)
            if st1 is None or st1 != st0:
                changed = True
                break

        if changed:
            self.undo_stack.append(self._scene_edit_pre)
            self.redo_stack.clear()
            self._set_dirty(True)
            self._trim_undo()

        self._scene_edit_pre = None
        self._scene_edit_items = []


    def _save_editor_state(self) -> None:
        """Сохраняет настройки инструментов с задержкой.

        Раньше файл переписывался на каждый шаг ползунка — десятки записей на
        диск за одно движение. Теперь — один раз после паузы (и при закрытии).
        """
        self._state_timer.start()

    def flush_editor_state(self) -> None:
        self._state_timer.stop()
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "tool": self.tool.name,
                "line_rgba": int(self.color.rgba()),
                "thickness": int(self.thickness),
                "fill_enabled": bool(self.fill_enabled),
                "fill_rgba": int(self.fill_color.rgba()),
                "fill_alpha": int(self.fill_alpha),
                "fill_tolerance": int(self.fill_tolerance),
                "last_save_dir": self.last_save_dir,
            }
            tmp = SCREENSHOT_STATE_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, SCREENSHOT_STATE_PATH)
        except Exception:
            log.debug("editor state save failed", exc_info=True)

    def show_original_size(self):
        self._zoom = 1.0
        self.setTransform(QTransform())
        self._update_smoothing()
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)

    def _snapshot_scene(self) -> list[dict]:
        out: list[dict] = []
        for it in self._scene.items():
            if it in (self.base_item, self.preview_item):
                continue

            if isinstance(it, StickerItem):
                out.append({
                    "type": "sticker",
                    "pos": (float(it.pos().x()), float(it.pos().y())),
                    "rect": (float(it._rect.x()), float(it._rect.y()), float(it._rect.width()), float(it._rect.height())),
                    "z": float(it.zValue()),
                    "pix": it._pix,
                })
                continue

            if isinstance(it, ResizableEllipseItem):
                out.append({
                    "type": "ellipse",
                    "pos": (float(it.pos().x()), float(it.pos().y())),
                    "rect": (float(it._rect.x()), float(it._rect.y()), float(it._rect.width()), float(it._rect.height())),
                    "pen": (it._pen.color().rgba(), float(it._pen.widthF())),
                    "brush": None if it._brush == Qt.NoBrush else QColor(it._brush).rgba(),
                    "z": float(it.zValue()),
                })
                continue

            if isinstance(it, ResizableRectItem):
                out.append({
                    "type": "rect",
                    "pos": (float(it.pos().x()), float(it.pos().y())),
                    "rect": (float(it._rect.x()), float(it._rect.y()), float(it._rect.width()), float(it._rect.height())),
                    "pen": (it._pen.color().rgba(), float(it._pen.widthF())),
                    "brush": None if it._brush == Qt.NoBrush else QColor(it._brush).rgba(),
                    "z": float(it.zValue()),
                })
                continue

            if isinstance(it, ResizableArrowItem):
                out.append({
                    "type": "arrow",
                    "pos": (float(it.pos().x()), float(it.pos().y())),
                    "a": (float(it._a.x()), float(it._a.y())),
                    "b": (float(it._b.x()), float(it._b.y())),
                    "color": it._color.rgba(),
                    "width": int(it._width),
                    "z": float(it.zValue()),
                })
                continue

        return out


    def _restore_scene(self, snap: list[dict]) -> None:
        for it in list(self._scene.items()):
            if it in (self.base_item, self.preview_item):
                continue
            self._scene.removeItem(it)

        self.stickers.clear()

        for d in snap:
            t = d.get("type")
            if t == "sticker":
                pix = d["pix"] if isinstance(d["pix"], QPixmap) else QPixmap.fromImage(d["pix"])
                item = StickerItem(pix, QSize(self.bg_img.width(), self.bg_img.height()))
                x, y, w, h = d["rect"]
                item._rect = QRectF(x, y, w, h)
                px, py = d["pos"]
                item.setPos(QPointF(px, py))
                item.setZValue(d.get("z", 2.0))
                self._scene.addItem(item)
                item.setFlag(QGraphicsItem.ItemIsMovable, self.tool == Tool.PAN)
                self.stickers.append(item)
                continue

            if t in ("rect", "ellipse"):
                pen_rgba, pen_w = d["pen"]
                pen = QPen(QColor.fromRgba(int(pen_rgba)), float(pen_w), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                brush_rgba = d.get("brush")
                brush = Qt.NoBrush if brush_rgba is None else QColor.fromRgba(int(brush_rgba))
                x, y, w, h = d["rect"]

                if t == "rect":
                    item = ResizableRectItem(QRectF(x, y, w, h), pen, brush)
                else:
                    item = ResizableEllipseItem(QRectF(x, y, w, h), pen, brush)

                px, py = d["pos"]
                item.setPos(QPointF(px, py))
                item.setZValue(d.get("z", 2.0))
                self._scene.addItem(item)
                item.setFlag(QGraphicsItem.ItemIsMovable, self.tool == Tool.PAN)
                continue

            if t == "arrow":
                ax, ay = d["a"]
                bx, by = d["b"]
                color = QColor.fromRgba(int(d["color"]))
                item = ResizableArrowItem(QPointF(ax, ay), QPointF(bx, by), color, int(d["width"]))
                px, py = d["pos"]
                item.setPos(QPointF(px, py))
                item.setZValue(d.get("z", 2.0))
                self._scene.addItem(item)
                item.setFlag(QGraphicsItem.ItemIsMovable, self.tool == Tool.PAN)
                continue

        self._scene.clearSelection()
        self.viewport().update()

    def fit_to_view(self):
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        t = self.transform()
        self._zoom = float(t.m11()) if abs(t.m11()) > 1e-9 else 1.0
        self._update_smoothing()

    def _update_smoothing(self):
        if abs(self._zoom - 1.0) < 1e-3:
            self.setRenderHints(QPainter.Antialiasing)
        else:
            self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

    def update_scene_rect(self):
        self._scene.setSceneRect(QRectF(QPointF(0, 0), self.bg_img.size()))

    def _refresh(self, dirty: Optional[QRect] = None):
        """Обновляет картинку на экране.

        dirty — изменившийся прямоугольник в пикселях картинки: пересобирается
        только он. Без dirty (или при смене размера) — полная пересборка.
        """
        if dirty is None or self.base_item.size() != self.bg_img.size():
            self.base_item.rebuild(self.bg_img, self.ov_img)
            self.viewport().update()
        else:
            self.base_item.refresh_region(self.bg_img, self.ov_img, dirty)

    def set_tool(self, t: Tool):
        self.tool = t
        self._save_editor_state()

        is_pan = (t == Tool.PAN)

        self.setInteractive(True)  # always interactive so items can receive resize events

        # Update per-item flags based on tool
        for item in self._resizable_items():
            item.setFlag(QGraphicsItem.ItemIsMovable, is_pan)
            if not is_pan and item._show_handles:
                item._show_handles = False
                item.update()

        self.setCursor(Qt.OpenHandCursor if is_pan else Qt.CrossCursor)

        if not is_pan:
            self._scene.clearSelection()

        if t == Tool.PAN:
            self.setDragMode(QGraphicsView.NoDrag)

        if t != Tool.ERASER:
            self._cursor_pos = None

        self.viewport().update()

    # ── handle-management helpers ─────────────────────────────────────────────

    def _resizable_items(self):
        """Return all resizable shape items in the scene."""
        return [
            it for it in self._scene.items()
            if isinstance(it, (ResizableRectItem, ResizableEllipseItem,
                                ResizableArrowItem, StickerItem))
        ]

    def _clear_all_handles(self):
        """Hide handles on every resizable item."""
        for it in self._resizable_items():
            if it._show_handles:
                it._show_handles = False
                it.update()

    def _hit_handle(self, scene_pos: QPointF):
        """Return (item, handle_name) if scene_pos is over a visible handle, else (None, None)."""
        for it in self._resizable_items():
            if not it._show_handles:
                continue
            local = it.mapFromScene(scene_pos)
            if isinstance(it, (StickerItem, ResizableArrowItem)):
                handles = it._handles()
            else:
                handles = it._handles_for_rect(it._rect)
            for name, rc in handles.items():
                if rc.contains(local):
                    return it, name
        return None, None

    def _hit_resizable_item(self, scene_pos: QPointF):
        """Return the best resizable item for a click at scene_pos.

        Priority:
        1. The currently active item (_show_handles=True) if the click is on it.
        2. The topmost item whose *border* the click is near (within BORDER_TOL px).
        3. The topmost item that merely contains the point (fill hit).
        """
        BORDER_TOL = 8.0
        candidates = [
            it for it in self._scene.items(scene_pos)
            if isinstance(it, (ResizableRectItem, ResizableEllipseItem,
                                ResizableArrowItem, StickerItem))
        ]
        if not candidates:
            return None

        # Priority 1: active item (handles visible) — keep using it if clicked anywhere on it
        for it in candidates:
            if it._show_handles:
                return it

        # Priority 2: border hit — click is within BORDER_TOL of the item's outline
        # Check in stacking order (candidates are already top-to-bottom)
        for it in candidates:
            local = it.mapFromScene(scene_pos)
            if isinstance(it, ResizableArrowItem):
                # Arrow: always a "border" (thin line)
                return it
            r = it._rect
            # Distance to each edge
            dist = min(
                abs(local.x() - r.left()),
                abs(local.x() - r.right()),
                abs(local.y() - r.top()),
                abs(local.y() - r.bottom()),
            )
            if dist <= BORDER_TOL:
                return it

        # Priority 3: plain fill hit — return topmost
        return candidates[0]

    def _hit_border_item(self, scene_pos: QPointF):
        """Return the topmost resizable item whose *border* (not fill) is at scene_pos.
        Returns None for pure fill hits — those should fall through to drawing."""
        BORDER_TOL = 8.0
        candidates = [
            it for it in self._scene.items(scene_pos)
            if isinstance(it, (ResizableRectItem, ResizableEllipseItem,
                                ResizableArrowItem, StickerItem))
        ]
        if not candidates:
            return None

        # Check each candidate for a true border hit (active or not)
        for it in candidates:
            local = it.mapFromScene(scene_pos)
            if isinstance(it, ResizableArrowItem):
                return it
            r = it._rect
            dist = min(
                abs(local.x() - r.left()),
                abs(local.x() - r.right()),
                abs(local.y() - r.top()),
                abs(local.y() - r.bottom()),
            )
            if dist <= BORDER_TOL:
                return it

        # Pure fill — caller decides what to do
        return None

    def set_color(self, c: QColor):
        self.color = c
        self._save_editor_state()

    def set_thickness(self, v: int):
        self.thickness = max(1, v)
        self._save_editor_state()
        if self.tool == Tool.ERASER:
            self.viewport().update()

    def set_fill_enabled(self, flag: bool):
        self.fill_enabled = bool(flag)
        self._save_editor_state()

    def set_fill_alpha(self, alpha: int):
        self.fill_alpha = max(0, min(255, int(alpha)))
        self._save_editor_state()

    def set_fill_color(self, c: QColor):
        self.fill_color = c
        self._save_editor_state()

    def set_fill_tolerance(self, v: int):
        self.fill_tolerance = max(0, min(255, int(v)))
        self._save_editor_state()

    def set_image(self, img: QImage):
        # Замену картинки можно отменить (Ctrl+Z), а фигуры и стикеры старой
        # картинки больше не остаются висеть поверх новой.
        self.push_undo()
        for it in self._resizable_items():
            self._scene.removeItem(it)
        self.stickers.clear()
        self.cancel_preview()
        self.bg_img = _normalized_image(img)
        self.ov_img = QImage(self.bg_img.size(), QImage.Format_ARGB32)
        self.ov_img.fill(Qt.transparent)
        self.update_scene_rect()
        self._refresh()
        self._zoom = 1.0
        self.setTransform(QTransform())
        self._update_smoothing()
        self.show_original_size()
        self._scene.clearSelection()
        self.mark_clean()

    def cancel_preview(self):
        self.preview_item.clear()

    def viewport_to_image(self, pos: QPoint) -> QPoint:
        sp = self.mapToScene(pos)
        return QPoint(int(sp.x()), int(sp.y()))

    def _erase_line(self, a: QPoint, b: QPoint, radius: int) -> QRect:
        """Стирает слой рисования по отрезку a→b кистью радиуса radius. Возвращает затронутую область."""
        r = max(1, radius)
        p = QPainter(self.ov_img)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        if a == b:
            p.setPen(Qt.NoPen)
            p.setBrush(Qt.black)
            p.drawEllipse(QRect(a - QPoint(r, r), QSize(2 * r, 2 * r)))
        else:
            p.setPen(QPen(Qt.black, 2 * r, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawLine(a, b)
        p.end()
        return QRect(a, b).normalized().adjusted(-r - 2, -r - 2, r + 2, r + 2)

    @staticmethod
    def _brush_rect(center: QPoint, radius: int) -> QRect:
        r = max(2, radius) + 2
        return QRect(center.x() - r, center.y() - r, 2 * r, 2 * r)

    def _stroke_pen(self) -> QPen:
        color = (
            self.color
            if self.tool == Tool.PEN
            else QColor(self.color.red(), self.color.green(), self.color.blue(), 120)
        )
        return QPen(color, self.thickness, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

    def _stroke_rect(self, a: QPoint, b: QPoint) -> QRect:
        pad = self.thickness // 2 + 3
        return QRect(a, b).normalized().adjusted(-pad, -pad, pad, pad)

    def _rect_from_points(
        self, a: QPoint, b: QPoint, constrain_square: bool = False
    ) -> QRect:
        r = QRect(a, b).normalized()
        if not constrain_square:
            return r
        side = min(r.width(), r.height())
        x = a.x() - side if b.x() < a.x() else a.x()
        y = a.y() - side if b.y() < a.y() else a.y()
        return QRect(QPoint(x, y), QSize(side, side)).normalized()

    def wheelEvent(self, e: QWheelEvent):
        if e.modifiers() & Qt.ControlModifier:
            delta = e.angleDelta().y()
            factor = 1.15 if delta > 0 else 1 / 1.15
            self._zoom = max(0.1, min(8.0, self._zoom * factor))
            self.setTransform(QTransform().scale(self._zoom, self._zoom))
            self._update_smoothing()
            self._emit_status()
            e.accept()
        else:
            super().wheelEvent(e)
            if self.tool == Tool.ERASER:
                self.viewport().update()

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(e.position().toPoint())

            if self.tool == Tool.PAN:
                # In PAN mode show handles for clicked item, then delegate to scene.
                hit_item, _ = self._hit_handle(scene_pos)
                if hit_item is None:
                    hit_item = self._hit_resizable_item(scene_pos)
                if hit_item is not None:
                    self._clear_all_handles()
                    hit_item._show_handles = True
                    hit_item.update()
                else:
                    self._clear_all_handles()
                super().mousePressEvent(e)
                if e.isAccepted():
                    target = self._scene.mouseGrabberItem()
                    if target is None:
                        target = self.itemAt(e.position().toPoint())
                    self._begin_scene_edit_undo(target)
                    return
                # Not accepted → fall through to panning below
            else:
                # Non-PAN tool: handle interaction takes priority over drawing.

                # Tools that draw new shapes — only intercept border/handle clicks,
                # never fill clicks (user wants to draw inside the shape).
                DRAWING_TOOLS = (
                    Tool.PEN, Tool.HIGHLIGHT, Tool.RECT, Tool.ELLIPSE,
                    Tool.ARROW, Tool.BLUR, Tool.PIXELATE, Tool.ERASER,
                    Tool.CROP, Tool.REDACT, Tool.STEP, Tool.FILL, Tool.TEXT,
                )
                is_drawing_tool = self.tool in DRAWING_TOOLS

                # 1. Clicking on a visible handle → start resize via scene routing
                hit_item, _ = self._hit_handle(scene_pos)
                if hit_item is not None:
                    self._begin_scene_edit_undo(hit_item)
                    super().mousePressEvent(e)
                    return

                # 2. Clicking on the border of any shape → select & start drag-move
                border_hit = self._hit_border_item(scene_pos)
                if border_hit is not None:
                    self._clear_all_handles()
                    border_hit._show_handles = True
                    border_hit.update()
                    self._begin_scene_edit_undo(border_hit)
                    self._dragging_item = border_hit
                    self._drag_scene_start = scene_pos
                    self._drag_item_start = border_hit.pos()
                    self.setCursor(Qt.SizeAllCursor)
                    e.accept()
                    return

                # 3. Clicking inside the fill:
                #    - drawing tool  → clear handles, proceed to draw (fall through)
                #    - PAN-intent    → select & drag
                fill_hit = self._hit_resizable_item(scene_pos)
                if fill_hit is not None:
                    if is_drawing_tool:
                        # Just clear other handles and let drawing proceed normally
                        self._clear_all_handles()
                        e.ignore()
                    else:
                        self._clear_all_handles()
                        fill_hit._show_handles = True
                        fill_hit.update()
                        self._begin_scene_edit_undo(fill_hit)
                        self._dragging_item = fill_hit
                        self._drag_scene_start = scene_pos
                        self._drag_item_start = fill_hit.pos()
                        self.setCursor(Qt.SizeAllCursor)
                        e.accept()
                        return
                else:
                    # 4. Empty space → clear handles and let normal drawing proceed
                    self._clear_all_handles()
                    e.ignore()
        if e.button() == Qt.MiddleButton or (
            self.tool == Tool.PAN and e.button() == Qt.LeftButton
        ):
            self._panning = True
            self._pan_start = e.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            e.accept()
            return

        if e.button() == Qt.LeftButton:
            img_pos = self.viewport_to_image(e.position().toPoint())
            self._cursor_pos = img_pos
            if self.tool == Tool.ERASER:
                self.viewport().update()
            if not QRect(QPoint(0, 0), self.bg_img.size()).contains(img_pos):
                return

            if self.tool in (
                Tool.PEN,
                Tool.HIGHLIGHT,
                Tool.BLUR,
                Tool.PIXELATE,
                Tool.ERASER,
            ):
                self.push_undo()
                self._drawing = True
                self._last_pos = img_pos
                if self.tool in (Tool.PEN, Tool.HIGHLIGHT):
                    p = QPainter(self.ov_img)
                    p.setPen(self._stroke_pen())
                    p.drawPoint(img_pos)
                    p.end()
                    self._refresh(self._stroke_rect(img_pos, img_pos))
                elif self.tool == Tool.BLUR:
                    apply_gaussian_like_blur(self.bg_img, img_pos, self.thickness * 2)
                    self._refresh(self._brush_rect(img_pos, self.thickness * 2))
                elif self.tool == Tool.PIXELATE:
                    apply_pixelate(self.bg_img, img_pos, self.thickness * 2, px_size=6)
                    self._refresh(self._brush_rect(img_pos, self.thickness * 2))
                elif self.tool == Tool.ERASER:
                    self._refresh(self._erase_line(img_pos, img_pos, self.thickness * 2))
            elif self.tool in (
                Tool.RECT,
                Tool.ELLIPSE,
                Tool.ARROW,
                Tool.CROP,
                Tool.REDACT,
            ):
                self._start_pos = img_pos
            elif self.tool == Tool.FILL:
                self.push_undo()
                fill_col = QColor(self.fill_color)
                fill_col.setAlpha(self.fill_alpha)
                sample = self.render_scene_to_image(hide_handles=True)
                target = self.bg_img if e.modifiers() & Qt.AltModifier else self.ov_img
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    flood_fill_into(sample, target, img_pos, fill_col, self.fill_tolerance)
                finally:
                    QApplication.restoreOverrideCursor()
                self._refresh()
                e.accept()
                return
            elif self.tool == Tool.TEXT:
                text, ok = QInputDialog.getText(self, "Текст", "Введите текст:")
                if ok and text:
                    self.push_undo()
                    p = QPainter(self.ov_img)
                    p.setRenderHint(QPainter.TextAntialiasing, True)
                    font = QFont()
                    font.setPointSize(max(8, int(self.thickness * 3)))
                    p.setFont(font)
                    p.setPen(QPen(self.color, 1))
                    p.drawText(QPointF(img_pos), text)
                    p.end()
                    self._refresh()
            elif self.tool == Tool.STEP:
                self.push_undo()
                radius = max(10, self.thickness * 4)
                r = QRect(
                    img_pos - QPoint(radius, radius), QSize(radius * 2, radius * 2)
                )
                p = QPainter(self.ov_img)
                p.setRenderHint(QPainter.Antialiasing, True)
                p.setPen(Qt.NoPen)
                p.setBrush(self.color)
                p.drawEllipse(r)
                font = QFont()
                font.setBold(True)
                font.setPointSize(max(8, int(radius * 0.9)))
                p.setFont(font)
                p.setPen(QPen(QColor(255, 255, 255), 1))
                text = str(self.step_counter)
                br = p.boundingRect(r, Qt.AlignCenter, text)
                p.drawText(br, Qt.AlignCenter, text)
                p.end()
                self.step_counter += 1
                self._refresh()
            e.accept()
            return

        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._dragging_item is not None:
            scene_pos = self.mapToScene(e.position().toPoint())
            delta = scene_pos - self._drag_scene_start
            self._dragging_item.setPos(self._drag_item_start + delta)
            e.accept()
            return
        if self._scene.mouseGrabberItem():
            super().mouseMoveEvent(e)
            return
        cur_pos = self.viewport_to_image(e.position().toPoint())
        self._cursor_pos = cur_pos
        self._emit_status()
        if self.tool == Tool.ERASER:
            self.viewport().update()

        if self._panning:
            delta = e.position().toPoint() - self._pan_start
            self._pan_start = e.position().toPoint()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            e.accept()
            return

        if self._drawing and self._last_pos:
            if not (e.buttons() & Qt.LeftButton):
                self._drawing = False
                self._last_pos = None
                if self.tool == Tool.ERASER:
                    self.viewport().update()
                e.accept()
                return

            img_pos = cur_pos
            if self.tool in (Tool.PEN, Tool.HIGHLIGHT):
                p = QPainter(self.ov_img)
                p.setPen(self._stroke_pen())
                p.drawLine(self._last_pos, img_pos)
                p.end()
                self._refresh(self._stroke_rect(self._last_pos, img_pos))
                self._last_pos = img_pos
            elif self.tool == Tool.BLUR:
                apply_gaussian_like_blur(self.bg_img, img_pos, self.thickness * 2)
                self._refresh(self._brush_rect(img_pos, self.thickness * 2))
                self._last_pos = img_pos
            elif self.tool == Tool.PIXELATE:
                apply_pixelate(self.bg_img, img_pos, self.thickness * 2, px_size=6)
                self._refresh(self._brush_rect(img_pos, self.thickness * 2))
                self._last_pos = img_pos
            elif self.tool == Tool.ERASER:
                self._refresh(self._erase_line(self._last_pos, img_pos, self.thickness * 2))
                self._last_pos = img_pos
            e.accept()
            return
        if (
            self._start_pos is not None
            and self.tool in (Tool.RECT, Tool.ELLIPSE, Tool.ARROW, Tool.CROP, Tool.REDACT)
        ):
            cur = self.viewport_to_image(e.position().toPoint())
            self._update_shape_preview(self._start_pos, cur, bool(e.modifiers() & Qt.ShiftModifier))
            e.accept()
            return

        super().mouseMoveEvent(e)

    def _update_shape_preview(self, start: QPoint, cur: QPoint, constrain: bool) -> None:
        """Рисует превью фигуры так же, как раньше рисовалось на копии картинки."""
        tool = self.tool
        thickness = max(1, self.thickness)
        if tool == Tool.ARROW:
            a, b = QPointF(start), QPointF(cur)
            color = QColor(self.color)
            pad = float(max(10, thickness * 3) + thickness + 4)
            bounds = QRectF(a, b).normalized().adjusted(-pad, -pad, pad, pad)
            self.preview_item.set_shape(bounds, lambda p: draw_arrow(p, a, b, color, thickness))
            return

        r = self._rect_from_points(start, cur, constrain if tool != Tool.CROP else False)
        if tool == Tool.REDACT:
            pen = QPen(Qt.NoPen)
            brush = QColor(_REDACT_COLOR)
        else:
            pen = QPen(
                self.color if tool in (Tool.RECT, Tool.ELLIPSE) else QColor(255, 255, 255, 220),
                thickness,
                Qt.SolidLine,
            )
            if tool in (Tool.RECT, Tool.ELLIPSE) and self.fill_enabled:
                brush = QColor(self.color)
                brush.setAlpha(self.fill_alpha)
            else:
                brush = Qt.NoBrush
        is_ellipse = tool == Tool.ELLIPSE

        def draw(p: QPainter) -> None:
            p.setPen(pen)
            p.setBrush(brush)
            if is_ellipse:
                p.drawEllipse(r)
            else:
                p.drawRect(r)

        pad = thickness + 2
        self.preview_item.set_shape(QRectF(r).adjusted(-pad, -pad, pad, pad), draw)

    def mouseReleaseEvent(self, e: QMouseEvent):
        if self._dragging_item is not None and e.button() == Qt.LeftButton:
            self._commit_scene_edit_undo_if_changed()
            self._dragging_item = None
            self.setCursor(Qt.CrossCursor)
            e.accept()
            return
        if self._panning and e.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._panning = False
            self.setCursor(Qt.OpenHandCursor if self.tool == Tool.PAN else Qt.CrossCursor)
            e.accept()
            return

        if e.button() == Qt.LeftButton:
            if self._drawing:
                self._drawing = False
                self._last_pos = None
                if self.tool == Tool.ERASER:
                    self.viewport().update()
                e.accept()
                return

            if (
                self._start_pos is not None
                and self.tool in (Tool.RECT, Tool.ELLIPSE, Tool.ARROW, Tool.CROP, Tool.REDACT)
            ):
                cur = self.viewport_to_image(e.position().toPoint())

                if self.tool == Tool.CROP:
                    r = self._rect_from_points(
                        self._start_pos, cur, bool(e.modifiers() & Qt.ShiftModifier)
                    ).intersected(self.bg_img.rect())
                    if r.width() > 3 and r.height() > 3:
                        self.push_undo()
                        self.bg_img = self.bg_img.copy(r)
                        self.ov_img = self.ov_img.copy(r)
                        # Транслируем все scene-объекты на смещение кропа.
                        # Объекты, полностью вышедшие за новые границы, удаляем.
                        offset = QPointF(-r.left(), -r.top())
                        new_bounds = QRectF(0, 0, r.width(), r.height())
                        for it in self._resizable_items():
                            it.setPos(it.pos() + offset)
                            # boundingRect в scene-координатах после сдвига
                            scene_br = it.mapToScene(it.boundingRect()).boundingRect()
                            if not new_bounds.intersects(scene_br):
                                self._scene.removeItem(it)
                                if isinstance(it, StickerItem) and it in self.stickers:
                                    self.stickers.remove(it)
                        self.update_scene_rect()
                        self._refresh()
                        # через fit_to_view, чтобы обновились зум в статусе и сглаживание
                        self.fit_to_view()
                else:
                    r = self._rect_from_points(
                        self._start_pos, cur, bool(e.modifiers() & Qt.ShiftModifier)
                    )

                    pen = QPen(
                        self.color,
                        max(1, self.thickness),
                        Qt.SolidLine,
                        Qt.RoundCap,
                        Qt.RoundJoin,
                    )
                    brush = (
                        QColor(self.color.red(), self.color.green(), self.color.blue(), self.fill_alpha)
                        if (self.fill_enabled and self.tool in (Tool.RECT, Tool.ELLIPSE))
                        else Qt.NoBrush
                    )

                    item: QGraphicsItem | None = None

                    if self.tool == Tool.RECT:
                        item = ResizableRectItem(QRectF(r), pen, brush)
                    elif self.tool == Tool.ELLIPSE:
                        item = ResizableEllipseItem(QRectF(r), pen, brush)
                    elif self.tool == Tool.ARROW:
                        item = ResizableArrowItem(QPointF(self._start_pos), QPointF(cur), self.color, self.thickness)
                    elif self.tool == Tool.REDACT:
                        item = ResizableRectItem(QRectF(r), QPen(Qt.NoPen), QColor(_REDACT_COLOR))

                    if item is not None:
                        self._scene.addItem(item)
                        item.setFlag(QGraphicsItem.ItemIsMovable, False)  # movable only in PAN mode
                        item.setZValue(2)

                self._start_pos = None
                self.cancel_preview()
                e.accept()
                return

        super().mouseReleaseEvent(e)

        if e.isAccepted():
            self._commit_scene_edit_undo_if_changed()

    def drawForeground(self, painter: QPainter, rect: QRectF):
        super().drawForeground(painter, rect)
        if self.tool == Tool.ERASER and self._cursor_pos:
            r = max(1, self.thickness * 2)
            cx, cy = float(self._cursor_pos.x()), float(self._cursor_pos.y())
            ellipse = QRectF(cx - r, cy - r, 2 * r, 2 * r)
            painter.setBrush(Qt.NoBrush)
            pen_outer = QPen(QColor(0, 0, 0, 180))
            pen_outer.setCosmetic(True)
            pen_outer.setWidth(2)
            painter.setPen(pen_outer)
            painter.drawEllipse(ellipse)
            pen_inner = QPen(QColor(255, 255, 255, 230))
            pen_inner.setCosmetic(True)
            pen_inner.setWidth(1)
            painter.setPen(pen_inner)
            painter.drawEllipse(ellipse)

    def leaveEvent(self, e):
        self._cursor_pos = None

        if self._drawing:
            self._drawing = False
            self._last_pos = None

        if self._start_pos is not None:
            self._start_pos = None
            self.cancel_preview()

        if self._panning:
            self._panning = False

        if self._dragging_item is not None:
            self._commit_scene_edit_undo_if_changed()
            self._dragging_item = None

        self.viewport().update()
        super().leaveEvent(e)

    def _undo_entry(self) -> tuple:
        # QImage(img) — неглубокая копия: данные общие, пока слой не изменят.
        # Раньше каждый шаг делал .copy() обоих слоёв: 60 шагов на 4K — до 4 ГБ.
        return (QImage(self.bg_img), QImage(self.ov_img), self._snapshot_scene(), self.step_counter)

    def _undo_bytes(self) -> int:
        seen: dict[int, int] = {}
        for bg, ov, _snap, _counter in (*self.undo_stack, *self.redo_stack):
            for img in (bg, ov):
                seen[img.cacheKey()] = img.sizeInBytes()
        return sum(seen.values())

    def _trim_undo(self) -> None:
        while len(self.undo_stack) > _UNDO_MAX_STEPS:
            self.undo_stack.pop(0)
        while len(self.undo_stack) > 1 and self._undo_bytes() > _UNDO_MAX_BYTES:
            self.undo_stack.pop(0)

    def push_undo(self):
        self.undo_stack.append(self._undo_entry())
        self.redo_stack.clear()
        self._set_dirty(True)
        self._trim_undo()

    def _apply_undo_entry(self, entry: tuple) -> None:
        bg, ov, snap, counter = entry
        self.bg_img, self.ov_img = bg, ov
        self.step_counter = counter
        self.cancel_preview()
        self.update_scene_rect()
        self._restore_scene(snap)
        self._refresh()
        # После отмены картинка отличается от сохранённой — иначе закрытие
        # окна не спрашивало бы о сохранении.
        self._set_dirty(True)

    def undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(self._undo_entry())
        self._apply_undo_entry(self.undo_stack.pop())

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self._undo_entry())
        self._apply_undo_entry(self.redo_stack.pop())

    def set_dirty_hook(self, hook: Optional[Callable[[bool], None]]) -> None:
        self._dirty_hook = hook

    def is_dirty(self) -> bool:
        return self._dirty

    def mark_clean(self) -> None:
        self._set_dirty(False)

    def _set_dirty(self, flag: bool) -> None:
        if self._dirty == flag:
            return
        self._dirty = flag
        if self._dirty_hook is not None:
            self._dirty_hook(flag)

    def set_status_hook(self, hook: Optional[Callable[[dict], None]]) -> None:
        self._status_hook = hook
        self._emit_status()

    def _emit_status(self) -> None:
        if self._status_hook is None:
            return
        img_w = int(self.bg_img.width()) if not self.bg_img.isNull() else 0
        img_h = int(self.bg_img.height()) if not self.bg_img.isNull() else 0
        x = int(self._cursor_pos.x()) if self._cursor_pos is not None else None
        y = int(self._cursor_pos.y()) if self._cursor_pos is not None else None
        self._status_hook(
            {
                "zoom": float(self._zoom),
                "tool": self.tool,
                "thickness": int(self.thickness),
                "img_w": img_w,
                "img_h": img_h,
                "x": x,
                "y": y,
            }
        )

    def save_rendered_image(self, path: Path) -> bool:
        lower = str(path).lower()
        if lower.endswith((".jpg", ".jpeg")):
            fmt, quality = "JPG", 95
        elif lower.endswith(".webp"):
            fmt, quality = "WEBP", 95
        elif lower.endswith(".bmp"):
            fmt, quality = "BMP", -1
        else:
            fmt, quality = "PNG", -1
        img = self.render_scene_to_image(hide_handles=True)
        if fmt in ("JPG", "BMP"):
            img = self._flatten_on_white(img)
        return bool(img.save(str(path), fmt, quality))

    @staticmethod
    def _flatten_on_white(img: QImage) -> QImage:
        """Картинка без прозрачности: прозрачные места (ластик, стикеры) — белые, а не чёрные."""
        flat = QImage(img.size(), QImage.Format_RGB32)
        flat.fill(Qt.white)
        p = QPainter(flat)
        p.drawImage(0, 0, img)
        p.end()
        return flat

    def save_as(self, parent: QWidget, initial_path: Optional[Path] = None) -> Optional[Path]:
        suggested = str(initial_path) if initial_path is not None else "screenshot.png"
        path_str, _ = QFileDialog.getSaveFileName(
            parent,
            "Сохранить изображение",
            suggested,
            "PNG (*.png);;JPEG (*.jpg *.jpeg);;WEBP (*.webp);;BMP (*.bmp)",
        )
        if not path_str:
            return None
        out_path = Path(path_str)
        if not self.save_rendered_image(out_path):
            QMessageBox.warning(parent, "Ошибка", "Не удалось сохранить файл.")
            return None
        return out_path

    def copy_to_clipboard(self) -> bool:
        # Плоское непрозрачное изображение — чтобы приложения, игнорирующие
        # альфа-канал (Paint, Word, мессенджеры), не вставляли чёрный фон
        # на месте прозрачных областей (ластик, повёрнутые стикеры).
        flat = self._flatten_on_white(self.render_scene_to_image(hide_handles=True))
        QApplication.clipboard().setImage(flat, QClipboard.Clipboard)
        return True

    def add_sticker(self, img: QImage):
        if img.isNull():
            return
        pix = QPixmap.fromImage(_normalized_image(img))
        max_size = QSize(int(self.bg_img.width() * 0.6), int(self.bg_img.height() * 0.6))
        item = StickerItem(pix, max_size)
        cx = (self.bg_img.width() - item._rect.width()) / 2
        cy = (self.bg_img.height() - item._rect.height()) / 2
        item.setPos(QPointF(cx, cy))
        self._scene.addItem(item)
        item.setFlag(QGraphicsItem.ItemIsMovable, self.tool == Tool.PAN)
        self.stickers.append(item)
        self._set_dirty(True)
        self.viewport().update()

    def flatten_selection(self):
        items = self._active_shape_items()
        if not items:
            # fallback to Qt selection (PAN mode)
            items = [it for it in self._scene.selectedItems() if it not in (self.base_item, self.preview_item)]
        if not items:
            return

        rasterizable = [it for it in items if hasattr(it, "rasterize_to")]
        if not rasterizable:
            return

        self.push_undo()
        p = QPainter(self.ov_img)
        p.setRenderHint(QPainter.Antialiasing, True)
        for it in rasterizable:
            it.rasterize_to(p)
        p.end()

        for it in rasterizable:
            self._scene.removeItem(it)
            if isinstance(it, StickerItem) and it in self.stickers:
                self.stickers.remove(it)

        self._refresh()

    def delete_selection(self) -> None:
        items = self._active_shape_items()
        if not items:
            items = [it for it in self._scene.selectedItems() if it not in (self.base_item, self.preview_item)]
        if not items:
            return

        self.push_undo()
        self._set_dirty(True)

        for it in items:
            self._scene.removeItem(it)
            if isinstance(it, StickerItem) and it in self.stickers:
                self.stickers.remove(it)

        self.viewport().update()

    def render_overlay_only(self) -> QImage:
        """Прозрачный слой аннотаций для наложения на видео: ov_img
        (перо/маркер/blur/заливка) + векторные элементы (rect/овал/стрелка/
        текст/стикеры), БЕЗ фонового кадра. Используется редактором видео."""
        w, h = self.bg_img.width(), self.bg_img.height()
        out = QImage(w, h, QImage.Format_ARGB32)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawImage(0, 0, self.ov_img)  # деструктивный слой рисования
        shown = [it for it in self._resizable_items() if getattr(it, "_show_handles", False)]
        for it in shown:
            it._show_handles = False; it.update()
        base_vis = self.base_item.isVisible()
        prev_vis = self.preview_item.isVisible()
        self.base_item.setVisible(False)
        self.preview_item.setVisible(False)
        self._scene.render(p, QRectF(0, 0, w, h), QRectF(0, 0, w, h))
        self.base_item.setVisible(base_vis)
        self.preview_item.setVisible(prev_vis)
        for it in shown:
            it._show_handles = True; it.update()
        p.end()
        return out

    def render_scene_to_image(self, hide_handles: bool = False) -> QImage:
        w, h = self.bg_img.width(), self.bg_img.height()
        img = QImage(w, h, QImage.Format_ARGB32)
        img.fill(Qt.transparent)

        # Temporarily hide handles so they don't appear in the rendered image
        if hide_handles:
            shown = [it for it in self._resizable_items() if it._show_handles]
            for it in shown:
                it._show_handles = False
                it.update()

        p = QPainter(img)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self._scene.render(p, QRectF(0, 0, w, h), QRectF(0, 0, w, h))
        p.end()

        if hide_handles:
            for it in shown:
                it._show_handles = True
                it.update()

        return img


class EditorWindow(QMainWindow):
    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Screenshot Editor")
        self.resize(1100, 700)
        self.view = CanvasView(image, self)
        self.setCentralWidget(self.view)
        self._build_toolbar()
        self._apply_shortcuts()
        self._add_apps_menu()
        self.setWindowIcon(_load_app_icon())
        self._last_save_path: Optional[Path] = None
        self._init_status_bar()
        self.view.set_status_hook(self._on_view_status)
        self.installEventFilter(self)
        self.view.installEventFilter(self)
        self.setAcceptDrops(True)
        self.view.set_dirty_hook(self._on_dirty_changed)
        self._on_dirty_changed(self.view.is_dirty())

    def _add_apps_menu(self):
        mb = self.menuBar()
        apps = mb.addMenu("Приложения")
        act = QAction("Выбрать приложение...  (Ctrl+Alt+L)", self)
        act.triggered.connect(self.show_app_launcher)
        apps.addAction(act)

        sc = QShortcut(QKeySequence("Ctrl+Alt+L"), self)
        sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc.activated.connect(self.show_app_launcher)

    def reveal_last_saved(self) -> None:
        if self._last_save_path is None:
            QMessageBox.information(self, "Папка", "Файл ещё не сохранён.")
            return
        QProcess.startDetached("explorer", ["/select,", str(self._last_save_path)])

    @staticmethod
    def _is_image_path(p: Path) -> bool:
        return p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md is not None and md.hasUrls():
            for u in md.urls():
                if u.isLocalFile():
                    p = Path(u.toLocalFile())
                    if self._is_image_path(p):
                        e.acceptProposedAction()
                        return
        super().dragEnterEvent(e)

    def dropEvent(self, e):
        md = e.mimeData()
        if md is None or not md.hasUrls():
            super().dropEvent(e)
            return

        paths: list[Path] = []
        for u in md.urls():
            if u.isLocalFile():
                p = Path(u.toLocalFile())
                if p.is_file() and self._is_image_path(p):
                    paths.append(p)

        if not paths:
            super().dropEvent(e)
            return

        images: list[QImage] = []
        for p in paths:
            img = QImage(str(p))
            if not img.isNull():
                images.append(img)

        if not images:
            return

        self._replace_image(images[0])
        for img in images[1:]:
            self.view.add_sticker(img)

        e.acceptProposedAction()

    def _init_status_bar(self) -> None:
        sb = self.statusBar()
        self._sb_left = QLabel("", self)
        self._sb_mid = QLabel("", self)
        self._sb_right = QLabel("", self)
        sb.addWidget(self._sb_left, 1)
        sb.addWidget(self._sb_mid, 1)
        sb.addPermanentWidget(self._sb_right)

    def _on_dirty_changed(self, dirty: bool) -> None:
        name = self._last_save_path.name if self._last_save_path is not None else "Без имени"
        mark = " *" if dirty else ""
        self.setWindowTitle(f"{name}{mark} — Screenshot Editor")

    def _on_view_status(self, payload: dict) -> None:
        zoom = payload.get("zoom", 1.0)
        thickness = payload.get("thickness", 0)
        tool = payload.get("tool", None)
        img_w = payload.get("img_w", 0)
        img_h = payload.get("img_h", 0)
        x = payload.get("x", None)
        y = payload.get("y", None)

        tool_name = getattr(tool, "name", str(tool))
        pos_text = f"x={x}, y={y}" if x is not None and y is not None else "x=—, y=—"

        self._sb_left.setText(f"Изображение: {img_w}×{img_h}")
        self._sb_mid.setText(f"Курсор: {pos_text}")
        self._sb_right.setText(f"Tool: {tool_name} | Толщина: {thickness}px | Zoom: {int(round(float(zoom) * 100))}%")

    def _default_save_name(self) -> Path:
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        folder = self.view.last_save_dir or QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        name = f"Screenshot_{stamp}.png"
        return Path(folder) / name if folder else Path(name)

    def _remember_save(self, path: Path) -> None:
        self._last_save_path = path
        self.view.last_save_dir = str(path.parent)
        self.view.flush_editor_state()

    def _replace_image(self, img: QImage) -> None:
        """Новая картинка в этом же окне: Ctrl+S больше не перезапишет файл прошлой картинки."""
        self.view.set_image(img)
        self._last_save_path = None
        self._on_dirty_changed(self.view.is_dirty())

    def save_quick(self) -> bool:
        if self._last_save_path is None:
            out = self.view.save_as(self, self._default_save_name())
            if out is None:
                return False
            self._remember_save(out)
            self.view.mark_clean()
            self._on_dirty_changed(False)
            return True

        if not self.view.save_rendered_image(self._last_save_path):
            QMessageBox.warning(self, "Ошибка", "Не удалось сохранить файл.")
            return False

        self.view.mark_clean()
        self._on_dirty_changed(False)
        return True

    def save_as(self) -> bool:
        out = self.view.save_as(self, self._last_save_path or self._default_save_name())
        if out is None:
            return False
        self._remember_save(out)
        self.view.mark_clean()
        self._on_dirty_changed(False)
        return True

    def copy_to_clipboard(self) -> bool:
        ok = self.view.copy_to_clipboard()
        self.statusBar().showMessage(
            "Скопировано в буфер обмена" if ok else "Не удалось скопировать", 2000
        )
        return ok

    def _bump_thickness(self, delta: int) -> None:
        new_val = max(1, min(200, int(self.view.thickness) + int(delta)))
        self.view.set_thickness(new_val)
        self.slider.setValue(new_val)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.KeyPress, QEvent.KeyRelease) and event.key() == Qt.Key_Space \
                and event.isAutoRepeat():
            # Удержание пробела шлёт пары KeyRelease/KeyPress с автоповтором —
            # раньше инструмент переключался PAN ↔ прежний прямо во время панорамы.
            return True
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Space:
            if getattr(self, "_space_pan_prev_tool", None) is None:
                self._space_pan_prev_tool = self.view.tool
                self.view.set_tool(Tool.PAN)
            return True
        if event.type() == QEvent.KeyRelease and event.key() == Qt.Key_Space:
            prev = getattr(self, "_space_pan_prev_tool", None)
            if prev is not None:
                self.view.set_tool(prev)
                self._space_pan_prev_tool = None
            return True
        return super().eventFilter(obj, event)

    @staticmethod
    def _iter_launcher_search_dirs() -> list[Path]:
        dirs: list[Path] = []

        dirs.append(ROOT_DIR)
        dirs.append(ROOT_DIR / "dev")

        argv0 = Path(sys.argv[0]).resolve()
        if argv0.parent:
            dirs.append(argv0.parent)

        dirs.append(Path(__file__).resolve().parent)

        seen: set[Path] = set()
        out: list[Path] = []
        for d in dirs:
            d = d.resolve()
            if d not in seen:
                seen.add(d)
                out.append(d)
        return out

    @staticmethod
    def _find_launcher_candidate() -> Optional[Path]:
        candidates = [
            "Choice.exe",
            "Choice.pyw",
            "choice_dev.py",
            "choice_dev.pyw",
        ]
        for d in EditorWindow._iter_launcher_search_dirs():
            for name in candidates:
                p = d / name
                if p.is_file():
                    return p
        return None

    def show_app_launcher(self) -> None:
        p = self._find_launcher_candidate()
        if p is None:
            QMessageBox.warning(self, "Приложения", "Файл Choice не найден.")
            return

        suffix = p.suffix.lower()
        if suffix in (".py", ".pyw"):
            # Portable: лаунчер запускается своей копией pythonw — Runtime\Choice.exe
            runner = p.parent / "Runtime" / "Choice.exe"
            QProcess.startDetached(str(runner) if runner.is_file() else sys.executable, [str(p)])
        else:
            QProcess.startDetached(str(p), [])

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_centered_once", False):
            QTimer.singleShot(0, lambda: center_on_screen(self))
            self._centered_once = True

    def _build_toolbar(self):
        t1 = QToolBar("Инструменты — 1", self)
        t2 = QToolBar("Инструменты — 2", self)
        t3 = QToolBar("Инструменты — 3", self)
        t4 = QToolBar("Инструменты — 4", self)
        for t in (t1, t2, t3, t4):
            t.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, t1)
        self.addToolBarBreak(Qt.TopToolBarArea)
        self.addToolBar(Qt.TopToolBarArea, t2)
        self.addToolBarBreak(Qt.TopToolBarArea)
        self.addToolBar(Qt.TopToolBarArea, t3)
        self.addToolBarBreak(Qt.TopToolBarArea)
        self.addToolBar(Qt.TopToolBarArea, t4)
        self.tb_rows = (t1, t2, t3, t4)

        def add_action(bar: QToolBar, text, cb, shortcut=None, checkable=False):
            act = QAction(text, self)
            act.triggered.connect(cb)
            act.setCheckable(checkable)
            if shortcut:
                act.setShortcut(shortcut)
            bar.addAction(act)
            return act

        self.group_actions: List[QAction] = []

        def tool_action(bar: QToolBar, label: str, t: Tool, shortcut: Optional[str] = None):
            def cb():
                for a in self.group_actions:
                    a.setChecked(False)
                act.setChecked(True)
                self.view.set_tool(t)

            act = add_action(bar, label, cb, shortcut, checkable=True)
            self.group_actions.append(act)
            return act

        a_pan    = tool_action(t1, "✥ Переместиться", Tool.PAN, "H")
        a_pen    = tool_action(t1, "✎ Перо",         Tool.PEN, "P")
        a_high   = tool_action(t1, "🖍 Маркер",       Tool.HIGHLIGHT, "M")
        a_rect   = tool_action(t1, "▭ Прямоуг.",     Tool.RECT, "R")
        a_ell    = tool_action(t1, "◯ Овал",         Tool.ELLIPSE, "O")
        a_arrow  = tool_action(t1, "➤ Стрелка",      Tool.ARROW, "A")
        a_text   = tool_action(t1, "🅣 Текст",       Tool.TEXT, "T")
        a_blur   = tool_action(t1, "🌫 Блюр",        Tool.BLUR, "B")
        a_pix    = tool_action(t1, "▦ Пиксели",      Tool.PIXELATE, "X")
        a_crop   = tool_action(t1, "✂ Обрезать",     Tool.CROP, "C")
        a_redact = tool_action(t1, "█ Редация",      Tool.REDACT, "D")
        a_step   = tool_action(t1, "① Шаг",          Tool.STEP, "1")
        a_filltool = tool_action(t1, "🪣 Заливка",    Tool.FILL, "F")
        a_filltool.setToolTip("Ведро: ЛКМ — заливка в верхнем слое, Alt+ЛКМ — заливка фона. «Допуск» = чувствительность к цвету.")
        a_eraser = tool_action(t1, "⌫ Ластик",       Tool.ERASER, "E")
        _tool_action_map: dict[Tool, QAction] = {
            Tool.PAN: a_pan, Tool.PEN: a_pen, Tool.HIGHLIGHT: a_high,
            Tool.RECT: a_rect, Tool.ELLIPSE: a_ell, Tool.ARROW: a_arrow,
            Tool.TEXT: a_text, Tool.BLUR: a_blur, Tool.PIXELATE: a_pix,
            Tool.CROP: a_crop, Tool.REDACT: a_redact, Tool.STEP: a_step,
            Tool.FILL: a_filltool, Tool.ERASER: a_eraser,
        }
        saved_tool = self.view.tool
        restored_action = _tool_action_map.get(saved_tool, a_pen)
        restored_action.trigger()
        t1.addSeparator()
        self.line_caption = QLabel(" Линия")
        self.line_caption.setStyleSheet("color: #c8c8c8;")
        t2.addWidget(self.line_caption)
        self.line_btn = QToolButton(self)
        self.line_btn.setToolTip("Цвет линии (кликни)")
        self.line_btn.setAutoRaise(True)
        self.line_btn.setFixedSize(26, 26)
        self.line_btn.clicked.connect(self.pick_color)
        t2.addWidget(self.line_btn)
        self._refresh_line_btn()
        self.fill_caption = QLabel(" Заливка")
        self.fill_caption.setStyleSheet("color: #c8c8c8;")
        t2.addWidget(self.fill_caption)
        self.fill_btn = QToolButton(self)
        self.fill_btn.setToolTip("Цвет заливки (кликни)")
        self.fill_btn.setAutoRaise(True)
        self.fill_btn.setFixedSize(26, 26)
        self.fill_btn.clicked.connect(self.pick_fill_color)
        t2.addWidget(self.fill_btn)
        self._refresh_fill_btn()
        lbl = QLabel(" Толщина: ")
        t2.addWidget(lbl)
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setMinimum(1)
        self.slider.setMaximum(200)
        self.slider.setValue(int(self.view.thickness))
        self.slider.valueChanged.connect(lambda v: self.view.set_thickness(v))
        self.slider.setMinimumWidth(90)
        self.slider.setMaximumWidth(220)
        t2.addWidget(self.slider)
        a_fill = QAction("⧉ Заливка форм", self)
        a_fill.setCheckable(True)
        a_fill.setChecked(bool(self.view.fill_enabled))
        a_fill.toggled.connect(lambda f: self.view.set_fill_enabled(f))
        t2.addAction(a_fill)
        self.lbl_alpha = QLabel(" Непрозрачность: 80% ")
        t2.addWidget(self.lbl_alpha)
        self.fill_slider = QSlider(Qt.Horizontal, self)
        self.fill_slider.setMinimum(0)
        self.fill_slider.setMaximum(255)
        self.fill_slider.setValue(int(self.view.fill_alpha))
        self.fill_slider.setMinimumWidth(90)
        self.fill_slider.setMaximumWidth(200)
        self.fill_slider.setToolTip("Непрозрачность заливки (0 — прозрачная, 255 — непрозрачная). Влияет на заливку фигур и «Ведро».")
        self.fill_slider.valueChanged.connect(lambda v: (self.view.set_fill_alpha(v), self._refresh_fill_btn(), self._update_alpha_label(v)))
        self._update_alpha_label(self.fill_slider.value())
        t2.addWidget(self.fill_slider)
        t2.addSeparator()
        self.lbl_tol = QLabel()
        t2.addWidget(self.lbl_tol)
        self.tol_slider = QSlider(Qt.Horizontal, self)
        self.tol_slider.setMinimum(0)
        self.tol_slider.setMaximum(255)
        self.tol_slider.setValue(int(self.view.fill_tolerance))
        self.tol_slider.setMinimumWidth(90)
        self.tol_slider.setMaximumWidth(200)
        self.tol_slider.setToolTip("Допуск цвета для «Ведра»: насколько похожими должны быть цвета, чтобы заливаться. 0 — только точный цвет.")
        self.tol_slider.valueChanged.connect(lambda v: (self.view.set_fill_tolerance(v), self._update_tol_label(v)))
        t2.addWidget(self.tol_slider)
        self._update_tol_label(self.tol_slider.value())
        add_action(t3, "📂 Открыть…", self.open_from_file, "Ctrl+O")
        add_action(t3, "🖼 Вставить картинку…", self.insert_sticker_from_file, "Ctrl+Shift+I")
        add_action(t3, "📋 Вставить как картинку", self.insert_sticker_from_clipboard, "Ctrl+Shift+V")
        add_action(t3, "⎆ Зафиксировать", self.flatten_selection, "Return")
        add_action(t3, "⌧ Удалить объект", self.delete_selection, "Del")
        add_action(t3, "📋 Вставить из буфера (заменить)", self.open_from_clipboard, "Ctrl+V")
        add_action(t3, "💾 Сохранить", self.save_quick, "Ctrl+S")
        add_action(t3, "💾 Сохранить как…", self.save_as, "Ctrl+Shift+S")
        add_action(t3, "📁 Показать в папке", self.reveal_last_saved, "Ctrl+Shift+E")
        add_action(t3, "📋 Копировать", self.copy_to_clipboard, "Ctrl+C")
        add_action(t4, "↶ Отменить", self.view.undo, "Ctrl+Z")
        add_action(t4, "↷ Повторить", self.view.redo, "Ctrl+Y")
        t4.addSeparator()
        add_action(t4, "⤢ Вписать", self.view.fit_to_view, "Ctrl+0")
        add_action(t4, "100% (1:1)", self.view.show_original_size, "Ctrl+1")
        t4.addSeparator()
        add_action(t4, "🖼 Новый снимок", self.new_capture, "Print")
        add_action(t4, "⟲ Сброс шагов", lambda: setattr(self.view, "step_counter", 1))
        self.tip_label = QLabel(" Подсказки: Ctrl+Колесо — зум, Средняя кнопка — панорама")
        self.tip_label.setStyleSheet("color: gray;")
        t4.addWidget(self.tip_label)

    def _update_alpha_label(self, v:int):
        pct = int(round(v/255*100))
        if hasattr(self, "lbl_alpha"):
            self.lbl_alpha.setText(f" Непрозрачность: {pct}% ")

    def _update_tol_label(self, v:int):
        if hasattr(self, "lbl_tol"):
            self.lbl_tol.setText(f" Допуск ведра: {v} ")

    def _apply_shortcuts(self):
        quit_act = QAction(self)
        quit_act.setShortcut(QKeySequence(Qt.Key_Escape))
        quit_act.triggered.connect(self.close)
        self.addAction(quit_act)

        sc_dec = QShortcut(QKeySequence("["), self)
        sc_dec.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_dec.activated.connect(lambda: self._bump_thickness(-1))

        sc_inc = QShortcut(QKeySequence("]"), self)
        sc_inc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_inc.activated.connect(lambda: self._bump_thickness(1))


    def closeEvent(self, e):
        if self.view.is_dirty():
            res = QMessageBox.question(
                self,
                "Несохранённые изменения",
                "Есть несохранённые изменения. Сохранить перед закрытием?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if res == QMessageBox.Save:
                if not self.save_quick():
                    e.ignore()
                    return
            elif res == QMessageBox.Cancel:
                e.ignore()
                return
        self.view.flush_editor_state()
        super().closeEvent(e)

    def pick_color(self):
        c = QColorDialog.getColor(self.view.color, self, "Выбери цвет")
        if c.isValid():
            self.view.set_color(c)
            self._refresh_line_btn()

    def _make_checker(self, size=22, cell=3) -> QPixmap:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        c1, c2 = QColor(70, 70, 70), QColor(90, 90, 90)
        for y in range(0, size, cell):
            for x in range(0, size, cell):
                p.fillRect(x, y, cell, cell, c1 if ((x // cell + y // cell) % 2) else c2)
        p.end()
        return pm

    def _refresh_fill_btn(self):
        pm = self._make_checker()
        p = QPainter(pm)
        r = pm.rect().adjusted(3, 3, -3, -3)
        fill = QColor(self.view.fill_color)
        fill.setAlpha(self.view.fill_alpha)
        p.setPen(QPen(QColor(20, 20, 20, 180), 1))
        p.setBrush(fill)
        p.drawRect(r)
        p.end()
        self.fill_btn.setIcon(QIcon(pm))

    def _refresh_line_btn(self):
        pm = self._make_checker()
        p = QPainter(pm)
        pen = QPen(self.view.color, 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.drawLine(3, pm.height() - 4, pm.width() - 4, 3)
        p.setPen(QPen(QColor(20, 20, 20, 180), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(pm.rect().adjusted(0, 0, -1, -1))
        p.end()
        self.line_btn.setIcon(QIcon(pm))

    def pick_fill_color(self):
        c = QColorDialog.getColor(self.view.fill_color, self, "Цвет заливки")
        if c.isValid():
            self.view.set_fill_color(c)
            self._refresh_fill_btn()

    def new_capture(self):
        self._was_max = self.isMaximized()
        # Экран теперь снимается в момент показа слоя выбора, поэтому окно
        # прячем мгновенно (hide), а не сворачиваем: анимация сворачивания
        # успевала попасть в кадр.
        self.hide()
        QTimer.singleShot(200, self._do_capture)

    def open_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Открыть изображение",
            "",
            "Изображения (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Ошибка", "Не удалось открыть файл.")
            return
        self._replace_image(img)

    def open_from_clipboard(self):
        cb = QApplication.clipboard()
        img = cb.image(QClipboard.Clipboard)
        if img.isNull():
            QMessageBox.information(
                self, "Буфер пуст", "В буфере обмена нет изображения."
            )
            return
        self._replace_image(img)

    def insert_sticker_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Вставить изображение", "",
            "Изображения (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Ошибка", "Не удалось открыть файл.")
            return
        self.view.add_sticker(img)

    def insert_sticker_from_clipboard(self):
        img = QApplication.clipboard().image(QClipboard.Clipboard)
        if img.isNull():
            QMessageBox.information(self, "Буфер пуст", "В буфере обмена нет изображения.")
            return
        self.view.add_sticker(img)

    def flatten_selection(self):
        self.view.flatten_selection()

    def delete_selection(self):
        self.view.delete_selection()

    def _do_capture(self):
        img = run_capture_flow(SelectionOverlay.MODE_SHOT, _find_launcher())
        (self.showMaximized() if getattr(self, "_was_max", False) else self.showNormal())
        if img is None:
            return
        QApplication.clipboard().setImage(img, QClipboard.Clipboard)
        ed = EditorWindow(img)
        ed.show()
        ed.activateWindow()
        _register_editor_in_launcher(ed)

def compose_region_from_shots(rect_g: QRect, shots: List[Tuple[QRect, QPixmap]]) -> QImage:
    """Собирает картинку области rect_g (глобальные логические координаты).

    shots — снимки целых экранов с их логической геометрией. Область внутри
    одного экрана вырезается пиксель в пиксель, как раньше. Область на
    нескольких мониторах (раньше бралась только часть с экрана под центром)
    склеивается в масштабе самого чёткого из них.
    """
    if rect_g.isEmpty() or rect_g.width() < 1 or rect_g.height() < 1:
        return QImage()

    parts: List[Tuple[QRect, QImage, QRect, float]] = []
    for geo, pm in shots:
        inter = geo.intersected(rect_g)
        if inter.isEmpty() or pm.isNull():
            continue
        img = _normalized_image(pm.toImage())
        sx = img.width() / max(1, geo.width())
        sy = img.height() / max(1, geo.height())
        # Начало экрана в Qt совпадает с нативными координатами, а размер —
        # в логических: поэтому сдвиг считаем от левого верхнего угла экрана.
        src = QRect(
            int(round((inter.left() - geo.left()) * sx)),
            int(round((inter.top() - geo.top()) * sy)),
            max(1, int(round(inter.width() * sx))),
            max(1, int(round(inter.height() * sy))),
        ).intersected(img.rect())
        if not src.isEmpty():
            parts.append((inter, img, src, sx))

    if not parts:
        return QImage()
    if len(parts) == 1:
        _inter, img, src, _scale = parts[0]
        return img.copy(src)

    scale = max(part[3] for part in parts)
    out = QImage(
        max(1, int(round(rect_g.width() * scale))),
        max(1, int(round(rect_g.height() * scale))),
        QImage.Format_ARGB32,
    )
    out.fill(Qt.black)
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    for inter, img, src, _scale in parts:
        dst = QRect(
            int(round((inter.left() - rect_g.left()) * scale)),
            int(round((inter.top() - rect_g.top()) * scale)),
            max(1, int(round(inter.width() * scale))),
            max(1, int(round(inter.height() * scale))),
        )
        p.drawImage(dst, img, src)
    p.end()
    return out


def grab_region_highdpi(rect_g: QRect) -> QImage:
    """Снимок области с живого экрана (без замороженного кадра)."""
    shots = []
    for screen in QGuiApplication.screens():
        if QRect(screen.geometry()).intersects(rect_g):
            pm = screen.grabWindow(0)
            if not pm.isNull():
                shots.append((QRect(screen.geometry()), pm))
    return compose_region_from_shots(rect_g, shots)


def _run_selection(overlay: SelectionOverlay) -> Optional[QRect]:
    """Показывает слой выбора и ждёт выделения (или отмены) во вложенном цикле событий."""
    ev = QEventLoop()
    result: dict[str, Optional[QRect]] = {"rect": None}

    def on_sel(rect: Optional[QRect]):
        result["rect"] = rect
        if ev.isRunning():
            ev.quit()

    overlay.selection_made = on_sel
    overlay.begin()

    def watchdog():
        if not overlay.isVisible() and ev.isRunning():
            ev.quit()

    timer = QTimer()
    timer.setInterval(30)
    timer.timeout.connect(watchdog)
    timer.start()
    ev.exec()
    timer.stop()
    return result["rect"]


_capture_in_progress = False


def run_capture_flow(initial_mode: str = SelectionOverlay.MODE_SHOT, launcher=None) -> Optional[QImage]:
    """Выделение области сразу в режиме скриншота с переключением на запись экрана.

    Возвращает картинку, если выбран скриншот. Если выбрана запись — сам
    запускает панель записи для выделенной области и возвращает None.
    None также при отмене или если выделение уже идёт (повторный PrintScreen).
    """
    global _capture_in_progress
    if _capture_in_progress:
        log.info("capture: skipped, already in progress")
        return None
    _capture_in_progress = True
    try:
        if not ffmpeg_path():
            record_ok, reason = False, "Запись: не найден ffmpeg.exe (положи в папку Data)"
        elif _active_huds:
            record_ok, reason = False, "Запись уже открыта"
        else:
            record_ok, reason = True, ""
        overlay = SelectionOverlay(
            frozen=True, switchable=True, mode=initial_mode,
            record_available=record_ok, record_unavailable_reason=reason,
        )
        try:
            log.info("capture: overlay panes=%d shots=%s",
                     len(overlay._panes),
                     [(s[0].getRect(), s[1].width(), s[1].height(), s[1].isNull()) for s in overlay.shots()])
            rect = _run_selection(overlay)
            mode = overlay.mode
            shots = overlay.shots()
            log.info("capture: selection rect=%s mode=%s",
                     None if rect is None else rect.getRect(), mode)
        finally:
            overlay.dispose()
    finally:
        _capture_in_progress = False

    if rect is None:
        return None
    if mode == SelectionOverlay.MODE_RECORD:
        if rect.width() >= 4 and rect.height() >= 4:
            _begin_recording(rect, launcher)
        return None
    if mode == SelectionOverlay.MODE_OCR:
        img = compose_region_from_shots(rect, shots)
        if not img.isNull():
            start_ocr(img, launcher)
        return None
    img = compose_region_from_shots(rect, shots)
    if img.isNull() or img.width() <= 0 or img.height() <= 0:
        return None
    return img


# ── Распознавание текста (встроенный в Windows OCR, без интернета) ───────────
# Через Windows PowerShell 5.1: он умеет вызывать WinRT без сторонних пакетов.
_OCR_PS = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) {
    $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $t.Wait(-1) | Out-Null
    $t.Result
}
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime] | Out-Null
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync('__PATH__')) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
function Engine($tag) {
    $lang = New-Object Windows.Globalization.Language $tag
    if ([Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($lang)) {
        return [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
    }
    return $null
}
function Recognize($engine) {
    $r = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    return (($r.Lines | ForEach-Object { $_.Text }) -join "`n")
}
$ru = Engine 'ru-RU'
$en = Engine 'en-US'
if ($null -eq $ru -and $null -eq $en) {
    $any = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $any) { [Console]::Error.WriteLine('NO_OCR_LANGUAGE'); exit 2 }
    Recognize $any
    exit 0
}
if ($null -eq $ru) { Recognize $en; exit 0 }
$text = Recognize $ru
# Русский модуль плохо читает чисто английский текст: если латиницы больше,
# чем кириллицы, распознаём ещё раз английским.
if ($null -ne $en) {
    $lat = ([regex]::Matches($text, '[A-Za-z]')).Count
    $cyr = ([regex]::Matches($text, '[А-Яа-яЁё]')).Count
    if ($lat -gt $cyr) { $text = Recognize $en }
}
$text
"""

_OCR_NO_LANGUAGE_HINT = (
    "В Windows нет модуля распознавания текста. Параметры → Время и язык → "
    "Язык и регион → Русский → … → Параметры языка → «Оптическое распознавание "
    "символов» → Скачать."
)

_ocr_jobs: List[QProcess] = []


def _ocr_prepare_image(img: QImage) -> QImage:
    """Мелкий текст Windows OCR читает плохо — небольшие фрагменты увеличиваем."""
    img = _normalized_image(img)
    w, h = img.width(), img.height()
    if max(w, h) <= 1600:
        img = img.scaled(w * 2, h * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return CanvasView._flatten_on_white(img)


def start_ocr(img: QImage, launcher=None) -> None:
    """Распознаёт текст на картинке и кладёт его в буфер обмена (асинхронно)."""
    tray = getattr(launcher, "tray", None) if launcher is not None else None

    def notify(title: str, text: str, warn: bool = False) -> None:
        log.info("ocr: %s — %s", title, text.replace("\n", " ")[:200])
        if tray is not None:
            icon = QSystemTrayIcon.Warning if warn else QSystemTrayIcon.Information
            tray.showMessage(title, text, icon, 5000 if warn else 3000)

    if not sys.platform.startswith("win"):
        notify("Распознавание текста", "Работает только в Windows.", warn=True)
        return
    path = _rec_tmp_dir() / f"ocr_{time.strftime('%H-%M-%S')}_{len(_ocr_jobs)}.png"
    if not _ocr_prepare_image(img).save(str(path), "PNG"):
        notify("Распознавание текста", "Не удалось сохранить картинку для распознавания.", warn=True)
        return

    script = _OCR_PS.replace("__PATH__", str(path).replace("'", "''"))
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    proc = QProcess()
    try:
        proc.setCreateProcessArgumentsModifier(
            lambda a: setattr(a, "flags", a.flags | _CREATE_NO_WINDOW))
    except Exception:
        pass
    proc.setProgram("powershell.exe")
    proc.setArguments(["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                       "-EncodedCommand", encoded])
    _ocr_jobs.append(proc)
    done = {"flag": False}

    def cleanup() -> None:
        if done["flag"]:
            return
        done["flag"] = True
        if proc in _ocr_jobs:
            _ocr_jobs.remove(proc)
        proc.deleteLater()
        try:
            path.unlink()
        except OSError:
            pass

    def finished(code, _status) -> None:
        try:
            out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
            out = out.lstrip("﻿").replace("\r\n", "\n").strip()
            err = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip()
            if "NO_OCR_LANGUAGE" in err:
                notify("Распознавание текста", _OCR_NO_LANGUAGE_HINT, warn=True)
            elif code != 0:
                log.error("ocr failed (code=%s):\n%s", code, err[-2000:])
                notify("Распознавание текста", "Ошибка распознавания — подробности в логе.", warn=True)
            elif not out:
                notify("Распознавание текста", "Текст не найден.")
            else:
                QApplication.clipboard().setText(out, QClipboard.Clipboard)
                preview = out.replace("\n", " ")
                notify("Текст скопирован", preview[:120] + ("…" if len(preview) > 120 else ""))
        finally:
            cleanup()

    def failed(err) -> None:
        if err == QProcess.FailedToStart:
            log.error("ocr: powershell failed to start: %s", proc.errorString())
            notify("Распознавание текста", "Не удалось запустить PowerShell.", warn=True)
            cleanup()

    proc.finished.connect(finished)
    proc.errorOccurred.connect(failed)
    proc.start()


def _find_launcher() -> Optional["Launcher"]:
    app = QApplication.instance()
    for w in app.topLevelWidgets():
        if isinstance(w, Launcher):
            return w
    return None


def capture_region_interactive() -> Optional[QImage]:
    overlay = SelectionOverlay(frozen=True)
    try:
        rect = _run_selection(overlay)
        shots = overlay.shots()
    finally:
        overlay.dispose()
    if rect is None:
        return None
    img = compose_region_from_shots(rect, shots)
    if img.isNull() or img.width() <= 0 or img.height() <= 0:
        return None
    return img


class Launcher(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NPCore Скриншоты")
        self.resize(420, 180)
        w = QWidget(self)
        self.setCentralWidget(w)
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 16, 16, 16)
        title = QLabel(
            "<b>Скриншоты</b><br>"
            "PrintScreen — выделить область. Режим (снимок / запись экрана / текст) — "
            "панель сверху или Tab; отмена — ПКМ или Esc.<br>"
            "Shift+PrintScreen — сразу распознать текст в буфер обмена.<br>"
            "В редакторе: Ctrl+S — сохранить, Ctrl+C — копировать, PrintScreen — новый снимок."
        )
        title.setWordWrap(True)
        v.addWidget(title)
        btn = QPushButton("Сделать скриншот")
        btn.clicked.connect(self.make_shot)
        v.addWidget(btn)
        btn_rec = QPushButton("Запись экрана")
        btn_rec.clicked.connect(self.start_recording)
        v.addWidget(btn_rec)
        btn_ocr = QPushButton("Распознать текст")
        btn_ocr.clicked.connect(self.make_ocr)
        v.addWidget(btn_ocr)
        btn_open = QPushButton("Открыть изображение…")
        btn_open.clicked.connect(self._open_image)
        v.addWidget(btn_open)
        info = QLabel(
            "Инструменты: Переместиться (H), Перо (P), Маркер (M), Прямоуг. (R), Овал (O), "
            "Стрелка (A), Текст (T), Блюр (B), Пиксели (X), Обрезать (C), Редация (D), "
            "Шаг (1), Заливка (F), Ластик (E). "
            "«⧉ Заливка форм» — заливка у прямоугольника и овала."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: gray;")
        v.addWidget(info)
        v.addStretch(1)
        _setup_logging()
        self._editors: List[EditorWindow] = []
        self._real_quit = False
        self._init_tray()
        self._install_global_hotkey()
        act_f8 = QAction(self)
        act_f8.setShortcut("Print")
        act_f8.triggered.connect(self.make_shot)
        self.addAction(act_f8)
        center_on_screen(self)

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_centered_once", False):
            QTimer.singleShot(0, lambda: center_on_screen(self))
            self._centered_once = True

    def _add_editor(self, ed: EditorWindow) -> None:
        ed.setAttribute(Qt.WA_DeleteOnClose, True)
        self._editors.append(ed)
        ed.destroyed.connect(lambda _obj=None, ed=ed: self._on_editor_destroyed(ed))
        self._update_tray_menu()

    def _on_editor_destroyed(self, ed: EditorWindow) -> None:
        self._editors = [w for w in self._editors if w is not ed]
        self._update_tray_menu()

    def _init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(_load_app_icon(), self)
        self.tray.setToolTip("NPCore Скриншоты")
        m = QMenu(self)
        self.act_tray_shot = m.addAction("Сделать скриншот", self.make_shot)
        self.act_tray_rec = m.addAction("Запись экрана", self.start_recording)
        self.act_tray_ocr = m.addAction("Распознать текст", self.make_ocr)
        self.act_tray_stop = m.addAction("⏹ Остановить запись", self._stop_recording)
        self.act_tray_stop.setVisible(False)
        self.act_tray_editors = m.addAction("Показать все редакторы", self._show_all_editors)
        self.act_tray_launcher = m.addAction("Окно «Скриншоты»", self._show_launcher)
        m.addAction("Открыть лог", self._open_log)
        m.addSeparator()
        self.act_tray_exit = m.addAction("Выход", self._quit_from_tray)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        self._update_tray_menu()

    def _update_tray_menu(self):
        has_any = bool(self._editors)
        if hasattr(self, "act_tray_editors"):
            self.act_tray_editors.setEnabled(has_any)

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self._editors:
                self._show_all_editors()
            else:
                self._show_launcher()

    def _show_all_editors(self):
        if not self._editors:
            return
        for ed in self._editors:
            ed.show()
        self._editors[-1].activateWindow()

    def _open_log(self):
        for h in logging.getLogger().handlers:
            h.flush()
        if LOG_PATH.exists():
            QProcess.startDetached("explorer", ["/select,", str(LOG_PATH)])
        else:
            QMessageBox.information(self, "Лог", f"Файла ещё нет:\n{LOG_PATH}")

    def _show_launcher(self):
        self.showNormal()
        self.activateWindow()

    def hotkey_capture(self, mode: str = SelectionOverlay.MODE_SHOT):
        """PrintScreen: сразу выделение области (режим можно сменить на запись/текст)."""
        # Из обработчика нативного события запускать вложенный цикл нельзя —
        # уходим через таймер. Если лаунчер на экране, сначала прячем его.
        delay = 200 if self.isVisible() else 0
        log.info("capture: hotkey -> hotkey_capture (delay=%s)", delay)
        self.hide()
        QTimer.singleShot(delay, lambda: self._capture(mode))

    def make_ocr(self):
        self.hide()
        QTimer.singleShot(200, lambda: self._capture(SelectionOverlay.MODE_OCR))

    def _quit_from_tray(self):
        app = QApplication.instance()
        hotkey = getattr(self, "_hotkey", None)
        if hotkey is not None:
            hotkey.unregister()
            app.removeNativeEventFilter(hotkey)
        if hasattr(app, "_global_hotkey_filter"):
            setattr(app, "_global_hotkey_filter", None)
        self._real_quit = True
        QApplication.instance().quit()

    def start_recording(self):
        if not ffmpeg_path():
            QMessageBox.warning(None, "ffmpeg не найден",
                                "Для записи экрана нужен ffmpeg.exe в папке Data "
                                "рядом с программой (или в PATH).")
            return
        self.hide()
        QTimer.singleShot(200, lambda: self._capture(SelectionOverlay.MODE_RECORD))

    def set_recording_active(self, active: bool, hud=None):
        self._rec_hud = hud if active else None
        if hasattr(self, "act_tray_stop"):
            self.act_tray_stop.setVisible(bool(active))
        if active and hasattr(self, "tray"):
            self.tray.showMessage(
                "Идёт запись экрана",
                "Останови кнопкой ■ Стоп на панели или пунктом «⏹ Остановить запись» в меню трея.",
                QSystemTrayIcon.Information, 4000,
            )

    def _stop_recording(self):
        hud = getattr(self, "_rec_hud", None)
        if hud is not None:
            hud._on_stop()

    def make_shot(self):
        self.hide()
        QTimer.singleShot(200, lambda: self._capture(SelectionOverlay.MODE_SHOT))

    def _capture(self, initial_mode: str) -> None:
        log.info("capture: _capture start mode=%s", initial_mode)
        img = run_capture_flow(initial_mode, self)
        log.info("capture: result %s", None if img is None else f"{img.width()}x{img.height()}")
        if img is not None:
            QApplication.clipboard().setImage(img, QClipboard.Clipboard)
            ed = EditorWindow(img)
            ed.show()
            ed.activateWindow()
            self._add_editor(ed)
        self.hide()

    def _open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Открыть изображение",
            "",
            "Изображения (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Ошибка", "Не удалось открыть файл.")
            return
        ed = EditorWindow(img)
        ed.show()
        ed.activateWindow()
        self._add_editor(ed)

    def closeEvent(self, e):
        if (
            getattr(self, "_real_quit", False)
            or not QSystemTrayIcon.isSystemTrayAvailable()
        ):
            return super().closeEvent(e)

        e.ignore()
        self.hide()

    def _install_global_hotkey(self):
        if not sys.platform.startswith("win"):
            return
        self._hotkey = _WinHotkey(
            QApplication.instance(), self.hotkey_capture,
            lambda: self.hotkey_capture(SelectionOverlay.MODE_OCR),
        )
        log = logging.getLogger(__name__)
        for line in self._hotkey.report:
            log.info("hotkey: %s", line)
        if hasattr(self, "tray"):
            if self._hotkey.registered:
                main = self._hotkey.main_key
                ocr = self._hotkey.ocr_key
                tip = f"NPCore Скриншоты\n{main} — снимок области"
                if ocr:
                    tip += f"\n{ocr} — распознать текст"
                self.tray.setToolTip(tip)
                # Справа в пунктах меню — клавиши (после \t Qt рисует их колонкой).
                self.act_tray_shot.setText(f"Сделать скриншот\t{main}")
                if ocr:
                    self.act_tray_ocr.setText(f"Распознать текст\t{ocr}")
                msg = f"{self._hotkey.description} — выделить область, Tab — снимок / запись / текст."
                if ocr:
                    msg += f"\n{ocr} — сразу распознать текст."
                self.tray.showMessage("NPCore Скриншоты", msg, QSystemTrayIcon.Information, 3000)
            else:
                self.tray.showMessage(
                    "NPCore Скриншоты",
                    "PrintScreen занят другой программой или запрещён политикой. "
                    f"Снимок — через меню трея. Подробности: {LOG_PATH}",
                    QSystemTrayIcon.Warning,
                    8000,
                )


def _asset_path(rel: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / rel


def _load_app_icon() -> QIcon:
    p = _asset_path("Data/Screenshot.ico")
    if p.exists():
        return QIcon(str(p))
    pm = QPixmap(64, 64)
    pm.fill(QColor("#6f42c1"))
    painter = QPainter(pm)
    painter.setPen(QColor("white"))
    f = QFont()
    f.setBold(True)
    f.setPointSize(28)
    painter.setFont(f)
    painter.drawText(pm.rect(), Qt.AlignCenter, "S")
    painter.end()
    return QIcon(pm)


WM_HOTKEY = 0x0312
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WH_KEYBOARD_LL = 13
HC_ACTION = 0
LLKHF_INJECTED = 0x10
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
VK_SNAPSHOT = 0x2C
VK_ESCAPE = 0x1B
VK_TAB = 0x09
# Некоторые клавиатуры/ноутбуки шлют на PrtSc «пустой» код vk=0xFF, scan=0
# (клавиша обрабатывается драйвером производителя) — Windows его PrintScreen
# не считает. Ловим и его тоже. Клавишу не глотаем: на 0xFF могут висеть
# и другие функции производителя.
VK_OEM_PRTSC_ALT = 0xFF
VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C
ERROR_HOTKEY_ALREADY_REGISTERED = 1409


def _snipping_owns_printscreen() -> Optional[bool]:
    """Windows 11: «Использовать PrintScreen для открытия Ножниц».

    True — система забирает клавишу себе, обычный RegisterHotKey её не получит.
    None — прочитать не удалось.
    """
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Keyboard") as key:
            value, _ = winreg.QueryValueEx(key, "PrintScreenKeyForSnipping")
            return bool(value)
    except FileNotFoundError:
        # Нет значения: в свежих сборках Windows 11 это означает «включено».
        return sys.getwindowsversion().build >= 22000
    except Exception:
        return None


def _ll_printscreen_action(vk: int, msg: int, flags: int, modifiers_down: bool, pressed: bool):
    """Решение для низкоуровневого хука: (поглотить клавишу, сделать снимок, новое pressed).

    Обычный PrintScreen перехватываем целиком (и нажатие, и отпускание), чтобы его не
    получили Ножницы и другие программы. Alt+PrtSc, Win+PrtSc и т.п. не трогаем.
    Повтор при удержании не запускает снимок второй раз. Некоторые клавиатуры шлют
    только отпускание — тогда снимок по отпусканию.
    """
    if vk != VK_SNAPSHOT or flags & LLKHF_INJECTED:
        return False, False, pressed
    down = msg in (WM_KEYDOWN, WM_SYSKEYDOWN)
    up = msg in (WM_KEYUP, WM_SYSKEYUP)
    if not (down or up):
        return False, False, pressed
    if down:
        if modifiers_down:
            return False, False, False
        return True, not pressed, True
    if modifiers_down and not pressed:
        return False, False, False
    return True, not pressed, False


WM_QUIT = 0x0012


class _HookBridge(QObject):
    """Переносит срабатывание из потока хука в главный поток Qt (queued-сигнал)."""
    fired = Signal()
    fired_ocr = Signal()
    overlay_key = Signal(int)

    def __init__(self, cb, cb_ocr=None):
        super().__init__()
        self._cb = cb
        self._cb_ocr = cb_ocr
        self.fired.connect(self._on_fired, Qt.QueuedConnection)
        self.fired_ocr.connect(self._on_fired_ocr, Qt.QueuedConnection)
        self.overlay_key.connect(self._on_overlay_key, Qt.QueuedConnection)

    @Slot()
    def _on_fired(self):
        self._cb()

    @Slot()
    def _on_fired_ocr(self):
        if self._cb_ocr is not None:
            self._cb_ocr()

    @Slot(int)
    def _on_overlay_key(self, vk: int):
        ov = SelectionOverlay.active
        if ov is None:
            return
        if vk == VK_ESCAPE:
            ov._cancel()
        elif vk == VK_TAB:
            ov.toggle_mode()


class _WinHotkey(QAbstractNativeEventFilter):
    """PrintScreen → снимок.

    1) Низкоуровневый хук клавиатуры: срабатывает раньше системных горячих клавиш,
       поэтому перехватывает PrintScreen, даже если его забрали Ножницы Windows 11,
       Lightshot, OneDrive и т.п.
    2) RegisterHotKey для Ctrl+Alt+PrintScreen всегда и для PrintScreen, если хук
       поставить не удалось (например, запретил антивирус или политика).
    """

    def __init__(self, app: QApplication, callback, ocr_callback=None):
        super().__init__()
        self._app = app
        self._cb = callback
        self._ocr_cb = ocr_callback
        self._ids: List[int] = []
        self._keys: List[str] = []
        self._ocr_keys: List[str] = []
        self.report: List[str] = []
        self._hook = None
        self._hook_proc = None
        self._hook_thread: Optional[threading.Thread] = None
        self._hook_tid = 0
        self._pressed = False
        self._last_fire = 0.0
        self._bridge = _HookBridge(self._fire, self._fire_ocr)

        self._u32 = ctypes.WinDLL("user32", use_last_error=True)
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        LRESULT = ctypes.c_ssize_t
        self._HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        u = self._u32
        u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        u.RegisterHotKey.restype = wintypes.BOOL
        u.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        u.UnregisterHotKey.restype = wintypes.BOOL
        u.SetWindowsHookExW.argtypes = [ctypes.c_int, self._HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        u.SetWindowsHookExW.restype = wintypes.HHOOK
        u.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        u.CallNextHookEx.restype = LRESULT
        u.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        u.UnhookWindowsHookEx.restype = wintypes.BOOL
        u.GetAsyncKeyState.argtypes = [ctypes.c_int]
        u.GetAsyncKeyState.restype = ctypes.c_short
        self._k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self._k32.GetModuleHandleW.restype = wintypes.HMODULE
        self._k32.GetCurrentThreadId.restype = wintypes.DWORD
        u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        u.GetMessageW.restype = wintypes.BOOL
        u.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.PostThreadMessageW.restype = wintypes.BOOL

        snipping = _snipping_owns_printscreen()
        if snipping:
            self.report.append("Windows отдаёт PrintScreen Ножницам — перехватываю хуком раньше них")

        hook_ok = self._install_hook()
        reg_ok = self._register(1, MOD_NOREPEAT, VK_SNAPSHOT, "PrintScreen")
        if hook_ok or reg_ok:
            self._keys.append("PrintScreen")
            if not hook_ok and snipping:
                self.report.append("Хук недоступен, а PrintScreen у Ножниц: отключи "
                                   "«Параметры → Специальные возможности → Клавиатура → "
                                   "Использовать PrintScreen для открытия Ножниц»")
        if self._register(2, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_SNAPSHOT, "Ctrl+Alt+PrintScreen"):
            self._keys.append("Ctrl+Alt+PrintScreen")
        if ocr_callback is not None:
            # Shift+PrintScreen хук пропускает (есть модификатор) — его ловит RegisterHotKey.
            # Клавиатуры с PrtSc = vk 0xFF RegisterHotKey не видит — их Shift+PrtSc ловит хук.
            if self._register(3, MOD_SHIFT | MOD_NOREPEAT, VK_SNAPSHOT, "Shift+PrintScreen (текст)") or hook_ok:
                self._ocr_keys.append("Shift+PrintScreen")

        if self._ids:
            app.installNativeEventFilter(self)
            setattr(app, "_global_hotkey_filter", self)
        self.report.append("активны: " + (", ".join(self._keys) or "ничего"))

    # ── регистрация ──
    def _register(self, ident: int, mods: int, vk: int, desc: str) -> bool:
        if self._u32.RegisterHotKey(None, ident, mods, vk):
            self._ids.append(ident)
            self.report.append(f"RegisterHotKey {desc}: ок")
            return True
        err = ctypes.get_last_error()
        why = "занята другой программой" if err == ERROR_HOTKEY_ALREADY_REGISTERED else f"ошибка {err}"
        self.report.append(f"RegisterHotKey {desc}: {why}")
        return False

    def _install_hook(self) -> bool:
        """Хук ставится в ОТДЕЛЬНОМ потоке со своим циклом сообщений.

        Раньше хук жил в главном потоке Qt. Пока он занят (ffmpeg-зонд, заливка,
        сборка снимка, открытие редактора), Windows не дожидается ответа хука
        (LowLevelHooksTimeout) и молча его снимает — после этого PrintScreen
        уходил Ножницам, а снимок не делался.
        """
        ready = threading.Event()
        result = {"ok": False, "err": 0}

        def run():
            self._hook_tid = int(self._k32.GetCurrentThreadId())
            proc = self._HOOKPROC(self._on_key)   # ссылка обязательна, иначе GC
            hook = self._u32.SetWindowsHookExW(WH_KEYBOARD_LL, proc,
                                               self._k32.GetModuleHandleW(None), 0)
            if not hook:
                result["err"] = ctypes.get_last_error()
                ready.set()
                return
            self._hook_proc = proc
            self._hook = hook
            result["ok"] = True
            ready.set()
            msg = wintypes.MSG()
            # LL-хук вызывается внутри GetMessage этого потока; выход — по WM_QUIT.
            while self._u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                pass
            self._u32.UnhookWindowsHookEx(hook)
            self._hook = None

        self._hook_thread = threading.Thread(target=run, name="kbd-ll-hook", daemon=True)
        self._hook_thread.start()
        ready.wait(3.0)
        if not result["ok"]:
            self.report.append(f"хук клавиатуры: ошибка {result['err']}")
            return False
        self.report.append("хук клавиатуры: ок (отдельный поток)")
        return True

    def _shift_only_down(self) -> bool:
        ks = self._u32.GetAsyncKeyState
        return bool(ks(VK_SHIFT) & 0x8000) and not any(
            ks(vk) & 0x8000 for vk in (VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN))

    def _modifiers_down(self) -> bool:
        return any(self._u32.GetAsyncKeyState(vk) & 0x8000
                   for vk in (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN))

    def _on_key(self, n_code, w_param, l_param):
        try:
            if n_code == HC_ACTION:
                info = ctypes.cast(l_param, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                if (SelectionOverlay.active is not None
                        and info.vkCode in (VK_ESCAPE, VK_TAB)
                        and not info.flags & LLKHF_INJECTED):
                    # Слой выделения открыт: Esc — отмена, Tab — смена режима.
                    # Глотаем и нажатие, и отпускание, чтобы клавиша не ушла в
                    # окно под слоем.
                    if int(w_param) in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        self._bridge.overlay_key.emit(int(info.vkCode))
                    return 1
                if (info.vkCode == VK_OEM_PRTSC_ALT and info.scanCode == 0
                        and not info.flags & LLKHF_INJECTED
                        and int(w_param) in (WM_KEYDOWN, WM_SYSKEYDOWN)
                        and not self._modifiers_down()):
                    log.info("hook: vk=0xFF scan=0 (PrtSc этой клавиатуры) -> fire")
                    self._bridge.fired.emit()
                elif (info.vkCode == VK_OEM_PRTSC_ALT and info.scanCode == 0
                        and not info.flags & LLKHF_INJECTED
                        and int(w_param) in (WM_KEYDOWN, WM_SYSKEYDOWN)
                        and self._shift_only_down()):
                    # Shift+PrtSc на клавиатуре, которая шлёт vk=0xFF: RegisterHotKey
                    # его не увидит, поэтому распознавание текста запускаем отсюда.
                    log.info("hook: Shift + vk=0xFF -> ocr")
                    self._bridge.fired_ocr.emit()
                elif info.vkCode == VK_SNAPSHOT:
                    mods = self._modifiers_down()
                    swallow, fire, self._pressed = _ll_printscreen_action(
                        info.vkCode, int(w_param), info.flags, mods, self._pressed)
                    log.info("hook: PrintScreen msg=0x%X flags=0x%X mods=%s -> swallow=%s fire=%s",
                             int(w_param), int(info.flags), mods, swallow, fire)
                    if fire:
                        # Мы в потоке хука: в главный поток Qt — через queued-сигнал.
                        self._bridge.fired.emit()
                    if swallow:
                        return 1
        except Exception:
            logging.getLogger(__name__).error("keyboard hook failed:\n%s", traceback.format_exc())
        return self._u32.CallNextHookEx(None, n_code, w_param, l_param)

    def _fire(self):
        now = time.monotonic()
        if now - self._last_fire < 0.3:   # хук и RegisterHotKey не должны дать двойной снимок
            return
        self._last_fire = now
        log.info("capture: hotkey fired")
        try:
            self._cb()
        except Exception:
            logging.getLogger(__name__).error(
                "Global hotkey callback failed:\n%s", traceback.format_exc()
            )

    def _fire_ocr(self):
        now = time.monotonic()
        if now - self._last_fire < 0.3:
            return
        self._last_fire = now
        log.info("capture: ocr hotkey fired")
        if self._ocr_cb is None:
            return
        try:
            self._ocr_cb()
        except Exception:
            logging.getLogger(__name__).error(
                "OCR hotkey callback failed:\n%s", traceback.format_exc()
            )

    @property
    def registered(self) -> bool:
        return bool(self._keys)

    @property
    def description(self) -> str:
        return " или ".join(self._keys)

    @property
    def main_key(self) -> str:
        return self._keys[0] if self._keys else ""

    @property
    def ocr_key(self) -> str:
        return self._ocr_keys[0] if self._ocr_keys else ""

    def unregister(self):
        if self._hook_thread is not None and self._hook_thread.is_alive() and self._hook_tid:
            self._u32.PostThreadMessageW(self._hook_tid, WM_QUIT, 0, 0)
            self._hook_thread.join(1.0)
        self._hook_thread = None
        for ident in self._ids:
            self._u32.UnregisterHotKey(None, ident)
        self._ids = []
        self._keys = []
        self._ocr_keys = []

    def nativeEventFilter(self, eventType, message):
        try:
            addr = message.__int__() if hasattr(message, "__int__") else int(message)
            msg = wintypes.MSG.from_address(addr)
        except Exception:
            return (False, 0)
        if msg.message == WM_HOTKEY and msg.wParam in self._ids:
            log.info("hotkey: WM_HOTKEY id=%s", msg.wParam)
            if msg.wParam == 3:
                self._fire_ocr()
            else:
                self._fire()
            return (True, 0)
        return (False, 0)


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


def _register_editor_in_launcher(ed: "EditorWindow"):
    app = QApplication.instance()
    for w in app.topLevelWidgets():
        if isinstance(w, Launcher):
            w._add_editor(ed)
            break

LOG_PATH = DATA_DIR / "screenshot_editor.log"


def _setup_logging() -> None:
    root = logging.getLogger()
    had_handlers = bool(root.handlers)
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    target = str(LOG_PATH.resolve())
    already = any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == target
                  for h in root.handlers)
    if not already:
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(target, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except Exception:
            pass
    logging.getLogger(__name__).info("log file: %s", target)
    if had_handlers:
        return
    if sys.stderr is not None:  # под pythonw stderr отсутствует
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

    def _excepthook(exc_type, exc, tb):
        # Исключения в слотах Qt иначе печатаются только в stderr — под pythonw теряются.
        logging.getLogger("unhandled").error("Unhandled exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = _excepthook

# ============================================================================
# ЗАПИСЬ ЭКРАНА (встроено) — ffmpeg gdigrab: захват региона, обрезка,
# аннотации (через штатный редактор), буфер обмена файлом (CF_HDROP).
# Нужен ffmpeg.exe и желательно ffprobe.exe в папке Data/ (или в PATH).
# ============================================================================
_CREATE_NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0
DEFAULT_FPS = 30

def _rec_tmp_dir() -> Path:
    d = DATA_DIR / "_rec_tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


_REC_TMP_MAX_AGE_DAYS = 7


def _cleanup_rec_tmp(max_age_days: float = _REC_TMP_MAX_AGE_DAYS) -> None:
    """Удаляет из Data/_rec_tmp записи и экспорты старше max_age_days.

    Раньше каждая запись и каждый экспорт оставались там навсегда.
    Занятые файлы (открыты другой программой) пропускаются.
    """
    d = DATA_DIR / "_rec_tmp"
    if not d.is_dir():
        return
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for p in d.iterdir():
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            pass
    if removed:
        log.info("rec_tmp cleanup: removed %d old file(s)", removed)


# ── поиск ffmpeg / ffprobe ───────────────────────────────────────────────────
_binary_cache: dict[str, str] = {}


def _find_binary(name: str) -> Optional[str]:
    """Ищет ffmpeg/ffprobe: Data, корень, распакованный архив в Data, PATH, winget.

    Найденный путь кэшируется (пока файл на месте); «не найдено» не кэшируется,
    чтобы положенный позже ffmpeg подхватился без перезапуска.
    """
    cached = _binary_cache.get(name)
    if cached and Path(cached).is_file():
        return cached
    exe = f"{name}.exe" if sys.platform.startswith("win") else name
    found = _search_binary(name, exe)
    if found:
        _binary_cache[name] = found
    return found


def _search_binary(name: str, exe: str) -> Optional[str]:
    for base in (DATA_DIR, ROOT_DIR, DATA_DIR / "ffmpeg" / "bin"):
        p = Path(base) / exe
        if p.is_file():
            return str(p)
    # Архив ffmpeg, распакованный в Data как есть:
    # Data\ffmpeg-7.1-essentials_build\bin\ffmpeg.exe и т.п.
    for pattern in (f"*/{exe}", f"*/bin/{exe}", f"*/*/bin/{exe}"):
        try:
            for p in sorted(DATA_DIR.glob(pattern)):
                if p.is_file():
                    return str(p)
        except OSError:
            pass
    found = shutil.which(exe) or shutil.which(name)
    if found:
        return found
    # winget install Gyan.FFmpeg кладёт ffmpeg сюда и не всегда прописывает PATH.
    local = os.environ.get("LOCALAPPDATA")
    if local:
        packages = Path(local) / "Microsoft" / "WinGet" / "Packages"
        try:
            for p in sorted(packages.glob(f"*FFmpeg*/*/bin/{exe}")):
                if p.is_file():
                    return str(p)
        except OSError:
            pass
    return None


def ffmpeg_path() -> Optional[str]:
    return _find_binary("ffmpeg")


def ffprobe_path() -> Optional[str]:
    return _find_binary("ffprobe")


def _run(args: list[str], timeout: float = 20.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=_CREATE_NO_WINDOW,
    )


# ── зондирование видео ───────────────────────────────────────────────────────
def probe_media(path: str) -> Tuple[Optional[int], Optional[int], Optional[float]]:
    """Возвращает (width, height, duration_sec) через ffprobe; при неудаче None."""
    ff = ffprobe_path()
    if not ff:
        return (None, None, None)
    try:
        r = _run([
            ff, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-show_entries", "format=duration",
            "-of", "json", path,
        ])
        data = json.loads(r.stdout or "{}")
        st = (data.get("streams") or [{}])[0]
        w = int(st.get("width")) if st.get("width") else None
        h = int(st.get("height")) if st.get("height") else None
        dur = data.get("format", {}).get("duration")
        dur = float(dur) if dur else None
        return (w, h, dur)
    except Exception:
        log.exception("probe_media failed")
        return (None, None, None)


def extract_poster(src: str, t_sec: float, dst: str) -> bool:
    """Вытаскивает один кадр в PNG (нативное разрешение) для авторинга оверлея."""
    ff = ffmpeg_path()
    if not ff:
        return False
    try:
        # -ss перед -i — быстрый переход по ключевым кадрам (при извлечении кадра
        # ffmpeg всё равно точно доходит до нужного момента); раньше видео
        # декодировалось с начала, и на длинных записях превью тормозило.
        _run([ff, "-y", "-ss", f"{max(0.0, t_sec):.3f}", "-i", src,
              "-frames:v", "1", dst], timeout=30.0)
        return Path(dst).exists()
    except Exception:
        log.exception("extract_poster failed")
        return False


# ── перечисление dshow-аудиоустройств ────────────────────────────────────────
def list_dshow_audio() -> List[str]:
    ff = ffmpeg_path()
    if not ff or not sys.platform.startswith("win"):
        return []
    try:
        r = _run([ff, "-hide_banner", "-list_devices", "true",
                  "-f", "dshow", "-i", "dummy"], timeout=10.0)
    except Exception:
        return []
    names: List[str] = []
    audio_section = False
    for line in (r.stderr or "").splitlines():
        low = line.lower()
        if "directshow audio devices" in low:
            audio_section = True
            continue
        if "directshow video devices" in low:
            audio_section = False
            continue
        if '"' in line:
            try:
                name = line.split('"')[1]
            except IndexError:
                continue
            if "(audio)" in low or audio_section:
                if name and name not in names:
                    names.append(name)
    return names


def guess_system_audio(devices: List[str]) -> Optional[str]:
    keys = ("stereo mix", "стерео микшер", "what u hear", "virtual-audio-capturer",
            "loopback", "cable output")
    for d in devices:
        dl = d.lower()
        if any(k in dl for k in keys):
            return d
    return None


# ── буфер обмена: положить файл (CF_HDROP) ───────────────────────────────────
def put_file_on_clipboard(path: str | Path) -> bool:
    try:
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(str(path))])
        QApplication.clipboard().setMimeData(md)
        return True
    except Exception:
        log.exception("put_file_on_clipboard failed")
        return False


# ── физический прямоугольник для gdigrab ─────────────────────────────────────
def _physical_rect(region: QRect) -> Tuple[int, int, int, int]:
    """
    region — глобальный логический QRect (как отдаёт SelectionOverlay).
    Пересчёт в физические пиксели для gdigrab по DPR экрана под центром
    выделения. Начало экрана в Qt совпадает с нативными координатами, а внутри
    экрана всё масштабировано, поэтому сдвиг считаем от его левого верхнего
    угла (раньше умножались абсолютные координаты — на втором мониторе с
    масштабом запись уезжала). При выделении через мониторы с разным DPI
    берётся масштаб экрана под центром.
    """
    center = region.center()
    scr = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
    dpr = float(scr.devicePixelRatio()) if scr else 1.0
    origin = scr.geometry().topLeft() if scr else QPoint(0, 0)
    x = origin.x() + int(round((region.left() - origin.x()) * dpr))
    y = origin.y() + int(round((region.top() - origin.y()) * dpr))
    w = int(round(region.width() * dpr))
    h = int(round(region.height() * dpr))
    # libx264 требует чётные размеры
    w -= w % 2
    h -= h % 2
    return (x, y, max(2, w), max(2, h))


# ── выбор области (переиспользуем SelectionOverlay), возвращает QRect ─────────
def select_region_rect() -> Optional[QRect]:
    overlay = SelectionOverlay()
    try:
        r = _run_selection(overlay)
    finally:
        overlay.dispose()
    if r is None or r.width() < 4 or r.height() < 4:
        return None
    return r


# ── построение команд ffmpeg ─────────────────────────────────────────────────
def build_record_cmd(out: str, rect: QRect, fps: int,
                     audio_mode: str, audio_device: Optional[str],
                     draw_mouse: bool = True) -> list[str]:
    ff = ffmpeg_path()
    x, y, w, h = _physical_rect(rect)
    a = [ff, "-y",
         "-f", "gdigrab", "-framerate", str(fps),
         "-offset_x", str(x), "-offset_y", str(y),
         "-video_size", f"{w}x{h}",
         "-draw_mouse", "1" if draw_mouse else "0",
         "-i", "desktop"]
    if audio_mode in ("mic", "system") and audio_device:
        a += ["-f", "dshow", "-i", f"audio={audio_device}",
              "-c:a", "aac", "-b:a", "160k", "-map", "0:v", "-map", "1:a"]
    a += ["-c:v", "libx264", "-pix_fmt", "yuv420p",
          "-preset", "veryfast", "-crf", "20",
          "-g", str(fps), "-keyint_min", str(fps),
          "-movflags", "+faststart", out]
    return a


def build_export_cmd(src: str, dst: str, t_in: float, t_out: float,
                    censors: List[dict], overlay_png: Optional[str],
                    native_wh: Tuple[int, int]) -> list[str]:
    """
    censors: список {'x','y','w','h','mode'} в НАТИВНЫХ пикселях видео,
             mode in {'blur','pixelate'}.
    overlay_png: путь к прозрачному PNG размера native_wh (или None).
    Без правок → потоковая обрезка -c copy (быстро, без потерь).
    """
    ff = ffmpeg_path()
    has_edits = bool(censors) or bool(overlay_png)
    t_in = max(0.0, float(t_in))
    t_out = max(t_in + 0.05, float(t_out))

    dur = t_out - t_in

    if not has_edits:
        # Точная обрезка: -ss (вход) + -t (длительность) с перекодированием.
        # -c copy на коротких записях с одним ключевым кадром не режет.
        return [ff, "-y", "-ss", f"{t_in:.3f}", "-i", src, "-t", f"{dur:.3f}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-preset", "veryfast", "-crf", "20", "-c:a", "aac",
                "-movflags", "+faststart", dst]

    args = [ff, "-y", "-ss", f"{t_in:.3f}", "-i", src]
    overlay_idx = None
    if overlay_png:
        args += ["-loop", "1", "-i", overlay_png]
        overlay_idx = 1

    # filter_complex: цепочка «замазок», затем статичный оверлей
    parts: list[str] = []
    cur = "0:v"
    for i, c in enumerate(censors):
        cx, cy = int(c["x"]), int(c["y"])
        cw, ch = max(2, int(c["w"])), max(2, int(c["h"]))
        side = min(cw, ch)
        if c.get("mode") == "pixelate":
            block = max(4, side // 8)
            reg = (f"crop={cw}:{ch}:{cx}:{cy},"
                   f"scale={max(1, cw // block)}:{max(1, ch // block)}:flags=neighbor,"
                   f"scale={cw}:{ch}:flags=neighbor")
        else:
            # boxblur требует радиус ≤ половины стороны, а цветность в yuv420p —
            # в половинном разрешении. Раньше радиус был не меньше 6, и замазка
            # небольшой области (строка текста) роняла экспорт.
            luma_r = max(1, min(max(6, side // 6), side // 2 - 1))
            chroma_r = max(0, min(luma_r, side // 4 - 1))
            reg = (f"crop={cw}:{ch}:{cx}:{cy},"
                   f"boxblur=luma_radius={luma_r}:luma_power=1:"
                   f"chroma_radius={chroma_r}:chroma_power=1")
        # Метку потока в filter_complex можно использовать только один раз:
        # раньше [cv0] шла и в crop, и в overlay — со второй замазкой ffmpeg
        # падал. split раздваивает поток явно.
        parts.append(f"[{cur}]split[base{i}][src{i}]")
        parts.append(f"[src{i}]{reg}[cb{i}]")
        parts.append(f"[base{i}][cb{i}]overlay={cx}:{cy}[cv{i}]")
        cur = f"cv{i}"

    if overlay_idx is not None:
        parts.append(f"[{cur}][{overlay_idx}:v]overlay=0:0:format=auto[vout]")
        vlabel = "vout"
    else:
        vlabel = cur

    args += ["-filter_complex", ";".join(parts),
             "-map", f"[{vlabel}]", "-map", "0:a?",
             "-t", f"{dur:.3f}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-preset", "veryfast", "-crf", "18",
             "-c:a", "aac", "-shortest",
             "-movflags", "+faststart", dst]
    return args


# ── HUD записи: плавающая панелька рядом с областью ──────────────────────────
class RecordHUD(QWidget):
    finished = Signal(str)   # путь к готовому mp4
    cancelled = Signal()

    def __init__(self, region: QRect, launcher=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self._launcher = launcher
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.region = region
        self._proc: Optional[QProcess] = None
        self._out_path: Optional[str] = None
        self._t0 = 0.0
        self._recording = False
        self._done = False
        self._devices = list_dshow_audio()

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(8)

        self.audio_combo = QComboBox(self)
        self.audio_combo.addItem("Без звука", ("none", None))
        sysdev = guess_system_audio(self._devices)
        if sysdev:
            self.audio_combo.addItem("Системный звук", ("system", sysdev))
        for d in self._devices:
            if d != sysdev:
                self.audio_combo.addItem(f"Микрофон: {d}", ("mic", d))
        root.addWidget(self.audio_combo)

        self.time_lbl = QLabel("00:00", self)
        self.time_lbl.setStyleSheet("font-weight:bold; min-width:44px;")
        root.addWidget(self.time_lbl)

        self.start_btn = QPushButton("● Старт", self)
        self.start_btn.clicked.connect(self._on_start)
        root.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("✕", self)
        self.cancel_btn.setFixedWidth(28)
        self.cancel_btn.clicked.connect(self._on_cancel)
        root.addWidget(self.cancel_btn)

        self.setStyleSheet(
            "QWidget{background:#202124;color:#eee;border-radius:8px;}"
            "QPushButton{background:#3c4043;border:none;padding:4px 10px;border-radius:6px;}"
            "QPushButton:hover{background:#5f6368;}"
            "QComboBox{background:#3c4043;border:none;padding:3px 6px;border-radius:6px;}"
        )

        self._tick = QTimer(self); self._tick.setInterval(250)
        self._tick.timeout.connect(self._update_time)

        self.adjustSize()
        self._place()

    def _place(self) -> None:
        """Панель ставится ВНЕ области (сверху, иначе снизу), чтобы не попасть в кадр."""
        self.adjustSize()
        w = self.width(); h = self.height()
        scr = QGuiApplication.screenAt(self.region.center()) or QGuiApplication.primaryScreen()
        geo = scr.availableGeometry() if scr else QRect(0, 0, 1920, 1080)
        x = self.region.center().x() - w // 2
        y = self.region.top() - h - 8
        if y < geo.top():
            y = self.region.bottom() + 8
        x = max(geo.left(), min(x, geo.right() - w))
        y = max(geo.top(), min(y, geo.bottom() - h))
        self.move(x, y)

    # ── старт/стоп ────────────────────────────────────────────────────────────
    def _on_start(self) -> None:
        ff = ffmpeg_path()
        if not ff:
            QMessageBox.warning(self, "ffmpeg не найден",
                                "Положи ffmpeg.exe в папку Data рядом с программой.")
            return
        mode, dev = self.audio_combo.currentData()
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        self._out_path = str(_rec_tmp_dir() / f"rec_{stamp}.mp4")
        cmd = build_record_cmd(self._out_path, self.region, DEFAULT_FPS, mode, dev)

        self._proc = QProcess(self)
        if sys.platform.startswith("win"):
            # прячем консоль ffmpeg
            def _mod(args):
                args.flags |= _CREATE_NO_WINDOW
            try:
                self._proc.setCreateProcessArgumentsModifier(_mod)
            except Exception:
                pass
        self._proc.setProgram(cmd[0])
        self._proc.setArguments(cmd[1:])
        self._proc.finished.connect(self._on_proc_finished)
        self._proc.errorOccurred.connect(self._on_proc_error)
        log.info("REC start: %s", " ".join(cmd))
        self._proc.start()
        if not self._proc.waitForStarted(4000):
            emsg = self._proc.errorString()
            log.error("REC ffmpeg failed to start: %s", emsg)
            QMessageBox.warning(self, "Ошибка", f"Не удалось запустить ffmpeg:\n{emsg}")
            self._proc = None
            return
        log.info("REC recording -> %s", self._out_path)

        self._recording = True
        self._t0 = time.monotonic()
        self._tick.start()
        self.audio_combo.setEnabled(False)
        self.start_btn.setText("■ Стоп")
        self.start_btn.clicked.disconnect()
        self.start_btn.clicked.connect(self._on_stop)
        self.start_btn.setStyleSheet("background:#a50e0e;")
        if self._launcher is not None:
            try:
                self._launcher.set_recording_active(True, self)
            except Exception:
                pass

    def _on_stop(self) -> None:
        if not self._proc or not self._recording:
            return
        self._recording = False
        self._tick.stop()
        self.start_btn.setEnabled(False)
        self.start_btn.setText("…")
        # Мягкая остановка: 'q' в stdin → ffmpeg дописывает moov-атом.
        # Финализация АСИНХРОННО в _on_proc_finished: без вложенного
        # waitForFinished, из-за которого self мог удаляться до emit.
        try:
            self._proc.write(b"q")
            self._proc.closeWriteChannel()
        except Exception:
            pass
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._force_finish)
        self._kill_timer.start(7000)

    def _force_finish(self) -> None:
        # ffmpeg не завершился по 'q' за отведённое время — дожимаем
        if self._proc and self._proc.state() != QProcess.NotRunning:
            self._proc.kill()

    def _on_cancel(self) -> None:
        self._done = True
        if self._proc and self._recording:
            self._recording = False
            self._tick.stop()
            try:
                self._proc.write(b"q"); self._proc.closeWriteChannel()
            except Exception:
                pass
            self._proc.waitForFinished(3000)
            self._proc.kill()
        if self._out_path and Path(self._out_path).exists():
            try:
                Path(self._out_path).unlink()
            except Exception:
                pass
        self.cancelled.emit()
        self.close()

    def _on_proc_finished(self, code, status) -> None:
        if self._done:
            return
        self._done = True
        kt = getattr(self, "_kill_timer", None)
        if kt is not None:
            kt.stop()
        try:
            err_tail = ""
            try:
                err_tail = bytes(self._proc.readAllStandardError()).decode("utf-8", "replace")
            except Exception:
                pass
            out = self._out_path
            exists = bool(out and Path(out).exists())
            size = Path(out).stat().st_size if exists else 0
            log.info("REC finished: code=%s exists=%s size=%s path=%s", code, exists, size, out)
            if err_tail:
                log.info("REC ffmpeg stderr tail:\n%s", err_tail[-2000:])
            if exists and size > 0:
                self.finished.emit(out)   # emit ДО close
            else:
                QMessageBox.warning(
                    None, "Запись не удалась",
                    "ffmpeg не создал файл (код выхода " + str(code) + ").\n\n"
                    "Последние строки ffmpeg:\n" + (err_tail[-1200:] or "(пусто)"))
                self.cancelled.emit()
        except Exception:
            tb = traceback.format_exc()
            log.error("REC post-finish handling failed:\n%s", tb)
            try:
                QMessageBox.critical(None, "Ошибка после записи", tb[-1500:])
            except Exception:
                pass
        finally:
            self.close()

    def _on_proc_error(self, err) -> None:
        try:
            log.error("ffmpeg QProcess error: %s (%s)", err,
                      self._proc.errorString() if self._proc else "")
        except Exception:
            log.error("ffmpeg QProcess error: %s", err)

    def _update_time(self) -> None:
        s = int(time.monotonic() - self._t0)
        self.time_lbl.setText(f"{s // 60:02d}:{s % 60:02d}")

    def closeEvent(self, e):
        try:
            if self._launcher is not None:
                self._launcher.set_recording_active(False, None)
        except Exception:
            pass
        if self in _active_huds:
            _active_huds.remove(self)
        super().closeEvent(e)


# ── виджет рисования «замазок» поверх видео ──────────────────────────────────
class _CensorOverlay(QWidget):
    def __init__(self, parent, get_video_rect: Callable[[], QRectF]):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._get_video_rect = get_video_rect     # видимый прямоугольник видео (letterbox) в px виджета
        self.rects: List[QRectF] = []             # в координатах виджета
        self._drag_from: Optional[QPointF] = None
        self._drag_cur: Optional[QPointF] = None
        self.enabled = False

    def set_enabled(self, flag: bool):
        self.enabled = flag
        self.setCursor(Qt.CrossCursor if flag else Qt.ArrowCursor)
        self.update()

    def mousePressEvent(self, e: QMouseEvent):
        if not self.enabled or e.button() != Qt.LeftButton:
            return
        self._drag_from = e.position()
        self._drag_cur = e.position()
        self.update()

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._drag_from is not None:
            self._drag_cur = e.position()
            self.update()

    def mouseReleaseEvent(self, e: QMouseEvent):
        if self._drag_from is not None and self._drag_cur is not None:
            r = QRectF(self._drag_from, self._drag_cur).normalized()
            if r.width() > 6 and r.height() > 6:
                self.rects.append(r)
            self._drag_from = self._drag_cur = None
            self.update()

    def clear(self):
        self.rects.clear()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        pen = QPen(QColor(255, 60, 60), 2, Qt.DashLine)
        for r in self.rects:
            p.setPen(pen)
            p.setBrush(QColor(255, 60, 60, 40))
            p.drawRect(r)
        if self._drag_from is not None and self._drag_cur is not None:
            p.setPen(QPen(QColor(255, 200, 0), 2, Qt.SolidLine))
            p.setBrush(QColor(255, 200, 0, 30))
            p.drawRect(QRectF(self._drag_from, self._drag_cur).normalized())
        p.end()

    def to_native(self, native_w: int, native_h: int) -> List[dict]:
        """Перевод прямоугольников из координат виджета в нативные пиксели видео."""
        vr = self._get_video_rect()
        if vr.width() < 1 or vr.height() < 1:
            return []
        sx = native_w / vr.width()
        sy = native_h / vr.height()
        out: List[dict] = []
        for r in self.rects:
            nx = int(round((r.left() - vr.left()) * sx))
            ny = int(round((r.top() - vr.top()) * sy))
            nw = int(round(r.width() * sx))
            nh = int(round(r.height() * sy))
            nx = max(0, min(nx, native_w - 2))
            ny = max(0, min(ny, native_h - 2))
            nw = max(2, min(nw, native_w - nx))
            nh = max(2, min(nh, native_h - ny))
            out.append({"x": nx, "y": ny, "w": nw, "h": nh, "mode": "blur"})
        return out


# ── окно редактора видео: превью + обрезка + замазки + аннотации + экспорт ────
def _take_mjpeg_frame(buffer: bytes) -> tuple[bytes | None, bytes]:
    """Extract one complete JPEG from an FFmpeg MJPEG byte stream, bounded to 12 MiB."""
    start = buffer.find(b"\xff\xd8")
    if start == -1:
        return None, buffer[-1:] if buffer.endswith(b"\xff") else b""
    if start:
        buffer = buffer[start:]
    end = buffer.find(b"\xff\xd9", 2)
    if end == -1:
        return None, buffer if len(buffer) <= 12 * 1024 * 1024 else b""
    return buffer[:end + 2], buffer[end + 2:]


class VideoEditorWindow(QMainWindow):
    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактор видео")
        self.resize(1000, 720)
        self.setWindowIcon(_load_app_icon())
        self.src = video_path
        self._overlay_png: Optional[str] = None
        self._native = probe_media(video_path)
        nw, nh, dur = self._native
        self._native_w = nw or 1920
        self._native_h = nh or 1080
        self._duration_ms = int((dur or 0) * 1000)
        self._in_ms = 0
        self._out_ms = self._duration_ms
        self._export_proc: Optional[QProcess] = None
        self._play_proc: Optional[QProcess] = None
        self._play_buffer = b""
        self._play_origin_ms = 0
        self._play_wall = 0.0
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(100)
        self._play_timer.timeout.connect(self._play_tick)

        self._build_ui()
        self._init_preview()

        # видео сразу в буфер (файлом), как и просили
        put_file_on_clipboard(self.src)
        self.statusBar().showMessage("Записанное видео скопировано в буфер (как файл).", 4000)

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        from PySide6.QtWidgets import QDoubleSpinBox
        central = QWidget(self)
        self.setCentralWidget(central)
        v = QVBoxLayout(central)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        self.video_host = QWidget(self)
        self.video_host.setMinimumHeight(360)
        self.video_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(self.video_host, 1)

        # ползунок позиции (перемотка по кадрам через ffmpeg)
        self.pos_slider = QSlider(Qt.Horizontal, self)
        self.pos_slider.setRange(0, max(1, self._duration_ms))
        self.pos_slider.valueChanged.connect(self._on_slider_value)
        self.pos_slider.sliderPressed.connect(self._stop_play)
        self.pos_slider.sliderReleased.connect(self._on_slider_released)
        v.addWidget(self.pos_slider)

        # строка перемотки + обрезка
        row = QHBoxLayout()
        self.play_btn = QPushButton("▶ Воспроизвести", self)
        self.play_btn.setToolTip("Воспроизвести видео прямо в редакторе (без звука, через FFmpeg)")
        self.play_btn.clicked.connect(self._toggle_play)
        row.addWidget(self.play_btn)
        self.frame_btn = QPushButton("⟳ Показать кадр", self)
        self.frame_btn.clicked.connect(self._on_slider_released)
        row.addWidget(self.frame_btn)

        self.time_lbl = QLabel("00:00 / 00:00", self)
        row.addWidget(self.time_lbl)
        row.addStretch(1)

        row.addWidget(QLabel("Начало, с:", self))
        self.in_spin = QDoubleSpinBox(self)
        self.in_spin.setDecimals(1); self.in_spin.setSingleStep(0.5); self.in_spin.setMinimum(0.0)
        self.in_spin.valueChanged.connect(self._on_in_spin)
        row.addWidget(self.in_spin)
        self.set_in_btn = QPushButton("тек.", self)
        self.set_in_btn.setToolTip("Взять начало из позиции ползунка")
        self.set_in_btn.clicked.connect(self._set_in)
        row.addWidget(self.set_in_btn)

        row.addWidget(QLabel("Конец, с:", self))
        self.out_spin = QDoubleSpinBox(self)
        self.out_spin.setDecimals(1); self.out_spin.setSingleStep(0.5); self.out_spin.setMinimum(0.0)
        self.out_spin.valueChanged.connect(self._on_out_spin)
        row.addWidget(self.out_spin)
        self.set_out_btn = QPushButton("тек.", self)
        self.set_out_btn.setToolTip("Взять конец из позиции ползунка")
        self.set_out_btn.clicked.connect(self._set_out)
        row.addWidget(self.set_out_btn)

        self.trim_lbl = QLabel("", self)
        row.addWidget(self.trim_lbl)
        v.addLayout(row)

        # инструменты правок
        row2 = QHBoxLayout()
        self.censor_btn = QPushButton("Замазать область", self)
        self.censor_btn.setCheckable(True)
        self.censor_btn.toggled.connect(self._toggle_censor)
        row2.addWidget(self.censor_btn)
        self.clear_censor_btn = QPushButton("Очистить замазки", self)
        self.clear_censor_btn.clicked.connect(lambda: self.censor.clear())
        row2.addWidget(self.clear_censor_btn)

        self.annot_btn = QPushButton("Аннотации (стрелки/текст…)", self)
        self.annot_btn.clicked.connect(self._open_annotations)
        row2.addWidget(self.annot_btn)
        self.annot_lbl = QLabel("", self)
        row2.addWidget(self.annot_lbl)
        row2.addStretch(1)
        v.addLayout(row2)

        # действия
        row3 = QHBoxLayout()
        row3.addStretch(1)
        self.copy_btn = QPushButton("Копировать в буфер", self)
        self.copy_btn.setToolTip("Применить обрезку/замазки/аннотации и положить готовый файл в буфер")
        self.copy_btn.clicked.connect(self._copy_current)
        row3.addWidget(self.copy_btn)
        self.saveas_btn = QPushButton("Сохранить…", self)
        self.saveas_btn.setStyleSheet("font-weight:bold;")
        self.saveas_btn.setToolTip("Применить правки и сохранить видео в файл")
        self.saveas_btn.clicked.connect(self._save_as)
        row3.addWidget(self.saveas_btn)
        v.addLayout(row3)

        self._refresh_trim_label()

    def _init_preview(self):
        # Без QtMultimedia (его WMF-бэкенд на Windows роняет процесс).
        # Превью — кадр, извлечённый ffmpeg; перемотка — ползунком.
        self._last_pm = None
        lay = QVBoxLayout(self.video_host)
        lay.setContentsMargins(0, 0, 0, 0)
        self.frame_lbl = QLabel(self.video_host)
        self.frame_lbl.setAlignment(Qt.AlignCenter)
        self.frame_lbl.setStyleSheet("background:#111;")
        lay.addWidget(self.frame_lbl)

        self.censor = _CensorOverlay(self.video_host, self._video_display_rect)
        self.censor.setGeometry(self.video_host.rect())
        self.censor.hide()

        self._ensure_duration()
        self.pos_slider.setRange(0, max(1, self._duration_ms))
        self.time_lbl.setText(f"{_fmt(0)} / {_fmt(self._duration_ms)}")
        self._refresh_trim_label()
        QTimer.singleShot(0, lambda: self._show_frame_at(0))

    def _ensure_duration(self):
        if self._duration_ms > 0:
            return
        ff = ffmpeg_path()
        if not ff:
            return
        try:
            r = _run([ff, "-i", self.src], timeout=15.0)
            for line in (r.stderr or "").splitlines():
                s = line.strip()
                if s.startswith("Duration:"):
                    hms = s.split("Duration:", 1)[1].split(",", 1)[0].strip()
                    h, m, sec = hms.split(":")
                    self._duration_ms = int((int(h) * 3600 + int(m) * 60 + float(sec)) * 1000)
                    break
        except Exception:
            pass
        if self._out_ms <= 0 or self._out_ms > self._duration_ms:
            self._out_ms = self._duration_ms

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "censor"):
            self.censor.setGeometry(self.video_host.rect())
        if getattr(self, "_last_pm", None) is not None:
            self._set_preview_pixmap(self._last_pm)

    def _video_display_rect(self) -> QRectF:
        host = self.video_host.rect()
        W, H = host.width(), host.height()
        if self._native_w < 1 or self._native_h < 1 or W < 1 or H < 1:
            return QRectF(host)
        scale = min(W / self._native_w, H / self._native_h)
        dw = self._native_w * scale
        dh = self._native_h * scale
        return QRectF((W - dw) / 2.0, (H - dh) / 2.0, dw, dh)

    def _show_frame_at(self, ms: int):
        self._stop_play()
        ff = ffmpeg_path()
        if not ff:
            return
        poster = str(_rec_tmp_dir() / "preview.png")
        if extract_poster(self.src, max(0, ms) / 1000.0, poster):
            pm = QPixmap(poster)
            if not pm.isNull():
                # если ffprobe не дал размер — берём реальный из кадра
                if not (self._native[0] and self._native[1]) and pm.width() > 0:
                    self._native_w, self._native_h = pm.width(), pm.height()
                self._set_preview_pixmap(pm)

    def _set_preview_pixmap(self, pm):
        self._last_pm = pm
        if pm is None or pm.isNull():
            return
        scaled = pm.scaled(self.video_host.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.frame_lbl.setPixmap(scaled)

    def _toggle_play(self):
        if self._play_proc is not None:
            self._stop_play()
            return
        ff = ffmpeg_path()
        if not ff:
            QMessageBox.warning(self, "Просмотр видео", "Для воспроизведения нужен FFmpeg.")
            return
        start = self.pos_slider.value()
        if self._duration_ms > 0 and start >= self._duration_ms:
            start = 0
        proc = QProcess(self)
        if sys.platform == "win32":
            try:
                proc.setCreateProcessArgumentsModifier(
                    lambda a: setattr(a, "flags", a.flags | _CREATE_NO_WINDOW))
            except Exception:
                pass
        proc.setProcessChannelMode(QProcess.SeparateChannels)
        proc.setProgram(ff)
        proc.setArguments(["-hide_banner", "-loglevel", "error", "-ss", f"{start / 1000:.3f}",
                           "-re", "-i", self.src, "-an", "-vf",
                           "fps=12,scale=1280:-2:force_original_aspect_ratio=decrease",
                           "-c:v", "mjpeg", "-q:v", "5", "-f", "image2pipe", "pipe:1"])
        self._play_buffer = b""
        self._play_origin_ms = start
        self._play_wall = time.monotonic()
        proc.readyReadStandardOutput.connect(self._read_play_frames)
        proc.finished.connect(lambda code, status, source=proc: self._play_finished(source))
        proc.errorOccurred.connect(lambda error, source=proc: self._play_error(source, error))
        self._play_proc = proc
        self.play_btn.setText("⏸ Пауза")
        self._play_timer.start()
        proc.start()

    def _read_play_frames(self):
        proc = self._play_proc
        if proc is None:
            return
        self._play_buffer += bytes(proc.readAllStandardOutput())
        frame_count = 0
        while frame_count < 10:
            frame, self._play_buffer = _take_mjpeg_frame(self._play_buffer)
            if frame is None:
                break
            pm = QPixmap()
            if pm.loadFromData(frame, "JPG"):
                self._set_preview_pixmap(pm)
            frame_count += 1
        if len(self._play_buffer) > 12 * 1024 * 1024:
            self._play_buffer = b""

    def _play_tick(self):
        if self._play_proc is None:
            self._play_timer.stop()
            return
        current = self._play_origin_ms + int((time.monotonic() - self._play_wall) * 1000)
        if self._duration_ms > 0 and current >= self._duration_ms:
            current = self._duration_ms
            self._stop_play()
        self.pos_slider.blockSignals(True)
        self.pos_slider.setValue(current)
        self.pos_slider.blockSignals(False)
        self._on_slider_value(current)

    def _stop_play(self):
        proc, self._play_proc = self._play_proc, None
        self._play_timer.stop()
        if hasattr(self, "play_btn"):
            self.play_btn.setText("▶ Воспроизвести")
        self._play_buffer = b""
        if proc is not None and proc.state() != QProcess.NotRunning:
            proc.kill()
            proc.waitForFinished(1500)

    def _play_finished(self, source):
        if source is not self._play_proc:
            return
        self._play_tick()
        self._stop_play()

    def _play_error(self, source, error):
        if source is not self._play_proc or error != QProcess.FailedToStart:
            return
        self._stop_play()
        self.statusBar().showMessage("FFmpeg не запустился. Проверь наличие ffmpeg.exe.", 5000)

    def _on_slider_value(self, ms: int):
        self.time_lbl.setText(f"{_fmt(ms)} / {_fmt(self._duration_ms)}")

    def _on_slider_released(self):
        self._show_frame_at(self.pos_slider.value())

    def _current_ms(self) -> int:
        return int(self.pos_slider.value())

    # ── обрезка ───────────────────────────────────────────────────────────────
    def _set_in(self):
        self._in_ms = min(self._current_ms(), max(0, self._out_ms - 100))
        self._refresh_trim_label()

    def _set_out(self):
        self._out_ms = max(self._current_ms(), self._in_ms + 100)
        self._refresh_trim_label()

    def _sync_spins(self):
        dur = max(0.1, self._duration_ms / 1000.0)
        for sp in (self.in_spin, self.out_spin):
            sp.blockSignals(True); sp.setMaximum(dur)
        self.in_spin.setValue(self._in_ms / 1000.0)
        self.out_spin.setValue(self._out_ms / 1000.0)
        for sp in (self.in_spin, self.out_spin):
            sp.blockSignals(False)

    def _on_in_spin(self, sec: float):
        self._in_ms = int(sec * 1000)
        if self._in_ms > self._out_ms - 100:
            self._out_ms = min(self._duration_ms, self._in_ms + 100)
        self._refresh_trim_label()
        self._show_frame_at(self._in_ms)

    def _on_out_spin(self, sec: float):
        self._out_ms = int(sec * 1000)
        if self._out_ms < self._in_ms + 100:
            self._in_ms = max(0, self._out_ms - 100)
        self._refresh_trim_label()
        self._show_frame_at(self._out_ms)

    def _refresh_trim_label(self):
        self.trim_lbl.setText(f"Обрезка: {_fmt(self._in_ms)} → {_fmt(self._out_ms)}")
        if hasattr(self, "in_spin"):
            self._sync_spins()

    # ── замазки ───────────────────────────────────────────────────────────────
    def _toggle_censor(self, on: bool):
        self.censor.setVisible(on)
        self.censor.raise_()
        self.censor.set_enabled(on)

    # ── аннотации через штатный редактор изображений на постер-кадре ─────────────
    def _open_annotations(self):
        poster = str(_rec_tmp_dir() / "poster.png")
        if not extract_poster(self.src, self._current_ms() / 1000.0, poster):
            QMessageBox.warning(self, "Аннотации", "Не удалось получить кадр.")
            return
        img = QImage(poster)
        if img.isNull():
            return

        ed = EditorWindow(img, self)
        ed.setAttribute(Qt.WA_DeleteOnClose, True)  # не копить закрытые редакторы в памяти
        # добавляем действие «применить к видео», забирающее прозрачный оверлей
        act = QAction("✔ Применить к видео", ed)
        act.setShortcut(QKeySequence("Ctrl+Return"))

        def apply_overlay():
            view = ed.view
            if not hasattr(view, "render_overlay_only"):
                QMessageBox.warning(ed, "Оверлей",
                                    "В CanvasView не хватает метода render_overlay_only "
                                    "(добавь патч из инструкции).")
                return
            ov = view.render_overlay_only()
            out = str(_rec_tmp_dir() / "overlay.png")
            if ov.save(out, "PNG"):
                self._overlay_png = out
                self.annot_lbl.setText("аннотации: применены ✓")
            # Аннотации ушли в видео — не спрашиваем «сохранить картинку?» при закрытии.
            view.mark_clean()
            ed.close()

        act.triggered.connect(apply_overlay)
        mb = ed.menuBar()
        m = mb.addMenu("Видео")
        m.addAction(act)
        ed.show()
        ed.activateWindow()

    # ── выгрузка ────────────────────────────────────────────────────────────────
    def _has_edits(self) -> bool:
        return bool(self.censor.rects) or bool(self._overlay_png) \
            or self._in_ms > 0 or (0 < self._out_ms < self._duration_ms)

    def _copy_current(self):
        # без правок — копируем исходник; с правками — предлагаем экспорт
        if self._has_edits() and (self.censor.rects or self._overlay_png):
            self._export(after=lambda p: put_file_on_clipboard(p))
            return
        # только обрезка → быстрый безпотерьный рез во временный файл
        if self._in_ms > 0 or (0 < self._out_ms < self._duration_ms):
            self._export(after=lambda p: put_file_on_clipboard(p))
            return
        put_file_on_clipboard(self.src)
        self.statusBar().showMessage("Скопировано в буфер (файл).", 3000)

    def _save_as(self):
        folder = QStandardPaths.writableLocation(QStandardPaths.MoviesLocation) or str(Path.home())
        default = str(Path(folder) / f"Recording_{time.strftime('%Y-%m-%d_%H-%M-%S')}.mp4")
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить видео", default,
                                              "MP4 (*.mp4)")
        if not path:
            return
        if self._has_edits():
            self._export(dst=path, after=lambda p: self.statusBar().showMessage(
                f"Сохранено: {p}", 5000))
        else:
            try:
                shutil.copyfile(self.src, path)
                self.statusBar().showMessage(f"Сохранено: {path}", 5000)
            except Exception as ex:
                QMessageBox.warning(self, "Ошибка", str(ex))

    def _export(self, dst: Optional[str] = None, after: Optional[Callable[[str], None]] = None):
        if isinstance(dst, bool):   # сигнал clicked шлёт checked(bool) — игнорируем
            dst = None
        ff = ffmpeg_path()
        if not ff:
            QMessageBox.warning(self, "ffmpeg", "ffmpeg.exe не найден.")
            return
        if dst is None:
            dst = str(_rec_tmp_dir() / f"export_{time.strftime('%H-%M-%S')}.mp4")

        censors = self.censor.to_native(self._native_w, self._native_h)
        t_in = self._in_ms / 1000.0
        t_out = (self._out_ms if self._out_ms > 0 else self._duration_ms) / 1000.0
        cmd = build_export_cmd(self.src, dst, t_in, t_out, censors,
                               self._overlay_png, (self._native_w, self._native_h))

        for _b in (getattr(self, "copy_btn", None), getattr(self, "saveas_btn", None)):
            if _b is not None:
                _b.setEnabled(False)
        self.statusBar().showMessage("Обработка видео (ffmpeg)…")

        proc = QProcess(self)
        if sys.platform.startswith("win"):
            try:
                proc.setCreateProcessArgumentsModifier(
                    lambda a: setattr(a, "flags", a.flags | _CREATE_NO_WINDOW))
            except Exception:
                pass
        proc.setProgram(cmd[0]); proc.setArguments(cmd[1:])

        def done(code, status):
            for _b in (getattr(self, "copy_btn", None), getattr(self, "saveas_btn", None)):
                if _b is not None:
                    _b.setEnabled(True)
            # Код выхода проверяем обязательно: при сохранении поверх старого
            # файла он существует, даже если ffmpeg упал.
            ok = (status == QProcess.NormalExit and code == 0
                  and Path(dst).exists() and Path(dst).stat().st_size > 0)
            if ok:
                self.statusBar().showMessage(f"Готово: {dst}", 5000)
                if after:
                    after(dst)
                else:
                    put_file_on_clipboard(dst)
            else:
                err = bytes(proc.readAllStandardError()).decode("utf-8", "ignore")
                log.error("export failed:\n%s", err[-2000:])
                QMessageBox.warning(self, "Экспорт", "Не удалось выполнить экспорт. См. лог.")

        def failed(err):
            # finished не приходит, если ffmpeg не запустился, — кнопки остались бы серыми.
            if err != QProcess.FailedToStart:
                return
            for _b in (getattr(self, "copy_btn", None), getattr(self, "saveas_btn", None)):
                if _b is not None:
                    _b.setEnabled(True)
            log.error("export: ffmpeg failed to start: %s", proc.errorString())
            self.statusBar().clearMessage()
            QMessageBox.warning(self, "Экспорт", f"Не удалось запустить ffmpeg:\n{proc.errorString()}")

        proc.finished.connect(done)
        proc.errorOccurred.connect(failed)
        self._export_proc = proc
        proc.start()

    def closeEvent(self, e):
        self._stop_play()
        proc = self._export_proc
        if proc is not None and proc.state() != QProcess.NotRunning:
            res = QMessageBox.question(
                self, "Экспорт",
                "Видео ещё обрабатывается. Прервать обработку и закрыть редактор?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if res != QMessageBox.Yes:
                e.ignore()
                return
            try:
                proc.finished.disconnect()
                proc.errorOccurred.disconnect()
            except (RuntimeError, TypeError):
                pass
            proc.kill()
            proc.waitForFinished(2000)
        super().closeEvent(e)

def _fmt(ms: int) -> str:
    s = max(0, int(ms)) // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


# ── точка входа: вызывается из Launcher ──────────────────────────────────────
_active_huds: List["RecordHUD"] = []
_open_video_editors: List[VideoEditorWindow] = []


def _begin_recording(rect: QRect, parent_launcher=None) -> None:
    """Панель записи (выбор звука, Старт/Стоп) для уже выделенной области."""
    hud = RecordHUD(rect, launcher=parent_launcher)
    _active_huds.append(hud)   # держим ссылку, иначе GC уберёт панель

    def on_done(path: str):
        try:
            ed = VideoEditorWindow(path)
            ed.setAttribute(Qt.WA_DeleteOnClose, True)
            ed.destroyed.connect(lambda *_: _open_video_editors.remove(ed)
                                 if ed in _open_video_editors else None)
            _open_video_editors.append(ed)
            ed.show()
            ed.raise_()
            ed.activateWindow()
            log.info("REC video editor opened for %s", path)
        except Exception:
            tb = traceback.format_exc()
            log.error("REC failed to open video editor:\n%s", tb)
            QMessageBox.critical(None, "Редактор видео",
                                 "Не удалось открыть редактор:\n\n" + tb[-1500:])

    hud.finished.connect(on_done)
    hud.show()
    hud.raise_()
    hud.activateWindow()


def start_screen_recording(parent_launcher=None) -> None:
    """Запись экрана: выделение области сразу в режиме записи."""
    if not ffmpeg_path():
        QMessageBox.warning(None, "ffmpeg не найден",
                            "Для записи экрана нужен ffmpeg.exe в папке Data "
                            "рядом с программой (или в PATH).")
        return
    if parent_launcher is not None:
        parent_launcher.hide()
    QTimer.singleShot(200, lambda: run_capture_flow(SelectionOverlay.MODE_RECORD, parent_launcher))




# ============================================================
# ОТДЕЛЬНЫЙ ЗНАЧОК В ТРЕЕ
# ============================================================
# Windows различает значки трея по exe. Если скрипт запущен общим
# python.exe/pythonw.exe (например, из Choice), перезапускаем его под своей
# копией NP_Screenshot.exe (их делает make_portable.py в папке Runtime). Нет копии — работаем как есть.

def _relaunch_under_own_exe(exe_name: str = "NP_Screenshot") -> None:
    if sys.platform != "win32" or getattr(sys, "frozen", False):
        return
    current = Path(sys.executable)
    if current.stem.lower() == exe_name.lower():
        return
    target = current.parent / f"{exe_name}.exe"
    if not target.exists():
        return
    cmd = [str(target), str(Path(__file__).resolve()), *sys.argv[1:]]
    try:
        # Выходим из Job Object лаунчера, чтобы он не закрыл нас вместе с собой.
        subprocess.Popen(cmd, cwd=str(Path.cwd()), close_fds=True, creationflags=0x01000000)
    except OSError:
        try:
            subprocess.Popen(cmd, cwd=str(Path.cwd()), close_fds=True)
        except OSError:
            return  # не вышло — работаем под текущим интерпретатором
    raise SystemExit(0)


def main():
    _relaunch_under_own_exe()
    _setup_logging()
    try:
        _cleanup_rec_tmp()
    except Exception:
        log.debug("rec_tmp cleanup failed", exc_info=True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Screenshot Editor")
    app.setWindowIcon(_load_app_icon())
    win = Launcher()
    win.setWindowIcon(_load_app_icon())
    win.hide()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

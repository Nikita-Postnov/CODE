from __future__ import annotations
import sys
from enum import Enum, auto
from typing import Optional, List, Tuple
from pathlib import Path
from PySide6.QtCore import (
    Qt,
    QRect,
    QRectF,
    QPoint,
    QPointF,
    QSize,
    QEvent,
    QTimer,
    QAbstractNativeEventFilter,
)
import ctypes
from ctypes import wintypes
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
    QPen,
    QPixmap,
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
    QGraphicsPixmapItem,
    QGraphicsItem,
    QStyle,
    QInputDialog,
    QScrollBar,
    QDialog,
    QMessageBox,
    QToolButton,
    QSystemTrayIcon,
    QMenu,
    QSizePolicy,
)


def qimage_from_qpixmap(pix: QPixmap) -> QImage:
    return pix.toImage().convertToFormat(QImage.Format_ARGB32)


def qpixmap_from_qimage(img: QImage) -> QPixmap:
    return QPixmap.fromImage(img)


def draw_arrow(p: QPainter, start: QPointF, end: QPointF, color: QColor, width: int):
    p.save()
    pen = QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.drawLine(start, end)
    import math

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
    r = max(2, radius)
    rect = QRect(center.x() - r, center.y() - r, 2 * r, 2 * r).intersected(img.rect())
    if rect.isEmpty():
        return
    sub = img.copy(rect)

    def box_blur(src: QImage, passes: int = 2, k: int = kernel) -> QImage:
        k = max(3, k | 1)
        w, h = src.width(), src.height()
        tmp = QImage(src.size(), QImage.Format_ARGB32)
        out = QImage(src.size(), QImage.Format_ARGB32)
        src_bits = src
        for _ in range(passes):
            for y in range(h):
                acc_r = acc_g = acc_b = acc_a = 0
                buf = []
                for x in range(w):
                    c = src_bits.pixelColor(x, y)
                    acc_r += c.red()
                    acc_g += c.green()
                    acc_b += c.blue()
                    acc_a += c.alpha()
                    buf.append((acc_r, acc_g, acc_b, acc_a))
                half = k // 2
                for x in range(w):
                    l = max(0, x - half)
                    rgt = min(w - 1, x + half)
                    left_acc = buf[l - 1] if l > 0 else (0, 0, 0, 0)
                    right_acc = buf[rgt]
                    cnt = rgt - l + 1
                    r_ = (right_acc[0] - left_acc[0]) // cnt
                    g_ = (right_acc[1] - left_acc[1]) // cnt
                    b_ = (right_acc[2] - left_acc[2]) // cnt
                    a_ = (right_acc[3] - left_acc[3]) // cnt
                    tmp.setPixelColor(x, y, QColor(r_, g_, b_, a_))
            for x in range(w):
                acc_r = acc_g = acc_b = acc_a = 0
                buf = []
                for y in range(h):
                    c = tmp.pixelColor(x, y)
                    acc_r += c.red()
                    acc_g += c.green()
                    acc_b += c.blue()
                    acc_a += c.alpha()
                    buf.append((acc_r, acc_g, acc_b, acc_a))
                half = k // 2
                for y in range(h):
                    t = max(0, y - half)
                    b = min(h - 1, y + half)
                    top_acc = buf[t - 1] if t > 0 else (0, 0, 0, 0)
                    bot_acc = buf[b]
                    cnt = b - t + 1
                    r_ = (bot_acc[0] - top_acc[0]) // cnt
                    g_ = (bot_acc[1] - top_acc[1]) // cnt
                    b_ = (bot_acc[2] - top_acc[2]) // cnt
                    a_ = (bot_acc[3] - top_acc[3]) // cnt
                    out.setPixelColor(x, y, QColor(r_, g_, b_, a_))
            src_bits = out
        return out

    blurred = box_blur(sub, passes=2, k=kernel)
    painter = QPainter(img)
    painter.setClipRegion(QRect(rect).toRectF().toAlignedRect())
    path = QPainterPath()
    path.addEllipse(QPointF(center), r, r)
    painter.setClipPath(path, Qt.ReplaceClip)
    painter.drawImage(rect.topLeft(), blurred)
    painter.end()


def flood_fill_into(
    sample: QImage, target: QImage, seed: QPoint, new_color: QColor, tol: int = 30
):
    w, h = sample.width(), sample.height()
    if not (0 <= seed.x() < w and 0 <= seed.y() < h):
        return
    target_c = sample.pixelColor(seed)
    if (
        abs(target_c.red() - new_color.red())
        + abs(target_c.green() - new_color.green())
        + abs(target_c.blue() - new_color.blue())
    ) <= tol * 3:
        return
    visited = bytearray(w * h)
    stack = [(seed.x(), seed.y())]

    def similar(c: QColor) -> bool:
        return (
            abs(c.red() - target_c.red())
            + abs(c.green() - target_c.green())
            + abs(c.blue() - target_c.blue())
        ) <= tol * 3

    while stack:
        x, y = stack.pop()
        xl = x
        while xl >= 0 and not visited[y * w + xl] and similar(sample.pixelColor(xl, y)):
            xl -= 1
        xl += 1
        xr = x
        while xr < w and not visited[y * w + xr] and similar(sample.pixelColor(xr, y)):
            xr += 1
        xr -= 1
        if xr < xl:
            continue
        for xi in range(xl, xr + 1):
            target.setPixelColor(xi, y, new_color)
            visited[y * w + xi] = 1
        if y > 0:
            yi = y - 1
            xi = xl
            while xi <= xr:
                if not visited[yi * w + xi] and similar(sample.pixelColor(xi, yi)):
                    stack.append((xi, yi))
                    while (
                        xi <= xr
                        and not visited[yi * w + xi]
                        and similar(sample.pixelColor(xi, yi))
                    ):
                        xi += 1
                xi += 1
        if y + 1 < h:
            yi = y + 1
            xi = xl
            while xi <= xr:
                if not visited[yi * w + xi] and similar(sample.pixelColor(xi, yi)):
                    stack.append((xi, yi))
                    while (
                        xi <= xr
                        and not visited[yi * w + xi]
                        and similar(sample.pixelColor(xi, yi))
                    ):
                        xi += 1
                xi += 1


def flood_fill(img: QImage, seed: QPoint, new_color: QColor, tol: int = 30):
    flood_fill_into(img, img, seed, new_color, tol)


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

    class _Pane(QWidget):
        def __init__(self, mgr: "SelectionOverlay", screen):
            super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setMouseTracking(True)
            self.setCursor(Qt.CrossCursor)
            self.mgr = mgr
            self.scr = screen
            self.setGeometry(screen.geometry())

        def showPane(self):
            self.show()
            self.raise_()

        def mousePressEvent(self, e: QMouseEvent):
            if e.button() == Qt.LeftButton:
                g = e.globalPosition().toPoint()
                self.mgr._on_press(g)
                self.update()

        def mouseMoveEvent(self, e: QMouseEvent):
            if self.mgr._origin_g is not None:
                g = e.globalPosition().toPoint()
                self.mgr._on_move(g)
                # перерисуем все панели
                for p in self.mgr._panes:
                    p.update()

        def mouseReleaseEvent(self, e: QMouseEvent):
            if e.button() == Qt.LeftButton and self.mgr._origin_g is not None:
                g = e.globalPosition().toPoint()
                self.mgr._on_release(g)

        def keyPressEvent(self, e):
            if e.key() == Qt.Key_Escape:
                self.mgr._cancel()

        def paintEvent(self, _):
            p = QPainter(self)
            p.fillRect(self.rect(), QColor(0, 0, 0, 100))
            if self.mgr._origin_g is not None and self.mgr._current_g is not None:
                top_left = self.geometry().topLeft()
                r_global = QRect(self.mgr._origin_g, self.mgr._current_g).normalized()
                r_local = r_global.translated(-top_left)
                inter = r_local.intersected(self.rect())
                if not inter.isEmpty():
                    p.setCompositionMode(QPainter.CompositionMode_Clear)
                    p.fillRect(inter, Qt.transparent)
                    p.setCompositionMode(QPainter.CompositionMode_SourceOver)
                if not r_local.intersected(self.rect()).isEmpty():
                    p.setPen(QPen(QColor(255, 255, 255, 220), 2))
                    p.drawRect(r_local)
                    info = f"{r_global.width()} x {r_global.height()}"
                    metrics = p.fontMetrics()
                    rect = QRect(r_local.left(), r_local.top() - metrics.height() - 8,
                                 metrics.horizontalAdvance(info) + 12, metrics.height() + 8)
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(0, 0, 0, 150))
                    p.drawRect(rect)
                    p.setPen(QColor(255, 255, 255))
                    p.drawText(rect.adjusted(6, 4, -6, -4), Qt.AlignLeft | Qt.AlignVCenter, info)
            p.end()

    def __init__(self):
        self._panes: List[SelectionOverlay._Pane] = [
            SelectionOverlay._Pane(self, s) for s in QGuiApplication.screens()
        ]
        self._origin_g: Optional[QPoint] = None
        self._current_g: Optional[QPoint] = None
        self.selection_made = lambda rect: None

    def begin(self):
        self._origin_g = self._current_g = None
        for p in self._panes:
            p.showPane()
        self._panes[0].activateWindow()
        self._panes[0].setFocus(Qt.ActiveWindowFocusReason)

    def isVisible(self) -> bool:
        return any(p.isVisible() for p in self._panes)

    def hide(self):
        for p in self._panes:
            p.hide()

    def _on_press(self, g: QPoint):
        self._origin_g = g
        self._current_g = g

    def _on_move(self, g: QPoint):
       self._current_g = g

    def _on_release(self, g: QPoint):
        self._current_g = g
        rect = QRect(self._origin_g, self._current_g).normalized()
        self._origin_g = self._current_g = None
        self.hide()
        self.selection_made(rect)
    
    def _cancel(self):
        self._origin_g = self._current_g = None
        self.hide()

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
        if self.isSelected() or self._hover_handle:
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
        for name, rc in self._handles().items():
            if rc.contains(pos):
                self._hover_handle = name
                break
        self.setCursor(self._cursor_for(self._hover_handle))
        super().hoverMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
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
        target = QRectF(self.scenePos(), self._rect.size())
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(target, self._pix, self._pix.rect())


class CanvasView(QGraphicsView):
    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.setRenderHints(QPainter.Antialiasing)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.bg_img: QImage = image.convertToFormat(QImage.Format_ARGB32)
        self.ov_img: QImage = QImage(self.bg_img.size(), QImage.Format_ARGB32)
        self.ov_img.fill(Qt.transparent)
        self.preview_img: Optional[QImage] = None
        self.base_item = QGraphicsPixmapItem(qpixmap_from_qimage(self._compose()))
        self.preview_item = QGraphicsPixmapItem()
        self.preview_item.setZValue(1)
        self._scene.addItem(self.base_item)
        self._scene.addItem(self.preview_item)
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
        self._drawing = False
        self._last_pos: Optional[QPoint] = None
        self._start_pos: Optional[QPoint] = None
        self.undo_stack: List[Tuple[QImage, QImage]] = []
        self.redo_stack: List[Tuple[QImage, QImage]] = []
        self._panning = False
        self._pan_start = QPoint()
        self._zoom = 1.0
        self._update_smoothing()
        self._cursor_pos: Optional[QPoint] = None
        self.update_scene_rect()
        self.stickers: List[StickerItem] = []

    def show_original_size(self):
        self._zoom = 1.0
        self.setTransform(QTransform())
        self._update_smoothing()
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)
        
    def _update_smoothing(self):
        if abs(self._zoom - 1.0) < 1e-3:
            self.setRenderHints(QPainter.Antialiasing)
        else:
            self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

    def update_scene_rect(self):
        self._scene.setSceneRect(QRectF(QPointF(0, 0), self.bg_img.size()))

    def _compose(self) -> QImage:
        out = QImage(self.bg_img.size(), QImage.Format_ARGB32)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.drawImage(0, 0, self.bg_img)
        p.drawImage(0, 0, self.ov_img)
        p.end()
        return out

    def _refresh(self):
        self.base_item.setPixmap(qpixmap_from_qimage(self._compose()))
        self.viewport().update()

    def push_undo(self):
        self.undo_stack.append((self.bg_img.copy(), self.ov_img.copy()))
        self.redo_stack.clear()

    def set_tool(self, t: Tool):
        self.tool = t
        self.setCursor(Qt.CrossCursor if t != Tool.PAN else Qt.OpenHandCursor)
        if t == Tool.PAN:
            self.setDragMode(QGraphicsView.NoDrag)
        if t != Tool.ERASER:
            self._cursor_pos = None
        self.viewport().update()

    def set_color(self, c: QColor):
        self.color = c

    def set_thickness(self, v: int):
        self.thickness = max(1, v)
        if self.tool == Tool.ERASER:
            self.viewport().update()

    def set_fill_enabled(self, flag: bool):
        self.fill_enabled = bool(flag)

    def set_fill_alpha(self, alpha: int):
        self.fill_alpha = max(0, min(255, int(alpha)))

    def set_fill_color(self, c: QColor):
        self.fill_color = c

    def set_fill_tolerance(self, v: int):
        self.fill_tolerance = max(0, min(255, int(v)))

    def set_image(self, img: QImage):
        self.bg_img = img.convertToFormat(QImage.Format_ARGB32)
        self.ov_img = QImage(self.bg_img.size(), QImage.Format_ARGB32)
        self.ov_img.fill(Qt.transparent)
        self.update_scene_rect()
        self._refresh()
        self._zoom = 1.0
        self.setTransform(QTransform())
        self._update_smoothing()
        self.show_original_size()
        self._scene.clearSelection()

    def commit_preview(self):
        if self.preview_img is not None:
            self.push_undo()
            p = QPainter(self.ov_img)
            p.drawImage(0, 0, self.preview_img)
            p.end()
            self._refresh()
            self.preview_img = None
            self.preview_item.setPixmap(QPixmap())

    def cancel_preview(self):
        self.preview_img = None
        self.preview_item.setPixmap(QPixmap())

    def viewport_to_image(self, pos: QPoint) -> QPoint:
        sp = self.mapToScene(pos)
        return QPoint(int(sp.x()), int(sp.y()))

    def _erase_at(self, center: QPoint, radius: int):
        r = max(1, radius)
        p = QPainter(self.ov_img)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.setPen(Qt.NoPen)
        p.setBrush(Qt.transparent)
        p.drawEllipse(QRect(center - QPoint(r, r), QSize(2 * r, 2 * r)))
        p.end()

    def _erase_line(self, a: QPoint, b: QPoint, radius: int):
        dx, dy = b.x() - a.x(), b.y() - a.y()
        dist = max(1, int((dx * dx + dy * dy) ** 0.5))
        step = max(1, radius // 2)
        for t in range(0, dist + 1, step):
            x = a.x() + dx * t // max(1, dist)
            y = a.y() + dy * t // max(1, dist)
            self._erase_at(QPoint(x, y), radius)

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
            e.accept()
        else:
            super().wheelEvent(e)
            if self.tool == Tool.ERASER:
                self.viewport().update()

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            super().mousePressEvent(e)
            if e.isAccepted():
                return
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
                    pen = QPen(
                        (
                            self.color
                            if self.tool == Tool.PEN
                            else QColor(
                                self.color.red(),
                                self.color.green(),
                                self.color.blue(),
                                120,
                            )
                        ),
                        self.thickness,
                        Qt.SolidLine,
                        Qt.RoundCap,
                        Qt.RoundJoin,
                    )
                    p.setPen(pen)
                    p.drawPoint(img_pos)
                    p.end()
                    self._refresh()
                elif self.tool == Tool.BLUR:
                    apply_gaussian_like_blur(self.bg_img, img_pos, self.thickness * 2)
                    self._refresh()
                elif self.tool == Tool.PIXELATE:
                    apply_pixelate(self.bg_img, img_pos, self.thickness * 2, px_size=6)
                    self._refresh()
                    self._last_pos = img_pos
                elif self.tool == Tool.ERASER:
                    self._erase_line(self._last_pos, img_pos, self.thickness * 2)
                    self._refresh()
                    self._last_pos = img_pos
            elif self.tool in (
                Tool.RECT,
                Tool.ELLIPSE,
                Tool.ARROW,
                Tool.CROP,
                Tool.REDACT,
            ):
                self._start_pos = img_pos
                self.preview_img = self._compose().copy()
            elif self.tool == Tool.FILL:
                self.push_undo()
                fill_col = QColor(self.fill_color)
                fill_col.setAlpha(self.fill_alpha)
                if e.modifiers() & Qt.AltModifier:
                    flood_fill(self.bg_img, img_pos, fill_col, self.fill_tolerance)
                else:
                    comp = self._compose()
                    flood_fill_into(
                        comp, self.ov_img, img_pos, fill_col, self.fill_tolerance
                    )
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
        if self._scene.mouseGrabberItem():
            super().mouseMoveEvent(e)
            return
        cur_pos = self.viewport_to_image(e.position().toPoint())
        self._cursor_pos = cur_pos
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
            img_pos = cur_pos
            if self.tool in (Tool.PEN, Tool.HIGHLIGHT):
                p = QPainter(self.ov_img)
                pen = QPen(
                    (
                        self.color
                        if self.tool == Tool.PEN
                        else QColor(
                            self.color.red(), self.color.green(), self.color.blue(), 120
                        )
                    ),
                    self.thickness,
                    Qt.SolidLine,
                    Qt.RoundCap,
                    Qt.RoundJoin,
                )
                p.setPen(pen)
                p.drawLine(self._last_pos, img_pos)
                p.end()
                self._refresh()
                self._last_pos = img_pos
            elif self.tool == Tool.BLUR:
                apply_gaussian_like_blur(self.bg_img, img_pos, self.thickness * 2)
                self._refresh()
                self._last_pos = img_pos
            elif self.tool == Tool.PIXELATE:
                apply_pixelate(self.bg_img, img_pos, self.thickness * 2, px_size=6)
                self._refresh()
                self._last_pos = img_pos
            elif self.tool == Tool.ERASER:
                self._erase_line(self._last_pos, img_pos, self.thickness * 2)
                self._refresh()
                self._last_pos = img_pos
            e.accept()
            return
        if (
            self._start_pos
            and self.preview_img is not None
            and self.tool
            in (Tool.RECT, Tool.ELLIPSE, Tool.ARROW, Tool.CROP, Tool.REDACT)
        ):
            cur = self.viewport_to_image(e.position().toPoint())
            preview = self.preview_img.copy()
            p = QPainter(preview)
            p.setRenderHint(QPainter.Antialiasing, True)
            if self.tool in (Tool.RECT, Tool.CROP, Tool.ELLIPSE, Tool.REDACT):
                pen = QPen(
                    (
                        self.color
                        if self.tool in (Tool.RECT, Tool.ELLIPSE)
                        else QColor(255, 255, 255, 220)
                    ),
                    max(1, self.thickness),
                    Qt.SolidLine,
                )
                p.setPen(pen)
                if self.tool in (Tool.RECT, Tool.ELLIPSE) and self.fill_enabled:
                    fill = QColor(self.color)
                    fill.setAlpha(self.fill_alpha)
                    p.setBrush(fill)
                elif self.tool == Tool.REDACT:
                    p.setBrush(QColor(0, 0, 0, 200))
                else:
                    p.setBrush(Qt.NoBrush)
                constrain = bool(e.modifiers() & Qt.ShiftModifier)
                r = self._rect_from_points(
                    self._start_pos,
                    cur,
                    constrain if self.tool != Tool.CROP else constrain,
                )
                if self.tool == Tool.ELLIPSE:
                    p.drawEllipse(r)
                else:
                    p.drawRect(r)
            elif self.tool == Tool.ARROW:
                draw_arrow(
                    p,
                    QPointF(self._start_pos),
                    QPointF(cur),
                    self.color,
                    self.thickness,
                )
            p.end()
            self.preview_item.setPixmap(qpixmap_from_qimage(preview))
            e.accept()
            return

        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent):
        super().mouseReleaseEvent(e)
        if e.isAccepted():
            return
        if self._panning and e.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._panning = False
            self.setCursor(
                Qt.OpenHandCursor if self.tool == Tool.PAN else Qt.CrossCursor
            )
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
                self._start_pos
                and self.preview_img is not None
                and self.tool
                in (Tool.RECT, Tool.ELLIPSE, Tool.ARROW, Tool.CROP, Tool.REDACT)
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
                        self.update_scene_rect()
                        self._refresh()
                        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
                else:
                    self.push_undo()
                    p = QPainter(self.ov_img)
                    p.setRenderHint(QPainter.Antialiasing, True)
                    if self.tool == Tool.RECT:
                        pen = QPen(
                            self.color,
                            max(1, self.thickness),
                            Qt.SolidLine,
                            Qt.RoundCap,
                            Qt.RoundJoin,
                        )
                        p.setPen(pen)
                        p.setBrush(
                            QColor(
                                self.color.red(),
                                self.color.green(),
                                self.color.blue(),
                                self.fill_alpha,
                            )
                            if self.fill_enabled
                            else Qt.NoBrush
                        )
                        r = self._rect_from_points(
                            self._start_pos, cur, bool(e.modifiers() & Qt.ShiftModifier)
                        )
                        p.drawRect(r)
                    elif self.tool == Tool.ELLIPSE:
                        pen = QPen(
                            self.color,
                            max(1, self.thickness),
                            Qt.SolidLine,
                            Qt.RoundCap,
                            Qt.RoundJoin,
                        )
                        p.setPen(pen)
                        p.setBrush(
                            QColor(
                                self.color.red(),
                                self.color.green(),
                                self.color.blue(),
                                self.fill_alpha,
                            )
                            if self.fill_enabled
                            else Qt.NoBrush
                        )
                        r = self._rect_from_points(
                            self._start_pos, cur, bool(e.modifiers() & Qt.ShiftModifier)
                        )
                        p.drawEllipse(r)
                    elif self.tool == Tool.REDACT:
                        p.setPen(Qt.NoPen)
                        p.setBrush(QColor(0, 0, 0))
                        r = self._rect_from_points(self._start_pos, cur, False)
                        p.drawRect(r)
                    elif self.tool == Tool.ARROW:
                        draw_arrow(
                            p,
                            QPointF(self._start_pos),
                            QPointF(cur),
                            self.color,
                            self.thickness,
                        )
                    p.end()
                    self._refresh()
                self._start_pos = None
                self.cancel_preview()
                e.accept()
                return

        super().mouseReleaseEvent(e)

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
        self.viewport().update()
        super().leaveEvent(e)

    def undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append((self.bg_img.copy(), self.ov_img.copy()))
        bg, ov = self.undo_stack.pop()
        self.bg_img, self.ov_img = bg, ov
        self.update_scene_rect()
        self._refresh()

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append((self.bg_img.copy(), self.ov_img.copy()))
        bg, ov = self.redo_stack.pop()
        self.bg_img, self.ov_img = bg, ov
        self.update_scene_rect()
        self._refresh()

    def save_to_file(self, parent: QWidget):
        path, _ = QFileDialog.getSaveFileName(
            parent,
            "Сохранить изображение",
            "screenshot.png",
           "PNG (*.png);;JPEG (*.jpg *.jpeg);;WEBP (*.webp);;BMP (*.bmp)",
        )
        if not path:
            return
        lower = path.lower()
        if lower.endswith((".jpg", ".jpeg")):
            fmt, quality = "JPG", 95
        elif lower.endswith(".webp"):
            fmt, quality = "WEBP", 95
        elif lower.endswith(".bmp"):
            fmt, quality = "BMP", -1
        else:
            fmt, quality = "PNG", -1
        img = self.render_scene_to_image()
        if not img.save(path, fmt, quality):
            QMessageBox.warning(parent, "Ошибка", "Не удалось сохранить файл.")

    def copy_to_clipboard(self):
        QApplication.clipboard().setImage(self.render_scene_to_image(), QClipboard.Clipboard)

    def add_sticker(self, img: QImage):
        if img.isNull():
            return
        pix = QPixmap.fromImage(img.convertToFormat(QImage.Format_ARGB32))
        max_size = QSize(int(self.bg_img.width() * 0.6), int(self.bg_img.height() * 0.6))
        item = StickerItem(pix, max_size)
        cx = (self.bg_img.width() - item._rect.width()) / 2
        cy = (self.bg_img.height() - item._rect.height()) / 2
        item.setPos(QPointF(cx, cy))
        self._scene.addItem(item)
        item.setSelected(True)
        self.stickers.append(item)
        self.viewport().update()

    def flatten_selected_stickers(self):
        items = [it for it in self._scene.selectedItems() if isinstance(it, StickerItem)]
        if not items:
            return
        self.push_undo()
        p = QPainter(self.ov_img)
        for it in items:
            it.rasterize_to(p)
        p.end()
        for it in items:
            self._scene.removeItem(it)
            if it in self.stickers:
                self.stickers.remove(it)
        self._refresh()

    def delete_selected_stickers(self):
        items = [it for it in self._scene.selectedItems() if isinstance(it, StickerItem)]
        if not items:
            return
        for it in items:
            self._scene.removeItem(it)
            if it in self.stickers:
                self.stickers.remove(it)
        self.viewport().update()

    def render_scene_to_image(self) -> QImage:
        w, h = self.bg_img.width(), self.bg_img.height()
        img = QImage(w, h, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self._scene.render(p, QRectF(0, 0, w, h), QRectF(0, 0, w, h))
        p.end()
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
        self.setWindowIcon(_load_app_icon())
        center_on_screen(self)

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
        a_pen.trigger()
        t1.addSeparator()
        self.line_btn = QToolButton(self)
        self.line_btn.setToolTip("Цвет линии (кликни)")
        self.line_btn.setAutoRaise(True)
        self.line_btn.setFixedSize(26, 26)
        self.line_btn.clicked.connect(self.pick_color)
        t2.addWidget(self.line_btn)
        self._refresh_line_btn()
        self.line_caption = QLabel(" Линия")
        self.line_caption.setStyleSheet("color: #c8c8c8;")
        t2.addWidget(self.line_caption)
        self.fill_btn = QToolButton(self)
        self.fill_btn.setToolTip("Цвет заливки (кликни)")
        self.fill_btn.setAutoRaise(True)
        self.fill_btn.setFixedSize(26, 26)
        self.fill_btn.clicked.connect(self.pick_fill_color)
        t2.addWidget(self.fill_btn)
        self._refresh_fill_btn()
        self.fill_caption = QLabel(" Заливка")
        self.fill_caption.setStyleSheet("color: #c8c8c8;")
        t2.addWidget(self.fill_caption)

        lbl = QLabel(" Толщина: ")
        t2.addWidget(lbl)
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setMinimum(1)
        self.slider.setMaximum(48)
        self.slider.setValue(4)
        self.slider.valueChanged.connect(lambda v: self.view.set_thickness(v))
        self.slider.setMinimumWidth(90)
        self.slider.setMaximumWidth(220)
        t2.addWidget(self.slider)
        a_fill = QAction("⧉ Заливка форм", self)
        a_fill.setCheckable(True)
        a_fill.toggled.connect(lambda f: self.view.set_fill_enabled(f))
        t2.addAction(a_fill)
        self.lbl_alpha = QLabel(" Непрозрачность: 80% ")
        t2.addWidget(self.lbl_alpha)
        self.fill_slider = QSlider(Qt.Horizontal, self)
        self.fill_slider.setMinimum(0)
        self.fill_slider.setMaximum(255)
        self.fill_slider.setValue(80)
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
        self.tol_slider.setValue(30)
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
        add_action(t3, "💾 Сохранить", lambda: self.view.save_to_file(self), "Ctrl+S")
        add_action(t3, "📋 Копировать", lambda: self.view.copy_to_clipboard(), "Ctrl+C")
        add_action(t4, "↶ Отменить", self.view.undo, "Ctrl+Z")
        add_action(t4, "↷ Повторить", self.view.redo, "Ctrl+Y")
        t4.addSeparator()
        add_action(t4, "🖼 Новый снимок", self.new_capture, "F9")
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
            self.lbl_tol.setText(f" Допуск ведра: {v}% ")

    def _apply_shortcuts(self):
        quit_act = QAction(self)
        quit_act.setShortcut(QKeySequence(Qt.Key_Escape))
        quit_act.triggered.connect(self.close)
        self.addAction(quit_act)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._reflow_toolbar)

    def _toolbar_widgets(self):
        out = []
        for act in self.tb.actions():
            w = self.tb.widgetForAction(act)
            if w is self._moreBtn or w is self._spacer:
                self._moreAction = act
                continue
            out.append((act, w))
        return out

    def _reflow_toolbar(self):
        if not hasattr(self, "tb"):
            return
        items = self._toolbar_widgets()
        for act, w in items:
            if w:
                w.setVisible(True)
            else:
                act.setVisible(True)
        self._moreMenu.clear()

        reserve = self._moreBtn.sizeHint().width() + 12
        avail = self.tb.contentsRect().width() - reserve
        used = 0
        overflow_started = False
        hidden_names = []
        for act, w in items:
            if act.isSeparator():
                w_hint = 10
            else:
                host = w or self.tb.widgetForAction(act)
                w_hint = host.sizeHint().width() if host else 80
            if used + w_hint <= avail and not overflow_started:
                used += w_hint
                continue
            overflow_started = True
            if w:
                w.setVisible(False)
                fa = self._overflow_fallback.get(w)
                if fa:
                    self._moreMenu.addAction(fa)
                    hidden_names.append(fa.text())
            else:
                act.setVisible(False)
                self._moreMenu.addAction(act)
                if act.text():
                    hidden_names.append(act.text())
        has_overflow = self._moreMenu.actions()
        self._moreBtn.setVisible(bool(has_overflow))
        if hasattr(self, "_moreAction"):
            self._moreAction.setVisible(bool(has_overflow))
        if has_overflow:
            n = len(self._moreMenu.actions())
            self._moreBtn.setText(f"Ещё ({n}) ▾")
            if hidden_names:
                self._moreBtn.setToolTip("Скрыто:\n• " + "\n• ".join(hidden_names))
        else:
            self._moreBtn.setText("Ещё ▾")
            self._moreBtn.setToolTip("Ещё")

    def _ask_thickness(self):
        val, ok = QInputDialog.getInt(self, "Толщина линии", "Значение (px):",
                                      self.view.thickness, 1, 200, 1)
        if ok:
            self.view.set_thickness(val)
            self.slider.setValue(val)

    def _ask_fill_alpha(self):
        val, ok = QInputDialog.getInt(self, "Непрозрачность заливки", "0–255:",
                                      self.view.fill_alpha, 0, 255, 1)
        if ok:
            self.view.set_fill_alpha(val)
            self.fill_slider.setValue(val)

    def _ask_tolerance(self):
        val, ok = QInputDialog.getInt(self, "Допуск заливки", "0–255:",
                                      self.view.fill_tolerance, 0, 255, 1)
        if ok:
            self.view.set_fill_tolerance(val)
            self.tol_slider.setValue(val)

    def closeEvent(self, e):
        e.ignore()
        self.hide()

    def pick_color(self):
        c = QColorDialog.getColor(self.view.color, self, "Выбери цвет")
        if c.isValid():
            self.view.set_color(c)
            self._refresh_line_btn()

    def _refresh_fill_btn(self):
        pm = QPixmap(18, 18)
        pm.fill(self.view.fill_color)
        self.fill_btn.setIcon(QIcon(pm))

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
        self.showMinimized()
        QTimer.singleShot(150, self._do_capture)

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
        self.view.set_image(img)

    def open_from_clipboard(self):
        cb = QApplication.clipboard()
        img = cb.image(QClipboard.Clipboard)
        if img.isNull():
            QMessageBox.information(
                self, "Буфер пуст", "В буфере обмена нет изображения."
            )
            return
        self.view.set_image(img)

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
        self.view.flatten_selected_stickers()

    def delete_selection(self):
        self.view.delete_selected_stickers()

    def _do_capture(self):
        img = capture_region_interactive()
        if img is None:
            (self.showMaximized() if getattr(self, "_was_max", False) else self.showNormal())
            return
        (self.showMaximized() if getattr(self, "_was_max", False) else self.showNormal())
        ed = EditorWindow(img)
        ed.show()
        ed.activateWindow()
        _register_editor_in_launcher(ed)


def grab_region_highdpi(rect_g: QRect) -> QImage:
    ref = QGuiApplication.screenAt(rect_g.center()) or QGuiApplication.primaryScreen()
    dpr_ref = ref.devicePixelRatio()
    out_w = int(round(rect_g.width() * dpr_ref))
    out_h = int(round(rect_g.height() * dpr_ref))
    out = QImage(out_w, out_h, QImage.Format_ARGB32)
    out.fill(Qt.transparent)
    p = QPainter(out)
    for s in QGuiApplication.screens():
        inter = rect_g.intersected(s.geometry())
        if inter.isEmpty():
            continue
        dpr = s.devicePixelRatio()
        rel_x = inter.left() - s.geometry().left()
        rel_y = inter.top()  - s.geometry().top()
        pm = s.grabWindow(0, rel_x, rel_y, inter.width(), inter.height())
        if dpr != dpr_ref:
            pm = pm.scaled(int(round(pm.width() * dpr_ref / dpr)),
                           int(round(pm.height() * dpr_ref / dpr)),
                           Qt.IgnoreAspectRatio, Qt.FastTransformation)
        dx = int(round((inter.left() - rect_g.left()) * dpr_ref))
        dy = int(round((inter.top()  - rect_g.top())  * dpr_ref))
        p.drawPixmap(dx, dy, pm)
    p.end()
    return out

def capture_region_interactive() -> Optional[QImage]:
    overlay = SelectionOverlay()

    result = {"rect": None}

    def on_sel(rect: QRect):
        result["rect"] = rect

    overlay.selection_made = on_sel
    overlay.begin()
    loop = QApplication.instance()
    while overlay.isVisible():
        loop.processEvents()
    if result["rect"] is None:
        return None
    return grab_region_highdpi(result["rect"])


class Launcher(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Screenshot Editor — Launcher")
        self.resize(420, 180)
        w = QWidget(self)
        self.setCentralWidget(w)
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 16, 16, 16)
        title = QLabel(
            "<b>Скриншотер с редактором</b><br>"
            "F9 — новый снимок (каждый в новом окне), Ctrl+S — сохранить, Ctrl+C — копировать."
        )
        v.addWidget(title)
        btn = QPushButton("Сделать скриншот (F9)")
        btn.clicked.connect(self.make_shot)
        v.addWidget(btn)
        btn_open = QPushButton("Открыть изображение…")
        btn_open.clicked.connect(self._open_image)
        v.addWidget(btn_open)
        info = QLabel(
            "Инструменты: Перо (P), Маркер (M), Прямоугольник (R), Овал (O), Стрелка (A), "
            "Текст (T), Blur (B), Pixelate (X), Обрезка (C), Редация (D), Шаг (1), Ведро (F), Панорама (H). "
            "Флаг «⧉ Заливка форм» — включает заливку у прямоугольника/овала."
        )
        info.setStyleSheet("color: gray;")
        v.addWidget(info)
        v.addStretch(1)
        self._editors: List[EditorWindow] = []
        self._real_quit = False
        self._init_tray()
        self._install_global_hotkey()
        act = QAction(self)
        act.setShortcut("F9")
        act.triggered.connect(self.make_shot)
        self.addAction(act)
        center_on_screen(self)

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_centered_once", False):
            QTimer.singleShot(0, lambda: center_on_screen(self))
            self._centered_once = True

    def _init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(_load_app_icon(), self)
        self.tray.setToolTip("Screenshot Editor")
        m = QMenu(self)
        self.act_tray_shot = m.addAction("Сделать скриншот (F9)", self.make_shot)
        self.act_tray_editors = m.addAction("Показать все редакторы", self._show_all_editors)
        self.act_tray_launcher = m.addAction("Показать лаунчер", self._show_launcher)
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

    def _show_launcher(self):
        self.showNormal()
        self.activateWindow()

    def _quit_from_tray(self):
        if hasattr(self, "_hotkey") and self._hotkey:
            self._hotkey.unregister()
        app = QApplication.instance()
        if hasattr(app, "_global_hotkey_filter"):
            delattr(app, "_global_hotkey_filter")
        self._real_quit = True
        QApplication.instance().quit()

    def make_shot(self):
        self._was_max = self.isMaximized()
        self.showMinimized()
        QTimer.singleShot(150, self._do_capture)

    def _do_capture(self):
        img = capture_region_interactive()
        if img is not None:
            ed = EditorWindow(img)
            ed.show()
            ed.activateWindow()
            self._editors.append(ed)
            self._update_tray_menu()
        else:
            (
                self.showMaximized()
                if getattr(self, "_was_max", False)
                else self.showNormal()
            )
        self.show()

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
        self._editors.append(ed)
        self._update_tray_menu()

    def closeEvent(self, e):
        if (
            getattr(self, "_real_quit", False)
            or not QSystemTrayIcon.isSystemTrayAvailable()
        ):
            return super().closeEvent(e)
        e.ignore()
        self.hide()
        if hasattr(self, "tray"):
            self.tray.showMessage(
                "Screenshot Editor",
                "Приложение продолжает работать в трее.",
                QSystemTrayIcon.Information,
                2500,
            )

    def _install_global_hotkey(self):
        if sys.platform.startswith("win"):
            combos = [
                (MOD_NOREPEAT, VK_F9, "F9"),
                (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_F9, "Ctrl+Alt+F9"),
            ]
            self._hotkey = _WinHotkey(QApplication.instance(), self.make_shot, combos)
            if hasattr(self, "tray"):
                if self._hotkey.registered:
                    self.tray.showMessage(
                        "Screenshot Editor",
                        f"Глобальная горячая клавиша: {self._hotkey.description}",
                        QSystemTrayIcon.Information,
                        2000,
                    )
                else:
                    self.tray.showMessage(
                        "Screenshot Editor",
                        "Не удалось зарегистрировать глобальную клавишу.",
                        QSystemTrayIcon.Warning,
                        2500,
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
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
VK_F9 = 0x78


class _WinHotkey(QAbstractNativeEventFilter):

    def __init__(self, app: QApplication, callback, combos):
        super().__init__()
        self._cb = callback
        self._id = 1
        self._reg_ok = False
        self._desc = ""
        self._u32 = ctypes.windll.user32
        for mods, vk, desc in combos:
            if self._u32.RegisterHotKey(None, self._id, mods, vk):
                self._reg_ok = True
                self._desc = desc
                break
        app.installNativeEventFilter(self)
        setattr(app, "_global_hotkey_filter", self)

    @property
    def registered(self) -> bool:
        return self._reg_ok

    @property
    def description(self) -> str:
        return self._desc

    def unregister(self):
        if self._reg_ok:
            self._u32.UnregisterHotKey(None, self._id)
            self._reg_ok = False

    def nativeEventFilter(self, eventType, message):
        try:
            addr = message.__int__() if hasattr(message, "__int__") else int(message)
            msg = wintypes.MSG.from_address(addr)
        except Exception:
            return False
        if msg.message == WM_HOTKEY and msg.wParam == self._id:
            try:
                self._cb()
            except Exception:
                pass
            return True
        return False

def _register_editor_in_launcher(ed: "EditorWindow"):
    app = QApplication.instance()
    for w in app.topLevelWidgets():
        if isinstance(w, Launcher):
            w._editors.append(ed)
            w._update_tray_menu()
            break

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Screenshot Editor")
    app.setWindowIcon(_load_app_icon())
    win = Launcher()
    win.setWindowIcon(_load_app_icon())
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

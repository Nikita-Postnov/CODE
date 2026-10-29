"""Холст рисования и диалог-обёртка над ним."""

from PySide6.QtCore import (
    Qt,
    QSize,
    QPoint,
    QRect,
    Signal,
    QPointF,
)

from PySide6.QtGui import (
    QBrush,
    QFontMetrics,
    QShortcut,
    QFont,
    QImage,
    QKeySequence,
    QPen,
    QColor,
    QPolygonF,
    QPainter,
)

from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QPushButton,
    QWidget,
    QLabel,
    QSizePolicy,
    QInputDialog,
    QColorDialog,
    QSpinBox,
    QDialog,
    QButtonGroup,
    QDialogButtonBox,
    QCheckBox,
    QToolButton,
)


class DrawingCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewport_pad = 16
        self._undo_stack: list[tuple[QImage, list[dict]]] = []
        self._redo_stack: list[tuple[QImage, list[dict]]] = []
        self._drag_changed = False
        self.canvas_bg = QColor("#f3f4f6")
        self.canvas_border_dark = QColor("#2f3338")
        self.canvas_border_light = QColor("#ffffff")
        self.viewport_pad = 16
        self._move_bbox = None
        self.setAttribute(Qt.WidgetAttribute.WA_StaticContents)
        self.image = QImage(1200, 800, QImage.Format.Format_ARGB32)
        self.image.fill(Qt.white)
        self._event_zoom = 1.0
        self._pending_zoom = None
        self.objects = []
        self.selected_index = None
        self._text_input_active = False
        self.drag_start = QPoint()
        self.drag_last = QPoint()
        self.hit_tolerance = 8
        self.show_layout_frame = True
        self.safe_margin = 16
        self.pen_color = QColor("black")
        self.pen_width = 3
        self.zoom = 1.0
        self.tool = "pen"
        self.is_drawing = False
        self.last_pos = QPoint()
        self.start_pos = QPoint()
        self.preview_pos = QPoint()
        self.fill_enabled = False
        self.fill_color = QColor(0, 0, 0, 60)
        self.text_font = QFont("Segoe UI", 18)
        self.move_active = False
        self.move_start = QPoint()
        self.move_delta = QPoint()
        self.image_before_move = None

    def set_color(self, color: QColor):
        self.pen_color = QColor(color)
        self.update()

    def set_show_frame(self, on: bool):
        self.show_layout_frame = bool(on)
        self.update()

    def set_safe_margin(self, px: int):
        self.safe_margin = max(0, int(px))
        self.update()

    def set_width(self, w: int):
        self.pen_width = max(1, int(w))
        self.update()

    def _bbox_union(self, a: QRect | None, b: QRect | None) -> QRect | None:
        if a is None or a.isNull():
            return b
        if b is None or b.isNull():
            return a
        return a.united(b)

    def _clone_objects(self) -> list[dict]:
        out = []
        for o in self.objects:
            c = {"type": o.get("type")}
            if "rect" in o:
                c["rect"] = QRect(o["rect"])
            if "p1" in o:
                c["p1"] = QPoint(o["p1"])
            if "p2" in o:
                c["p2"] = QPoint(o["p2"])
            if "pos" in o:
                c["pos"] = QPoint(o["pos"])
            if "text" in o:
                c["text"] = str(o["text"])
            if "font" in o:
                c["font"] = QFont(o["font"])
            if "pen" in o:
                c["pen"] = QPen(o["pen"])
            if "brush" in o:
                c["brush"] = QBrush(o["brush"])
            out.append(c)
        return out

    def _push_undo_snapshot(self) -> None:
        self._undo_stack.append((self.image.copy(), self._clone_objects()))
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append((self.image.copy(), self._clone_objects()))
        img, objs = self._undo_stack.pop()
        self.image = img
        self.objects = objs
        self.update()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append((self.image.copy(), self._clone_objects()))
        img, objs = self._redo_stack.pop()
        self.image = img
        self.objects = objs
        self.update()

    def _object_bbox(self, obj: dict) -> QRect:
        t = obj.get("type")
        if t in ("rect", "ellipse"):
            return QRect(obj["rect"])
        elif t in ("line", "arrow"):
            x1, y1 = obj["p1"].x(), obj["p1"].y()
            x2, y2 = obj["p2"].x(), obj["p2"].y()
            r = QRect(min(x1, x2), min(y1, y2), abs(x1 - x2), abs(y1 - y2))
            w = max(1, obj.get("pen", QPen()).width())
            return r.adjusted(-w, -w, w, w)
        elif t == "text":
            fm = QFontMetrics(obj.get("font", self.text_font))
            pos = obj.get("pos", QPoint())
            return QRect(
                pos, QSize(fm.horizontalAdvance(obj.get("text", "")), fm.height())
            )
        return QRect()

    def _objects_bbox(self) -> QRect | None:
        box = None
        for o in self.objects:
            box = self._bbox_union(box, self._object_bbox(o))
        return box

    def _raster_bbox(self, img: QImage) -> QRect | None:
        w, h = img.width(), img.height()
        left, right, top, bottom = w, -1, h, -1
        white = QColor(Qt.white).rgba()
        for y in range(h):
            for x in range(w):
                if img.pixel(x, y) != white:
                    if x < left:
                        left = x
                    if x > right:
                        right = x
                    if y < top:
                        top = y
                    if y > bottom:
                        bottom = y
        if right < left or bottom < top:
            return None
        return QRect(left, top, right - left + 1, bottom - top + 1)

    def _content_bbox(self) -> QRect | None:
        box = self._raster_bbox(self.image)
        box = self._bbox_union(box, self._objects_bbox())
        return box

    def _clamp_delta_to_box(self, dx: int, dy: int, box: QRect | None) -> QPoint:
        if box is None or box.isNull():
            return QPoint(0, 0)
        min_dx = -box.left()
        max_dx = (self.image.width() - 1) - box.right()
        min_dy = -box.top()
        max_dy = (self.image.height() - 1) - box.bottom()
        dx = max(min_dx, min(max_dx, dx))
        dy = max(min_dy, min(max_dy, dy))
        return QPoint(dx, dy)

    def set_tool(self, tool: str):
        self.tool = tool
        self.is_drawing = False
        self.move_active = False
        self.move_delta = QPoint()
        self.image_before_move = None
        self.selected_index = None
        self.update()

    def _draw_object(self, painter: QPainter, obj: dict) -> None:
        t = obj.get("type")
        pen: QPen = obj.get("pen", QPen(Qt.black, 3))
        painter.setPen(pen)
        painter.setBrush(obj.get("brush", Qt.NoBrush))
        if t == "rect":
            painter.drawRect(obj["rect"])
        elif t == "ellipse":
            painter.drawEllipse(obj["rect"])
        elif t == "line":
            painter.drawLine(obj["p1"], obj["p2"])
        elif t == "arrow":
            p1, p2 = QPointF(obj["p1"]), QPointF(obj["p2"])
            painter.drawLine(p1, p2)
            head = self._arrow_head(p1, p2, max(10, pen.width() * 3))
            painter.setBrush(QBrush(pen.color()))
            painter.drawPolygon(head)
        elif t == "text":
            painter.setFont(obj["font"])
            painter.drawText(obj["pos"], obj["text"])

    zoomChanged = Signal(float)

    def set_zoom(self, z: float):
        z = max(0.25, min(4.0, float(z)))
        if self.is_drawing or self.move_active:
            self._pending_zoom = z
            return
        if abs(z - self.zoom) > 1e-3:
            self.zoom = z
            self.update()
            try:
                self.zoomChanged.emit(self.zoom)
            except Exception:
                pass

    def set_zoom_percent(self, p: int):
        self.set_zoom(max(25, min(400, int(p))) / 100.0)

    def _to_image_pos(self, p: QPoint, zoom: float | None = None) -> QPoint:
        z = float(self.zoom if zoom is None else zoom)
        pad = getattr(self, "viewport_pad", 0)
        return QPoint(int((p.x() - pad) / z), int((p.y() - pad) / z))

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            if self.is_drawing or self.move_active:
                e.ignore()
                return
            delta = e.angleDelta().y()
            step = 0.1 if delta > 0 else -0.1
            self.set_zoom(self.zoom + step)
            e.accept()
        else:
            super().wheelEvent(e)

    def _draw_objects(self, painter: QPainter) -> None:
        for obj in self.objects:
            self._draw_object(painter, obj)

    def _shape_from_current(self, end_pos: QPoint) -> dict:
        pen = QPen(
            self.pen_color, self.pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin
        )
        t = self.tool
        if t in ("rect", "ellipse"):
            return {
                "type": t,
                "rect": self._norm_rect(self.start_pos, end_pos),
                "pen": pen,
                "brush": QBrush(self.fill_color) if self.fill_enabled else Qt.NoBrush,
            }
        elif t in ("line", "arrow"):
            return {
                "type": t,
                "p1": QPoint(self.start_pos),
                "p2": QPoint(end_pos),
                "pen": pen,
            }
        return {}

    def _translate_object(self, obj: dict, delta: QPoint) -> None:
        if "rect" in obj:
            obj["rect"].translate(delta)
        if "p1" in obj:
            obj["p1"] += delta
        if "p2" in obj:
            obj["p2"] += delta
        if "pos" in obj:
            obj["pos"] += delta

    def _distance_to_segment(self, p: QPoint, a: QPoint, b: QPoint) -> float:
        ax, ay = a.x(), a.y()
        bx, by = b.x(), b.y()
        px, py = p.x(), p.y()
        vx, vy = bx - ax, by - ay
        wx, wy = px - ax, py - ay
        vv = vx * vx + vy * vy or 1.0
        t = max(0.0, min(1.0, (wx * vx + wy * vy) / vv))
        cx, cy = ax + t * vx, ay + t * vy
        dx, dy = px - cx, py - cy
        return (dx * dx + dy * dy) ** 0.5

    def _object_at(self, pos: QPoint) -> int | None:
        for i in range(len(self.objects) - 1, -1, -1):
            obj = self.objects[i]
            t = obj.get("type")
            if t in ("rect", "ellipse"):
                if (
                    obj["rect"]
                    .adjusted(
                        -self.hit_tolerance,
                        -self.hit_tolerance,
                        self.hit_tolerance,
                        self.hit_tolerance,
                    )
                    .contains(pos)
                ):
                    return i
            elif t in ("line", "arrow"):
                if (
                    self._distance_to_segment(pos, obj["p1"], obj["p2"])
                    <= self.hit_tolerance
                ):
                    return i
            elif t == "text":
                fm = QFontMetrics(obj["font"])
                br = QRect(
                    obj["pos"], QSize(fm.horizontalAdvance(obj["text"]), fm.height())
                )
                if br.adjusted(
                    -self.hit_tolerance,
                    -self.hit_tolerance,
                    self.hit_tolerance,
                    self.hit_tolerance,
                ).contains(pos):
                    return i
        return None

    def set_fill_enabled(self, enabled: bool):
        self.fill_enabled = bool(enabled)
        self.update()

    def set_fill_color(self, color: QColor):
        self.fill_color = QColor(color)
        self.update()

    def set_text_size(self, px: int):
        self.text_font.setPointSize(int(px))
        self.update()

    def clear(self):
        self.image.fill(Qt.white)
        self.update()

    @staticmethod
    def _norm_rect(a: QPoint, b: QPoint) -> QRect:
        return QRect(
            min(a.x(), b.x()), min(a.y(), b.y()), abs(a.x() - b.x()), abs(a.y() - b.y())
        )

    @staticmethod
    def _arrow_head(p1: QPointF, p2: QPointF, size: float) -> QPolygonF:
        vec = QPointF(p2.x() - p1.x(), p2.y() - p1.y())
        length = (vec.x() ** 2 + vec.y() ** 2) ** 0.5 or 1.0
        ux, uy = vec.x() / length, vec.y() / length
        nx, ny = -uy, ux
        back = QPointF(p2.x() - ux * size, p2.y() - uy * size)
        left = QPointF(back.x() + nx * size * 0.5, back.y() + ny * size * 0.5)
        right = QPointF(back.x() - nx * size * 0.5, back.y() - ny * size * 0.5)
        return QPolygonF([p2, left, right])

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self._event_zoom = self.zoom
        tools_need_grab = {
            "pen",
            "eraser",
            "rect",
            "ellipse",
            "line",
            "arrow",
            "move",
            "select",
        }
        if self.tool in tools_need_grab:
            w = self.window()
            can_grab = self.isVisible() and (w is not None and w.isVisible())
            wh = w.windowHandle() if (w is not None) else None
            if wh is not None and hasattr(wh, "isExposed"):
                can_grab = can_grab and wh.isExposed()
            if can_grab:
                try:
                    self.grabMouse()
                except Exception:
                    pass
        if self.tool == "text":
            try:
                self.releaseMouse()
            except Exception:
                pass
            w = self.window()
            if (
                self._text_input_active
                or not self.isVisible()
                or w is None
                or not w.isVisible()
            ):
                return
            self._text_input_active = True
            try:
                dlg = QInputDialog(w)
                dlg.setModal(True)
                dlg.setWindowTitle("Текст")
                dlg.setLabelText("Введите текст:")
                dlg.setInputMode(QInputDialog.TextInput)
                dlg.setWindowFlag(Qt.WindowStaysOnTopHint, True)
                fg = dlg.frameGeometry()
                fg.moveCenter(w.frameGeometry().center())
                dlg.move(fg.topLeft())
                if dlg.exec() == QDialog.Accepted:
                    if self.tool == "text" and self.isVisible() and w.isVisible():
                        text = dlg.textValue().strip()
                        if text:
                            img_pos = self._to_image_pos(
                                e.position().toPoint(), zoom=self._event_zoom
                            )
                            obj = {
                                "type": "text",
                                "text": text,
                                "pos": img_pos,
                                "font": QFont(self.text_font),
                                "pen": QPen(
                                    self.pen_color,
                                    self.pen_width,
                                    Qt.SolidLine,
                                    Qt.RoundCap,
                                    Qt.RoundJoin,
                                ),
                            }
                            self._push_undo_snapshot()
                            self.objects.append(obj)
                            self.update()
            finally:
                self._text_input_active = False
            return
        if self.tool == "select":
            self.is_drawing = True
            self.last_pos = self._to_image_pos(
                e.position().toPoint(), zoom=self._event_zoom
            )
            self.selected_index = self._object_at(self.last_pos)
            self.drag_start = self.last_pos
            self.drag_last = self.last_pos
            return
        if self.tool == "move":
            self.move_active = True
            self.is_drawing = True
            self.move_start = self._to_image_pos(
                e.position().toPoint(), zoom=self._event_zoom
            )
            self.image_before_move = self.image.copy()
            self._move_bbox = self._content_bbox()
            self.move_delta = QPoint()
            return
        self.is_drawing = True
        self.last_pos = self._to_image_pos(
            e.position().toPoint(), zoom=self._event_zoom
        )
        self.start_pos = self.last_pos
        self.preview_pos = self.last_pos
        if self.tool in ("pen", "eraser"):
            self._push_undo_snapshot()
            painter = QPainter(self.image)
            pen = QPen(
                Qt.white if self.tool == "eraser" else self.pen_color,
                self.pen_width,
                Qt.SolidLine,
                Qt.RoundCap,
                Qt.RoundJoin,
            )
            painter.setPen(pen)
            painter.drawPoint(self.last_pos)
            painter.end()
            self.update()

    def mouseMoveEvent(self, e):
        if not self.is_drawing:
            return
        if self.tool == "move" and self.move_active:
            pos_img = self._to_image_pos(e.position().toPoint(), zoom=self._event_zoom)
            raw = pos_img - self.move_start
            self.move_delta = self._clamp_delta_to_box(
                raw.x(), raw.y(), self._move_bbox
            )
            self.update()
            return
        if self.tool == "select" and self.selected_index is not None:
            pos_img = self._to_image_pos(e.position().toPoint(), zoom=self._event_zoom)
            raw = pos_img - self.drag_last
            if not raw.isNull():
                obj = self.objects[self.selected_index]
                box = self._object_bbox(obj)
                allowed = self._clamp_delta_to_box(raw.x(), raw.y(), box)
                if not self._drag_changed:
                    self._push_undo_snapshot()
                    self._drag_changed = True
                self._translate_object(obj, allowed)
                self.update()
            return
        pos_img = self._to_image_pos(e.position().toPoint(), zoom=self._event_zoom)
        if self.tool in ("pen", "eraser"):
            painter = QPainter(self.image)
            pen = QPen(
                Qt.white if self.tool == "eraser" else self.pen_color,
                self.pen_width,
                Qt.SolidLine,
                Qt.RoundCap,
                Qt.RoundJoin,
            )
            painter.setPen(pen)
            painter.drawLine(self.last_pos, pos_img)
            painter.end()
            self.last_pos = pos_img
            self.update()
        else:
            self.preview_pos = pos_img
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or not self.is_drawing:
            return
        try:
            self.releaseMouse()
        except Exception:
            pass
        self.is_drawing = False
        end_img = self._to_image_pos(e.position().toPoint(), zoom=self._event_zoom)
        if self.tool == "move" and self.move_active:
            self.move_active = False
            dx, dy = self.move_delta.x(), self.move_delta.y()
            if dx or dy:
                self._push_undo_snapshot()
                newimg = QImage(self.image.size(), self.image.format())
                newimg.fill(Qt.white)
                p = QPainter(newimg)
                p.setRenderHint(QPainter.Antialiasing, True)
                p.drawImage(dx, dy, self.image_before_move)
                p.end()
                self.image = newimg
                shift = QPoint(dx, dy)
                for obj in self.objects:
                    self._translate_object(obj, shift)
            self.image_before_move = None
            self.move_delta = QPoint()
            self._move_bbox = None
            self.update()
            if self._pending_zoom is not None:
                z = self._pending_zoom
                self._pending_zoom = None
                self.set_zoom(z)
            return
        if self.tool == "select":
            self._drag_changed = False
            self.selected_index = None
            self.update()
            if self._pending_zoom is not None:
                z = self._pending_zoom
                self._pending_zoom = None
                self.set_zoom(z)
            return
        if self.tool in ("rect", "ellipse", "line", "arrow"):
            self._push_undo_snapshot()
            painter = QPainter(self.image)
            pen = QPen(
                self.pen_color,
                self.pen_width,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            painter.setPen(pen)
            brush = Qt.BrushStyle.NoBrush
            if self.tool in ("rect", "ellipse") and self.fill_enabled:
                brush = QBrush(self.fill_color)
            painter.setBrush(brush)
            if self.tool == "rect":
                painter.drawRect(self._norm_rect(self.start_pos, end_img))
            elif self.tool == "ellipse":
                painter.drawEllipse(self._norm_rect(self.start_pos, end_img))
            elif self.tool == "line":
                painter.drawLine(self.start_pos, end_img)
            elif self.tool == "arrow":
                p1, p2 = QPointF(self.start_pos), QPointF(end_img)
                painter.drawLine(p1, p2)
                head = self._arrow_head(p1, p2, max(10, self.pen_width * 3))
                painter.setBrush(QBrush(self.pen_color))
                painter.drawPolygon(head)
            painter.end()
            self.update()
            if self._pending_zoom is not None:
                z = self._pending_zoom
                self._pending_zoom = None
                self.set_zoom(z)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.white)
        pad = getattr(self, "viewport_pad", 0)
        canvas_w = int(self.image.width() * self.zoom)
        canvas_h = int(self.image.height() * self.zoom)
        painter.fillRect(
            QRect(pad, pad, canvas_w, canvas_h),
            getattr(self, "canvas_bg", QColor("#f3f4f6")),
        )
        painter.translate(pad / self.zoom, pad / self.zoom)
        painter.scale(self.zoom, self.zoom)
        if (
            self.tool == "move"
            and self.move_active
            and self.image_before_move is not None
        ):
            painter.drawImage(self.move_delta, self.image_before_move)
            painter.save()
            painter.translate(self.move_delta)
            self._draw_objects(painter)
            painter.restore()
        else:
            painter.drawImage(0, 0, self.image)
            self._draw_objects(painter)
        if self.is_drawing and self.tool in ("rect", "ellipse", "line", "arrow"):
            pen = QPen(
                self.pen_color, self.pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin
            )
            painter.setPen(pen)
            painter.setBrush(
                QBrush(self.fill_color)
                if (self.tool in ("rect", "ellipse") and self.fill_enabled)
                else Qt.NoBrush
            )
            if self.tool == "rect":
                painter.drawRect(self._norm_rect(self.start_pos, self.preview_pos))
            elif self.tool == "ellipse":
                painter.drawEllipse(self._norm_rect(self.start_pos, self.preview_pos))
            elif self.tool == "line":
                painter.drawLine(self.start_pos, self.preview_pos)
            elif self.tool == "arrow":
                p1, p2 = QPointF(self.start_pos), QPointF(self.preview_pos)
                painter.drawLine(p1, p2)
                head = self._arrow_head(p1, p2, max(10, self.pen_width * 3))
                painter.setBrush(QBrush(self.pen_color))
                painter.drawPolygon(head)
        painter.resetTransform()
        outer = QRect(pad - 1, pad - 1, canvas_w + 2, canvas_h + 2)
        inner = QRect(pad, pad, canvas_w, canvas_h)
        if self.show_layout_frame:
            dash = QPen(QColor("#9aa0a6"))
            dash.setStyle(Qt.DashLine)
            dash.setCosmetic(True)
            painter.setPen(dash)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRect(pad, pad, canvas_w, canvas_h))
            m = int(round(self.safe_margin * self.zoom))
            if m > 0 and 2 * m < min(canvas_w, canvas_h):
                painter.drawRect(
                    QRect(pad + m, pad + m, canvas_w - 2 * m, canvas_h - 2 * m)
                )
        pen = QPen(getattr(self, "canvas_border_dark", QColor("#2f3338")), 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(outer)
        pen2 = QPen(getattr(self, "canvas_border_light", QColor("#ffffff")), 1)
        pen2.setCosmetic(True)
        painter.setPen(pen2)
        painter.drawRect(inner)
        painter.end()

    def sizeHint(self):
        return QSize(self.image.width(), self.image.height())

    def get_image(self) -> QImage:
        if not self.objects:
            return self.image
        out = QImage(self.image.size(), self.image.format())
        out.fill(Qt.white)
        p = QPainter(out)
        p.drawImage(0, 0, self.image)
        self._draw_objects(p)
        p.end()
        return out


class DrawingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Рисование")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.resize(1100, 700)
        self.canvas = DrawingCanvas(self)
        self.canvas.setMinimumSize(800, 500)
        sc_undo = QShortcut(QKeySequence.Undo, self)
        sc_undo.setContext(Qt.WidgetWithChildrenShortcut)
        sc_undo.activated.connect(self.canvas.undo)
        sc_redo = QShortcut(QKeySequence.Redo, self)
        sc_redo.setContext(Qt.WidgetWithChildrenShortcut)
        sc_redo.activated.connect(self.canvas.redo)
        tools_layout = QHBoxLayout()
        tools_layout.setContentsMargins(6, 6, 6, 6)
        tools_layout.setSpacing(8)

        def _mk_tool(text: str, tool_name: str):
            btn = QToolButton(self)
            btn.setText(text)
            btn.setCheckable(True)
            btn.clicked.connect(lambda: self.canvas.set_tool(tool_name))
            return btn

        self.btn_select = _mk_tool("☰ Выбор", "select")
        self.btn_pencil = _mk_tool("✎ Карандаш", "pen")
        self.btn_move = _mk_tool("🖐 Перемещение", "move")
        self.btn_rect = _mk_tool("▭ Прямоугольник", "rect")
        self.btn_ellipse = _mk_tool("◯ Эллипс", "ellipse")
        self.btn_line = _mk_tool("— Линия", "line")
        self.btn_arrow = _mk_tool("➤ Стрелка", "arrow")
        self.btn_text = _mk_tool("Т Текст", "text")
        self.btn_eraser = _mk_tool("⌫ Ластик", "eraser")
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for b in (
            self.btn_select,
            self.btn_pencil,
            self.btn_move,
            self.btn_rect,
            self.btn_ellipse,
            self.btn_line,
            self.btn_arrow,
            self.btn_text,
            self.btn_eraser,
        ):
            grp.addButton(b)
            tools_layout.addWidget(b)
        self.btn_select.setChecked(True)
        self.canvas.set_tool("select")
        tools_layout.addStretch(1)
        opts = QFormLayout()
        opts.setContentsMargins(6, 0, 6, 6)
        opts.setSpacing(8)
        self.cb_frame = QCheckBox("Границы макета", self)
        self.cb_frame.setChecked(True)
        self.cb_frame.toggled.connect(self.canvas.set_show_frame)
        opts.addRow(self.cb_frame)
        self.spin_margin = QSpinBox(self)
        self.spin_margin.setRange(0, 400)
        self.spin_margin.setValue(getattr(self.canvas, "safe_margin", 16))
        self.spin_margin.valueChanged.connect(self.canvas.set_safe_margin)
        opts.addRow("Отступ, px:", self.spin_margin)
        zoom_row = QHBoxLayout()
        self.btn_zoom_minus = QToolButton(self)
        self.btn_zoom_minus.setText("−")
        self.btn_zoom_plus = QToolButton(self)
        self.btn_zoom_plus.setText("+")
        self.lbl_zoom = QLabel(self)
        self.lbl_zoom.setMinimumWidth(48)
        self.lbl_zoom.setAlignment(Qt.AlignCenter)

        def _update_zoom_label():
            self.lbl_zoom.setText(f"{int(round(self.canvas.zoom * 100))}%")

        def _step_zoom(sign: int):
            z = self.canvas.zoom
            new_z = max(0.1, min(5.0, round((z + sign * 0.05), 2)))
            self.canvas.set_zoom(new_z)
            _update_zoom_label()

        self.btn_zoom_minus.clicked.connect(lambda: _step_zoom(-1))
        self.btn_zoom_plus.clicked.connect(lambda: _step_zoom(+1))
        _update_zoom_label()
        zoom_row.addWidget(self.btn_zoom_minus)
        zoom_row.addWidget(self.lbl_zoom)
        zoom_row.addWidget(self.btn_zoom_plus)
        opts.addRow("Масштаб:", zoom_row)
        self.spin_width = QSpinBox(self)
        self.spin_width.setRange(1, 40)
        self.spin_width.setValue(getattr(self.canvas, "pen_width", 3))
        self.spin_width.valueChanged.connect(self.canvas.set_width)
        opts.addRow("Толщина:", self.spin_width)

        def _btn_color(title: str, getter, setter):
            btn = QPushButton(title, self)

            def pick():
                c = QColorDialog.getColor(getter(), self, title)
                if c.isValid():
                    setter(c)
                    btn.setStyleSheet(f"background: {c.name()};")

            btn.clicked.connect(pick)
            try:
                btn.setStyleSheet(f"background: {getter().name()};")
            except Exception:
                pass
            return btn

        line_color_btn = _btn_color(
            "Цвет линии…",
            lambda: getattr(self.canvas, "pen_color"),
            self.canvas.set_color,
        )
        self.btn_fill = _btn_color(
            "Цвет заливки…",
            lambda: getattr(self.canvas, "fill_color"),
            self.canvas.set_fill_color,
        )

        self.cb_fill = QCheckBox("Заливка", self)
        self.cb_fill.setChecked(getattr(self.canvas, "fill_enabled", False))
        self.cb_fill.toggled.connect(self.on_fill_toggled)
        self.btn_fill.setEnabled(self.cb_fill.isChecked())
        opts.addRow(line_color_btn)
        opts.addRow(self.btn_fill)
        opts.addRow(self.cb_fill)
        self.spin_text = QSpinBox(self)
        self.spin_text.setRange(6, 96)
        self.spin_text.setValue(getattr(self.canvas, "text_size", 18))
        self.spin_text.valueChanged.connect(self.canvas.set_text_size)
        opts.addRow("Размер текста:", self.spin_text)
        self.btn_clear = QPushButton("Очистить", self)
        self.btn_clear.clicked.connect(self.canvas.clear)
        opts.addRow(self.btn_clear)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        tools_wrap = QWidget(self)
        tools_wrap.setLayout(tools_layout)
        tools_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(tools_wrap)
        root.addWidget(self.canvas, 1)
        opts_wrap = QWidget(self)
        opts_wrap.setLayout(opts)
        root.addWidget(opts_wrap)
        root.addWidget(buttons)
        _update_zoom_label()

    def _select_tool(self, btn: QPushButton, tool: str):
        for b in (
            self.btn_pencil,
            self.btn_rect,
            self.btn_ellipse,
            self.btn_line,
            self.btn_arrow,
            self.btn_text,
            self.btn_eraser,
            self.btn_move,
            self.btn_select,
        ):
            b.setChecked(b is btn)
        self.canvas.set_tool(tool)

    def _choose_pen_color(self):
        col = QColorDialog.getColor(self.canvas.pen_color, self, "Цвет линии")
        if col.isValid():
            self.canvas.set_color(col)

    def on_fill_toggled(self, on: bool) -> None:
        self.btn_fill.setEnabled(on)
        if hasattr(self.canvas, "set_fill_enabled"):
            self.canvas.set_fill_enabled(on)

    def _choose_fill_color(self):
        col = QColorDialog.getColor(
            self.canvas.fill_color,
            self,
            "Цвет заливки",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if col.isValid():
            self.canvas.set_fill_color(col)

    def get_image(self) -> QImage:
        return self.canvas.get_image()

    def showEvent(self, e):
        super().showEvent(e)
        p = self.parent()
        if p and isinstance(p, QWidget):
            fg = self.frameGeometry()
            fg.moveCenter(p.frameGeometry().center())
            self.move(fg.topLeft())

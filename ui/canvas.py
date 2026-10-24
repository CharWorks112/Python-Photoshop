"""Canvas — brush/eraser/pencil/lasso/bucket/text/grab + pan/zoom."""
from PyQt5.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QDialog, QVBoxLayout, QLabel, QFontComboBox, QSpinBox,
    QHBoxLayout, QDialogButtonBox, QLineEdit
)
from PyQt5.QtGui import (
    QPixmap, QImage, QColor, QPainter, QPolygonF, QPen,
    QBrush, QFont, QPainterPath, QBitmap, QRegion
)
from PyQt5.QtCore import Qt, QPointF, QPoint, QRectF, pyqtSignal

from core.commands import BrushStrokeCommand, FillCommand
from core.layer import merge_layers, PixelLayer
from core.shape_layer import ShapeLayer, TextShape
from core.image_shape import ImageShape
from ui.image_import_dialog import ImageImportDialog
from core import imagemagick
from core.fill import flood_fill
from core import sounds
from ui._autosize import AutoSizeMixin


TOOL_BRUSH  = "brush"
TOOL_PENCIL = "pencil"
TOOL_ERASER = "eraser"
TOOL_LASSO  = "lasso"
TOOL_BUCKET = "bucket"
TOOL_TEXT   = "text"
TOOL_GRAB   = "grab"
TOOL_IMAGE  = "image"
TOOL_BLUR   = "blur"
TOOL_PICKER = "picker"
TOOL_SHAPE  = "shape"
TOOL_3D_BRUSH = "3d_brush"


class TextDialog(QDialog, AutoSizeMixin):
    def __init__(self, parent=None, existing=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Text" if existing else "Text")
        self.setMinimumWidth(420)
        self.text_edit = QLineEdit(); self.text_edit.setPlaceholderText("Type text…")
        self.font_combo = QFontComboBox()
        self.size_spin = QSpinBox(); self.size_spin.setRange(6, 400); self.size_spin.setValue(48)
        self.size_spin.setSuffix(" px")
        if existing is not None:
            self.text_edit.setText(existing.text)
            self.font_combo.setCurrentFont(existing.font)
            self.size_spin.setValue(existing.font.pointSize() or 48)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(QLabel("Font")); row.addWidget(self.font_combo)
        row.addWidget(self.size_spin)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Text:")); v.addWidget(self.text_edit)
        v.addLayout(row); v.addWidget(buttons)

        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, lambda: self.auto_size(min_w=420, min_h=230))

    def values(self):
        f = self.font_combo.currentFont()
        f.setPointSize(self.size_spin.value())
        return self.text_edit.text(), f


class Canvas(QGraphicsView):
    strokeFinished = pyqtSignal(object, object)
    collabStrokeReady = pyqtSignal(object)
    collabCursorMoved = pyqtSignal(int, int)
    def __init__(self, undo_stack, parent=None):
        super().__init__(parent)
        self.undo_stack = undo_stack
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self._canvas_bg = "#2b2b2b"
        self.setBackgroundBrush(QColor(self._canvas_bg))
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

        self.project = None
        self._applying_remote = False
        self.on_shape_added = None     # callback(layer_idx, shape_idx, shape_dict)
        self.on_layer_added = None     # callback(layer_idx, layer_dict)
        self.on_shape_edited = None    # callback(layer_idx, shape_idx, shape_dict)
        self._remote_cursor_items = {}   # name -> (polygon_item, label_item)
        self._last_remote_hash = None
        self.active_layer = None
        self.tool = TOOL_BRUSH
        self.brush_color = QColor("black")
        self.brush_radius = 12
        self.fill_tolerance = 24

        self._painting = False
        self._last_point = None
        self._before_snapshot = None
        self._lasso_points: list[QPointF] = []
        # drawing-sound state, updated by Preferences
        self.drawing_sound_enabled = True
        self.drawing_sound_sensitivity = 1.0
        self.shape_kind = "rect"     # rect | ellipse
        self._shape_origin = None
        self._shape_preview: QPointF | None = None
        self.selected_shape = None
        self.selected_layer = None
        self._resize_handle = None        # 'tl'|'tr'|'bl'|'br'|None
        self._resize_origin = None        # (x,y,w,h) at grab time
        self._resize_start = None         # QPointF at grab time

        # grab state
        self._grabbing = False
        self._grab_start = None
        self._grab_layer = None
        self._grab_before = None

        self._space_held = False
        self._panning = False
        self._pan_start = None

        self._pixmap_item = None
        self._refresh()

    # ---------- binding ----------
    def set_project(self, project):
        self.project = project
        self.active_layer = project.layers[-1] if project.layers else None
        self._lasso_points.clear()
        self._refresh()
        if project:
            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def set_active_layer(self, layer):
        self.active_layer = layer

    def set_tool(self, tool: str):
        self.tool = tool
        self._lasso_points.clear()
        self._refresh()

    # ---------- rendering ----------
    def _refresh(self):
        self.scene.clear()
        # scene.clear() orphaned our cursor items — re-create lazily
        self._remote_cursor_items = {}
        self._pixmap_item = None
        if not self.project:
            self.setSceneRect(0, 0, 400, 300)
            return
        composite = merge_layers(self.project.layers, self.project.width,
                                 self.project.height, background=self.project.background)
        pix = QPixmap.fromImage(composite)
        self._pixmap_item = QGraphicsPixmapItem(pix)
        self.scene.addItem(self._pixmap_item)
        self.setSceneRect(0, 0, self.project.width, self.project.height)

        # ---------- selection outline + handles ----------
        self._draw_selection_overlay()

        if self.tool == TOOL_LASSO and len(self._lasso_points) >= 2:
            pen = QPen(QColor("white"), 1, Qt.DashLine)
            poly = QPolygonF(self._lasso_points)
            if len(self._lasso_points) > 2:
                poly.append(self._lasso_points[0])
            self.scene.addPolygon(poly, pen, QBrush(Qt.NoBrush))

        if self.tool == TOOL_SHAPE and self._shape_origin is not None and self._shape_preview is not None:
            from PyQt5.QtWidgets import QGraphicsRectItem, QGraphicsEllipseItem
            from PyQt5.QtCore import QRectF
            o = self._shape_origin
            pv = self._shape_preview
            r = QRectF(min(o.x(), pv.x()), min(o.y(), pv.y()),
                       abs(pv.x() - o.x()), abs(pv.y() - o.y()))
            pen = QPen(QColor("white"), 1, Qt.DashLine)
            if self.shape_kind == "ellipse":
                self.scene.addEllipse(r, pen)
            else:
                self.scene.addRect(r, pen)

    # ---------- zoom / pan ----------
    def wheelEvent(self, event):
        if not self.project:
            return super().wheelEvent(event)
        f = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)
        cb = getattr(self, "on_zoom_changed", None)
        if cb: cb()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_held = True; self.setCursor(Qt.OpenHandCursor)
            event.accept(); return
        if event.key() == Qt.Key_0 and event.modifiers() & Qt.ControlModifier:
            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            event.accept(); return
        if event.key() == Qt.Key_1 and event.modifiers() & Qt.ControlModifier:
            self.resetTransform(); event.accept(); return
        if event.key() == Qt.Key_Escape and self.tool == TOOL_LASSO:
            self._lasso_points.clear(); self._refresh(); event.accept(); return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_held = False; self.setCursor(Qt.ArrowCursor)
            event.accept(); return
        super().keyReleaseEvent(event)

    # ---------- mouse ----------
    def _map(self, event): return self.mapToScene(event.pos())

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton or (self._space_held and event.button() == Qt.LeftButton):
            self._panning = True; self._pan_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor); event.accept(); return

        if not self.project or not self.active_layer:
            return super().mousePressEvent(event)

        # Alt+click = eyedropper (any tool)
        if event.button() == Qt.LeftButton and event.modifiers() & Qt.AltModifier:
            self._pick_color_at(self._map(event))
            event.accept(); return

        # handle-resize when a shape is selected
        if event.button() == Qt.LeftButton and self.selected_shape is not None:
            hit = self._handle_at(self._map(event))
            if hit:
                self._resize_handle = hit
                self._resize_start = self._map(event)
                b = self.selected_shape.bounds()
                self._resize_origin = (b.x(), b.y(), b.width(), b.height())
                event.accept(); return

        if event.button() == Qt.LeftButton:
            t = self.tool
            if t == TOOL_PICKER:
                self._pick_color_at(self._map(event))
                event.accept(); return
            if t in (TOOL_BRUSH, TOOL_PENCIL, TOOL_ERASER, TOOL_BLUR, TOOL_3D_BRUSH):
                self._begin_stroke(event); return
            if t == TOOL_LASSO:
                self._lasso_points = [self._map(event)]
                self._painting = True; self._refresh(); return
            if t == TOOL_BUCKET:
                self._bucket_fill(self._map(event)); return
            if t == TOOL_TEXT:
                self._place_text(self._map(event)); return
            if t == TOOL_GRAB:
                self._begin_grab(self._map(event)); return
            if t == TOOL_IMAGE:
                self._place_image(self._map(event)); return
            if t == TOOL_SHAPE:
                self._shape_origin = self._map(event)
                self._shape_preview = self._shape_origin
                event.accept(); return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        try:
            pt = self.mapToScene(event.pos())
            self.collabCursorMoved.emit(int(pt.x()), int(pt.y()))
        except Exception:
            pass
        if self._panning:
            d = event.pos() - self._pan_start; self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
            event.accept(); return
        if self._resize_handle is not None:
            self._do_resize(self._map(event))
            event.accept(); return
        if self._grabbing:
            self._do_grab(self._map(event))
            event.accept(); return
        if self._painting and self.active_layer:
            if self.tool in (TOOL_BRUSH, TOOL_PENCIL, TOOL_ERASER, TOOL_BLUR, TOOL_3D_BRUSH):
                pt = self._map(event)
                if self.drawing_sound_enabled:
                    dx = pt.x() - self._last_point.x()
                    dy = pt.y() - self._last_point.y()
                    speed = (dx*dx + dy*dy) ** 0.5
                    # normalize: fast drag ≈ 0.7 volume, slow ≈ 0.15
                    vol = min(0.7, 0.15 + speed * 0.015 * self.drawing_sound_sensitivity)
                    sounds.set_loop_volume('brush_loop', vol)
                self._stroke_segment(self._last_point, pt)
                self._last_point = pt
                self._refresh(); event.accept(); return
            if self.tool == TOOL_LASSO:
                self._lasso_points.append(self._map(event))
                self._refresh(); event.accept(); return
        if self.tool == TOOL_SHAPE and self._shape_origin is not None:
            self._shape_preview = self._map(event)
            self._refresh(); event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning:
            self._panning = False
            self.setCursor(Qt.OpenHandCursor if self._space_held else Qt.ArrowCursor)
            event.accept(); return
        if self._resize_handle is not None:
            # push undo for the resize
            if not hasattr(self.selected_shape, 'w') or not hasattr(self.selected_shape, 'h'):
                self._resize_handle = None
                self._resize_origin = None
                event.accept()
                return
            from core.commands import ResizeShapeCommand
            self.undo_stack.push(ResizeShapeCommand(
                self.selected_layer, self.selected_shape,
                self._resize_origin,
                (self.selected_shape.x, self.selected_shape.y,
                 self.selected_shape.w, self.selected_shape.h),
                on_change=self._refresh))
            if self.on_shape_edited and not self._applying_remote:
                try:
                    li = self.project.layers.index(self.selected_layer)
                    si = self.selected_layer.shapes.index(self.selected_shape)
                    payload = self.selected_shape.to_wire() if hasattr(self.selected_shape, 'to_wire') else self.selected_shape.to_dict()
                    self.on_shape_edited(li, si, payload)
                except Exception:
                    pass
            self._resize_handle = None
            self._resize_origin = None
            event.accept(); return
        if self._grabbing:
            self._end_grab()
            event.accept(); return
        if self._painting and self.active_layer:
            if self.tool in (TOOL_BRUSH, TOOL_PENCIL, TOOL_ERASER, TOOL_BLUR, TOOL_3D_BRUSH):
                self._end_stroke(); event.accept(); return
            if self.tool == TOOL_LASSO:
                self._painting = False
                self._finish_lasso(); event.accept(); return
        if self.tool == TOOL_SHAPE and self._shape_origin is not None:
            self._finish_shape(self._map(event))
            event.accept(); return
        super().mouseReleaseEvent(event)

    # ---------- brush/pencil/eraser ----------
    def _begin_stroke(self, event):
        # Eraser on a shape layer → rasterize it first so we can erase pixels
        if isinstance(self.active_layer, ShapeLayer):
            if self.tool != TOOL_ERASER:
                return
            self._rasterize_active_shape_layer()
        self._painting = True
        self._before_snapshot = self.active_layer.clone_image()
        self._last_point = self._map(event)
        # tool sound
        tool_sound = {
            TOOL_BRUSH: 'brush',
            TOOL_PENCIL: 'pencil',
            TOOL_ERASER: 'eraser',
            TOOL_BLUR: 'blur',
            TOOL_3D_BRUSH: '3d_brush',
        }.get(self.tool)
        if tool_sound:
            sounds.play(tool_sound)
        if self.drawing_sound_enabled:
            sounds.start_loop('brush_loop', volume=0.35)
        self._paint_at(self._last_point)
        self._refresh()

    def _rasterize_active_shape_layer(self):
        """Convert active ShapeLayer → PixelLayer of same name above it."""
        layer = self.active_layer
        rendered = layer.render_to_image()
        new_layer = PixelLayer(layer.name + " (px)", self.project.width,
                               self.project.height, fill="transparent")
        new_layer.image = rendered

        idx = self.project.layers.index(layer)
        self.project.layers.insert(idx + 1, new_layer)

        # remove the original shape layer (undo-less here — it's part of the erase step)
        self.project.layers.remove(layer)
        self.active_layer = new_layer

        # Clear undo since the rasterization isn't itself undoable — the erase stroke will be
        cb = getattr(self, "on_layers_changed", None)
        if cb: cb()

    def _end_stroke(self):
        sounds.stop_loop('brush_loop')
        was_painting = self._painting
        self._painting = False
        if was_painting:
            try:
                sounds.stop_loop('brush_loop')
            except Exception:
                pass
        if self._before_snapshot is None: return
        after = self.active_layer.clone_image()
        label = {"brush": "Brush", "pencil": "Pencil", "eraser": "Eraser",
                 "blur": "Blur", "3d_brush": "3D Brush"}.get(self.tool, "Stroke")
        self.undo_stack.push(BrushStrokeCommand(
            self.active_layer, self._before_snapshot, after,
            on_change=self._refresh, text=f"{label} Stroke",
        ))
        self._before_snapshot = None
        # collab broadcast
        if not self._applying_remote:
            try:
                self.collabStrokeReady.emit(after)
            except Exception:
                pass

    def _paint_at(self, pt):
        x, y = int(pt.x()), int(pt.y())
        if self.tool == TOOL_ERASER:
            self._erase_dab(x, y); return
        if self.tool == TOOL_BLUR:
            self._blur_dab(x, y); return
        if self.tool == TOOL_3D_BRUSH:
            self._dab_3d(x, y); return
        if self.tool == TOOL_PENCIL:
            # hard 1px-ish dab, no AA
            p = QPainter(self.active_layer.image)
            p.setRenderHint(QPainter.Antialiasing, False)
            r = max(1, self.brush_radius // 3)
            p.setBrush(self.brush_color); p.setPen(Qt.NoPen)
            p.drawRect(x - r // 2, y - r // 2, r, r)
            p.end(); return
        self.active_layer.paint_dab(x, y, self.brush_radius, self.brush_color)

    def _erase_dab(self, x, y):
        if not self.active_layer.visible: return
        p = QPainter(self.active_layer.image)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.setBrush(Qt.transparent); p.setPen(Qt.NoPen)
        p.drawEllipse(x - self.brush_radius, y - self.brush_radius,
                      self.brush_radius * 2, self.brush_radius * 2)
        p.end()

    def _blur_dab(self, x, y):
        if not self.active_layer.visible:
            return
        if not hasattr(self.active_layer, "image"):
            return
        from PyQt5.QtGui import QImage
        img = self.active_layer.image
        r = max(2, self.brush_radius // 2)
        x0, y0 = max(0, x - r), max(0, y - r)
        x1 = min(img.width(), x + r)
        y1 = min(img.height(), y + r)
        if x1 <= x0 or y1 <= y0:
            return
        # blur the patch using Qt's built-in smoothing via scale down/up
        patch = img.copy(x0, y0, x1 - x0, y1 - y0)
        small = patch.scaled(max(1, patch.width() // 3),
                             max(1, patch.height() // 3),
                             Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        blurred = small.scaled(patch.width(), patch.height(),
                               Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        p = QPainter(img)
        # clip to a circle so it looks like a brush
        from PyQt5.QtGui import QPainterPath
        path = QPainterPath()
        path.addEllipse(x - r, y - r, r * 2, r * 2)
        p.setClipPath(path)
        p.drawImage(x0, y0, blurred)
        p.end()

    def _pick_color_at(self, pt):
        """Pick the *visible* color at (x, y) — composites all layers,
        so it works on shape layers (images, text) too."""
        if not self.project:
            return
        x, y = int(pt.x()), int(pt.y())
        if not (0 <= x < self.project.width and 0 <= y < self.project.height):
            return
        # composite (respects visibility/opacity)
        composite = merge_layers(self.project.layers, self.project.width,
                                 self.project.height,
                                 background=self.project.background)
        c = composite.pixelColor(x, y)
        self.brush_color = c
        cb = getattr(self, "on_color_picked", None)
        if cb: cb(c)

    def _emit_layer_added(self, layer):
        """Broadcast layer_add for a layer that was auto-created by a tool."""
        if self.on_layer_added is None or self._applying_remote:
            return
        try:
            from extensions.collab.protocol import layer_to_wire
            li = self.project.layers.index(layer)
            self.on_layer_added(li, layer_to_wire(layer))
        except Exception as e:
            print(f"[collab] emit layer_add failed: {e}")

    def _finish_shape(self, pt):
        from PyQt5.QtCore import QRectF
        o = self._shape_origin
        self._shape_origin = None
        self._shape_preview = None
        w = abs(pt.x() - o.x()); h = abs(pt.y() - o.y())
        if w < 3 or h < 3:
            self._refresh()
            return
        x = min(o.x(), pt.x()); y = min(o.y(), pt.y())

        # --- auto-create a shape layer if needed ---
        from core.shape_layer import ShapeLayer
        if not isinstance(self.active_layer, ShapeLayer):
            layer = ShapeLayer(
                f"Shapes {sum(1 for l in self.project.layers if isinstance(l, ShapeLayer)) + 1}",
                self.project.width, self.project.height)
            self.project.layers.append(layer)
            self.active_layer = layer
            self._notify_layers_changed()
            try:
                self._emit_layer_added(layer)
            except Exception as e:
                print(f'[collab] shape layer_add failed: {e}')

        # --- build the shape ---
        from core.shape_objects import RectShape, EllipseShape
        from core.commands import AddShapeCommand
        fill = QColor(self.brush_color)
        stroke = QColor("#000000") if fill.lightness() > 200 else QColor("#ffffff")
        klass = RectShape if self.shape_kind == "rect" else EllipseShape
        shape = klass(x, y, w, h, fill, stroke, 2)
        sounds.play('shape')
        self.undo_stack.push(AddShapeCommand(self.active_layer, shape,
                                             on_change=self._refresh))

        # --- broadcast the shape ---
        if self.on_shape_added and not self._applying_remote:
            try:
                li = self.project.layers.index(self.active_layer)
                si = len(self.active_layer.shapes) - 1
                self.on_shape_added(li, si, shape.to_dict())
            except Exception as e:
                print(f'[collab] shape shape_add failed: {e}')

        self.selected_layer = self.active_layer
        self.selected_shape = shape
        self._refresh()

    def _dab_3d(self, x, y):
        """Sphere-shaded dab: radial gradient from top-left highlight
        to darker rim. Gives paint a raised, metallic look."""
        if not self.active_layer.visible:
            return
        from PyQt5.QtGui import QRadialGradient, QBrush, QColor
        r = self.brush_radius
        base = QColor(self.brush_color)
        if base.alpha() == 0:
            base.setAlpha(255)

        # Colors: highlight (lightened), mid (base), shadow (darkened)
        def shift(c, factor):
            v = c.value()
            new_v = max(0, min(255, int(v * factor)))
            new = QColor.fromHsv(c.hue() if c.hue() >= 0 else 0,
                                 c.saturation(), new_v, c.alpha())
            return new

        highlight = shift(base, 1.6)
        highlight.setAlpha(min(255, base.alpha() + 40))
        mid = base
        shadow = shift(base, 0.55)

        p = QPainter(self.active_layer.image)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)

        # radial gradient: offset center toward top-left for light source
        grad = QRadialGradient(x - r * 0.35, y - r * 0.35, r * 1.4,
                               x - r * 0.35, y - r * 0.35)
        grad.setColorAt(0.0, highlight)
        grad.setColorAt(0.45, mid)
        grad.setColorAt(1.0, shadow)
        p.setBrush(QBrush(grad))
        p.drawEllipse(x - r, y - r, r * 2, r * 2)
        p.end()

    # ---------- shape selection + resize handles ----------
    def _draw_selection_overlay(self):
        shape = self.selected_shape
        if shape is None or self.selected_layer is None:
            return
        if self.selected_layer not in self.project.layers:
            self.selected_shape = None
            self.selected_layer = None
            return
        if not hasattr(shape, "bounds"):
            return
        if not hasattr(shape, 'w') or not hasattr(shape, 'h'):
            # non-rect shapes (text/image) still get an outline via bounds()
            r = shape.bounds()
        else:
            r = shape.bounds()
        from PyQt5.QtWidgets import QGraphicsRectItem
        from PyQt5.QtCore import QRectF
        pen = QPen(QColor("#1f6feb"), 1, Qt.DashLine)
        self.scene.addRect(r, pen)
        # corner handles — 8px squares
        hs = 8
        if not hasattr(shape, 'w') or not hasattr(shape, 'h'):
            return
        for hx, hy in (
            (r.left(), r.top()),
            (r.right(), r.top()),
            (r.left(), r.bottom()),
            (r.right(), r.bottom()),
        ):
            self.scene.addRect(QRectF(hx - hs/2, hy - hs/2, hs, hs),
                               QPen(QColor("#1f6feb"), 1),
                               QBrush(QColor("#ffffff")))

    def _handle_at(self, pt: QPointF) -> str | None:
        shape = self.selected_shape
        if shape is None:
            return None
        r = shape.bounds()
        hs = 10
        corners = {
            "tl": (r.left(), r.top()),
            "tr": (r.right(), r.top()),
            "bl": (r.left(), r.bottom()),
            "br": (r.right(), r.bottom()),
        }
        for key, (hx, hy) in corners.items():
            if abs(pt.x() - hx) <= hs and abs(pt.y() - hy) <= hs:
                return key
        return None

    def _pick_shape_under(self, pt: QPointF):
        """Topmost shape under `pt`, searching top→bottom of layer stack."""
        from core.shape_layer import ShapeLayer
        for layer in reversed(self.project.layers):
            if not isinstance(layer, ShapeLayer) or not layer.visible:
                continue
            for s in reversed(layer.shapes):
                try:
                    if s.bounds().contains(pt):
                        return layer, s
                except Exception:
                    continue
        return None, None

    def _do_resize(self, pt: QPointF):
        if self.selected_shape is None or self._resize_origin is None:
            return
        x0, y0, w0, h0 = self._resize_origin
        sx, sy = self._resize_start.x(), self._resize_start.y()
        dx = pt.x() - sx
        dy = pt.y() - sy
        h = self._resize_handle
        # compute new rect from the *opposite* fixed corner
        if h == "br":
            nx, ny = x0, y0
            nw, nh = w0 + dx, h0 + dy
        elif h == "tl":
            nw, nh = w0 - dx, h0 - dy
            nx, ny = x0 + dx, y0 + dy
        elif h == "tr":
            nw, nh = w0 + dx, h0 - dy
            nx, ny = x0, y0 + dy
        elif h == "bl":
            nw, nh = w0 - dx, h0 + dy
            nx, ny = x0 + dx, y0
        else:
            return
        if hasattr(self.selected_shape, "set_bounds"):
            self.selected_shape.set_bounds(nx, ny, max(4, nw), max(4, nh))
        self._refresh()

    def _stroke_segment(self, a, b):
        dx, dy = b.x() - a.x(), b.y() - a.y()
        dist = (dx * dx + dy * dy) ** 0.5
        step = max(1, self.brush_radius // 2 if self.tool != TOOL_PENCIL else 1)
        n = max(1, int(dist / step))
        for i in range(n + 1):
            t = i / n
            self._paint_at(QPointF(a.x() + dx * t, a.y() + dy * t))

    # ---------- lasso ----------
    def _finish_lasso(self):
        if len(self._lasso_points) < 3 or isinstance(self.active_layer, ShapeLayer):
            self._lasso_points.clear(); self._refresh(); return
        before = self.active_layer.clone_image()
        region = self._lasso_region()
        p = QPainter(self.active_layer.image)
        p.setClipRegion(region)
        p.fillRect(self.active_layer.image.rect(), self.brush_color)
        p.end()
        after = self.active_layer.clone_image()
        self.undo_stack.push(FillCommand(self.active_layer, before, after,
                                         on_change=self._refresh, text="Lasso Fill"))
        self._lasso_points.clear(); self._refresh()

    def _lasso_region(self):
        path = QPainterPath(); path.addPolygon(QPolygonF(self._lasso_points))
        path.closeSubpath()
        mask = QBitmap(self.project.width, self.project.height); mask.clear()
        mp = QPainter(mask)
        mp.setBrush(Qt.color1); mp.setPen(Qt.NoPen); mp.drawPath(path); mp.end()
        return QRegion(mask)

    # ---------- bucket ----------
    def _bucket_fill(self, pt):
        if isinstance(self.active_layer, ShapeLayer):
            return
        sounds.play('bucket')
        before = self.active_layer.clone_image()
        if not flood_fill(self.active_layer.image, int(pt.x()), int(pt.y()),
                          self.brush_color, self.fill_tolerance):
            return
        after = self.active_layer.clone_image()
        self.undo_stack.push(FillCommand(self.active_layer, before, after,
                                         on_change=self._refresh, text="Bucket Fill"))
        self._refresh()

    # ---------- text (as vector shape on its own layer) ----------
    def _place_text(self, pt):
        sounds.play('text')
        dlg = TextDialog(self)
        if dlg.exec_() != dlg.Accepted:
            return
        text, font = dlg.values()
        if not text:
            return

        # --- auto-create a shape layer if needed ---
        created_layer = False
        if not isinstance(self.active_layer, ShapeLayer):
            shape_layer = ShapeLayer(
                f"Text {sum(1 for l in self.project.layers if isinstance(l, ShapeLayer)) + 1}",
                self.project.width, self.project.height)
            self.project.layers.append(shape_layer)
            self._notify_layers_changed()
            self.active_layer = shape_layer
            created_layer = True
            try:
                self._emit_layer_added(shape_layer)
            except Exception as e:
                print(f'[collab] text layer_add failed: {e}')

        # --- add the text shape ---
        from core.commands import AddShapeCommand
        shape = TextShape(pt.x(), pt.y(), text, font, self.brush_color)
        self.undo_stack.push(AddShapeCommand(self.active_layer, shape,
                                             on_change=self._refresh))

        # --- broadcast the shape (skip when the layer_add already carried it) ---
        if self.on_shape_added and not self._applying_remote:
            try:
                li = self.project.layers.index(self.active_layer)
                si = len(self.active_layer.shapes) - 1
                self.on_shape_added(li, si, shape.to_dict())
            except Exception as e:
                print(f'[collab] text shape_add failed: {e}')

        self.selected_layer = self.active_layer
        self.selected_shape = shape
        self._refresh()

    def mouseDoubleClickEvent(self, event):
        if not self.project:
            return super().mouseDoubleClickEvent(event)
        pt = self._map(event)

        layer_hit, shape_hit = self._pick_shape_under(pt)
        if layer_hit is not None and shape_hit is not None:
            # select (so the user can drag a handle to resize)
            self.selected_layer = layer_hit
            self.selected_shape = shape_hit
            self._refresh()

        # find the topmost shape layer with a shape under the cursor
        for layer in reversed(self.project.layers):
            if not isinstance(layer, ShapeLayer) or not layer.visible:
                continue
            hit = None
            for s in reversed(layer.shapes):
                if s.bounds().contains(pt):
                    hit = s; break
            if hit is None:
                continue

            if isinstance(hit, TextShape):
                self._edit_text_shape(layer, hit); return
            if isinstance(hit, ImageShape):
                self._edit_image_shape(layer, hit); return
        super().mouseDoubleClickEvent(event)

    def _edit_text_shape(self, layer, shape):
        dlg = TextDialog(self, existing=shape)
        if dlg.exec_() != dlg.Accepted:
            return
        text, font = dlg.values()
        if not text:
            return
        from core.commands import EditShapeCommand
        new_shape = TextShape(shape.x, shape.y, text, font, self.brush_color)
        self.undo_stack.push(EditShapeCommand(layer, shape, new_shape,
                                              on_change=self._refresh,
                                              text="Edit Text"))
        if self.on_shape_edited and not self._applying_remote:
            try:
                li = self.project.layers.index(layer)
                si = layer.shapes.index(new_shape)
                self.on_shape_edited(li, si, new_shape.to_dict())
            except Exception:
                pass
        self._refresh()

    def _edit_image_shape(self, layer, shape):
        existing = {
            "source": shape.source_path,
            "scale": shape.scale,
            "rotation": shape.rotation,
            "effects": shape.effects,
            "pixel_override": shape.pixel_override,
        }
        dlg = ImageImportDialog(self, existing=existing)
        if dlg.exec_() != dlg.Accepted:
            return
        v = dlg.values()
        from core.commands import EditShapeCommand
        new_shape = ImageShape(shape.x, shape.y, v["path"],
                               scale=v["scale"], rotation=v["rotation"],
                               effects=v["effects"],
                               pixel_override=v.get("pixel_override"))
        self.undo_stack.push(EditShapeCommand(layer, shape, new_shape,
                                              on_change=self._refresh,
                                              text="Edit Image"))
        if self.on_shape_edited and not self._applying_remote:
            try:
                li = self.project.layers.index(layer)
                si = layer.shapes.index(new_shape)
                payload = new_shape.to_wire() if hasattr(new_shape, 'to_wire') else new_shape.to_dict()
                self.on_shape_edited(li, si, payload)
            except Exception:
                pass
        self._refresh()

    def _place_image(self, pt):
        sounds.play('image')
        dlg = ImageImportDialog(self)
        if dlg.exec_() != dlg.Accepted:
            return
        v = dlg.values()

        # --- auto-create a shape layer if needed ---
        if not isinstance(self.active_layer, ShapeLayer):
            shape_layer = ShapeLayer(
                f"Image {sum(1 for l in self.project.layers if isinstance(l, ShapeLayer)) + 1}",
                self.project.width, self.project.height)
            self.project.layers.append(shape_layer)
            self.active_layer = shape_layer
            self._notify_layers_changed()
            try:
                self._emit_layer_added(shape_layer)
            except Exception as e:
                print(f'[collab] image layer_add failed: {e}')

        # --- create the image shape ---
        from core.commands import AddShapeCommand
        shape = ImageShape(pt.x(), pt.y(), v["path"],
                           scale=v["scale"], rotation=v["rotation"],
                           effects=v["effects"],
                           pixel_override=v.get("pixel_override"))
        self.undo_stack.push(AddShapeCommand(self.active_layer, shape,
                                             on_change=self._refresh))

        # --- broadcast the shape with embedded pixels ---
        if self.on_shape_added and not self._applying_remote:
            try:
                li = self.project.layers.index(self.active_layer)
                si = len(self.active_layer.shapes) - 1
                payload = shape.to_wire() if hasattr(shape, "to_wire") else shape.to_dict()
                self.on_shape_added(li, si, payload)
            except Exception as e:
                print(f'[collab] image shape_add failed: {e}')

        self.selected_layer = self.active_layer
        self.selected_shape = shape
        self._refresh()

    def _notify_layers_changed(self):
        # main_window registers a callback
        cb = getattr(self, "on_layers_changed", None)
        if cb: cb()

    # ---------- grab ----------
    def _begin_grab(self, pt):
        self._grabbing = True
        self._grab_start = pt
        self._grab_layer = self.active_layer

        if isinstance(self.active_layer, ShapeLayer):
            # move the whole shape layer
            self._grab_before = [(s.x, s.y) for s in self.active_layer.shapes]
        else:
            self._grab_before = self.active_layer.clone_image()
            self._grab_empty = PixelLayer("tmp", self.project.width, self.project.height, "transparent")

    def _do_grab(self, pt):
        dx = pt.x() - self._grab_start.x()
        dy = pt.y() - self._grab_start.y()
        if isinstance(self._grab_layer, ShapeLayer):
            for s, (ox, oy) in zip(self._grab_layer.shapes, self._grab_before):
                s.x = ox + dx; s.y = oy + dy
        else:
            # translate by redrawing snapshot at offset
            from PyQt5.QtGui import QPainter
            img = self._grab_layer.image
            img.fill(Qt.transparent)
            p = QPainter(img)
            p.drawImage(int(dx), int(dy), self._grab_before)
            p.end()
        self._refresh()

    def _end_grab(self):
        self._grabbing = False
        dx = 0; dy = 0
        if isinstance(self._grab_layer, ShapeLayer):
            from core.commands import MoveShapeLayerCommand
            self.undo_stack.push(MoveShapeLayerCommand(
                self._grab_layer, self._grab_before,
                [(s.x, s.y) for s in self._grab_layer.shapes],
                on_change=self._refresh,
            ))
        else:
            after = self._grab_layer.clone_image()
            self.undo_stack.push(FillCommand(self._grab_layer, self._grab_before,
                                             after, on_change=self._refresh,
                                             text="Move"))
        self._grab_layer = None
        self._grab_before = None

    def refresh(self):
        self._refresh()

    def set_theme_bg(self, color: str):
        self._canvas_bg = color
        self.setBackgroundBrush(QColor(color))

    # ---------- collab hooks ----------
    def apply_remote_cursor(self, name: str, x: int, y: int):
        """Draw a name-tagged pointer. Reuses one item pair per peer so
        we never leak items or leave trails across _refresh()."""
        try:
            from PyQt5.QtGui import QPolygonF, QPen, QBrush
            from PyQt5.QtCore import QPointF
            from PyQt5.QtWidgets import QGraphicsTextItem

            # lazy-create the pair for this peer
            pair = self._remote_cursor_items.get(name)
            if pair is None:
                poly = QPolygonF([
                    QPointF(0, 0), QPointF(12, 4),
                    QPointF(6, 6), QPointF(8, 12),
                ])
                item = self.scene.addPolygon(
                    poly, QPen(QColor('#ff3030'), 1),
                    QBrush(QColor(255, 48, 48, 220)))
                item.setZValue(1000)
                label = QGraphicsTextItem(name)
                label.setDefaultTextColor(QColor('white'))
                label.setZValue(1001)
                self.scene.addItem(label)
                self._remote_cursor_items[name] = (item, label)
                pair = (item, label)

            item, label = pair
            item.setPos(QPointF(x, y))
            label.setPos(x + 14, y + 2)
        except Exception:
            pass

    def apply_remote_stroke(self, img, layer_index=0):
        if self.project is None:
            return
        if not self.project.layers:
            return
        if layer_index < 0 or layer_index >= len(self.project.layers):
            layer_index = 0
        layer = self.project.layers[layer_index]
        if not hasattr(layer, "image") or img is None:
            return
        try:
            import hashlib
            from PyQt5.QtCore import QBuffer, QIODevice
            buf = QBuffer(); buf.open(QIODevice.WriteOnly)
            img.save(buf, "PNG")
            h = hashlib.md5(bytes(buf.data())).hexdigest()
            if h == self._last_remote_hash:
                return
            self._last_remote_hash = h

            self._applying_remote = True
            try:
                if img.size() != layer.image.size():
                    img = img.scaled(layer.image.size(), Qt.IgnoreAspectRatio,
                                     Qt.SmoothTransformation)
                layer.image = img.convertToFormat(QImage.Format_ARGB32)
                self._refresh()
            finally:
                self._applying_remote = False
        except Exception:
            self._applying_remote = False

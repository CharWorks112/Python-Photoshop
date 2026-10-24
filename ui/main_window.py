"""Main window: menus, docks, layers panel (reorder + hide), brush, undo, export."""
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QAction, QDockWidget, QWidget, QVBoxLayout,
    QPushButton, QListWidget, QListWidgetItem, QMessageBox, QLabel,
    QSpinBox, QColorDialog, QFileDialog, QHBoxLayout, QUndoStack, QSlider, QTabWidget,
    QScrollArea, QFrame, QSizePolicy
)
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtCore import Qt

from ui.new_dialog import NewDocumentDialog
from ui.export_dialog import ExportDialog
from ui.color_picker import ColorPickerDialog
from ui.themes import apply_theme, PALETTES
from core import autosave, sounds
from core.settings import get_settings
from core.commands import OpacityCommand
from ui.canvas import (TOOL_BRUSH, TOOL_PENCIL, TOOL_ERASER, TOOL_LASSO,
                       TOOL_TEXT, TOOL_BUCKET, TOOL_GRAB, TOOL_IMAGE,
                       TOOL_BLUR, TOOL_PICKER, TOOL_SHAPE, TOOL_3D_BRUSH)
from ui.canvas import Canvas
from core.project import Project
from core.layer import PixelLayer
from core.commands import (
    AddLayerCommand, RemoveLayerCommand,
    MoveLayerCommand, ToggleVisibilityCommand,
)
from core.export import export_project


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project: Project | None = None
        self.undo_stack = QUndoStack(self)
        self._brush_color = QColor("black")
        self._brush_radius = 12
        self._fill_tolerance = 24
        self._updating_list = False
        self._opacity_before = 1.0
        self._dirty = False
        self._collab_session = None
        self._open_project_dirs = set()
        self.setWindowTitle("Python Photoshop")
        self.resize(1200, 800)
        self.setMinimumSize(800, 600)

        self.settings = get_settings()
        self._theme_name = self.settings.get('theme')
        self._brush_radius = int(self.settings.get('default_brush_radius', 12))
        self._fill_tolerance = int(self.settings.get('default_fill_tolerance', 24))
        self._build_canvas()
        self._build_menus()
        self._build_tools_dock()
        self._build_layers_dock()
        self._build_info_dock()
        self._setup_autosave()
        sounds.get_engine().set_enabled(self.settings.get('sounds_enabled'))
        sounds.set_master_volume(self.settings.get('sounds_volume'))
        self._set_theme(self.settings.get('theme'))
        self.statusBar().showMessage("Ready")

    # ---------------- menus ----------------
    def _build_menus(self):
        mb = self.menuBar()
        file_menu = mb.addMenu("File")

        new_act = QAction("New…", self); new_act.setShortcut("Ctrl+N")
        new_act.triggered.connect(self.new_document); file_menu.addAction(new_act)

        open_act = QAction("Open Project…", self); open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self.open_project_prompt); file_menu.addAction(open_act)

        open_img_act = QAction("Open Image…", self); open_img_act.setShortcut("Ctrl+Shift+O")
        open_img_act.triggered.connect(self.open_image_directly); file_menu.addAction(open_img_act)

        file_menu.addSeparator()

        close_tab_act = QAction("Close Tab", self); close_tab_act.setShortcut("Ctrl+W")
        close_tab_act.triggered.connect(lambda: self._close_tab(self.tabs.currentIndex()))
        file_menu.addAction(close_tab_act)

        file_menu.addSeparator()

        save_act = QAction("Save Project", self); save_act.setShortcut("Ctrl+S")
        save_act.triggered.connect(self.save_project); file_menu.addAction(save_act)

        export_act = QAction("Export As…", self); export_act.setShortcut("Ctrl+E")
        export_act.triggered.connect(self.export_project_prompt); file_menu.addAction(export_act)

        save_copy_act = QAction("Save a Copy…", self); save_copy_act.setShortcut("Ctrl+Shift+S")
        save_copy_act.triggered.connect(self.save_a_copy)
        file_menu.addAction(save_copy_act)

        save_as_act = QAction("Save Project As…", self)
        save_as_act.triggered.connect(self.save_project_as)
        file_menu.addAction(save_as_act)

        file_menu.addSeparator()
        exit_act = QAction("Exit", self); exit_act.setShortcut("Ctrl+Q")
        exit_act.triggered.connect(self.close); file_menu.addAction(exit_act)

        edit_menu = mb.addMenu("Edit")
        undo_act = self.undo_stack.createUndoAction(self, "Undo")
        undo_act.setShortcut("Ctrl+Z")
        undo_act.triggered.connect(lambda: sounds.play("undo"))
        redo_act = self.undo_stack.createRedoAction(self, "Redo")
        redo_act.setShortcut("Ctrl+Shift+Z")
        redo_act.triggered.connect(lambda: sounds.play("redo"))
        edit_menu.addAction(undo_act); edit_menu.addAction(redo_act)

        edit_menu.addSeparator()

        cut_act = QAction("Cut", self); cut_act.setShortcut("Ctrl+X")
        cut_act.triggered.connect(lambda: self._edit_clipboard("cut"))
        edit_menu.addAction(cut_act)

        copy_act = QAction("Copy", self); copy_act.setShortcut("Ctrl+C")
        copy_act.triggered.connect(lambda: self._edit_clipboard("copy"))
        edit_menu.addAction(copy_act)

        paste_act = QAction("Paste as New Layer", self); paste_act.setShortcut("Ctrl+V")
        paste_act.triggered.connect(lambda: self._edit_clipboard("paste"))
        edit_menu.addAction(paste_act)

        edit_menu.addSeparator()

        # --- transform submenu (operates on active pixel layer) ---
        transform = edit_menu.addMenu("Transform")
        for label, fn in (
            ("Flip Horizontal", lambda: self._transform_layer("flip_h")),
            ("Flip Vertical",   lambda: self._transform_layer("flip_v")),
            ("Rotate 90° CW",   lambda: self._transform_layer("rot90")),
            ("Rotate 90° CCW",  lambda: self._transform_layer("rot270")),
            ("Rotate 180°",     lambda: self._transform_layer("rot180")),
        ):
            a = QAction(label, self)
            a.triggered.connect(fn)
            transform.addAction(a)

        edit_menu.addSeparator()

        crop_act = QAction("Crop to Selection…", self); crop_act.setShortcut("Ctrl+Shift+X")
        crop_act.triggered.connect(self._edit_crop)
        edit_menu.addAction(crop_act)

        resize_act = QAction("Resize Image…", self); resize_act.setShortcut("Ctrl+Alt+I")
        resize_act.triggered.connect(self._edit_resize)
        edit_menu.addAction(resize_act)

        edit_menu.addSeparator()

        sound_menu = edit_menu.addMenu("Sound")
        from core.sounds import get_engine
        self._sound_toggle = QAction("Enable Sounds", self, checkable=True, checked=True)
        self._sound_toggle.triggered.connect(
            lambda v: get_engine().set_enabled(v))
        sound_menu.addAction(self._sound_toggle)

        prefs_act = QAction("Preferences…", self)
        prefs_act.setShortcut("Ctrl+,")
        prefs_act.triggered.connect(self.open_preferences)
        edit_menu.addAction(prefs_act)

        # ---------- Theme menu ----------
        theme_menu = mb.addMenu("Theme")
        self._theme_name = "Dark"
        for name in PALETTES.keys():
            act = QAction(name, self, checkable=True)
            act.setChecked(name == self._theme_name)
            act.triggered.connect(lambda _=False, n=name: self._set_theme(n))
            theme_menu.addAction(act)
            if not hasattr(self, "_theme_actions"):
                self._theme_actions = []
            self._theme_actions.append(act)

        # ---------- Extensions menu ----------
        ext_menu = mb.addMenu("Extensions")

        collab_act = QAction("Collab Paint…", self)
        collab_act.setShortcut("Ctrl+Shift+P")
        collab_act.triggered.connect(self.open_collab_lobby)
        ext_menu.addAction(collab_act)

        self._collab_publish_act = QAction("Publish Collab Session", self)
        self._collab_publish_act.setEnabled(False)
        self._collab_publish_act.triggered.connect(self._collab_publish)
        ext_menu.addAction(self._collab_publish_act)

        layer_menu = mb.addMenu("Layer")
        add_act = QAction("New Layer", self); add_act.setShortcut("Ctrl+Shift+N")
        add_act.triggered.connect(self.add_layer); layer_menu.addAction(add_act)

        del_act = QAction("Delete Layer", self); del_act.setShortcut("Ctrl+Shift+Del")
        del_act.triggered.connect(self.delete_layer); layer_menu.addAction(del_act)

        shape_props_act = QAction("Shape Properties…", self)
        shape_props_act.setShortcut("Ctrl+Alt+P")
        shape_props_act.triggered.connect(self.open_shape_properties)
        layer_menu.addAction(shape_props_act)

        layer_menu.addSeparator()

        raster_act = QAction("Rasterize Layer", self)
        raster_act.setShortcut("Ctrl+Shift+R")
        raster_act.triggered.connect(self.rasterize_active_layer)
        layer_menu.addAction(raster_act)

        layer_menu.addSeparator()

        up_act = QAction("Move Layer Up", self); up_act.setShortcut("Ctrl+]")
        up_act.triggered.connect(self.move_layer_up); layer_menu.addAction(up_act)

        down_act = QAction("Move Layer Down", self); down_act.setShortcut("Ctrl+[")
        down_act.triggered.connect(self.move_layer_down); layer_menu.addAction(down_act)

        top_act = QAction("Bring to Front", self); top_act.setShortcut("Ctrl+Shift+]")
        top_act.triggered.connect(self.move_layer_top); layer_menu.addAction(top_act)

        bottom_act = QAction("Send to Back", self); bottom_act.setShortcut("Ctrl+Shift+[")
        bottom_act.triggered.connect(self.move_layer_bottom); layer_menu.addAction(bottom_act)

        layer_menu.addSeparator()

        toggle_act = QAction("Toggle Visibility", self); toggle_act.setShortcut("Ctrl+,")
        toggle_act.triggered.connect(self.toggle_active_visibility); layer_menu.addAction(toggle_act)

        # --- tool shortcuts ---
        for key, tool in (("V", TOOL_GRAB), ("B", TOOL_BRUSH),
                          ("P", TOOL_PENCIL), ("E", TOOL_ERASER),
                          ("L", TOOL_LASSO), ("G", TOOL_BUCKET),
                          ("T", TOOL_TEXT), ("I", TOOL_IMAGE), ("R", TOOL_BLUR), ("K", TOOL_PICKER), ("U", TOOL_SHAPE), ("J", TOOL_3D_BRUSH)):
            act = QAction(self)
            act.setShortcut(key)
            act.triggered.connect(lambda _=False, t=tool: self._set_tool(t))
            self.addAction(act)

        # ---------- View menu ----------
        view_menu = mb.addMenu("View")

        zoom_in = QAction("Zoom In", self); zoom_in.setShortcut("Ctrl++")
        zoom_in.triggered.connect(lambda: self._zoom(1.25)); view_menu.addAction(zoom_in)

        zoom_out = QAction("Zoom Out", self); zoom_out.setShortcut("Ctrl+-")
        zoom_out.triggered.connect(lambda: self._zoom(1/1.25)); view_menu.addAction(zoom_out)

        fit_act = QAction("Fit on Screen", self); fit_act.setShortcut("Ctrl+0")
        fit_act.triggered.connect(self._fit_view); view_menu.addAction(fit_act)

        reset_act = QAction("Actual Pixels (100%)", self); reset_act.setShortcut("Ctrl+1")
        reset_act.triggered.connect(self._reset_view); view_menu.addAction(reset_act)

        view_menu.addSeparator()

        bg_dark = QAction("Dark Canvas Background", self)
        bg_dark.triggered.connect(lambda: self._set_canvas_bg("#2b2b2b"))
        view_menu.addAction(bg_dark)

        bg_mid = QAction("Neutral Canvas Background", self)
        bg_mid.triggered.connect(lambda: self._set_canvas_bg("#555"))
        view_menu.addAction(bg_mid)

        bg_light = QAction("Light Canvas Background", self)
        bg_light.triggered.connect(lambda: self._set_canvas_bg("#d0d0d0"))
        view_menu.addAction(bg_light)

        # ---------- Image menu ----------
        image_menu = mb.addMenu("Image")

        hue_act = QAction("Hue Shift Active Shape…", self)
        hue_act.triggered.connect(self._img_hue_shift_active)
        image_menu.addAction(hue_act)

        gray_act = QAction("Grayscale Active Shape", self)
        gray_act.triggered.connect(lambda: self._img_simple_effect("grayscale"))
        image_menu.addAction(gray_act)

        sepia_act = QAction("Sepia Active Shape", self)
        sepia_act.triggered.connect(lambda: self._img_simple_effect("sepia"))
        image_menu.addAction(sepia_act)

        blur_act = QAction("Blur Whole Active Shape…", self)
        blur_act.triggered.connect(self._img_blur_active)
        image_menu.addAction(blur_act)

        image_menu.addSeparator()

        rembg_act = QAction("Remove Background (active pixel layer)", self)
        rembg_act.triggered.connect(self._img_remove_bg)
        image_menu.addAction(rembg_act)

        # ---------- Filter menu ----------
        filter_menu = mb.addMenu("Filter")

        f_blur = QAction("Gaussian Blur Active Pixel Layer…", self)
        f_blur.triggered.connect(self._filter_blur_layer)
        filter_menu.addAction(f_blur)

        f_sharp = QAction("Sharpen Active Pixel Layer…", self)
        f_sharp.triggered.connect(self._filter_sharpen_layer)
        filter_menu.addAction(f_sharp)

        f_bc = QAction("Brightness / Contrast Active Pixel Layer…", self)
        f_bc.triggered.connect(self._filter_bc_layer)
        filter_menu.addAction(f_bc)

        filter_menu.addSeparator()

        f_gray = QAction("Grayscale Active Pixel Layer", self)
        f_gray.triggered.connect(lambda: self._filter_simple_layer("grayscale"))
        filter_menu.addAction(f_gray)

        f_sepia = QAction("Sepia Active Pixel Layer", self)
        f_sepia.triggered.connect(lambda: self._filter_simple_layer("sepia"))
        filter_menu.addAction(f_sepia)

        # ---------- Window menu ----------
        window_menu = mb.addMenu("Window")

        for title, dock_attr in (
            ("Tools",   "_tools_dock"),
            ("Layers",  "_layers_dock"),
            ("Info",    "_info_dock"),
        ):
            act = QAction(title, self, checkable=True, checked=True)
            act.triggered.connect(
                lambda checked, name=title, attr=dock_attr:
                self._toggle_dock(name, attr, checked))
            window_menu.addAction(act)

        window_menu.addSeparator()
        reset_layout = QAction("Reset Layout", self)
        reset_layout.triggered.connect(self._reset_layout)
        window_menu.addAction(reset_layout)

        # ---------- Help menu ----------
        help_menu = mb.addMenu("Help")

        shortcuts_act = QAction("Keyboard Shortcuts", self)
        shortcuts_act.triggered.connect(self._show_shortcuts)
        help_menu.addAction(shortcuts_act)

        howto_act = QAction("How To…", self)
        howto_act.triggered.connect(self._show_howto)
        help_menu.addAction(howto_act)

        help_menu.addSeparator()

        about_act = QAction("About Python Photoshop", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

    # ---------------- docks ----------------
    def _build_tools_dock(self):
        dock = QDockWidget("Tools", self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        w = QWidget(); v = QVBoxLayout(w)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        scroll.setWidget(w)

        self.tool_buttons = {}
        for label, tool in (
            ("Grab",   TOOL_GRAB),
            ("Brush",  TOOL_BRUSH),
            ("Pencil", TOOL_PENCIL),
            ("Eraser", TOOL_ERASER),
            ("Lasso",  TOOL_LASSO),
            ("Bucket", TOOL_BUCKET),
            ("Text",   TOOL_TEXT),
            ("Image",  TOOL_IMAGE),
            ("Blur",   TOOL_BLUR),
            ("Picker", TOOL_PICKER),
            ("Shape",  TOOL_SHAPE),
            ("3D Brush", TOOL_3D_BRUSH),
        ):
            b = QPushButton(label)
            b.setFixedSize(90, 34); b.setCheckable(True)
            b.clicked.connect(lambda _=False, t=tool: self._set_tool(t))
            self.tool_buttons[tool] = b
            v.addWidget(b)
        self.tool_buttons[TOOL_BRUSH].setChecked(True)

        from PyQt5.QtWidgets import QComboBox
        kind_row = QHBoxLayout()
        kind_row.addWidget(QLabel("Shape"))
        self.shape_kind_combo = QComboBox()
        self.shape_kind_combo.addItems(["rect", "ellipse"])
        self.shape_kind_combo.currentTextChanged.connect(self._on_shape_kind_changed)
        kind_row.addWidget(self.shape_kind_combo)
        v.addLayout(kind_row)

        self.color_btn = QPushButton("Color")
        self.color_btn.setFixedSize(90, 34); self.color_btn.clicked.connect(self.pick_color)
        v.addWidget(self.color_btn)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Size"))
        self.size_spin = QSpinBox(); self.size_spin.setRange(1, 200)
        self.size_spin.setValue(self._brush_radius)
        self.size_spin.valueChanged.connect(self._on_size_changed)
        size_row.addWidget(self.size_spin)
        v.addLayout(size_row)

        tol_row = QHBoxLayout()
        tol_row.addWidget(QLabel("Tolerance"))
        self.tolerance_spin = QSpinBox(); self.tolerance_spin.setRange(0, 255)
        self.tolerance_spin.setValue(self._fill_tolerance)
        self.tolerance_spin.valueChanged.connect(self._on_tolerance_changed)
        tol_row.addWidget(self.tolerance_spin)
        v.addLayout(tol_row)

        # ---------- glow controls (for text/shape selections) ----------
        glow_row = QHBoxLayout()
        glow_row.addWidget(QLabel("Glow"))
        self.glow_radius_spin = QSpinBox()
        self.glow_radius_spin.setRange(0, 60)
        self.glow_radius_spin.setValue(0)
        self.glow_radius_spin.setSuffix(" px")
        glow_row.addWidget(self.glow_radius_spin)
        v.addLayout(glow_row)

        glow_color_row = QHBoxLayout()
        glow_color_row.addWidget(QLabel("Glow Color"))
        self.glow_color_btn = QPushButton("#ffff00")
        self.glow_color_btn.setFixedHeight(24)
        self.glow_color_btn.clicked.connect(self._pick_glow_color)
        self._glow_color = QColor("#ffff00")
        self._update_glow_btn()
        glow_color_row.addWidget(self.glow_color_btn)
        v.addLayout(glow_color_row)

        apply_glow_btn = QPushButton("Apply Glow to Selection")
        apply_glow_btn.clicked.connect(self._apply_glow_to_active_shape)
        v.addWidget(apply_glow_btn)

        v.addStretch()

        dock.setWidget(scroll)
        dock.setMinimumWidth(150)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self._tools_dock = dock
        self._update_color_btn()

    def _build_layers_dock(self):
        dock = QDockWidget("Layers", self)
        w = QWidget(); v = QVBoxLayout(w)

        self.layer_list = QListWidget()
        self.layer_list.setDragDropMode(QListWidget.InternalMove)
        self.layer_list.setDefaultDropAction(Qt.MoveAction)
        self.layer_list.itemClicked.connect(self._on_layer_clicked)
        self.layer_list.itemChanged.connect(self._on_layer_item_changed)
        self.layer_list.model().rowsMoved.connect(self._on_rows_moved)
        v.addWidget(self.layer_list)

        op_row = QHBoxLayout()
        op_row.addWidget(QLabel("Opacity"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(self._on_opacity_slider_changed)
        self.opacity_slider.sliderPressed.connect(self._begin_opacity_change)
        self.opacity_slider.sliderReleased.connect(self._commit_opacity_change)
        op_row.addWidget(self.opacity_slider, 1)
        self.opacity_label = QLabel("100%")
        op_row.addWidget(self.opacity_label)
        v.addLayout(op_row)

        row = QHBoxLayout()
        for label, cb in (("+", self.add_layer), ("−", self.delete_layer),
                          ("↑", self.move_layer_up), ("↓", self.move_layer_down)):
            b = QPushButton(label); b.setFixedSize(32, 28); b.clicked.connect(cb)
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)

        dock.setWidget(w)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self._layers_dock = dock

    def _build_info_dock(self):
        self.info_label = QLabel("No document"); self.info_label.setWordWrap(True)
        dock = QDockWidget("Document Info", self)
        dock.setWidget(self.info_label)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self._info_dock = dock

    def _build_canvas(self):
        from PyQt5.QtWidgets import QSizePolicy
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMinimumSize(400, 300)
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

    def _new_canvas(self) -> Canvas:
        c = Canvas(self.undo_stack)
        c.on_layers_changed = self._sync_layers_ui
        c.on_zoom_changed = self._update_zoom_status
        c.on_color_picked = self._on_color_picked
        return c

    @property
    def canvas(self) -> Canvas | None:
        return self.tabs.currentWidget() if hasattr(self, "tabs") else None

    def _add_tab(self, title: str, canvas: Canvas) -> None:
        if hasattr(self, '_theme_name'):
            from ui.themes import PALETTES
            canvas.set_theme_bg(PALETTES[self._theme_name]['canvas'])
        idx = self.tabs.addTab(canvas, title)
        self.tabs.setCurrentIndex(idx)

    def _close_tab(self, index: int) -> None:
        if self.tabs.count() <= 1:
            return
        w = self.tabs.widget(index)
        self.tabs.removeTab(index)
        w.deleteLater()

    def _on_tab_changed(self, _idx: int) -> None:
        c = self.canvas
        if c is None:
            return
        self._update_zoom_status()
        sounds.play('tab')
        self.project = c.project
        self.undo_stack = c.undo_stack
        try:
            # disconnect the previous tab's hook if any
            if getattr(self, "_dirty_hook", None) is not None:
                try:
                    self._undo_signal_stack.indexChanged.disconnect(self._dirty_hook)
                except Exception:
                    pass
            self._undo_signal_stack = self.undo_stack
            self._dirty_hook = lambda _i: self._safe_mark_dirty()
            self.undo_stack.indexChanged.connect(self._dirty_hook)
        except Exception:
            pass
        # rebind menus' undo stack (they were created once, so just re-use)
        self._refresh_after_tab_switch()
        if self.project:
            self.setWindowTitle(f"Python Photoshop — {self.project.name}")
            self._sync_layers_ui()
            self.info_label.setText(
                f"{self.project.name}\n{self.project.width} × {self.project.height} px\n"
                f"BG: {self.project.background}\nFile:\n{self.project.image_path}"
            )
        else:
            self.setWindowTitle("Python Photoshop")
            self.layer_list.clear()
            self.info_label.setText("No document")

    # ---------- View actions ----------
    def _zoom(self, factor: float):
        c = self.canvas
        if c is None:
            return
        c.scale(factor, factor)
        self._update_zoom_status()

    def _fit_view(self):
        from PyQt5.QtCore import Qt as _Qt
        c = self.canvas
        if c is None or c.project is None:
            return
        c.fitInView(c.scene.sceneRect(), _Qt.KeepAspectRatio)
        self._update_zoom_status()

    def _reset_view(self):
        c = self.canvas
        if c is None:
            return
        c.resetTransform()
        self._update_zoom_status()

    def _set_canvas_bg(self, color: str):
        c = self.canvas
        if c is None:
            return
        from PyQt5.QtGui import QColor as _QColor
        c.setBackgroundBrush(_QColor(color))

    def _update_zoom_status(self):
        c = self.canvas
        if c is None:
            return
        pct = int(c.transform().m11() * 100)
        self.statusBar().showMessage(f"Zoom: {pct}%")

    # ---------- color picked from canvas ----------
    def _on_color_picked(self, c):
        self._brush_color = c
        self._update_color_btn()
        if self.canvas is not None:
            self.canvas.brush_color = c
        self.statusBar().showMessage(f"Picked: {c.name()} a={c.alpha()}")

    # ---------- image menu: effects on active shape layer's images ----------
    def _active_shape_images(self):
        """Return the (layer, shape) pairs on the active layer, if any."""
        from core.image_shape import ImageShape
        idx = self._active_model_index()
        if idx is None:
            return []
        layer = self.project.layers[idx]
        if not hasattr(layer, "shapes"):
            return []
        return [(layer, s) for s in layer.shapes if isinstance(s, ImageShape)]

    def _apply_effect_to_active_shape(self, mutate_effects, label):
        from core.commands import EditShapeCommand
        pairs = self._active_shape_images()
        if not pairs:
            self.statusBar().showMessage("No image shape on the active layer.")
            return
        layer, shape = pairs[-1]
        from core.image_shape import ImageShape
        new_effects = dict(shape.effects)
        mutate_effects(new_effects)
        new_shape = ImageShape(shape.x, shape.y, shape.source_path,
                               scale=shape.scale, rotation=shape.rotation,
                               effects=new_effects,
                               pixel_override=shape.pixel_override)
        self.undo_stack.push(EditShapeCommand(layer, shape, new_shape,
                                              on_change=self.canvas.refresh,
                                              text=label))
        self.canvas.refresh()

    def _img_hue_shift_active(self):
        from PyQt5.QtWidgets import QInputDialog
        v, ok = QInputDialog.getInt(self, "Hue Shift", "Degrees (-180..180):",
                                    0, -180, 180)
        if not ok:
            return
        self._apply_effect_to_active_shape(lambda fx: fx.__setitem__("hue", v),
                                           "Hue Shift")

    def _img_simple_effect(self, kind: str):
        if kind == "grayscale":
            self._apply_effect_to_active_shape(lambda fx: fx.__setitem__("grayscale", True),
                                               "Grayscale")
        elif kind == "sepia":
            self._apply_effect_to_active_shape(lambda fx: fx.__setitem__("sepia", True),
                                               "Sepia")

    def _img_blur_active(self):
        from PyQt5.QtWidgets import QInputDialog
        v, ok = QInputDialog.getInt(self, "Blur", "Radius (px):", 3, 0, 40)
        if not ok:
            return
        self._apply_effect_to_active_shape(lambda fx: fx.__setitem__("blur", v),
                                           "Blur")

    def _img_remove_bg(self):
        """Operate on the active PixelLayer's QImage."""
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QColor
        from core import image_ops
        from core.commands import FillCommand

        idx = self._active_model_index()
        if idx is None:
            return
        layer = self.project.layers[idx]
        if not hasattr(layer, "image"):
            self.statusBar().showMessage("Active layer is not a pixel layer.")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            before = layer.clone_image()
            new_img = image_ops.remove_background(before)
            after = new_img
            layer.image = after
            # push as undo command — reuse FillCommand as a raw image swapper
            from PyQt5.QtWidgets import QUndoCommand
            project = self.project
            on_change = self.canvas.refresh
            class _RemoveBG(QUndoCommand):
                def __init__(self):
                    super().__init__("Remove Background")
                def redo(self):
                    layer.image = after; on_change()
                def undo(self):
                    layer.image = before; on_change()
            self.undo_stack.push(_RemoveBG())
            self.canvas.refresh()
            if image_ops.has_rembg():
                self.statusBar().showMessage("Background removed (rembg).")
            else:
                self.statusBar().showMessage("Background removed (ImageMagick fallback).")
        except Exception as e:
            self.statusBar().showMessage(f"Remove BG failed: {e}")
        finally:
            QApplication.restoreOverrideCursor()

    # ---------- help dialogs ----------
    def _show_shortcuts(self):
        from PyQt5.QtWidgets import QMessageBox
        text = (
            "<b>Tools</b><br>"
            "V — Grab &nbsp;&nbsp; B — Brush &nbsp;&nbsp; P — Pencil<br>"
            "E — Eraser &nbsp;&nbsp; L — Lasso &nbsp;&nbsp; G — Bucket<br>"
            "T — Text &nbsp;&nbsp; I — Image &nbsp;&nbsp; R — Blur<br>"
            "K — Picker &nbsp;&nbsp; Alt+Click — pick color anywhere<br><br>"
            "<b>View</b><br>"
            "Ctrl+ + / − zoom &nbsp;&nbsp; Ctrl+0 fit &nbsp;&nbsp; Ctrl+1 100%<br>"
            "Space-drag pan &nbsp;&nbsp; wheel zoom<br><br>"
            "<b>Layers</b><br>"
            "Ctrl+Shift+N new &nbsp;&nbsp; Ctrl+Shift+Del delete &nbsp;&nbsp; "
            "Ctrl+Shift+R rasterize<br>"
            "Ctrl+] / [ move &nbsp;&nbsp; Ctrl+Shift+] / [ front / back<br><br>"
            "<b>Edit</b><br>"
            "Ctrl+Z undo &nbsp;&nbsp; Ctrl+Shift+Z redo<br><br>"
            "<b>File</b><br>"
            "Ctrl+N new doc &nbsp;&nbsp; Ctrl+O open project &nbsp;&nbsp; "
            "Ctrl+Shift+O open image &nbsp;&nbsp; Ctrl+E export &nbsp;&nbsp; Ctrl+W close tab"
        )
        QMessageBox.information(self, "Keyboard Shortcuts", text)

    def _show_howto(self):
        from PyQt5.QtWidgets import QMessageBox
        text = (
            "<b>Paint on an image</b><br>"
            "File → Open Image, pick a file. Paint with B/E/R tools.<br><br>"
            "<b>Recolor an image</b><br>"
            "Double-click an image on the canvas → slide Hue in the dialog.<br>"
            "Or select its layer and use Image → Hue Shift Active Shape.<br><br>"
            "<b>Remove background</b><br>"
            "Select the pixel layer → Image → Remove Background.<br>"
            "Uses rembg if installed, else ImageMagick fallback.<br><br>"
            "<b>Erase half a text or image</b><br>"
            "Select Eraser and click on the shape layer → it rasterizes, "
            "then you can erase pixels.<br><br>"
            "<b>Import with edits</b><br>"
            "Image tool (I) → click canvas → pick file → click preview to enter "
            "the sub-editor → paint → Done → still adjust effects → Import."
        )
        QMessageBox.information(self, "How To", text)

    def _show_about(self):
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.about(
            self, "About Python Photoshop",
            "<h3>Python Photoshop</h3>"
            "<p>A PyQt5 + ImageMagick painting app.</p>"
            "<p>Brush, Pencil, Eraser, Blur, Bucket, Lasso, Text, Image, Grab, "
            "Eyedropper. Layers with undo. Live effect previews. SVG support.</p>"
        )

    # ---------- glow ----------
    def _pick_glow_color(self):
        from ui.color_picker import ColorPickerDialog
        dlg = ColorPickerDialog(self._glow_color, self)
        if dlg.exec_() == dlg.Accepted:
            self._glow_color = dlg.color()
            self._update_glow_btn()

    def _update_glow_btn(self):
        c = self._glow_color
        self.glow_color_btn.setStyleSheet(
            f"background-color:{c.name()};"
            f"color:{'white' if c.lightness() < 128 else 'black'};"
        )
        self.glow_color_btn.setText(c.name())

    def _apply_glow_to_active_shape(self):
        """Apply glow to shapes. If the active layer has no shapes, walk
        up to the nearest shape layer so users don't have to guess."""
        from core.commands import EditShapeCommand
        from core.shape_layer import TextShape
        from core.image_shape import ImageShape

        idx = self._active_model_index()
        if idx is None:
            self.statusBar().showMessage("No active layer."); return

        layer = self.project.layers[idx]
        if not hasattr(layer, "shapes"):
            # walk upward (toward the top of the stack)
            for j in range(idx + 1, len(self.project.layers)):
                if hasattr(self.project.layers[j], "shapes"):
                    layer = self.project.layers[j]
                    break
            else:
                self.statusBar().showMessage(
                    "No shape layer found — place text or an image first.")
                return
        if not layer.shapes:
            self.statusBar().showMessage("That shape layer is empty.")
            return

        r = self.glow_radius_spin.value()
        color = QColor(self._glow_color)
        count = 0
        for shape in list(layer.shapes):
            if isinstance(shape, TextShape):
                new = TextShape(shape.x, shape.y, shape.text, shape.font,
                                shape.color, r, color)
            elif isinstance(shape, ImageShape):
                new = ImageShape(shape.x, shape.y, shape.source_path,
                                 scale=shape.scale, rotation=shape.rotation,
                                 effects=shape.effects,
                                 pixel_override=shape.pixel_override,
                                 glow_radius=r, glow_color=color)
            else:
                continue
            self.undo_stack.push(EditShapeCommand(layer, shape, new,
                                                  on_change=self.canvas.refresh,
                                                  text="Glow"))
            count += 1
        self.canvas.refresh()
        self.statusBar().showMessage(f"Glow applied to {count} shape(s).")

    # ---------- dock toggling ----------
    def _toggle_dock(self, name: str, attr: str, checked: bool):
        dock = getattr(self, attr, None)
        if dock is not None:
            dock.setVisible(checked)

    def _reset_layout(self):
        for attr in ("_tools_dock", "_layers_dock", "_info_dock"):
            d = getattr(self, attr, None)
            if d is not None:
                d.setVisible(True)

    # ---------- filter menu helpers ----------
    def _active_pixel_layer(self):
        idx = self._active_model_index()
        if idx is None:
            return None
        layer = self.project.layers[idx]
        if hasattr(layer, "image"):
            return layer
        return None

    def _replace_layer_image(self, layer, new_img, label):
        from PyQt5.QtWidgets import QUndoCommand
        before = layer.clone_image()
        after = new_img
        on_change = self.canvas.refresh

        class _Apply(QUndoCommand):
            def __init__(self):
                super().__init__(label)
            def redo(self):
                layer.image = after; on_change()
            def undo(self):
                layer.image = before; on_change()

        layer.image = after
        self.undo_stack.push(_Apply())
        self.canvas.refresh()
        try:
            from extensions.collab.protocol import image_to_b64
            idx = self.project.layers.index(layer)
            self._collab_emit({"type": "stroke",
                               "layer": idx,
                               "data": image_to_b64(after)})
        except Exception:
            pass

    def _filter_blur_layer(self):
        from PyQt5.QtWidgets import QInputDialog, QApplication
        from core import image_ops
        layer = self._active_pixel_layer()
        if layer is None:
            self.statusBar().showMessage("No active pixel layer."); return
        v, ok = QInputDialog.getInt(self, "Gaussian Blur", "Radius (px):", 4, 0, 50)
        if not ok: return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._replace_layer_image(layer, image_ops.blur(layer.image, v), "Blur")
        finally:
            QApplication.restoreOverrideCursor()

    def _filter_sharpen_layer(self):
        from PyQt5.QtWidgets import QInputDialog, QApplication
        from core import image_ops
        layer = self._active_pixel_layer()
        if layer is None:
            self.statusBar().showMessage("No active pixel layer."); return
        v, ok = QInputDialog.getInt(self, "Sharpen", "Radius (px):", 2, 0, 20)
        if not ok: return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._replace_layer_image(layer, image_ops.sharpen(layer.image, v), "Sharpen")
        finally:
            QApplication.restoreOverrideCursor()

    def _filter_bc_layer(self):
        from PyQt5.QtWidgets import QInputDialog, QApplication
        from core import image_ops
        layer = self._active_pixel_layer()
        if layer is None:
            self.statusBar().showMessage("No active pixel layer."); return
        b, ok = QInputDialog.getInt(self, "Brightness", "Value (-100..100):", 0, -100, 100)
        if not ok: return
        c, ok = QInputDialog.getInt(self, "Contrast", "Value (-100..100):", 0, -100, 100)
        if not ok: return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._replace_layer_image(
                layer, image_ops.adjust_brightness_contrast(layer.image, b, c),
                "Brightness/Contrast")
        finally:
            QApplication.restoreOverrideCursor()

    def _filter_simple_layer(self, kind):
        from PyQt5.QtWidgets import QApplication
        from core import image_ops
        layer = self._active_pixel_layer()
        if layer is None:
            self.statusBar().showMessage("No active pixel layer."); return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if kind == "grayscale":
                self._replace_layer_image(layer, image_ops.grayscale(layer.image), "Grayscale")
            elif kind == "sepia":
                self._replace_layer_image(layer, image_ops.sepia(layer.image), "Sepia")
        finally:
            QApplication.restoreOverrideCursor()

    # ---------- theme ----------
    def _set_theme(self, name: str):
        self._theme_name = name
        for act in getattr(self, "_theme_actions", []):
            act.setChecked(act.text() == name)
        apply_theme(name)
        self.apply_canvas_theme(name)

    def apply_canvas_theme(self, name: str):
        from ui.themes import PALETTES
        color = PALETTES.get(name, PALETTES["Dark"])["canvas"]
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if hasattr(w, "set_theme_bg"):
                w.set_theme_bg(color)

    # ---------- edit clipboard ----------
    def _edit_clipboard(self, op: str):
        """Cut/Copy/Paste whole pixel layer via system clipboard image."""
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QImage
        from core.layer import PixelLayer
        from core.commands import AddLayerCommand

        idx = self._active_model_index()
        if idx is None:
            return
        layer = self.project.layers[idx]

        if op in ("copy", "cut"):
            if not hasattr(layer, "image"):
                self.statusBar().showMessage("Only pixel layers can be copied.")
                return
            QApplication.clipboard().setImage(layer.image)
            if op == "cut":
                from PyQt5.QtGui import QColor
                from PyQt5.QtCore import Qt
                layer.image.fill(Qt.transparent)
                self.canvas.refresh()
            self.statusBar().showMessage(f"{op.capitalize()} layer.")
            return

        if op == "paste":
            img = QApplication.clipboard().image()
            if img.isNull():
                self.statusBar().showMessage("Clipboard is empty.")
                return
            new = PixelLayer(
                f"Pasted {len(self.project.layers) + 1}",
                self.project.width, self.project.height, fill="transparent")
            # center-place (scale down if bigger than canvas)
            if img.width() > self.project.width or img.height() > self.project.height:
                img = img.scaled(self.project.width, self.project.height,
                                 Qt.KeepAspectRatio, Qt.SmoothTransformation)
            from PyQt5.QtGui import QPainter, QImage
            canvas_img = QImage(self.project.width, self.project.height,
                                QImage.Format_ARGB32)
            canvas_img.fill(Qt.transparent)
            p = QPainter(canvas_img)
            x = (self.project.width - img.width()) // 2
            y = (self.project.height - img.height()) // 2
            p.drawImage(x, y, img)
            p.end()
            new.image = canvas_img
            self.undo_stack.push(AddLayerCommand(self.project, new, self._sync_layers_ui))
            self.statusBar().showMessage("Pasted as new layer.")

    # ---------- transforms ----------
    def _transform_layer(self, kind: str):
        idx = self._active_model_index()
        if idx is None:
            return
        layer = self.project.layers[idx]
        if not hasattr(layer, "image"):
            self.statusBar().showMessage("Transform works on pixel layers."); return
        from PyQt5.QtGui import QTransform
        t = QTransform()
        if kind == "flip_h":  t.scale(-1, 1)
        if kind == "flip_v":  t.scale(1, -1)
        if kind == "rot90":   t.rotate(90)
        if kind == "rot180":  t.rotate(180)
        if kind == "rot270":  t.rotate(270)
        new_img = layer.image.transformed(t, Qt.SmoothTransformation)
        # for 90° rotations, keep original dimensions (center-crop)
        if kind in ("rot90", "rot270"):
            from PyQt5.QtGui import QImage, QPainter
            fixed = QImage(layer.image.width(), layer.image.height(),
                           QImage.Format_ARGB32)
            fixed.fill(Qt.transparent)
            p = QPainter(fixed)
            p.drawImage((fixed.width() - new_img.width()) // 2,
                        (fixed.height() - new_img.height()) // 2, new_img)
            p.end()
            new_img = fixed
        self._replace_layer_image(layer, new_img, kind.replace("_", " ").title())

    # ---------- crop / resize (operate on whole project) ----------
    def _edit_crop(self):
        from PyQt5.QtWidgets import QInputDialog, QApplication
        from PyQt5.QtGui import QImage
        if not self.project:
            return
        x, ok = QInputDialog.getInt(self, "Crop", "X:", 0, 0, self.project.width - 1)
        if not ok: return
        y, ok = QInputDialog.getInt(self, "Crop", "Y:", 0, 0, self.project.height - 1)
        if not ok: return
        w, ok = QInputDialog.getInt(self, "Crop", "Width:", self.project.width,
                                    1, self.project.width - x)
        if not ok: return
        h, ok = QInputDialog.getInt(self, "Crop", "Height:", self.project.height,
                                    1, self.project.height - y)
        if not ok: return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for layer in self.project.layers:
                if hasattr(layer, "image"):
                    cropped = layer.image.copy(x, y, w, h)
                    layer.image = QImage(cropped).convertToFormat(QImage.Format_ARGB32)
                elif hasattr(layer, "shapes"):
                    for s in layer.shapes:
                        s.x -= x; s.y -= y
            self.project.width = w
            self.project.height = h
            self.canvas._refresh()
            self.canvas.fitInView(self.canvas.scene.sceneRect(), Qt.KeepAspectRatio)
        finally:
            QApplication.restoreOverrideCursor()

    def _edit_resize(self):
        from PyQt5.QtWidgets import QInputDialog, QApplication
        if not self.project:
            return
        w, ok = QInputDialog.getInt(self, "Resize", "New width:", self.project.width, 1, 10000)
        if not ok: return
        h, ok = QInputDialog.getInt(self, "Resize", "New height:", self.project.height, 1, 10000)
        if not ok: return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for layer in self.project.layers:
                if hasattr(layer, "image"):
                    layer.image = layer.image.scaled(w, h, Qt.IgnoreAspectRatio,
                                                     Qt.SmoothTransformation)
                elif hasattr(layer, "shapes"):
                    sx = w / self.project.width
                    sy = h / self.project.height
                    for s in layer.shapes:
                        s.x *= sx; s.y *= sy
                        if hasattr(s, "scale"):
                            s.scale *= max(sx, sy)
            self.project.width = w
            self.project.height = h
            self.canvas._refresh()
            self.canvas.fitInView(self.canvas.scene.sceneRect(), Qt.KeepAspectRatio)
        finally:
            QApplication.restoreOverrideCursor()

    def open_preferences(self):
        from ui.preferences_dialog import PreferencesDialog
        dlg = PreferencesDialog(self)
        if dlg.exec_() == dlg.Accepted:
            dlg.apply_to(self)
            self.statusBar().showMessage("Preferences saved.")

    def open_shape_properties(self):
        from ui.shape_properties_dialog import ShapePropertiesDialog
        from core.commands import EditShapeCommand

        # what shape? — the selected one on the canvas, or the first shape on the active layer
        shape = getattr(self.canvas, "selected_shape", None) if self.canvas else None
        layer = getattr(self.canvas, "selected_layer", None) if self.canvas else None

        if shape is None:
            idx = self._active_model_index()
            if idx is None:
                self.statusBar().showMessage("Select a shape or shape layer first.")
                return
            layer = self.project.layers[idx]
            if not hasattr(layer, "shapes") or not layer.shapes:
                self.statusBar().showMessage("No shape selected. Click a shape with Grab.")
                return
            shape = layer.shapes[-1]

        dlg = ShapePropertiesDialog(shape, self)
        if dlg.exec_() != dlg.Accepted:
            return

        new_shape = dlg.apply_to_shape()
        if new_shape is None:
            return
        self.undo_stack.push(EditShapeCommand(
            layer, shape, new_shape,
            on_change=self.canvas.refresh,
            text="Edit Shape Properties"))
        self.canvas.selected_shape = new_shape
        self.canvas.selected_layer = layer
        self.canvas.refresh()

    # ---------- autosave / crash recovery ----------
    def _setup_autosave(self):
        from PyQt5.QtCore import QTimer
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(
            int(self.settings.get('autosave_interval_seconds', 30)) * 1000)
        self._autosave_timer.timeout.connect(self._do_autosave)
        self._autosave_timer.start()

    def _mark_dirty(self):
        self._dirty = True
        self._update_title_dirty()

    def _safe_mark_dirty(self):
        # undo stack can outlive the window during teardown; ignore late signals
        try:
            self._mark_dirty()
        except RuntimeError:
            pass

    def _mark_clean(self):
        self._dirty = False
        self._update_title_dirty()

    def _update_title_dirty(self):
        base = "Python Photoshop"
        if self.project:
            base = f"{base} — {self.project.name}"
        if self._dirty:
            base = "● " + base
        self.setWindowTitle(base)

    def _do_autosave(self):
        """Called by the timer — writes autosave snapshots for dirty projects."""
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if w.project is None:
                continue
            try:
                autosave.autosave_project(w.project)
            except Exception:
                pass

    def _register_open_project(self, project):
        try:
            autosave.mark_open(project.project_dir)
            self._open_project_dirs.add(project.project_dir)
        except Exception:
            pass

    def _release_open_project(self, project):
        try:
            autosave.mark_clean(project.project_dir)
            self._open_project_dirs.discard(project.project_dir)
        except Exception:
            pass

    def _scan_crash_recovery(self):
        """On startup, look for projects whose lock file survived."""
        from PyQt5.QtWidgets import QMessageBox
        from core.project import PROJECTS_DIR
        if not PROJECTS_DIR.is_dir():
            return
        found = []
        for d in PROJECTS_DIR.iterdir():
            if d.is_dir() and autosave.has_crash(d):
                found.append(d)
        if not found:
            return
        names = ", ".join(d.name for d in found)
        if QMessageBox.question(
            self, "Recover Session",
            f"Python Photoshop did not shut down cleanly.\n\n"
            f"Recover unsaved work for: {names}?",
        ) == QMessageBox.Yes:
            for d in found:
                self._recover_project(d)

    def _recover_project(self, project_dir):
        from core.layer import PixelLayer
        from core.shape_layer import ShapeLayer
        from core.project import Project
        from pathlib import Path

        loaded = autosave.load_autosave(project_dir)
        if loaded is None:
            return
        meta, folder = loaded

        project = Project(name=meta["name"], width=meta["width"],
                          height=meta["height"], background=meta["background"])
        layers = []
        for l in meta["layers"]:
            if l.get("kind") == "shape":
                layers.append(ShapeLayer.from_dict(l, folder, project.width, project.height))
            else:
                layer = PixelLayer(l["name"], project.width, project.height, fill="transparent")
                px = folder / l["pixels"]
                if px.is_file():
                    from PyQt5.QtGui import QImage
                    img = QImage(str(px))
                    if not img.isNull():
                        layer.image = img.convertToFormat(QImage.Format_ARGB32)
                layer.visible = l.get("visible", True)
                layer.opacity = l.get("opacity", 1.0)
                layers.append(layer)
        project.layers = layers

        canvas = self._new_canvas()
        self._add_tab(f"[recovered] {project.name}", canvas)
        self._bind_project_to_canvas(project, canvas)
        self._register_open_project(project)
        self._mark_dirty()

    # ---------- close handling ----------
    def closeEvent(self, event):
        # stop the autosave timer so it can't fire mid-teardown
        try:
            if getattr(self, '_autosave_timer', None) is not None:
                self._autosave_timer.stop()
        except Exception:
            pass
        # disconnect the undo-stack hook
        try:
            if getattr(self, '_undo_signal_stack', None) is not None and getattr(self, '_dirty_hook', None) is not None:
                self._undo_signal_stack.indexChanged.disconnect(self._dirty_hook)
        except Exception:
            pass
        # close collab session cleanly
        try:
            if getattr(self, '_collab_session', None) is not None:
                self._collab_session.close()
                self._collab_session = None
        except Exception:
            pass
        from PyQt5.QtWidgets import QMessageBox
        if self._dirty and self.project is not None:
            r = QMessageBox.question(
                self, "Unsaved changes",
                f"'{self.project.name}' has unsaved changes.\n\nSave before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            )
            if r == QMessageBox.Cancel:
                event.ignore(); return
            if r == QMessageBox.Save:
                try:
                    self.project.save_meta()
                except Exception as e:
                    QMessageBox.critical(self, "Save failed", str(e))
                    event.ignore(); return
        # release all locks
        for d in list(self._open_project_dirs):
            try: autosave.mark_clean(d)
            except Exception: pass
        super().closeEvent(event)

    # ---------- collab ----------
    def _collab_emit(self, msg: dict):
        s = getattr(self, "_collab_session", None)
        if s is None:
            return
        try:
            if s.role == "host":
                s.broadcast_structure(msg)
            else:
                s._send_to_host(msg)
        except Exception as e:
            print(f"[collab] emit failed: {e}")

    def open_collab_lobby(self):
        from extensions.collab.lobby import CollabLobby
        from extensions.collab.session import CollabSession
        from core.layer import PixelLayer, merge_layers
        from PyQt5.QtGui import QImage

        dlg = CollabLobby(self)
        if dlg.exec_() != dlg.Accepted or dlg.mode is None:
            return

        # ---------- HOST: requires a project, flattens it ----------
        if dlg.mode == "host":
            if self.project is None or self.canvas is None:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.information(self, "Collab",
                    "Host: open or create a document first.")
                return
            flat = merge_layers(self.project.layers,
                                self.project.width, self.project.height,
                                background=self.project.background)
            px = PixelLayer("Collab", self.project.width, self.project.height,
                            fill="transparent")
            px.image = flat.convertToFormat(QImage.Format_ARGB32)
            self.project.layers = [px]
            self._sync_layers_ui()
            self.canvas.set_active_layer(px)
            session_w, session_h = self.project.width, self.project.height
            session_name = self.project.name

        # ---------- CLIENT: no project required — host will provide one ----------
        else:
            # If the client already has a project, we still replace it on connect.
            # If not, use a placeholder project so the canvas / status bar has
            # something to bind to. Sizes get overwritten by `welcome`.
            from core.project import Project
            existing = self.project
            if existing is None:
                placeholder = Project(name="Collab Session",
                                      width=900, height=600,
                                      background="white")
                px = PixelLayer("Collab", 900, 600, fill="white")
                placeholder.layers = [px]
                try:
                    placeholder.project_dir.mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass
                canvas = self._new_canvas()
                self._add_tab(placeholder.name, canvas)
                self._bind_project_to_canvas(placeholder, canvas)
                self.undo_stack = canvas.undo_stack
            session_w, session_h = self.project.width, self.project.height
            session_name = self.project.name

        # ---------- build session ----------
        session = CollabSession(
            role=dlg.mode,
            my_name=dlg.name,
            project_name=session_name,
            width=session_w,
            height=session_h,
            parent=self,
        )
        # host: provide current flattened canvas whenever a new peer connects
        if dlg.mode == "host":
            def _provider():
                if self.project is None:
                    return None
                return merge_layers(self.project.layers,
                                    self.project.width, self.project.height,
                                    background=self.project.background)
            session.host_image_provider = _provider
        self._collab_session = session

        # mount chat dock
        from extensions.collab.chat_dock import ChatDock
        if getattr(self, "_chat_dock", None) is not None:
            try:
                self.removeDockWidget(self._chat_dock)
                self._chat_dock.deleteLater()
            except Exception:
                pass
        self._chat_dock = ChatDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self._chat_dock)

        def _on_chat_submit(text: str):
            session.send_chat(text)
            # echo locally with own name
            self._chat_dock.append_message(dlg.name, text, "#4ea8ff")
        self._chat_dock.messageSubmitted.connect(_on_chat_submit)

        def _on_chat_received(name: str, text: str):
            color = "#ffaa44" if name != dlg.name else "#4ea8ff"
            self._chat_dock.append_message(name, text, color)
        session.chatReceived.connect(_on_chat_received)
        session.chatBubble.connect(self.canvas.show_chat_from)

        # status messages
        session.statusMessage.connect(
            lambda m: self.statusBar().showMessage(m))

        # when the host sends welcome, resize the client's project to match
        def _on_connected(who):
            self.statusBar().showMessage(f"Collab: {who} connected")
            if dlg.mode == "client" and self.project is not None:
                w, h = session.width, session.height
                if (self.project.width, self.project.height) != (w, h):
                    px = PixelLayer("Collab", w, h, fill="white")
                    self.project.width, self.project.height = w, h
                    self.project.layers = [px]
                    self.canvas.set_project(self.project)
                    self._sync_layers_ui()
        session.connected.connect(_on_connected)

        session.disconnected.connect(
            lambda why: self.statusBar().showMessage(f"Collab: {why}"))

        # remote stroke — for clients without any layer, create one on the fly
        def _apply_remote(payload):
            """payload is (QImage, layer_index) from session.remoteImage."""
            if payload is None:
                return
            if isinstance(payload, tuple):
                img, layer_idx = payload
            else:
                img, layer_idx = payload, 0

            if img is None:
                return
            if self.project is None:
                return

            # create / resize project to match incoming image if needed
            from core.layer import PixelLayer
            if (self.project.width != img.width() or
                    self.project.height != img.height()):
                self.project.width = img.width()
                self.project.height = img.height()
                if not self.project.layers:
                    self.project.layers = [PixelLayer("Collab", img.width(),
                                                      img.height(),
                                                      fill="transparent")]
                    self.canvas.set_project(self.project)
                else:
                    # resize existing layers
                    for lay in self.project.layers:
                        if hasattr(lay, "image"):
                            lay.image = lay.image.scaled(
                                img.width(), img.height(),
                                __import__("PyQt5.QtCore", fromlist=["Qt"]).Qt.IgnoreAspectRatio,
                                __import__("PyQt5.QtCore", fromlist=["Qt"]).Qt.SmoothTransformation)
                    self.canvas.set_project(self.project)

            if not self.project.layers:
                self.project.layers = [PixelLayer("Collab", img.width(),
                                                  img.height(),
                                                  fill="transparent")]
                self.canvas.set_project(self.project)

            self.canvas.apply_remote_stroke(img, layer_index=layer_idx)

        session.remoteImage.connect(_apply_remote)

        def _apply_structure(msg):
            from extensions.collab.protocol import layer_from_wire
            t = msg.get("type")
            try:
                if t == "layer_add":
                    new_layer = layer_from_wire(msg["layer"])
                    idx = int(msg["index"])
                    if 0 <= idx <= len(self.project.layers):
                        self.project.layers.insert(idx, new_layer)
                    else:
                        self.project.layers.append(new_layer)
                    self._sync_layers_ui()

                elif t == "layer_del":
                    idx = int(msg["index"])
                    if 0 <= idx < len(self.project.layers):
                        self.project.layers.pop(idx)
                        self._sync_layers_ui()

                elif t == "layer_rasterize":
                    idx = int(msg["index"])
                    if 0 <= idx < len(self.project.layers):
                        self.project.layers[idx] = layer_from_wire(msg["layer"])
                        self._sync_layers_ui()

                elif t == "layer_reorder":
                    old, new = int(msg["old"]), int(msg["new"])
                    if 0 <= old < len(self.project.layers):
                        item = self.project.layers.pop(old)
                        self.project.layers.insert(max(0, min(new, len(self.project.layers))), item)
                        self._sync_layers_ui()

                elif t == "layer_visible":
                    idx = int(msg["index"])
                    if 0 <= idx < len(self.project.layers):
                        self.project.layers[idx].visible = bool(msg["visible"])
                        self._sync_layers_ui()

                elif t == "layer_opacity":
                    idx = int(msg["index"])
                    if 0 <= idx < len(self.project.layers):
                        self.project.layers[idx].opacity = float(msg["opacity"])
                        self._sync_layers_ui()

                elif t in ("shape_add", "shape_edit"):
                    from core.image_shape import ImageShape
                    from core.shape_layer import TextShape
                    from core.shape_objects import RectShape, EllipseShape
                    from PyQt5.QtGui import QFont, QColor
                    li = int(msg["layer"])
                    if not (0 <= li < len(self.project.layers)):
                        return
                    layer = self.project.layers[li]
                    if not hasattr(layer, "shapes"):
                        return
                    sd = msg["shape"]
                    st = sd.get("type")
                    if st == "image":
                        shape = ImageShape.from_wire(sd)
                    elif st == "text":
                        f = QFont(sd["font"]["family"], sd["font"]["size"])
                        gc = QColor(sd["glow_color"]) if sd.get("glow_color") else None
                        shape = TextShape(sd["x"], sd["y"], sd["text"], f,
                                          QColor(sd["color"]),
                                          sd.get("glow_radius", 0), gc)
                    elif st == "rect":
                        shape = RectShape.from_dict(sd, None)
                    elif st == "ellipse":
                        shape = EllipseShape.from_dict(sd, None)
                    else:
                        print(f"[collab] unknown shape type: {st}")
                        return
                    if t == "shape_add":
                        layer.shapes.append(shape)
                    else:
                        si = int(msg["index"])
                        if 0 <= si < len(layer.shapes):
                            layer.shapes[si] = shape
                        else:
                            layer.shapes.append(shape)
                    self.canvas.refresh()

                elif t == "shape_delete":
                    li = int(msg["layer"])
                    si = int(msg["index"])
                    if 0 <= li < len(self.project.layers):
                        layer = self.project.layers[li]
                        if hasattr(layer, "shapes") and 0 <= si < len(layer.shapes):
                            layer.shapes.pop(si)
                            self.canvas.refresh()
            except Exception as e:
                import traceback
                print(f"[collab] apply_structure({t}) error: {e}")
                traceback.print_exc()

        session.structureMessage.connect(_apply_structure)
        session.remoteCursor.connect(self.canvas.apply_remote_cursor)
        session.published.connect(self._collab_published)

        # outbound structure changes from canvas
        def _shape_added(li, si, sd):
            self._collab_emit({"type": "shape_add", "layer": li, "shape": sd})
        def _shape_edited(li, si, sd):
            self._collab_emit({"type": "shape_edit",
                              "layer": li, "index": si, "shape": sd})
        def _layer_added(li, layer_dict):
            self._collab_emit({"type": "layer_add",
                               "index": li,
                               "layer": layer_dict})
        self.canvas.on_layer_added = _layer_added
        self.canvas.on_shape_added = _shape_added
        self.canvas.on_shape_edited = _shape_edited

        # outbound: local strokes/cursors → server
        # throttled outbound — max 12.5 strokes/sec, prevents lockup on loop
        import time as _time
        _last_send = {"t": 0.0}
        def _send_throttled(img):
            now = _time.time()
            if now - _last_send["t"] < 0.08:
                return
            _last_send["t"] = now
            try:
                session.send_stroke(img)
            except Exception:
                pass
        self.canvas.collabStrokeReady.connect(_send_throttled)
        # throttle cursor updates — 30 Hz is plenty and keeps CPU low
        import time as _ctime
        _last_cursor = {"t": 0.0}
        def _send_cursor_throttled(x, y):
            now = _ctime.time()
            if now - _last_cursor["t"] < 0.033:
                return
            _last_cursor["t"] = now
            try:
                session.send_cursor(x, y)
            except Exception:
                pass
        self.canvas.collabCursorMoved.connect(_send_cursor_throttled)

        # start
        if dlg.mode == "host":
            session.start_host()
            self._collab_publish_act.setEnabled(True)
        else:
            ip = getattr(dlg, 'selected_ip', None)
            session.start_client(host_ip=ip)
            self._collab_publish_act.setEnabled(False)

        self.statusBar().showMessage(f"Collab as {dlg.mode} — '{dlg.name}'")

    def _collab_publish(self):
        if self._collab_session is None:
            return
        from core.layer import merge_layers
        flat = merge_layers(self.project.layers,
                            self.project.width, self.project.height,
                            background=self.project.background)
        self._collab_session.publish(flat, self.project.name)
        # also save locally
        try:
            self.project.save_meta()
        except Exception:
            pass
        self.statusBar().showMessage("Published to all clients.")

    def _collab_published(self, name, img):
        """Host published — show confirmation. Yes = save + continue;
        No = save + disconnect."""
        from PyQt5.QtWidgets import QMessageBox
        from pathlib import Path

        # save to disk first so data isn't lost if they disconnect
        saved_path = None
        try:
            target = Path.home() / "Downloads" / f"{name}_collab.png"
            target.parent.mkdir(exist_ok=True)
            if img.save(str(target), "PNG"):
                saved_path = str(target)
        except Exception:
            pass

        msg = QMessageBox(self)
        msg.setWindowTitle("Host Published")
        msg.setIcon(QMessageBox.Question)
        msg.setText(f"Host has published <b>{name}</b>.")
        if saved_path:
            msg.setInformativeText(
                f"Saved to:\n{saved_path}\n\nDo you want to continue "
                f"in this session, or disconnect?")
        else:
            msg.setInformativeText(
                "Save failed, but you can still continue. "
                "Do you want to continue or disconnect?")
        continue_btn = msg.addButton("Continue", QMessageBox.YesRole)
        disconnect_btn = msg.addButton("Disconnect", QMessageBox.NoRole)
        msg.setDefaultButton(continue_btn)
        msg.exec_()

        if msg.clickedButton() is disconnect_btn:
            self._disconnect_collab()
            self.statusBar().showMessage("Disconnected after publish.")
        else:
            self.statusBar().showMessage(
                f"Publish accepted — saved to {saved_path or 'memory'}")

    def _disconnect_collab(self):
        """Close the collab session cleanly, keep the tab's content."""
        s = getattr(self, "_collab_session", None)
        if s is not None:
            try:
                s.close()
            except Exception:
                pass
            self._collab_session = None
        try:
            self._collab_publish_act.setEnabled(False)
        except Exception:
            pass
        try:
            if getattr(self, '_chat_dock', None) is not None:
                self.removeDockWidget(self._chat_dock)
                self._chat_dock.deleteLater()
                self._chat_dock = None
        except Exception:
            pass

    def _refresh_after_tab_switch(self):
        pass

    # ---------------- tools ----------------
    def pick_color(self):
        dlg = ColorPickerDialog(self._brush_color, self)
        if dlg.exec_() == dlg.Accepted:
            self._brush_color = dlg.color()
            if self.canvas is not None:
                self.canvas.brush_color = self._brush_color
            self._update_color_btn()

    def _set_tool(self, tool: str):
        if self.canvas is None:
            return
        self.canvas.set_tool(tool)
        for t, b in self.tool_buttons.items():
            b.setChecked(t == tool)
        self.statusBar().showMessage(f"Tool: {tool}")

    def _update_color_btn(self):
        c = self._brush_color
        self.color_btn.setStyleSheet(
            f"background-color:{c.name()}; color:{'white' if c.lightness() < 128 else 'black'};"
        )
        self.color_btn.setText(f"{c.name()} a={c.alpha()}")

    # ---------------- layer list <-> model sync ----------------
    def _ui_index_to_model(self, ui_row: int) -> int:
        """UI shows top layer first; model is bottom-first."""
        return len(self.project.layers) - 1 - ui_row

    def _model_index_to_ui(self, model_idx: int) -> int:
        return len(self.project.layers) - 1 - model_idx

    def _on_size_changed(self, v):
        self._brush_radius = v
        if self.canvas is not None:
            self.canvas.brush_radius = v

    def _on_shape_kind_changed(self, kind: str):
        if self.canvas is not None:
            self.canvas.shape_kind = kind

    def _on_tolerance_changed(self, v):
        self._fill_tolerance = v
        if self.canvas is not None:
            self.canvas.fill_tolerance = v

    def _on_layer_clicked(self, item):
        if not self.project:
            return
        idx = self._ui_index_to_model(self.layer_list.row(item))
        if not (0 <= idx < len(self.project.layers)):
            return
        self.canvas.set_active_layer(self.project.layers[idx])
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(int(self.project.layers[idx].opacity * 100))
        self.opacity_label.setText(f"{int(self.project.layers[idx].opacity * 100)}%")
        self.opacity_slider.blockSignals(False)
        self.statusBar().showMessage(f"Active layer: {self.project.layers[idx].name}")

    def _on_layer_item_changed(self, item):
        """Fires when a checkbox (visibility) is toggled."""
        if not self.project:
            return
        ui_row = self.layer_list.row(item)
        idx = self._ui_index_to_model(ui_row)
        if not (0 <= idx < len(self.project.layers)):
            return
        layer = self.project.layers[idx]
        want_visible = bool(item.checkState())
        if want_visible != layer.visible:
            self._collab_emit({"type": "layer_visible", "index": idx, "visible": want_visible})
            self.undo_stack.push(ToggleVisibilityCommand(self.project, layer, self._sync_layers_ui))

    def _on_rows_moved(self, *_args):
        """Fires on drag-and-drop reorder. Rebuild model, push a single command."""
        if not self.project or self._updating_list:
            return
        # Reconstruct model order from current UI order (bottom-first)
        new_model = [self.project.layers[self._ui_index_to_model(i)]
                     for i in range(len(self.project.layers) - 1, -1, -1)]
        if new_model == self.project.layers:
            return
        # Snapshot for undo by reusing MoveLayerCommand per displaced item —
        # simplest correct approach: replace whole list in one command.
        from PyQt5.QtWidgets import QUndoCommand
        project = self.project
        on_change = self._sync_layers_ui
        old_model = list(self.project.layers)

        class _ReorderCommand(QUndoCommand):
            def __init__(self):
                super().__init__("Reorder Layers")
            def redo(self):
                project.layers[:] = new_model
                on_change()
            def undo(self):
                project.layers[:] = old_model
                on_change()

        self.undo_stack.push(_ReorderCommand())

    def _begin_opacity_change(self):
        idx = self._active_model_index()
        if idx is None:
            return
        self._opacity_before = self.project.layers[idx].opacity

    def _on_opacity_slider_changed(self, val: int):
        if not self.project:
            return
        idx = self._active_model_index()
        if idx is None:
            return
        layer = self.project.layers[idx]
        new_op = val / 100.0
        layer.opacity = new_op
        self.opacity_label.setText(f"{val}%")
        self.canvas.refresh()

    def _commit_opacity_change(self):
        if not self.project:
            return
        idx = self._active_model_index()
        if idx is None:
            return
        layer = self.project.layers[idx]
        before = getattr(self, "_opacity_before", layer.opacity)
        after = layer.opacity
        if abs(before - after) < 1e-6:
            return
        # restore before so the command's redo applies after cleanly
        layer.opacity = before
        self._collab_emit({"type": "layer_opacity", "index": idx,
                           "opacity": after})
        self.undo_stack.push(OpacityCommand(self.project, layer, before, after,
                                            self._sync_layers_ui))

    def _sync_layers_ui(self):
        # tab switched → pull the active canvas's project
        if self.canvas is not None and self.canvas.project is not None:
            self.project = self.canvas.project
        if not self.project:
            return
        self._updating_list = True
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        for layer in reversed(self.project.layers):
            item = QListWidgetItem(layer.name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            item.setCheckState(Qt.Checked if layer.visible else Qt.Unchecked)
            self.layer_list.addItem(item)
        self.layer_list.blockSignals(False)
        self._updating_list = False
        self.canvas.refresh()
        if self.project.layers:
            self.canvas.set_active_layer(self.project.layers[-1])
            self.layer_list.setCurrentRow(0)
            self.opacity_slider.blockSignals(True)
            self.opacity_slider.setValue(int(self.project.layers[-1].opacity * 100))
            self.opacity_label.setText(f"{int(self.project.layers[-1].opacity * 100)}%")
            self.opacity_slider.blockSignals(False)

    # ---------------- layer ops ----------------
    def add_layer(self):
        if not self.project:
            return
        layer = PixelLayer(
            name=f"Layer {len(self.project.layers) + 1}",
            width=self.project.width, height=self.project.height, fill="transparent",
        )
        sounds.play('layer_new')
        self.undo_stack.push(AddLayerCommand(self.project, layer, self._sync_layers_ui))
        from extensions.collab.protocol import layer_to_wire
        try:
            idx = self.project.layers.index(layer)
        except ValueError:
            idx = len(self.project.layers) - 1
        self._collab_emit({"type": "layer_add",
                           "index": idx,
                           "layer": layer_to_wire(layer)})
        self._collab_emit({"type": "layer_add",
                           "index": len(self.project.layers) - 1,
                           "layer": __import__("extensions.collab.protocol", fromlist=["layer_to_wire"]).layer_to_wire(layer)})

    def delete_layer(self):
        if not self.project or len(self.project.layers) <= 1:
            return
        idx = len(self.project.layers) - 1
        sounds.play('layer_del')
        self._collab_emit({"type": "layer_del", "index": idx})
        self.undo_stack.push(RemoveLayerCommand(self.project, idx, self._sync_layers_ui))

    def rasterize_active_layer(self):
        """Convert active ShapeLayer into a PixelLayer so it can be erased/painted."""
        from core.layer import PixelLayer
        from core.shape_layer import ShapeLayer

        idx = self._active_model_index()
        if idx is None:
            return
        layer = self.project.layers[idx]
        if not isinstance(layer, ShapeLayer):
            self.statusBar().showMessage("Layer is already raster.")
            return

        rendered = layer.render_to_image()
        new_layer = PixelLayer(layer.name + " (px)", self.project.width,
                               self.project.height, fill="transparent")
        new_layer.image = rendered
        self.project.layers[idx] = new_layer
        self.canvas.set_active_layer(new_layer)
        self._sync_layers_ui()
        from extensions.collab.protocol import layer_to_wire
        self._collab_emit({"type": "layer_rasterize",
                           "index": idx,
                           "layer": layer_to_wire(new_layer)})
        self.statusBar().showMessage(f"Rasterized: {layer.name}")

    def _active_model_index(self) -> int | None:
        if not self.project:
            return None
        row = self.layer_list.currentRow()
        if row < 0:
            return None
        return self._ui_index_to_model(row)

    def move_layer_up(self):
        """UI 'up' = toward top of stack = model index +1."""
        idx = self._active_model_index()
        if idx is None or idx >= len(self.project.layers) - 1:
            return
        self._collab_emit({"type": "layer_reorder",
                           "old": idx,
                           "new": idx + 1 if idx + 1 < len(self.project.layers) else idx})
        self.undo_stack.push(MoveLayerCommand(self.project, idx, idx + 1, self._sync_layers_ui))

    def move_layer_down(self):
        idx = self._active_model_index()
        if idx is None or idx <= 0:
            return
        self._collab_emit({"type": "layer_reorder",
                           "old": idx,
                           "new": idx - 1 if idx - 1 >= 0 else idx})
        self.undo_stack.push(MoveLayerCommand(self.project, idx, idx - 1, self._sync_layers_ui))

    def move_layer_top(self):
        idx = self._active_model_index()
        if idx is None or idx >= len(self.project.layers) - 1:
            return
        self.undo_stack.push(MoveLayerCommand(self.project, idx,
                                              len(self.project.layers) - 1,
                                              self._sync_layers_ui))

    def move_layer_bottom(self):
        idx = self._active_model_index()
        if idx is None or idx <= 0:
            return
        self.undo_stack.push(MoveLayerCommand(self.project, idx, 0, self._sync_layers_ui))

    def toggle_active_visibility(self):
        idx = self._active_model_index()
        if idx is None:
            return
        layer = self.project.layers[idx]
        self.undo_stack.push(ToggleVisibilityCommand(self.project, layer, self._sync_layers_ui))

    # ---------------- documents ----------------
    def new_document(self):
        dlg = NewDocumentDialog(self)
        if dlg.exec_() != dlg.Accepted:
            return
        v = dlg.values()
        project = Project(name=v["name"], width=v["width"],
                          height=v["height"], background=v["background"])
        try:
            folder = project.create_on_disk()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not create document:\n{e}")
            return
        bg = PixelLayer("Background", project.width, project.height, fill=v["background"])
        project.layers = [bg]
        project.save_meta()
        canvas = self._new_canvas()
        self._add_tab(project.name, canvas)
        self._bind_project_to_canvas(project, canvas)
        self.undo_stack = canvas.undo_stack
        self.undo_stack.clear()
        self.statusBar().showMessage(f"Created → {folder}")

    def open_project_prompt(self):
        path = QFileDialog.getExistingDirectory(self, "Open Project Folder", "docs")
        if not path:
            return
        try:
            project = Project.load(Path(path))
        except Exception as e:
            sounds.play('error'); QMessageBox.critical(self, "Error", f"Not a valid project:\n{e}")
            return
        canvas = self._new_canvas()
        self._add_tab(project.name, canvas)
        self._bind_project_to_canvas(project, canvas)
        self.undo_stack = canvas.undo_stack
        self.undo_stack.clear()
        self.statusBar().showMessage(f"Opened → {path}")

    def save_project(self):
        if not self.project:
            return
        try:
            self.project.save_meta()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Save failed:\n{e}")
            return
        self.statusBar().showMessage(f"Saved → {self.project.project_dir}")

    # ---------- save-as / save-copy ----------
    def save_a_copy(self):
        """Write a *snapshot* of the current project to a new folder, without
        switching the active tab to it."""
        if not self.project:
            return
        from PyQt5.QtWidgets import QInputDialog
        from core.project import Project, PROJECTS_DIR

        name, ok = QInputDialog.getText(
            self, "Save a Copy", "Copy name:",
            text=f"{self.project.name}_copy")
        if not ok or not name.strip():
            return

        copy = Project(name=name.strip(),
                       width=self.project.width,
                       height=self.project.height,
                       background=self.project.background)
        copy.layers = [self._clone_layer(l) for l in self.project.layers]
        try:
            copy.create_on_disk()
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            sounds.play("error")
            QMessageBox.critical(self, "Save a Copy failed", str(e))
            return
        sounds.play("export")
        self.statusBar().showMessage(f"Copied to → {copy.project_dir}")

    def save_project_as(self):
        """Save under a new name AND switch the current tab to it."""
        if not self.project:
            return
        from PyQt5.QtWidgets import QInputDialog
        from core.project import Project

        name, ok = QInputDialog.getText(
            self, "Save Project As", "New project name:",
            text=f"{self.project.name}_v2")
        if not ok or not name.strip():
            return

        new_project = Project(name=name.strip(),
                              width=self.project.width,
                              height=self.project.height,
                              background=self.project.background)
        new_project.layers = [self._clone_layer(l) for l in self.project.layers]
        try:
            new_project.create_on_disk()
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            sounds.play("error")
            QMessageBox.critical(self, "Save As failed", str(e))
            return

        # swap the current tab's project
        self.canvas.project = new_project
        self.project = new_project
        self._bind_project_to_canvas(new_project, self.canvas)
        self._mark_clean()
        sounds.play("export")
        self.statusBar().showMessage(f"Saved as → {new_project.project_dir}")

    def _clone_layer(self, layer):
        """Deep-ish copy of a layer for save-a-copy / save-as."""
        from core.layer import PixelLayer
        from core.shape_layer import ShapeLayer
        import copy

        if hasattr(layer, "image"):
            new = PixelLayer(layer.name, layer.image.width(),
                             layer.image.height(), fill="transparent")
            new.image = layer.image.copy()
            new.visible = layer.visible
            new.opacity = layer.opacity
            return new
        if hasattr(layer, "shapes"):
            new = ShapeLayer(layer.name, layer.width, layer.height)
            new.visible = layer.visible
            new.opacity = layer.opacity
            new.shapes = copy.deepcopy(layer.shapes)
            return new
        return layer

    def export_project_prompt(self):
        if not self.project:
            return
        dlg = ExportDialog(self)
        if dlg.exec_() != dlg.Accepted:
            return
        v = dlg.values()
        suggested = str(Path.home() / f"{self.project.slug}.{v['format'].lower()}")
        out, _ = QFileDialog.getSaveFileName(
            self, "Export As", suggested,
            f"{v['format']} Files (*.{v['format'].lower()})"
        )
        if not out:
            return
        try:
            final = export_project(self.project, Path(out), v["format"], v["quality"])
        except Exception as e:
            sounds.play('error'); QMessageBox.critical(self, "Export failed", str(e))
            return
        self.statusBar().showMessage(f"Exported → {final}")

    # ---------------- binding ----------------
    def _bind_project_to_canvas(self, project: Project, canvas: Canvas):
        self.project = project
        self.setWindowTitle(f"Python Photoshop — {project.name}")
        canvas.set_project(project)
        canvas.brush_color = self._brush_color
        canvas.brush_radius = self._brush_radius
        canvas.fill_tolerance = self._fill_tolerance
        canvas.shape_kind = self.shape_kind_combo.currentText()
        canvas.drawing_sound_enabled = self.settings.get('drawing_sound_enabled')
        canvas.drawing_sound_sensitivity = self.settings.get('drawing_sound_sensitivity')
        self._sync_layers_ui()
        self._register_open_project(project)
        self.info_label.setText(
            f"{project.name}\n{project.width} × {project.height} px\n"
            f"BG: {project.background}\nFile:\n{project.image_path}"
        )

    # ---------- open image directly as a new tab ----------
    def open_image_directly(self):
        from pathlib import Path as P
        from core import imagemagick
        from core.layer import PixelLayer

        path, _ = QFileDialog.getOpenFileName(
            self, "Open Image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff *.svg *.heic *.avif);;All Files (*)"
        )
        if not path:
            return

        try:
            png_path = imagemagick.load_any_image(path)
            img = QImage(png_path)
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e)); return
        if img.isNull():
            QMessageBox.warning(self, "Open failed", "Could not read image."); return

        name = P(path).stem or "Untitled"
        project = Project(name=name, width=img.width(), height=img.height(),
                          background="transparent")
        # create folder skeleton so Save works
        project.project_dir.mkdir(parents=True, exist_ok=True)

        layer = PixelLayer("Image", img.width(), img.height(), fill="transparent")
        layer.image = img.convertToFormat(QImage.Format_ARGB32)
        project.layers = [layer]
        project.save_meta()

        canvas = self._new_canvas()
        self._add_tab(project.name, canvas)
        self._bind_project_to_canvas(project, canvas)
        self.undo_stack = canvas.undo_stack
        self.undo_stack.clear()
        self.statusBar().showMessage(f"Opened image → {path}")

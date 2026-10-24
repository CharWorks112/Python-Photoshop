"""Undo/redo commands."""
from PyQt5.QtWidgets import QUndoCommand
from PyQt5.QtGui import QImage


class AddLayerCommand(QUndoCommand):
    def __init__(self, project, layer, on_change):
        super().__init__(f"Add Layer '{layer.name}'")
        self.project = project
        self.layer = layer
        self.on_change = on_change

    def redo(self):
        self.project.layers.append(self.layer)
        self.on_change()

    def undo(self):
        if self.layer in self.project.layers:
            self.project.layers.remove(self.layer)
        self.on_change()


class RemoveLayerCommand(QUndoCommand):
    def __init__(self, project, index, on_change):
        super().__init__("Remove Layer")
        self.project = project
        self.index = index
        self.on_change = on_change
        self.layer = None

    def redo(self):
        self.layer = self.project.layers.pop(self.index)
        self.on_change()

    def undo(self):
        if self.layer is not None:
            self.project.layers.insert(self.index, self.layer)
        self.on_change()


class MoveLayerCommand(QUndoCommand):
    """Move a layer from `src` index to `dst` index."""

    def __init__(self, project, src: int, dst: int, on_change):
        super().__init__("Move Layer")
        self.project = project
        self.src = src
        self.dst = dst
        self.on_change = on_change

    def redo(self):
        layer = self.project.layers.pop(self.src)
        self.project.layers.insert(self.dst, layer)
        self.on_change()

    def undo(self):
        layer = self.project.layers.pop(self.dst)
        self.project.layers.insert(self.src, layer)
        self.on_change()


class ToggleVisibilityCommand(QUndoCommand):
    def __init__(self, project, layer, on_change):
        super().__init__("Toggle Layer Visibility")
        self.project = project
        self.layer = layer
        self.on_change = on_change
        self.prev = layer.visible

    def redo(self):
        self.layer.visible = not self.prev
        self.on_change()

    def undo(self):
        self.layer.visible = self.prev
        self.on_change()


class BrushStrokeCommand(QUndoCommand):
    def __init__(self, layer, before: QImage, after: QImage,
                 on_change, text="Brush Stroke"):
        super().__init__(text)
        self.layer = layer
        self.before = before
        self.after = after
        self.on_change = on_change

    def redo(self):
        self.layer.restore(self.after)
        self.on_change()

    def undo(self):
        self.layer.restore(self.before)
        self.on_change()


class OpacityCommand(QUndoCommand):
    def __init__(self, project, layer, before: float, after: float, on_change):
        super().__init__("Layer Opacity")
        self.project = project
        self.layer = layer
        self.before = before
        self.after = after
        self.on_change = on_change
        self._applied = False

    def redo(self):
        self.layer.opacity = self.after
        self._applied = True
        self.on_change()

    def undo(self):
        self.layer.opacity = self.before
        self.on_change()


class FillCommand(QUndoCommand):
    """Undoable arbitrary pixel mutation (used by bucket fill)."""
    def __init__(self, layer, before, after, on_change, text="Fill"):
        super().__init__(text)
        self.layer = layer
        self.before = before
        self.after = after
        self.on_change = on_change

    def redo(self):
        self.layer.restore(self.after)
        self.on_change()

    def undo(self):
        self.layer.restore(self.before)
        self.on_change()


class AddShapeCommand(QUndoCommand):
    def __init__(self, layer, shape, on_change):
        super().__init__("Add Shape")
        self.layer = layer
        self.shape = shape
        self.on_change = on_change

    def redo(self):
        self.layer.shapes.append(self.shape)
        self.on_change()

    def undo(self):
        if self.shape in self.layer.shapes:
            self.layer.shapes.remove(self.shape)
        self.on_change()


class MoveShapeLayerCommand(QUndoCommand):
    def __init__(self, layer, before_positions, after_positions, on_change):
        super().__init__("Move Shapes")
        self.layer = layer
        self.before = list(before_positions)
        self.after = list(after_positions)
        self.on_change = on_change

    def _apply(self, positions):
        for s, (x, y) in zip(self.layer.shapes, positions):
            s.x = x; s.y = y
        self.on_change()

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)


class EditShapeCommand(QUndoCommand):
    """Replace one shape with another (edit-in-place)."""
    def __init__(self, layer, old_shape, new_shape, on_change, text="Edit Shape"):
        super().__init__(text)
        self.layer = layer
        self.old = old_shape
        self.new = new_shape
        self.on_change = on_change

    def redo(self):
        try:
            idx = self.layer.shapes.index(self.old)
        except ValueError:
            return
        self.layer.shapes[idx] = self.new
        self.on_change()

    def undo(self):
        try:
            idx = self.layer.shapes.index(self.new)
        except ValueError:
            return
        self.layer.shapes[idx] = self.old
        self.on_change()


class ResizeShapeCommand(QUndoCommand):
    """Undo for shape resize."""
    def __init__(self, layer, shape, before_bounds, after_bounds, on_change):
        super().__init__("Resize Shape")
        self.layer = layer
        self.shape = shape
        self.before = tuple(before_bounds)
        self.after = tuple(after_bounds)
        self.on_change = on_change

    def _apply(self, b):
        x, y, w, h = b
        if hasattr(self.shape, "set_bounds"):
            self.shape.set_bounds(x, y, w, h)
        else:
            self.shape.x, self.shape.y = x, y
        self.on_change()

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)


class ResizeShapeCommand(QUndoCommand):
    """Undo for shape resize."""
    def __init__(self, layer, shape, before_bounds, after_bounds, on_change):
        super().__init__("Resize Shape")
        self.layer = layer
        self.shape = shape
        self.before = tuple(before_bounds)
        self.after = tuple(after_bounds)
        self.on_change = on_change

    def _apply(self, b):
        x, y, w, h = b
        if hasattr(self.shape, "set_bounds"):
            self.shape.set_bounds(x, y, w, h)
        else:
            self.shape.x, self.shape.y = x, y
        self.on_change()

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)

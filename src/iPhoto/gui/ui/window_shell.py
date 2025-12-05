"""Standalone widget component for the rounded window shell."""

from __future__ import annotations

from PySide6.QtCore import Property, Qt
from PySide6.QtGui import (
    QColor,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPalette,
)
from PySide6.QtWidgets import QVBoxLayout, QWidget


class RoundedWindowShell(QWidget):
    """Container that draws the translucent rounded chrome for the window."""

    def __init__(self, *, radius: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._corner_radius = max(0, radius)
        self._override_color: QColor | None = None

        # ``WA_TranslucentBackground`` prevents Qt from filling the widget with
        # an opaque rectangle before our custom paint routine executes.  The
        # shell therefore relies on ``paintEvent`` to render the rounded surface
        # while the actual ``QMainWindow`` remains frameless and fully
        # transparent.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

    # ------------------------------------------------------------------
    # Public API used by ``FramelessWindowManager``
    def _get_override_color(self) -> QColor:
        """Return the colour currently used when painting the rounded shell."""

        # ``QPropertyAnimation`` requires a getter when driving a ``Property``
        # on PySide.  Returning the active override keeps the animation in sync
        # with whatever value :meth:`set_override_color` most recently applied.
        return self._override_color or self.palette().color(QPalette.ColorRole.Window)

    def set_corner_radius(self, radius: int) -> None:
        """Update the corner radius and repaint if it changed."""

        clamped = max(0, radius)
        if clamped == self._corner_radius:
            return
        self._corner_radius = clamped
        self.update()

    def corner_radius(self) -> int:
        """Return the current corner radius."""

        return self._corner_radius

    def set_override_color(self, color: QColor | None) -> None:
        """Force the shell to use a specific background colour."""

        if self._override_color == color:
            return
        self._override_color = color
        self.update()

    # Expose a Qt property so controllers can animate the background colour
    # without reaching into private attributes.  The setter already triggers a
    # repaint, so the animation simply drives the property and the shell reacts.
    overrideColor = Property(QColor, _get_override_color, set_override_color)

    # ------------------------------------------------------------------
    # QWidget overrides
    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        """Draw an anti-aliased rounded rectangle matching the window palette."""

        if self.width() <= 0 or self.height() <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setPen(Qt.PenStyle.NoPen)

        effective_color = self._override_color or self.palette().color(
            QPalette.ColorRole.Window
        )
        rect = self.rect()
        radius = min(self._corner_radius, min(rect.width(), rect.height()) / 2)

        path = QPainterPath()
        if radius > 0:
            # Offsetting by half a pixel keeps the curve crisp on high-DPI
            # displays.
            path.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        else:
            path.addRect(rect)

        painter.fillPath(path, effective_color)
        super().paintEvent(event)

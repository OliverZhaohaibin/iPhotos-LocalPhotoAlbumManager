"""Gallery page embedding the grid view inside a simple layout.

This module provides a QML-based gallery page that uses the native QML rendering
pipeline for improved performance and smoother scrolling. The implementation
explicitly configures the surface format to prevent transparency issues when
used with Windows frameless (DWM) windows.
"""

from __future__ import annotations

import logging
import os

from PySide6.QtWidgets import QVBoxLayout, QWidget

# Check for environment variable to force legacy mode
USE_LEGACY_GALLERY = os.environ.get("IPHOTO_LEGACY_GALLERY", "").lower() in ("1", "true", "yes")

logger = logging.getLogger(__name__)


def _create_grid_view():
    """Factory function to create the appropriate grid view implementation.

    Returns the QML-based view by default, falling back to the legacy OpenGL
    widget-based view if QML is unavailable or if the IPHOTO_LEGACY_GALLERY
    environment variable is set.
    """
    if USE_LEGACY_GALLERY:
        logger.info("Using legacy GalleryGridView (IPHOTO_LEGACY_GALLERY is set)")
        from .gallery_grid_view import GalleryGridView
        return GalleryGridView()

    try:
        from .qml_gallery_page import QmlGalleryGridView
        logger.info("Using QML-based GalleryGridView")
        return QmlGalleryGridView()
    except ImportError as e:
        logger.warning(
            "Failed to import QML gallery view, falling back to legacy: %s", e
        )
        from .gallery_grid_view import GalleryGridView
        return GalleryGridView()
    except (RuntimeError, OSError) as e:
        logger.warning(
            "Failed to initialize QML gallery view, falling back to legacy: %s", e
        )
        from .gallery_grid_view import GalleryGridView
        return GalleryGridView()


class GalleryPageWidget(QWidget):
    """Thin wrapper that exposes the gallery grid view as a self-contained page.

    By default, uses a QML-based grid view that leverages the native QML rendering
    pipeline. This provides improved scrolling performance and ensures compatibility
    with Windows frameless windows by explicitly configuring the OpenGL surface
    format to disable the alpha buffer.

    To use the legacy OpenGL widget-based implementation, set the environment
    variable ``IPHOTO_LEGACY_GALLERY=1`` before starting the application.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("galleryPage")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.grid_view = _create_grid_view()
        self.grid_view.setObjectName("galleryGridView")
        layout.addWidget(self.grid_view)


__all__ = ["GalleryPageWidget"]

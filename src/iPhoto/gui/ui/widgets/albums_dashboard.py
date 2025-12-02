"""Dashboard view displaying all user albums."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ....utils.pathutils import ensure_work_dir
from ....cache.index_store import IndexStore
from ....config import WORK_DIR_NAME
from ....models.album import Album
from ..tasks.thumbnail_loader import ThumbnailJob
from .flow_layout import FlowLayout
from ..icon import load_icon

if TYPE_CHECKING:
    from ....library.manager import LibraryManager
    from ....library.tree import AlbumNode


class AlbumCard(QFrame):
    """Card widget representing a single album."""

    def __init__(self, title: str, count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # 1. Container dimensions
        self.setFixedSize(260, 80)
        self.setObjectName("AlbumCard")

        # 2. Layout
        self.layout = QHBoxLayout(self)  # type: ignore[assignment]
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # 3. Left side: Image
        self.image_label = QLabel()
        self.image_label.setFixedSize(80, 80)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setObjectName("ImagePart")
        # Placeholder icon or text until image loads
        self.image_label.setPixmap(
            load_icon("photo.on.rectangle", color="#FFFFFF").pixmap(32, 32)
        )

        # 4. Right side: Metadata
        self.text_container = QWidget()
        self.text_container.setObjectName("TextPart")

        self.text_layout = QVBoxLayout(self.text_container)
        self.text_layout.setContentsMargins(15, 0, 10, 0)
        self.text_layout.setSpacing(4)
        self.text_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Title
        self.title_label = QLabel()
        self.title_label.setStyleSheet(
            "color: #1d1d1f; font-size: 14px; font-weight: 600; background: transparent;"
        )
        self.set_title(title)

        # Count
        self.count_label = QLabel(str(count))
        self.count_label.setStyleSheet(
            "color: #86868b; font-size: 13px; background: transparent;"
        )

        self.text_layout.addWidget(self.title_label)
        self.text_layout.addWidget(self.count_label)

        self.layout.addWidget(self.image_label)
        self.layout.addWidget(self.text_container)

        # 5. Stylesheet
        self.setStyleSheet("""
            /* Parent container: white background and rounded corners */
            #AlbumCard {
                background-color: #FFFFFF;
                border-radius: 12px;
            }

            /* Left image part: rounded on left, straight on right */
            #ImagePart {
                background-color: #B0BEC5;
                color: white;
                font-weight: bold;
                border-top-left-radius: 12px;
                border-bottom-left-radius: 12px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
            }

            /* Right text part: transparent */
            #TextPart {
                background-color: transparent;
            }
        """)

        # 6. Shadow
        self.add_shadow()

    def add_shadow(self) -> None:
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setXOffset(0)
        shadow.setYOffset(4)
        shadow.setColor(QColor(0, 0, 0, 25))
        self.setGraphicsEffect(shadow)

    def set_title(self, title: str) -> None:
        """Set the title with truncation if it exceeds 25 characters."""
        if len(title) > 25:
            truncated = title[:25] + "..."
            self.title_label.setText(truncated)
            self.title_label.setToolTip(title)
        else:
            self.title_label.setText(title)
            self.title_label.setToolTip("")

    def set_cover_image(self, pixmap: QPixmap) -> None:
        """Update the cover image."""
        self.image_label.setPixmap(
            pixmap.scaled(
                self.image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class DashboardLoaderSignals(QObject):
    """Signals for the dashboard data loader."""

    albumReady = Signal(object, int, object, object)  # node, count, cover_path, album_root


class AlbumDataWorker(QRunnable):
    """Background worker to fetch metadata (count, cover path) for an album."""

    def __init__(self, node: AlbumNode, signals: DashboardLoaderSignals) -> None:
        super().__init__()
        self.node = node
        self.signals = signals

    def run(self) -> None:
        # 1. Get count and first asset for cover fallback
        count = 0
        first_rel: str | None = None

        try:
            store = IndexStore(self.node.path)
            # Efficiently count rows and find first rel
            for i, row in enumerate(store.read_all()):
                count += 1
                if i == 0 and isinstance(row, dict):
                    first_rel = str(row.get("rel", ""))
        except Exception:
            pass

        # 2. Determine cover path
        cover_path: Path | None = None
        try:
            album = Album.open(self.node.path)
            cover_rel = album.manifest.get("cover")
            if cover_rel:
                candidate = self.node.path / cover_rel
                if candidate.exists():
                    cover_path = candidate
        except Exception:
            pass

        if cover_path is None and first_rel:
            candidate = self.node.path / first_rel
            if candidate.exists():
                cover_path = candidate

        self.signals.albumReady.emit(self.node, count, cover_path, self.node.path)


class DashboardThumbnailLoader(QObject):
    """Simplified thumbnail loader for dashboard cards."""

    thumbnailReady = Signal(Path, QPixmap)  # album_root, pixmap
    _delivered = Signal(object, object, str)  # key, image, rel

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._delivered.connect(self._handle_result)
        # Map unique keys to album roots
        self._key_to_root: dict[str, Path] = {}

    def request_with_absolute_key(self, album_root: Path, image_path: Path, size: QSize) -> None:
        # To avoid rel collision across albums, we use the absolute path string as the 'rel' identifier
        # passed to ThumbnailJob. This ensures the key emitted back is unique.
        unique_rel = str(image_path)

        # However, we must ensure the cache path is calculated correctly.
        # ThumbnailJob uses the passed cache_path.

        try:
            work_dir = ensure_work_dir(album_root, WORK_DIR_NAME)
            thumbs_dir = work_dir / "thumbs"
            thumbs_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return

        stat = image_path.stat()
        stamp = int(stat.st_mtime * 1_000_000_000)

        # For the cache file name, we want it to be based on the album-relative path so it's stable
        # if the library moves (if we used real rel).
        try:
            real_rel = str(image_path.relative_to(album_root))
        except ValueError:
            real_rel = image_path.name

        digest = hashlib.sha1(real_rel.encode("utf-8")).hexdigest()
        filename = f"{digest}_{stamp}_{size.width()}x{size.height()}.png"
        cache_path = thumbs_dir / filename

        if cache_path.exists():
            pixmap = QPixmap(str(cache_path))
            if not pixmap.isNull():
                self.thumbnailReady.emit(album_root, pixmap)
                return

        # Store mapping
        key_str = self._make_key_str(unique_rel, size, stamp)
        self._key_to_root[key_str] = album_root

        job = ThumbnailJob(
            self,  # type: ignore
            unique_rel,  # Pass absolute path string as rel to ensure uniqueness
            image_path,
            size,
            stamp,
            cache_path,
            is_image=True,
            is_video=False,
            still_image_time=None,
            duration=None,
        )
        self._pool.start(job)

    def _make_key(self, rel: str, size: QSize, stamp: int) -> str:
        # Used by ThumbnailJob to emit signal
        return self._make_key_str(rel, size, stamp)

    def _make_key_str(self, rel: str, size: QSize, stamp: int) -> str:
        return f"{rel}::{size.width()}::{size.height()}::{stamp}"

    def _handle_result(self, key: str, image: Optional[QImage], rel: str) -> None:
        album_root = self._key_to_root.pop(key, None)
        if not album_root or image is None:
            return

        pixmap = QPixmap.fromImage(image)
        if not pixmap.isNull():
            self.thumbnailReady.emit(album_root, pixmap)


class AlbumsDashboard(QWidget):
    """Main view for browsing all user albums."""

    def __init__(self, library: LibraryManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._library = library
        self._cards: dict[Path, AlbumCard] = {}

        # Setup loader
        self._loader_signals = DashboardLoaderSignals()
        self._loader_signals.albumReady.connect(self._on_album_data_ready)

        self._thumb_loader = DashboardThumbnailLoader(self)
        self._thumb_loader.thumbnailReady.connect(self._on_thumbnail_ready)

        self._init_ui()
        self._library.treeUpdated.connect(self.refresh)
        self.refresh()

    def _init_ui(self) -> None:
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(40, 40, 40, 40)
        self.main_layout.setSpacing(20)

        # Header
        self.header_label = QLabel("Albums")
        font = QFont()
        font.setPixelSize(22)
        font.setBold(True)
        self.header_label.setFont(font)
        self.header_label.setStyleSheet("color: #1d1d1f; margin-bottom: 10px;")
        self.main_layout.addWidget(self.header_label)

        # Scroll Area for the grid
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet("background: transparent;")

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")
        self.flow_layout = FlowLayout(self.scroll_content, margin=0, h_spacing=20, v_spacing=20)

        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)

        # Empty state placeholder
        self.empty_label = QLabel(self.tr("No albums available"))
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #86868b; font-size: 16px;")
        self.empty_label.hide()
        self.main_layout.addWidget(self.empty_label)

    def refresh(self) -> None:
        # Clear existing
        while self.flow_layout.count():
            item = self.flow_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._cards.clear()

        albums = self._library.list_albums()

        if not albums:
            self.scroll_area.hide()
            self.empty_label.show()
            return

        self.empty_label.hide()
        self.scroll_area.show()

        pool = QThreadPool.globalInstance()

        for album in albums:
            # Create card with "0" count first
            card = AlbumCard(album.title, 0, self.scroll_content)
            self.flow_layout.addWidget(card)
            self._cards[album.path] = card

            # Fetch data
            worker = AlbumDataWorker(album, self._loader_signals)
            pool.start(worker)

    def _on_album_data_ready(
        self, node: AlbumNode, count: int, cover_path: Path | None, root: Path
    ) -> None:
        card = self._cards.get(root)
        if not card:
            return

        # Update count
        card.count_label.setText(str(count))

        # Load cover
        if cover_path:
            self._thumb_loader.request_with_absolute_key(root, cover_path, QSize(80, 80))

    def _on_thumbnail_ready(self, album_root: Path, pixmap: QPixmap) -> None:
        card = self._cards.get(album_root)
        if card:
            card.set_cover_image(pixmap)

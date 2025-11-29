import sys
from types import ModuleType
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# Ensure the project sources are importable as ``iPhotos.src`` to match legacy tests.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if "iPhotos" not in sys.modules:
    pkg = ModuleType("iPhotos")
    pkg.__path__ = [str(ROOT)]  # type: ignore[attr-defined]
    sys.modules["iPhotos"] = pkg

# Mock QtMultimedia to avoid libpulse dependency in headless tests
if "PySide6.QtMultimedia" not in sys.modules:
    mock_mm = MagicMock()
    mock_mm.__spec__ = MagicMock()
    sys.modules["PySide6.QtMultimedia"] = mock_mm

if "PySide6.QtMultimediaWidgets" not in sys.modules:
    mock_mmw = MagicMock()
    mock_mmw.__spec__ = MagicMock()
    sys.modules["PySide6.QtMultimediaWidgets"] = mock_mmw

# Mock QtOpenGLWidgets to avoid display dependency in headless tests
if "PySide6.QtOpenGLWidgets" not in sys.modules:
    mock_glw = MagicMock()
    mock_glw.__spec__ = MagicMock()
    sys.modules["PySide6.QtOpenGLWidgets"] = mock_glw

if "PySide6.QtOpenGL" not in sys.modules:
    mock_qgl = MagicMock()
    mock_qgl.__spec__ = MagicMock()
    sys.modules["PySide6.QtOpenGL"] = mock_qgl

if "PySide6.QtWidgets" not in sys.modules:
    mock_qt = MagicMock()
    mock_qt.__spec__ = MagicMock()
    sys.modules["PySide6.QtWidgets"] = mock_qt

if "PySide6.QtGui" not in sys.modules:
    mock_gui = MagicMock()
    mock_gui.__spec__ = MagicMock()

    # Define dummy classes for types used in type hints or Slots
    class MockQtClass:
        def __init__(self, *args, **kwargs): pass
        def __getattr__(self, name): return MagicMock()

    class MockQImage(MockQtClass): pass
    class MockQColor(MockQtClass): pass
    class MockQPixmap(MockQtClass): pass
    class MockQIcon(MockQtClass): pass
    class MockQPainter(MockQtClass): pass
    class MockQPen(MockQtClass): pass
    class MockQBrush(MockQtClass): pass
    class MockQMouseEvent(MockQtClass): pass
    class MockQResizeEvent(MockQtClass): pass
    class MockQPaintEvent(MockQtClass): pass
    class MockQPalette(MockQtClass):
        class ColorRole:
            Window = 1
            WindowText = 2
            Base = 3
            AlternateBase = 4
            ToolTipBase = 5
            ToolTipText = 6
            Text = 7
            Button = 8
            ButtonText = 9
            BrightText = 10
            Link = 11
            Highlight = 12
            HighlightedText = 13
            Mid = 14
            Midlight = 15
            Shadow = 16
            Dark = 17

    mock_gui.QImage = MockQImage
    mock_gui.QColor = MockQColor
    mock_gui.QPixmap = MockQPixmap
    mock_gui.QIcon = MockQIcon
    mock_gui.QPainter = MockQPainter
    mock_gui.QPen = MockQPen
    mock_gui.QBrush = MockQBrush
    mock_gui.QMouseEvent = MockQMouseEvent
    mock_gui.QResizeEvent = MockQResizeEvent
    mock_gui.QPaintEvent = MockQPaintEvent
    mock_gui.QPalette = MockQPalette

    sys.modules["PySide6.QtGui"] = mock_gui

if "PySide6.QtSvg" not in sys.modules:
    mock_svg = MagicMock()
    mock_svg.__spec__ = MagicMock()
    sys.modules["PySide6.QtSvg"] = mock_svg

if "PySide6.QtTest" not in sys.modules:
    mock_qttest = MagicMock()
    mock_qttest.__spec__ = MagicMock()
    sys.modules["PySide6.QtTest"] = mock_qttest

# Mock OpenGL to avoid display dependency
if "OpenGL" not in sys.modules:
    mock_gl = MagicMock()
    mock_gl.__spec__ = MagicMock()
    sys.modules["OpenGL"] = mock_gl
    sys.modules["OpenGL.GL"] = MagicMock()

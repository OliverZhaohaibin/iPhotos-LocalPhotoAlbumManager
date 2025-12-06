"""
Unit tests for gl_image_viewer input event handler.

Tests the input event routing logic without requiring Qt GUI infrastructure.
"""

import sys
import importlib
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
import pytest

# Add project root (parent of 'src') to sys.path for package imports
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


@pytest.fixture
def input_handler_module():
    """
    Fixture that mocks the necessary Qt and internal modules, then imports
    and returns the input_handler module.

    This avoids module-level mocking which conflicts with plugins like pytest-qt
    that rely on real Qt modules being loaded at startup.
    """

    # Create mocks
    mock_pyside6 = MagicMock()
    mock_core = MagicMock()
    mock_gui = MagicMock()
    mock_widgets = MagicMock()
    mock_opengl = MagicMock()
    mock_opengl_widgets = MagicMock()
    mock_multimedia = MagicMock()
    mock_multimedia_widgets = MagicMock()

    # Configure specific attributes
    mock_core.Qt.LeftButton = 1

    # Set __spec__ for importlib checks
    mock_multimedia.__spec__ = MagicMock()
    mock_multimedia_widgets.__spec__ = MagicMock()

    # Mock OpenGL
    mock_gl_pkg = MagicMock()
    mock_gl_module = MagicMock()

    # Mock AlbumTreeModel
    mock_album_model_module = MagicMock()
    mock_album_tree_model_class = MagicMock()
    mock_album_tree_model_class.STATIC_NODES = ("All Photos", "Videos", "Live Photos", "Favorites", "Location")
    mock_album_model_module.AlbumTreeModel = mock_album_tree_model_class

    # Prepare the dictionary for patch.dict
    modules_to_patch = {
        'PySide6': mock_pyside6,
        'PySide6.QtCore': mock_core,
        'PySide6.QtGui': mock_gui,
        'PySide6.QtWidgets': mock_widgets,
        'PySide6.QtOpenGL': mock_opengl,
        'PySide6.QtOpenGLWidgets': mock_opengl_widgets,
        'PySide6.QtMultimedia': mock_multimedia,
        'PySide6.QtMultimediaWidgets': mock_multimedia_widgets,
        'OpenGL': mock_gl_pkg,
        'OpenGL.GL': mock_gl_module,
        'src.iPhoto.gui.ui.models.album_tree_model': mock_album_model_module,
    }

    # Apply patch
    with patch.dict(sys.modules, modules_to_patch):
        # Import the module under test inside the patch context
        # We use import_module to ensure we get the module executed with our mocks
        from src.iPhoto.gui.ui.widgets.gl_image_viewer import input_handler

        # If it was already loaded (unlikely in fresh test env, but possible), reload it
        importlib.reload(input_handler)

        yield input_handler


class TestInputEventHandler:
    """Test input event routing."""

    def setup_method(self):
        """Set up test fixtures."""
        self.crop_controller = Mock()
        self.transform_controller = Mock()
        self.on_replay = Mock()
        self.on_fullscreen_exit = Mock()
        self.on_fullscreen_toggle = Mock()
        self.on_cancel_crop_lock = Mock()

    def create_handler(self, module):
        """Helper to create handler instance using the mocked module."""
        return module.InputEventHandler(
            crop_controller=self.crop_controller,
            transform_controller=self.transform_controller,
            on_replay_requested=self.on_replay,
            on_fullscreen_exit=self.on_fullscreen_exit,
            on_fullscreen_toggle=self.on_fullscreen_toggle,
            on_cancel_auto_crop_lock=self.on_cancel_crop_lock,
        )

    def test_routes_to_crop_when_active(self, input_handler_module):
        """Events should route to crop controller when crop mode is active."""
        handler = self.create_handler(input_handler_module)
        self.crop_controller.is_active.return_value = True
        
        event = Mock()
        event.button.return_value = 1  # Qt.LeftButton
        
        result = handler.handle_mouse_press(event)
        
        assert result is True
        self.crop_controller.handle_mouse_press.assert_called_once_with(event)
        self.transform_controller.handle_mouse_press.assert_not_called()

    def test_routes_to_transform_when_crop_inactive(self, input_handler_module):
        """Events should route to transform controller when crop is inactive."""
        handler = self.create_handler(input_handler_module)
        self.crop_controller.is_active.return_value = False
        
        event = Mock()
        event.button.return_value = 1  # Qt.LeftButton
        
        result = handler.handle_mouse_press(event)
        
        assert result is False
        self.on_cancel_crop_lock.assert_called_once()
        self.transform_controller.handle_mouse_press.assert_called_once_with(event)

    def test_replay_mode_triggers_callback(self, input_handler_module):
        """Left click in replay mode should trigger replay callback."""
        handler = self.create_handler(input_handler_module)
        self.crop_controller.is_active.return_value = False
        handler.set_live_replay_enabled(True)
        
        event = Mock()
        event.button.return_value = 1  # Qt.LeftButton
        
        handler.handle_mouse_press(event)
        
        self.on_replay.assert_called_once()
        self.transform_controller.handle_mouse_press.assert_not_called()

    def test_mouse_move_routes_to_crop_when_active(self, input_handler_module):
        """Mouse move should route to crop controller when active."""
        handler = self.create_handler(input_handler_module)
        self.crop_controller.is_active.return_value = True
        
        event = Mock()
        result = handler.handle_mouse_move(event)
        
        assert result is True
        self.crop_controller.handle_mouse_move.assert_called_once_with(event)

    def test_mouse_move_routes_to_transform_when_inactive(self, input_handler_module):
        """Mouse move should route to transform controller when crop inactive."""
        handler = self.create_handler(input_handler_module)
        self.crop_controller.is_active.return_value = False
        handler.set_live_replay_enabled(False)
        
        event = Mock()
        result = handler.handle_mouse_move(event)
        
        assert result is False
        self.transform_controller.handle_mouse_move.assert_called_once_with(event)

    def test_wheel_routes_to_crop_when_active(self, input_handler_module):
        """Wheel events should route to crop controller when active."""
        handler = self.create_handler(input_handler_module)
        self.crop_controller.is_active.return_value = True
        
        event = Mock()
        handler.handle_wheel(event)
        
        self.crop_controller.handle_wheel.assert_called_once_with(event)
        self.transform_controller.handle_wheel.assert_not_called()

    def test_wheel_cancels_crop_lock_when_inactive(self, input_handler_module):
        """Wheel events should cancel crop lock when crop inactive."""
        handler = self.create_handler(input_handler_module)
        self.crop_controller.is_active.return_value = False
        
        event = Mock()
        handler.handle_wheel(event)
        
        self.on_cancel_crop_lock.assert_called_once()
        self.transform_controller.handle_wheel.assert_called_once_with(event)

    def test_double_click_with_fullscreen_window(self, input_handler_module):
        """Double-click should exit fullscreen when window is fullscreen."""
        handler = self.create_handler(input_handler_module)
        event = Mock()
        event.button.return_value = 1
        
        window = Mock()
        window.isFullScreen.return_value = True
        
        result = handler.handle_double_click_with_window(event, window)
        
        assert result is True
        self.on_fullscreen_exit.assert_called_once()

    def test_double_click_with_normal_window(self, input_handler_module):
        """Double-click should toggle fullscreen when window is normal."""
        handler = self.create_handler(input_handler_module)
        event = Mock()
        event.button.return_value = 1
        
        window = Mock()
        window.isFullScreen.return_value = False
        
        result = handler.handle_double_click_with_window(event, window)
        
        assert result is True
        self.on_fullscreen_toggle.assert_called_once()

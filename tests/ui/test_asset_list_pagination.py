import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from PySide6.QtCore import QThreadPool, QModelIndex, QSize

from src.iPhoto.gui.ui.models.asset_list_model import AssetListModel
from src.iPhoto.gui.ui.tasks.page_loader_worker import PageLoaderWorker

@pytest.fixture
def mock_facade():
    facade = MagicMock()
    facade.current_album.manifest = {}
    facade.library_manager.root.return_value = Path("/tmp/library")
    # Mock signals
    facade.linksUpdated = MagicMock()
    facade.assetUpdated = MagicMock()
    facade.scanChunkReady = MagicMock()
    return facade

@pytest.fixture
def model(mock_facade):
    with patch("src.iPhoto.gui.ui.models.asset_list_model.AssetCacheManager") as MockCacheManager, \
         patch("src.iPhoto.gui.ui.models.asset_list_model.AssetDataLoader") as MockDataLoader, \
         patch("src.iPhoto.gui.ui.models.asset_list_model.AssetListStateManager") as MockStateManager:

        # Setup mocks
        MockCacheManager.return_value.thumbnailReady = MagicMock()

        MockDataLoader.return_value.chunkReady = MagicMock()
        MockDataLoader.return_value.loadProgress = MagicMock()
        MockDataLoader.return_value.loadFinished = MagicMock()
        MockDataLoader.return_value.error = MagicMock()

        model = AssetListModel(mock_facade)
        # Manually set album root as prepare_for_album does
        model._album_root = Path("/tmp/album")

        # Restore StateManager mock if overwritten by init or just use the one from init
        # The model sets self._state_manager = AssetListStateManager(...)
        # So it is the mock instance

        return model

def test_start_load_fetches_first_page(model):
    with patch.object(QThreadPool, 'globalInstance') as mock_pool_cls:
        mock_pool = mock_pool_cls.return_value

        model.start_load()

        # Verify worker started
        assert mock_pool.start.called
        # Check args
        # The worker is the first arg to start()
        # Note: LiveIngestWorker might also start if live items exist, but in this mock they don't return anything unless configured

        # Check if any started worker is PageLoaderWorker
        workers = [call[0][0] for call in mock_pool.start.call_args_list]
        page_worker = next((w for w in workers if isinstance(w, PageLoaderWorker)), None)

        assert page_worker is not None
        assert page_worker._cursor is None
        assert page_worker._limit == 100
        assert page_worker._fetch_total is True

def test_can_fetch_more(model):
    model._total_count = 100

    # Mock state manager row_count
    model._state_manager.row_count.return_value = 50
    assert model.canFetchMore(None) is True

    model._state_manager.row_count.return_value = 100
    assert model.canFetchMore(None) is False

def test_fetch_more_triggers_worker(model):
    model._total_count = 200
    model._state_manager.row_count.return_value = 100
    model._state_manager.rows = [{"dt": "2023-01-01", "id": "123"}]

    with patch.object(QThreadPool, 'globalInstance') as mock_pool_cls:
        mock_pool = mock_pool_cls.return_value

        model.fetchMore(None)

        assert mock_pool.start.called
        workers = [call[0][0] for call in mock_pool.start.call_args_list]
        page_worker = next((w for w in workers if isinstance(w, PageLoaderWorker)), None)

        assert page_worker is not None
        assert page_worker._cursor == ("2023-01-01", "123")
        assert page_worker._limit == 100
        assert page_worker._fetch_total is False

def test_on_page_ready_updates_count(model):
    entries = [{"rel": "img1.jpg", "dt": "2023", "id": "1"}]
    total = 500

    with patch.object(model, '_on_loader_chunk_ready') as mock_chunk_ready:
        model._on_page_ready(model._album_root, entries, total)

        assert model._total_count == 500
        mock_chunk_ready.assert_called_with(model._album_root, entries)
        assert model._is_fetching_page is False

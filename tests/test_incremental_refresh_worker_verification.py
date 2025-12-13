
import pytest
from pathlib import Path
from PySide6.QtCore import QThreadPool, Signal, QObject
from typing import Dict, List, Optional
import time

from src.iPhoto.gui.ui.tasks.incremental_refresh_worker import IncrementalRefreshWorker, IncrementalRefreshSignals
from src.iPhoto.cache.index_store import IndexStore

# Mock AssetLoaderWorker.compute_asset_rows since we don't want to rely on real FS scanning
import src.iPhoto.gui.ui.tasks.incremental_refresh_worker as worker_module

def mock_compute_asset_rows(root, featured, filter_params=None):
    # Return fake rows
    store = IndexStore(root)
    # We read from store to simulate real behavior, but we pre-populate store
    rows = list(store.read_geometry_only())
    # Transform to asset entries (simplification)
    entries = []
    for r in rows:
        entries.append({
            "rel": r["rel"],
            "abs": str(root / r["rel"]),
            "location": r.get("location"),
            "featured": False
        })
    return entries, len(entries)

# Monkey patch
worker_module.compute_asset_rows = mock_compute_asset_rows


class ResultCatcher(QObject):
    def __init__(self):
        super().__init__()
        self.results = None
        self.error = None

    def on_results(self, root, rows):
        self.results = rows

    def on_error(self, root, msg):
        self.error = msg

@pytest.fixture
def store(tmp_path):
    return IndexStore(tmp_path)

def test_incremental_refresh_worker(store, qtbot):
    """Test that the worker fetches rows and emits them."""
    root = store.album_root

    # Populate store
    row = {"rel": "test.jpg", "id": "1", "location": "Test Loc"}
    store.append_rows([row])

    signals = IncrementalRefreshSignals()
    catcher = ResultCatcher()
    signals.resultsReady.connect(catcher.on_results)
    signals.error.connect(catcher.on_error)

    worker = IncrementalRefreshWorker(
        root=root,
        featured=[],
        signals=signals
    )

    # Run worker directly
    worker.run()

    assert catcher.results is not None
    assert len(catcher.results) == 1
    assert catcher.results[0]["rel"] == "test.jpg"
    assert catcher.results[0]["location"] == "Test Loc"
    assert catcher.error is None

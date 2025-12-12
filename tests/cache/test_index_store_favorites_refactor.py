from __future__ import annotations

from pathlib import Path
import pytest
from src.iPhoto.cache.index_store import IndexStore

@pytest.fixture
def store(tmp_path: Path) -> IndexStore:
    return IndexStore(tmp_path)

def test_sync_favorites_unicode_paths(store: IndexStore) -> None:
    """Test synchronizing favorites with non-ASCII (Chinese) characters in paths.

    This test simulates the scenario where 'TEMP TABLE' could crash on Windows,
    ensuring that the logic (whether SQL or Python-based) handles these characters correctly.
    """
    # Paths with Chinese characters
    photo1 = "目录/图像1.jpg"
    photo2 = "目录/图像2.jpg"
    photo3 = "其他/图像3.jpg"

    rows = [
        {"rel": photo1, "is_favorite": 0},
        {"rel": photo2, "is_favorite": 1},
        {"rel": photo3, "is_favorite": 0},
    ]
    store.write_rows(rows)

    # Sync: photo1=Fav, photo2=NotFav (removed), photo3=NotFav (unchanged)
    # The sync list contains unicode strings
    store.sync_favorites([photo1])

    data = {r["rel"]: r["is_favorite"] for r in store.read_all()}

    # Check photo1 became favorite
    assert data[photo1] == 1, f"Expected {photo1} to be favorite"
    # Check photo2 was unfavorited
    assert data[photo2] == 0, f"Expected {photo2} to be unfavorited"
    # Check photo3 remained non-favorite
    assert data[photo3] == 0, f"Expected {photo3} to be non-favorite"

def test_sync_favorites_logic_complex_diff(store: IndexStore) -> None:
    """Test complex diff logic: add some, remove some, keep some."""
    rows = [
        {"rel": "keep.jpg", "is_favorite": 1},
        {"rel": "remove.jpg", "is_favorite": 1},
        {"rel": "add.jpg", "is_favorite": 0},
        {"rel": "ignore.jpg", "is_favorite": 0},
    ]
    store.write_rows(rows)

    # Desired state: keep.jpg and add.jpg should be favorites
    target_favorites = ["keep.jpg", "add.jpg"]

    store.sync_favorites(target_favorites)

    data = {r["rel"]: r["is_favorite"] for r in store.read_all()}

    assert data["keep.jpg"] == 1
    assert data["remove.jpg"] == 0
    assert data["add.jpg"] == 1
    assert data["ignore.jpg"] == 0

def test_sync_favorites_empty_list(store: IndexStore) -> None:
    """Test clearing all favorites by passing an empty list."""
    rows = [
        {"rel": "a.jpg", "is_favorite": 1},
        {"rel": "b.jpg", "is_favorite": 1},
    ]
    store.write_rows(rows)

    store.sync_favorites([])

    data = {r["rel"]: r["is_favorite"] for r in store.read_all()}
    assert data["a.jpg"] == 0
    assert data["b.jpg"] == 0

def test_sync_favorites_no_changes(store: IndexStore) -> None:
    """Test syncing when the list matches DB exactly."""
    rows = [
        {"rel": "a.jpg", "is_favorite": 1},
        {"rel": "b.jpg", "is_favorite": 0},
    ]
    store.write_rows(rows)

    store.sync_favorites(["a.jpg"])

    data = {r["rel"]: r["is_favorite"] for r in store.read_all()}
    assert data["a.jpg"] == 1
    assert data["b.jpg"] == 0

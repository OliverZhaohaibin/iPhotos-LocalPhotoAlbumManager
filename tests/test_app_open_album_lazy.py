from pathlib import Path

from iPhoto import app


def test_open_album_skips_hydration_when_disabled(monkeypatch, tmp_path):
    album_dir = tmp_path / "album"
    album_dir.mkdir()

    calls: dict[str, int] = {"read_all": 0, "read_album_assets": 0, "count": 0}

    class DummyStore:
        def __init__(self, root: Path):
            self.root = root

        def read_all(self):
            calls["read_all"] += 1
            raise AssertionError("read_all should not be called when hydration is disabled")

        def read_album_assets(self, *_args, **_kwargs):
            calls["read_album_assets"] += 1
            raise AssertionError("read_album_assets should not be called when hydration is disabled")

        def count(self, **_kwargs):
            calls["count"] += 1
            return 5

        def write_rows(self, _rows):
            raise AssertionError("write_rows should not run in the lazy path")

        def sync_favorites(self, _featured):
            # Minimal stub; the call is expected but should not hydrate the index.
            return None

    def _fail_ensure_links(*_args, **_kwargs):
        raise AssertionError("_ensure_links should not be invoked without hydration")

    monkeypatch.setattr(app, "IndexStore", DummyStore)
    monkeypatch.setattr(app, "_ensure_links", _fail_ensure_links)

    album = app.open_album(album_dir, autoscan=False, hydrate_index=False)

    assert album.root == album_dir
    assert calls["count"] == 1
    assert calls["read_all"] == 0
    assert calls["read_album_assets"] == 0

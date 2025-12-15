from __future__ import annotations

from iPhoto.core.merger import PhotoStreamMerger


class _FakeSource:
    def __init__(self, batches):
        self._batches = list(batches)

    def fetch_page(self, limit):
        if not self._batches:
            return [], None
        rows = self._batches.pop(0)
        if limit and len(rows) > limit:
            rows = rows[:limit]
        return rows, None


def test_photo_stream_merger_orders_sources() -> None:
    src1 = _FakeSource([[{"id": "a1", "ts": 3}, {"id": "a0", "ts": 1}]])
    src2 = _FakeSource([[{"id": "b1", "ts": 2}]])

    merger = PhotoStreamMerger([src1, src2], page_size=2)
    batch = merger.fetch_next_batch(3)

    assert [row["id"] for row in batch] == ["a1", "b1", "a0"]
    assert merger.has_more() is False

from __future__ import annotations

import heapq
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple, Protocol, Any


def _normalize_timestamp(value: object) -> float:
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float("-inf")

    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return float("-inf")
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            return float("-inf")
    return float("-inf")


class _PagedSource(Protocol):
    def fetch_page(self, limit: int, cursor=None) -> Tuple[List[Dict[str, object]], Any]:
        ...


class PhotoStreamMerger:
    """K-way merge helper for paginated photo streams."""

    def __init__(self, sources: Sequence[object], page_size: int = 128) -> None:
        """
        :param sources: Sequence of objects exposing ``fetch_page(limit)`` returning (rows, next_cursor).
        :param page_size: Number of rows to prefetch from each source when refilling buffers.
        """

        self._sources = list(sources)
        self._page_size = page_size
        self._buffers: Dict[int, List[Dict[str, object]]] = {}
        self._cursors: List[Any] = [None] * len(self._sources)
        self._exhausted = [False for _ in self._sources]
        self._active_indices = {idx for idx in range(len(self._sources))}
        self._heap: List[Tuple[float, str, int, Dict[str, object]]] = []
        self._init_heap()

    def _init_heap(self) -> None:
        for idx in range(len(self._sources)):
            item = self._fetch_next_from_source(idx)
            if item is not None:
                heapq.heappush(self._heap, self._make_heap_item(item, idx))

    def _make_heap_item(self, item: Dict[str, object], src_idx: int) -> Tuple[float, str, int, Dict[str, object]]:
        ts_raw = item.get("ts")
        ts_val = float(ts_raw) if isinstance(ts_raw, (int, float)) else _normalize_timestamp(item.get("dt"))
        sort_id = str(item.get("id") or "")
        # Negative timestamp to simulate max-heap ordering (newest first)
        return (-ts_val, sort_id, src_idx, item)

    def _fetch_next_from_source(self, src_idx: int) -> Optional[Dict[str, object]]:
        buffered = self._buffers.get(src_idx)
        if buffered:
            return buffered.pop(0)

        if self._exhausted[src_idx]:
            return None

        current_cursor = self._cursors[src_idx]
        rows, next_cursor = self._sources[src_idx].fetch_page(self._page_size, cursor=current_cursor)
        # If the source signals exhaustion (next_cursor is None) after returning rows,
        # mark it exhausted to avoid re-reading from the start.
        if next_cursor is None:
            self._exhausted[src_idx] = True
            self._active_indices.discard(src_idx)
        else:
            self._cursors[src_idx] = next_cursor

        if not rows:
            self._exhausted[src_idx] = True
            self._active_indices.discard(src_idx)
            return None

        if len(rows) > 1:
            self._buffers[src_idx] = list(rows[1:])
        return rows[0]

    def fetch_next_batch(self, batch_size: int) -> List[Dict[str, object]]:
        """Return up to ``batch_size`` merged rows across all sources."""

        if batch_size <= 0:
            return []

        results: List[Dict[str, object]] = []

        while len(results) < batch_size:
            if not self._heap:
                break

            _, _, src_idx, item = heapq.heappop(self._heap)
            results.append(item)

            next_item = self._fetch_next_from_source(src_idx)
            if next_item is not None:
                heapq.heappush(self._heap, self._make_heap_item(next_item, src_idx))
            elif not self._heap:
                # Attempt to pull one more item from any remaining non-exhausted source
                for idx in list(self._active_indices):
                    candidate = self._fetch_next_from_source(idx)
                    if candidate is not None:
                        heapq.heappush(self._heap, self._make_heap_item(candidate, idx))

        return results

    def has_more(self) -> bool:
        """Return True while any source still has rows."""

        if self._heap:
            return True
        return not all(self._exhausted)

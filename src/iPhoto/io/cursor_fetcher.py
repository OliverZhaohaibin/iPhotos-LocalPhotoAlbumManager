from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..cache.index_store import IndexStore


class CursorQuery:
    """Lightweight wrapper to perform cursor/seek pagination against ``IndexStore``."""

    def __init__(self, store: IndexStore, filter_params: Optional[Dict[str, object]] = None) -> None:
        self._store = store
        self._filter_params = filter_params or {}
        self._cursor: Optional[Tuple[Optional[str], Optional[str]]] = None
        self._exhausted: bool = False

    def fetch_page(
        self, limit: int, cursor: Optional[Tuple[Optional[str], Optional[str]]] = None
    ) -> Tuple[List[Dict[str, object]], Optional[Tuple[Optional[str], Optional[str]]]]:
        """Fetch a page of rows and return the next cursor."""

        if cursor is not None:
            self._cursor = cursor

        rows = self._store.read_geometry_page(
            limit=limit,
            cursor=self._cursor,
            filter_params=self._filter_params,
            sort_by_date=True,
        )
        if not rows:
            self._exhausted = True
            return [], None

        last = rows[-1]
        next_cursor = (last.get("dt"), last.get("id"))
        self._cursor = next_cursor
        return rows, next_cursor

    def reset(self) -> None:
        """Reset the cursor so pagination restarts from the newest row."""

        self._cursor = None
        self._exhausted = False

    @property
    def exhausted(self) -> bool:
        return self._exhausted


"""Asset index storage package.

This package provides a modular architecture for asset persistence using a
**Single Global Database** pattern:

- `repository`: High-level API for CRUD operations (main entry point)
- `engine`: Low-level database connection management
- `migrations`: Schema initialization and updates
- `recovery`: Database corruption recovery
- `queries`: SQL query construction utilities

Architecture:
    The package enforces a unified write pipeline where all database operations
    go through the `AssetRepository` (aliased as `IndexStore`). Key principles:
    
    - **Single Global Database**: One database at the library root
    - **Single Write Gateway**: All writes through `AssetRepository`
    - **Idempotent Writes**: Duplicate scans don't create duplicates
    - **Additive-Only Scans**: Scanning never deletes data

Usage:
    For the global singleton (recommended):
        from iPhoto.cache.index_store import get_global_repository
        store = get_global_repository(library_root)
    
    For direct instantiation (legacy compatibility):
        from iPhoto.cache.index_store import IndexStore
        store = IndexStore(library_root)
"""
from .repository import AssetRepository as IndexStore
from .repository import GLOBAL_INDEX_DB_NAME, get_global_repository, reset_global_repository

__all__ = [
    "IndexStore",
    "GLOBAL_INDEX_DB_NAME",
    "get_global_repository",
    "reset_global_repository",
]

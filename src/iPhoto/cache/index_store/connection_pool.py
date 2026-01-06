"""SQLite connection pool for improved database performance.

This module provides a connection pool implementation for SQLite databases,
allowing connection reuse across multiple queries and reducing connection
overhead.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from queue import Queue, Empty
from typing import Optional, Dict, Any, List, Tuple
import logging

logger = logging.getLogger(__name__)


class ConnectionPool:
    """Thread-safe SQLite connection pool.
    
    Maintains a pool of SQLite connections that can be reused across
    multiple queries, reducing the overhead of creating new connections.
    
    Features:
    - Thread-safe connection acquisition and release
    - Automatic connection initialization with performance pragmas
    - Configurable pool size
    - Connection validation and cleanup
    """
    
    # Class-level registry of pools by database path
    _pools: Dict[str, "ConnectionPool"] = {}
    _pools_lock = threading.Lock()
    
    @classmethod
    def get_pool(cls, db_path: str | Path, pool_size: int = 5) -> "ConnectionPool":
        """Get or create a connection pool for the given database.
        
        Args:
            db_path: Path to the SQLite database file
            pool_size: Maximum number of connections in the pool
            
        Returns:
            ConnectionPool instance for the database
        """
        db_path_str = str(db_path)
        
        with cls._pools_lock:
            if db_path_str not in cls._pools:
                cls._pools[db_path_str] = ConnectionPool(db_path_str, pool_size)
            return cls._pools[db_path_str]
    
    def __init__(self, db_path: str, pool_size: int = 5):
        """Initialize a connection pool.
        
        Args:
            db_path: Path to the SQLite database file
            pool_size: Maximum number of connections in the pool
        """
        self._db_path = db_path
        self._pool_size = pool_size
        self._pool: Queue[sqlite3.Connection] = Queue(maxsize=pool_size)
        self._lock = threading.Lock()
        self._initialized = False
        self._total_connections = 0
    
    def _init_pool(self) -> None:
        """Initialize the connection pool with connections."""
        with self._lock:
            if self._initialized:
                return
            
            for _ in range(self._pool_size):
                conn = self._create_connection()
                if conn:
                    self._pool.put(conn)
                    self._total_connections += 1
            
            self._initialized = True
            logger.debug(
                "Initialized connection pool for %s with %d connections",
                self._db_path,
                self._total_connections,
            )
    
    def _create_connection(self) -> Optional[sqlite3.Connection]:
        """Create a new connection with optimal settings.
        
        Returns:
            Configured SQLite connection or None on error
        """
        try:
            conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,  # Allow use across threads
                timeout=10.0,  # Wait up to 10s for lock
            )
            
            # Apply performance optimizations
            # WAL mode: Better concurrency, faster writes
            conn.execute("PRAGMA journal_mode=WAL")
            # NORMAL synchronous: Balance between safety and performance
            conn.execute("PRAGMA synchronous=NORMAL")
            # 64MB cache: Improve query performance
            conn.execute("PRAGMA cache_size=-64000")
            # Memory temp store: Faster temporary tables
            conn.execute("PRAGMA temp_store=MEMORY")
            # Enable memory-mapped I/O for reads (up to 1GB)
            conn.execute("PRAGMA mmap_size=1073741824")
            
            conn.row_factory = sqlite3.Row  # Enable column access by name
            
            return conn
        except sqlite3.Error as e:
            logger.error("Failed to create database connection: %s", e)
            return None
    
    def acquire(self, timeout: float = 5.0) -> Optional[sqlite3.Connection]:
        """Acquire a connection from the pool.
        
        Args:
            timeout: Maximum time to wait for a connection (seconds)
            
        Returns:
            Database connection or None if timeout
        """
        if not self._initialized:
            self._init_pool()
        
        try:
            conn = self._pool.get(timeout=timeout)
            logger.debug("Connection acquired from pool")
            return conn
        except Empty:
            logger.warning("Connection pool exhausted (timeout after %.1fs)", timeout)
            return None
    
    def release(self, conn: sqlite3.Connection) -> None:
        """Release a connection back to the pool.
        
        Args:
            conn: Connection to release
        """
        if conn is None:
            return
        
        try:
            # Rollback any uncommitted transactions
            conn.rollback()
            self._pool.put(conn, block=False)
            logger.debug("Connection released to pool")
        except Exception as e:
            logger.error("Error releasing connection: %s", e)
            # If we can't return it to the pool, close it
            try:
                conn.close()
            except Exception:
                pass
    
    def execute_query(
        self, 
        query: str, 
        params: Tuple[Any, ...] = (), 
        timeout: float = 5.0
    ) -> List[sqlite3.Row]:
        """Execute a SELECT query and return results.
        
        Args:
            query: SQL query string
            params: Query parameters
            timeout: Connection acquisition timeout
            
        Returns:
            List of result rows
            
        Raises:
            RuntimeError: If connection cannot be acquired
            sqlite3.Error: On database errors
        """
        conn = self.acquire(timeout)
        if conn is None:
            raise RuntimeError("Failed to acquire database connection")
        
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            results = cursor.fetchall()
            return results
        finally:
            self.release(conn)
    
    def execute_many(
        self,
        query: str,
        params_list: List[Tuple[Any, ...]],
        timeout: float = 5.0
    ) -> None:
        """Execute a query multiple times with different parameters.
        
        Args:
            query: SQL query string
            params_list: List of parameter tuples
            timeout: Connection acquisition timeout
            
        Raises:
            RuntimeError: If connection cannot be acquired
            sqlite3.Error: On database errors
        """
        conn = self.acquire(timeout)
        if conn is None:
            raise RuntimeError("Failed to acquire database connection")
        
        try:
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.release(conn)
    
    def execute_transaction(
        self,
        queries: List[Tuple[str, Tuple[Any, ...]]],
        timeout: float = 5.0
    ) -> None:
        """Execute multiple queries in a single transaction.
        
        Args:
            queries: List of (query, params) tuples
            timeout: Connection acquisition timeout
            
        Raises:
            RuntimeError: If connection cannot be acquired
            sqlite3.Error: On database errors
        """
        conn = self.acquire(timeout)
        if conn is None:
            raise RuntimeError("Failed to acquire database connection")
        
        try:
            cursor = conn.cursor()
            for query, params in queries:
                cursor.execute(query, params)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.release(conn)
    
    def shutdown(self) -> None:
        """Close all connections in the pool."""
        with self._lock:
            if not self._initialized:
                return
            
            closed_count = 0
            while not self._pool.empty():
                try:
                    conn = self._pool.get(block=False)
                    conn.close()
                    closed_count += 1
                except Exception as e:
                    logger.error("Error closing connection: %s", e)
            
            self._initialized = False
            logger.info("Closed %d connections from pool", closed_count)
    
    def __del__(self):
        """Cleanup connections on garbage collection."""
        try:
            self.shutdown()
        except Exception:
            pass

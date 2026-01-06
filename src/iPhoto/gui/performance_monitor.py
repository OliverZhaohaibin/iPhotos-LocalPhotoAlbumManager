"""Real-time performance monitoring for GUI operations.

This module provides performance measurement decorators and statistics
collection to help identify bottlenecks and track optimization progress.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional, TypeVar
from functools import wraps

from PySide6.QtCore import QObject, Signal

F = TypeVar('F', bound=Callable[..., Any])


class PerformanceMonitor(QObject):
    """Real-time performance monitoring for application operations.
    
    Tracks timing metrics for decorated operations and provides
    statistical analysis (mean, percentiles, etc.).
    """
    
    # Signal emitted when a slow operation is detected
    slowOperationDetected = Signal(str, float)  # operation_name, duration_ms
    
    def __init__(self, enabled: bool = False, slow_threshold_ms: float = 100.0):
        """Initialize the performance monitor.
        
        Args:
            enabled: Whether monitoring is enabled (default: False for production)
            slow_threshold_ms: Threshold in ms to trigger slowOperationDetected signal
        """
        super().__init__()
        self._enabled = enabled
        self._slow_threshold_ms = slow_threshold_ms
        # Store last 100 measurements for each operation
        self._metrics: Dict[str, deque] = {}
        self._operation_counts: Dict[str, int] = {}
    
    def enable(self, enabled: bool = True) -> None:
        """Enable or disable performance monitoring."""
        self._enabled = enabled
    
    def is_enabled(self) -> bool:
        """Check if monitoring is enabled."""
        return self._enabled
    
    def measure(self, operation: str) -> Callable[[F], F]:
        """Decorator to measure operation performance.
        
        Args:
            operation: Name of the operation being measured
            
        Returns:
            Decorated function that records timing
            
        Example:
            @performance_monitor.measure("open_album")
            def open_album(self, path):
                ...
        """
        def decorator(func: F) -> F:
            @wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                if not self._enabled:
                    return func(*args, **kwargs)
                
                start = time.perf_counter()
                try:
                    result = func(*args, **kwargs)
                    return result
                finally:
                    elapsed = time.perf_counter() - start
                    self._record(operation, elapsed)
                    
                    # Emit signal if operation is slow
                    elapsed_ms = elapsed * 1000
                    if elapsed_ms > self._slow_threshold_ms:
                        self.slowOperationDetected.emit(operation, elapsed_ms)
            
            return wrapper  # type: ignore
        return decorator
    
    def _record(self, operation: str, elapsed: float) -> None:
        """Record a timing measurement.
        
        Args:
            operation: Name of the operation
            elapsed: Elapsed time in seconds
        """
        if operation not in self._metrics:
            self._metrics[operation] = deque(maxlen=100)
            self._operation_counts[operation] = 0
        
        self._metrics[operation].append(elapsed)
        self._operation_counts[operation] += 1
    
    def get_stats(self, operation: str) -> Optional[Dict[str, float]]:
        """Get statistics for an operation.
        
        Args:
            operation: Name of the operation
            
        Returns:
            Dictionary with statistics or None if no data
            Keys: count, total_count, mean, min, max, p50, p95, p99 (all in ms)
        """
        if operation not in self._metrics or not self._metrics[operation]:
            return None
        
        timings = list(self._metrics[operation])
        timings_ms = [t * 1000 for t in timings]  # Convert to milliseconds
        
        return {
            "count": len(timings_ms),
            "total_count": self._operation_counts.get(operation, 0),
            "mean": sum(timings_ms) / len(timings_ms),
            "min": min(timings_ms),
            "max": max(timings_ms),
            "p50": self._percentile(timings_ms, 50),
            "p95": self._percentile(timings_ms, 95),
            "p99": self._percentile(timings_ms, 99),
        }
    
    def get_all_stats(self) -> Dict[str, Dict[str, float]]:
        """Get statistics for all measured operations.
        
        Returns:
            Dictionary mapping operation names to their statistics
        """
        return {
            op: stats
            for op in self._metrics.keys()
            if (stats := self.get_stats(op)) is not None
        }
    
    def print_report(self) -> None:
        """Print a formatted performance report to console."""
        if not self._metrics:
            print("No performance data collected.")
            return
        
        print("=" * 70)
        print("Performance Report")
        print("=" * 70)
        
        for operation in sorted(self._metrics.keys()):
            stats = self.get_stats(operation)
            if stats is None:
                continue
                
            print(f"\n{operation}:")
            print(f"  Samples:     {stats['count']} (total: {stats['total_count']})")
            print(f"  Mean:        {stats['mean']:.2f}ms")
            print(f"  Median (P50):{stats['p50']:.2f}ms")
            print(f"  P95:         {stats['p95']:.2f}ms")
            print(f"  P99:         {stats['p99']:.2f}ms")
            print(f"  Min/Max:     {stats['min']:.2f}ms / {stats['max']:.2f}ms")
        
        print("=" * 70)
    
    def reset(self) -> None:
        """Clear all collected metrics."""
        self._metrics.clear()
        self._operation_counts.clear()
    
    @staticmethod
    def _percentile(data: List[float], p: int) -> float:
        """Calculate percentile of data.
        
        Args:
            data: List of values
            p: Percentile (0-100)
            
        Returns:
            Percentile value
        """
        if not data:
            return 0.0
        
        sorted_data = sorted(data)
        index = int(len(sorted_data) * p / 100)
        index = min(index, len(sorted_data) - 1)
        return sorted_data[index]


# Global performance monitor instance
# Enable in development/debug mode by calling: performance_monitor.enable(True)
performance_monitor = PerformanceMonitor(enabled=False, slow_threshold_ms=100.0)

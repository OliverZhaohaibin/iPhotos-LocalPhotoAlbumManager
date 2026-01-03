"""Tests for AssetListModel backpressure and worker yielding logic."""

from unittest.mock import MagicMock, patch, call
import pytest
from PySide6.QtCore import QThread

from iPhoto.gui.ui.models.asset_list.streaming import AssetStreamBuffer
from iPhoto.gui.ui.tasks.asset_loader_worker import AssetLoaderWorker, LiveIngestWorker, AssetLoaderSignals

class TestAssetStreamBufferBackpressure:
    """Test the extracted AssetStreamBuffer logic."""

    @pytest.fixture
    def flush_callback(self):
        return MagicMock()

    @pytest.fixture
    def finish_callback(self):
        return MagicMock()

    @pytest.fixture
    def stream_buffer(self, flush_callback, finish_callback):
        buffer = AssetStreamBuffer(flush_callback, finish_callback)
        # Mock timer
        buffer._flush_timer = MagicMock()
        return buffer

    def test_backpressure_batching(self, stream_buffer, flush_callback):
        """Test that chunks are buffered and processed in batches."""

        # Verify tuned constants
        assert stream_buffer.DEFAULT_BATCH_SIZE == 100
        assert stream_buffer.DEFAULT_FLUSH_THRESHOLD == 2000
        assert stream_buffer.DEFAULT_FLUSH_INTERVAL_MS == 100

        # Simulate receiving a large chunk (e.g., 500 items)
        # We assume deduplication happened before calling add_chunk (in orchestrator)
        # But here we test add_chunk's buffering.
        # add_chunk expects existing_rels and existing_abs_lookup.
        chunk = [{"rel": f"img{i}.jpg"} for i in range(500)]

        stream_buffer.add_chunk(chunk, set(), lambda x: None)

        stream_buffer._is_flushing = False

        # Call flush (simulating timer)
        stream_buffer._on_timer_flush()

        # 1. Should have consumed 100 items (Batch Size)
        # Remaining: 400
        assert len(stream_buffer._pending_chunks_buffer) == 400
        flush_callback.assert_called_once()
        args, _ = flush_callback.call_args
        assert len(args[0]) == 100
        assert args[0][0]["rel"] == "img0.jpg"
        assert args[0][99]["rel"] == "img99.jpg"

        # 2. Should have started timer for next batch
        stream_buffer._flush_timer.start.assert_called_once_with(stream_buffer.DEFAULT_FLUSH_INTERVAL_MS)

        # Reset mocks
        flush_callback.reset_mock()
        stream_buffer._flush_timer.start.reset_mock()

        # Call flush again
        stream_buffer._on_timer_flush()

        # 3. Should have consumed next 100 items
        assert len(stream_buffer._pending_chunks_buffer) == 300
        flush_callback.assert_called_once()
        args, _ = flush_callback.call_args
        assert len(args[0]) == 100
        assert args[0][0]["rel"] == "img100.jpg"

        # 4. Timer started again
        stream_buffer._flush_timer.start.assert_called_once_with(stream_buffer.DEFAULT_FLUSH_INTERVAL_MS)

    def test_buffer_exhaustion(self, stream_buffer, flush_callback):
        """Test that timer stops when buffer is empty."""

        # Case: 100 items in buffer (exactly one batch)
        chunk = [{"rel": f"img{i}.jpg"} for i in range(100)]
        stream_buffer.add_chunk(chunk, set(), lambda x: None)

        stream_buffer._on_timer_flush()

        # Buffer empty
        assert len(stream_buffer._pending_chunks_buffer) == 0

        # Flush happened
        flush_callback.assert_called_once()

        # Timer should be stopped
        stream_buffer._flush_timer.stop.assert_called_once()
        # Should NOT be started
        stream_buffer._flush_timer.start.assert_not_called()

    def test_finish_pending_flushes_immediately(self, stream_buffer):
        """Buffered rows should drain without delay once load completion is pending."""

        # Prepare a partially drained buffer and mark finish pending
        stream_buffer.set_finish_event(("root", True))
        stream_buffer._pending_chunks_buffer = [{"rel": f"img{i}.jpg"} for i in range(150)]

        # When set_finish_event is called, it calls flush_now().
        # We need to simulate that or call it.
        # Actually set_finish_event calls flush_now() which calls _on_timer_flush().
        # Let's reset mocks before calling set_finish_event because constructor sets them up.
        stream_buffer._flush_timer.reset_mock()

        # Re-trigger logic manually or rely on set_finish_event
        # The test originally manually flushed.
        stream_buffer._on_timer_flush()

        # Remaining items should be scheduled with zero-delay timer
        stream_buffer._flush_timer.start.assert_called_once_with(0)

class TestWorkerYielding:
    @patch("PySide6.QtCore.QThread.currentThread")
    @patch("PySide6.QtCore.QThread.msleep")
    def test_live_ingest_worker_yielding(self, mock_msleep, mock_current_thread):
        """Test that LiveIngestWorker sets low priority and sleeps periodically."""

        mock_thread = MagicMock()
        mock_current_thread.return_value = mock_thread

        # Create worker with 120 items
        items = [{"rel": f"img{i}.jpg"} for i in range(120)]
        signals = AssetLoaderSignals()
        worker = LiveIngestWorker(MagicMock(), items, [], signals)

        # Mock build_asset_entry to accept path_exists kwarg
        with patch("iPhoto.gui.ui.tasks.asset_loader_worker.build_asset_entry") as mock_build:
            # Update lambda to accept **kwargs to catch path_exists
            mock_build.side_effect = lambda r, row, f, **kwargs: row

            worker.run()

            # Check priority set
            mock_thread.setPriority.assert_called_with(QThread.LowPriority)

            # Check sleep calls.
            # 120 items with enumerate starting at 1, so positions are 1..120
            # Sleep condition: i > 0 and i % 50 == 0
            # Sleeps occur at i=50 and i=100
            # Total 2 sleeps
            assert mock_msleep.call_count == 2
            mock_msleep.assert_has_calls([call(10), call(10)])

    @patch("iPhoto.gui.ui.tasks.asset_loader_worker.QThread")
    @patch("iPhoto.gui.ui.tasks.asset_loader_worker.IndexStore")
    @patch("iPhoto.gui.ui.tasks.asset_loader_worker.ensure_work_dir")
    def test_asset_loader_worker_yielding(self, mock_ensure, MockIndexStore, MockQThread):
        """Test that AssetLoaderWorker sets low priority and sleeps periodically."""

        # Mock QThread.currentThread().setPriority
        mock_thread_instance = MagicMock()
        MockQThread.currentThread.return_value = mock_thread_instance
        MockQThread.LowPriority = QThread.LowPriority # Preserve constant

        # Mock Store and Generator
        mock_store = MockIndexStore.return_value
        # Mock the context manager __enter__ return value
        mock_store.transaction.return_value.__enter__.return_value = None
        # IMPORTANT: Mock count to return an integer, otherwise comparison fails!
        mock_store.count.return_value = 120

        # Generator yielding 120 items
        def fake_generator(*args, **kwargs):
            for i in range(120):
                yield {"rel": f"img{i}.jpg"}

        mock_store.read_geometry_only.side_effect = fake_generator

        signals = AssetLoaderSignals()
        signals.error = MagicMock()
        signals.finished = MagicMock()

        worker = AssetLoaderWorker(MagicMock(), [], signals)

        # Mock build_asset_entry
        with patch("iPhoto.gui.ui.tasks.asset_loader_worker.build_asset_entry") as mock_build:
            mock_build.return_value = {"rel": "foo"}

            worker.run()

            # Check for errors
            if signals.error.called:
                pytest.fail(f"Worker emitted error: {signals.error.call_args}")

            # Check priority set
            mock_thread_instance.setPriority.assert_called_with(QThread.LowPriority)

            # Check sleep calls
            # enumerate starts at 1
            # 1..120
            # Sleeps at 50, 100
            assert MockQThread.msleep.call_count == 2
            MockQThread.msleep.assert_has_calls([call(10), call(10)])

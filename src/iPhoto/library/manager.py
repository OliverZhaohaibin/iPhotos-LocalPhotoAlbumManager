    def get_live_scan_results(self, relative_to: Optional[Path] = None) -> List[Dict]:
        """Return a snapshot of valid items currently in the scan buffer.

        Args:
            relative_to: If provided, only returns items that are descendants of this path.
        """
        with self._scan_buffer_lock:
            if not self._live_scan_buffer:
                return []

            if relative_to is None:
                return list(self._live_scan_buffer)

            # Capture root inside lock to prevent race with stop_scanning
            scan_root = self._live_scan_root
            if not scan_root:
                return []

            filtered = []
            try:
                rel_root = relative_to.resolve()
                for item in self._live_scan_buffer:
                    # Item 'rel' is relative to the scan root
                    item_rel = item.get("rel")
                    if not item_rel:
                        continue

                    full_path = (scan_root / item_rel).resolve()

                    if full_path == rel_root or rel_root in full_path.parents:
                        filtered.append(item)
            except (OSError, ValueError):
                pass

            return filtered

"""Batch-oriented helpers for invoking the :command:`exiftool` CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from ..errors import ExternalToolError


def get_metadata_batch(paths: List[Path]) -> List[Dict[str, Any]]:
    """Return metadata for *paths* by launching ``exiftool`` in batches.

    The prior implementation spawned one external process per asset which was
    both slow and prone to locale-related decoding errors on Windows.  Issuing
    batch requests avoids that overhead and lets us explicitly request UTF-8 so
    ``exiftool`` output is decoded consistently across platforms.

    On Windows, the command line length is limited (approx 32k chars).  We chunk
    the requests to prevent `Argument list too long` or `FileNotFoundError` when
    processing thousands of files.

    Parameters
    ----------
    paths:
        The media files that should be inspected.  Passing an empty list returns
        an empty list immediately.

    Raises
    ------
    ExternalToolError
        Raised when the ``exiftool`` executable is missing or when the command
        exits with a non-zero status code.
    """

    executable = shutil.which("exiftool")
    if executable is None:
        raise ExternalToolError(
            "exiftool executable not found. Install it from https://exiftool.org/ "
            "and ensure it is available on PATH."
        )

    if not paths:
        return []

    # Windows command line limit is around 32k.
    # Safe batch size of 50 files ensures we stay well under limits even with long paths.
    BATCH_SIZE = 50
    results: List[Dict[str, Any]] = []

    # Define startupinfo to hide the window on Windows
    startupinfo = None
    creationflags = 0
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

    for i in range(0, len(paths), BATCH_SIZE):
        batch = paths[i : i + BATCH_SIZE]

        cmd = [
            executable,
            "-n",  # emit numeric GPS values instead of DMS strings
            "-g1",  # keep group information (e.g. Composite, GPS) in the payload
            "-json",
            "-charset",
            "UTF8",  # tell exiftool how to interpret incoming file paths
            *[str(path) for path in batch],
        ]

        try:
            # ``encoding`` forces Python to decode the JSON using UTF-8 even on
            # locales that default to a more restrictive codec such as ``cp1252``.
            # ``errors='replace'`` keeps the scan moving if unexpected byte
            # sequences appear in the metadata.
            process = subprocess.run(
                cmd,
                capture_output=True,
                check=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=startupinfo,
                creationflags=creationflags,
            )

            try:
                chunk_results = json.loads(process.stdout)
                if isinstance(chunk_results, list):
                    results.extend(chunk_results)
            except json.JSONDecodeError as exc:
                raise ExternalToolError(f"Failed to parse JSON output from ExifTool: {exc}") from exc

        except FileNotFoundError as exc:
            # Since we checked shutil.which above, this likely means the command line
            # is still too long or some other OS limitation was hit, rather than
            # the executable missing.
            raise ExternalToolError(
                f"Failed to execute exiftool (FileNotFoundError): {exc}"
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else "unknown error"
            # ExifTool reports a successful batch run with summary lines such as
            # ``"2 image files read"`` on stderr. Treat these runs as successful
            # so long as JSON payload is present, otherwise propagate the real
            # failure details to the caller.
            if "image files read" in stderr.lower() and exc.stdout:
                try:
                    chunk_results = json.loads(exc.stdout)
                    if isinstance(chunk_results, list):
                        results.extend(chunk_results)
                    continue
                except json.JSONDecodeError as json_exc:  # pragma: no cover - defensive
                    raise ExternalToolError(
                        "Failed to parse JSON output from ExifTool: "
                        f"{json_exc}"
                    ) from json_exc

            # If we are here, it's a real failure
            raise ExternalToolError(f"ExifTool failed with an error: {stderr}") from exc

    return results


__all__ = ["get_metadata_batch"]

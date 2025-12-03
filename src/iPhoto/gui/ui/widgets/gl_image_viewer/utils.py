"""
Utility functions for GL image viewer.

This module provides helper functions for color normalization and other
miscellaneous utilities.
"""

from __future__ import annotations

from PySide6.QtGui import QColor


def normalise_colour(value: QColor | str) -> QColor:
    """Return a valid ``QColor`` derived from *value* (defaulting to black).
    
    Parameters
    ----------
    value:
        Color as QColor object or string representation
        
    Returns
    -------
    QColor
        Valid QColor object (defaults to black if input is invalid)
    """
    colour = QColor(value)
    if not colour.isValid():
        colour = QColor("#000000")
    return colour

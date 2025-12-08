
import pytest
from PySide6.QtCore import QRectF, QSize

def calculate_center_crop(img_size: QSize, view_size: QSize) -> QRectF:
    """
    Calculates the source rectangle in the image coordinates that should be
    displayed to fill the view_size while preserving aspect ratio (Center Crop).
    """
    img_w, img_h = img_size.width(), img_size.height()
    view_w, view_h = view_size.width(), view_size.height()

    if img_w == 0 or img_h == 0 or view_w == 0 or view_h == 0:
        return QRectF(0, 0, 0, 0)

    img_ratio = img_w / img_h
    view_ratio = view_w / view_h

    if img_ratio > view_ratio:
        # Image is wider relative to height than the view: Crop horizontal sides
        # We want the source height to match the image height, and source width to satisfy ratio
        new_w = img_h * view_ratio
        offset_x = (img_w - new_w) / 2.0
        return QRectF(offset_x, 0.0, new_w, float(img_h))
    else:
        # Image is taller or equal ratio: Crop top/bottom
        # We want source width to match image width
        new_h = img_w / view_ratio
        offset_y = (img_h - new_h) / 2.0
        return QRectF(0.0, offset_y, float(img_w), new_h)

def test_landscape_in_square():
    # 200x100 image in 100x100 view
    img = QSize(200, 100)
    view = QSize(100, 100)
    # Expected: Center 100x100 of the image
    rect = calculate_center_crop(img, view)

    assert rect.x() == 50.0
    assert rect.y() == 0.0
    assert rect.width() == 100.0
    assert rect.height() == 100.0

def test_portrait_in_square():
    # 100x200 image in 100x100 view
    img = QSize(100, 200)
    view = QSize(100, 100)
    # Expected: Center 100x100
    rect = calculate_center_crop(img, view)

    assert rect.x() == 0.0
    assert rect.y() == 50.0
    assert rect.width() == 100.0
    assert rect.height() == 100.0

def test_exact_match():
    img = QSize(150, 100)
    view = QSize(300, 200) # Same ratio 1.5
    rect = calculate_center_crop(img, view)

    assert rect.x() == 0.0
    assert rect.y() == 0.0
    assert rect.width() == 150.0
    assert rect.height() == 100.0

def test_floating_point_precision():
    img = QSize(300, 100)
    view = QSize(100, 100)
    rect = calculate_center_crop(img, view)

    assert rect.width() == 100.0
    assert rect.x() == 100.0 # (300-100)/2 = 100

    img = QSize(100, 100)
    view = QSize(200, 100)
    rect = calculate_center_crop(img, view)

    assert rect.width() == 100.0
    assert rect.height() == 50.0
    assert rect.y() == 25.0

def test_zero_division_guard():
    # Ensure our standalone helper handles zero properly, mirroring what we want in the app
    assert calculate_center_crop(QSize(0, 100), QSize(100, 100)) == QRectF(0, 0, 0, 0)
    assert calculate_center_crop(QSize(100, 100), QSize(0, 100)) == QRectF(0, 0, 0, 0)

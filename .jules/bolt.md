## 2025-02-18 - [Pillow Thumbnail vs ExifTranspose Order]
**Learning:** `PIL.Image.thumbnail()` is an in-place operation that triggers a load, while `ImageOps.exif_transpose()` creates a copy. For non-JPEG images (where `draft()` isn't available), calling `exif_transpose` first forces a full-resolution load and copy. Swapping the order (thumbnail first) works correctly for any rectangular target bounding box and saves massive memory/CPU.
**Action:** When downscaling images with EXIF orientation, always downscale *before* applying orientation correction for any rectangular target bounding box.

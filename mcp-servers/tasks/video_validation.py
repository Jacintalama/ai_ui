"""Screenshot validation for video jobs: image-only, magic-number, dimensions."""
import io

from PIL import Image

MAX_DIM = 4096
ALLOWED = {"PNG", "JPEG", "WEBP"}


class ScreenshotRejected(Exception):
    pass


def validate_screenshot(filename: str, body: bytes) -> None:
    try:
        img = Image.open(io.BytesIO(body))
        img.verify()                        # magic-number / structural check
        img = Image.open(io.BytesIO(body))  # reopen (verify() consumes)
    except Exception:
        raise ScreenshotRejected(f"{filename}: not a valid image")
    if img.format not in ALLOWED:
        raise ScreenshotRejected(f"{filename}: unsupported format {img.format}")
    w, h = img.size
    if w > MAX_DIM or h > MAX_DIM:
        raise ScreenshotRejected(f"{filename}: {w}x{h} exceeds {MAX_DIM}px")

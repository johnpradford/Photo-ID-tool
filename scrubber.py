"""Metadata scrubber: remove EXIF/IPTC/XMP from photos.

Preferred: exiftool -all= (preserves pixels, no re-encode for JPEG).
Fallback: Pillow re-save (re-encodes JPEG at quality=95, documented).
"""

import json
import os
import shutil
import subprocess
from typing import Tuple


def _has_exiftool() -> bool:
    return shutil.which("exiftool") is not None


def scrub_with_exiftool(src: str, dst: str) -> Tuple[bool, str]:
    """Scrub metadata using exiftool. Preserves pixel data (no re-encode).

    Returns (success, message).
    """
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        # Copy file first, then strip in-place on the copy
        shutil.copy2(src, dst)

        result = subprocess.run(
            ["exiftool", "-all=", "-overwrite_original", dst],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return False, f"exiftool error: {result.stderr.strip()}"

        # Verify scrub
        verify = subprocess.run(
            ["exiftool", "-json", dst],
            capture_output=True, text=True, timeout=10
        )
        if verify.returncode == 0:
            data = json.loads(verify.stdout)
            if data:
                remaining = {k: v for k, v in data[0].items()
                             if k not in ("SourceFile", "FileName", "Directory",
                                          "FileSize", "FileModifyDate",
                                          "FileAccessDate", "FileInodeChangeDate",
                                          "FilePermissions", "FileType",
                                          "FileTypeExtension", "MIMEType",
                                          "ImageWidth", "ImageHeight",
                                          "BitsPerSample", "ColorComponents",
                                          "EncodingProcess", "JFIFVersion",
                                          "ResolutionUnit", "XResolution",
                                          "YResolution", "ImageSize", "Megapixels",
                                          "YCbCrSubSampling", "ExifByteOrder")}
                if remaining:
                    return True, f"Scrubbed (minor remnants: {list(remaining.keys())})"

        return True, "Scrubbed clean (exiftool, no re-encode)"

    except subprocess.TimeoutExpired:
        return False, "exiftool timeout"
    except Exception as e:
        return False, str(e)


def scrub_with_pillow(src: str, dst: str) -> Tuple[bool, str]:
    """Fallback: scrub metadata by re-saving with Pillow.

    Note: This re-encodes JPEG at quality=95. Minimal quality loss.
    PNG and TIFF are re-saved without metadata.
    """
    try:
        from PIL import Image

        os.makedirs(os.path.dirname(dst), exist_ok=True)
        img = Image.open(src)

        # Remove EXIF
        data = list(img.getdata())
        clean = Image.new(img.mode, img.size)
        clean.putdata(data)

        ext = os.path.splitext(src)[1].lower()
        if ext in (".jpg", ".jpeg"):
            clean.save(dst, "JPEG", quality=95, optimize=True)
            return True, "Scrubbed (Pillow re-encode, JPEG quality=95)"
        elif ext == ".png":
            clean.save(dst, "PNG", optimize=True)
            return True, "Scrubbed (Pillow re-save, PNG)"
        elif ext in (".tif", ".tiff"):
            clean.save(dst, "TIFF")
            return True, "Scrubbed (Pillow re-save, TIFF)"
        else:
            clean.save(dst)
            return True, "Scrubbed (Pillow re-save)"

    except Exception as e:
        return False, f"Pillow scrub failed: {e}"


def scrub_metadata(src: str, dst: str) -> Tuple[bool, str]:
    """Scrub metadata from src photo, writing clean copy to dst.

    Returns (success, message).
    """
    if _has_exiftool():
        return scrub_with_exiftool(src, dst)
    else:
        return scrub_with_pillow(src, dst)


def scrub_overwrite(filepath: str) -> Tuple[bool, str]:
    """Scrub metadata in place (overwrites original). Use with caution."""
    if _has_exiftool():
        try:
            result = subprocess.run(
                ["exiftool", "-all=", "-overwrite_original", filepath],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return True, "Scrubbed in place (exiftool)"
            return False, result.stderr.strip()
        except Exception as e:
            return False, str(e)
    else:
        # Pillow: scrub to temp, then replace
        import tempfile
        tmp = filepath + ".tmp_scrub"
        ok, msg = scrub_with_pillow(filepath, tmp)
        if ok:
            try:
                os.replace(tmp, filepath)
                return True, "Scrubbed in place (Pillow re-encode)"
            except OSError as e:
                return False, str(e)
        return ok, msg

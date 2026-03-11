"""Metadata extraction from photos: EXIF date, GPS, camera info.

Uses Pillow + piexif as primary method, with subprocess exiftool as preferred
method if available on PATH.
"""

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class PhotoMetadata:
    """Extracted metadata from a photo."""
    date_obs: str = ""          # ISO date YYYY-MM-DD
    time_str: str = ""          # HH:MM:SS
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    camera_info: str = ""       # Camera model/serial
    date_source: str = ""       # Which EXIF tag or fallback was used
    gps_present: bool = False
    raw_exif: dict = None       # For debugging

    def __post_init__(self):
        if self.raw_exif is None:
            self.raw_exif = {}


def _has_exiftool() -> bool:
    """Check if exiftool is available on PATH."""
    return shutil.which("exiftool") is not None


def _parse_exif_datetime(dt_str: str) -> tuple:
    """Parse EXIF datetime string to (date_str, time_str)."""
    if not dt_str:
        return "", ""
    # Common formats: "2024:03:15 14:30:00", "2024-03-15T14:30:00"
    dt_str = dt_str.strip().replace("T", " ")
    for fmt in ["%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%Y:%m:%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z"]:
        try:
            dt = datetime.strptime(dt_str[:19], fmt[:len(fmt)])
            return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S")
        except (ValueError, IndexError):
            continue
    # Try date only
    for fmt in ["%Y:%m:%d", "%Y-%m-%d"]:
        try:
            dt = datetime.strptime(dt_str[:10], fmt)
            return dt.strftime("%Y-%m-%d"), ""
        except (ValueError, IndexError):
            continue
    return "", ""


def _dms_to_decimal(dms_str: str, ref: str = "") -> Optional[float]:
    """Convert DMS string to decimal degrees."""
    if not dms_str:
        return None
    try:
        # Handle "deg min' sec" format
        nums = re.findall(r'[\d.]+', str(dms_str))
        if len(nums) >= 3:
            d, m, s = float(nums[0]), float(nums[1]), float(nums[2])
            dec = d + m / 60 + s / 3600
        elif len(nums) == 1:
            dec = float(nums[0])
        else:
            return None
        if ref in ("S", "W"):
            dec = -dec
        return round(dec, 8)
    except (ValueError, IndexError):
        return None


def extract_with_exiftool(filepath: str) -> PhotoMetadata:
    """Extract metadata using exiftool (most complete)."""
    meta = PhotoMetadata()
    try:
        result = subprocess.run(
            ["exiftool", "-json", "-n", "-DateTimeOriginal", "-CreateDate",
             "-GPSLatitude", "-GPSLongitude", "-GPSLatitudeRef", "-GPSLongitudeRef",
             "-Model", "-SerialNumber", "-BodySerialNumber",
             "-Make", "-DeviceSerialNumber", filepath],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return _extract_with_pillow(filepath)

        data = json.loads(result.stdout)
        if not data:
            return meta
        d = data[0]
        meta.raw_exif = d

        # Date
        for tag, source_name in [("DateTimeOriginal", "DateTimeOriginal"),
                                  ("CreateDate", "CreateDate")]:
            if tag in d and d[tag]:
                date_str, time_str = _parse_exif_datetime(str(d[tag]))
                if date_str:
                    meta.date_obs = date_str
                    meta.time_str = time_str
                    meta.date_source = source_name
                    break

        # GPS - with -n flag, values are already decimal
        if "GPSLatitude" in d and d["GPSLatitude"] is not None:
            try:
                meta.latitude = round(float(d["GPSLatitude"]), 8)
                meta.gps_present = True
            except (ValueError, TypeError):
                pass
        if "GPSLongitude" in d and d["GPSLongitude"] is not None:
            try:
                meta.longitude = round(float(d["GPSLongitude"]), 8)
            except (ValueError, TypeError):
                pass

        # Camera
        parts = []
        for tag in ["Make", "Model"]:
            if tag in d and d[tag]:
                parts.append(str(d[tag]))
        for tag in ["SerialNumber", "BodySerialNumber", "DeviceSerialNumber"]:
            if tag in d and d[tag]:
                parts.append(f"SN:{d[tag]}")
                break
        if parts:
            meta.camera_info = " ".join(parts)

    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        return _extract_with_pillow(filepath)

    return meta


def _extract_with_pillow(filepath: str) -> PhotoMetadata:
    """Fallback: extract metadata using Pillow."""
    meta = PhotoMetadata()
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS, GPSTAGS

        img = Image.open(filepath)
        exif_data = img._getexif()
        if not exif_data:
            return meta

        decoded = {}
        for tag_id, value in exif_data.items():
            tag = TAGS.get(tag_id, tag_id)
            decoded[tag] = value

        # Date
        for tag, source_name in [("DateTimeOriginal", "DateTimeOriginal"),
                                  ("DateTimeDigitized", "DateTimeDigitized"),
                                  ("DateTime", "DateTime")]:
            if tag in decoded and decoded[tag]:
                date_str, time_str = _parse_exif_datetime(str(decoded[tag]))
                if date_str:
                    meta.date_obs = date_str
                    meta.time_str = time_str
                    meta.date_source = source_name
                    break

        # GPS
        gps_info = decoded.get("GPSInfo", {})
        if gps_info:
            gps_decoded = {}
            for k, v in gps_info.items():
                gps_decoded[GPSTAGS.get(k, k)] = v

            if "GPSLatitude" in gps_decoded:
                lat_dms = gps_decoded["GPSLatitude"]
                lat_ref = gps_decoded.get("GPSLatitudeRef", "N")
                try:
                    d = float(lat_dms[0])
                    m = float(lat_dms[1])
                    s = float(lat_dms[2])
                    lat = d + m / 60 + s / 3600
                    if lat_ref == "S":
                        lat = -lat
                    meta.latitude = round(lat, 8)
                    meta.gps_present = True
                except (TypeError, IndexError, ValueError):
                    pass

            if "GPSLongitude" in gps_decoded:
                lon_dms = gps_decoded["GPSLongitude"]
                lon_ref = gps_decoded.get("GPSLongitudeRef", "E")
                try:
                    d = float(lon_dms[0])
                    m = float(lon_dms[1])
                    s = float(lon_dms[2])
                    lon = d + m / 60 + s / 3600
                    if lon_ref == "W":
                        lon = -lon
                    meta.longitude = round(lon, 8)
                except (TypeError, IndexError, ValueError):
                    pass

        # Camera
        parts = []
        for tag in ["Make", "Model"]:
            if tag in decoded and decoded[tag]:
                parts.append(str(decoded[tag]).strip())
        if "BodySerialNumber" in decoded:
            parts.append(f"SN:{decoded['BodySerialNumber']}")
        if parts:
            meta.camera_info = " ".join(parts)

    except Exception:
        pass

    return meta


def extract_metadata(filepath: str) -> PhotoMetadata:
    """Extract metadata using best available method."""
    if _has_exiftool():
        meta = extract_with_exiftool(filepath)
    else:
        meta = _extract_with_pillow(filepath)

    # Fallback: file modification time for date
    if not meta.date_obs:
        try:
            mtime = os.path.getmtime(filepath)
            dt = datetime.fromtimestamp(mtime)
            meta.date_obs = dt.strftime("%Y-%m-%d")
            meta.time_str = dt.strftime("%H:%M:%S")
            meta.date_source = "file_modified_time"
        except OSError:
            pass

    return meta


def format_time_hmm(time_str: str) -> str:
    """Format HH:MM:SS or HH:MM to H:MM (24 h, no leading zero on hour).

    Returns blank string when the input is missing or unparseable.

    >>> format_time_hmm("06:05:00")
    '6:05'
    >>> format_time_hmm("18:42:00")
    '18:42'
    >>> format_time_hmm("")
    ''
    """
    if not time_str or len(time_str) < 3:
        return ""
    try:
        parts = time_str.split(":")
        h = int(parts[0])
        m = int(parts[1])
        return f"{h}:{m:02d}"
    except (ValueError, IndexError):
        return ""



def extract_time_from_col_ac(col_ac: str) -> str:
    """Extract H:MM time from a Column AC identifier string.

    col_ac format: {site}_{file}_{noext}_{YYYY.MM.DD}_{HHMM}_{seq}{ext}
    Example: 2-1_SYPR0015.JPG_SYPR0015_2025.08.16_0227_1.jpg -> '2:27'
    """
    if not col_ac:
        return ""
    try:
        parts = col_ac.split("_")
        for i, part in enumerate(parts):
            if len(part) == 10 and part[4] == "." and part[7] == ".":
                if i + 1 < len(parts):
                    hhmm = parts[i + 1]
                    if len(hhmm) == 4 and hhmm.isdigit():
                        h = int(hhmm[:2])
                        m = int(hhmm[2:])
                        if 0 <= h <= 23 and 0 <= m <= 59:
                            return f"{h}:{m:02d}"
    except (ValueError, IndexError):
        pass
    return ""


def build_comments(meta: PhotoMetadata, user_notes: str = "",
                   original_filename: str = "") -> str:
    """Build the Comments field from metadata and user notes."""
    parts = []
    if meta.time_str:
        parts.append(f"Time: {meta.time_str}")
    if meta.camera_info:
        parts.append(f"Camera: {meta.camera_info}")
    if original_filename:
        parts.append(f"File: {original_filename}")
    if user_notes:
        parts.append(user_notes)
    return "; ".join(parts)


def build_column_ac(site_name: str, filename: str, date_obs: str,
                    time_str: str, sequence: int) -> str:
    """Build the standardised Column AC (Comments) identifier.

    Format: {sitename}_{filename}_{filenameNoExt}_{yyyy.mm.dd}_{HHMM}_{sequence}.{ext_lower}

    Examples:
        10-10_SYER0012.JPG_SYER0012_2025.06.13_2050_12.jpg
        10-5_SYER0004.JPG_SYER0004_2025.06.13_1741_463.jpg
    """
    name_no_ext = os.path.splitext(filename)[0]
    ext = os.path.splitext(filename)[1].lower()
    if not ext:
        ext = ".jpg"

    # Format date as yyyy.mm.dd
    date_fmt = date_obs.replace("-", ".") if date_obs else "0000.00.00"

    # Format time as HHMM (strip seconds and colons)
    if time_str and len(time_str) >= 5:
        hhmm = time_str[:2] + time_str[3:5]
    else:
        hhmm = "0000"

    site = site_name.strip() if site_name else "NOSITE"

    return f"{site}_{filename}_{name_no_ext}_{date_fmt}_{hhmm}_{sequence}{ext}"

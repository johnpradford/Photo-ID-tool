"""Image indexer: scan folder, build photo list, generate stable PhotoIDs."""

import hashlib
import os
from dataclasses import dataclass, field
from typing import List, Optional

from PySide6.QtCore import QThread, Signal

from .constants import SUPPORTED_EXTENSIONS, PHOTO_ID_LENGTH

# Folder names to skip during indexing (case-insensitive)
SKIP_FOLDERS = {"scrubbed", ".scrubbed", "__pycache__", ".git", "thumbs",
                "quoll clipped", "nq clipped", "chuditch clipped"}


def _natural_sort_key(s: str):
    """Sort strings with embedded numbers naturally: '10-2' before '10-10'."""
    import re
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]


@dataclass
class PhotoItem:
    """Represents a single photo in the index."""
    full_path: str
    filename: str
    relative_path: str  # relative to base folder
    photo_id: str
    processed: bool = False
    taxon_name: str = ""
    common_name: str = ""
    row_data: dict = field(default_factory=dict)


def generate_photo_id(relative_path: str, filename: str, filesize: int, mtime: float) -> str:
    """Generate a stable PhotoID from file attributes."""
    raw = f"{relative_path}|{filename}|{filesize}|{mtime}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:PHOTO_ID_LENGTH]


def generate_filename_id(filename: str) -> str:
    """Use filename (without extension) as PhotoID."""
    return os.path.splitext(filename)[0]


class ImageIndexer(QThread):
    """Background thread to scan a folder for images."""
    progress = Signal(int, int)  # current, total
    finished_indexing = Signal(object)  # list of PhotoItem — use object for cross-thread safety
    error = Signal(str)

    def __init__(self, folder_path: str, use_filename_id: bool = False):
        super().__init__()
        self.folder_path = folder_path
        self.use_filename_id = use_filename_id

    def run(self):
        try:
            photos = []
            # First pass: collect all image files with their stat info
            all_files = []
            print(f"ImageIndexer: scanning {self.folder_path}", flush=True)
            for root, dirs, files in os.walk(self.folder_path):
                # Skip excluded folders (modify dirs in-place to prevent descent)
                dirs[:] = sorted(d for d in dirs if d.lower() not in SKIP_FOLDERS)
                for fname in files:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        full_path = os.path.join(root, fname)
                        rel_path = os.path.relpath(full_path, self.folder_path)
                        try:
                            st = os.stat(full_path)
                            all_files.append((root, fname, full_path, rel_path, st))
                        except OSError:
                            pass

            print(f"ImageIndexer: found {len(all_files)} image files", flush=True)

            # Sort: subfolder name (natural sort), then modification time
            def sort_key(item):
                _root, _fname, _full, rel, st = item
                parts = rel.replace("\\", "/").split("/")
                subfolder = parts[0] if len(parts) >= 2 else ""
                return (_natural_sort_key(subfolder), st.st_mtime, _fname.lower())

            all_files.sort(key=sort_key)

            total = len(all_files)
            for i, (root, fname, full_path, rel_path, st) in enumerate(all_files):
                try:
                    if self.use_filename_id:
                        pid = generate_filename_id(fname)
                    else:
                        pid = generate_photo_id(rel_path, fname, st.st_size, st.st_mtime)

                    photo = PhotoItem(
                        full_path=full_path,
                        filename=fname,
                        relative_path=rel_path,
                        photo_id=pid,
                    )
                    photos.append(photo)
                except OSError:
                    pass

                if i % 50 == 0:
                    self.progress.emit(i + 1, total)

            self.progress.emit(total, total)
            print(f"ImageIndexer: emitting {len(photos)} photos to UI", flush=True)
            self.finished_indexing.emit(photos)
        except Exception as e:
            print(f"ImageIndexer ERROR: {e}", flush=True)
            self.error.emit(str(e))


def index_folder_sync(folder_path: str, use_filename_id: bool = False,
                      progress_callback=None) -> List[PhotoItem]:
    """Synchronous indexing with optional progress callback.

    Args:
        progress_callback: callable(current, total) called periodically during scan.
    """
    all_files = []
    try:
        for root, dirs, files in os.walk(folder_path):
            # Skip excluded folders (modify dirs in-place to prevent descent)
            dirs[:] = sorted(d for d in dirs if d.lower() not in SKIP_FOLDERS)
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, folder_path)
                try:
                    st = os.stat(full_path)
                    all_files.append((fname, full_path, rel_path, st))
                except OSError:
                    pass
    except (OSError, PermissionError) as e:
        print(f"Warning: os.walk error in {folder_path}: {e}", flush=True)

    print(f"ImageIndexer: found {len(all_files)} image files", flush=True)

    # Sort: subfolder (natural), then mtime, then filename
    def sort_key(item):
        _fname, _full, rel, st = item
        parts = rel.replace("\\", "/").split("/")
        subfolder = parts[0] if len(parts) >= 2 else ""
        return (_natural_sort_key(subfolder), st.st_mtime, _fname.lower())

    all_files.sort(key=sort_key)

    total = len(all_files)
    photos = []
    for i, (fname, full_path, rel_path, st) in enumerate(all_files):
        try:
            if use_filename_id:
                pid = generate_filename_id(fname)
            else:
                pid = generate_photo_id(rel_path, fname, st.st_size, st.st_mtime)
            photos.append(PhotoItem(
                full_path=full_path, filename=fname,
                relative_path=rel_path, photo_id=pid,
            ))
        except OSError:
            pass
        if progress_callback and i % 100 == 0:
            progress_callback(i + 1, total)

    if progress_callback and total > 0:
        progress_callback(total, total)
    return photos

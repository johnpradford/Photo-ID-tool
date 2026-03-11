# CLAUDE.md — Species ID Tool

AI assistant guide for this codebase. Read this before making changes.

---

## What This Project Is

A desktop GUI app for rapidly identifying wildlife species from camera trap photos. Users step through a folder of images and assign species using quick-buttons or search. Each assignment writes a row to a standardised IBSA-format CSV, and optionally creates a metadata-scrubbed copy of the photo.

**Primary users:** Biologists and field ecologists in Western Australia, working with WAM (Western Australian Museum) species data.

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| GUI framework | PySide6 (Qt6) |
| Excel reading | openpyxl |
| Image handling | Pillow (PIL), optional exiftool binary |
| EXIF metadata | piexif + Pillow; exiftool preferred for lossless ops |
| Packaging | PyInstaller (Windows .exe) |
| Output format | CSV (not Excel — avoids file-locking issues on Windows) |

No database, no network calls, no web framework. Pure desktop app.

---

## Repository Layout

```
Photo-ID-tool/
├── main.py                    # Entry point — crash logging, launches Qt app
├── requirements.txt           # PySide6, openpyxl, Pillow, piexif
├── SpeciesIDTool.bat          # Windows launcher — auto-installs Python/deps
├── TEST_PLAN.md               # Manual test cases (no automated tests)
├── README.md                  # End-user documentation
├── WAM_species_list_2024.xlsx # Bundled species reference data
├── Commonly found Pilbara species.xlsx
├── Commonly found south west species.xlsx
├── logo.png                   # App logo (repo root, NOT inside species_id/)
├── crash_log.txt              # Runtime log (auto-generated, gitignore candidate)
│
└── species_id/                # Main package
    ├── __init__.py
    ├── constants.py           # OUTPUT_COLUMNS, SUPPORTED_EXTENSIONS, paths, version
    ├── ui_main.py             # MainWindow, ImageViewer, ScrubWorker (~2900 lines)
    ├── image_indexer.py       # Folder scan, PhotoID generation, ImageIndexer thread
    ├── metadata.py            # EXIF/GPS extraction (exiftool → Pillow → filesystem)
    ├── scrubber.py            # Metadata stripping (exiftool lossless or Pillow fallback)
    ├── species_db.py          # WAM Excel reader + search index
    ├── exporter.py            # CSV writer — autosave, resume, undo
    └── audit_log.py           # Audit trail (currently disabled in ui_main.py)
```

Note: `logo.png`, `__init__.py`, and all `.py` source modules live at the **repo root**, not inside `species_id/`. The `species_id/` subdirectory is the importable package.

---

## Module Responsibilities

### `main.py`
- Redirects stdout/stderr to `crash_log.txt` before any imports
- Sets `sys.dont_write_bytecode = True` and deletes `__pycache__` on startup (prevents stale `.pyc` on Windows)
- Imports `species_id.ui_main.MainWindow` and runs the Qt event loop
- Uses `os._exit(0)` at shutdown to avoid PySide6 destructor crashes on Python 3.14

### `constants.py`
- Single source of truth for `OUTPUT_COLUMNS` — exact CSV column order
- `SUPPORTED_EXTENSIONS`, `WAM_SHEET_NAME`, `PHOTO_ID_LENGTH`
- `get_config_dir()` → `~/.species_id_tool/`
- **Add new CSV columns here first, always append to end**

### `ui_main.py`
- `MainWindow` — main window; owns all panels, state, coordination
- `ImageViewer(QScrollArea)` — custom viewer with mouse-centred zoom, 25-image LRU pixmap cache, deferred smooth scaling (QTimer 250ms), quoll-clip overlay, multi-ID detection markers. Replaced QGraphicsView which crashes on PySide6 6.10+
- `ScrubWorker(QThread)` — background scrubbing queue to keep UI responsive
- `safe_slot` decorator — wraps Qt slots; catches exceptions and shows error dialogs
- `NoScrollComboBox` — prevents accidental scroll on dropdowns
- Config saved to `~/.species_id_tool/config.json` on every change
- Autosave timer every 30s calls `self._exporter.save()`
- `closeEvent` stops threads, saves data, then `os._exit(0)`

### `image_indexer.py`
- `PhotoItem` dataclass — core data unit (path, PhotoID, processed flag, row_data)
- `generate_photo_id()` — `SHA1(rel_path|filename|filesize|mtime)[:16]`
- `ImageIndexer(QThread)` — async folder scan; emits `progress` and `finished_indexing`
- `index_folder_sync()` — synchronous version for non-Qt contexts
- Skips: `scrubbed`, `.git`, `__pycache__`, `thumbs`, `quoll clipped`, etc.
- Sort order: natural sort by subfolder name, then mtime, then filename

### `metadata.py`
- Priority chain: **exiftool subprocess** → **Pillow EXIF** → **filesystem mtime**
- `extract_metadata(path)` → `PhotoMetadata` dataclass
- `build_comments()` assembles the Comments CSV column (Time, Camera, File)
- `format_time_hmm()` → `H:MM` 24h format for the Time column

### `scrubber.py`
- `scrub_metadata(src, dst)` — copies with all metadata stripped
- With exiftool: lossless (no JPEG re-encode)
- Without exiftool: Pillow re-save, JPEG at quality=95, PNG/TIFF lossless
- `scrub_overwrite(path)` — strips in-place (irreversible)
- Returns `(success: bool, message: str)`

### `species_db.py`
- `SpeciesDB` — loads WAM Excel, builds case-insensitive substring search index
- Handles two formats: standalone WAM xlsx (Sheet1) or hidden sheet inside IBSA workbook
- `SpeciesRecord.to_output_fields()` maps WAM columns to CSV column names
- `COLUMN_MAP` normalises variant header spellings across xlsx versions
- `BIOLOGIC NAMES` column indexed so users can find species by Biologic's internal naming

### `exporter.py`
- `Exporter` — holds output CSV in memory as `OrderedDict[photo_id → row_dict]`
- `write_row()` updates memory only; `save()` writes to disk
- Atomic write: `.tmp` file then `os.replace()` — never corrupts existing data
- If file locked (Windows): falls back to `_latest.csv`
- `undo_last()` — pops undo stack, removes row, saves
- `get_taxon_counts()` — used to repopulate top-20 buttons on resume

### `audit_log.py`
- Appends timestamped action records to `audit_log.csv` next to the output file
- Currently **disabled** in `ui_main.py` ("audit_log removed for performance")

---

## How to Run

```bash
pip install -r requirements.txt
python main.py
```

On Windows: double-click `SpeciesIDTool.bat` — auto-detects Python, installs deps, launches.

## How to Build (Windows Executable)

```bash
pip install pyinstaller
pyinstaller species_id_tool.spec
# Output: dist/SpeciesIDTool/
# Optionally copy exiftool.exe into dist/SpeciesIDTool/
```

---

## Key Data Flows

### Photo loading
1. User clicks "Load Photo Folder"
2. `ImageIndexer` (QThread) scans folder → emits `finished_indexing` with `List[PhotoItem]`
3. `MainWindow` checks each PhotoID against `Exporter._processed_ids`
4. First unprocessed photo loaded; next photo prefetched into viewer cache

### Species assignment
1. User clicks quick-button or double-clicks search result → `_assign_species(record)`
2. `extract_metadata()` reads current photo
3. `Exporter.write_row(photo_id, row_data)` → memory update
4. `Exporter.save()` → atomic CSV write
5. `ScrubWorker.add_job()` if scrubbing enabled → background scrub
6. Auto-advance to next unprocessed photo

### Resume
1. User loads folder + existing output CSV
2. `Exporter._load_existing()` populates `_processed_ids` from CSV rows
3. Photos with matching PhotoIDs marked `processed=True`
4. Top-20 buttons repopulated from `get_taxon_counts()`

---

## Critical Conventions — Do Not Break

**OUTPUT_COLUMNS order is fixed.** The column order in `constants.py` must match the IBSA submission format. You may append new columns at the end; never reorder existing ones.

**PhotoID algorithm is stable by contract.** `generate_photo_id()` uses `rel_path|filename|filesize|mtime`. Changing this breaks resume for all existing CSVs.

**Qt thread safety.** All UI updates on main thread only. Workers communicate via Qt signals. Never call Qt UI methods directly from a QThread.

**`@safe_slot` on all user-facing slots.** Unhandled exceptions in Qt slots cause silent crashes. Always decorate with `@safe_slot`.

**No `__pycache__`.** `main.py` sets `sys.dont_write_bytecode = True` and deletes it at startup. Do not remove this — it prevents stale bytecode bugs on Windows.

**Config via `get_config_dir()`.** Never hardcode `~/.species_id_tool` — always use `constants.get_config_dir()`.

**CSV not Excel for output.** openpyxl locks files on Windows when Excel has them open. The CSV + atomic write approach is intentional.

---

## Testing

No automated tests. All testing is manual using `TEST_PLAN.md` (15 test cases).

Key cases to run after changes:
- **TC05** — undo (removes row + scrubbed copy)
- **TC06** — resume from existing CSV
- **TC07** — duplicate filenames in subfolders
- **TC10/TC11** — metadata scrubbing with and without exiftool
- **TC13** — large folder (500+ photos, UI must stay responsive)

Check `crash_log.txt` after every test run — all stdout/stderr goes there.

---

## Known Quirks

- **No `QGraphicsView`** — crashes on PySide6 6.10+. `ImageViewer(QScrollArea)` is the intentional replacement.
- **`os._exit(0)` at shutdown** — not a bug. Skips atexit to avoid PySide6 destructor crashes on Python 3.14. Data is saved in `closeEvent` before this.
- **WAM sheet name** is `"WAM_AFD Names (Fauna - 2024)"` (hidden sheet). Exact string in `constants.py:WAM_SHEET_NAME`.
- **`scrubbed/` folder** is automatically excluded from `ImageIndexer` scans.
- **`audit_log.py`** exists but is not imported in `ui_main.py` — disabled for performance.
- **Font size**: set to 10pt on startup if Qt reports ≤0pt. Avoids `QFont::setPointSize` warnings.

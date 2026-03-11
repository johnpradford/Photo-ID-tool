# Species ID Tool

Rapid species identification from bulk photos with standardised IBSA Excel export and optional metadata scrubbing.

## Overview

This tool lets you step through a folder of wildlife photos and quickly assign species using configurable quick-buttons or search. Each assignment writes a row to a standardised output `.csv` file matching the IBSA column structure, and optionally creates a metadata-scrubbed copy of the photo.

## Requirements

- **OS**: Windows 10/11 (also runs on macOS/Linux)
- **Python**: 3.11+
- **exiftool** (recommended, optional): Download from [exiftool.org](https://exiftool.org/) and place `exiftool.exe` on your PATH for best metadata extraction and lossless scrubbing. Without it, the tool falls back to Pillow (re-encodes JPEGs at quality=95).

## Installation

### From source

```bash
cd species-id-app
pip install -r requirements.txt
python main.py
```

### Build a Windows executable

```bash
pip install pyinstaller
pyinstaller species_id_tool.spec
```

The output will be in `dist/SpeciesIDTool/`. If using exiftool, copy `exiftool.exe` into that folder.

## Quick Start

1. **Launch** the application (`python main.py` or the built `.exe`)
2. Click **Load Photo Folder** — select a folder containing `.jpg`, `.png`, or `.tif` images (subfolders are scanned)
3. Click **Load Species Workbook (WAM)** — select your `WAM_species_list_2024.xlsx` file or the full IBSA workbook (`ProjectNoXXXX_IBSA_Data_Submission_Workbook_vX1.xlsx`). The tool reads species data from:
   - A standalone WAM xlsx with columns: `BIOLOGIC NAMES`, `WAM NAMES`, `CLASS`, `ORDER`, `FAMILY`, `GENUS`, `SPECIES`, `SUBSPECIES`, `VERNACULAR`, `NATURALISED`, `EPBCConStat`, `BCConStat`, `WAPriority`, `WAConStat`
   - Or the hidden `WAM_AFD Names (Fauna - 2024)` sheet inside an IBSA workbook
4. *(Optional)* Click **Load Common Species List** — select an xlsx containing frequently-encountered species names (one column, scientific or common names). The tool counts frequencies and creates the top-20 quick buttons ranked by how often each species appears.
5. Click **Set Output File** (or accept the auto-generated path inside the photo folder)
6. Set your **default fields** (SiteName, ObsMethod, RecordType, FaunaType, Author, Citation) — these apply to every photo unless changed
7. Start identifying:
   - Click a **quick species button** (right panel) or press its shortcut key
   - Use the **search bar** (Ctrl+F) to find any species and press Enter or double-click
   - Press **Space** to mark as "Unknown"
8. The tool auto-saves after every assignment and auto-advances to the next photo

## How Top 20 Buttons Are Configured

The right panel shows up to 20 quick-assign species buttons, bound to keyboard shortcuts (1–0 for the first 10, F1–F10 for the next 10).

**Population order:**
1. If you click **Load Common Species List** → species ranked by frequency in that file (e.g. your East Pilbara camera trap data has Pilbara Leaf-nosed Bat at #1, Ghost Bat at #2, Northern Quoll at #3...)
2. If resuming from an existing output CSV → top 20 most frequently assigned TaxonNames
3. If a preset file exists at `~/.species_id_tool/top20_preset.json` → those species (auto-saved when you load a common species list)
4. Fallback → first 20 species from the WAM sheet

**Common species file format:** A simple xlsx with one column of species names (either scientific names like `Dasyurus hallucatus` or common names like `Ghost Bat`). The tool resolves each name against the WAM database and ranks by frequency. The included `east_pilbara_common_species.json` is an example preset derived from the East Pilbara data.

**Custom preset format** (`top20_preset.json`):
```json
[
  {"taxon_name": "Rhinonicteris aurantia Pilbara form", "common_name": "Pilbara Leaf-nosed Bat"},
  {"taxon_name": "Macroderma gigas", "common_name": "Ghost Bat"},
  {"taxon_name": "Dasyurus hallucatus", "common_name": "Northern Quoll"}
]
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| ← / → | Previous / next photo |
| 1–9, 0 | Assign quick species 1–10 |
| F1–F10 | Assign quick species 11–20 |
| Ctrl+F | Focus search bar |
| Enter | Assign highlighted search result |
| Space | Mark as "Unknown" |
| Ctrl+Z | Undo last assignment |
| F | Fit image to window |
| Ctrl+O | Open photo folder |
| Ctrl+Q | Quit |
| Ctrl+Scroll | Zoom in/out |

## WAM Column Mapping

The tool maps WAM 2024 columns to IBSA output columns as follows:

| WAM Column | IBSA Output Column | Notes |
|---|---|---|
| WAM NAMES | TaxonName | Primary scientific name |
| CLASS | Class | e.g. Mammalia, Aves, Reptilia |
| ORDER | Order | e.g. Chiroptera, Squamata |
| FAMILY | FamilyName | e.g. Megadermatidae |
| VERNACULAR | CommonName | e.g. Ghost Bat |
| NATURALISED | Introduced | Naturalised/introduced status |
| EPBCConStat | EPBCConStat | EPBC Act conservation status |
| BCConStat | BCConStat | BC Act conservation status |
| WAConStat | WAConStat | WA conservation status |
| WAPriority | *(stored internally)* | WA priority listing |

BIOLOGIC NAMES is also indexed for search (allows matching Biologic's internal naming where it differs from WAM).

## Metadata Extraction

For each photo, the tool extracts (best effort):

| Field | Source | Stored In |
|-------|--------|-----------|
| Date | EXIF DateTimeOriginal → CreateDate → file modified time | `DateObs` (YYYY-MM-DD) |
| Time | Same EXIF tags | `Comments` as "Time: HH:MM:SS" |
| GPS | EXIF GPS tags (decimal degrees) | `Latitude`, `Longitude` |
| Camera | EXIF Make + Model + SerialNumber | `Comments` as "Camera: ..." |
| Filename | Original filename | `Comments` as "File: ..." |

**Priority:** exiftool (if on PATH) → Pillow EXIF → file system metadata.

## Metadata Scrubbing

When "Scrub metadata" is enabled (default):
- A clean copy is created in `<output folder>/scrubbed/<same relative path>`
- **With exiftool**: All EXIF/IPTC/XMP removed; pixel data preserved (no re-encode for JPEG)
- **Without exiftool (Pillow fallback)**: Image is re-saved — JPEG at quality=95 (minimal loss), PNG/TIFF lossless
- After scrubbing, the tool re-reads metadata to verify removal
- The "Overwrite originals" option strips metadata in place (irreversible — requires confirmation)

## Output CSV Format

The output file has exactly these columns in this order — all columns are always present even if blank:

```
ID | Latitude | Longitude | fulcrum_id | FulcrumExportedName | TaxonName | Class |
Order | FamilyName | CommonName | Introduced | SiteName | Abundance | MuseumRef |
EPBCConStat | BCConStat | WAConStat | SRE_Sts | ObsMethod | RecordType | FaunaType |
DateObs | HabType | AnimalID | Recapture | Sex | Weight | Maturity | Comments |
Author | Citation
```

**One row per photo.** The `ID` column contains a stable PhotoID (SHA1 hash of relative path + filename + filesize + modified time, truncated to 16 characters).

## PhotoID Rules

- Default: `SHA1(relative_path | filename | filesize | mtime)[:16]` — stable across runs as long as files aren't moved
- Handles duplicate filenames in different subfolders correctly
- Original filename is stored in the Comments field

## Resume Support

If the output CSV already exists when you load a folder, previously processed photos are detected by their PhotoID and marked as complete. You can continue where you left off. The "Unprocessed only" checkbox filters the view.

## Audit Log

An `audit_log.csv` is created alongside the output file, recording every action with timestamp, PhotoID, file path, assigned species, scrub result, metadata details, and any errors.

## Edge Cases Handled

- Duplicate filenames in different subfolders → unique PhotoID from path hash
- Photos without EXIF → file modification time used; all fields optional
- Very large folders → background thread indexing with progress bar
- WAM sheet not found → manual species entry mode with warning
- Corrupt images → skipped with error logged; app continues
- Undo → removes CSV row and deletes scrubbed copy

## Project Structure

```
species-id-app/
├── main.py                    # Entry point
├── requirements.txt
├── species_id_tool.spec       # PyInstaller build config
├── README.md
├── TEST_PLAN.md
└── species_id/
    ├── __init__.py
    ├── constants.py           # Column order, extensions, config paths
    ├── ui_main.py             # PySide6 UI (main window, viewer, panels)
    ├── image_indexer.py       # Folder scanning, PhotoID generation
    ├── metadata.py            # EXIF/GPS extraction (exiftool + Pillow)
    ├── scrubber.py            # Metadata removal and verification
    ├── species_db.py          # WAM sheet reader, search index
    ├── exporter.py            # CSV writer with autosave and resume
    └── audit_log.py           # CSV audit trail
```

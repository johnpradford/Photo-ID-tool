"""CSV exporter: write output CSV in required column order, autosave, resume.

Simple, reliable, works on every platform. No openpyxl file-locking issues.
"""

import csv
import os
from collections import Counter, OrderedDict
from datetime import datetime
from typing import Dict, List, Optional, Set

from .constants import OUTPUT_COLUMNS


class Exporter:
    """Manages the output CSV file with immediate saves and resume."""

    def __init__(self, output_path: str):
        # Force .csv extension
        if output_path.endswith(".xlsx"):
            output_path = output_path.replace(".xlsx", ".csv")
        if not output_path.endswith(".csv"):
            output_path += ".csv"

        self.output_path = output_path
        self._rows: OrderedDict[str, dict] = OrderedDict()
        self._processed_ids: Set[str] = set()
        self._undo_stack: List[str] = []

        if os.path.exists(output_path):
            self._load_existing()

    def _load_existing(self):
        """Load existing CSV into memory and populate undo stack."""
        try:
            with open(self.output_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    photo_id = row.get("ID", "")
                    if not photo_id:
                        continue
                    self._rows[photo_id] = row
                    if (row.get("TaxonName", "") or
                            "Unknown" in str(row.get("Comments", ""))):
                        self._processed_ids.add(photo_id)
                    self._undo_stack.append(photo_id)
        except Exception as e:
            print(f"Warning: could not load existing CSV: {e}")

    def is_processed(self, photo_id: str) -> bool:
        return photo_id in self._processed_ids

    def get_processed_ids(self) -> Set[str]:
        return self._processed_ids.copy()

    def get_taxon_counts(self) -> Dict[str, int]:
        counts = Counter()
        for row in self._rows.values():
            tn = row.get("TaxonName", "")
            if tn:
                counts[tn] += 1
        return dict(counts)

    def get_row(self, photo_id: str) -> Optional[dict]:
        return self._rows.get(photo_id)

    def write_row(self, photo_id: str, row_data: dict):
        """Write or update a row in memory. Does NOT write to disk."""
        full_row = {col: "" for col in OUTPUT_COLUMNS}
        full_row.update(row_data)
        full_row["ID"] = photo_id

        self._rows[photo_id] = full_row
        self._processed_ids.add(photo_id)
        self._undo_stack.append(photo_id)

    def undo_last(self) -> Optional[str]:
        if not self._undo_stack:
            return None
        photo_id = self._undo_stack.pop()
        if photo_id in self._rows:
            del self._rows[photo_id]
        self._processed_ids.discard(photo_id)
        self._save()
        return photo_id

    def _save(self):
        """Write all rows to CSV. Fast: ~2ms for 200 rows."""
        try:
            tmp = self.output_path + ".tmp"
            with open(tmp, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
                writer.writeheader()
                for row_data in self._rows.values():
                    writer.writerow({col: row_data.get(col, "") for col in OUTPUT_COLUMNS})
            os.replace(tmp, self.output_path)
        except PermissionError:
            alt = self.output_path.replace(".csv", "_latest.csv")
            try:
                os.replace(tmp, alt)
                print(f"Warning: {self.output_path} locked, saved to {alt}")
            except Exception:
                pass
        except Exception as e:
            print(f"CSV save error: {e}")

    def force_refresh(self):
        """Delete the CSV and rewrite from memory. Clears any stale data on disk."""
        try:
            if os.path.exists(self.output_path):
                os.remove(self.output_path)
        except PermissionError:
            print(f"Warning: {self.output_path} locked, cannot delete for refresh")
        except OSError:
            pass
        self._save()

    def save(self):
        """Write all rows to disk. Called by autosave timer, app close, refresh."""
        self._save()

    def patch_all_rows(self, field_updates: Dict[str, str]):
        """Update specified fields on every existing row and re-save."""
        for row in self._rows.values():
            row.update(field_updates)
        self._save()

    def export_timestamped(self) -> str:
        """Export all rows to a new CSV with a date-time stamp in the filename.

        Returns the path of the newly created file. Does NOT overwrite the
        existing output file.
        """
        base, ext = os.path.splitext(self.output_path)
        if not ext:
            ext = ".csv"
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        new_path = f"{base}_{stamp}{ext}"
        try:
            with open(new_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
                writer.writeheader()
                for row_data in self._rows.values():
                    writer.writerow({col: row_data.get(col, "") for col in OUTPUT_COLUMNS})
        except Exception as e:
            print(f"Timestamped export error: {e}")
            return self.output_path
        return new_path

    @property
    def total_rows(self) -> int:
        return len(self._rows)

    @property
    def processed_count(self) -> int:
        return len(self._processed_ids)

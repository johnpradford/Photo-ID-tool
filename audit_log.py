"""Audit logging for species ID assignments and metadata operations."""

import csv
import os
import threading
from datetime import datetime


class AuditLog:
    """Thread-safe CSV audit logger."""

    FIELDS = [
        "Timestamp", "PhotoID", "OriginalFilePath", "AssignedTaxonName",
        "ScrubbedFilePath", "DateSource", "GPSPresent", "Errors",
    ]

    def __init__(self, log_path: str):
        self.log_path = log_path
        self._lock = threading.Lock()
        if not os.path.exists(log_path):
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDS)
                writer.writeheader()

    def log(self, photo_id: str, original_path: str, taxon_name: str = "",
            scrubbed_path: str = "", date_source: str = "",
            gps_present: bool = False, errors: str = ""):
        row = {
            "Timestamp": datetime.now().isoformat(),
            "PhotoID": photo_id,
            "OriginalFilePath": original_path,
            "AssignedTaxonName": taxon_name,
            "ScrubbedFilePath": scrubbed_path,
            "DateSource": date_source,
            "GPSPresent": "Yes" if gps_present else "No",
            "Errors": errors,
        }
        with self._lock:
            with open(self.log_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDS)
                writer.writerow(row)

    def log_error(self, photo_id: str, original_path: str, error: str):
        self.log(photo_id=photo_id, original_path=original_path, errors=error)

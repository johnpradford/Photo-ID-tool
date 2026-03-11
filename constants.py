"""Constants and column definitions for the Species ID application."""

import os

APP_NAME = "Species ID Tool"
APP_VERSION = "1.0.0"

# Required output columns in exact order
OUTPUT_COLUMNS = [
    "ID",
    "Latitude",
    "Longitude",
    "fulcrum_id",
    "FulcrumExportedName",
    "TaxonName",
    "Class",
    "Order",
    "FamilyName",
    "CommonName",
    "Introduced",
    "SiteName",
    "CameraID",
    "Abundance",
    "MuseumRef",
    "EPBCConStat",
    "BCConStat",
    "WAConStat",
    "SRE_Sts",
    "ObsMethod",
    "RecordType",
    "FaunaType",
    "DateObs",
    "HabType",
    "AnimalID",
    "Recapture",
    "Sex",
    "Weight",
    "Maturity",
    "Comments",
    "Author",
    "Citation",
    "PhotoCount",
    "Time",          # Column AH — H:MM 24h from EXIF/filesystem
]

# Species fields that come from the WAM sheet
SPECIES_FIELDS = [
    "TaxonName", "Class", "Order", "FamilyName", "CommonName",
    "Introduced", "EPBCConStat", "BCConStat", "WAConStat", "SRE_Sts",
]

# Supported image extensions
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

# Default config file path (next to executable or script)
def get_config_dir():
    return os.path.join(os.path.expanduser("~"), ".species_id_tool")

CONFIG_FILE = os.path.join(get_config_dir(), "config.json")
TOP20_FILE = os.path.join(get_config_dir(), "top20_preset.json")

# WAM sheet name
WAM_SHEET_NAME = "WAM_AFD Names (Fauna - 2024)"

# PhotoID length
PHOTO_ID_LENGTH = 16

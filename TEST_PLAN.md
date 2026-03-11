# Test Plan — Species ID Tool

## Test Cases

### TC01: Load Photo Folder (basic)
**Steps:** Click "Load Photo Folder", select a folder with 5 JPEGs.
**Expected:** Progress bar shows indexing. All 5 photos appear. First photo displayed. Status shows "Photo 1 of 5 (processed 0 of 5)".

### TC02: Photo Without EXIF
**Steps:** Load a PNG file with no EXIF data. Assign a species.
**Expected:** DateObs populated from file modified time. Latitude/Longitude blank. Comments shows "Time: HH:MM:SS; File: filename.png". No crash.

### TC03: Photo With GPS Metadata
**Steps:** Load a JPEG with embedded GPS coordinates. Assign a species.
**Expected:** Latitude and Longitude columns populated with decimal degrees. Comments includes "Camera: ..." if camera info present.

### TC04: Corrupted Image File
**Steps:** Include a file named `bad.jpg` that is actually a text file renamed. Load the folder.
**Expected:** Image viewer shows error message. Photo is still navigable. Assigning species writes row (with blank metadata). Error logged in audit_log.csv.

### TC05: Undo Assignment
**Steps:** Assign species to photo A, then press Ctrl+Z.
**Expected:** Photo A marked as unprocessed. Row removed from output xlsx. Scrubbed copy deleted (if created). Viewer navigates back to photo A.

### TC06: Resume From Existing Output
**Steps:** Process 3 of 10 photos. Close app. Reopen, load same folder and output file.
**Expected:** 3 photos marked as processed. Progress shows "processed 3 of 10". Unprocessed filter works correctly.

### TC07: Duplicate Filenames in Subfolders
**Steps:** Create `folder_a/photo.jpg` and `folder_b/photo.jpg`. Load parent folder.
**Expected:** Both photos indexed with different PhotoIDs. Both can be assigned independently. Two distinct rows in output xlsx.

### TC08: Species Search and Assignment
**Steps:** Load WAM workbook. Type partial species name in search. Double-click result.
**Expected:** Species fields (TaxonName, Class, Order, etc.) populated from WAM data. Row written to xlsx with correct species info.

### TC09: Mark as Unknown
**Steps:** Navigate to a photo. Press Space.
**Expected:** Comments contains "Unknown". TaxonName is blank. Photo marked as processed. Auto-advances to next photo.

### TC10: Metadata Scrub (exiftool)
**Steps:** With exiftool on PATH, assign species with scrubbing enabled.
**Expected:** Clean copy created in `scrubbed/` subfolder. Re-reading scrubbed file shows no EXIF/IPTC/XMP. Original file unchanged.

### TC11: Metadata Scrub (Pillow fallback)
**Steps:** Without exiftool, assign species with scrubbing enabled to a JPEG.
**Expected:** Scrubbed copy created. JPEG re-encoded at quality=95. No EXIF metadata in scrubbed copy. Audit log notes Pillow method.

### TC12: WAM Workbook Not Found / Wrong Format
**Steps:** Load an xlsx that doesn't contain the WAM sheet.
**Expected:** Warning dialog displayed. App continues in manual entry mode. Search returns no results but doesn't crash. Species DB status shows error.

### TC13: Large Folder (500+ photos)
**Steps:** Load a folder with 500+ images.
**Expected:** Indexing runs in background thread. Progress bar updates. UI remains responsive during indexing. All photos loaded correctly.

### TC14: Quick Species Buttons + Keyboard Shortcuts
**Steps:** Load workbook and process a few photos to populate top 20. Press key "1" on a new photo.
**Expected:** First quick species button's species assigned. Row written with correct TaxonName. Auto-advances.

### TC15: Output xlsx Column Order
**Steps:** Process several photos. Open output xlsx in Excel.
**Expected:** Header row has exactly the 31 required columns in the specified order. No extra columns. All columns present even if blank for most rows.

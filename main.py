#!/usr/bin/env python3
"""Species ID Tool - Entry point with comprehensive crash logging.

All stdout/stderr go to crash_log.txt so errors are captured even when
the console window closes immediately.
"""

import sys
import os
import traceback

# NUCLEAR FIX: Prevent Python from EVER creating __pycache__/.pyc files.
# This MUST be set before any other imports. Without this, Python caches
# compiled bytecode and may run old code even after you replace .py files.
sys.dont_write_bytecode = True

# Resolve paths before anything else
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(SCRIPT_DIR, "crash_log.txt")

# Ensure the package is importable when run directly
sys.path.insert(0, SCRIPT_DIR)

# Also delete any existing __pycache__ from previous runs
import shutil as _shutil
for _cache_dir in [
    os.path.join(SCRIPT_DIR, "__pycache__"),
    os.path.join(SCRIPT_DIR, "species_id", "__pycache__"),
]:
    if os.path.isdir(_cache_dir):
        try:
            _shutil.rmtree(_cache_dir)
        except OSError:
            # If rmtree fails (locked files on Windows), delete individual .pyc files
            try:
                for f in os.listdir(_cache_dir):
                    if f.endswith((".pyc", ".pyo")):
                        try:
                            os.remove(os.path.join(_cache_dir, f))
                        except OSError:
                            pass
            except OSError:
                pass


def main():
    """Main entry point with full crash capture."""

    # Open log file - redirect ALL output so nothing is lost
    try:
        log_file = open(LOG_PATH, "w", encoding="utf-8")
    except Exception:
        log_file = open("crash_log.txt", "w", encoding="utf-8")

    # Keep original streams for fallback console output
    _orig_stdout = sys.stdout
    _orig_stderr = sys.stderr
    sys.stdout = log_file
    sys.stderr = log_file

    def log(msg):
        """Write to log and flush immediately."""
        print(msg, flush=True)

    try:
        log("=== Species ID Tool Crash Log ===")
        log(f"Python {sys.version}")
        log(f"Platform: {sys.platform}")
        log(f"Working dir: {os.getcwd()}")
        log(f"Script dir: {SCRIPT_DIR}")
        log("")

        # Step 1: Import PySide6
        log("Step 1: Importing PySide6...")
        import PySide6
        log(f"  PySide6 version: {PySide6.__version__}")
        from PySide6.QtWidgets import QApplication, QMessageBox
        from PySide6.QtGui import QFont
        from PySide6.QtCore import QTimer
        log("  PySide6 imports OK")

        # Step 2: Import our package
        log("Step 2: Importing species_id...")
        from species_id.ui_main import MainWindow
        from species_id.constants import APP_NAME, APP_VERSION
        log("  species_id imports OK")
        log("")

        # Step 3: Create QApplication
        log("Step 3: Creating QApplication...")
        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setApplicationVersion(APP_VERSION)
        log(f"  QApplication created, platform: {app.platformName()}")

        # Step 4: Fix font - use pt not px to avoid QFont::setPointSize warnings
        log("Step 4: Setting default font...")
        default_font = app.font()
        pts = default_font.pointSize()
        log(f"  Default font pointSize = {pts}")
        if pts <= 0:
            default_font.setPointSize(10)
            app.setFont(default_font)
            log("  Fixed: set to 10pt")
        log("")

        # Step 5: Create main window (most likely crash point)
        log("Step 5: Creating MainWindow...")
        log_file.flush()

        window = MainWindow()
        log("  MainWindow created OK")

        # Step 6: Show window
        log("Step 6: Showing window...")
        window.show()
        log("  Window shown")

        # Step 6b: Force first paint cycle before entering event loop
        log("Step 6b: Processing first paint events...")
        log_file.flush()
        app.processEvents()
        log("  First paint OK")
        log("")

        # Step 7: Enter event loop
        log("Step 7: Entering event loop...")
        log_file.flush()

        exit_code = app.exec()

        log("")
        log(f"App exited with code {exit_code}")
        log_file.flush()
        log_file.close()

        # Use os._exit() to skip Python's atexit cleanup which can trigger
        # PySide6 destructor crashes on Python 3.14. The app has already
        # saved all data and stopped threads in closeEvent.
        os._exit(0)

    except SystemExit as e:
        log(f"\nSystemExit with code {e.code}")
        log_file.flush()
        raise

    except Exception as e:
        tb = traceback.format_exc()
        msg = f"\n{'='*60}\nFATAL ERROR:\n{e}\n\n{tb}\n{'='*60}"
        log(msg)
        log_file.flush()

        # Try to show a dialog
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance():
                QMessageBox.critical(
                    None, "Species ID Tool - Fatal Error",
                    f"The application crashed:\n\n{e}\n\n"
                    f"Full details saved to:\n{LOG_PATH}"
                )
        except Exception:
            pass

        # Backup error file
        try:
            backup = os.path.join(SCRIPT_DIR, "crash_error.txt")
            with open(backup, "w", encoding="utf-8") as f:
                f.write(msg)
        except Exception:
            pass

        # Restore stdout so the console shows the error
        sys.stdout = _orig_stdout
        sys.stderr = _orig_stderr
        print(msg)
        print(f"\nFull log: {LOG_PATH}")
        print("Press Enter to close...")
        try:
            input()
        except Exception:
            pass

        sys.exit(1)

    finally:
        try:
            log_file.flush()
            log_file.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

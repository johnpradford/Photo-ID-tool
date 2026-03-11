"""Main UI for Species ID Tool - PySide6 (Qt6) application."""

import functools
import json
import math
import os
import sys
import traceback
from datetime import datetime
from functools import partial
from typing import Dict, List, Optional

from PySide6.QtCore import (Qt, QSize, QTimer, Signal, Slot, QThread, QPointF)
from PySide6.QtGui import (
    QAction, QFont, QIcon, QImage, QKeySequence, QPixmap, QShortcut,
    QWheelEvent, QPainter, QColor, QTransform, QPen, QBrush,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QProgressBar, QSplitter, QScrollArea,
    QStatusBar,
    QGroupBox, QFormLayout, QTextEdit, QComboBox, QCheckBox, QFrame,
    QToolBar, QMenuBar, QMenu, QSizePolicy, QDialog, QDialogButtonBox,
    QGridLayout,
)

from .constants import (
    APP_NAME, APP_VERSION, OUTPUT_COLUMNS, SPECIES_FIELDS,
    CONFIG_FILE, TOP20_FILE, get_config_dir,
)
from .image_indexer import PhotoItem
from .metadata import extract_metadata, build_comments, build_column_ac, format_time_hmm, extract_time_from_col_ac, PhotoMetadata
from .scrubber import scrub_metadata
from .species_db import SpeciesDB, SpeciesRecord
from .exporter import Exporter
# audit_log removed for performance


# ---------------------------------------------------------------------------
# Path to the bundled logo (lives next to this .py file)
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(_THIS_DIR, "logo.png")


class NoScrollComboBox(QComboBox):
    """QComboBox that ignores mouse wheel unless it has focus from a click."""
    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class ScrubWorker(QThread):
    """Background thread for metadata scrubbing -- keeps UI snappy."""
    finished = Signal(str, str, bool, str)  # photo_id, scrubbed_path, success, message

    def __init__(self):
        super().__init__()
        self._queue: list = []
        self._running = True

    def add_job(self, photo_id: str, src: str, dst: str, overwrite: bool = False):
        self._queue.append((photo_id, src, dst, overwrite))
        if not self.isRunning():
            self.start()

    def run(self):
        while self._queue:
            photo_id, src, dst, overwrite = self._queue.pop(0)
            try:
                if overwrite:
                    from .scrubber import scrub_overwrite
                    ok, msg = scrub_overwrite(src)
                    self.finished.emit(photo_id, src if ok else "", ok, msg)
                else:
                    ok, msg = scrub_metadata(src, dst)
                    self.finished.emit(photo_id, dst if ok else "", ok, msg)
            except Exception as e:
                self.finished.emit(photo_id, "", False, str(e))

    def stop(self):
        self._running = False
        self._queue.clear()


def safe_slot(func):
    """Decorator: catch exceptions in Qt slots and show them in a dialog."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            tb = traceback.format_exc()
            print(f"ERROR in {func.__name__}: {e}\n{tb}", file=sys.stderr)
            try:
                QMessageBox.critical(None, "Error",
                    f"Error in {func.__name__}:\n\n{e}\n\nSee console for full traceback.")
            except Exception:
                pass
    return wrapper


# ---------------------------------------------------------------------------
# ImageViewer -- QScrollArea + QLabel with mouse-centred zoom
# ---------------------------------------------------------------------------

class ImageViewer(QScrollArea):
    """Image viewer with mouse-centred zoom using QScrollArea + QLabel.

    Replaces QGraphicsView (crash vector on PySide6 6.10) and the earlier
    plain-QLabel viewer (zoom was always centre-of-widget).
    """

    # Signal emitted when user clicks the image in quoll-clip mode.
    # Carries the click coordinates in *original image* pixel space.
    image_clicked = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setWidget(self._label)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("QScrollArea { background: #0a0a1a; border: none; }")
        self._label.setStyleSheet("QLabel { background: #0a0a1a; }")

        self._pixmap_orig: Optional[QPixmap] = None
        self._zoom = 1.0
        self._fit_zoom = 1.0
        self._click_mode = False  # True when in quoll-clip mode
        self._overlay_points: List[QPointF] = []  # quoll clip points
        # Multi-ID detection markers
        self._detection_markers: list = []   # [(QPointF, str, int)]
        self._pending_marker = None          # QPointF or None
        # Staged-loading pixmap cache: small LRU for nearby images
        self._px_cache: Dict[str, QPixmap] = {}
        self._px_cache_order: List[str] = []
        self._PX_CACHE_MAX = 25
        # Deferred smooth scaling
        self._smooth_timer = QTimer()
        self._smooth_timer.setSingleShot(True)
        self._smooth_timer.setInterval(250)
        self._smooth_timer.timeout.connect(self._apply_smooth)
        self._use_fast = True

    @property
    def click_mode(self):
        return self._click_mode

    @click_mode.setter
    def click_mode(self, value: bool):
        self._click_mode = value
        self.viewport().setCursor(
            Qt.CrossCursor if value else Qt.ArrowCursor
        )

    def set_overlay_points(self, points: List[QPointF]):
        """Set overlay points (in original-image coords) to draw on the viewer."""
        self._overlay_points = list(points)
        self._update_display()

    def clear_overlay(self):
        self._overlay_points.clear()
        self._update_display()

    def set_detection_markers(self, markers, pending=None):
        self._detection_markers = list(markers)
        self._pending_marker = pending
        self._update_display()

    def clear_detections(self):
        self._detection_markers.clear()
        self._pending_marker = None
        self._update_display()

    def load_image(self, filepath: str) -> bool:
        try:
            # Check cache first
            if filepath in self._px_cache:
                pixmap = self._px_cache[filepath]
            else:
                pixmap = QPixmap(filepath)
                if pixmap.isNull():
                    img = QImage(filepath)
                    if img.isNull():
                        self._label.setText("Cannot load image")
                        self._pixmap_orig = None
                        return False
                    pixmap = QPixmap.fromImage(img)
                # Store in cache
                self._px_cache[filepath] = pixmap
                self._px_cache_order.append(filepath)
                while len(self._px_cache_order) > self._PX_CACHE_MAX:
                    old = self._px_cache_order.pop(0)
                    self._px_cache.pop(old, None)
            self._pixmap_orig = pixmap
            self._zoom = 1.0
            self._compute_fit_zoom()
            self._zoom = self._fit_zoom
            self._use_fast = True
            self._update_display()
            self._smooth_timer.start()
            return True
        except Exception as e:
            self._label.setText(str(e))
            self._pixmap_orig = None
            return False

    def prefetch(self, filepath: str):
        """Pre-load an image into the cache for smooth navigation."""
        if filepath in self._px_cache:
            return
        try:
            pm = QPixmap(filepath)
            if pm.isNull():
                return
            self._px_cache[filepath] = pm
            self._px_cache_order.append(filepath)
            while len(self._px_cache_order) > self._PX_CACHE_MAX:
                old = self._px_cache_order.pop(0)
                self._px_cache.pop(old, None)
        except Exception:
            pass

    def _compute_fit_zoom(self):
        """Calculate the zoom level that fits the image inside the viewport."""
        if self._pixmap_orig is None:
            self._fit_zoom = 1.0
            return
        vp = self.viewport().size()
        pw = self._pixmap_orig.width()
        ph = self._pixmap_orig.height()
        if pw <= 0 or ph <= 0:
            self._fit_zoom = 1.0
            return
        self._fit_zoom = min(vp.width() / pw, vp.height() / ph, 1.0)

    def _update_display(self):
        if self._pixmap_orig is None:
            return
        w = max(1, int(self._pixmap_orig.width() * self._zoom))
        h = max(1, int(self._pixmap_orig.height() * self._zoom))
        scaled = self._pixmap_orig.scaled(w, h, Qt.KeepAspectRatio,
            Qt.FastTransformation if self._use_fast else Qt.SmoothTransformation)

        # Draw overlay markers/lines for quoll clipping
        if self._overlay_points:
            pm = QPixmap(scaled)
            painter = QPainter(pm)
            painter.setRenderHint(QPainter.Antialiasing)
            pen = QPen(QColor(255, 50, 50), 2)
            painter.setPen(pen)
            brush = QBrush(QColor(255, 50, 50, 180))
            painter.setBrush(brush)
            z = self._zoom
            pts_screen = [QPointF(p.x() * z, p.y() * z) for p in self._overlay_points]
            for pt in pts_screen:
                painter.drawEllipse(pt, 5, 5)
            # Draw line between first two points (left→right axis)
            if len(pts_screen) >= 2:
                pen2 = QPen(QColor(50, 255, 50), 2, Qt.DashLine)
                painter.setPen(pen2)
                painter.setBrush(Qt.NoBrush)
                painter.drawLine(pts_screen[0], pts_screen[1])
            if len(pts_screen) >= 3:
                # Draw perpendicular indicator for top point
                pen3 = QPen(QColor(50, 150, 255), 2, Qt.DashLine)
                painter.setPen(pen3)
                p1, p2, p3 = pts_screen[0], pts_screen[1], pts_screen[2]
                ax = p2.x() - p1.x()
                ay = p2.y() - p1.y()
                axis_len_sq = ax * ax + ay * ay
                if axis_len_sq > 0:
                    t = ((p3.x() - p1.x()) * ax + (p3.y() - p1.y()) * ay) / axis_len_sq
                    foot = QPointF(p1.x() + t * ax, p1.y() + t * ay)
                    painter.drawLine(foot, p3)
            if len(pts_screen) >= 4:
                # Draw the oriented bounding box from 4 points
                p1, p2, p3, p4 = pts_screen[:4]
                ax = p2.x() - p1.x()
                ay = p2.y() - p1.y()
                alen = math.hypot(ax, ay)
                if alen > 0:
                    ux, uy = ax / alen, ay / alen
                    px, py = -uy, ux
                    mx = (p1.x() + p2.x()) / 2.0
                    my = (p1.y() + p2.y()) / 2.0
                    t_perp = (p3.x() - mx) * px + (p3.y() - my) * py
                    b_perp = (p4.x() - mx) * px + (p4.y() - my) * py
                    min_p = min(t_perp, b_perp)
                    max_p = max(t_perp, b_perp)
                    hl = alen / 2.0
                    corners = [
                        QPointF(mx - hl * ux + min_p * px, my - hl * uy + min_p * py),
                        QPointF(mx + hl * ux + min_p * px, my + hl * uy + min_p * py),
                        QPointF(mx + hl * ux + max_p * px, my + hl * uy + max_p * py),
                        QPointF(mx - hl * ux + max_p * px, my - hl * uy + max_p * py),
                    ]
                    pen4 = QPen(QColor(255, 255, 50), 2, Qt.SolidLine)
                    painter.setPen(pen4)
                    painter.setBrush(Qt.NoBrush)
                    for i in range(4):
                        painter.drawLine(corners[i], corners[(i + 1) % 4])
            painter.end()
            scaled = pm

        # Draw multi-ID detection markers
        if self._detection_markers or self._pending_marker:
            pm = QPixmap(scaled)
            painter = QPainter(pm)
            painter.setRenderHint(QPainter.Antialiasing)
            z = self._zoom
            font = painter.font()
            font.setPointSize(10)
            font.setBold(True)
            painter.setFont(font)
            # Confirmed markers: cyan circle + white label
            for pt, label, num in self._detection_markers:
                sx, sy = pt.x() * z, pt.y() * z
                painter.setPen(QPen(QColor(0, 220, 255), 2))
                painter.setBrush(QBrush(QColor(0, 220, 255, 80)))
                painter.drawEllipse(QPointF(sx, sy), 14, 14)
                painter.setPen(QPen(QColor(255, 255, 255)))
                painter.setBrush(Qt.NoBrush)
                painter.drawText(int(sx - 5), int(sy + 4), str(num))
                painter.drawText(int(sx + 18), int(sy + 5), label)
            # Pending marker: yellow "?"
            if self._pending_marker:
                sx, sy = self._pending_marker.x() * z, self._pending_marker.y() * z
                painter.setPen(QPen(QColor(255, 220, 50), 2))
                painter.setBrush(QBrush(QColor(255, 220, 50, 80)))
                painter.drawEllipse(QPointF(sx, sy), 14, 14)
                painter.setPen(QPen(QColor(255, 255, 255)))
                painter.drawText(int(sx - 4), int(sy + 5), "?")
            painter.end()
            scaled = pm

        self._label.setPixmap(scaled)
        self._label.resize(scaled.size())

    def mousePressEvent(self, event):
        """Handle mouse clicks for quoll-clip mode."""
        if self._click_mode and self._pixmap_orig and event.button() == Qt.LeftButton:
            # Convert viewport click to original image coordinates
            vp_pos = event.position()
            hs = self.horizontalScrollBar()
            vs = self.verticalScrollBar()
            vp_w = self.viewport().width()
            vp_h = self.viewport().height()
            label_w = self._label.width()
            label_h = self._label.height()
            offset_x = max(0, (vp_w - label_w) / 2)
            offset_y = max(0, (vp_h - label_h) / 2)
            img_x = (hs.value() + vp_pos.x() - offset_x) / self._zoom
            img_y = (vs.value() + vp_pos.y() - offset_y) / self._zoom
            # Bounds check
            if 0 <= img_x <= self._pixmap_orig.width() and 0 <= img_y <= self._pixmap_orig.height():
                self.image_clicked.emit(img_x, img_y)
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        if self._pixmap_orig is None:
            return

        # Mouse position in viewport coordinates
        vp_pos = event.position()

        # Current scroll values
        hs = self.horizontalScrollBar()
        vs = self.verticalScrollBar()

        # Centering offset when image is smaller than viewport
        vp_w = self.viewport().width()
        vp_h = self.viewport().height()
        label_w = self._label.width()
        label_h = self._label.height()
        offset_x = max(0, (vp_w - label_w) / 2)
        offset_y = max(0, (vp_h - label_h) / 2)

        # Point in original-image coordinates under the mouse
        img_x = (hs.value() + vp_pos.x() - offset_x) / self._zoom
        img_y = (vs.value() + vp_pos.y() - offset_y) / self._zoom

        # Apply zoom factor
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new_zoom = max(self._fit_zoom * 0.5, min(15.0, self._zoom * factor))
        self._zoom = new_zoom
        self._use_fast = True
        self._update_display()
        self._smooth_timer.start()

        # Recompute centering offsets after resize
        label_w = self._label.width()
        label_h = self._label.height()
        offset_x = max(0, (vp_w - label_w) / 2)
        offset_y = max(0, (vp_h - label_h) / 2)

        # Scroll so the same image point stays under the mouse
        new_h = int(img_x * new_zoom - vp_pos.x() + offset_x)
        new_v = int(img_y * new_zoom - vp_pos.y() + offset_y)
        hs.setValue(new_h)
        vs.setValue(new_v)

    def fit_image(self):
        self._compute_fit_zoom()
        self._zoom = self._fit_zoom
        self._use_fast = False
        self._update_display()
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)

    def _apply_smooth(self):
        if self._pixmap_orig and self._use_fast:
            self._use_fast = False
            self._update_display()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pixmap_orig and abs(self._zoom - self._fit_zoom) < 0.01:
            self._compute_fit_zoom()
            self._zoom = self._fit_zoom
            self._update_display()


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1200, 800)
        self.resize(1600, 1000)

        # State
        self.photos: List[PhotoItem] = []
        self.current_index = 0
        self.species_db = SpeciesDB()
        self.exporter: Optional[Exporter] = None
        # audit_log removed
        self.photo_folder = ""
        self.output_path = ""
        self.scrub_output_root = ""
        self.top20_species: List[SpeciesRecord] = []
        self.show_unprocessed_only = False
        self.scrub_enabled = True
        self.overwrite_originals = False
        self._sequence_counter = 0
        self._search_results_list: List[SpeciesRecord] = []
        self._meta_cache: Dict[str, PhotoMetadata] = {}
        self._subfolder_list: List[str] = []
        self._subfolder_index: int = -1
        # Same-individual tracking
        self._last_assigned_photo_id: Optional[str] = None
        self._same_individual_count: int = 0
        # Multi-ID mode: assign multiple species to one photo
        self._multi_id_active: bool = False
        self._multi_id_count: int = 0
        self._multi_id_detections: list = []     # [(QPointF, SpeciesRecord)]
        self._multi_id_pending_point = None      # QPointF or None
        # Quoll clipping state
        self._quoll_clip_points: List[QPointF] = []
        self._quoll_clip_active: bool = False
        self._clip_species_name: str = ""      # "NQ" or "Chuditch"
        self._clip_folder_name: str = ""       # "NQ clipped" or "Chuditch clipped" 
        # Per-photo reset tracking
        self._last_shown_index: int = -1
        # Reentrancy guard
        self._assigning: bool = False
        # Processed count (incremental)
        self._processed_count: int = 0
        # Background scrubber
        self._scrub_worker = ScrubWorker()
        self._scrub_worker.finished.connect(self._on_scrub_done)

        self._setup_ui()
        self._setup_shortcuts()
        QTimer.singleShot(0, self._apply_dark_theme)
        # Autosave timer: write CSV every 30s
        self._autosave_timer = QTimer()
        self._autosave_timer.setInterval(30_000)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()

    def closeEvent(self, event):
        try:
            self._autosave_timer.stop()
            if self.exporter:
                self.exporter.save()
            self._scrub_worker.stop()
            if self._scrub_worker.isRunning():
                self._scrub_worker.quit()
                self._scrub_worker.wait(2000)
            self._meta_cache.clear()
        except Exception:
            pass
        event.accept()

    def _autosave(self):
        if self.exporter:
            self.exporter.save()

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _apply_dark_theme(self):
        try:
            self.setStyleSheet("""
            QMainWindow { background: #1a1a2e; }
            QWidget { background: #16213e; color: #e0e0e0; font-family: 'Segoe UI', Arial; font-size: 10pt; }
            QLabel { background: transparent; }
            QGroupBox {
                border: 1px solid #3a3a5c; border-radius: 6px;
                margin-top: 10px; padding-top: 14px;
                font-weight: bold; color: #a0c4ff;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; }
            QLineEdit, QTextEdit, QComboBox {
                background: #0f3460; border: 1px solid #3a3a5c;
                border-radius: 4px; padding: 5px; color: #e0e0e0;
            }
            QLineEdit:focus, QTextEdit:focus { border-color: #5a8fbf; }
            QPushButton {
                background: #1a3a5c; color: #e0e0e0; border: 1px solid #3a3a5c;
                border-radius: 4px; padding: 6px 12px; font-weight: bold;
            }
            QPushButton:hover { background: #3d5a80; border-color: #5a8fbf; }
            QPushButton:pressed { background: #4a7fb5; }
            QPushButton:disabled { background: #1a1a2e; color: #555; }
            QListWidget {
                background: #0f3460; border: 1px solid #3a3a5c;
                border-radius: 4px; color: #e0e0e0;
            }
            QListWidget::item:selected { background: #3d5a80; }
            QListWidget::item:hover { background: #2a4a6b; }
            QProgressBar {
                border: 1px solid #3a3a5c; border-radius: 4px;
                text-align: center; color: #e0e0e0;
            }
            QProgressBar::chunk { background: #4a7fb5; border-radius: 3px; }
            QScrollBar:vertical { background: #1a1a2e; width: 10px; }
            QScrollBar::handle:vertical { background: #3a3a5c; border-radius: 5px; min-height: 20px; }
            QScrollBar:horizontal { background: #1a1a2e; height: 10px; }
            QScrollBar::handle:horizontal { background: #3a3a5c; border-radius: 5px; min-width: 20px; }
            QCheckBox { spacing: 6px; }
            QCheckBox::indicator { width: 16px; height: 16px; }
            QStatusBar { background: #0f3460; color: #a0c4ff; border-top: 1px solid #3a3a5c; }
            QMenuBar { background: #0f3460; color: #e0e0e0; }
            QMenuBar::item:selected { background: #3d5a80; }
            QMenu { background: #16213e; color: #e0e0e0; border: 1px solid #3a3a5c; }
            QMenu::item:selected { background: #3d5a80; }
            QSplitter::handle { background: #3a3a5c; }
            #lbl_assignment {
                font-size: 11pt; font-weight: bold; padding: 6px;
                background: #0f3460; border-radius: 4px; color: #a0c4ff;
            }
            #lbl_filename { font-size: 9pt; color: #888; padding: 2px; }
            #lbl_camera_id { color: #a0c4ff; font-weight: bold; }
            #lbl_db_status { color: #ff6b6b; }
            #lbl_hint { color: #888; font-style: italic; }
            #field_site_ro { background: #1a1a2e; color: #a0c4ff; }
            #btn_remove_quick {
                background: transparent; color: #ff6b6b; border: none;
                font-size: 9pt; font-weight: bold; padding: 0px;
                min-width: 18px; max-width: 18px;
                min-height: 18px; max-height: 18px;
            }
            #btn_remove_quick:hover { color: #ff3333; background: #3a1a1a; border-radius: 9px; }
            #btn_same_individual {
                background: #2d4a1a; color: #a0d468; border: 1px solid #4a7a2e;
                border-radius: 4px; padding: 4px 8px; font-weight: bold;
            }
            #btn_same_individual:hover { background: #3d6a2a; border-color: #6aaa3e; }
            #btn_same_individual:pressed { background: #4d8a3a; }
            #btn_same_individual:disabled { background: #1a1a2e; color: #555; border-color: #333; }
            #btn_multi_id {
                background: #1a3a5c; color: #a0c4ff; border: 1px solid #3a5a8c;
                border-radius: 4px; padding: 4px 8px; font-weight: bold;
            }
            #btn_multi_id:hover { background: #2a5a8c; border-color: #5a8fbf; }
            #btn_multi_id:checked {
                background: #5a3a00; color: #ffd166; border-color: #aa8833;
            }
            #btn_multi_id:checked:hover { background: #6a4a10; }
            #btn_unknown_id {
                background: #5a3a00; color: #ffd166; border: 1px solid #aa8833;
                border-radius: 4px; padding: 6px 12px; font-weight: bold;
            }
            #btn_unknown_id:hover { background: #6a4a10; border-color: #ccaa44; }
            #btn_unknown_id:pressed { background: #8a6a20; }
            #btn_multi_same_go {
                background: #2d4a1a; color: #a0d468; border: 1px solid #4a7a2e;
                border-radius: 4px; padding: 4px 8px; font-weight: bold;
            }
            #btn_multi_same_go:hover { background: #3d6a2a; border-color: #6aaa3e; }
            #btn_multi_same_go:disabled { background: #1a1a2e; color: #555; border-color: #333; }
            #btn_multi_same_go:pressed { background: #4d8a3a; }
            #btn_clip_quoll {
                background: #3a1a5a; color: #d4a0ff; border: 1px solid #7a44aa;
                border-radius: 4px; padding: 6px 12px; font-weight: bold;
            }
            #btn_clip_quoll:hover { background: #4a2a6a; border-color: #9a64ca; }
            #btn_clip_quoll:checked { background: #6a3a9a; color: #ffffff; border-color: #bb88ee; }
            #btn_clip_quoll:pressed { background: #8a5aba; }
        """)
        except Exception as e:
            print(f"WARNING: Failed to apply dark theme: {e}", flush=True)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # === LEFT: Image viewer ===
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        nav_bar = QHBoxLayout()
        self.btn_prev = QPushButton("Prev")
        self.btn_prev.clicked.connect(self.go_prev)
        self.btn_next = QPushButton("Next")
        self.btn_next.clicked.connect(self.go_next)
        self.lbl_progress = QLabel("No photos loaded")
        self.lbl_progress.setAlignment(Qt.AlignCenter)
        self.chk_unprocessed = QCheckBox("Unprocessed only")
        self.chk_unprocessed.toggled.connect(self._toggle_filter)

        nav_bar.addWidget(self.btn_prev)
        nav_bar.addWidget(self.lbl_progress, 1)
        nav_bar.addWidget(self.chk_unprocessed)
        nav_bar.addWidget(self.btn_next)
        left_layout.addLayout(nav_bar)

        self.image_viewer = ImageViewer()
        self.image_viewer.image_clicked.connect(self._on_image_click)
        left_layout.addWidget(self.image_viewer, 1)

        self.lbl_assignment = QLabel("")
        self.lbl_assignment.setAlignment(Qt.AlignCenter)
        self.lbl_assignment.setObjectName("lbl_assignment")
        left_layout.addWidget(self.lbl_assignment)

        self.lbl_filename = QLabel("")
        self.lbl_filename.setAlignment(Qt.AlignCenter)
        self.lbl_filename.setObjectName("lbl_filename")
        left_layout.addWidget(self.lbl_filename)

        splitter.addWidget(left_widget)

        # === RIGHT: Control panel ===
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setMinimumWidth(380)
        right_scroll.setMaximumWidth(520)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setSpacing(6)

        # --- Biologic logo ---
        if os.path.exists(LOGO_PATH):
            logo_pix = QPixmap(LOGO_PATH)
            if not logo_pix.isNull():
                logo_label = QLabel()
                try:
                    logo_img = logo_pix.toImage().convertToFormat(QImage.Format_ARGB32)
                    w, h = logo_img.width(), logo_img.height()
                    bpl = logo_img.bytesPerLine()
                    ptr = logo_img.bits()
                    if ptr is not None:
                        buf = bytearray(bytes(ptr))
                        for i in range(0, len(buf), 4):
                            b, g, r = buf[i], buf[i+1], buf[i+2]
                            if r < 30 and g < 30 and b < 30:
                                buf[i+3] = 0
                        new_img = QImage(bytes(buf), w, h, bpl,
                                         QImage.Format_ARGB32).copy()
                        logo_pix = QPixmap.fromImage(new_img)
                except Exception:
                    pass  # keep original if byte manipulation fails
                logo_pix = logo_pix.scaledToHeight(80, Qt.SmoothTransformation)
                logo_label.setPixmap(logo_pix)
                logo_label.setAlignment(Qt.AlignCenter)
                logo_label.setStyleSheet("padding: 6px 0px;")
                right_layout.addWidget(logo_label)

        # --- Setup ---
        setup_group = QGroupBox("Setup")
        setup_lay = QVBoxLayout(setup_group)
        self.btn_load_folder = QPushButton("Load Photo Folder")
        self.btn_load_folder.clicked.connect(self.load_photo_folder)
        self.btn_load_workbook = QPushButton("Load Species Workbook (WAM)")
        self.btn_load_workbook.clicked.connect(self.load_species_workbook)
        self.btn_load_common = QPushButton("Load Common Species List")
        self.btn_load_common.clicked.connect(self.load_common_species)
        self.btn_set_output = QPushButton("Set Output File")
        self.btn_set_output.clicked.connect(self.set_output_file)
        self.btn_refresh_output = QPushButton("Refresh Output")
        self.btn_refresh_output.setToolTip("Re-save the output file from memory")
        self.btn_refresh_output.clicked.connect(self._refresh_output)

        self.lbl_camera_id = QLabel("Site ID: --")
        self.lbl_camera_id.setObjectName("lbl_camera_id")
        self.lbl_db_status = QLabel("Species DB: Not loaded")
        self.lbl_db_status.setObjectName("lbl_db_status")

        setup_lay.addWidget(self.btn_load_folder)
        setup_lay.addWidget(self.btn_load_workbook)
        setup_lay.addWidget(self.btn_load_common)
        setup_lay.addWidget(self.btn_set_output)
        setup_lay.addWidget(self.btn_refresh_output)
        setup_lay.addWidget(self.lbl_camera_id)
        setup_lay.addWidget(self.lbl_db_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        setup_lay.addWidget(self.progress_bar)
        right_layout.addWidget(setup_group)

        # --- Species Search ---
        search_group = QGroupBox("Species Search (Ctrl+F)")
        search_lay = QVBoxLayout(search_group)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type species name...")
        self.search_input.textChanged.connect(self._on_search)
        search_lay.addWidget(self.search_input)

        self.search_results = QListWidget()
        self.search_results.setMaximumHeight(180)
        self.search_results.itemDoubleClicked.connect(self._on_search_result_double_clicked)
        search_lay.addWidget(self.search_results)

        search_btn_row = QHBoxLayout()
        self.btn_add_quick = QPushButton("+ Add to Quick ID")
        self.btn_add_quick.setToolTip("Add the selected search result as a Quick Species button")
        self.btn_add_quick.clicked.connect(self._add_quick_from_search)
        search_btn_row.addWidget(self.btn_add_quick)
        search_btn_row.addStretch()
        search_lay.addLayout(search_btn_row)

        right_layout.addWidget(search_group)

        # --- Individuals ---
        multi_group = QGroupBox("Individuals")
        multi_lay = QVBoxLayout(multi_group)

        # Row 1: Multi Individuals (same sp.) -- Entry + Go
        same_sp_row = QHBoxLayout()
        same_sp_label = QLabel("Multi Individuals (same sp.):")
        same_sp_label.setToolTip(
            "Enter count, then click Go to create one row per individual\n"
            "using the currently assigned species."
        )
        self.spin_count = QLineEdit("0")
        self.spin_count.setFixedWidth(44)
        self.spin_count.setToolTip("Number of individuals (same species) in this photo")
        self.spin_count.textChanged.connect(self._validate_multi_count)
        self.btn_multi_same_go = QPushButton("Go")
        self.btn_multi_same_go.setObjectName("btn_multi_same_go")
        self.btn_multi_same_go.setFixedWidth(50)
        self.btn_multi_same_go.setEnabled(False)
        self.btn_multi_same_go.setToolTip(
            "Create one CSV row per individual for the current species"
        )
        self.btn_multi_same_go.clicked.connect(self._on_multi_same_go)
        same_sp_row.addWidget(same_sp_label)
        same_sp_row.addWidget(self.spin_count)
        same_sp_row.addWidget(self.btn_multi_same_go)
        same_sp_row.addStretch()
        multi_lay.addLayout(same_sp_row)

        # Row 2: Same individual + Multi ID (diff sp.)
        indiv_row = QHBoxLayout()
        self.btn_same_individual = QPushButton("Same individual (as prev. pic)")
        self.btn_same_individual.setObjectName("btn_same_individual")
        self.btn_same_individual.setToolTip(
            "This photo shows the same individual as the last assignment.\n"
            "Increments PhotoCount on the previous row instead of creating a new row."
        )
        self.btn_same_individual.setEnabled(False)
        self.btn_same_individual.clicked.connect(self._on_same_individual)
        indiv_row.addWidget(self.btn_same_individual)

        self.btn_multi_id = QPushButton("Multi Individuals (diff. sp.)")
        self.btn_multi_id.setObjectName("btn_multi_id")
        self.btn_multi_id.setCheckable(True)
        self.btn_multi_id.setToolTip(
            "Click photo to place markers, then click species to assign.\n"
            "Press Done when finished."
        )
        self.btn_multi_id.toggled.connect(self._toggle_multi_id)
        indiv_row.addWidget(self.btn_multi_id)
        indiv_row.addStretch()
        multi_lay.addLayout(indiv_row)

        # Row 2b: Done + Undo for multi-ID
        mid_btn_row = QHBoxLayout()
        self.btn_multi_id_done = QPushButton("Done \u2713")
        self.btn_multi_id_done.setObjectName("btn_multi_same_go")
        self.btn_multi_id_done.setToolTip("Write one row per detection and advance")
        self.btn_multi_id_done.setEnabled(False)
        self.btn_multi_id_done.clicked.connect(self._multi_id_done)
        self.btn_multi_id_undo = QPushButton("Undo Marker")
        self.btn_multi_id_undo.setToolTip("Remove last detection or pending marker")
        self.btn_multi_id_undo.setEnabled(False)
        self.btn_multi_id_undo.clicked.connect(self._undo_last_marker)
        mid_btn_row.addWidget(self.btn_multi_id_done)
        mid_btn_row.addWidget(self.btn_multi_id_undo)
        mid_btn_row.addStretch()
        multi_lay.addLayout(mid_btn_row)

        # Row 3: Unknown ID (moved here from Actions)
        self.btn_unknown = QPushButton("Unknown ID (Space)")
        self.btn_unknown.setObjectName("btn_unknown_id")
        self.btn_unknown.setToolTip("Mark this photo as unidentifiable")
        self.btn_unknown.clicked.connect(self.mark_unknown)
        multi_lay.addWidget(self.btn_unknown)

        # Row 4: Clip NQ + Clip Chuditch
        clip_row = QHBoxLayout()
        self.btn_clip_nq = QPushButton("Clip NQ")
        self.btn_clip_nq.setObjectName("btn_clip_quoll")
        self.btn_clip_nq.setToolTip(
            "Assign 'Northern Quoll' and clip.\n"
            "4 clicks: left, right, top, bottom."
        )
        self.btn_clip_nq.clicked.connect(lambda: self._start_clip("NQ"))
        clip_row.addWidget(self.btn_clip_nq)

        self.btn_clip_chuditch = QPushButton("Clip Chuditch")
        self.btn_clip_chuditch.setObjectName("btn_clip_quoll")
        self.btn_clip_chuditch.setToolTip(
            "Assign 'Chuditch' (Western Quoll) and clip.\n"
            "4 clicks: left, right, top, bottom."
        )
        self.btn_clip_chuditch.clicked.connect(lambda: self._start_clip("Chuditch"))
        clip_row.addWidget(self.btn_clip_chuditch)
        multi_lay.addLayout(clip_row)

        right_layout.addWidget(multi_group)

        # --- Quick Species (16 buttons, 2 columns of 8) ---
        top20_group = QGroupBox("Quick Species (1-0, F1-F6)")
        top20_inner = QVBoxLayout(top20_group)
        self.top20_layout = QGridLayout()
        self.top20_layout.setSpacing(3)
        top20_inner.addLayout(self.top20_layout)
        self.top20_buttons: List[QPushButton] = []
        self._top20_remove_btns: List[QPushButton] = []
        self.lbl_top20_empty = QLabel("Load common species xlsx or add from search")
        self.lbl_top20_empty.setObjectName("lbl_hint")
        self.top20_layout.addWidget(self.lbl_top20_empty, 0, 0, 1, 4)
        right_layout.addWidget(top20_group)

        # --- Actions (above Default Fields) ---
        actions_group = QGroupBox("Actions")
        actions_lay = QVBoxLayout(actions_group)

        undo_row = QHBoxLayout()
        self.btn_undo_last = QPushButton("Undo Last")
        self.btn_undo_last.setToolTip("Undo the most recent assignment (Ctrl+Z)")
        self.btn_undo_last.clicked.connect(self.undo_last)
        self.undo_n_input = QLineEdit()
        self.undo_n_input.setFixedWidth(40)
        self.undo_n_input.setPlaceholderText("#")
        self.undo_n_input.setToolTip("Enter number then click to undo that many")
        self.btn_undo_n = QPushButton("Undo N")
        self.btn_undo_n.setToolTip("Undo the number of assignments entered in the box")
        self.btn_undo_n.clicked.connect(self._undo_n)
        self.btn_undo_all = QPushButton("Undo All")
        self.btn_undo_all.setToolTip("Undo ALL assignments in this session")
        self.btn_undo_all.clicked.connect(self._undo_all)
        undo_row.addWidget(self.btn_undo_last)
        undo_row.addWidget(self.undo_n_input)
        undo_row.addWidget(self.btn_undo_n)
        undo_row.addWidget(self.btn_undo_all)

        self.btn_fit = QPushButton("Fit Image (F)")
        self.btn_fit.clicked.connect(self.image_viewer.fit_image)

        subfolder_row = QHBoxLayout()
        self.btn_prev_subfolder = QPushButton("Prev Folder")
        self.btn_prev_subfolder.clicked.connect(self._prev_subfolder)
        self.btn_next_subfolder = QPushButton("Next Folder")
        self.btn_next_subfolder.clicked.connect(self._next_subfolder)
        self.lbl_subfolder = QLabel("")
        self.lbl_subfolder.setAlignment(Qt.AlignCenter)
        subfolder_row.addWidget(self.btn_prev_subfolder)
        subfolder_row.addWidget(self.lbl_subfolder, 1)
        subfolder_row.addWidget(self.btn_next_subfolder)

        actions_lay.addLayout(undo_row)
        actions_lay.addWidget(self.btn_fit)
        actions_lay.addLayout(subfolder_row)
        right_layout.addWidget(actions_group)

        # --- Default Fields ---
        fields_group = QGroupBox("Default Fields")
        fields_lay = QFormLayout(fields_group)
        fields_lay.setLabelAlignment(Qt.AlignRight)

        self.field_site = QLineEdit()
        self.field_site.setReadOnly(True)
        self.field_site.setPlaceholderText("(auto from site folder)")
        self.field_site.setToolTip("Site ID -- first component of relative path (e.g. VABY-001)")
        self.field_site.setObjectName("field_site_ro")
        self.field_camera_id = QLineEdit()
        self.field_camera_id.setReadOnly(True)
        self.field_camera_id.setPlaceholderText("(auto from camera folder)")
        self.field_camera_id.setToolTip("Camera ID -- camera folder under site (e.g. 4-1)")
        self.field_camera_id.setObjectName("field_site_ro")
        self.field_obs_method = NoScrollComboBox()
        self.field_obs_method.setEditable(True)
        self.field_obs_method.setFocusPolicy(Qt.StrongFocus)
        self.field_obs_method.addItems(["", "Camera Trap", "Visual", "Acoustic",
                                         "Pitfall Trap", "Funnel Trap", "Elliott Trap",
                                         "Cage Trap", "Hand Capture", "Other"])
        self.field_record_type = NoScrollComboBox()
        self.field_record_type.setEditable(True)
        self.field_record_type.setFocusPolicy(Qt.StrongFocus)
        self.field_record_type.addItems([
            "Individual (alive)",
            "Individual (dead)",
            "Burrow (active)",
            "Burrow (inactive)",
            "Digging",
            "Foraging Evidence",
            "Mound (active)",
            "Mound (recently inactive)",
            "Nest",
            "Scat",
            "Track",
            "Other",
        ])
        self.field_fauna_type = NoScrollComboBox()
        self.field_fauna_type.setEditable(True)
        self.field_fauna_type.setFocusPolicy(Qt.StrongFocus)
        self.field_fauna_type.addItems([
            "Terrestrial vertebrate fauna",
            "Terrestrial invertebrate fauna",
            "Subterranean fauna",
            "Aquatic fauna",
            "Other",
        ])
        # Default: Terrestrial vertebrate fauna (index 0)
        self.field_fauna_type.setCurrentIndex(0)

        self.field_author = QLineEdit()
        self.field_citation = QLineEdit()

        fields_lay.addRow("Site ID:", self.field_site)
        fields_lay.addRow("Camera ID:", self.field_camera_id)
        fields_lay.addRow("ObsMethod:", self.field_obs_method)
        fields_lay.addRow("RecordType:", self.field_record_type)
        fields_lay.addRow("FaunaType:", self.field_fauna_type)
        fields_lay.addRow("Author:", self.field_author)
        fields_lay.addRow("Citation:", self.field_citation)
        right_layout.addWidget(fields_group)

        # --- Notes ---
        notes_group = QGroupBox("Notes > Comments")
        notes_lay = QVBoxLayout(notes_group)
        self.notes_input = QTextEdit()
        self.notes_input.setMaximumHeight(60)
        self.notes_input.setPlaceholderText("Additional comments for this photo...")
        notes_lay.addWidget(self.notes_input)
        right_layout.addWidget(notes_group)

        # --- Options ---
        opts_group = QGroupBox("Options")
        opts_lay = QVBoxLayout(opts_group)
        self.chk_scrub = QCheckBox("Scrub metadata (create clean copies)")
        self.chk_scrub.setChecked(True)
        self.chk_scrub.toggled.connect(lambda v: setattr(self, 'scrub_enabled', v))
        self.chk_overwrite = QCheckBox("WARNING: Overwrite originals (dangerous)")
        self.chk_overwrite.toggled.connect(self._toggle_overwrite)
        opts_lay.addWidget(self.chk_scrub)
        opts_lay.addWidget(self.chk_overwrite)
        right_layout.addWidget(opts_group)

        right_layout.addStretch()
        right_scroll.setWidget(right_widget)
        splitter.addWidget(right_scroll)
        splitter.setSizes([1000, 400])

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready -- Load a photo folder and species workbook to begin")

        self._setup_menu()

    # ------------------------------------------------------------------
    # Menu bar
    # ------------------------------------------------------------------

    def _setup_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")

        act_folder = QAction("Open Photo &Folder...", self)
        act_folder.setShortcut("Ctrl+O")
        act_folder.triggered.connect(self.load_photo_folder)
        file_menu.addAction(act_folder)

        act_wb = QAction("Load Species &Workbook (WAM)...", self)
        act_wb.triggered.connect(self.load_species_workbook)
        file_menu.addAction(act_wb)

        act_common = QAction("Load &Common Species List...", self)
        act_common.triggered.connect(self.load_common_species)
        file_menu.addAction(act_common)

        act_output = QAction("Set &Output File...", self)
        act_output.triggered.connect(self.set_output_file)
        file_menu.addAction(act_output)

        file_menu.addSeparator()

        act_quit = QAction("&Quit", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        help_menu = menubar.addMenu("&Help")
        act_about = QAction("&About", self)
        act_about.triggered.connect(lambda: QMessageBox.about(
            self, "About", f"{APP_NAME} v{APP_VERSION}\n\nRapid species ID from bulk photos."
        ))
        help_menu.addAction(act_about)

    # ------------------------------------------------------------------
    # Shortcuts
    # ------------------------------------------------------------------

    def _setup_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key_Left), self, self.go_prev)
        QShortcut(QKeySequence(Qt.Key_Right), self, self.go_next)
        QShortcut(QKeySequence("Ctrl+F"), self, lambda: self.search_input.setFocus())
        QShortcut(QKeySequence("Ctrl+Z"), self, self.undo_last)

        # F1-F6 for quick species 11-16
        for i in range(6):
            QShortcut(QKeySequence(f"F{i+1}"), self, partial(self._trigger_top20, 10 + i))

    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            return
        focused = QApplication.focusWidget()
        text_widget_focused = isinstance(focused, (QLineEdit, QTextEdit, QComboBox))
        key = event.key()

        if not text_widget_focused:
            if Qt.Key_1 <= key <= Qt.Key_9:
                self._trigger_top20(key - Qt.Key_1)
                return
            if key == Qt.Key_0:
                self._trigger_top20(9)
                return
            if key == Qt.Key_Space:
                self.mark_unknown()
                return
            if key == Qt.Key_F:
                self.image_viewer.fit_image()
                return

        if key in (Qt.Key_Return, Qt.Key_Enter):
            if self.search_results.hasFocus() or (
                    focused == self.search_input and self.search_results.count() > 0):
                self._assign_search_selection()
                return

        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Data Loading
    # ------------------------------------------------------------------

    @safe_slot
    def load_photo_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Photo Folder")
        if not folder:
            return
        self.photo_folder = folder
        self.lbl_camera_id.setText("Site ID: (per subfolder)")

        # Always set output path inside the loaded folder
        self.output_path = os.path.join(folder, "species_output.csv")
        self.scrub_output_root = os.path.join(folder, "scrubbed")

        # Check if there's an existing CSV with previous assignments
        existing_csv = os.path.exists(self.output_path)
        resume = False
        if existing_csv:
            reply = QMessageBox.question(
                self, "Existing Output Found",
                f"Found existing species_output.csv in this folder.\n\n"
                f"Resume previous assignments, or start fresh?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            resume = (reply == QMessageBox.Yes)
            if not resume:
                # Delete the old CSV to start fresh
                try:
                    os.remove(self.output_path)
                except OSError:
                    pass

        # Always create a fresh exporter (loads CSV if resume, empty if fresh)
        self.exporter = Exporter(self.output_path)
        self._sequence_counter = self.exporter.total_rows
        self._meta_cache.clear()
        self._processed_count = 0

        from .constants import SUPPORTED_EXTENSIONS
        from .image_indexer import _natural_sort_key, SKIP_FOLDERS

        self.status_bar.showMessage(f"Scanning subfolders in {folder}...")
        QApplication.processEvents()

        # Walk the tree and group by camera-level folder (2nd-level dir).
        # Structure: {photo_folder}/{site}/{camera}/[nested/]photo.jpg
        # Photos in root or 1st-level dirs are handled as their own group.
        camera_set = set()
        camera_folders = []

        for root, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if d.lower() not in SKIP_FOLDERS)
            has_images = any(
                os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
                for f in files
            )
            if not has_images:
                continue

            rel = os.path.relpath(root, folder)
            parts = rel.replace("\\", "/").split("/") if rel != "." else []
            depth = len(parts)

            if depth >= 2:
                # Camera-level folder = first two path components
                cam_path = os.path.join(folder, parts[0], parts[1])
            else:
                # Photos in root (depth=0) or site-level (depth=1)
                cam_path = root

            if cam_path not in camera_set:
                camera_set.add(cam_path)
                camera_folders.append(cam_path)

        camera_folders.sort(key=lambda p: _natural_sort_key(os.path.relpath(p, folder)))

        if not camera_folders:
            self._subfolder_list = [folder]
        else:
            self._subfolder_list = camera_folders

        self._subfolder_index = 0
        self._load_current_subfolder()

    def _load_current_subfolder(self):
        if not self._subfolder_list or self._subfolder_index < 0:
            return

        idx = self._subfolder_index
        subfolder = self._subfolder_list[idx]
        total_folders = len(self._subfolder_list)
        rel = os.path.relpath(subfolder, self.photo_folder)

        self.lbl_subfolder.setText(f"Folder {idx + 1}/{total_folders}: {rel}")
        self.status_bar.showMessage(f"Loading {rel}...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        QApplication.processEvents()

        self._meta_cache.clear()

        try:
            from .constants import SUPPORTED_EXTENSIONS
            from .image_indexer import PhotoItem as _PI, generate_photo_id, SKIP_FOLDERS
            import os as _os

            # --- Pass 1: fast path collection (no stat) ---
            self.status_bar.showMessage(f"Scanning {rel}...")
            QApplication.processEvents()
            path_list = []  # (full_path, filename, rel_path)
            for root, dirs, files in _os.walk(subfolder):
                dirs[:] = sorted(d for d in dirs if d.lower() not in SKIP_FOLDERS)
                for fname in files:
                    ext = _os.path.splitext(fname)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        full_path = _os.path.join(root, fname)
                        rel_path = _os.path.relpath(full_path, self.photo_folder)
                        path_list.append((full_path, fname, rel_path))

            total = len(path_list)
            if total == 0:
                self._on_index_done([])
                return

            self.progress_bar.setMaximum(total)
            self.status_bar.showMessage(
                f"Found {total} photos in {rel} — indexing..."
            )
            QApplication.processEvents()

            # --- Pass 2: stat + PhotoItem creation in batches ---
            BATCH = 500  # large batches for 10000+ photo folders
            all_files = []
            for i, (full_path, fname, rel_path) in enumerate(path_list):
                try:
                    st = _os.stat(full_path)
                    all_files.append((fname, full_path, rel_path, st))
                except OSError:
                    pass
                if (i + 1) % BATCH == 0:
                    self.progress_bar.setValue(i + 1)
                    QApplication.processEvents()

            self.progress_bar.setValue(total)
            QApplication.processEvents()

            all_files.sort(key=lambda x: (x[3].st_mtime, x[0].lower()))

            photos = []
            total2 = len(all_files)
            for i, (fname, full_path, rel_path, st) in enumerate(all_files):
                pid = generate_photo_id(rel_path, fname, st.st_size, st.st_mtime)
                photos.append(PhotoItem(
                    full_path=full_path, filename=fname,
                    relative_path=rel_path, photo_id=pid,
                ))
                if (i + 1) % BATCH == 0:
                    self.progress_bar.setValue(i + 1)
                    QApplication.processEvents()

            self._on_index_done(photos)

        except Exception as e:
            self.progress_bar.setVisible(False)
            QMessageBox.critical(self, "Indexing Error",
                f"Failed to scan photos in:\n{subfolder}\n\n{e}")

    @safe_slot
    def _next_subfolder(self):
        if not self._subfolder_list:
            self.status_bar.showMessage("No folder loaded")
            return
        if self._subfolder_index >= len(self._subfolder_list) - 1:
            self.status_bar.showMessage("Already at last subfolder")
            return
        self._subfolder_index += 1
        self._load_current_subfolder()

    @safe_slot
    def _prev_subfolder(self):
        if not self._subfolder_list:
            self.status_bar.showMessage("No folder loaded")
            return
        if self._subfolder_index <= 0:
            self.status_bar.showMessage("Already at first subfolder")
            return
        self._subfolder_index -= 1
        self._load_current_subfolder()

    def _ensure_exporter(self):
        if self.exporter is None and self.output_path:
            try:
                self.exporter = Exporter(self.output_path)
            except Exception as e:
                QMessageBox.critical(self, "Output File Error",
                    f"Cannot create/open output file:\n{self.output_path}\n\n{e}")

    @safe_slot
    def _on_index_done(self, photos):
        if not isinstance(photos, list):
            print(f"WARNING: _on_index_done received {type(photos)} instead of list",
                  file=sys.stderr)
            photos = []

        self.photos = photos
        self.progress_bar.setVisible(False)

        if not photos:
            self.status_bar.showMessage(
                f"No photos found in {self.photo_folder}  "
                f"(supported: .jpg .jpeg .png .tif .tiff)"
            )
            self.lbl_progress.setText("No photos found")
            return

        self._ensure_exporter()

        if self.exporter:
            processed_ids = self.exporter.get_processed_ids()
            self._sequence_counter = self.exporter.total_rows
            for p in self.photos:
                if p.photo_id in processed_ids:
                    p.processed = True
                    row = self.exporter.get_row(p.photo_id)
                    if row:
                        p.taxon_name = row.get("TaxonName", "")
                        p.common_name = row.get("CommonName", "")
            self._update_top20()

        self._processed_count = sum(1 for p in self.photos if p.processed)
        self.current_index = 0
        self._last_shown_index = -1
        if self.show_unprocessed_only:
            self._find_next_unprocessed()
        self._show_current_photo()

        # Notify user about existing assignments from CSV
        if self._processed_count > 0:
            self.status_bar.showMessage(
                f"Resumed: {self._processed_count} previously assigned photos found in output CSV. "
                f"Use Undo All to start fresh."
            )

        # Reset same-individual state
        self._last_assigned_photo_id = None
        self._same_individual_count = 0
        self.btn_same_individual.setEnabled(False)

        if self._subfolder_list:
            idx = self._subfolder_index
            rel = os.path.relpath(self._subfolder_list[idx], self.photo_folder)
            self.status_bar.showMessage(
                f"Loaded {len(self.photos)} photos from {rel} "
                f"(folder {idx + 1}/{len(self._subfolder_list)})"
            )
        else:
            self.status_bar.showMessage(
                f"Loaded {len(self.photos)} photos from {self.photo_folder}"
            )

    @Slot(str)
    @safe_slot
    def load_species_workbook(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select WAM Species List or IBSA Workbook", "",
            "Excel Files (*.xlsx *.xlsm);;All Files (*)"
        )
        if not path:
            return
        self.status_bar.showMessage("Loading species workbook...")
        ok, msg = self.species_db.load_from_workbook(path)
        if ok:
            self.lbl_db_status.setText(f"Species DB: {self.species_db.count} species loaded")
            self.lbl_db_status.setStyleSheet("color: #4caf50;")
            self.status_bar.showMessage(msg)
            self._update_top20()
        else:
            self.lbl_db_status.setText("Species DB: Error")
            self.lbl_db_status.setStyleSheet("color: #ff6b6b;")
            QMessageBox.warning(self, "Species Load Warning",
                                f"{msg}\n\nYou can still use manual entry.")
            self.status_bar.showMessage("Species workbook load failed -- manual entry mode")

    @safe_slot
    def load_common_species(self):
        if not self.species_db.loaded:
            QMessageBox.information(
                self, "Load WAM First",
                "Load the WAM species workbook first, then load the common species list.\n\n"
                "The common species names need to be matched against the WAM database."
            )
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Common Species List", "",
            "Excel Files (*.xlsx *.xlsm);;All Files (*)"
        )
        if not path:
            return
        species_list, msg = self.species_db.load_common_species_file(path)
        if species_list:
            self.top20_species = species_list[:16]
            self._rebuild_top20_buttons()
            self.status_bar.showMessage(f"Common species loaded: {msg}")
        else:
            QMessageBox.warning(self, "Common Species", f"Could not load:\n{msg}")

    @safe_slot
    def set_output_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Set Output CSV File", self.output_path or "species_output.csv",
            "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        if not path.endswith(".csv"):
            path += ".csv"
        self.output_path = path
        self.scrub_output_root = os.path.join(os.path.dirname(path), "scrubbed")
        self.exporter = Exporter(path)

        if self.photos:
            processed_ids = self.exporter.get_processed_ids()
            self._sequence_counter = self.exporter.total_rows
            for p in self.photos:
                if p.photo_id in processed_ids:
                    p.processed = True
                    row = self.exporter.get_row(p.photo_id)
                    if row:
                        p.taxon_name = row.get("TaxonName", "")
                        p.common_name = row.get("CommonName", "")
            self._update_top20()
            self._processed_count = sum(1 for p in self.photos if p.processed)
            self._show_current_photo()
        self.status_bar.showMessage(f"Output: {path}")

    # ------------------------------------------------------------------
    # Per-photo state reset
    # ------------------------------------------------------------------

    def _reset_per_photo_state(self):
        if self._multi_id_active:
            self._multi_id_active = False
            self._multi_id_count = 0
            self.btn_multi_id.blockSignals(True)
            self.btn_multi_id.setChecked(False)
            self.btn_multi_id.blockSignals(False)
        self._multi_id_detections.clear()
        self._multi_id_pending_point = None
        self.btn_multi_id_done.setEnabled(False)
        self.btn_multi_id_undo.setEnabled(False)
        self.image_viewer.clear_detections()
        if self._quoll_clip_active:
            self._quoll_clip_active = False
            self._quoll_clip_points.clear()
            self.image_viewer.click_mode = False
            self.image_viewer.clear_overlay()
        self.spin_count.setText("0")
        self.notes_input.clear()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _get_visible_indices(self) -> List[int]:
        if self.show_unprocessed_only:
            return [i for i, p in enumerate(self.photos) if not p.processed]
        return list(range(len(self.photos)))

    def go_prev(self):
        if not self.photos:
            return
        visible = self._get_visible_indices()
        if not visible:
            return
        try:
            pos = visible.index(self.current_index)
            if pos > 0:
                self.current_index = visible[pos - 1]
        except ValueError:
            before = [i for i in visible if i < self.current_index]
            if before:
                self.current_index = before[-1]
            elif visible:
                self.current_index = visible[0]
        self._show_current_photo()

    def go_next(self):
        if not self.photos:
            return
        visible = self._get_visible_indices()
        if not visible:
            if self._subfolder_list and self._subfolder_index < len(self._subfolder_list) - 1:
                self._next_subfolder()
            return
        try:
            pos = visible.index(self.current_index)
            if pos < len(visible) - 1:
                self.current_index = visible[pos + 1]
            elif self._subfolder_list and self._subfolder_index < len(self._subfolder_list) - 1:
                self._next_subfolder()
                return
        except ValueError:
            after = [i for i in visible if i > self.current_index]
            if after:
                self.current_index = after[0]
            elif visible:
                self.current_index = visible[-1]
        self._show_current_photo()

    def _find_next_unprocessed(self):
        for i in range(self.current_index, len(self.photos)):
            if not self.photos[i].processed:
                self.current_index = i
                return
        for i in range(0, self.current_index):
            if not self.photos[i].processed:
                self.current_index = i
                return

    def _toggle_filter(self, checked):
        self.show_unprocessed_only = checked
        if checked:
            self._find_next_unprocessed()
        self._show_current_photo()

    def _show_current_photo(self):
        if not self.photos:
            self.lbl_progress.setText("No photos loaded")
            self.lbl_assignment.setText("")
            self.lbl_filename.setText("")
            return

        if self.current_index >= len(self.photos):
            self.current_index = len(self.photos) - 1
        if self.current_index < 0:
            self.current_index = 0

        # Reset per-photo state on photo change
        if self.current_index != self._last_shown_index:
            self._reset_per_photo_state()
            self._last_shown_index = self.current_index

        photo = self.photos[self.current_index]
        self.image_viewer.load_image(photo.full_path)

        processed = self._processed_count
        total = len(self.photos)
        visible = self._get_visible_indices()
        try:
            vis_pos = visible.index(self.current_index) + 1
        except ValueError:
            vis_pos = self.current_index + 1
        vis_total = len(visible)

        self.lbl_progress.setText(
            f"Photo {vis_pos} of {vis_total} (processed {processed} of {total})"
        )

        if photo.processed:
            if photo.taxon_name:
                self.lbl_assignment.setText(
                    f"Done: {photo.taxon_name}"
                    + (f" ({photo.common_name})" if photo.common_name else "")
                )
                self.lbl_assignment.setStyleSheet(
                    "font-size: 11pt; font-weight: bold; padding: 6px; "
                    "background: #1b4332; border-radius: 4px; color: #95d5b2;"
                )
            else:
                self.lbl_assignment.setText("Done: Unknown ID")
                self.lbl_assignment.setStyleSheet(
                    "font-size: 11pt; font-weight: bold; padding: 6px; "
                    "background: #5a3a00; border-radius: 4px; color: #ffd166;"
                )
        else:
            self.lbl_assignment.setText("Not yet assigned")
            self.lbl_assignment.setStyleSheet(
                "font-size: 11pt; font-weight: bold; padding: 6px; "
                "background: #0f3460; border-radius: 4px; color: #a0c4ff;"
            )

        self.lbl_filename.setText(photo.relative_path)
        camera_id = self._get_camera_id(photo)
        site_id = self._get_site_id(photo)
        self.field_site.setText(site_id)
        self.field_camera_id.setText(camera_id)

        # Deferred prefetch: don't block current frame
        def _pf():
            for off in [1, 2, 3, 4, 5, -1, -2]:
                idx = self.current_index + off
                if 0 <= idx < len(self.photos):
                    self.image_viewer.prefetch(self.photos[idx].full_path)
        QTimer.singleShot(5, _pf)

    # ------------------------------------------------------------------
    # Species Assignment
    # ------------------------------------------------------------------

    def _get_camera_id(self, photo) -> str:
        """Extract Camera ID from the photo's relative path.

        Structure: {site}/{camera}/[nested/]photo.jpg
        Camera ID = second path component.  Falls back to first component
        when there are only two levels (camera/photo.jpg).
        """
        parts = photo.relative_path.replace("\\", "/").split("/")
        if len(parts) >= 3:
            return parts[1]  # site/camera/.../photo
        elif len(parts) == 2:
            return parts[0]  # camera/photo (no site level)
        return ""

    def _get_site_id(self, photo) -> str:
        """Extract Site ID from the photo's relative path.

        Structure: {site}/{camera}/[nested/]photo.jpg
        Site ID = first path component when at least 3 levels exist.
        """
        parts = photo.relative_path.replace("\\", "/").split("/")
        if len(parts) >= 3:
            return parts[0]  # site/camera/.../photo
        return ""

    @safe_slot
    def _on_search(self, text):
        self.search_results.clear()
        self._search_results_list = []
        if not text or len(text) < 2:
            return
        if not self.species_db.loaded:
            return
        results = self.species_db.search(text, max_results=20)
        self._search_results_list = results
        for sp in results:
            self.search_results.addItem(sp.display_text())
        if results:
            self.search_results.setCurrentRow(0)

    @safe_slot
    def _on_search_result_double_clicked(self, item: QListWidgetItem):
        row = self.search_results.row(item)
        if 0 <= row < len(self._search_results_list):
            self.assign_species(self._search_results_list[row])

    @safe_slot
    def _assign_search_selection(self):
        row = self.search_results.currentRow()
        if 0 <= row < len(self._search_results_list):
            self.assign_species(self._search_results_list[row])

    @safe_slot
    def _add_quick_from_search(self):
        """Add selected search result to the Quick Species grid."""
        row = self.search_results.currentRow()
        if row < 0 or row >= len(self._search_results_list):
            self.status_bar.showMessage("Select a species from the search results first")
            return
        species = self._search_results_list[row]
        for sp in self.top20_species:
            if sp.taxon_name == species.taxon_name:
                self.status_bar.showMessage(f"{species.taxon_name} is already a Quick Species button")
                return
        if len(self.top20_species) >= 16:
            self.status_bar.showMessage("Maximum 16 Quick Species buttons -- remove one first")
            return
        self.top20_species.append(species)
        self._rebuild_top20_buttons()
        self.status_bar.showMessage(f"Added Quick Species: {species.display_text()}")

    @safe_slot
    def _remove_quick_species(self, index: int):
        """Remove a species from the quick-assign grid."""
        if 0 <= index < len(self.top20_species):
            removed = self.top20_species.pop(index)
            self._rebuild_top20_buttons()
            self.status_bar.showMessage(f"Removed Quick Species: {removed.display_text()}")

    @safe_slot
    def _trigger_top20(self, index: int):
        if 0 <= index < len(self.top20_species):
            self.assign_species(self.top20_species[index])

    @safe_slot
    def assign_species(self, species: SpeciesRecord):
        """Assign a species to the current photo."""
        if self._assigning:
            return
        self._assigning = True
        try:
            self._do_assign_species(species)
        finally:
            self._assigning = False

    def _do_assign_species(self, species: SpeciesRecord):
        self._ensure_exporter()

        if not self.photos:
            QMessageBox.warning(self, "Not Ready", "Load a photo folder first.")
            return
        if not self.exporter:
            QMessageBox.warning(self, "Not Ready",
                "No output file set.\n\nClick 'Set Output File' or reload the photo folder.")
            return

        # --- Multi-ID click-to-place: consume pending marker ---
        if self._multi_id_active:
            if self._multi_id_pending_point is None:
                self.status_bar.showMessage(
                    "Click the photo first to place a marker, then click a species."
                )
                return
            self._multi_id_detections.append(
                (self._multi_id_pending_point, species)
            )
            self._multi_id_pending_point = None
            self._refresh_detection_overlay()
            n = len(self._multi_id_detections)
            self.btn_multi_id_done.setEnabled(True)
            self.btn_multi_id_undo.setEnabled(True)
            self.lbl_assignment.setText(
                f"Multi ID: {n} detection{'s' if n != 1 else ''} — "
                f"last: {species.display_text()}"
            )
            self.lbl_assignment.setStyleSheet(
                "font-size: 11pt; font-weight: bold; padding: 6px; "
                "background: #5a3a00; border-radius: 4px; color: #ffd166;"
            )
            self.status_bar.showMessage(
                f"Detection #{n}: {species.display_text()} — "
                f"click photo for next, or press Done"
            )
            return

        photo = self.photos[self.current_index]

        meta = self._meta_cache.get(photo.photo_id)
        if meta is None:
            try:
                meta = extract_metadata(photo.full_path)
            except Exception:
                meta = PhotoMetadata()
            self._meta_cache[photo.photo_id] = meta

        camera_id = self._get_camera_id(photo)
        site_id = self._get_site_id(photo)
        self._sequence_counter += 1

        # Column AC: standardised identifier
        col_ac = build_column_ac(
            site_name=camera_id,
            filename=photo.filename,
            date_obs=meta.date_obs,
            time_str=meta.time_str,
            sequence=self._sequence_counter,
        )

        # Abundance: default 0, overridden by Multi Individuals (same sp.) field
        abundance = "0"
        try:
            n = int(self.spin_count.text())
            if n > 0:
                abundance = str(n)
        except (ValueError, TypeError):
            pass

        row_id = photo.photo_id

        row = {col: "" for col in OUTPUT_COLUMNS}
        row["ID"] = row_id
        row["DateObs"] = meta.date_obs
        if meta.latitude is not None:
            row["Latitude"] = meta.latitude
        if meta.longitude is not None:
            row["Longitude"] = meta.longitude
        _user_notes = self.notes_input.toPlainText().strip()
        row["Comments"] = (col_ac + "; " + _user_notes) if _user_notes else col_ac
        row["Abundance"] = abundance
        row["PhotoCount"] = "1"
        row["Time"] = format_time_hmm(meta.time_str) or extract_time_from_col_ac(col_ac)
        row.update(species.to_output_fields())
        row["SiteName"] = site_id
        row["CameraID"] = camera_id
        row["ObsMethod"] = self.field_obs_method.currentText()
        row["RecordType"] = self.field_record_type.currentText()
        row["FaunaType"] = self.field_fauna_type.currentText()
        row["Author"] = self.field_author.text()
        row["Citation"] = self.field_citation.text()

        self.exporter.write_row(row_id, row)

        if self.scrub_enabled and not photo.processed:
            self._queue_scrub(photo, species_name=species.common_name)

        self._processed_count += (not photo.processed)
        photo.processed = True
        photo.taxon_name = species.taxon_name
        photo.common_name = species.common_name
        photo.row_data = row
        self.notes_input.clear()

        # Enable "Same Individual" for subsequent photos
        self._last_assigned_photo_id = photo.photo_id
        self._same_individual_count = 0
        self.btn_same_individual.setEnabled(True)

        # Show confirmation ribbon on the current photo BEFORE advancing
        self.lbl_assignment.setText(
            f"Done: {species.taxon_name}"
            + (f" ({species.common_name})" if species.common_name else "")
        )
        self.lbl_assignment.setStyleSheet(
            "font-size: 11pt; font-weight: bold; padding: 6px; "
            "background: #1b4332; border-radius: 4px; color: #95d5b2;"
        )
        self.status_bar.showMessage(
            f"Done: Assigned: {species.display_text()} > {photo.filename}"
        )
        self.go_next()

    @safe_slot
    def _on_same_individual(self):
        """Current photo is the same individual as the last assignment.

        Increments PhotoCount on the previous row; does NOT create a new
        output row.  Marks the current photo processed and advances.
        """
        if not self._last_assigned_photo_id or not self.exporter:
            self.status_bar.showMessage("No previous assignment to link to")
            return
        if not self.photos:
            return

        self._flash_button(self.btn_same_individual)

        photo = self.photos[self.current_index]
        if photo.processed:
            self.status_bar.showMessage("This photo is already processed")
            return

        prev_row = self.exporter.get_row(self._last_assigned_photo_id)
        if prev_row is None:
            self.status_bar.showMessage("Previous assignment row not found")
            return

        try:
            current_count = int(prev_row.get("PhotoCount", "1") or "1")
        except ValueError:
            current_count = 1
        current_count += 1
        prev_row["PhotoCount"] = str(current_count)

        # Update the row in the exporter
        self.exporter.write_row(self._last_assigned_photo_id, prev_row)
        self._same_individual_count += 1

        if self.scrub_enabled:
            self._queue_scrub(photo, species_name=prev_row.get("CommonName", ""))

        # Mark processed without creating a new output row
        self._processed_count += (not photo.processed)
        photo.processed = True
        photo.taxon_name = prev_row.get("TaxonName", "")
        photo.common_name = prev_row.get("CommonName", "")

        # Show ribbon on photo before advancing
        taxon = prev_row.get("TaxonName", "")
        common = prev_row.get("CommonName", "")
        disp = f"{taxon} ({common})" if common else taxon
        self.lbl_assignment.setText(
            f"Same Individual #{current_count}: {disp}"
        )
        self.lbl_assignment.setStyleSheet(
            "font-size: 11pt; font-weight: bold; padding: 6px; "
            "background: #2d4a1a; border-radius: 4px; color: #a0d468;"
        )
        self.status_bar.showMessage(
            f"Same individual (photo {current_count} of this individual) > {photo.filename}"
        )
        self.go_next()

    @safe_slot
    def mark_unknown(self):
        self._ensure_exporter()
        if not self.photos or not self.exporter:
            return

        self._flash_button(self.btn_unknown)

        photo = self.photos[self.current_index]
        meta = self._meta_cache.get(photo.photo_id)
        if meta is None:
            try:
                meta = extract_metadata(photo.full_path)
            except Exception:
                meta = PhotoMetadata()
            self._meta_cache[photo.photo_id] = meta

        camera_id = self._get_camera_id(photo)
        site_id = self._get_site_id(photo)
        self._sequence_counter += 1

        col_ac = build_column_ac(
            site_name=camera_id,
            filename=photo.filename,
            date_obs=meta.date_obs,
            time_str=meta.time_str,
            sequence=self._sequence_counter,
        )

        row = {col: "" for col in OUTPUT_COLUMNS}
        row["ID"] = photo.photo_id
        row["TaxonName"] = "Unknown ID"
        row["DateObs"] = meta.date_obs
        if meta.latitude is not None:
            row["Latitude"] = meta.latitude
        if meta.longitude is not None:
            row["Longitude"] = meta.longitude
        _user_notes = self.notes_input.toPlainText().strip()
        row["Comments"] = (col_ac + "; " + _user_notes) if _user_notes else col_ac
        row["Abundance"] = "0"
        row["PhotoCount"] = "1"
        row["Time"] = format_time_hmm(meta.time_str) or extract_time_from_col_ac(col_ac)
        row["SiteName"] = site_id
        row["CameraID"] = camera_id
        row["ObsMethod"] = self.field_obs_method.currentText()
        row["RecordType"] = self.field_record_type.currentText()
        row["FaunaType"] = self.field_fauna_type.currentText()
        row["Author"] = self.field_author.text()
        row["Citation"] = self.field_citation.text()

        self.exporter.write_row(photo.photo_id, row)

        if self.scrub_enabled:
            self._queue_scrub(photo, species_name="Unknown ID")

        self._processed_count += (not photo.processed)
        photo.processed = True
        photo.taxon_name = "Unknown ID"
        photo.common_name = ""
        self.notes_input.clear()

        # Unknown resets same-individual chain
        self._last_assigned_photo_id = None
        self._same_individual_count = 0
        self.btn_same_individual.setEnabled(False)

        # Show confirmation ribbon before advancing
        self.lbl_assignment.setText("Done: Unknown ID")
        self.lbl_assignment.setStyleSheet(
            "font-size: 11pt; font-weight: bold; padding: 6px; "
            "background: #5a3a00; border-radius: 4px; color: #ffd166;"
        )
        self.status_bar.showMessage(f"Done: Unknown ID: {photo.filename}")
        self.go_next()

    def _queue_scrub(self, photo: PhotoItem, species_name: str = ""):
        if not self.scrub_output_root:
            return
        if self.overwrite_originals:
            self._scrub_worker.add_job(photo.photo_id, photo.full_path, "", True)
        else:
            # Build destination path; append species name for scrubbed copies
            base, ext = os.path.splitext(photo.filename)
            if species_name:
                dst_name = f"{base}_{species_name}{ext}"
            else:
                dst_name = photo.filename
            rel_dir = os.path.dirname(photo.relative_path)
            dst = os.path.join(self.scrub_output_root, rel_dir, dst_name)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            self._scrub_worker.add_job(photo.photo_id, photo.full_path, dst, False)

    def _validate_multi_count(self, text: str):
        """Enable/disable Go button based on valid numeric count > 0."""
        try:
            n = int(text)
            self.btn_multi_same_go.setEnabled(n > 0)
        except (ValueError, TypeError):
            self.btn_multi_same_go.setEnabled(False)

    @safe_slot
    def _on_multi_same_go(self):
        """Create N separate rows for the same species on the current photo.

        Each row has Abundance=1. Uses suffixed IDs for rows 2..N.
        """
        self._ensure_exporter()
        if not self.photos or not self.exporter:
            return

        try:
            count = int(self.spin_count.text())
        except (ValueError, TypeError):
            self.status_bar.showMessage("Enter a valid number")
            return
        if count <= 0:
            self.status_bar.showMessage("Count must be > 0")
            return

        # Determine which species to use: search selection > last assigned
        species = None
        sr_row = self.search_results.currentRow()
        if 0 <= sr_row < len(self._search_results_list):
            species = self._search_results_list[sr_row]
        elif self._last_assigned_photo_id:
            prev_row = self.exporter.get_row(self._last_assigned_photo_id)
            if prev_row and prev_row.get("TaxonName"):
                # Try species_db first for full record (Class, Order, Family...)
                taxon = prev_row.get("TaxonName", "")
                if self.species_db.loaded:
                    species = self.species_db.resolve_name(taxon)
                if species is None:
                    # Fallback: build record from all CSV columns
                    species = SpeciesRecord(
                        taxon_name=taxon,
                        common_name=prev_row.get("CommonName", ""),
                        class_name=prev_row.get("Class", ""),
                        order=prev_row.get("Order", ""),
                        family_name=prev_row.get("FamilyName", ""),
                        introduced=prev_row.get("Introduced", ""),
                        epbc_con_stat=prev_row.get("EPBCConStat", ""),
                        bc_con_stat=prev_row.get("BCConStat", ""),
                        wa_con_stat=prev_row.get("WAConStat", ""),
                        sre_sts=prev_row.get("SRE_Sts", ""),
                    )

        if species is None:
            self.status_bar.showMessage(
                "Select a species in search results first, or assign one normally"
            )
            return

        self._flash_button(self.btn_multi_same_go)

        photo = self.photos[self.current_index]
        meta = self._meta_cache.get(photo.photo_id)
        if meta is None:
            try:
                meta = extract_metadata(photo.full_path)
            except Exception:
                meta = PhotoMetadata()
            self._meta_cache[photo.photo_id] = meta

        camera_id = self._get_camera_id(photo)
        site_id = self._get_site_id(photo)

        for idx in range(count):
            self._sequence_counter += 1
            col_ac = build_column_ac(
                site_name=camera_id,
                filename=photo.filename,
                date_obs=meta.date_obs,
                time_str=meta.time_str,
                sequence=self._sequence_counter,
            )

            # First row uses base photo_id; subsequent get _i2, _i3, ...
            if idx == 0:
                row_id = photo.photo_id
            else:
                row_id = f"{photo.photo_id}_i{idx + 1}"

            row = {col: "" for col in OUTPUT_COLUMNS}
            row["ID"] = row_id
            row["DateObs"] = meta.date_obs
            if meta.latitude is not None:
                row["Latitude"] = meta.latitude
            if meta.longitude is not None:
                row["Longitude"] = meta.longitude
            _user_notes = self.notes_input.toPlainText().strip()
            row["Comments"] = (col_ac + "; " + _user_notes) if _user_notes else col_ac
            row["Abundance"] = "1"
            row["PhotoCount"] = "1"
            row["Time"] = format_time_hmm(meta.time_str) or extract_time_from_col_ac(col_ac)
            row.update(species.to_output_fields())
            row["SiteName"] = site_id
            row["CameraID"] = camera_id
            row["ObsMethod"] = self.field_obs_method.currentText()
            row["RecordType"] = self.field_record_type.currentText()
            row["FaunaType"] = self.field_fauna_type.currentText()
            row["Author"] = self.field_author.text()
            row["Citation"] = self.field_citation.text()

            self.exporter.write_row(row_id, row)

        if self.scrub_enabled:
            self._queue_scrub(photo, species_name=species.common_name)

        self._processed_count += (not photo.processed)
        photo.processed = True
        photo.taxon_name = species.taxon_name
        photo.common_name = species.common_name
        self._last_assigned_photo_id = photo.photo_id
        self._same_individual_count = 0
        self.btn_same_individual.setEnabled(True)

        # Show confirmation
        self.lbl_assignment.setText(
            f"Done: {count}x {species.display_text()}"
        )
        self.lbl_assignment.setStyleSheet(
            "font-size: 11pt; font-weight: bold; padding: 6px; "
            "background: #1b4332; border-radius: 4px; color: #95d5b2;"
        )
        self.status_bar.showMessage(
            f"Created {count} rows: {species.display_text()} > {photo.filename}"
        )
        self.spin_count.setText("0")
        self.go_next()

    @safe_slot
    def _toggle_multi_id(self, checked: bool):
        """Toggle Multi Individuals (diff. sp.) click-to-place mode."""
        self._multi_id_active = checked
        if checked:
            # Mutually exclusive with quoll clip
            if self._quoll_clip_active:
                self._quoll_clip_active = False
                self._quoll_clip_points.clear()
                self.image_viewer.clear_overlay()
            self._multi_id_count = 0
            self._multi_id_detections.clear()
            self._multi_id_pending_point = None
            self.image_viewer.click_mode = True
            self.image_viewer.clear_detections()
            self.btn_multi_id_done.setEnabled(False)
            self.btn_multi_id_undo.setEnabled(False)
            self.status_bar.showMessage(
                "Multi ID ON: Click photo to place marker, then click species to assign."
            )
        else:
            self._multi_id_count = 0
            self._multi_id_detections.clear()
            self._multi_id_pending_point = None
            self.image_viewer.click_mode = False
            self.image_viewer.clear_detections()
            self.btn_multi_id_done.setEnabled(False)
            self.btn_multi_id_undo.setEnabled(False)
            self.status_bar.showMessage("Multi ID OFF")

    # ------------------------------------------------------------------
    # Multi-ID click-to-place methods
    # ------------------------------------------------------------------

    @safe_slot
    def _on_image_click(self, img_x: float, img_y: float):
        if self._quoll_clip_active:
            self._on_quoll_clip_click(img_x, img_y)
        elif self._multi_id_active:
            self._on_multi_id_click(img_x, img_y)

    @safe_slot
    def _on_multi_id_click(self, img_x: float, img_y: float):
        self._multi_id_pending_point = QPointF(img_x, img_y)
        self._refresh_detection_overlay()
        self.btn_multi_id_undo.setEnabled(True)
        self.status_bar.showMessage("Marker placed — now click a species button.")

    @safe_slot
    def _multi_id_done(self):
        self._ensure_exporter()
        if not self.photos or not self.exporter:
            return
        if not self._multi_id_detections:
            self.status_bar.showMessage("No detections — place and assign markers first.")
            return

        photo = self.photos[self.current_index]
        meta = self._meta_cache.get(photo.photo_id)
        if meta is None:
            try:
                meta = extract_metadata(photo.full_path)
            except Exception:
                meta = PhotoMetadata()
            self._meta_cache[photo.photo_id] = meta

        camera_id = self._get_camera_id(photo)
        site_id = self._get_site_id(photo)
        first_species = None

        for det_idx, (pt, species) in enumerate(self._multi_id_detections):
            self._sequence_counter += 1
            col_ac = build_column_ac(
                site_name=camera_id, filename=photo.filename,
                date_obs=meta.date_obs, time_str=meta.time_str,
                sequence=self._sequence_counter,
            )
            row_id = photo.photo_id if det_idx == 0 else f"{photo.photo_id}_m{det_idx + 1}"
            if det_idx == 0:
                first_species = species

            row = {col: "" for col in OUTPUT_COLUMNS}
            row["ID"] = row_id
            row["DateObs"] = meta.date_obs
            if meta.latitude is not None:
                row["Latitude"] = meta.latitude
            if meta.longitude is not None:
                row["Longitude"] = meta.longitude
            _user_notes = self.notes_input.toPlainText().strip()
            row["Comments"] = (col_ac + "; " + _user_notes) if _user_notes else col_ac
            row["Abundance"] = "1"
            row["PhotoCount"] = "1"
            row["Time"] = format_time_hmm(meta.time_str) or extract_time_from_col_ac(col_ac)
            row.update(species.to_output_fields())
            row["SiteName"] = site_id
            row["CameraID"] = camera_id
            row["ObsMethod"] = self.field_obs_method.currentText()
            row["RecordType"] = self.field_record_type.currentText()
            row["FaunaType"] = self.field_fauna_type.currentText()
            row["Author"] = self.field_author.text()
            row["Citation"] = self.field_citation.text()
            self.exporter.write_row(row_id, row)

        if self.scrub_enabled and not photo.processed and first_species:
            self._queue_scrub(photo, species_name=first_species.common_name)

        self._processed_count += (not photo.processed)
        photo.processed = True
        if first_species:
            photo.taxon_name = first_species.taxon_name
            photo.common_name = first_species.common_name

        n = len(self._multi_id_detections)
        self._last_assigned_photo_id = photo.photo_id
        self._same_individual_count = 0
        self.btn_same_individual.setEnabled(True)

        self.lbl_assignment.setText(f"Done: {n} detection{'s' if n != 1 else ''}")
        self.lbl_assignment.setStyleSheet(
            "font-size: 11pt; font-weight: bold; padding: 6px; "
            "background: #1b4332; border-radius: 4px; color: #95d5b2;"
        )

        # Clean up and advance
        self._multi_id_detections.clear()
        self._multi_id_pending_point = None
        self._multi_id_active = False
        self.btn_multi_id.blockSignals(True)
        self.btn_multi_id.setChecked(False)
        self.btn_multi_id.blockSignals(False)
        self.btn_multi_id_done.setEnabled(False)
        self.btn_multi_id_undo.setEnabled(False)
        self.image_viewer.click_mode = False
        self.image_viewer.clear_detections()
        self.notes_input.clear()
        self.go_next()

    @safe_slot
    def _undo_last_marker(self):
        if self._multi_id_pending_point is not None:
            self._multi_id_pending_point = None
            self._refresh_detection_overlay()
            self.status_bar.showMessage("Pending marker removed.")
        elif self._multi_id_detections:
            pt, species = self._multi_id_detections.pop()
            self._refresh_detection_overlay()
            n = len(self._multi_id_detections)
            self.status_bar.showMessage(
                f"Removed: {species.display_text()} — {n} remaining"
            )
        else:
            self.status_bar.showMessage("Nothing to undo.")
            return
        has_any = bool(self._multi_id_detections or self._multi_id_pending_point)
        self.btn_multi_id_undo.setEnabled(has_any)
        self.btn_multi_id_done.setEnabled(bool(self._multi_id_detections))

    def _refresh_detection_overlay(self):
        markers = []
        for i, (pt, species) in enumerate(self._multi_id_detections):
            label = species.common_name or species.taxon_name
            markers.append((pt, label, i + 1))
        self.image_viewer.set_detection_markers(markers, self._multi_id_pending_point)

    @safe_slot
    def _refresh_output(self):
        """Re-read current Default-Field values and update every existing row.

        Solves the stale-field bug (UI2): previously written rows retained the
        field values captured at assignment time.  Now each Refresh reads the
        live UI controls and patches all rows before exporting a timestamped
        copy.
        """
        if not self.exporter:
            QMessageBox.information(self, "Refresh", "No output file loaded yet.")
            return

        # Single source of truth: read current UI field values
        field_updates = {
            "ObsMethod":  self.field_obs_method.currentText(),
            "RecordType": self.field_record_type.currentText(),
            "FaunaType":  self.field_fauna_type.currentText(),
            "Author":     self.field_author.text(),
            "Citation":   self.field_citation.text(),
        }

        # Patch every row in the exporter, then re-save the main CSV
        self.exporter.patch_all_rows(field_updates)

        # Export a timestamped snapshot
        new_path = self.exporter.export_timestamped()
        self.status_bar.showMessage(
            f"Refreshed {self.exporter.total_rows} rows with current fields > {new_path}"
        )

    def _flash_button(self, btn: QPushButton):
        """Briefly flash a button."""
        original_style = btn.styleSheet()
        btn.setStyleSheet(
            "background: #4a7fb5; color: #ffffff; border: 2px solid #ffffff;"
            "border-radius: 4px; padding: 4px 8px; font-weight: bold;"
        )
        QTimer.singleShot(150, lambda s=original_style: btn.setStyleSheet(s))

    @Slot(str, str, bool, str)
    def _on_scrub_done(self, photo_id: str, scrubbed_path: str, success: bool, message: str):
        if not success:
            print(f"Scrub failed for {photo_id}: {message}", flush=True)

    # ------------------------------------------------------------------
    # Undo
    # ------------------------------------------------------------------

    @safe_slot
    def undo_last(self):
        if not self.exporter:
            return
        photo_id = self.exporter.undo_last()
        if photo_id is None:
            self.status_bar.showMessage("Nothing to undo")
            return

        self._sequence_counter = max(0, self._sequence_counter - 1)

        # Strip suffixes (_i2, _m2 etc) to find the base photo
        base_id = photo_id.split("_i")[0].split("_m")[0] if ("_i" in photo_id or "_m" in photo_id) else photo_id

        for i, p in enumerate(self.photos):
            if p.photo_id == base_id:
                # Only mark unprocessed if no other rows remain for this photo
                remaining = any(
                    rid == base_id or rid.startswith(base_id + "_")
                    for rid in self.exporter._rows
                )
                if not remaining:
                    if p.processed:
                        self._processed_count = max(0, self._processed_count - 1)
                    p.processed = False
                    p.taxon_name = ""
                    p.common_name = ""
                    p.row_data = {}
                self.current_index = i
                if self.scrub_output_root:
                    scrubbed = os.path.join(self.scrub_output_root, p.relative_path)
                    if os.path.exists(scrubbed):
                        try:
                            os.remove(scrubbed)
                        except OSError:
                            pass
                break

        self._last_assigned_photo_id = None
        self._same_individual_count = 0
        self.btn_same_individual.setEnabled(False)

        self._last_shown_index = -1  # force per-photo reset
        self._show_current_photo()
        self.status_bar.showMessage(f"Undone — ready to re-assign")

    @safe_slot
    def _undo_n(self):
        if not self.exporter:
            return
        text = self.undo_n_input.text().strip()
        if not text:
            self.status_bar.showMessage("Enter a number in the box first")
            return
        try:
            n = int(text)
        except ValueError:
            self.status_bar.showMessage("Invalid number")
            return
        if n <= 0:
            return

        count = 0
        for _ in range(n):
            photo_id = self.exporter.undo_last()
            if photo_id is None:
                break
            self._sequence_counter = max(0, self._sequence_counter - 1)
            base_id = photo_id.split("_i")[0].split("_m")[0] if ("_i" in photo_id or "_m" in photo_id) else photo_id
            for p in self.photos:
                if p.photo_id == base_id:
                    remaining = any(
                        rid == base_id or rid.startswith(base_id + "_")
                        for rid in self.exporter._rows
                    )
                    if not remaining:
                        if p.processed:
                            self._processed_count = max(0, self._processed_count - 1)
                        p.processed = False
                        p.taxon_name = ""
                        p.common_name = ""
                        p.row_data = {}
                    if self.scrub_output_root:
                        scrubbed = os.path.join(self.scrub_output_root, p.relative_path)
                        if os.path.exists(scrubbed):
                            try:
                                os.remove(scrubbed)
                            except OSError:
                                pass
                    break
            count += 1

        self._last_assigned_photo_id = None
        self._same_individual_count = 0
        self.btn_same_individual.setEnabled(False)

        # Navigate to the first undone photo (earliest in the list)
        for i, p in enumerate(self.photos):
            if not p.processed:
                self.current_index = i
                break
        self._last_shown_index = -1
        self._show_current_photo()
        self.status_bar.showMessage(f"Undone {count} assignments — ready to re-assign")
        self.undo_n_input.clear()

    @safe_slot
    def _undo_all(self):
        if not self.exporter:
            return
        reply = QMessageBox.warning(
            self, "Undo All",
            "This will undo ALL assignments. Are you sure?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        count = 0
        while True:
            photo_id = self.exporter.undo_last()
            if photo_id is None:
                break
            self._sequence_counter = max(0, self._sequence_counter - 1)
            for p in self.photos:
                if p.photo_id == photo_id:
                    p.processed = False
                    p.taxon_name = ""
                    p.common_name = ""
                    p.row_data = {}
                    break
            count += 1

        if self.scrub_output_root and os.path.isdir(self.scrub_output_root):
            import shutil
            try:
                shutil.rmtree(self.scrub_output_root)
            except OSError:
                pass

        self._last_assigned_photo_id = None
        self._same_individual_count = 0
        self.btn_same_individual.setEnabled(False)
        self._processed_count = 0

        self.current_index = 0
        self._last_shown_index = -1
        self._show_current_photo()
        self.status_bar.showMessage(f"Undone all {count} — back to start of folder")

    def _toggle_overwrite(self, checked):
        if checked:
            reply = QMessageBox.warning(
                self, "WARNING: Warning",
                "Overwriting originals will permanently remove metadata from your original photos.\n\n"
                "This cannot be undone. Are you sure?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.overwrite_originals = True
            else:
                self.chk_overwrite.setChecked(False)
        else:
            self.overwrite_originals = False

    # ------------------------------------------------------------------
    # Quick Species buttons
    # ------------------------------------------------------------------

    def _update_top20(self):
        if self.top20_species:
            self._rebuild_top20_buttons()

    def _rebuild_top20_buttons(self):
        for btn in self.top20_buttons:
            self.top20_layout.removeWidget(btn)
            btn.deleteLater()
        self.top20_buttons.clear()
        for btn in self._top20_remove_btns:
            self.top20_layout.removeWidget(btn)
            btn.deleteLater()
        self._top20_remove_btns.clear()

        if self.lbl_top20_empty:
            self.top20_layout.removeWidget(self.lbl_top20_empty)
            self.lbl_top20_empty.deleteLater()
            self.lbl_top20_empty = None

        # 16 shortcuts: 1-0 for first 10, F1-F6 for next 6
        shortcut_labels = (
            ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"] +
            ["F1", "F2", "F3", "F4", "F5", "F6"]
        )
        for i, sp in enumerate(self.top20_species):
            label = shortcut_labels[i] if i < len(shortcut_labels) else ""
            text = sp.taxon_name
            if sp.common_name:
                text = f"{sp.common_name}\n{sp.taxon_name}"
            if label:
                text = f"[{label}] {text}"

            btn = QPushButton(text)
            btn.setFixedHeight(48)
            btn.setStyleSheet("""
                QPushButton {
                    text-align: left; padding: 4px 8px;
                    font-size: 9pt; background: #2d2d2d; color: #e0e0e0;
                    border: 1px solid #444; border-radius: 4px;
                }
                QPushButton:hover { background: #3d5a80; border-color: #5a8fbf; }
                QPushButton:pressed { background: #4a7fb5; }
            """)
            btn.clicked.connect(lambda checked=False, idx=i: self._trigger_top20(idx))

            # Small X button to remove
            rm_btn = QPushButton("X")
            rm_btn.setObjectName("btn_remove_quick")
            rm_btn.setToolTip(f"Remove {sp.taxon_name}")
            rm_btn.clicked.connect(lambda checked=False, idx=i: self._remove_quick_species(idx))

            row_idx = i // 2
            col = (i % 2) * 2  # cols: 0,2 for species buttons; 1,3 for X buttons
            self.top20_layout.addWidget(btn, row_idx, col)
            self.top20_layout.addWidget(rm_btn, row_idx, col + 1)
            self.top20_buttons.append(btn)
            self._top20_remove_btns.append(rm_btn)

        self.top20_layout.setColumnStretch(0, 1)
        self.top20_layout.setColumnStretch(1, 0)
        self.top20_layout.setColumnStretch(2, 1)
        self.top20_layout.setColumnStretch(3, 0)

        if not self.top20_species:
            lbl = QLabel("Load common species xlsx or add from search")
            lbl.setObjectName("lbl_hint")
            self.top20_layout.addWidget(lbl, 0, 0, 1, 4)
            self.lbl_top20_empty = lbl

    # ------------------------------------------------------------------
    # Quoll Clipping Tool
    # ------------------------------------------------------------------

    @safe_slot
    def _start_clip(self, clip_type: str):
        """Start clip: auto-assign species then enter 4-click mode.

        clip_type: "NQ" for Northern Quoll, "Chuditch" for Western Quoll.
        """
        if not self.photos:
            self.status_bar.showMessage("No photos loaded")
            return
        self._ensure_exporter()
        if not self.exporter:
            QMessageBox.warning(self, "Not Ready", "No output file set.")
            return

        # Cancel multi-ID if active
        if self._multi_id_active:
            self._multi_id_active = False
            self._multi_id_detections.clear()
            self._multi_id_pending_point = None
            self.btn_multi_id.blockSignals(True)
            self.btn_multi_id.setChecked(False)
            self.btn_multi_id.blockSignals(False)
            self.btn_multi_id_done.setEnabled(False)
            self.btn_multi_id_undo.setEnabled(False)
            self.image_viewer.clear_detections()

        photo = self.photos[self.current_index]

        # Resolve species based on clip type
        species = None
        if clip_type == "NQ":
            self._clip_species_name = "NQ"
            self._clip_folder_name = "NQ clipped"
            if self.species_db.loaded:
                species = self.species_db.resolve_name("Dasyurus hallucatus")
            if species is None:
                species = SpeciesRecord(
                    taxon_name="Dasyurus hallucatus",
                    common_name="Northern Quoll",
                )
        else:  # Chuditch
            self._clip_species_name = "Chuditch"
            self._clip_folder_name = "Chuditch clipped"
            if self.species_db.loaded:
                species = self.species_db.resolve_name("Dasyurus geoffroii")
            if species is None:
                species = SpeciesRecord(
                    taxon_name="Dasyurus geoffroii",
                    common_name="Chuditch",
                )

        # Assign species (but don't advance — we need to clip first)
        self._assign_for_quoll(photo, species)

        # Enter click mode
        self._quoll_clip_active = True
        self._quoll_clip_points.clear()
        self.image_viewer.click_mode = True
        self.image_viewer.clear_overlay()
        self.status_bar.showMessage(
            f"{self._clip_species_name} Clip: Click 1 = left side"
        )

    def _assign_for_quoll(self, photo, species):
        """Assign species for quoll clip (no advance)."""
        meta = self._meta_cache.get(photo.photo_id)
        if meta is None:
            try:
                meta = extract_metadata(photo.full_path)
            except Exception:
                meta = PhotoMetadata()
            self._meta_cache[photo.photo_id] = meta

        camera_id = self._get_camera_id(photo)
        site_id = self._get_site_id(photo)
        self._sequence_counter += 1

        col_ac = build_column_ac(
            site_name=camera_id,
            filename=photo.filename,
            date_obs=meta.date_obs,
            time_str=meta.time_str,
            sequence=self._sequence_counter,
        )

        abundance = "0"
        try:
            n = int(self.spin_count.text())
            if n > 0:
                abundance = str(n)
        except (ValueError, TypeError):
            pass

        row = {col: "" for col in OUTPUT_COLUMNS}
        row["ID"] = photo.photo_id
        row["DateObs"] = meta.date_obs
        if meta.latitude is not None:
            row["Latitude"] = meta.latitude
        if meta.longitude is not None:
            row["Longitude"] = meta.longitude
        _user_notes = self.notes_input.toPlainText().strip()
        row["Comments"] = (col_ac + "; " + _user_notes) if _user_notes else col_ac
        row["Abundance"] = abundance
        row["PhotoCount"] = "1"
        row["Time"] = format_time_hmm(meta.time_str) or extract_time_from_col_ac(col_ac)
        row.update(species.to_output_fields())
        row["SiteName"] = site_id
        row["CameraID"] = camera_id
        row["ObsMethod"] = self.field_obs_method.currentText()
        row["RecordType"] = self.field_record_type.currentText()
        row["FaunaType"] = self.field_fauna_type.currentText()
        row["Author"] = self.field_author.text()
        row["Citation"] = self.field_citation.text()

        self.exporter.write_row(photo.photo_id, row)

        if self.scrub_enabled and not photo.processed:
            self._queue_scrub(photo, species_name=species.common_name)

        self._processed_count += (not photo.processed)
        photo.processed = True
        photo.taxon_name = species.taxon_name
        photo.common_name = species.common_name
        photo.row_data = row

        self._last_assigned_photo_id = photo.photo_id
        self._same_individual_count = 0
        self.btn_same_individual.setEnabled(True)

        self.lbl_assignment.setText(
            f"Done: {species.taxon_name}"
            + (f" ({species.common_name})" if species.common_name else "")
        )
        self.lbl_assignment.setStyleSheet(
            "font-size: 11pt; font-weight: bold; padding: 6px; "
            "background: #1b4332; border-radius: 4px; color: #95d5b2;"
        )

    @safe_slot
    def _on_quoll_clip_click(self, img_x: float, img_y: float):
        """Handle a click on the image during quoll-clip mode."""
        if not self._quoll_clip_active:
            return

        pt = QPointF(img_x, img_y)
        self._quoll_clip_points.append(pt)
        n = len(self._quoll_clip_points)

        # Update overlay
        self.image_viewer.set_overlay_points(self._quoll_clip_points)

        label = self._clip_species_name or "Clip"
        if n == 1:
            self.status_bar.showMessage(f"{label} Clip: Click 2 = right side")
        elif n == 2:
            self.status_bar.showMessage(f"{label} Clip: Click 3 = top")
        elif n == 3:
            self.status_bar.showMessage(f"{label} Clip: Click 4 = bottom")
        elif n == 4:
            self.status_bar.showMessage("Computing clip …")
            QTimer.singleShot(0, self._do_quoll_clip)

    def _do_quoll_clip(self):
        """Compute the oriented crop from 4 click points (left, right, top, bottom)."""
        if len(self._quoll_clip_points) < 4:
            return
        if not self.photos:
            return

        pL, pR, pT, pB = self._quoll_clip_points[:4]
        photo = self.photos[self.current_index]

        # Axis vector (left → right) and length
        ax = pR.x() - pL.x()
        ay = pR.y() - pL.y()
        axis_len = math.hypot(ax, ay)
        if axis_len < 2:
            self.status_bar.showMessage("Left/right points too close — try again")
            self._quoll_clip_points.clear()
            self.image_viewer.clear_overlay()
            return

        # Unit vectors: u = along axis, p = perpendicular
        ux, uy = ax / axis_len, ay / axis_len
        px, py = -uy, ux  # 90° CCW

        # Midpoint of the axis
        mx = (pL.x() + pR.x()) / 2.0
        my = (pL.y() + pR.y()) / 2.0

        # Signed perpendicular distances of top and bottom from the axis
        t_perp = (pT.x() - mx) * px + (pT.y() - my) * py
        b_perp = (pB.x() - mx) * px + (pB.y() - my) * py
        min_perp = min(t_perp, b_perp)
        max_perp = max(t_perp, b_perp)
        body_width = max_perp - min_perp
        if body_width < 2:
            self.status_bar.showMessage("Top/bottom too close — try again")
            self._quoll_clip_points.clear()
            self.image_viewer.clear_overlay()
            return

        # Centre of the oriented rectangle
        perp_centre = (min_perp + max_perp) / 2.0
        cx = mx + perp_centre * px
        cy = my + perp_centre * py

        # Rotation angle (axis from horizontal)
        angle_rad = math.atan2(ay, ax)

        # Use PIL for rotation + crop
        try:
            from PIL import Image as PILImage
        except ImportError:
            QMessageBox.warning(self, "Missing Library",
                "Pillow is required for quoll clipping.\npip install Pillow")
            self._reset_quoll_clip()
            return

        try:
            pil_img = PILImage.open(photo.full_path)
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Cannot open image:\n{e}")
            self._reset_quoll_clip()
            return

        # Rotate so the axis is horizontal
        angle_deg = math.degrees(angle_rad)
        rotated = pil_img.rotate(angle_deg, resample=PILImage.BICUBIC,
                                  expand=True, fillcolor=(0, 0, 0))

        # Transform centre point through rotation
        orig_w, orig_h = pil_img.size
        rot_w, rot_h = rotated.size
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        ocx, ocy = orig_w / 2.0, orig_h / 2.0
        dx, dy = cx - ocx, cy - ocy
        new_dx = dx * cos_a + dy * sin_a
        new_dy = -dx * sin_a + dy * cos_a
        rcx = rot_w / 2.0 + new_dx
        rcy = rot_h / 2.0 + new_dy

        # Crop box: axis_len wide × body_width tall, centred on (rcx, rcy)
        half_len = axis_len / 2.0
        half_w = body_width / 2.0
        left = max(0, int(rcx - half_len))
        upper = max(0, int(rcy - half_w))
        right = min(rot_w, int(rcx + half_len))
        lower = min(rot_h, int(rcy + half_w))

        if right - left < 4 or lower - upper < 4:
            self.status_bar.showMessage("Crop region too small — try again")
            self._reset_quoll_clip()
            return

        cropped = rotated.crop((left, upper, right, lower))

        # Show preview dialog
        self._show_quoll_preview(cropped, photo)

    def _reset_quoll_clip(self):
        """Reset quoll clip state without advancing."""
        self._quoll_clip_points.clear()
        self.image_viewer.clear_overlay()
        self._quoll_clip_active = False
        self.image_viewer.click_mode = False

    def _show_quoll_preview(self, pil_cropped, photo):
        """Show a dialog with the cropped quoll and confirm/cancel/redraw."""
        from io import BytesIO
        buf = BytesIO()
        pil_cropped.save(buf, format="PNG")
        buf.seek(0)
        qimg = QImage()
        qimg.loadFromData(buf.read())
        pixmap = QPixmap.fromImage(qimg)

        dlg = QDialog(self)
        dlg.setWindowTitle("Quoll Clip Preview")
        dlg.setMinimumSize(400, 300)
        lay = QVBoxLayout(dlg)

        lbl = QLabel()
        scaled = pixmap.scaled(600, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        lbl.setPixmap(scaled)
        lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(lbl)

        info = QLabel(f"Crop: {pil_cropped.width} × {pil_cropped.height} px")
        info.setAlignment(Qt.AlignCenter)
        lay.addWidget(info)

        btn_row = QHBoxLayout()
        btn_confirm = QPushButton("Confirm && Save")
        btn_redraw = QPushButton("Redraw")
        btn_cancel = QPushButton("Cancel")
        btn_row.addWidget(btn_confirm)
        btn_row.addWidget(btn_redraw)
        btn_row.addWidget(btn_cancel)
        lay.addLayout(btn_row)

        result = {"action": "cancel"}

        def on_confirm():
            result["action"] = "confirm"
            dlg.accept()

        def on_redraw():
            result["action"] = "redraw"
            dlg.reject()

        def on_cancel():
            result["action"] = "cancel"
            dlg.reject()

        btn_confirm.clicked.connect(on_confirm)
        btn_redraw.clicked.connect(on_redraw)
        btn_cancel.clicked.connect(on_cancel)

        dlg.exec()

        if result["action"] == "confirm":
            self._save_quoll_clip(pil_cropped, photo)
            self._quoll_clip_points.clear()
            self.image_viewer.clear_overlay()
            self._quoll_clip_active = False
            self.image_viewer.click_mode = False
            self.status_bar.showMessage(f"Quoll clip saved — advancing to next photo")
            self.go_next()
        elif result["action"] == "redraw":
            self._quoll_clip_points.clear()
            self.image_viewer.clear_overlay()
            self.status_bar.showMessage("Quoll Clip: Click 1 = left side")
        else:
            self._reset_quoll_clip()
            self.status_bar.showMessage("Quoll clip cancelled.")

    def _save_quoll_clip(self, pil_cropped, photo):
        """Save the cropped clip image to the species-specific clip folder."""
        folder_name = self._clip_folder_name or "Quoll clipped"
        if hasattr(self, 'photo_folder') and self.photo_folder:
            clip_dir = os.path.join(self.photo_folder, folder_name)
        else:
            clip_dir = os.path.join(os.path.dirname(photo.full_path), folder_name)
        os.makedirs(clip_dir, exist_ok=True)

        base = os.path.splitext(photo.filename)[0]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out_name = f"{base}_clip_{stamp}.png"
        out_path = os.path.join(clip_dir, out_name)

        counter = 1
        while os.path.exists(out_path):
            out_name = f"{base}_clip_{stamp}_{counter}.png"
            out_path = os.path.join(clip_dir, out_name)
            counter += 1

        try:
            pil_cropped.save(out_path, format="PNG")
            self.status_bar.showMessage(f"Quoll clip saved: {out_name}")
        except Exception as e:
            QMessageBox.warning(self, "Save Error",
                f"Could not save quoll clip:\n{e}")


# ---------------------------------------------------------------------------
# Standalone entry point (kept for backwards compatibility)
# ---------------------------------------------------------------------------

def run_app():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    default_font = app.font()
    if default_font.pointSize() <= 0:
        default_font.setPointSize(10)
        app.setFont(default_font)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

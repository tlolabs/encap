from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from encap.export_tools import (
        BITRATE_OPTIONS,
        export_project,
        normalize_encoder,
        normalize_output_format,
    )
    from encap.ffmpeg_tools import (
        apple_aac_encoder_implementation,
        ensure_lame,
        media_encoder_available,
    )
    from encap.models import CapabilityFlags, ChapterEntry, ProjectDocument
    from encap.project_io import cleanup_loaded_project, load_project, save_project
    from encap.service import audio_path_sort_key, build_project_document
    from encap.transcript_tools import (
        export_transcript_srt,
        export_transcript_txt,
    )
    from encap.transcription_models import (
        MODEL_BY_ID,
        WHISPER_MODELS,
        TranscriptionModel,
        TranscriptionModelStore,
    )
    from encap.transcription_service import (
        APPLE_PROVIDER_ID,
        apple_transcription_available,
        transcribe_audio_sources,
    )
    from encap.transcribe_workspace import TranscribeWorkspace
    from encap.update_service import (
        PreparedUpdate,
        UpdateRelease,
        check_for_update,
        download_update,
        installed_app_dir,
        launch_update_helper,
        prepare_update,
    )
    from encap.version import __version__
    from encap.wav_tools import AUDIO_FILE_EXTENSIONS, EncapError
else:
    from .export_tools import (
        BITRATE_OPTIONS,
        export_project,
        normalize_encoder,
        normalize_output_format,
    )
    from .ffmpeg_tools import (
        apple_aac_encoder_implementation,
        ensure_lame,
        media_encoder_available,
    )
    from .models import CapabilityFlags, ChapterEntry, ProjectDocument
    from .project_io import cleanup_loaded_project, load_project, save_project
    from .service import audio_path_sort_key, build_project_document
    from .transcript_tools import (
        export_transcript_srt,
        export_transcript_txt,
    )
    from .transcription_models import (
        MODEL_BY_ID,
        WHISPER_MODELS,
        TranscriptionModel,
        TranscriptionModelStore,
    )
    from .transcription_service import (
        APPLE_PROVIDER_ID,
        apple_transcription_available,
        transcribe_audio_sources,
    )
    from .transcribe_workspace import TranscribeWorkspace
    from .update_service import (
        PreparedUpdate,
        UpdateRelease,
        check_for_update,
        download_update,
        installed_app_dir,
        launch_update_helper,
        prepare_update,
    )
    from .version import __version__
    from .wav_tools import AUDIO_FILE_EXTENSIONS, EncapError

try:
    from PySide6.QtCore import (
        QEvent,
        QObject,
        QRunnable,
        QSize,
        Qt,
        QThreadPool,
        QTimer,
        QUrl,
        Signal,
    )
    from PySide6.QtGui import (
        QAction,
        QActionGroup,
        QDesktopServices,
        QIcon,
        QKeySequence,
        QPainter,
        QPixmap,
    )
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QDockWidget,
        QFileDialog,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMenu,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QSizePolicy,
        QStatusBar,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTextEdit,
        QToolBar,
        QStyle,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as exc:  # pragma: no cover
    missing_gui_dependency = exc
else:
    missing_gui_dependency = None


if missing_gui_dependency is None:

    IMAGE_EXTENSIONS = {".bmp", ".gif", ".heic", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


    def _image_path_from_mime(mime_data) -> Path | None:
        if not mime_data.hasUrls():
            return None
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                return path
        return None


    def _audio_folder_from_mime(mime_data) -> Path | None:
        if not mime_data.hasUrls():
            return None
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if not path.is_dir():
                continue
            try:
                has_audio = any(
                    child.is_file() and child.suffix.lower() in AUDIO_FILE_EXTENSIONS
                    for child in path.iterdir()
                )
            except OSError:
                continue
            if has_audio:
                return path
        return None

    class UrlValidationSignals(QObject):
        resolved = Signal(int, str, str, str)


    class UrlValidationWorker(QRunnable):
        def __init__(self, request_id: int, raw_value: str) -> None:
            super().__init__()
            self.request_id = request_id
            self.raw_value = raw_value
            self.signals = UrlValidationSignals()

        def run(self) -> None:
            status, resolved_url, detail = validate_link_url(self.raw_value)
            self.signals.resolved.emit(self.request_id, self.raw_value, status, resolved_url or detail)


    class UpdateCheckSignals(QObject):
        resolved = Signal(object, str)


    class UpdateCheckWorker(QRunnable):
        def __init__(self) -> None:
            super().__init__()
            self.signals = UpdateCheckSignals()

        def run(self) -> None:
            try:
                release = check_for_update()
            except Exception as exc:
                self.signals.resolved.emit(None, str(exc))
                return
            self.signals.resolved.emit(release, "")


    class UpdateDownloadSignals(QObject):
        completed = Signal(object, str)


    class UpdateDownloadWorker(QRunnable):
        def __init__(self, release: UpdateRelease) -> None:
            super().__init__()
            self.release = release
            self.signals = UpdateDownloadSignals()

        def run(self) -> None:
            archive_path = None
            try:
                archive_path = download_update(self.release)
                prepared = prepare_update(self.release, archive_path)
            except Exception as exc:
                self.signals.completed.emit(None, str(exc))
                return
            finally:
                if archive_path is not None:
                    archive_path.unlink(missing_ok=True)
                    try:
                        archive_path.parent.rmdir()
                    except OSError:
                        pass
            self.signals.completed.emit(prepared, "")


    class ModelDownloadSignals(QObject):
        progress = Signal(int, int)
        completed = Signal(str, str)


    class ModelDownloadWorker(QRunnable):
        def __init__(self, store: TranscriptionModelStore, model: TranscriptionModel) -> None:
            super().__init__()
            self.store = store
            self.model = model
            self.signals = ModelDownloadSignals()

        def run(self) -> None:
            try:
                self.store.download(
                    self.model,
                    progress=lambda downloaded, total: self.signals.progress.emit(
                        downloaded,
                        total or 0,
                    ),
                )
            except Exception as exc:
                self.signals.completed.emit(self.model.model_id, str(exc))
                return
            self.signals.completed.emit(self.model.model_id, "")


    class TranscriptionSignals(QObject):
        progress = Signal(int, int, str)
        completed = Signal(object, str)


    class TranscriptionWorker(QRunnable):
        def __init__(
            self,
            audio_sources,
            provider_id: str,
            model_store: TranscriptionModelStore,
        ) -> None:
            super().__init__()
            self.audio_sources = list(audio_sources)
            self.provider_id = provider_id
            self.model_store = model_store
            self.signals = TranscriptionSignals()

        def run(self) -> None:
            try:
                segments = transcribe_audio_sources(
                    self.audio_sources,
                    self.provider_id,
                    model_store=self.model_store,
                    progress=lambda current, total, message: self.signals.progress.emit(
                        current,
                        total,
                        message,
                    ),
                )
            except Exception as exc:
                self.signals.completed.emit(None, str(exc))
                return
            self.signals.completed.emit(segments, "")


    class ModelManagerDialog(QDialog):
        selected_model_changed = Signal(str)

        def __init__(self, store: TranscriptionModelStore, parent=None) -> None:
            super().__init__(parent)
            self.store = store
            self._download_worker: ModelDownloadWorker | None = None
            self.setWindowTitle("Transcription Models")
            self.resize(780, 430)

            layout = QVBoxLayout(self)
            explanation = QLabel(
                "Whisper models are downloaded only when you request them and remain on this "
                "computer. No model weights are included in EnCap."
            )
            explanation.setWordWrap(True)
            layout.addWidget(explanation)

            self.table = QTableWidget(0, 4)
            self.table.setHorizontalHeaderLabels(["Model", "Languages", "Download", "Status"])
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.table.setSelectionMode(QAbstractItemView.SingleSelection)
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            for column in (1, 2, 3):
                self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
            self.table.itemSelectionChanged.connect(self._update_details)
            layout.addWidget(self.table, stretch=1)

            self.details = QLabel()
            self.details.setWordWrap(True)
            layout.addWidget(self.details)

            self.progress = QProgressBar()
            self.progress.setVisible(False)
            layout.addWidget(self.progress)

            action_layout = QHBoxLayout()
            self.download_button = QPushButton("Download")
            self.use_button = QPushButton("Use Model")
            self.remove_button = QPushButton("Remove")
            self.download_button.clicked.connect(self._download_selected)
            self.use_button.clicked.connect(self._use_selected)
            self.remove_button.clicked.connect(self._remove_selected)
            action_layout.addWidget(self.download_button)
            action_layout.addWidget(self.use_button)
            action_layout.addWidget(self.remove_button)
            action_layout.addStretch(1)
            close_buttons = QDialogButtonBox(QDialogButtonBox.Close)
            close_buttons.rejected.connect(self.reject)
            action_layout.addWidget(close_buttons)
            layout.addLayout(action_layout)

            self._refresh()

        def _selected_model(self) -> TranscriptionModel | None:
            row = self.table.currentRow()
            if row < 0:
                return None
            item = self.table.item(row, 0)
            if item is None:
                return None
            return MODEL_BY_ID.get(item.data(Qt.UserRole))

        def _refresh(self, select_model_id: str | None = None) -> None:
            selected_id = self.store.selected_model_id()
            wanted_id = select_model_id or (
                self._selected_model().model_id if self._selected_model() is not None else selected_id
            )
            self.table.setRowCount(len(WHISPER_MODELS))
            wanted_row = 0
            for row, model in enumerate(WHISPER_MODELS):
                installed = self.store.is_installed(model)
                status = "Selected" if installed and selected_id == model.model_id else (
                    "Installed" if installed else "Not downloaded"
                )
                values = [model.name, model.languages, model.download_size, status]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.UserRole, model.model_id)
                    self.table.setItem(row, column, item)
                if model.model_id == wanted_id:
                    wanted_row = row
            self.table.selectRow(wanted_row)
            self._update_details()

        def _update_details(self) -> None:
            model = self._selected_model()
            busy = self._download_worker is not None
            if model is None:
                self.details.clear()
                self.download_button.setEnabled(False)
                self.use_button.setEnabled(False)
                self.remove_button.setEnabled(False)
                return
            installed = self.store.is_installed(model)
            self.details.setText(
                f"{model.description} License: {model.license_name}. "
                f"Stored in {self.store.model_path(model)}"
            )
            self.download_button.setEnabled(not installed and not busy)
            self.use_button.setEnabled(installed and not busy)
            self.remove_button.setEnabled(installed and not busy)
            self.table.setEnabled(not busy)

        def _download_selected(self) -> None:
            model = self._selected_model()
            if model is None or self._download_worker is not None:
                return
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            worker = ModelDownloadWorker(self.store, model)
            self._download_worker = worker
            worker.signals.progress.connect(self._handle_download_progress)
            worker.signals.completed.connect(self._handle_download_complete)
            self._update_details()
            QThreadPool.globalInstance().start(worker)

        def _handle_download_progress(self, downloaded: int, total: int) -> None:
            if total <= 0:
                self.progress.setRange(0, 0)
                return
            self.progress.setRange(0, 1000)
            self.progress.setValue(min(1000, int(downloaded * 1000 / total)))

        def _handle_download_complete(self, model_id: str, error: str) -> None:
            self._download_worker = None
            self.progress.setVisible(False)
            if error:
                QMessageBox.critical(self, "Model download failed", error)
            self._refresh(select_model_id=model_id)

        def _use_selected(self) -> None:
            model = self._selected_model()
            if model is None:
                return
            try:
                self.store.set_selected_model(model.model_id)
            except Exception as exc:
                QMessageBox.warning(self, "Cannot select model", str(exc))
                return
            self.selected_model_changed.emit(model.model_id)
            self._refresh(select_model_id=model.model_id)

        def _remove_selected(self) -> None:
            model = self._selected_model()
            if model is None:
                return
            response = QMessageBox.question(
                self,
                "Remove transcription model?",
                f"Remove {model.name} from this computer?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if response != QMessageBox.Yes:
                return
            try:
                self.store.remove(model)
            except OSError as exc:
                QMessageBox.critical(self, "Could not remove model", str(exc))
                return
            self.selected_model_changed.emit("")
            self._refresh(select_model_id=model.model_id)


    class ArtworkDropLabel(QLabel):
        image_dropped = Signal(str)
        activated = Signal()

        def __init__(self, placeholder: str, parent=None) -> None:
            super().__init__(parent)
            self._placeholder = placeholder
            self._image_path: Path | None = None
            self.setAcceptDrops(True)
            self.setAlignment(Qt.AlignCenter)
            self.setFrameShape(QLabel.Panel)
            self.setFrameShadow(QLabel.Sunken)
            self.setMinimumHeight(120)
            self.setWordWrap(True)
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Click to choose an image, or drag an image file here.")
            self.set_image_path(None)

        def hasHeightForWidth(self) -> bool:
            return True

        def heightForWidth(self, width: int) -> int:
            return width

        def sizeHint(self) -> QSize:
            return QSize(280, 280)

        def minimumSizeHint(self) -> QSize:
            return QSize(190, 190)

        def set_image_path(self, path: Path | None) -> bool:
            self._image_path = path
            if path is not None:
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    self._render_pixmap(pixmap)
                    self.setToolTip(f"{path.name}\nClick or drop another image to replace it.")
                    return True
            self.clear()
            self.setText(self._placeholder)
            self.setToolTip("Click to choose an image, or drag an image file here.")
            return path is None

        def resizeEvent(self, event) -> None:  # pragma: no cover - visual behavior
            super().resizeEvent(event)
            if self._image_path is None:
                return
            pixmap = QPixmap(str(self._image_path))
            if not pixmap.isNull():
                self._render_pixmap(pixmap)

        def mousePressEvent(self, event) -> None:  # pragma: no cover - GUI behavior
            if event.button() == Qt.LeftButton:
                self.activated.emit()
                event.accept()
                return
            super().mousePressEvent(event)

        def dragEnterEvent(self, event) -> None:  # pragma: no cover - GUI behavior
            if _image_path_from_mime(event.mimeData()) is not None:
                event.acceptProposedAction()
                return
            event.ignore()

        def dragMoveEvent(self, event) -> None:  # pragma: no cover - GUI behavior
            if _image_path_from_mime(event.mimeData()) is not None:
                event.acceptProposedAction()
                return
            event.ignore()

        def dropEvent(self, event) -> None:  # pragma: no cover - GUI behavior
            path = _image_path_from_mime(event.mimeData())
            if path is None:
                event.ignore()
                return
            self.image_dropped.emit(str(path))
            event.acceptProposedAction()

        def _render_pixmap(self, pixmap: QPixmap) -> None:
            available = self.contentsRect().size() - QSize(12, 12)
            if available.width() <= 0 or available.height() <= 0:
                return
            self.setText("")
            self.setPixmap(
                pixmap.scaled(
                    available,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )


    class ChapterTableWidget(QTableWidget):
        rows_reordered = Signal(list)
        image_dropped = Signal(int, str)
        audio_folder_dropped = Signal(str)

        def dragEnterEvent(self, event) -> None:  # pragma: no cover - GUI behavior
            if _audio_folder_from_mime(event.mimeData()) is not None:
                event.acceptProposedAction()
                return
            if _image_path_from_mime(event.mimeData()) is not None:
                event.acceptProposedAction()
                return
            super().dragEnterEvent(event)

        def dragMoveEvent(self, event) -> None:  # pragma: no cover - GUI behavior
            if _audio_folder_from_mime(event.mimeData()) is not None:
                event.acceptProposedAction()
                return
            if _image_path_from_mime(event.mimeData()) is not None:
                index = self.indexAt(event.position().toPoint())
                if index.isValid() and index.column() == 5:
                    event.acceptProposedAction()
                    return
                event.ignore()
                return
            super().dragMoveEvent(event)

        def dropEvent(self, event) -> None:  # pragma: no cover - GUI behavior
            audio_folder = _audio_folder_from_mime(event.mimeData())
            if audio_folder is not None:
                self.audio_folder_dropped.emit(str(audio_folder))
                event.acceptProposedAction()
                return
            image_path = _image_path_from_mime(event.mimeData())
            if image_path is not None:
                index = self.indexAt(event.position().toPoint())
                if index.isValid() and index.column() == 5:
                    self.image_dropped.emit(index.row(), str(image_path))
                    event.acceptProposedAction()
                else:
                    event.ignore()
                return
            super().dropEvent(event)
            ordered_keys: list[str] = []
            for row in range(self.rowCount()):
                item = self.item(row, 0)
                if item is None:
                    continue
                chapter_key = item.data(Qt.UserRole)
                if chapter_key is not None:
                    ordered_keys.append(chapter_key)
            self.rows_reordered.emit(ordered_keys)

    class EncapWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            QApplication.setApplicationName("EnCap")
            QApplication.setApplicationDisplayName("EnCap")
            QApplication.setOrganizationName("EnCap")
            self.setWindowTitle("EnCap Next")
            self.resize(1240, 900)
            self.setMinimumSize(1080, 760)

            try:
                ensure_lame()
                lame_available = True
            except EncapError:
                lame_available = False
            audio_toolbox_available = (
                sys.platform == "darwin" and media_encoder_available("aac_at")
            )
            self.capabilities = CapabilityFlags(
                apple_transcription_available=apple_transcription_available(),
                apple_ai_available=False,
                lame_available=lame_available,
                audio_toolbox_aac_available=audio_toolbox_available,
                audio_toolbox_aac_implementation=(
                    apple_aac_encoder_implementation() if audio_toolbox_available else ""
                ),
            )
            self.model_store = TranscriptionModelStore()
            self.project: ProjectDocument | None = None
            self._updating_chapter_table = False
            self._chapter_url_states: dict[str, tuple[str, str]] = {}
            self._url_validation_timer = QTimer(self)
            self._url_validation_timer.setSingleShot(True)
            self._url_validation_timer.setInterval(600)
            self._url_validation_timer.timeout.connect(self._run_pending_url_validation)
            self._url_validation_request_id = 0
            self._pending_url_validation: tuple[int, str, str] | None = None
            self._thread_pool = QThreadPool.globalInstance()
            self._sparkle_updater = None
            self._update_check_is_manual = False
            self._transcription_worker: TranscriptionWorker | None = None
            self._model_manager_dialog: ModelManagerDialog | None = None
            self._appearance_refresh_timer = QTimer(self)
            self._appearance_refresh_timer.setSingleShot(True)
            self._appearance_refresh_timer.setInterval(0)
            self._appearance_refresh_timer.timeout.connect(self._refresh_appearance)

            self.podcast_edit: QLineEdit
            self.episode_edit: QLineEdit
            self.summary_edit: QTextEdit
            self.artwork_label: ArtworkDropLabel
            self.format_box: QComboBox
            self.quality_box: QComboBox
            self.encoder_box: QComboBox
            self.channels_box: QComboBox
            self.chapter_table: ChapterTableWidget
            self.transcript_edit: QPlainTextEdit
            self.transcript_segment_table: QTableWidget
            self.transcription_provider_box: QComboBox
            self.transcribe_button: QPushButton
            self.manage_models_button: QPushButton
            self.log_output: QPlainTextEdit
            self.status_bar: QStatusBar
            self.activity_tabs: QTabWidget
            self.process_audio_page: QWidget
            self.transcribe_page: TranscribeWorkspace
            self.log_dock: QDockWidget
            self.log_action: QAction
            self.toolbar_actions: dict[str, QAction]

            self._build_ui()
            QApplication.instance().installEventFilter(self)
            self._refresh_quality_options()
            if self.capabilities.audio_toolbox_aac_available:
                self.append_log(
                    "Apple AudioToolbox AAC: "
                    f"{self.capabilities.audio_toolbox_aac_implementation}. "
                    "Highest codec-quality mode enabled."
                )
            self._set_status("Import an audio folder to begin.")
            self._initialize_updates()

        def eventFilter(self, watched, event):
            if watched is QApplication.instance() and event.type() in {
                QEvent.ApplicationPaletteChange,
                QEvent.ThemeChange,
            }:
                self._schedule_appearance_refresh()
            return super().eventFilter(watched, event)

        def changeEvent(self, event) -> None:
            super().changeEvent(event)
            if event.type() in {
                QEvent.ApplicationPaletteChange,
                QEvent.PaletteChange,
                QEvent.ThemeChange,
            }:
                self._schedule_appearance_refresh()

        def _schedule_appearance_refresh(self) -> None:
            # Qt resolves palette(...) values when it polishes a stylesheet.
            # Wait until the platform palette change has propagated, and restart
            # the timer when macOS sends more than one appearance notification.
            if hasattr(self, "activity_tabs"):
                self.setUpdatesEnabled(False)
            self._appearance_refresh_timer.start()

        def _refresh_appearance(self) -> None:
            if not hasattr(self, "activity_tabs"):
                return

            # Prevent an intermediate frame where native controls have the new
            # appearance but the palette-based stylesheets still have the old one.
            self.setUpdatesEnabled(False)
            try:
                activity_style = self.activity_tabs.styleSheet()
                self.activity_tabs.setStyleSheet("")
                self.activity_tabs.setStyleSheet(activity_style)
                self.transcribe_page.refresh_appearance()
            finally:
                self.setUpdatesEnabled(True)
            self.update()

        def closeEvent(self, event) -> None:  # pragma: no cover - GUI lifecycle
            if hasattr(self, "transcribe_page"):
                self.transcribe_page.stop_playback()
            if self.project is not None:
                cleanup_loaded_project(self.project)
            super().closeEvent(event)

        def _build_ui(self) -> None:
            self._build_actions()
            self._build_toolbar()
            self._build_log_dock()
            self._build_menus()

            central = QWidget()
            layout = QVBoxLayout(central)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(10)

            self.activity_tabs = QTabWidget()
            self.activity_tabs.setObjectName("activityTabs")
            self.activity_tabs.setTabPosition(QTabWidget.North)
            self.activity_tabs.setMovable(False)
            self.activity_tabs.setDocumentMode(False)
            self.activity_tabs.tabBar().setDrawBase(False)
            self.activity_tabs.tabBar().setExpanding(False)
            self.activity_tabs.setStyleSheet(
                "QTabWidget#activityTabs { background: palette(window); }"
                "QTabWidget#activityTabs::pane {"
                "  background: palette(window);"
                "  border: 1px solid palette(mid);"
                "  border-radius: 3px;"
                "  top: -1px;"
                "}"
                "QTabWidget#activityTabs::tab-bar { alignment: center; }"
                "QTabWidget#activityTabs QTabBar { background: transparent; }"
                "QTabWidget#activityTabs QTabBar::tab {"
                "  background: palette(button);"
                "  border: 1px solid palette(mid);"
                "  color: palette(button-text);"
                "  min-width: 118px;"
                "  padding: 5px 18px;"
                "  margin-top: 5px;"
                "  margin-bottom: 5px;"
                "}"
                "QTabWidget#activityTabs QTabBar::tab:first {"
                "  border-top-left-radius: 5px;"
                "  border-bottom-left-radius: 5px;"
                "}"
                "QTabWidget#activityTabs QTabBar::tab:last {"
                "  border-top-right-radius: 5px;"
                "  border-bottom-right-radius: 5px;"
                "  margin-left: -1px;"
                "}"
                "QTabWidget#activityTabs QTabBar::tab:selected {"
                "  background: palette(highlight);"
                "  border-color: palette(highlight);"
                "  color: palette(highlighted-text);"
                "}"
                "QTabWidget#activityTabs QTabBar::tab:hover:!selected {"
                "  background: palette(midlight);"
                "}"
            )
            self.process_audio_page = self._build_process_audio_page()
            self.transcribe_page = self._build_transcribe_page()
            self.activity_tabs.addTab(self.process_audio_page, "Process Audio")
            self.activity_tabs.addTab(self.transcribe_page, "Transcribe")
            self.activity_tabs.currentChanged.connect(self._update_activity_ui)
            layout.addWidget(self.activity_tabs, stretch=1)

            self.setCentralWidget(central)
            self.status_bar = QStatusBar()
            self.setStatusBar(self.status_bar)
            self._update_activity_ui(0)

        def _build_actions(self) -> None:
            action_specs = [
                ("import_audio", "Import Audio Folder…", self.import_audio_folder),
                ("open_project", "Open Project…", self.open_project),
                ("save_project", "Save Project…", self.save_project_file),
                ("choose_artwork", "Choose Artwork…", self.choose_artwork),
                ("export_all", "All…", self.export_all),
                ("export_audio", "Audio…", self.export_audio),
                ("export_txt", "Transcript as TXT…", lambda: self.export_transcript("txt")),
                ("export_srt", "Transcript as SRT…", lambda: self.export_transcript("srt")),
                ("transcribe", "Transcribe", self.transcribe_project),
                ("ai_summary", "Summary", self.generate_ai_summary),
                ("ai_title", "Title Suggestion", self.generate_ai_title),
            ]
            self.toolbar_actions = {}
            for key, label, callback in action_specs:
                action = QAction(label, self)
                action.setObjectName(f"{key}Action")
                action.triggered.connect(callback)
                if key.startswith("ai_"):
                    action.setEnabled(False)
                self.toolbar_actions[key] = action
            self.transcribe_action = self.toolbar_actions["transcribe"]
            self.toolbar_actions["import_audio"].setShortcut(QKeySequence("Ctrl+I"))
            self.toolbar_actions["open_project"].setShortcut(QKeySequence.StandardKey.Open)
            self.toolbar_actions["save_project"].setShortcut(QKeySequence.StandardKey.Save)
            self.toolbar_actions["export_all"].setShortcut(QKeySequence("Ctrl+Shift+E"))
            self.toolbar_actions["export_audio"].setShortcut(QKeySequence("Ctrl+E"))
            self.toolbar_actions["export_txt"].setShortcut(QKeySequence("Ctrl+Alt+T"))
            self.toolbar_actions["export_srt"].setShortcut(QKeySequence("Ctrl+Alt+S"))
            self.toolbar_actions["transcribe"].setShortcut(QKeySequence("Ctrl+Shift+T"))
            for key in ("export_all", "export_audio", "export_txt", "export_srt"):
                self.toolbar_actions[key].setEnabled(False)

            self.manage_models_action = QAction("Manage Models…", self)
            self.manage_models_action.setObjectName("manageModelsAction")
            self.manage_models_action.setShortcut(QKeySequence("Ctrl+Shift+M"))
            self.manage_models_action.triggered.connect(self.show_model_manager)

            self.quit_action = QAction("Quit EnCap", self)
            self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
            self.quit_action.setMenuRole(QAction.MenuRole.QuitRole)
            self.quit_action.triggered.connect(QApplication.instance().quit)

            self.edit_actions: list[tuple[QAction, str]] = []
            for label, shortcut, method_name in [
                ("Undo", QKeySequence.StandardKey.Undo, "undo"),
                ("Redo", QKeySequence.StandardKey.Redo, "redo"),
                ("Cut", QKeySequence.StandardKey.Cut, "cut"),
                ("Copy", QKeySequence.StandardKey.Copy, "copy"),
                ("Paste", QKeySequence.StandardKey.Paste, "paste"),
                ("Select All", QKeySequence.StandardKey.SelectAll, "selectAll"),
            ]:
                action = QAction(label, self)
                action.setShortcut(shortcut)
                action.triggered.connect(
                    lambda _checked=False, method=method_name: self._invoke_focused_widget(method)
                )
                self.edit_actions.append((action, method_name))

        def _build_menus(self) -> None:
            menu_bar = self.menuBar()
            menu_bar.setNativeMenuBar(
                sys.platform == "darwin" and QApplication.platformName() == "cocoa"
            )

            self.file_menu = QMenu("&File", menu_bar)
            menu_bar.addMenu(self.file_menu)
            self.file_menu.addAction(self.toolbar_actions["import_audio"])
            self.file_menu.addAction(self.toolbar_actions["open_project"])
            self.file_menu.addSeparator()
            self.file_menu.addAction(self.toolbar_actions["save_project"])
            self.export_menu = QMenu("Export", self.file_menu)
            self.file_menu.addMenu(self.export_menu)
            self.export_menu.addAction(self.toolbar_actions["export_all"])
            self.export_menu.addSeparator()
            self.export_menu.addAction(self.toolbar_actions["export_audio"])
            self.export_menu.addAction(self.toolbar_actions["export_txt"])
            self.export_menu.addAction(self.toolbar_actions["export_srt"])
            self.file_menu.addSeparator()
            self.file_menu.addAction(self.quit_action)

            self.edit_menu = QMenu("&Edit", menu_bar)
            menu_bar.addMenu(self.edit_menu)
            for index, (action, _method_name) in enumerate(self.edit_actions):
                if index in {2, 5}:
                    self.edit_menu.addSeparator()
                self.edit_menu.addAction(action)
            self.edit_menu.aboutToShow.connect(self._update_edit_menu)
            self.edit_menu.addSeparator()

            self.chapter_menu = QMenu("Chapter", self.edit_menu)
            self.edit_menu.addMenu(self.chapter_menu)
            for label, callback, shortcut in [
                ("Add Chapter", self.add_chapter, "Ctrl+Shift+N"),
                ("Remove Chapter", self.remove_chapter, ""),
                ("Move Up", lambda: self.move_chapter(-1), "Ctrl+Alt+Up"),
                ("Move Down", lambda: self.move_chapter(1), "Ctrl+Alt+Down"),
            ]:
                action = QAction(label, self)
                if shortcut:
                    action.setShortcut(QKeySequence(shortcut))
                action.triggered.connect(callback)
                self.chapter_menu.addAction(action)

            self.transcription_menu = QMenu("Transcription", self.edit_menu)
            self.edit_menu.addMenu(self.transcription_menu)
            self.transcription_menu.addAction(self.transcribe_action)
            self.transcription_menu.addAction(self.manage_models_action)
            self.transcription_menu.addSeparator()
            self.transcription_menu.addAction(self.toolbar_actions["ai_summary"])
            self.transcription_menu.addAction(self.toolbar_actions["ai_title"])

            self.view_menu = QMenu("&View", menu_bar)
            menu_bar.addMenu(self.view_menu)
            self.workspace_action_group = QActionGroup(self)
            self.workspace_action_group.setExclusive(True)
            self.process_audio_view_action = QAction("Process Audio", self)
            self.process_audio_view_action.setCheckable(True)
            self.process_audio_view_action.setShortcut(QKeySequence("Ctrl+1"))
            self.transcribe_view_action = QAction("Transcribe", self)
            self.transcribe_view_action.setCheckable(True)
            self.transcribe_view_action.setShortcut(QKeySequence("Ctrl+2"))
            self.workspace_action_group.addAction(self.process_audio_view_action)
            self.workspace_action_group.addAction(self.transcribe_view_action)
            self.process_audio_view_action.triggered.connect(
                lambda: self.activity_tabs.setCurrentWidget(self.process_audio_page)
            )
            self.transcribe_view_action.triggered.connect(
                lambda: self.activity_tabs.setCurrentWidget(self.transcribe_page)
            )
            self.view_menu.addAction(self.process_audio_view_action)
            self.view_menu.addAction(self.transcribe_view_action)
            self.view_menu.addSeparator()
            self.log_action.setShortcut(QKeySequence("Ctrl+Shift+L"))
            self.view_menu.addAction(self.log_action)

            self.window_menu = QMenu("&Window", menu_bar)
            menu_bar.addMenu(self.window_menu)
            self.minimize_action = QAction("Minimize", self)
            self.minimize_action.setShortcut(QKeySequence("Ctrl+M"))
            self.minimize_action.triggered.connect(self.showMinimized)
            self.zoom_action = QAction("Zoom" if sys.platform == "darwin" else "Maximize", self)
            self.zoom_action.triggered.connect(self._toggle_zoomed)
            self.full_screen_action = QAction("Enter Full Screen", self)
            self.full_screen_action.setShortcut(QKeySequence.StandardKey.FullScreen)
            self.full_screen_action.triggered.connect(self._toggle_full_screen)
            self.bring_front_action = QAction("Bring All to Front", self)
            self.bring_front_action.triggered.connect(self._bring_all_to_front)
            self.window_menu.addAction(self.minimize_action)
            self.window_menu.addAction(self.zoom_action)
            self.window_menu.addAction(self.full_screen_action)
            self.window_menu.addSeparator()
            self.window_menu.addAction(self.bring_front_action)
            self.window_menu.aboutToShow.connect(self._update_window_menu)

            self.help_menu = QMenu("&Help", menu_bar)
            menu_bar.addMenu(self.help_menu)
            self.check_updates_action = QAction("Check for Updates…", self)
            self.check_updates_action.setMenuRole(QAction.MenuRole.NoRole)
            self.check_updates_action.triggered.connect(
                lambda _checked=False: self.check_for_updates(manual=True)
            )
            self.help_menu.addAction(self.check_updates_action)
            self.help_menu.addSeparator()
            self.about_action = QAction("About EnCap", self)
            self.about_action.setMenuRole(QAction.MenuRole.AboutRole)
            self.about_action.triggered.connect(self.show_about)
            self.help_menu.addAction(self.about_action)

        def _invoke_focused_widget(self, method_name: str) -> None:
            widget = QApplication.focusWidget()
            method = getattr(widget, method_name, None) if widget is not None else None
            if callable(method):
                method()

        def _update_edit_menu(self) -> None:
            widget = QApplication.focusWidget()
            for action, method_name in self.edit_actions:
                action.setEnabled(callable(getattr(widget, method_name, None)))

        def _toggle_zoomed(self) -> None:
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()

        def _toggle_full_screen(self) -> None:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()

        def _bring_all_to_front(self) -> None:
            for widget in QApplication.topLevelWidgets():
                if widget.isWindow():
                    widget.raise_()
                    widget.activateWindow()

        def _update_window_menu(self) -> None:
            if sys.platform != "darwin":
                self.zoom_action.setText("Restore" if self.isMaximized() else "Maximize")
            self.full_screen_action.setText(
                "Exit Full Screen" if self.isFullScreen() else "Enter Full Screen"
            )

        def _initialize_updates(self) -> None:
            if sys.platform == "darwin":
                try:
                    if __package__ in {None, ""}:
                        from encap.sparkle_updater import SparkleUpdater
                    else:
                        from .sparkle_updater import SparkleUpdater
                    self._sparkle_updater = SparkleUpdater()
                except Exception as exc:
                    self.append_log(f"Automatic updates unavailable in this build: {exc}")
                return
            QTimer.singleShot(5000, lambda: self.check_for_updates(manual=False))

        def check_for_updates(self, *, manual: bool) -> None:
            if sys.platform == "darwin":
                if self._sparkle_updater is None:
                    if manual:
                        QMessageBox.warning(
                            self,
                            "Updates unavailable",
                            "Sparkle is not configured in this development build.",
                        )
                    return
                try:
                    self._sparkle_updater.check_for_updates()
                except Exception as exc:
                    QMessageBox.warning(self, "Update check failed", str(exc))
                return

            if not self.check_updates_action.isEnabled():
                return
            self._update_check_is_manual = manual
            self.check_updates_action.setEnabled(False)
            if manual:
                self._set_status("Checking GitHub for updates…")
            worker = UpdateCheckWorker()
            worker.signals.resolved.connect(self._handle_update_check)
            self._thread_pool.start(worker)

        def _handle_update_check(self, release: UpdateRelease | None, error: str) -> None:
            manual = self._update_check_is_manual
            self.check_updates_action.setEnabled(True)
            if error:
                self.append_log(f"Update check failed: {error}")
                if manual:
                    QMessageBox.warning(self, "Update check failed", error)
                    self._set_status("Update check failed.")
                return
            if release is None:
                if manual:
                    QMessageBox.information(
                        self,
                        "EnCap is up to date",
                        f"You are running the latest version ({__version__}).",
                    )
                    self._set_status("EnCap is up to date.")
                return
            self._offer_update(release)

        def _offer_update(self, release: UpdateRelease) -> None:
            notes = release.notes.strip()
            if len(notes) > 1200:
                notes = notes[:1197] + "…"
            detail = f"EnCap {release.version} is available (installed: {__version__})."
            if notes:
                detail += f"\n\n{notes}"
            if installed_app_dir() is None:
                detail += "\n\nOpen the GitHub release page to download it?"
                response = QMessageBox.question(
                    self,
                    "Update available",
                    detail,
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if response == QMessageBox.Yes:
                    QDesktopServices.openUrl(QUrl(release.release_url))
                return

            detail += "\n\nDownload, install, and restart now?"
            response = QMessageBox.question(
                self,
                "Update available",
                detail,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if response != QMessageBox.Yes:
                return
            self.check_updates_action.setEnabled(False)
            self._set_status(f"Downloading EnCap {release.version}…")
            worker = UpdateDownloadWorker(release)
            worker.signals.completed.connect(self._handle_prepared_update)
            self._thread_pool.start(worker)

        def _handle_prepared_update(self, prepared: PreparedUpdate | None, error: str) -> None:
            if error or prepared is None:
                self.check_updates_action.setEnabled(True)
                message = error or "The update could not be prepared."
                self.append_log(f"Update installation failed: {message}")
                QMessageBox.critical(self, "Update failed", message)
                self._set_status("Update installation failed.")
                return
            try:
                launch_update_helper(prepared)
            except Exception as exc:
                self.check_updates_action.setEnabled(True)
                QMessageBox.critical(self, "Update failed", str(exc))
                self._set_status("Update installation failed.")
                return
            self._set_status(f"Installing EnCap {prepared.version}…")
            QApplication.instance().quit()

        def show_about(self) -> None:
            QMessageBox.about(
                self,
                "About EnCap",
                f"EnCap {__version__}\nEncoder with Chapter Assembly Protocol",
            )

        def _build_toolbar(self) -> None:
            self.main_toolbar = QToolBar("Main")
            self.main_toolbar.setObjectName("mainToolbar")
            self.main_toolbar.setMovable(False)
            self.addToolBar(self.main_toolbar)
            self._populate_main_toolbar(is_process_audio=True)

        def _populate_main_toolbar(self, *, is_process_audio: bool) -> None:
            self.main_toolbar.clear()
            process_only = {"choose_artwork", "export_audio", "ai_summary", "ai_title"}
            for key in [
                "import_audio",
                "open_project",
                "save_project",
                "choose_artwork",
                "export_audio",
                "export_txt",
                "export_srt",
                "transcribe",
                "ai_summary",
                "ai_title",
            ]:
                if key in process_only and not is_process_audio:
                    continue
                self.main_toolbar.addAction(self.toolbar_actions[key])

        def _build_log_dock(self) -> None:
            self.log_output = QPlainTextEdit()
            self.log_output.setObjectName("logOutput")
            self.log_output.setReadOnly(True)

            self.log_dock = QDockWidget("Log", self)
            self.log_dock.setObjectName("logDock")
            self.log_dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.RightDockWidgetArea)
            self.log_dock.setWidget(self.log_output)
            self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)
            self.log_dock.hide()

            self.log_action = self.log_dock.toggleViewAction()
            self.log_action.setObjectName("logAction")
            self.log_action.setText("Log")

        def _build_process_audio_page(self) -> QWidget:
            container = QWidget()
            container.setObjectName("processAudioPage")
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 8, 0, 0)
            layout.setSpacing(10)
            layout.addWidget(self._build_metadata_group())
            layout.addWidget(self._build_chapters_tab(), stretch=1)
            return container

        def _build_transcribe_page(self) -> TranscribeWorkspace:
            workspace = TranscribeWorkspace()
            workspace.setObjectName("transcribePage")
            workspace.transcribe_requested.connect(self.transcribe_project)
            workspace.manage_models_requested.connect(self.show_model_manager)
            workspace.export_requested.connect(self.export_transcript)
            workspace.transcript_content_changed.connect(self._update_export_actions)

            self.transcription_provider_box = workspace.provider_box
            self.transcription_provider_box.currentIndexChanged.connect(
                self._update_transcription_controls
            )
            self.manage_models_button = workspace.manage_models_button
            self.transcribe_button = workspace.transcribe_button
            self.transcript_edit = workspace.editor
            self.transcript_segment_table = workspace.segment_table
            self._refresh_transcription_providers()
            return workspace

        def _update_activity_ui(self, index: int) -> None:
            is_process_audio = index == 0
            self._populate_main_toolbar(is_process_audio=is_process_audio)
            self.chapter_menu.menuAction().setEnabled(is_process_audio)
            self.process_audio_view_action.setChecked(is_process_audio)
            self.transcribe_view_action.setChecked(not is_process_audio)

        def _build_metadata_group(self) -> QGroupBox:
            group = QGroupBox("Episode")
            group_layout = QHBoxLayout(group)
            group_layout.setContentsMargins(10, 12, 10, 10)
            group_layout.setSpacing(14)

            details_widget = QWidget()
            grid = QGridLayout(details_widget)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(8)
            grid.setColumnStretch(1, 1)

            self.podcast_edit = QLineEdit()
            self.episode_edit = QLineEdit()

            self.format_box = QComboBox()
            self.format_box.addItem("MP3", "mp3")
            self.format_box.addItem("AAC", "aac")
            self.format_box.setMaximumWidth(105)
            self.format_box.setToolTip("Select the audio codec. This determines which encoders are available.")

            self.quality_box = QComboBox()
            self.quality_box.setMaximumWidth(115)
            self.quality_box.setToolTip("Select the final bitrate, balancing quality and file size.")

            self.summary_edit = QTextEdit()
            self.summary_edit.setMinimumHeight(150)

            self.artwork_label = ArtworkDropLabel("No artwork selected\nDrop an image here")
            self.artwork_label.setObjectName("episodeArtworkPreview")
            self.artwork_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.artwork_label.setMinimumSize(190, 190)
            self.artwork_label.setMaximumSize(360, 360)
            self.artwork_label.activated.connect(self.choose_artwork)
            self.artwork_label.image_dropped.connect(self._set_episode_artwork_from_drop)

            self.encoder_box = QComboBox()
            self.encoder_box.setMinimumWidth(245)
            self.encoder_box.setMaximumWidth(285)
            self.encoder_box.setToolTip("Select an encoder supported by the chosen codec.")

            self.channels_box = QComboBox()
            self.channels_box.addItem("Stereo", 2)
            self.channels_box.addItem("Mono", 1)
            self.channels_box.setMaximumWidth(105)
            self.channels_box.setToolTip("Select Stereo or Mono. This determines the available bitrates.")

            self.format_box.currentIndexChanged.connect(
                lambda _index: self._refresh_encoder_options()
            )
            self.encoder_box.currentIndexChanged.connect(
                lambda _index: self._update_encoder_tooltip()
            )
            self.channels_box.currentIndexChanged.connect(
                lambda _index: self._refresh_bitrate_options()
            )

            grid.addWidget(QLabel("Podcast title"), 0, 0)
            grid.addWidget(self.podcast_edit, 0, 1)
            grid.addWidget(QLabel("Episode title"), 1, 0)
            grid.addWidget(self.episode_edit, 1, 1)
            grid.addWidget(QLabel("Summary"), 2, 0, alignment=Qt.AlignTop)
            grid.addWidget(self.summary_edit, 2, 1)

            settings_layout = QHBoxLayout()
            settings_layout.setContentsMargins(0, 0, 0, 0)
            settings_layout.setSpacing(7)
            settings_layout.addWidget(self.format_box)
            settings_layout.addSpacing(8)
            settings_layout.addWidget(QLabel("Encoder"))
            settings_layout.addWidget(self.encoder_box)
            settings_layout.addSpacing(8)
            settings_layout.addWidget(QLabel("Channels"))
            settings_layout.addWidget(self.channels_box)
            settings_layout.addSpacing(8)
            settings_layout.addWidget(QLabel("Bitrate"))
            settings_layout.addWidget(self.quality_box)
            settings_layout.addStretch(1)
            grid.addWidget(QLabel("Format/Codec"), 3, 0)
            grid.addLayout(settings_layout, 3, 1)

            artwork_widget = QWidget()
            artwork_widget.setObjectName("episodeArtworkColumn")
            artwork_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            artwork_widget.setMaximumWidth(370)
            artwork_box = QVBoxLayout()
            artwork_box.setContentsMargins(0, 0, 0, 0)
            artwork_box.setSpacing(5)
            artwork_box.addWidget(QLabel("Artwork"))
            artwork_box.addWidget(self.artwork_label, alignment=Qt.AlignTop | Qt.AlignHCenter)
            artwork_box.addStretch(1)
            artwork_widget.setLayout(artwork_box)

            group_layout.addWidget(details_widget, stretch=1)
            group_layout.addWidget(artwork_widget, stretch=0, alignment=Qt.AlignTop)

            self._refresh_encoder_options()

            return group

        def _build_chapters_tab(self) -> QWidget:
            container = QWidget()
            layout = QVBoxLayout(container)

            self.chapter_table = ChapterTableWidget(0, 6)
            self.chapter_table.setHorizontalHeaderLabels(
                ["Start Time", "Duration", "Chapter #", "Chapter Title", "Link URL", "Image"]
            )
            self.chapter_table.setSelectionBehavior(QAbstractItemView.SelectItems)
            self.chapter_table.setSelectionMode(QTableWidget.SingleSelection)
            self.chapter_table.setEditTriggers(
                QAbstractItemView.EditKeyPressed
                | QAbstractItemView.AnyKeyPressed
                | QAbstractItemView.SelectedClicked
            )
            self.chapter_table.setDragEnabled(True)
            self.chapter_table.setAcceptDrops(True)
            self.chapter_table.viewport().setAcceptDrops(True)
            self.chapter_table.setDropIndicatorShown(True)
            self.chapter_table.setDragDropOverwriteMode(False)
            self.chapter_table.setDragDropMode(QAbstractItemView.InternalMove)
            self.chapter_table.setIconSize(QSize(20, 20))
            self.chapter_table.verticalHeader().setDefaultSectionSize(30)
            header = self.chapter_table.horizontalHeader()
            header.setStretchLastSection(False)
            for column in (0, 1, 2):
                header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(3, QHeaderView.Stretch)
            header.setSectionResizeMode(4, QHeaderView.Stretch)
            header.setSectionResizeMode(5, QHeaderView.Fixed)
            self.chapter_table.setColumnWidth(5, 86)
            self.chapter_table.itemChanged.connect(self.on_chapter_item_changed)
            self.chapter_table.cellDoubleClicked.connect(self.on_chapter_cell_double_clicked)
            self.chapter_table.cellClicked.connect(self.on_chapter_cell_clicked)
            self.chapter_table.rows_reordered.connect(self.on_chapter_rows_reordered)
            self.chapter_table.image_dropped.connect(self._set_chapter_image_from_drop)
            self.chapter_table.audio_folder_dropped.connect(
                lambda folder: self._import_audio_path(Path(folder))
            )
            layout.addWidget(self.chapter_table, stretch=1)
            return container

        def _set_status(self, message: str) -> None:
            self.status_bar.showMessage(message)

        def append_log(self, message: str) -> None:
            self.log_output.appendPlainText(message)

        def _refresh_transcription_providers(self, preferred_id: str | None = None) -> None:
            if not hasattr(self, "transcription_provider_box"):
                return
            current_id = preferred_id or self.transcription_provider_box.currentData()
            selected_model_id = self.model_store.selected_model_id()
            self.transcription_provider_box.blockSignals(True)
            self.transcription_provider_box.clear()
            if self.capabilities.apple_transcription_available:
                self.transcription_provider_box.addItem(
                    "Apple On-Device (system managed)",
                    APPLE_PROVIDER_ID,
                )
            for model in WHISPER_MODELS:
                if self.model_store.is_installed(model):
                    self.transcription_provider_box.addItem(model.name, model.model_id)
            if self.transcription_provider_box.count() == 0:
                self.transcription_provider_box.addItem(
                    "No local transcription engine available",
                    None,
                )
            wanted_id = current_id or selected_model_id
            if wanted_id is not None:
                index = self.transcription_provider_box.findData(wanted_id)
                if index >= 0:
                    self.transcription_provider_box.setCurrentIndex(index)
            self.transcription_provider_box.blockSignals(False)
            self._update_transcription_controls()

        def _update_transcription_controls(self, *_args) -> None:
            if not hasattr(self, "transcribe_button"):
                return
            available = self.transcription_provider_box.currentData() is not None
            idle = self._transcription_worker is None
            has_project = self.project is not None and bool(self.project.audio_sources)
            enabled = available and idle and has_project
            self.transcribe_button.setEnabled(enabled)
            if hasattr(self, "transcribe_page"):
                self.transcribe_page.set_transcription_enabled(enabled)
            if hasattr(self, "transcribe_action"):
                self.transcribe_action.setEnabled(enabled)
            self._update_export_actions()

        def _update_export_actions(
            self,
            transcript_available: bool | None = None,
        ) -> None:
            has_audio = self.project is not None and bool(self.project.audio_sources)
            if transcript_available is None:
                transcript_available = bool(
                    self.project is not None
                    and any(
                        segment.text.strip()
                        for segment in self.project.transcript_segments
                    )
                )
            self.toolbar_actions["export_audio"].setEnabled(has_audio)
            self.toolbar_actions["export_txt"].setEnabled(
                has_audio and transcript_available
            )
            self.toolbar_actions["export_srt"].setEnabled(
                has_audio and transcript_available
            )
            self.toolbar_actions["export_all"].setEnabled(
                has_audio and transcript_available
            )

        def show_model_manager(self) -> None:
            dialog = ModelManagerDialog(self.model_store, self)
            self._model_manager_dialog = dialog
            dialog.selected_model_changed.connect(
                lambda model_id: self._refresh_transcription_providers(model_id or None)
            )
            dialog.exec()
            self._model_manager_dialog = None
            self._refresh_transcription_providers()

        def transcribe_project(self) -> None:
            if self.project is None or not self.project.audio_sources:
                QMessageBox.warning(self, "No project", "Import audio before transcribing.")
                return
            if self._transcription_worker is not None:
                return
            provider_id = self.transcription_provider_box.currentData()
            if not isinstance(provider_id, str):
                response = QMessageBox.question(
                    self,
                    "Download a transcription model?",
                    "No local transcription engine is available. Open the model manager?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if response == QMessageBox.Yes:
                    self.show_model_manager()
                return
            self.transcribe_page.sync_to_project()
            if self.transcribe_page.has_transcript_content():
                response = QMessageBox.question(
                    self,
                    "Replace existing transcript?",
                    "Transcription will replace the current transcript. Continue?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if response != QMessageBox.Yes:
                    return

            worker = TranscriptionWorker(
                self.project.audio_sources,
                provider_id,
                self.model_store,
            )
            self._transcription_worker = worker
            worker.signals.progress.connect(self._handle_transcription_progress)
            worker.signals.completed.connect(self._handle_transcription_complete)
            self._update_transcription_controls()
            provider_name = self.transcription_provider_box.currentText()
            self._set_status(f"Starting transcription with {provider_name}…")
            self.append_log(f"Starting local transcription with {provider_name}.")
            self.activity_tabs.setCurrentWidget(self.transcribe_page)
            self._thread_pool.start(worker)

        def _handle_transcription_progress(self, current: int, total: int, message: str) -> None:
            suffix = f" ({current}/{total})" if total else ""
            self._set_status(message + suffix)

        def _handle_transcription_complete(self, segments, error: str) -> None:
            self._transcription_worker = None
            self._update_transcription_controls()
            if error or segments is None:
                message = error or "The transcription did not return a result."
                self.append_log(f"Transcription failed: {message}")
                QMessageBox.critical(self, "Transcription failed", message)
                self._set_status("Transcription failed.")
                return
            assert self.project is not None
            self.project.transcript_segments = list(segments)
            self._set_transcript_editor_from_project()
            self.activity_tabs.setCurrentWidget(self.transcribe_page)
            self._set_status(f"Transcription complete: {len(segments)} segment(s).")
            self.append_log(f"Local transcription completed with {len(segments)} segment(s).")

        def _set_transcript_editor_from_project(self) -> None:
            self.transcribe_page.set_project(self.project)

        def _refresh_quality_options(self) -> None:
            self._refresh_encoder_options()

        def _refresh_encoder_options(self, preferred_id: str | None = None) -> None:
            format_name = self.format_box.currentData() or "mp3"
            current_id = preferred_id or self.encoder_box.currentData()
            if format_name == "mp3":
                options = [
                    (
                        "FFmpeg MP3",
                        "ffmpeg",
                        "FFmpeg's libmp3lame encoder in its highest-quality mode.",
                    )
                ]
            else:
                options = [
                    (
                        "FFmpeg AAC",
                        "ffmpeg",
                        "FFmpeg's native AAC encoder using its highest-quality two-loop search.",
                    )
                ]
            if format_name == "mp3" and self.capabilities.lame_available:
                options.append(
                    (
                        "LAME MP3",
                        "lame",
                        "Bundled LAME MP3 in highest-quality mode; separate source files encode in parallel.",
                    )
                )
            if format_name == "aac" and self.capabilities.audio_toolbox_aac_available:
                implementation = self.capabilities.audio_toolbox_aac_implementation
                options.append(
                    (
                        "Apple AudioToolbox AAC",
                        "audio_toolbox",
                        f"macOS AudioToolbox in highest-quality mode. Detected: {implementation}.",
                    )
                )

            self.encoder_box.blockSignals(True)
            self.encoder_box.clear()
            for label, encoder_id, tooltip in options:
                self.encoder_box.addItem(label, encoder_id)
                self.encoder_box.setItemData(
                    self.encoder_box.count() - 1, tooltip, Qt.ToolTipRole
                )
            default_encoder = "lame" if format_name == "mp3" and self.capabilities.lame_available else "ffmpeg"
            wanted = normalize_encoder(current_id or default_encoder)
            index = self.encoder_box.findData(wanted)
            self.encoder_box.setCurrentIndex(index if index >= 0 else 0)
            selected_tooltip = self.encoder_box.currentData(Qt.ToolTipRole)
            if selected_tooltip:
                self.encoder_box.setToolTip(str(selected_tooltip))
            self.encoder_box.blockSignals(False)
            self._refresh_bitrate_options()

        def _update_encoder_tooltip(self) -> None:
            tooltip = self.encoder_box.currentData(Qt.ToolTipRole)
            if tooltip:
                self.encoder_box.setToolTip(str(tooltip))

        def _refresh_bitrate_options(self, preferred_bitrate: str | None = None) -> None:
            format_name = self.format_box.currentData() or "mp3"
            channels = int(self.channels_box.currentData() or 2)
            values = BITRATE_OPTIONS[format_name][channels]
            current = preferred_bitrate or self.quality_box.currentData()
            self.quality_box.blockSignals(True)
            self.quality_box.clear()
            for bitrate in values:
                self.quality_box.addItem(f"{bitrate.rstrip('k')} kbps", bitrate)
            wanted = current if current in values else values[-1]
            index = self.quality_box.findData(wanted)
            self.quality_box.setCurrentIndex(index if index >= 0 else 0)
            self.quality_box.blockSignals(False)

        def import_audio_folder(self) -> None:
            folder = QFileDialog.getExistingDirectory(self, "Select source audio folder")
            if not folder:
                return
            self._import_audio_path(Path(folder))

        def _import_audio_path(self, folder: Path) -> None:
            try:
                imported = build_project_document(
                    folder,
                    prompt_for_conversion=self.confirm_conversion,
                )
            except EncapError as exc:
                QMessageBox.critical(self, "Import failed", str(exc))
                return

            if self.project is not None and self.project.audio_sources:
                insertion = self._choose_audio_insertion(len(imported.audio_sources))
                if insertion is None:
                    cleanup_loaded_project(imported)
                    return
                self.transcribe_page.stop_playback()
                self._sync_project_from_form()
                try:
                    self._merge_imported_audio(imported, insertion)
                except EncapError as exc:
                    cleanup_loaded_project(imported)
                    QMessageBox.critical(self, "Import failed", str(exc))
                    return
                self._populate_form_from_project()
                self._set_status(
                    f"Added {len(imported.audio_sources)} audio file(s) {self._insertion_label(insertion)}."
                )
                self.append_log(
                    f"Added audio folder {folder} {self._insertion_label(insertion)}."
                )
                return

            if self.project is not None:
                self.transcribe_page.stop_playback()
                self._sync_project_from_form()
                previous_project = self.project
                inferred_channels = imported.export_settings.channels
                imported.metadata = previous_project.metadata
                imported.export_settings = previous_project.export_settings
                imported.export_settings.channels = inferred_channels
                format_name = normalize_output_format(imported.export_settings.output_format)
                valid_bitrates = BITRATE_OPTIONS[format_name][inferred_channels]
                if imported.export_settings.quality_preset not in valid_bitrates:
                    imported.export_settings.quality_preset = valid_bitrates[-1]
                imported.project_path = previous_project.project_path
                if previous_project.working_dir is not None:
                    # Loaded project artwork points into this extracted directory.
                    # Transfer its cleanup ownership so importing audio does not
                    # invalidate artwork that was selected before the audio.
                    imported.working_dir = previous_project.working_dir
                    previous_project.working_dir = None
                cleanup_loaded_project(previous_project)
            self.project = imported
            self._populate_form_from_project()
            self._set_status(f"Imported {len(imported.audio_sources)} audio file(s).")
            self.append_log(f"Imported audio folder: {folder}")

        def _choose_audio_insertion(self, file_count: int) -> str | None:
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Question)
            dialog.setWindowTitle("Add audio files")
            dialog.setText(f"How should the {file_count} new audio file(s) be added?")
            dialog.setInformativeText(
                "Chronological order uses recorder timestamps when available, then filenames."
            )
            chronological_button = dialog.addButton(
                "Chronologically", QMessageBox.ButtonRole.AcceptRole
            )
            beginning_button = dialog.addButton(
                "At Beginning", QMessageBox.ButtonRole.ActionRole
            )
            end_button = dialog.addButton("At End", QMessageBox.ButtonRole.ActionRole)
            dialog.addButton(QMessageBox.StandardButton.Cancel)
            dialog.setDefaultButton(chronological_button)
            dialog.exec()
            clicked = dialog.clickedButton()
            if clicked is chronological_button:
                return "chronological"
            if clicked is beginning_button:
                return "beginning"
            if clicked is end_button:
                return "end"
            return None

        def _merge_imported_audio(self, imported: ProjectDocument, insertion: str) -> None:
            assert self.project is not None
            if len(imported.audio_sources) != len(imported.chapters):
                raise EncapError("Imported audio files do not have matching chapters.")

            if insertion == "chronological":
                if len(self.project.audio_sources) != len(self.project.chapters):
                    raise EncapError(
                        "Chronological insertion requires one chapter per existing audio file. "
                        "Choose beginning or end for a project with additional chapter markers."
                    )
                existing_pairs = list(zip(self.project.audio_sources, self.project.chapters))
                imported_pairs = list(zip(imported.audio_sources, imported.chapters))
                combined_pairs = sorted(
                    [*existing_pairs, *imported_pairs],
                    key=lambda pair: audio_path_sort_key(Path(pair[0].display_name)),
                )
                self.project.audio_sources = [pair[0] for pair in combined_pairs]
                self.project.chapters = [pair[1] for pair in combined_pairs]
            elif insertion == "beginning":
                self.project.audio_sources = [
                    *imported.audio_sources,
                    *self.project.audio_sources,
                ]
                self.project.chapters = [*imported.chapters, *self.project.chapters]
            elif insertion == "end":
                self.project.audio_sources.extend(imported.audio_sources)
                self.project.chapters.extend(imported.chapters)
            else:
                raise EncapError(f"Unknown audio insertion mode: {insertion}")

            self.project.source_folder = None
            self._renumber_chapters()

        @staticmethod
        def _insertion_label(insertion: str) -> str:
            return {
                "chronological": "in chronological order",
                "beginning": "at the beginning",
                "end": "at the end",
            }[insertion]

        def open_project(self) -> None:
            path, _ = QFileDialog.getOpenFileName(self, "Open project", "", "EnCap Project (*.encap)")
            if not path:
                return
            try:
                project = load_project(Path(path))
            except EncapError as exc:
                QMessageBox.critical(self, "Open failed", str(exc))
                return

            if self.project is not None:
                self.transcribe_page.stop_playback()
                cleanup_loaded_project(self.project)
            self.project = project
            self._populate_form_from_project()
            self._set_status(f"Opened project: {Path(path).name}")
            self.append_log(f"Opened project: {path}")

        def save_project_file(self) -> None:
            if self.project is None:
                self._ensure_project_from_form()
            try:
                self._sync_project_from_form()
            except EncapError:
                return
            initial_name = (
                self.project.project_path.name
                if self.project.project_path
                else f"{self.project.output_basename()}.encap"
            )
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save project",
                initial_name,
                "EnCap Project (*.encap)",
            )
            if not path:
                return
            try:
                saved_path = save_project(self.project, Path(path))
            except EncapError as exc:
                QMessageBox.critical(self, "Save failed", str(exc))
                return
            self._set_status(f"Saved project: {saved_path.name}")
            self.append_log(f"Saved project: {saved_path}")

        def choose_artwork(self) -> None:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Choose artwork",
                "",
                "Images (*.png *.jpg *.jpeg *.webp);;All files (*.*)",
            )
            if not path:
                return
            self._set_episode_artwork(Path(path))

        def _set_episode_artwork_from_drop(self, path: str) -> None:
            self._set_episode_artwork(Path(path))

        def _set_episode_artwork(self, path: Path) -> bool:
            self._ensure_project_from_form()
            assert self.project is not None
            if not path.is_file() or not self.artwork_label.set_image_path(path):
                QMessageBox.warning(self, "Unsupported image", f"EnCap could not load {path.name}.")
                self.artwork_label.set_image_path(self.project.metadata.artwork_path)
                return False
            self.project.metadata.artwork_path = path
            self._set_status(f"Artwork selected: {path.name}")
            return True

        def _ensure_project_from_form(self) -> ProjectDocument:
            if self.project is not None:
                return self.project
            self.project = ProjectDocument()
            self.transcribe_page.set_project(self.project)
            self._sync_project_from_form()
            self._refresh_chapter_table()
            self._update_transcription_controls()
            return self.project

        def choose_chapter_image(self, row: int | None = None) -> None:
            chapter = self._selected_chapter(row)
            if chapter is None:
                return
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Choose chapter image",
                "",
                "Images (*.png *.jpg *.jpeg *.webp);;All files (*.*)",
            )
            if not path:
                return
            selected_row = row if row is not None else self.chapter_table.currentRow()
            self._set_chapter_image(selected_row, Path(path))

        def _set_chapter_image_from_drop(self, row: int, path: str) -> None:
            self._set_chapter_image(row, Path(path))

        def _set_chapter_image(self, row: int, path: Path) -> bool:
            chapter = self._selected_chapter(row)
            if chapter is None:
                return False
            pixmap = QPixmap(str(path))
            if not path.is_file() or pixmap.isNull():
                QMessageBox.warning(self, "Unsupported image", f"EnCap could not load {path.name}.")
                return False
            chapter.image_path = path
            self._refresh_chapter_table(select_row=row)
            self._set_status(f"Chapter {chapter.chapter_number} artwork selected: {path.name}")
            return True

        def export_all(self) -> None:
            if self.project is None or not self.project.audio_sources:
                QMessageBox.warning(self, "No project", "Import audio before exporting.")
                return
            try:
                self._sync_project_from_form()
            except EncapError:
                return
            if not any(segment.text.strip() for segment in self.project.transcript_segments):
                QMessageBox.warning(
                    self,
                    "No transcript",
                    "Transcribe the audio before exporting all formats.",
                )
                self._update_export_actions(False)
                return

            audio_path = self._choose_audio_export_path("Export All")
            if audio_path is None:
                return
            transcript_base = audio_path.with_suffix("").with_name(
                f"{audio_path.stem}-transcript"
            )
            txt_path = transcript_base.with_suffix(".txt")
            srt_path = transcript_base.with_suffix(".srt")
            existing_transcripts = [
                path.name for path in (txt_path, srt_path) if path.exists()
            ]
            if existing_transcripts:
                response = QMessageBox.question(
                    self,
                    "Replace transcript exports?",
                    "The following files already exist:\n\n"
                    + "\n".join(existing_transcripts)
                    + "\n\nReplace them?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if response != QMessageBox.Yes:
                    return
            try:
                exported_audio_path = export_project(
                    self.project,
                    audio_path.parent,
                    prompt_for_conversion=self.confirm_conversion,
                    output_path=audio_path,
                )
                export_transcript_txt(self.project, txt_path)
                export_transcript_srt(self.project, srt_path)
            except (EncapError, OSError) as exc:
                QMessageBox.critical(self, "Export failed", str(exc))
                self.append_log(f"Export all failed: {exc}")
                return
            self._set_status(f"Exported audio and transcripts: {exported_audio_path.name}")
            self.append_log(f"Exported audio: {exported_audio_path}")
            self.append_log(f"Exported transcript: {txt_path}")
            self.append_log(f"Exported transcript: {srt_path}")
            QMessageBox.information(
                self,
                "Export complete",
                "Created:\n"
                f"{exported_audio_path.name}\n"
                f"{txt_path.name}\n"
                f"{srt_path.name}",
            )

        def export_audio(self) -> None:
            if self.project is None or not self.project.audio_sources:
                QMessageBox.warning(self, "No project", "Import audio before exporting.")
                return
            try:
                self._sync_project_from_form()
            except EncapError:
                return
            requested_path = self._choose_audio_export_path("Export Audio")
            if requested_path is None:
                return
            try:
                output_path = export_project(
                    self.project,
                    requested_path.parent,
                    prompt_for_conversion=self.confirm_conversion,
                    output_path=requested_path,
                )
            except EncapError as exc:
                QMessageBox.critical(self, "Export failed", str(exc))
                self.append_log(f"Export failed: {exc}")
                return
            self._set_status(f"Exported audio: {output_path.name}")
            self.append_log(f"Exported audio: {output_path}")
            QMessageBox.information(self, "Export complete", f"Created {output_path.name}")

        def _choose_audio_export_path(self, title: str) -> Path | None:
            assert self.project is not None
            extension = self.project.export_settings.output_extension()
            initial_name = f"{self.project.output_basename()}{extension}"
            initial_path = (
                self.project.project_path.parent / initial_name
                if self.project.project_path is not None
                else Path(initial_name)
            )
            file_filter = (
                "MPEG-4 Audio (*.m4a)" if extension == ".m4a" else "MP3 Audio (*.mp3)"
            )
            path, _selected_filter = QFileDialog.getSaveFileName(
                self,
                title,
                str(initial_path),
                file_filter,
            )
            if not path:
                return None
            selected_path = Path(path)
            if selected_path.suffix.lower() != extension:
                selected_path = selected_path.with_suffix(extension)
            return selected_path

        def export_transcript(self, format_name: str) -> None:
            if self.project is None or not self.project.audio_sources:
                QMessageBox.warning(self, "No project", "Import audio before exporting a transcript.")
                return
            try:
                self._sync_project_from_form()
            except EncapError:
                return
            if not any(segment.text.strip() for segment in self.project.transcript_segments):
                QMessageBox.warning(
                    self,
                    "No transcript",
                    "Transcribe the audio before exporting a transcript.",
                )
                self._update_export_actions(False)
                return
            extension = ".srt" if format_name == "srt" else ".txt"
            initial_name = f"{self.project.output_basename()}-transcript{extension}"
            initial_path = (
                self.project.project_path.parent / initial_name
                if self.project.project_path is not None
                else Path(initial_name)
            )
            path, _ = QFileDialog.getSaveFileName(
                self,
                f"Export {format_name.upper()}",
                str(initial_path),
                f"{format_name.upper()} files (*{extension})",
            )
            if not path:
                return
            output_path = Path(path)
            if output_path.suffix.lower() != extension:
                output_path = output_path.with_suffix(extension)
            if format_name == "srt":
                export_transcript_srt(self.project, output_path)
            else:
                export_transcript_txt(self.project, output_path)
            self._set_status(f"Exported transcript: {output_path.name}")
            self.append_log(f"Exported transcript: {output_path}")

        def generate_ai_summary(self) -> None:
            QMessageBox.information(
                self,
                "AI unavailable",
                "Apple local AI integration is not implemented in this build yet.",
            )

        def generate_ai_title(self) -> None:
            QMessageBox.information(
                self,
                "AI unavailable",
                "Apple local title suggestion is not implemented in this build yet.",
            )

        def confirm_conversion(self, path: Path) -> bool:
            response = QMessageBox.question(
                self,
                "Convert mismatched WAV?",
                (
                    f"{path.name} does not match the first WAV file.\n\n"
                    "Convert it to the reference format with ffmpeg before stitching?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            return response == QMessageBox.Yes

        def add_chapter(self) -> None:
            if self.project is None:
                return
            start_time = (
                self.project.chapters[-1].start_time_seconds + self.project.chapters[-1].duration_seconds
                if self.project.chapters
                else 0.0
            )
            chapter = ChapterEntry(
                start_time_seconds=start_time,
                duration_seconds=5.0,
                chapter_number=len(self.project.chapters) + 1,
                title=f"Chapter {len(self.project.chapters) + 1}",
            )
            self.project.chapters.append(chapter)
            self._refresh_chapter_table(select_row=len(self.project.chapters) - 1)

        def remove_chapter(self) -> None:
            if self.project is None:
                return
            row = self.chapter_table.currentRow()
            if row < 0:
                return
            del self.project.chapters[row]
            self._renumber_chapters()
            self._refresh_chapter_table(select_row=min(row, len(self.project.chapters) - 1))

        def move_chapter(self, offset: int) -> None:
            if self.project is None:
                return
            row = self.chapter_table.currentRow()
            if row < 0:
                return
            new_row = row + offset
            if new_row < 0 or new_row >= len(self.project.chapters):
                return
            chapter = self.project.chapters.pop(row)
            self.project.chapters.insert(new_row, chapter)
            self._renumber_chapters()
            self._refresh_chapter_table(select_row=new_row)

        def on_chapter_cell_clicked(self, row: int, column: int) -> None:
            if column == 5:
                self.choose_chapter_image(row)

        def on_chapter_cell_double_clicked(self, row: int, column: int) -> None:
            if column != 4 or self.project is None or row < 0 or row >= len(self.project.chapters):
                return
            chapter = self.project.chapters[row]
            if chapter.link_url:
                QDesktopServices.openUrl(QUrl(chapter.link_url))

        def on_chapter_rows_reordered(self, ordered_keys: list[str]) -> None:
            if self.project is None or not ordered_keys:
                return
            chapter_map = {_chapter_key(chapter): chapter for chapter in self.project.chapters}
            reordered = [chapter_map[key] for key in ordered_keys if key in chapter_map]
            if len(reordered) != len(self.project.chapters):
                return
            self.project.chapters = reordered
            self._renumber_chapters()
            self._refresh_chapter_table(select_row=self.chapter_table.currentRow())

        def on_chapter_item_changed(self, item: QTableWidgetItem) -> None:
            if self.project is None or self._updating_chapter_table:
                return
            row = item.row()
            if row < 0 or row >= len(self.project.chapters):
                return
            chapter = self.project.chapters[row]
            if item.column() == 3:
                chapter.title = str(item.text()).strip()
                return
            if item.column() != 4:
                return
            try:
                normalized = _normalize_link_url(item.text())
            except Exception as exc:
                self._chapter_url_states[_chapter_key(chapter)] = ("invalid", f"Invalid URL: {exc}")
                self._decorate_url_item(item, "invalid", f"Invalid URL: {exc}")
                return
            chapter.link_url = normalized
            self._set_table_item_text(item, normalized)
            if normalized:
                self._schedule_url_validation(row, _chapter_key(chapter), normalized)
            else:
                self._chapter_url_states.pop(_chapter_key(chapter), None)
                self._decorate_url_item(item, "empty", "")

        def _selected_chapter(self, row: int | None = None) -> ChapterEntry | None:
            if self.project is None:
                return None
            if row is None:
                row = self.chapter_table.currentRow()
            if row < 0 or row >= len(self.project.chapters):
                return None
            return self.project.chapters[row]

        def _renumber_chapters(self) -> None:
            if self.project is None:
                return
            running_time = 0.0
            for index, chapter in enumerate(self.project.chapters, start=1):
                chapter.chapter_number = index
                chapter.start_time_seconds = running_time
                if re.fullmatch(r"Chapter \d+", chapter.title.strip()):
                    chapter.title = f"Chapter {index}"
                running_time += chapter.duration_seconds

        def _populate_form_from_project(self) -> None:
            assert self.project is not None
            self._rebuild_chapter_url_states()
            self.podcast_edit.setText(self.project.metadata.podcast_title)
            self.episode_edit.setText(self.project.metadata.episode_title or self.project.project_title)
            format_name = normalize_output_format(self.project.export_settings.output_format)
            format_index = self.format_box.findData(format_name)
            self.format_box.blockSignals(True)
            self.format_box.setCurrentIndex(format_index if format_index >= 0 else 0)
            self.format_box.blockSignals(False)
            channels_index = self.channels_box.findData(self.project.export_settings.channels)
            self.channels_box.blockSignals(True)
            self.channels_box.setCurrentIndex(channels_index if channels_index >= 0 else 0)
            self.channels_box.blockSignals(False)
            self._refresh_encoder_options(self.project.export_settings.encoder)
            self._refresh_bitrate_options(self.project.export_settings.quality_preset)
            self.summary_edit.setPlainText(self.project.metadata.summary)
            self.artwork_label.set_image_path(self.project.metadata.artwork_path)
            self._set_transcript_editor_from_project()
            self._refresh_chapter_table()
            self._update_transcription_controls()

        def _rebuild_chapter_url_states(self) -> None:
            self._chapter_url_states = {}
            if self.project is None:
                return
            for chapter in self.project.chapters:
                chapter_key = _chapter_key(chapter)
                if chapter.link_url:
                    self._chapter_url_states[chapter_key] = ("valid", chapter.link_url)

        def _refresh_chapter_table(self, select_row: int | None = None) -> None:
            self._updating_chapter_table = True
            self.chapter_table.blockSignals(True)
            self.chapter_table.setRowCount(0)
            if self.project is not None:
                self.chapter_table.setRowCount(len(self.project.chapters))
                for row, chapter in enumerate(self.project.chapters):
                    chapter_key = _chapter_key(chapter)
                    image_value = chapter.image_path.name if chapter.image_path is not None else "Choose image..."
                    values = [
                        _format_timestamp(chapter.start_time_seconds),
                        _format_timestamp(chapter.duration_seconds),
                        str(chapter.chapter_number),
                        chapter.title,
                        chapter.link_url,
                        image_value,
                    ]
                    for column, value in enumerate(values):
                        item = QTableWidgetItem(value)
                        item.setData(Qt.UserRole, chapter_key)
                        if column in {3, 4}:
                            item.setFlags(item.flags() | Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                        else:
                            item.setFlags((item.flags() | Qt.ItemIsEnabled | Qt.ItemIsSelectable) & ~Qt.ItemIsEditable)
                        if column == 4:
                            status, detail = self._chapter_url_states.get(chapter_key, ("empty", ""))
                            self._decorate_url_item(item, status, detail)
                        if column == 5:
                            if chapter.image_path is not None:
                                pixmap = QPixmap(str(chapter.image_path))
                                if not pixmap.isNull():
                                    item.setIcon(QIcon(pixmap))
                                    item.setToolTip(
                                        f"{chapter.image_path.name}\nClick or drop another image to replace it."
                                    )
                                else:
                                    item.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxWarning))
                                    item.setToolTip("This chapter image could not be loaded. Click to replace it.")
                            else:
                                item.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
                                item.setToolTip("Click to choose a chapter image, or drag an image here.")
                        self.chapter_table.setItem(row, column, item)
                    self.chapter_table.setRowHeight(row, 30)
            self.chapter_table.blockSignals(False)
            self._updating_chapter_table = False

            if self.project is None or not self.project.chapters:
                return

            if select_row is None:
                select_row = 0
            select_row = max(0, min(select_row, len(self.project.chapters) - 1))
            self.chapter_table.setCurrentCell(select_row, 3)

        def _sync_project_from_form(self) -> None:
            if self.project is None:
                return
            self.project.metadata.podcast_title = self.podcast_edit.text().strip()
            self.project.metadata.episode_title = self.episode_edit.text().strip()
            self.project.metadata.summary = self.summary_edit.toPlainText().strip()
            self.project.project_title = self.project.metadata.episode_title or self.project.project_title
            self.project.export_settings.output_format = str(self.format_box.currentData() or "mp3")
            self.project.export_settings.encoder = str(self.encoder_box.currentData() or "lame")
            self.project.export_settings.channels = int(self.channels_box.currentData() or 2)
            self.project.export_settings.quality_preset = str(
                self.quality_box.currentData() or "320k"
            )
            self.transcribe_page.sync_to_project()

        def _schedule_url_validation(self, row: int, chapter_key: str, raw_value: str) -> None:
            self._pending_url_validation = (row, chapter_key, raw_value)
            item = self.chapter_table.item(row, 4)
            if item is not None:
                self._decorate_url_item(item, "pending", raw_value)
            self._url_validation_timer.start()

        def _run_pending_url_validation(self) -> None:
            if self._pending_url_validation is None:
                return
            row, chapter_key, raw_value = self._pending_url_validation
            self._pending_url_validation = None
            self._url_validation_request_id += 1
            request_id = self._url_validation_request_id
            worker = UrlValidationWorker(request_id, raw_value)
            worker.signals.resolved.connect(
                lambda result_id, validated_raw, status, payload: self._handle_url_validation_result(
                    result_id,
                    row,
                    chapter_key,
                    validated_raw,
                    status,
                    payload,
                )
            )
            self._thread_pool.start(worker)

        def _handle_url_validation_result(
            self,
            request_id: int,
            row: int,
            chapter_key: str,
            raw_value: str,
            status: str,
            payload: str,
        ) -> None:
            if request_id != self._url_validation_request_id or self.project is None:
                return
            chapter = self._selected_chapter(row)
            if chapter is None or _chapter_key(chapter) != chapter_key:
                return
            if chapter.link_url != _normalize_link_url(raw_value):
                return
            item = self.chapter_table.item(row, 4)
            if item is None:
                return
            if status == "valid":
                chapter.link_url = payload
                self._chapter_url_states[chapter_key] = ("valid", payload)
                self._set_table_item_text(item, payload)
                self._decorate_url_item(item, "valid", payload)
                return
            self._chapter_url_states[chapter_key] = ("invalid", payload)
            self._decorate_url_item(item, "invalid", payload)

        def _decorate_url_item(self, item: QTableWidgetItem, status: str, detail: str) -> None:
            icon = None
            tooltip = ""
            if status == "valid":
                icon = self._link_icon()
                tooltip = f"Verified URL. Double-click to open: {detail}"
            elif status == "invalid":
                icon = self.style().standardIcon(QStyle.SP_MessageBoxWarning)
                tooltip = detail
            elif status == "pending":
                icon = self.style().standardIcon(QStyle.SP_BrowserReload)
                tooltip = f"Validating {detail}"
            else:
                icon = self._link_icon()
                tooltip = "Enter a URL. The app will validate it in the background."
            self._mutate_table_item(item, icon=icon, tooltip=tooltip)

        def _link_icon(self) -> QIcon:
            icon = QIcon.fromTheme("insert-link")
            if not icon.isNull():
                return icon
            pixmap = QPixmap(16, 16)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(self.palette().link().color())
            font = painter.font()
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(pixmap.rect(), Qt.AlignCenter, "🔗")
            painter.end()
            return QIcon(pixmap)

        def _set_table_item_text(self, item: QTableWidgetItem, text: str) -> None:
            if item.text() == text:
                return
            self._mutate_table_item(item, text=text)

        def _mutate_table_item(
            self,
            item: QTableWidgetItem,
            *,
            text: str | None = None,
            icon=None,
            tooltip: str | None = None,
        ) -> None:
            table = item.tableWidget()
            if table is None:
                if text is not None:
                    item.setText(text)
                if icon is not None:
                    item.setIcon(icon)
                if tooltip is not None:
                    item.setToolTip(tooltip)
                return
            self._updating_chapter_table = True
            table.blockSignals(True)
            try:
                if text is not None:
                    item.setText(text)
                if icon is not None:
                    item.setIcon(icon)
                if tooltip is not None:
                    item.setToolTip(tooltip)
            finally:
                table.blockSignals(False)
                self._updating_chapter_table = False


def _format_timestamp(seconds: float) -> str:
    total_seconds = int(round(max(seconds, 0.0)))
    minutes, seconds_remainder = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds_remainder:02d}"
    return f"{minutes}:{seconds_remainder:02d}"


def _parse_timestamp(value: str) -> float:
    parts = [part.strip() for part in value.split(":")]
    if not parts or len(parts) > 3:
        raise ValueError(f"Invalid timestamp: {value}")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _apply_chapter_form_values(
    chapter: ChapterEntry,
    start_value: str,
    duration_value: str,
    chapter_number_value: str,
    title_value: str,
    link_value: str,
) -> None:
    chapter.start_time_seconds = _parse_timestamp(start_value)
    chapter.duration_seconds = _parse_timestamp(duration_value)
    chapter.chapter_number = int(chapter_number_value.strip())
    chapter.title = title_value.strip()
    chapter.link_url = _normalize_link_url(link_value)


def _normalize_link_url(value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        return ""
    if "://" in normalized:
        return normalized
    if normalized.startswith(("mailto:", "tel:")):
        return normalized
    return f"https://{normalized}"


def _chapter_key(chapter: ChapterEntry) -> str:
    return str(id(chapter))


def _resolve_url_candidate(url: str, timeout_seconds: float = 4.0) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "EnCap/1.0"},
        method="HEAD",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.geturl()
    except urllib.error.HTTPError as exc:
        if exc.code in {403, 405, 501}:
            fallback_request = urllib.request.Request(
                url,
                headers={"User-Agent": "EnCap/1.0"},
                method="GET",
            )
            with urllib.request.urlopen(fallback_request, timeout=timeout_seconds) as response:
                return response.geturl()
        raise


def validate_link_url(value: str) -> tuple[str, str | None, str]:
    raw_value = value.strip()
    normalized = _normalize_link_url(raw_value)
    if not normalized:
        return ("empty", None, "No URL entered.")
    candidates = [normalized]
    if "://" not in raw_value:
        candidates.append(normalized.replace("https://", "http://", 1))
    elif normalized.startswith("https://"):
        http_candidate = normalized.replace("https://", "http://", 1)
        candidates.append(http_candidate)
    for candidate in candidates:
        try:
            return ("valid", _resolve_url_candidate(candidate), "")
        except (urllib.error.URLError, ValueError):
            continue
    return ("invalid", None, f"Could not verify {normalized}")


def main() -> int:
    if missing_gui_dependency is not None:  # pragma: no cover
        raise SystemExit(
            "PySide6 is required for the GUI build of EnCap. "
            f"Original error: {missing_gui_dependency}"
        )

    app = QApplication.instance() or QApplication(sys.argv)
    window = EncapWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

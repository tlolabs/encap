from __future__ import annotations

"""Transcript-focused workspace used by the EnCap desktop application.

The widget deliberately owns only presentation and lightweight transcript editing.
Transcription, model management, and file export remain responsibilities of the
main window and are exposed as signals.
"""

from bisect import bisect_right
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .models import ProjectDocument, TranscriptSegment

try:  # QtMultimedia can be absent from minimal/headless PySide installations.
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except (ImportError, ModuleNotFoundError):  # pragma: no cover - build dependent
    QAudioOutput = None  # type: ignore[assignment]
    QMediaPlayer = None  # type: ignore[assignment]


_EDITOR_MODE = 0
_SEGMENTS_MODE = 1
_SPEAKER_COLORS = (
    "#d94bc6",
    "#d3b514",
    "#82c73d",
    "#f29f2d",
    "#31c8bd",
    "#df6d70",
    "#55a7d6",
    "#8b70d6",
    "#2eaa68",
    "#dc7038",
)


class TranscriptWorkspace(QWidget):
    """A complete transcription editor suitable for a top-level workspace.

    Transcript edits made in the segment table update ``ProjectDocument``
    immediately. Free-form editor changes are committed by ``sync_to_project``
    (and automatically when switching views or projects). Existing segment timing
    is retained by index when the free-form text is edited.
    """

    transcribe_requested = Signal()
    manage_models_requested = Signal()
    export_requested = Signal(str)
    transcript_content_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transcriptWorkspace")

        self._project: ProjectDocument | None = None
        self._refreshing_editor = False
        self._refreshing_table = False
        self._editor_dirty = False
        self._editor_rendered_with_speakers = True
        self._speaker_colors: dict[str, QColor] = {}
        self._mode = _SEGMENTS_MODE
        self._transcription_enabled = True

        self._player = None
        self._audio_output = None
        self._source_paths: list[Path] = []
        self._source_durations_ms: list[int] = []
        self._source_offsets_ms: list[int] = []
        self._total_duration_ms = 0
        self._active_source_index = -1
        self._pending_local_position_ms: int | None = None
        self._pending_play_after_load = False
        self._play_requested = False
        self._seeking = False

        self._build_ui()
        self.content_stack.setCurrentIndex(self._mode)
        self._set_transcript_font_size(18)
        self._build_player()
        self._apply_style()
        self.set_project(None)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("transcriptHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 12, 18, 12)
        header_layout.setSpacing(10)

        self.title_label = QLabel("Transcript")
        self.title_label.setObjectName("transcriptProjectTitle")
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        header_layout.addWidget(self.title_label, stretch=1)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("transcriptSearch")
        self.search_edit.setPlaceholderText("Search transcript")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMaximumWidth(250)
        self.search_edit.textChanged.connect(self._apply_search)
        header_layout.addWidget(self.search_edit)

        self.export_button = QToolButton()
        self.export_button.setObjectName("transcriptExportButton")
        self.export_button.setText("Export")
        self.export_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.export_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.export_button.clicked.connect(lambda: self.export_requested.emit("txt"))
        export_menu = QMenu(self.export_button)
        txt_action = export_menu.addAction("Plain Text (.txt)")
        srt_action = export_menu.addAction("SubRip Captions (.srt)")
        txt_action.triggered.connect(
            lambda _checked=False: self.export_requested.emit("txt")
        )
        srt_action.triggered.connect(
            lambda _checked=False: self.export_requested.emit("srt")
        )
        self.export_button.setMenu(export_menu)
        header_layout.addWidget(self.export_button)
        root.addWidget(header)

        engine_bar = QFrame()
        engine_bar.setObjectName("transcriptionEngineBar")
        engine_layout = QHBoxLayout(engine_bar)
        engine_layout.setContentsMargins(18, 8, 18, 8)
        engine_layout.setSpacing(8)

        engine_label = QLabel("Transcription engine")
        engine_label.setObjectName("transcriptionEngineLabel")
        engine_layout.addWidget(engine_label)

        self.provider_box = QComboBox()
        self.provider_box.setObjectName("transcriptionProviderBox")
        self.provider_box.setMinimumContentsLength(22)
        self.provider_box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        engine_layout.addWidget(self.provider_box, stretch=1)

        self.manage_models_button = QPushButton("Manage Models…")
        self.manage_models_button.setObjectName("manageTranscriptionModelsButton")
        self.manage_models_button.clicked.connect(self.manage_models_requested)
        engine_layout.addWidget(self.manage_models_button)

        self.transcribe_button = QPushButton("Transcribe Audio")
        self.transcribe_button.setObjectName("transcribeAudioButton")
        self.transcribe_button.setProperty("accent", True)
        self.transcribe_button.clicked.connect(self.transcribe_requested)
        engine_layout.addWidget(self.transcribe_button)
        root.addWidget(engine_bar)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setObjectName("transcriptSplitter")
        self.main_splitter.setChildrenCollapsible(False)

        transcript_panel = QFrame()
        transcript_panel.setObjectName("transcriptContentPanel")
        transcript_layout = QVBoxLayout(transcript_panel)
        transcript_layout.setContentsMargins(0, 0, 0, 0)
        transcript_layout.setSpacing(0)

        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("transcriptViewStack")

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("transcriptEditor")
        self.editor.setPlaceholderText(
            "Your transcript will appear here. Choose an engine and transcribe the audio to begin."
        )
        self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.editor.setTabChangesFocus(True)
        self.editor.textChanged.connect(self._on_editor_changed)
        self.content_stack.addWidget(self.editor)

        self.segment_table = QTableWidget(0, 4)
        self.segment_table.setObjectName("transcriptSegmentTable")
        self.segment_table.setHorizontalHeaderLabels(
            ["Start", "End", "Speaker", "Transcript"]
        )
        self.segment_table.setAlternatingRowColors(True)
        self.segment_table.setShowGrid(False)
        self.segment_table.setWordWrap(True)
        self.segment_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.segment_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.segment_table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.SelectedClicked
        )
        self.segment_table.verticalHeader().setDefaultSectionSize(50)
        self.segment_table.verticalHeader().setMinimumSectionSize(36)
        self.segment_table.verticalHeader().hide()
        table_header = self.segment_table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(3, QHeaderView.Stretch)
        table_header.hide()
        for column in (0, 1, 2):
            self.segment_table.setColumnHidden(column, True)
        self.segment_table.itemChanged.connect(self._on_segment_item_changed)
        self.segment_table.cellDoubleClicked.connect(self._seek_to_segment)
        self.content_stack.addWidget(self.segment_table)
        transcript_layout.addWidget(self.content_stack, stretch=1)

        self._build_playback_footer(transcript_layout)
        self.main_splitter.addWidget(transcript_panel)
        self.main_splitter.addWidget(self._build_inspector())
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 0)
        self.main_splitter.setSizes([900, 285])
        root.addWidget(self.main_splitter, stretch=1)

    def _build_inspector(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("transcriptInspector")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(260)
        scroll.setMaximumWidth(390)

        inspector = QWidget()
        inspector.setObjectName("transcriptInspectorContents")
        layout = QVBoxLayout(inspector)
        layout.setContentsMargins(14, 14, 14, 18)
        layout.setSpacing(14)

        self.copy_button = QPushButton("Copy Transcript")
        self.copy_button.setObjectName("copyTranscriptButton")
        self.copy_button.clicked.connect(self._copy_transcript)
        layout.addWidget(self.copy_button)

        view_card = QFrame()
        view_card.setObjectName("inspectorCard")
        view_layout = QHBoxLayout(view_card)
        view_layout.setContentsMargins(8, 8, 8, 8)
        view_layout.setSpacing(8)
        self.editor_mode_button = QPushButton("Editor")
        self.editor_mode_button.setObjectName("transcriptEditorModeButton")
        self.segments_mode_button = QPushButton("Segments")
        self.segments_mode_button.setObjectName("transcriptSegmentsModeButton")
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        for button, mode in (
            (self.editor_mode_button, _EDITOR_MODE),
            (self.segments_mode_button, _SEGMENTS_MODE),
        ):
            button.setCheckable(True)
            button.setProperty("modeButton", True)
            button.setMinimumHeight(70)
            self._mode_group.addButton(button, mode)
            button.clicked.connect(
                lambda _checked=False, selected_mode=mode: self._set_mode(selected_mode)
            )
            view_layout.addWidget(button)
        self.segments_mode_button.setChecked(True)
        layout.addWidget(view_card)

        people_heading = QLabel("People")
        people_heading.setObjectName("inspectorHeading")
        layout.addWidget(people_heading)

        people_card = QFrame()
        people_card.setObjectName("inspectorCard")
        people_card_layout = QVBoxLayout(people_card)
        people_card_layout.setContentsMargins(8, 6, 8, 8)
        people_card_layout.setSpacing(0)

        self.people_widget = QWidget()
        self.people_widget.setObjectName("transcriptPeopleList")
        self.people_layout = QVBoxLayout(self.people_widget)
        self.people_layout.setContentsMargins(0, 0, 0, 0)
        self.people_layout.setSpacing(0)
        people_card_layout.addWidget(self.people_widget)

        add_row = QHBoxLayout()
        add_row.setContentsMargins(0, 8, 0, 0)
        add_row.setSpacing(6)
        self.add_speaker_edit = QLineEdit()
        self.add_speaker_edit.setObjectName("addSpeakerEdit")
        self.add_speaker_edit.setPlaceholderText("Add or assign a speaker…")
        self.add_speaker_edit.textChanged.connect(self._update_add_speaker_button)
        self.add_speaker_edit.returnPressed.connect(self._add_or_assign_speaker)
        add_row.addWidget(self.add_speaker_edit, stretch=1)
        self.add_speaker_button = QToolButton()
        self.add_speaker_button.setObjectName("addSpeakerButton")
        self.add_speaker_button.setText("+")
        self.add_speaker_button.setToolTip("Assign this speaker to the selected segment")
        self.add_speaker_button.clicked.connect(self._add_or_assign_speaker)
        add_row.addWidget(self.add_speaker_button)
        people_card_layout.addLayout(add_row)
        layout.addWidget(people_card)

        display_heading = QLabel("Display")
        display_heading.setObjectName("inspectorHeading")
        layout.addWidget(display_heading)

        display_card = QFrame()
        display_card.setObjectName("inspectorCard")
        display_layout = QVBoxLayout(display_card)
        display_layout.setContentsMargins(12, 8, 12, 8)
        display_layout.setSpacing(0)

        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Font Size"))
        font_row.addStretch(1)
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setObjectName("transcriptFontSize")
        self.font_size_spin.setRange(11, 32)
        self.font_size_spin.setValue(18)
        self.font_size_spin.setSuffix(" pt")
        self.font_size_spin.valueChanged.connect(self._set_transcript_font_size)
        font_row.addWidget(self.font_size_spin)
        display_layout.addLayout(font_row)

        divider = QFrame()
        divider.setObjectName("inspectorDivider")
        divider.setFrameShape(QFrame.HLine)
        display_layout.addWidget(divider)

        self.show_speakers_check = QCheckBox("Show Speaker Names")
        self.show_speakers_check.setObjectName("showTranscriptSpeakers")
        self.show_speakers_check.setChecked(True)
        self.show_speakers_check.toggled.connect(self._show_speakers_changed)
        display_layout.addWidget(self.show_speakers_check)
        layout.addWidget(display_card)
        layout.addStretch(1)

        scroll.setWidget(inspector)
        return scroll

    def _build_playback_footer(self, parent_layout: QVBoxLayout) -> None:
        footer = QFrame()
        footer.setObjectName("transcriptPlaybackFooter")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)

        self.play_button = QToolButton()
        self.play_button.setObjectName("transcriptPlayButton")
        self.play_button.setText("▶")
        self.play_button.setToolTip("Play")
        self.play_button.setAccessibleName("Play")
        self.play_button.clicked.connect(self._toggle_playback)
        layout.addWidget(self.play_button)

        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setObjectName("transcriptPlaybackPosition")
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderPressed.connect(self._begin_seek)
        self.position_slider.sliderReleased.connect(self._finish_seek)
        self.position_slider.sliderMoved.connect(self._preview_seek)
        layout.addWidget(self.position_slider, stretch=1)

        self.position_label = QLabel("00:00 / 00:00")
        self.position_label.setObjectName("transcriptPlaybackTime")
        self.position_label.setMinimumWidth(105)
        self.position_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.position_label)

        self.playback_rate_box = QComboBox()
        self.playback_rate_box.setObjectName("transcriptPlaybackRate")
        for rate in (0.75, 1.0, 1.25, 1.5, 2.0):
            self.playback_rate_box.addItem(f"{rate:g}×", rate)
        self.playback_rate_box.setCurrentIndex(1)
        self.playback_rate_box.currentIndexChanged.connect(self._set_playback_rate)
        layout.addWidget(self.playback_rate_box)
        parent_layout.addWidget(footer)

    def _apply_style(self) -> None:
        # Clearing first forces Qt to resolve every palette(...) reference again
        # after a live macOS appearance change.
        self.setStyleSheet("")
        self.setStyleSheet(
            """
            QWidget#transcriptWorkspace {
                background: palette(window);
            }
            QFrame#transcriptHeader {
                background: palette(window);
                border-bottom: 1px solid palette(mid);
            }
            QLabel#transcriptProjectTitle {
                font-size: 18px;
                font-weight: 600;
            }
            QFrame#transcriptionEngineBar {
                background: palette(alternate-base);
                border-bottom: 1px solid palette(mid);
            }
            QLabel#transcriptionEngineLabel, QLabel#inspectorHeading {
                color: palette(window-text);
                font-size: 12px;
                font-weight: 600;
            }
            QLineEdit#transcriptSearch, QComboBox#transcriptionProviderBox,
            QLineEdit#addSpeakerEdit, QSpinBox#transcriptFontSize,
            QComboBox#transcriptPlaybackRate {
                background: palette(base);
                color: palette(text);
                border: 1px solid palette(mid);
                border-radius: 4px;
                padding: 3px 6px;
                selection-background-color: palette(highlight);
                selection-color: palette(highlighted-text);
            }
            QPushButton[accent="true"] {
                background: palette(highlight);
                border: 1px solid palette(highlight);
                border-radius: 6px;
                color: palette(highlighted-text);
                padding: 5px 12px;
            }
            QPushButton[accent="true"]:disabled {
                background: palette(button);
                border-color: palette(mid);
                color: palette(button-text);
            }
            QFrame#transcriptContentPanel {
                background: palette(base);
                border: none;
            }
            QPlainTextEdit#transcriptEditor {
                background: palette(base);
                color: palette(text);
                border: none;
                padding: 16px;
                selection-background-color: palette(highlight);
                selection-color: palette(highlighted-text);
            }
            QTableWidget#transcriptSegmentTable {
                background: palette(base);
                alternate-background-color: palette(alternate-base);
                color: palette(text);
                border: none;
                gridline-color: palette(mid);
                selection-background-color: palette(highlight);
                selection-color: palette(highlighted-text);
            }
            QTableWidget#transcriptSegmentTable::item {
                border-bottom: 1px solid palette(mid);
                padding-left: 6px;
                padding-right: 6px;
            }
            QHeaderView::section {
                background: palette(button);
                color: palette(button-text);
                border: none;
                border-bottom: 1px solid palette(mid);
                padding: 6px;
                font-weight: 600;
            }
            QScrollArea#transcriptInspector {
                background: palette(window);
                border: none;
                border-left: 1px solid palette(mid);
            }
            QWidget#transcriptInspectorContents {
                background: palette(window);
            }
            QFrame#inspectorCard {
                background: palette(button);
                border: 1px solid palette(mid);
                border-radius: 7px;
            }
            QPushButton[modeButton="true"] {
                background: palette(button);
                color: palette(button-text);
                border: 1px solid palette(mid);
                border-radius: 5px;
                padding: 8px;
            }
            QPushButton[modeButton="true"]:checked {
                border-color: palette(highlight);
                background: palette(highlight);
                color: palette(highlighted-text);
            }
            QFrame#inspectorDivider {
                color: palette(mid);
                margin-top: 7px;
                margin-bottom: 7px;
            }
            QFrame#transcriptPlaybackFooter {
                background: palette(alternate-base);
                border-top: 1px solid palette(mid);
            }
            QToolButton#transcriptPlayButton {
                background: palette(button);
                color: palette(button-text);
                border: 1px solid palette(mid);
                border-radius: 16px;
                font-size: 19px;
                min-width: 32px;
                min-height: 32px;
            }
            QToolButton#transcriptPlayButton:hover {
                background: palette(midlight);
                border-color: palette(highlight);
            }
            QToolButton#addSpeakerButton {
                background: palette(button);
                color: palette(button-text);
                border: 1px solid palette(mid);
                border-radius: 4px;
                font-size: 18px;
                min-width: 26px;
                min-height: 26px;
            }
            QToolButton#transcriptExportButton, QPushButton#copyTranscriptButton,
            QPushButton#manageTranscriptionModelsButton {
                background: palette(button);
                color: palette(button-text);
                border: 1px solid palette(mid);
                border-radius: 5px;
                padding: 4px 10px;
            }
            QToolButton#transcriptExportButton:hover,
            QPushButton#copyTranscriptButton:hover,
            QPushButton#manageTranscriptionModelsButton:hover,
            QToolButton#addSpeakerButton:hover {
                background: palette(midlight);
                border-color: palette(highlight);
            }
            QSplitter::handle {
                background: palette(mid);
                width: 1px;
            }
            """
        )

    # ------------------------------------------------------------- public API

    def refresh_appearance(self) -> None:
        self._apply_style()
        self.update()

    @property
    def project(self) -> ProjectDocument | None:
        return self._project

    def set_project(self, project: ProjectDocument | None) -> None:
        """Display ``project``, committing edits on the previous project first."""

        if self._project is project:
            self.refresh_segments()
            self._update_project_state()
            return
        if self._project is not None:
            self.sync_to_project()
        self.stop_playback()
        self._project = project
        self._update_project_state()
        self.refresh_segments()
        self._configure_audio_sources()

    def refresh_segments(self) -> None:
        """Reload editor, table, and speaker inspector from the current project."""

        segments = self._segments()
        self._refresh_editor(segments)
        self._rebuild_people()
        self._refresh_segment_table(segments)
        self._apply_search(self.search_edit.text())
        self._update_add_speaker_button()

    def sync_to_project(self) -> None:
        """Commit free-form editor changes while retaining known timestamps."""

        if self._project is None or not self._editor_dirty:
            return
        old_segments = list(self._project.transcript_segments)
        lines = [line.strip() for line in self.editor.toPlainText().splitlines() if line.strip()]
        durations = [
            segment.end_time_seconds - segment.start_time_seconds
            for segment in old_segments
            if segment.end_time_seconds > segment.start_time_seconds
        ]
        default_duration = sorted(durations)[len(durations) // 2] if durations else 5.0
        default_duration = min(max(default_duration, 0.25), 30.0)

        replacement: list[TranscriptSegment] = []
        # This records how the dirty editor was rendered.  The checkbox can have
        # changed by the time sync runs, and parsing against its new state would
        # turn an existing ``Speaker: text`` prefix into transcript body text.
        show_speakers = self._editor_rendered_with_speakers
        for index, line in enumerate(lines):
            prior = old_segments[index] if index < len(old_segments) else None
            prior_speaker = prior.speaker if prior is not None else ""
            speaker, text = self._parse_editor_line(line, prior_speaker, show_speakers)
            if prior is not None:
                start = prior.start_time_seconds
                end = prior.end_time_seconds
            else:
                start = replacement[-1].end_time_seconds if replacement else 0.0
                end = start + default_duration
            replacement.append(
                TranscriptSegment(
                    start_time_seconds=start,
                    end_time_seconds=max(end, start),
                    speaker=speaker,
                    text=text,
                )
            )

        self._project.transcript_segments = replacement
        self._editor_dirty = False
        self._rebuild_people()
        self._refresh_segment_table(replacement)
        self._update_project_state()

    def has_transcript_content(self) -> bool:
        self.sync_to_project()
        return bool(
            self._project is not None
            and any(
                segment.text.strip() or segment.speaker.strip()
                for segment in self._project.transcript_segments
            )
        )

    def set_transcription_enabled(self, enabled: bool) -> None:
        self._transcription_enabled = bool(enabled)
        self._update_project_state()

    def stop_playback(self) -> None:
        """Stop multimedia playback and return the global playhead to zero."""

        self._play_requested = False
        self._pending_play_after_load = False
        self._pending_local_position_ms = None
        if self._player is not None:
            self._player.stop()
        self._active_source_index = -1
        self._set_global_position(0)
        self._update_play_button(False)

    # ------------------------------------------------------- transcript editing

    def _segments(self) -> list[TranscriptSegment]:
        return self._project.transcript_segments if self._project is not None else []

    def _update_project_state(self) -> None:
        project = self._project
        if project is None:
            title = "Transcript"
        else:
            title = (
                project.metadata.episode_title.strip()
                or project.project_title.strip()
                or "Untitled Transcript"
            )
        self.title_label.setText(title)

        has_project = project is not None
        has_audio = bool(project is not None and project.audio_sources)
        can_transcribe = has_audio and self._transcription_enabled
        self.transcribe_button.setEnabled(can_transcribe)
        has_transcript = bool(
            project is not None
            and any(segment.text.strip() for segment in project.transcript_segments)
        )
        self.export_button.setEnabled(has_audio and has_transcript)
        self.copy_button.setEnabled(has_project and has_transcript)
        self.editor.setEnabled(has_project)
        self.segment_table.setEnabled(has_project)
        self.transcript_content_changed.emit(has_transcript)

    def _refresh_editor(self, segments: list[TranscriptSegment]) -> None:
        show_speakers = self.show_speakers_check.isChecked()
        lines = [self._segment_display_text(segment, show_speakers) for segment in segments]
        cursor = self.editor.textCursor()
        cursor_position = cursor.position()
        scroll_value = self.editor.verticalScrollBar().value()
        self._refreshing_editor = True
        blocker = QSignalBlocker(self.editor)
        try:
            self.editor.setPlainText("\n".join(lines))
            cursor = self.editor.textCursor()
            cursor.setPosition(min(cursor_position, len(self.editor.toPlainText())))
            self.editor.setTextCursor(cursor)
            self.editor.verticalScrollBar().setValue(scroll_value)
        finally:
            del blocker
            self._refreshing_editor = False
        self._editor_dirty = False
        self._editor_rendered_with_speakers = show_speakers

    def _refresh_segment_table(self, segments: list[TranscriptSegment]) -> None:
        selected_rows = {index.row() for index in self.segment_table.selectionModel().selectedRows()}
        current_row = self.segment_table.currentRow()
        self._refreshing_table = True
        blocker = QSignalBlocker(self.segment_table)
        try:
            self.segment_table.clearContents()
            self.segment_table.setRowCount(len(segments))
            for row, segment in enumerate(segments):
                values = (
                    _format_time(segment.start_time_seconds, include_milliseconds=True),
                    _format_time(segment.end_time_seconds, include_milliseconds=True),
                    segment.speaker,
                    segment.text,
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.UserRole, row)
                    if column in (0, 1):
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    else:
                        item.setFlags(item.flags() | Qt.ItemIsEditable)
                    if column == 2 and segment.speaker.strip():
                        item.setForeground(self._speaker_color(segment.speaker))
                    self.segment_table.setItem(row, column, item)
            for row in selected_rows:
                if 0 <= row < len(segments):
                    self.segment_table.selectRow(row)
            if not selected_rows and 0 <= current_row < len(segments):
                self.segment_table.setCurrentCell(current_row, 3)
        finally:
            del blocker
            self._refreshing_table = False

    def _on_editor_changed(self) -> None:
        if not self._refreshing_editor:
            self._editor_dirty = True
            has_transcript = bool(self.editor.toPlainText().strip())
            has_audio = bool(self._project is not None and self._project.audio_sources)
            self.export_button.setEnabled(has_audio and has_transcript)
            self.copy_button.setEnabled(has_transcript)
            self.transcript_content_changed.emit(has_transcript)

    def _on_segment_item_changed(self, item: QTableWidgetItem) -> None:
        if self._refreshing_table or self._project is None:
            return
        row = item.row()
        if row < 0 or row >= len(self._project.transcript_segments):
            return
        segment = self._project.transcript_segments[row]
        if item.column() == 2:
            segment.speaker = item.text().strip()
            self._rebuild_people()
            item.setForeground(
                self._speaker_color(segment.speaker) if segment.speaker else self.palette().text()
            )
        elif item.column() == 3:
            segment.text = item.text().strip()
        self._editor_dirty = False
        self._refresh_editor(self._project.transcript_segments)
        self._update_project_state()
        self._apply_search(self.search_edit.text())

    @staticmethod
    def _parse_editor_line(
        line: str,
        prior_speaker: str,
        show_speakers: bool,
    ) -> tuple[str, str]:
        if not show_speakers:
            return prior_speaker, line.strip()
        if ":" in line:
            candidate, text = line.split(":", 1)
            candidate = candidate.strip()
            text = text.strip()
            if candidate and text and len(candidate) <= 80 and "\n" not in candidate:
                return candidate, text
        # Keeping the previous speaker makes normal prose edits timestamp/speaker safe.
        return prior_speaker, line.strip()

    @staticmethod
    def _segment_display_text(segment: TranscriptSegment, show_speaker: bool) -> str:
        speaker = segment.speaker.strip()
        text = segment.text.strip()
        if show_speaker and speaker:
            return f"{speaker}: {text}".rstrip()
        return text

    def _set_mode(self, mode: int) -> None:
        if mode not in (_EDITOR_MODE, _SEGMENTS_MODE):
            return
        if self._mode == _EDITOR_MODE and mode != _EDITOR_MODE:
            self.sync_to_project()
        elif mode == _EDITOR_MODE and self._project is not None:
            self._refresh_editor(self._project.transcript_segments)
        self._mode = mode
        self.content_stack.setCurrentIndex(mode)
        wanted = self.editor_mode_button if mode == _EDITOR_MODE else self.segments_mode_button
        if not wanted.isChecked():
            wanted.setChecked(True)
        self._apply_search(self.search_edit.text())

    def _show_speakers_changed(self, _checked: bool) -> None:
        self.sync_to_project()
        self._refresh_editor(self._segments())
        self._apply_search(self.search_edit.text())

    def _set_transcript_font_size(self, point_size: int) -> None:
        font = QFont(self.editor.font())
        font.setPointSize(point_size)
        self.editor.setFont(font)
        table_font = QFont(self.segment_table.font())
        table_font.setPointSize(point_size)
        self.segment_table.setFont(table_font)
        self.segment_table.verticalHeader().setDefaultSectionSize(max(42, point_size * 3))

    # ---------------------------------------------------------- search / copy

    def _apply_search(self, query: str) -> None:
        query = query.strip()
        query_folded = query.casefold()
        for row, segment in enumerate(self._segments()):
            haystack = f"{segment.speaker}\n{segment.text}".casefold()
            self.segment_table.setRowHidden(row, bool(query and query_folded not in haystack))

        extra_selections: list[QTextEdit.ExtraSelection] = []
        if query:
            document = self.editor.document()
            search_cursor = QTextCursor(document)
            search_cursor.movePosition(QTextCursor.Start)
            highlight = QTextCharFormat()
            highlight.setBackground(QColor("#ffe28a"))
            highlight.setForeground(QColor("#352b00"))
            for _ in range(500):
                found = document.find(query, search_cursor)
                if found.isNull():
                    break
                selection = QTextEdit.ExtraSelection()
                selection.cursor = found
                selection.format = highlight
                extra_selections.append(selection)
                search_cursor = found
        self.editor.setExtraSelections(extra_selections)

    def _copy_transcript(self) -> None:
        self.sync_to_project()
        text = ""
        if self._mode == _EDITOR_MODE:
            cursor = self.editor.textCursor()
            if cursor.hasSelection():
                text = cursor.selectedText().replace("\u2029", "\n")
        else:
            rows = sorted({index.row() for index in self.segment_table.selectionModel().selectedRows()})
            if rows:
                text = "\n".join(
                    self._segment_display_text(
                        self._project.transcript_segments[row],  # type: ignore[union-attr]
                        self.show_speakers_check.isChecked(),
                    )
                    for row in rows
                    if self._project is not None and row < len(self._project.transcript_segments)
                )
        if not text:
            text = "\n".join(
                self._segment_display_text(segment, self.show_speakers_check.isChecked())
                for segment in self._segments()
            )
        if text:
            QApplication.clipboard().setText(text)

    # --------------------------------------------------------------- speakers

    def _rebuild_people(self) -> None:
        while self.people_layout.count():
            item = self.people_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        speakers: list[str] = []
        seen: set[str] = set()
        for segment in self._segments():
            speaker = segment.speaker.strip()
            key = speaker.casefold()
            if speaker and key not in seen:
                seen.add(key)
                speakers.append(speaker)

        if not speakers:
            self._speaker_colors = {}
            empty_label = QLabel("No speakers identified")
            empty_label.setObjectName("emptyPeopleLabel")
            empty_label.setContentsMargins(8, 9, 8, 9)
            self.people_layout.addWidget(empty_label)
            return

        self._speaker_colors = {
            speaker.casefold(): QColor(_SPEAKER_COLORS[index % len(_SPEAKER_COLORS)])
            for index, speaker in enumerate(speakers)
        }
        for speaker in speakers:
            button = QPushButton(f"●   {speaker}")
            button.setObjectName("speakerAssignmentButton")
            button.setFlat(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(f"Assign {speaker} to the selected segment")
            button.setStyleSheet(
                "QPushButton {"
                f"color: {self._speaker_color(speaker).name()};"
                "text-align: left; border: none; border-bottom: 1px solid palette(midlight);"
                "padding: 10px 7px; font-weight: 600;"
                "} QPushButton:hover { background: palette(alternate-base); }"
            )
            button.clicked.connect(
                lambda _checked=False, name=speaker: self._assign_speaker(name)
            )
            self.people_layout.addWidget(button)

    def _selected_segment_rows(self) -> list[int]:
        if not self._segments():
            return []
        if self._mode == _SEGMENTS_MODE:
            rows = sorted({index.row() for index in self.segment_table.selectionModel().selectedRows()})
            if not rows and self.segment_table.currentRow() >= 0:
                rows = [self.segment_table.currentRow()]
            return [row for row in rows if 0 <= row < len(self._segments())]

        cursor_block = self.editor.textCursor().blockNumber()
        nonempty_index = -1
        block = self.editor.document().firstBlock()
        while block.isValid():
            if block.text().strip():
                nonempty_index += 1
            if block.blockNumber() == cursor_block:
                break
            block = block.next()
        if 0 <= nonempty_index < len(self._segments()):
            return [nonempty_index]
        return []

    def _assign_speaker(self, speaker: str) -> None:
        speaker = speaker.strip()
        if not speaker or self._project is None:
            return
        self.sync_to_project()
        rows = self._selected_segment_rows()
        if not rows and self._project.transcript_segments:
            rows = [0]
        for row in rows:
            self._project.transcript_segments[row].speaker = speaker
        self.refresh_segments()
        if rows and self._mode == _SEGMENTS_MODE:
            for row in rows:
                self.segment_table.selectRow(row)

    def _add_or_assign_speaker(self) -> None:
        speaker = self.add_speaker_edit.text().strip()
        if not speaker:
            return
        self._assign_speaker(speaker)
        self.add_speaker_edit.clear()

    def _update_add_speaker_button(self, *_args) -> None:
        self.add_speaker_button.setEnabled(
            bool(self.add_speaker_edit.text().strip()) and bool(self._segments())
        )

    def _speaker_color(self, speaker: str) -> QColor:
        """Return the distinct accent assigned by first appearance in the transcript."""

        return self._speaker_colors.get(speaker.strip().casefold(), QColor(_SPEAKER_COLORS[0]))

    # --------------------------------------------------------------- playback

    def _build_player(self) -> None:
        if QMediaPlayer is None or QAudioOutput is None:
            self.play_button.setEnabled(False)
            self.position_slider.setEnabled(False)
            self.playback_rate_box.setEnabled(False)
            unavailable = "Audio preview is unavailable in this PySide build."
            self.play_button.setToolTip(unavailable)
            self.position_slider.setToolTip(unavailable)
            return

        self._audio_output = QAudioOutput(self)
        self._audio_output.setVolume(1.0)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.positionChanged.connect(self._on_player_position)
        self._player.durationChanged.connect(self._on_player_duration)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        if hasattr(self._player, "errorOccurred"):
            self._player.errorOccurred.connect(self._on_player_error)

    def _configure_audio_sources(self) -> None:
        self._source_paths = []
        self._source_durations_ms = []
        if self._project is not None:
            for source in self._project.audio_sources:
                path = Path(source.source_path)
                if not path.exists():
                    continue
                self._source_paths.append(path)
                self._source_durations_ms.append(max(0, int(round(source.duration_seconds * 1000))))
        self._recalculate_source_offsets()
        available = bool(self._source_paths) and self._player is not None
        self.play_button.setEnabled(available)
        self.position_slider.setEnabled(available)
        self.playback_rate_box.setEnabled(available)
        if self._project is not None and self._project.audio_sources and not self._source_paths:
            self.play_button.setToolTip("The project audio files could not be found.")
        elif available:
            self.play_button.setToolTip("Play")

    def _recalculate_source_offsets(self) -> None:
        offsets: list[int] = []
        running_total = 0
        for duration in self._source_durations_ms:
            offsets.append(running_total)
            running_total += max(0, duration)
        self._source_offsets_ms = offsets
        self._total_duration_ms = running_total
        self.position_slider.setRange(0, max(0, running_total))
        self._set_global_position(min(self.position_slider.value(), running_total))

    def _toggle_playback(self) -> None:
        if self._player is None or not self._source_paths:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._play_requested = False
            self._player.pause()
            return
        self._play_requested = True
        global_position = self.position_slider.value()
        if self._total_duration_ms and global_position >= self._total_duration_ms:
            global_position = 0
        source_index, local_position = self._source_for_global_position(global_position)
        if source_index < 0:
            return
        if source_index != self._active_source_index:
            self._load_source(source_index, local_position, play=True)
        else:
            self._player.setPosition(local_position)
            self._player.play()

    def _load_source(self, index: int, local_position_ms: int, *, play: bool) -> None:
        if self._player is None or index < 0 or index >= len(self._source_paths):
            return
        self._active_source_index = index
        self._pending_local_position_ms = max(0, local_position_ms)
        self._pending_play_after_load = play
        self._player.setSource(QUrl.fromLocalFile(str(self._source_paths[index])))

    def _source_for_global_position(self, position_ms: int) -> tuple[int, int]:
        if not self._source_offsets_ms:
            return -1, 0
        position_ms = max(0, min(position_ms, self._total_duration_ms))
        index = bisect_right(self._source_offsets_ms, position_ms) - 1
        index = max(0, min(index, len(self._source_offsets_ms) - 1))
        # At an exact zero-duration boundary, advance to the next playable source.
        while index < len(self._source_durations_ms) - 1 and position_ms >= (
            self._source_offsets_ms[index] + self._source_durations_ms[index]
        ):
            index += 1
        return index, max(0, position_ms - self._source_offsets_ms[index])

    def _on_player_position(self, local_position_ms: int) -> None:
        if self._active_source_index < 0 or self._active_source_index >= len(self._source_offsets_ms):
            return
        global_position = self._source_offsets_ms[self._active_source_index] + local_position_ms
        if not self._seeking:
            self._set_global_position(global_position)

    def _on_player_duration(self, duration_ms: int) -> None:
        index = self._active_source_index
        if index < 0 or index >= len(self._source_durations_ms) or duration_ms <= 0:
            return
        if self._source_durations_ms[index] <= 0:
            current_global = self._source_offsets_ms[index] + (
                self._player.position() if self._player is not None else 0
            )
            self._source_durations_ms[index] = duration_ms
            self._recalculate_source_offsets()
            self._set_global_position(current_global)

    def _on_media_status_changed(self, status) -> None:
        if self._player is None:
            return
        loaded_statuses = {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }
        if status in loaded_statuses and self._pending_local_position_ms is not None:
            pending_position = self._pending_local_position_ms
            pending_play = self._pending_play_after_load
            self._pending_local_position_ms = None
            self._pending_play_after_load = False
            self._player.setPosition(pending_position)
            if pending_play:
                self._player.play()
            return
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            next_index = self._active_source_index + 1
            if self._play_requested and next_index < len(self._source_paths):
                self._load_source(next_index, 0, play=True)
            else:
                self._play_requested = False
                self._set_global_position(self._total_duration_ms)
                self._update_play_button(False)

    def _on_playback_state_changed(self, state) -> None:
        self._update_play_button(state == QMediaPlayer.PlaybackState.PlayingState)

    def _on_player_error(self, *_args) -> None:
        if self._player is None or self._player.error() == QMediaPlayer.Error.NoError:
            return
        self._play_requested = False
        detail = self._player.errorString().strip() or "Audio playback failed."
        self.play_button.setToolTip(detail)
        self._update_play_button(False)

    def _update_play_button(self, playing: bool) -> None:
        self.play_button.setText("❚❚" if playing else "▶")
        self.play_button.setToolTip("Pause" if playing else "Play")
        self.play_button.setAccessibleName("Pause" if playing else "Play")

    def _begin_seek(self) -> None:
        self._seeking = True

    def _preview_seek(self, position_ms: int) -> None:
        self._update_position_label(position_ms)

    def _finish_seek(self) -> None:
        self._seeking = False
        self._seek_global(self.position_slider.value())

    def _seek_global(self, position_ms: int) -> None:
        if self._player is None or not self._source_paths:
            return
        was_playing = (
            self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        source_index, local_position = self._source_for_global_position(position_ms)
        if source_index < 0:
            return
        self._set_global_position(position_ms)
        if source_index != self._active_source_index:
            self._load_source(source_index, local_position, play=was_playing)
        else:
            self._player.setPosition(local_position)

    def _seek_to_segment(self, row: int, _column: int) -> None:
        segments = self._segments()
        if 0 <= row < len(segments):
            self._seek_global(int(round(segments[row].start_time_seconds * 1000)))

    def _set_global_position(self, position_ms: int) -> None:
        position_ms = max(0, min(position_ms, self._total_duration_ms))
        blocker = QSignalBlocker(self.position_slider)
        try:
            self.position_slider.setValue(position_ms)
        finally:
            del blocker
        self._update_position_label(position_ms)

    def _update_position_label(self, position_ms: int) -> None:
        self.position_label.setText(
            f"{_format_clock_ms(position_ms)} / {_format_clock_ms(self._total_duration_ms)}"
        )

    def _set_playback_rate(self, _index: int) -> None:
        if self._player is not None:
            rate = self.playback_rate_box.currentData()
            self._player.setPlaybackRate(float(rate) if rate is not None else 1.0)


def _format_time(seconds: float, *, include_milliseconds: bool = False) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    if hours:
        base = f"{hours:d}:{minutes:02d}:{whole_seconds:02d}"
    else:
        base = f"{minutes:02d}:{whole_seconds:02d}"
    return f"{base}.{millis:03d}" if include_milliseconds else base


def _format_clock_ms(milliseconds: int) -> str:
    return _format_time(max(0, milliseconds) / 1000.0)


__all__ = ["TranscriptWorkspace"]

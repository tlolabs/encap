from __future__ import annotations

import os

# Qt must select its headless platform before PySide6 (directly or indirectly) is imported.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QEvent, QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDropEvent, QKeySequence, QPixmap
from PySide6.QtWidgets import QApplication, QTabWidget

from encap.gui import EncapWindow
from encap.models import (
    AudioSourceEntry,
    ChapterEntry,
    ExportSettings,
    ProjectDocument,
    TranscriptSegment,
)
from encap.project_io import cleanup_loaded_project, load_project


class GuiWorkspacesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.update_patch = patch.object(EncapWindow, "_initialize_updates", return_value=None)
        self.update_patch.start()
        self.addCleanup(self.update_patch.stop)

        self.window = EncapWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.close()
        self.app.processEvents()
        super().tearDown()

    def test_activity_tabs_are_top_level_workspaces_and_switch_complete_pages(self) -> None:
        tabs = self.window.activity_tabs

        self.assertEqual(tabs.count(), 2)
        self.assertEqual([tabs.tabText(index) for index in range(tabs.count())], [
            "Process Audio",
            "Transcribe",
        ])
        self.assertEqual(tabs.tabPosition(), QTabWidget.North)
        self.assertIs(tabs.widget(0), self.window.process_audio_page)
        self.assertIs(tabs.widget(1), self.window.transcribe_page)

        # The controls belong to their activity page, rather than remaining visible around it.
        self.assertTrue(self.window.process_audio_page.isAncestorOf(self.window.podcast_edit))
        self.assertTrue(self.window.process_audio_page.isAncestorOf(self.window.chapter_table))
        self.assertTrue(self.window.transcribe_page.isAncestorOf(self.window.transcript_edit))
        self.assertTrue(
            self.window.transcribe_page.isAncestorOf(self.window.transcript_segment_table)
        )

        tabs.setCurrentWidget(self.window.process_audio_page)
        self.app.processEvents()
        self.assertIs(tabs.currentWidget(), self.window.process_audio_page)
        self.assertTrue(self.window.process_audio_page.isVisible())
        self.assertTrue(self.window.podcast_edit.isVisible())
        self.assertFalse(self.window.transcribe_page.isVisible())

        tabs.setCurrentWidget(self.window.transcribe_page)
        self.app.processEvents()
        self.assertIs(tabs.currentWidget(), self.window.transcribe_page)
        self.assertTrue(self.window.transcribe_page.isVisible())
        self.assertIs(
            self.window.transcribe_page.content_stack.currentWidget(),
            self.window.transcript_segment_table,
        )
        self.assertFalse(self.window.process_audio_page.isVisible())
        self.assertFalse(self.window.podcast_edit.isVisible())
        self.assertFalse(self.window.chapter_table.isVisible())

    def test_workspace_styles_use_the_application_palette(self) -> None:
        styles = "\n".join(
            (
                self.window.activity_tabs.styleSheet(),
                self.window.transcribe_page.styleSheet(),
            )
        ).lower()

        for role in (
            "palette(window)",
            "palette(base)",
            "palette(alternate-base)",
            "palette(button)",
            "palette(text)",
            "palette(highlight)",
            "palette(highlighted-text)",
        ):
            with self.subTest(role=role):
                self.assertIn(role, styles)

        # Neutral surfaces and selections must come from the active macOS
        # appearance instead of locking either workspace to the light theme.
        for fixed_color in (
            "#e7e7e7",
            "#f4f4f4",
            "#ffffff",
            "#ededed",
            "#dcdcdc",
            "#168bd2",
        ):
            with self.subTest(fixed_color=fixed_color):
                self.assertNotIn(fixed_color, styles)

    def test_live_appearance_changes_reapply_styles_once_after_palette_settles(self) -> None:
        original_activity_style = self.window.activity_tabs.styleSheet()
        original_transcribe_style = self.window.transcribe_page.styleSheet()

        with patch.object(
            self.window.transcribe_page,
            "refresh_appearance",
            wraps=self.window.transcribe_page.refresh_appearance,
        ) as refresh_transcribe:
            # macOS/Qt can deliver application, widget palette, and theme events
            # for a single appearance toggle. They should collapse into one repaint.
            QApplication.sendEvent(
                self.app,
                QEvent(QEvent.ApplicationPaletteChange),
            )
            QApplication.sendEvent(
                self.window,
                QEvent(QEvent.PaletteChange),
            )
            QApplication.sendEvent(
                self.window,
                QEvent(QEvent.ThemeChange),
            )
            self.app.processEvents()

        self.assertEqual(refresh_transcribe.call_count, 1)
        self.assertEqual(self.window.activity_tabs.styleSheet(), original_activity_style)
        self.assertEqual(self.window.transcribe_page.styleSheet(), original_transcribe_style)
        self.assertTrue(self.window.updatesEnabled())

    def test_log_is_a_persistent_dock_toggled_from_the_view_menu(self) -> None:
        tabs = self.window.activity_tabs
        self.assertNotIn("Log", [tabs.tabText(index) for index in range(tabs.count())])

        # Call QAction.menu() once per action. Repeated temporary wrappers can have
        # surprising ownership semantics in some PySide6 builds.
        view_menus = []
        for menu_action in self.window.menuBar().actions():
            menu = menu_action.menu()
            if menu is not None and menu.title().replace("&", "") == "View":
                view_menus.append(menu)
        self.assertEqual(len(view_menus), 1)
        self.assertIn(self.window.log_action, view_menus[0].actions())
        self.assertEqual(self.window.log_action.text().replace("&", ""), "Log")
        self.assertTrue(self.window.log_action.isCheckable())

        if self.window.log_dock.isVisible():
            self.window.log_action.trigger()
            self.app.processEvents()
        self.assertFalse(self.window.log_dock.isVisible())
        self.assertFalse(self.window.log_action.isChecked())

    def test_native_menu_structure_uses_platform_conventions(self) -> None:
        top_level = [
            action.menu().title().replace("&", "")
            for action in self.window.menuBar().actions()
            if action.menu() is not None
        ]
        self.assertEqual(top_level, ["File", "Edit", "View", "Window", "Help"])

        file_labels = [action.text().replace("&", "") for action in self.window.file_menu.actions()]
        self.assertLess(file_labels.index("Import Audio Folder…"), file_labels.index("Open Project…"))
        self.assertLess(file_labels.index("Open Project…"), file_labels.index("Save Project…"))
        self.assertEqual(
            [
                action.text()
                for action in self.window.export_menu.actions()
                if not action.isSeparator()
            ],
            ["All…", "Audio…", "Transcript as TXT…", "Transcript as SRT…"],
        )
        self.assertEqual(
            [action.text() for action in self.window.transcription_menu.actions() if not action.isSeparator()],
            ["Transcribe", "Manage Models…", "Summary", "Title Suggestion"],
        )
        self.assertEqual(self.window.about_action.menuRole(), QAction.MenuRole.AboutRole)
        self.assertEqual(self.window.quit_action.menuRole(), QAction.MenuRole.QuitRole)
        self.assertEqual(
            self.window.check_updates_action.menuRole(),
            QAction.MenuRole.NoRole,
        )
        self.assertEqual(
            self.window.process_audio_view_action.shortcut(),
            QKeySequence("Ctrl+1"),
        )
        self.assertEqual(
            self.window.transcribe_view_action.shortcut(),
            QKeySequence("Ctrl+2"),
        )
        self.assertEqual(
            self.window.toolbar_actions["export_all"].shortcut(),
            QKeySequence("Ctrl+Shift+E"),
        )

        original_dock = self.window.log_dock
        self.window.append_log("message retained while the log is closed")
        self.window.log_action.trigger()
        self.app.processEvents()

        self.assertIs(self.window.log_dock, original_dock)
        self.assertTrue(self.window.log_dock.isVisible())
        self.assertTrue(self.window.log_action.isChecked())
        self.assertIn("message retained while the log is closed", self.window.log_output.toPlainText())

        self.window.log_action.trigger()
        self.app.processEvents()
        self.assertIs(self.window.log_dock, original_dock)
        self.assertFalse(self.window.log_dock.isVisible())
        self.assertFalse(self.window.log_action.isChecked())

    def test_toolbar_hides_process_only_actions_in_transcribe_workspace(self) -> None:
        process_only = {"choose_artwork", "export_audio", "ai_summary", "ai_title"}
        shared = {
            "import_audio",
            "open_project",
            "save_project",
            "export_txt",
            "export_srt",
            "transcribe",
        }

        self.window.activity_tabs.setCurrentWidget(self.window.process_audio_page)
        self.app.processEvents()
        # Qt may place wide actions in the toolbar overflow on some platforms.
        # Membership plus QAction visibility is the stable workspace contract.
        for key in process_only | shared:
            with self.subTest(workspace="Process Audio", action=key):
                widget = self.window.main_toolbar.widgetForAction(self.window.toolbar_actions[key])
                self.assertIsNotNone(widget)
                self.assertTrue(self.window.toolbar_actions[key].isVisible())

        self.window.activity_tabs.setCurrentWidget(self.window.transcribe_page)
        self.app.processEvents()
        for key in process_only:
            with self.subTest(workspace="Transcribe", action=key):
                widget = self.window.main_toolbar.widgetForAction(self.window.toolbar_actions[key])
                self.assertIsNone(widget)
                self.assertTrue(self.window.toolbar_actions[key].isVisible())
        for key in shared:
            with self.subTest(workspace="Transcribe", action=key):
                widget = self.window.main_toolbar.widgetForAction(self.window.toolbar_actions[key])
                self.assertIsNotNone(widget)
                self.assertTrue(self.window.toolbar_actions[key].isVisible())

    def test_transcript_exports_enable_only_with_audio_and_transcript(self) -> None:
        export_keys = ("export_all", "export_txt", "export_srt")
        for key in (*export_keys, "export_audio"):
            self.assertFalse(self.window.toolbar_actions[key].isEnabled())

        self.window.project = ProjectDocument(
            project_title="Episode",
            audio_sources=[AudioSourceEntry(Path("/audio/one.wav"), "one.wav", 1.0)],
        )
        self.window.transcribe_page.set_project(self.window.project)
        self.window._update_export_actions()
        self.assertTrue(self.window.toolbar_actions["export_audio"].isEnabled())
        for key in export_keys:
            self.assertFalse(self.window.toolbar_actions[key].isEnabled())

        self.window.project.transcript_segments = [
            TranscriptSegment(0.0, 1.0, "Host", "A finished transcript")
        ]
        self.window.transcribe_page.set_project(self.window.project)
        for key in export_keys:
            self.assertTrue(self.window.toolbar_actions[key].isEnabled())

    def test_audio_export_uses_save_dialog_with_editable_prefilled_name(self) -> None:
        self.window.project = ProjectDocument(
            project_title="Current Episode Name",
            audio_sources=[AudioSourceEntry(Path("/audio/one.wav"), "one.wav", 1.0)],
        )
        requested_path = Path("/exports/renamed-episode.mp3")
        with (
            patch("encap.gui.QFileDialog.getSaveFileName", return_value=(str(requested_path), "")) as dialog,
            patch("encap.gui.export_project", return_value=requested_path) as exporter,
            patch("encap.gui.QMessageBox.information"),
        ):
            self.window.export_audio()

        self.assertTrue(str(dialog.call_args.args[2]).endswith("Current-Episode-Name.mp3"))
        exporter.assert_called_once_with(
            self.window.project,
            requested_path.parent,
            prompt_for_conversion=self.window.confirm_conversion,
            output_path=requested_path,
        )

    def test_export_all_uses_selected_audio_name_for_all_three_files(self) -> None:
        self.window.project = ProjectDocument(
            project_title="Episode",
            audio_sources=[AudioSourceEntry(Path("/audio/one.wav"), "one.wav", 1.0)],
            transcript_segments=[TranscriptSegment(0.0, 1.0, "Host", "Hello")],
        )
        with tempfile.TemporaryDirectory() as temp_dir_name:
            audio_path = Path(temp_dir_name) / "custom-name.mp3"
            txt_path = Path(temp_dir_name) / "custom-name-transcript.txt"
            srt_path = Path(temp_dir_name) / "custom-name-transcript.srt"
            with (
                patch("encap.gui.QFileDialog.getSaveFileName", return_value=(str(audio_path), "")),
                patch("encap.gui.export_project", return_value=audio_path) as audio_exporter,
                patch("encap.gui.export_transcript_txt") as txt_exporter,
                patch("encap.gui.export_transcript_srt") as srt_exporter,
                patch("encap.gui.QMessageBox.information"),
            ):
                self.window.export_all()

            audio_exporter.assert_called_once_with(
                self.window.project,
                audio_path.parent,
                prompt_for_conversion=self.window.confirm_conversion,
                output_path=audio_path,
            )
            txt_exporter.assert_called_once_with(self.window.project, txt_path)
            srt_exporter.assert_called_once_with(self.window.project, srt_path)

    def test_dropped_audio_folder_is_imported_by_chapter_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            audio_folder = Path(temp_dir_name) / "audio"
            audio_folder.mkdir()
            (audio_folder / "chapter.aiff").write_bytes(b"placeholder")
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(audio_folder))])
            drop = QDropEvent(
                QPointF(10, 10),
                Qt.CopyAction,
                mime,
                Qt.LeftButton,
                Qt.NoModifier,
            )
            with patch.object(self.window, "_import_audio_path") as importer:
                self.window.chapter_table.dropEvent(drop)
                self.app.processEvents()

            self.assertTrue(drop.isAccepted())
            importer.assert_called_once_with(audio_folder)

    def test_repeated_audio_import_can_merge_chronologically_and_renumber(self) -> None:
        def source(name: str, duration: float) -> AudioSourceEntry:
            return AudioSourceEntry(Path("/audio") / name, name, duration)

        self.window.project = ProjectDocument(
            audio_sources=[source("05042026120000_DN-700R.wav", 2.0)],
            chapters=[ChapterEntry(0.0, 2.0, 1, "Opening")],
        )
        imported = ProjectDocument(
            audio_sources=[
                source("05042026110000_DN-700R.aiff", 1.0),
                source("05042026130000_DN-700R.wav", 3.0),
            ],
            chapters=[
                ChapterEntry(0.0, 1.0, 1, "Chapter 1"),
                ChapterEntry(1.0, 3.0, 2, "Chapter 2"),
            ],
        )

        self.window._merge_imported_audio(imported, "chronological")

        self.assertEqual(
            [entry.display_name for entry in self.window.project.audio_sources],
            [
                "05042026110000_DN-700R.aiff",
                "05042026120000_DN-700R.wav",
                "05042026130000_DN-700R.wav",
            ],
        )
        self.assertEqual([chapter.chapter_number for chapter in self.window.project.chapters], [1, 2, 3])
        self.assertEqual([chapter.start_time_seconds for chapter in self.window.project.chapters], [0.0, 1.0, 3.0])
        self.assertEqual([chapter.title for chapter in self.window.project.chapters], ["Chapter 1", "Opening", "Chapter 3"])

    def test_repeated_audio_import_can_insert_at_beginning_or_end(self) -> None:
        def make_project(name: str, duration: float) -> ProjectDocument:
            return ProjectDocument(
                audio_sources=[AudioSourceEntry(Path("/audio") / name, name, duration)],
                chapters=[ChapterEntry(0.0, duration, 1, "Chapter 1")],
            )

        for insertion, expected_names in [
            ("beginning", ["new.wav", "existing.wav"]),
            ("end", ["existing.wav", "new.wav"]),
        ]:
            with self.subTest(insertion=insertion):
                self.window.project = make_project("existing.wav", 2.0)
                self.window._merge_imported_audio(make_project("new.wav", 1.0), insertion)
                self.assertEqual(
                    [entry.display_name for entry in self.window.project.audio_sources],
                    expected_names,
                )
                self.assertEqual(
                    [chapter.chapter_number for chapter in self.window.project.chapters],
                    [1, 2],
                )
                expected_starts = [0.0, 1.0] if insertion == "beginning" else [0.0, 2.0]
                self.assertEqual(
                    [chapter.start_time_seconds for chapter in self.window.project.chapters],
                    expected_starts,
                )

    def test_artwork_drop_targets_render_episode_and_chapter_previews(self) -> None:
        self.window.project = ProjectDocument(
            project_title="Artwork Project",
            chapters=[
                ChapterEntry(
                    start_time_seconds=0.0,
                    duration_seconds=5.0,
                    chapter_number=1,
                    title="Opening",
                )
            ],
        )
        self.window._populate_form_from_project()

        with tempfile.TemporaryDirectory() as temp_dir_name:
            image_path = Path(temp_dir_name) / "cover.png"
            pixmap = QPixmap(96, 64)
            pixmap.fill(QColor("#168bd2"))
            self.assertTrue(pixmap.save(str(image_path), "PNG"))

            self.assertTrue(self.window.artwork_label.acceptDrops())
            artwork_mime = QMimeData()
            artwork_mime.setUrls([QUrl.fromLocalFile(str(image_path))])
            artwork_drop = QDropEvent(
                QPointF(10, 10),
                Qt.CopyAction,
                artwork_mime,
                Qt.LeftButton,
                Qt.NoModifier,
            )
            self.window.artwork_label.dropEvent(artwork_drop)
            self.app.processEvents()
            self.assertTrue(artwork_drop.isAccepted())
            self.assertEqual(self.window.project.metadata.artwork_path, image_path)
            self.assertIsNotNone(self.window.artwork_label.pixmap())
            self.assertFalse(self.window.artwork_label.pixmap().isNull())

            self.assertTrue(self.window.chapter_table.acceptDrops())
            self.assertTrue(self.window.chapter_table.viewport().acceptDrops())
            image_item = self.window.chapter_table.item(0, 5)
            image_cell_center = self.window.chapter_table.visualItemRect(image_item).center()
            chapter_mime = QMimeData()
            chapter_mime.setUrls([QUrl.fromLocalFile(str(image_path))])
            chapter_drop = QDropEvent(
                QPointF(image_cell_center),
                Qt.CopyAction,
                chapter_mime,
                Qt.LeftButton,
                Qt.NoModifier,
            )
            self.window.chapter_table.dropEvent(chapter_drop)
            self.app.processEvents()
            self.assertTrue(chapter_drop.isAccepted())
            self.assertEqual(self.window.project.chapters[0].image_path, image_path)
            self.assertFalse(self.window.chapter_table.item(0, 5).icon().isNull())

            # Empty chapter links use the link affordance instead of the old reset icon.
            self.assertFalse(self.window.chapter_table.item(0, 4).icon().isNull())

    def test_artwork_can_create_and_save_a_project_without_audio(self) -> None:
        self.assertIsNone(self.window.project)

        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            image_path = temp_dir / "artwork-only.png"
            pixmap = QPixmap(80, 80)
            pixmap.fill(QColor("#168bd2"))
            self.assertTrue(pixmap.save(str(image_path), "PNG"))

            self.assertTrue(self.window._set_episode_artwork(image_path))
            self.assertIsNotNone(self.window.project)
            self.assertEqual(self.window.project.audio_sources, [])

            project_path = temp_dir / "artwork-only.encap"
            with patch(
                "encap.gui.QFileDialog.getSaveFileName",
                return_value=(str(project_path), "EnCap Project (*.encap)"),
            ):
                self.window.save_project_file()

            loaded = load_project(project_path)
            self.addCleanup(lambda: cleanup_loaded_project(loaded))
            self.assertEqual(loaded.audio_sources, [])
            self.assertIsNotNone(loaded.metadata.artwork_path)
            self.assertTrue(loaded.metadata.artwork_path.exists())

    def test_process_audio_layout_prioritizes_text_and_square_artwork(self) -> None:
        self.assertEqual(self.window.artwork_label.heightForWidth(240), 240)
        self.assertLessEqual(self.window.format_box.maximumWidth(), 115)
        self.assertLessEqual(self.window.quality_box.maximumWidth(), 115)
        self.assertGreaterEqual(self.window.encoder_box.minimumWidth(), 245)
        self.assertLessEqual(self.window.chapter_table.iconSize().width(), 20)
        self.assertLessEqual(self.window.chapter_table.iconSize().height(), 20)
        self.assertLessEqual(self.window.chapter_table.columnWidth(5), 90)

    def test_codec_and_channels_filter_encoders_and_bitrates(self) -> None:
        def select_data(combo, value) -> None:
            index = combo.findData(value)
            self.assertGreaterEqual(index, 0)
            combo.setCurrentIndex(index)
            self.app.processEvents()

        def item_data(combo) -> list:
            return [combo.itemData(index) for index in range(combo.count())]

        self.assertEqual(self.window.format_box.currentData(), "mp3")
        if self.window.capabilities.lame_available:
            self.assertEqual(self.window.encoder_box.currentData(), "lame")
        self.assertEqual(self.window.channels_box.currentData(), 2)
        self.assertEqual(self.window.quality_box.currentData(), "320k")

        select_data(self.window.format_box, "mp3")
        self.assertIn("ffmpeg", item_data(self.window.encoder_box))
        self.assertNotIn("audio_toolbox", item_data(self.window.encoder_box))
        self.assertEqual(self.window.encoder_box.itemText(0), "FFmpeg MP3")
        if self.window.capabilities.lame_available:
            lame_index = self.window.encoder_box.findData("lame")
            self.assertGreaterEqual(lame_index, 0)
            self.assertEqual(self.window.encoder_box.itemText(lame_index), "LAME MP3")
        select_data(self.window.channels_box, 2)
        self.assertEqual(
            item_data(self.window.quality_box),
            ["96k", "128k", "160k", "192k", "224k", "256k", "320k"],
        )
        select_data(self.window.channels_box, 1)
        self.assertEqual(
            item_data(self.window.quality_box),
            ["64k", "80k", "96k", "112k", "128k", "160k"],
        )

        select_data(self.window.format_box, "aac")
        self.assertIn("ffmpeg", item_data(self.window.encoder_box))
        self.assertNotIn("lame", item_data(self.window.encoder_box))
        self.assertEqual(self.window.encoder_box.itemText(0), "FFmpeg AAC")
        if self.window.capabilities.audio_toolbox_aac_available:
            self.assertIn("audio_toolbox", item_data(self.window.encoder_box))
            audio_toolbox_index = self.window.encoder_box.findData("audio_toolbox")
            self.assertEqual(
                self.window.encoder_box.itemText(audio_toolbox_index),
                "Apple AudioToolbox AAC",
            )
        select_data(self.window.channels_box, 2)
        self.assertEqual(
            item_data(self.window.quality_box),
            ["64k", "96k", "128k", "160k", "192k", "256k", "320k"],
        )
        select_data(self.window.channels_box, 1)
        self.assertEqual(
            item_data(self.window.quality_box),
            ["48k", "64k", "80k", "96k", "128k", "160k"],
        )

    def test_artwork_selected_before_audio_survives_audio_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            image_path = Path(temp_dir_name) / "cover-first.png"
            pixmap = QPixmap(64, 64)
            pixmap.fill(QColor("#168bd2"))
            self.assertTrue(pixmap.save(str(image_path), "PNG"))
            self.assertTrue(self.window._set_episode_artwork(image_path))

            imported_project = ProjectDocument(
                project_title="Imported Audio",
                export_settings=ExportSettings(
                    output_format="mp3",
                    encoder="lame",
                    channels=1,
                    quality_preset="160k",
                ),
            )
            with (
                patch(
                    "encap.gui.QFileDialog.getExistingDirectory",
                    return_value=str(Path(temp_dir_name) / "audio"),
                ),
                patch("encap.gui.build_project_document", return_value=imported_project),
            ):
                self.window.import_audio_folder()

            self.assertIs(self.window.project, imported_project)
            self.assertEqual(self.window.project.metadata.artwork_path, image_path)
            self.assertEqual(self.window.project.export_settings.channels, 1)
            self.assertEqual(self.window.project.export_settings.quality_preset, "160k")
            self.assertEqual(self.window.channels_box.currentData(), 1)
            self.assertEqual(self.window.quality_box.currentData(), "160k")
            self.assertIsNotNone(self.window.artwork_label.pixmap())
            self.assertFalse(self.window.artwork_label.pixmap().isNull())

    def test_segment_table_edit_preserves_timing_when_workspace_is_saved(self) -> None:
        original_start = 12.375
        original_end = 18.625
        self.window.project = ProjectDocument(
            project_title="Timed Transcript",
            transcript_segments=[
                TranscriptSegment(
                    start_time_seconds=original_start,
                    end_time_seconds=original_end,
                    speaker="Host",
                    text="Original timed text",
                )
            ],
        )
        self.window._populate_form_from_project()
        self.app.processEvents()

        table = self.window.transcript_segment_table
        self.assertEqual(table.rowCount(), 1)
        text_column = self._column_with_header(table, "text", "transcript", "content")
        text_item = table.item(0, text_column)
        self.assertIsNotNone(text_item)
        text_item.setText("Corrected timed text")
        self.app.processEvents()

        with tempfile.TemporaryDirectory() as temp_dir_name:
            project_path = Path(temp_dir_name) / "timed-transcript.encap"
            with patch(
                "encap.gui.QFileDialog.getSaveFileName",
                return_value=(str(project_path), "EnCap Project (*.encap)"),
            ):
                self.window.save_project_file()

            loaded = load_project(project_path)
            self.addCleanup(lambda: cleanup_loaded_project(loaded))

            self.assertEqual(len(loaded.transcript_segments), 1)
            saved_segment = loaded.transcript_segments[0]
            self.assertEqual(saved_segment.text, "Corrected timed text")
            self.assertEqual(saved_segment.speaker, "Host")
            self.assertAlmostEqual(saved_segment.start_time_seconds, original_start)
            self.assertAlmostEqual(saved_segment.end_time_seconds, original_end)

    def test_editor_corrections_preserve_existing_segment_timing(self) -> None:
        self.window.project = ProjectDocument(
            project_title="Editor Timing",
            transcript_segments=[
                TranscriptSegment(4.125, 7.75, "Host", "Original first line"),
                TranscriptSegment(8.5, 12.25, "Guest", "Original second line"),
            ],
        )
        self.window._populate_form_from_project()
        workspace = self.window.transcribe_page
        workspace.editor_mode_button.click()
        self.app.processEvents()

        workspace.editor.setPlainText("Host: Revised first line\nGuest: Revised second line")
        self.window._sync_project_from_form()

        self.assertEqual(
            [(segment.speaker, segment.text) for segment in self.window.project.transcript_segments],
            [("Host", "Revised first line"), ("Guest", "Revised second line")],
        )
        self.assertEqual(
            [
                (segment.start_time_seconds, segment.end_time_seconds)
                for segment in self.window.project.transcript_segments
            ],
            [(4.125, 7.75), (8.5, 12.25)],
        )

    def _column_with_header(self, table, *accepted_names: str) -> int:
        accepted = {name.casefold() for name in accepted_names}
        headers: list[str] = []
        for column in range(table.columnCount()):
            item = table.horizontalHeaderItem(column)
            label = item.text().strip() if item is not None else ""
            headers.append(label)
            if label.casefold() in accepted:
                return column
        self.fail(
            f"Expected one of {sorted(accepted_names)!r} in transcript table headers; "
            f"found {headers!r}"
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os

# Qt must select its headless platform before PySide6 is imported.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication, QLabel

from encap.gui import EncapWindow, ModelManagerDialog
from encap.transcription_models import (
    SUPERWHISPER_PROVIDER_ID,
    WHISPER_CPP_ENGINE,
    TranscriptionModelStore,
    TranscriptionProvider,
)
from encap.transcription_service import APPLE_PROVIDER_ID


class SharedModelManagerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.app = QApplication.instance() or QApplication([])

    def test_shared_provider_disables_duplicate_downloads(self) -> None:
        provider = TranscriptionProvider(
            provider_id=SUPERWHISPER_PROVIDER_ID,
            name="Whisper Large V3 — Superwhisper",
            engine=WHISPER_CPP_ENGINE,
            source_name="Superwhisper",
            model_path=Path("/shared/superwhisper/ggml-large-v3.bin"),
        )
        store = MagicMock(spec=TranscriptionModelStore)
        store.shared_providers.return_value = (provider,)
        store.selected_model_id.return_value = None
        store.is_installed.return_value = False
        store.model_path.side_effect = lambda model: Path("/encap/models") / model.filename

        dialog = ModelManagerDialog(store)
        self.addCleanup(dialog.close)

        self.assertFalse(dialog.download_button.isEnabled())
        self.assertFalse(dialog.use_button.isEnabled())
        self.assertFalse(dialog.remove_button.isEnabled())
        explanation = " ".join(label.text() for label in dialog.findChildren(QLabel))
        self.assertIn("without copying it", explanation)

    def test_shared_provider_precedes_apple_in_the_engine_picker(self) -> None:
        provider = TranscriptionProvider(
            provider_id=SUPERWHISPER_PROVIDER_ID,
            name="Whisper Large V3 — Superwhisper",
            engine=WHISPER_CPP_ENGINE,
            source_name="Superwhisper",
            model_path=Path("/shared/superwhisper/ggml-large-v3.bin"),
        )
        store = MagicMock(spec=TranscriptionModelStore)
        store.available_providers.return_value = (provider,)
        store.selected_model_id.return_value = None

        with patch(
            "encap.gui.TranscriptionModelStore",
            return_value=store,
        ), patch(
            "encap.gui.apple_transcription_available",
            return_value=True,
        ), patch.object(
            EncapWindow,
            "_initialize_updates",
            return_value=None,
        ):
            window = EncapWindow()
        self.addCleanup(window.close)

        provider_ids = [
            window.transcription_provider_box.itemData(index)
            for index in range(window.transcription_provider_box.count())
        ]
        self.assertEqual(provider_ids, [SUPERWHISPER_PROVIDER_ID, APPLE_PROVIDER_ID])
        self.assertEqual(window.transcription_provider_box.currentData(), SUPERWHISPER_PROVIDER_ID)


if __name__ == "__main__":
    unittest.main()

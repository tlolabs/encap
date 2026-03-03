from __future__ import annotations

import sys
from pathlib import Path

from .service import create_stitched_wav
from .wav_tools import EncapError

try:
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as exc:  # pragma: no cover
    missing_gui_dependency = exc
else:
    missing_gui_dependency = None


if missing_gui_dependency is None:

    class EncapWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("E.N.C.A.P.")
            self.resize(760, 480)

            self.source_input = QLineEdit()
            self.output_input = QLineEdit()
            self.name_input = QLineEdit("encap-output.wav")
            self.report_checkbox = QCheckBox("Write troubleshooting marker report")
            self.log_output = QTextEdit()
            self.log_output.setReadOnly(True)

            source_button = QPushButton("Choose Source Folder")
            source_button.clicked.connect(self.choose_source_dir)
            output_button = QPushButton("Choose Output Folder")
            output_button.clicked.connect(self.choose_output_dir)
            run_button = QPushButton("Build WAV")
            run_button.clicked.connect(self.run_encap)

            form = QFormLayout()
            form.addRow("Source folder", self._row_with_button(self.source_input, source_button))
            form.addRow("Output folder", self._row_with_button(self.output_input, output_button))
            form.addRow("Output name", self.name_input)
            form.addRow("", self.report_checkbox)

            layout = QVBoxLayout()
            layout.addLayout(form)
            layout.addWidget(run_button)
            layout.addWidget(QLabel("Run log"))
            layout.addWidget(self.log_output)

            container = QWidget()
            container.setLayout(layout)
            self.setCentralWidget(container)

        def _row_with_button(self, line_edit: QLineEdit, button: QPushButton) -> QWidget:
            widget = QWidget()
            layout = QHBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(line_edit)
            layout.addWidget(button)
            widget.setLayout(layout)
            return widget

        def choose_source_dir(self) -> None:
            folder = QFileDialog.getExistingDirectory(self, "Select source WAV folder")
            if folder:
                self.source_input.setText(folder)

        def choose_output_dir(self) -> None:
            folder = QFileDialog.getExistingDirectory(self, "Select output folder")
            if folder:
                self.output_input.setText(folder)

        def confirm_conversion(self, path: Path) -> bool:
            answer = QMessageBox.question(
                self,
                "Convert mismatched WAV?",
                (
                    f"{path.name} does not match the first WAV file.\n\n"
                    "Convert it to the reference format with ffmpeg before stitching?"
                ),
            )
            return answer == QMessageBox.StandardButton.Yes

        def run_encap(self) -> None:
            source_dir = Path(self.source_input.text().strip())
            output_dir = Path(self.output_input.text().strip())
            output_name = self.name_input.text().strip() or "encap-output.wav"

            if not source_dir.exists():
                QMessageBox.warning(self, "Missing source folder", "Choose a valid source folder.")
                return
            if not output_dir.exists():
                QMessageBox.warning(self, "Missing output folder", "Choose a valid output folder.")
                return

            self.log_output.clear()
            self.log_output.append(f"Source folder: {source_dir}")
            self.log_output.append(f"Output folder: {output_dir}")
            self.log_output.append(f"Output file: {output_name}")

            try:
                plan = create_stitched_wav(
                    source_dir=source_dir,
                    output_dir=output_dir,
                    output_name=output_name,
                    prompt_for_conversion=self.confirm_conversion,
                    write_report=self.report_checkbox.isChecked(),
                )
            except EncapError as exc:
                self.log_output.append("")
                self.log_output.append(f"Error: {exc}")
                QMessageBox.critical(self, "E.N.C.A.P. failed", str(exc))
                return

            self.log_output.append("")
            self.log_output.append(f"Wrote stitched WAV: {plan.output_path}")
            self.log_output.append(f"Cue markers added: {len(plan.markers)}")
            if plan.report_path is not None:
                self.log_output.append(f"Marker report: {plan.report_path}")
            QMessageBox.information(self, "E.N.C.A.P. complete", f"Created {plan.output_path.name}")


def main() -> int:
    if missing_gui_dependency is not None:  # pragma: no cover
        print(
            "PySide6 is required for the GUI. Install dependencies with `python3 -m pip install -e .`.",
            file=sys.stderr,
        )
        return 1

    app = QApplication(sys.argv)
    window = EncapWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

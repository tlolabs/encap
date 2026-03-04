from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from encap.service import (
        build_date_output_name,
        create_stitched_wav_for_paths,
        create_stitched_wavs_by_date,
        discover_wav_groups,
        parse_recorder_timestamp,
    )
    from encap.wav_tools import EncapError
else:
    from .service import (
        build_date_output_name,
        create_stitched_wav_for_paths,
        create_stitched_wavs_by_date,
        discover_wav_groups,
        parse_recorder_timestamp,
    )
    from .wav_tools import EncapError

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ModuleNotFoundError as exc:  # pragma: no cover
    missing_gui_dependency = exc
else:
    missing_gui_dependency = None


if missing_gui_dependency is None:

    AUTO_OUTPUT_NAME_PATTERN = re.compile(r"^encap-\d{1,2}\.\d{1,2}\.\d{2}\.wav$", re.IGNORECASE)

    class EncapApp:
        def __init__(self, root: tk.Tk) -> None:
            self.root = root
            self.root.title("En.C.A.P. – Encoder with Chapter Assembly Protocol")
            self.root.geometry("760x500")
            self.root.minsize(680, 420)

            self.source_var = tk.StringVar()
            self.output_var = tk.StringVar()
            self.name_var = tk.StringVar(value="encap-output.wav")
            self.report_var = tk.BooleanVar(value=False)
            self.launch_when_done_var = tk.BooleanVar(value=False)
            self.launch_program_var = tk.StringVar()

            self._build_ui()

        def _build_ui(self) -> None:
            outer = ttk.Frame(self.root, padding=16)
            outer.pack(fill=tk.BOTH, expand=True)
            outer.columnconfigure(1, weight=1)
            outer.rowconfigure(8, weight=1)

            ttk.Label(outer, text="Source folder").grid(row=0, column=0, sticky="w", pady=(0, 10))
            ttk.Entry(outer, textvariable=self.source_var).grid(
                row=0, column=1, sticky="ew", padx=(12, 8), pady=(0, 10)
            )
            ttk.Button(outer, text="Browse", command=self.choose_source_dir).grid(
                row=0, column=2, sticky="ew", pady=(0, 10)
            )

            ttk.Label(outer, text="Output folder").grid(row=1, column=0, sticky="w", pady=(0, 10))
            ttk.Entry(outer, textvariable=self.output_var).grid(
                row=1, column=1, sticky="ew", padx=(12, 8), pady=(0, 10)
            )
            ttk.Button(outer, text="Browse", command=self.choose_output_dir).grid(
                row=1, column=2, sticky="ew", pady=(0, 10)
            )

            ttk.Label(outer, text="Output name").grid(row=2, column=0, sticky="w", pady=(0, 10))
            ttk.Entry(outer, textvariable=self.name_var).grid(
                row=2, column=1, columnspan=2, sticky="ew", padx=(12, 0), pady=(0, 10)
            )

            ttk.Checkbutton(
                outer,
                text="Write troubleshooting marker report",
                variable=self.report_var,
            ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 14))

            ttk.Checkbutton(
                outer,
                text="Open output audio when complete",
                variable=self.launch_when_done_var,
            ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 10))

            ttk.Label(outer, text="Open with").grid(row=5, column=0, sticky="w", pady=(0, 10))
            ttk.Entry(outer, textvariable=self.launch_program_var).grid(
                row=5, column=1, sticky="ew", padx=(12, 8), pady=(0, 10)
            )
            ttk.Button(outer, text="Browse", command=self.choose_launch_program).grid(
                row=5, column=2, sticky="ew", pady=(0, 10)
            )

            ttk.Button(outer, text="Build WAV", command=self.run_encap).grid(
                row=6, column=0, columnspan=3, sticky="ew", pady=(0, 12)
            )

            ttk.Label(outer, text="Run log").grid(row=7, column=0, columnspan=3, sticky="w")
            self.log_output = tk.Text(outer, wrap="word", height=12, state="disabled")
            self.log_output.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
            outer.rowconfigure(8, weight=1)

        def append_log(self, message: str) -> None:
            self.log_output.configure(state="normal")
            self.log_output.insert(tk.END, message + "\n")
            self.log_output.see(tk.END)
            self.log_output.configure(state="disabled")

        def clear_log(self) -> None:
            self.log_output.configure(state="normal")
            self.log_output.delete("1.0", tk.END)
            self.log_output.configure(state="disabled")

        def choose_source_dir(self) -> None:
            folder = filedialog.askdirectory(title="Select source WAV folder")
            if folder:
                self.source_var.set(folder)
                self.populate_output_name_from_source(Path(folder))

        def choose_output_dir(self) -> None:
            folder = filedialog.askdirectory(title="Select output folder")
            if folder:
                self.output_var.set(folder)

        def choose_launch_program(self) -> None:
            program = filedialog.askopenfilename(title="Select application/executable")
            if program:
                self.launch_program_var.set(program)

        def populate_output_name_from_source(self, source_dir: Path) -> None:
            current_name = self.name_var.get().strip()
            if (
                current_name
                and current_name != "encap-output.wav"
                and AUTO_OUTPUT_NAME_PATTERN.match(current_name) is None
            ):
                return

            wav_paths = sorted(path for path in source_dir.iterdir() if path.is_file() and path.suffix.lower() == ".wav")
            if not wav_paths:
                return

            suggested_name = self.build_output_name_from_recording_name(wav_paths[0].stem)
            if suggested_name is not None:
                self.name_var.set(suggested_name)

        def build_output_name_from_recording_name(self, stem: str) -> str | None:
            parsed = parse_recorder_timestamp(stem)
            if parsed is None:
                return None
            return build_date_output_name((parsed[1], parsed[2], parsed[0]))

        def confirm_conversion(self, path: Path) -> bool:
            return messagebox.askyesno(
                "Convert mismatched WAV?",
                (
                    f"{path.name} does not match the first WAV file.\n\n"
                    "Convert it to the reference format with ffmpeg before stitching?"
                ),
                parent=self.root,
            )

        def run_encap(self) -> None:
            source_dir = Path(self.source_var.get().strip())
            output_dir = Path(self.output_var.get().strip())
            output_name = self.name_var.get().strip() or "encap-output.wav"

            if not source_dir.exists():
                messagebox.showwarning("Missing source folder", "Choose a valid source folder.", parent=self.root)
                return
            if not output_dir.exists():
                messagebox.showwarning("Missing output folder", "Choose a valid output folder.", parent=self.root)
                return

            self.clear_log()
            self.append_log(f"Source folder: {source_dir}")
            self.append_log(f"Output folder: {output_dir}")
            self.append_log(f"Requested output file: {output_name}")

            try:
                groups = discover_wav_groups(source_dir)
            except EncapError as exc:
                self.append_log("")
                self.append_log(f"Error: {exc}")
                messagebox.showerror("E.N.C.A.P. failed", str(exc), parent=self.root)
                return

            if len(groups) > 1:
                summary_lines: list[str] = []
                for recording_date, paths in groups:
                    if recording_date is None:
                        label = "Unrecognized date format"
                    else:
                        month, day, year = recording_date
                        label = f"{month}/{day}/{year}"
                    summary_lines.append(f"{label}: {len(paths)} file(s)")

                summary_text = "\n".join(summary_lines)
                decision = messagebox.askyesnocancel(
                    "Mixed aircheck dates found",
                    (
                        "WAV files from multiple recording dates were found.\n\n"
                        f"{summary_text}\n\n"
                        "Yes = make a single aircheck from the earliest detected date.\n"
                        "No = process multiple airchecks (batch output by date).\n"
                        "Cancel = stop and review the folder contents."
                    ),
                    parent=self.root,
                )
                if decision is None:
                    self.append_log("Cancelled: mixed-date source folder needs review.")
                    return
                if decision:
                    selected_date, selected_paths = groups[0]
                    if selected_date is not None:
                        month, day, year = selected_date
                        self.append_log(f"Single-aircheck mode: using {month}/{day}/{year}.")
                    else:
                        self.append_log("Single-aircheck mode: using files with unrecognized date format.")
                    try:
                        plan = create_stitched_wav_for_paths(
                            wav_paths=selected_paths,
                            output_dir=output_dir,
                            output_name=output_name,
                            prompt_for_conversion=self.confirm_conversion,
                            write_report=self.report_var.get(),
                        )
                    except EncapError as exc:
                        self.append_log("")
                        self.append_log(f"Error: {exc}")
                        messagebox.showerror("E.N.C.A.P. failed", str(exc), parent=self.root)
                        return

                    self.append_log("")
                    self.append_log(f"Wrote stitched WAV: {plan.output_path}")
                    self.append_log(f"Cue markers added: {len(plan.markers)}")
                    if plan.report_path is not None:
                        self.append_log(f"Marker report: {plan.report_path}")
                    if self.launch_when_done_var.get():
                        if self.launch_output(plan.output_path):
                            self.append_log("Opened output in external application.")
                        else:
                            self.append_log("Could not open output in external application.")
                    messagebox.showinfo("E.N.C.A.P. complete", f"Created {plan.output_path.name}", parent=self.root)
                    return

                try:
                    plans = create_stitched_wavs_by_date(
                        source_dir=source_dir,
                        output_dir=output_dir,
                        prompt_for_conversion=self.confirm_conversion,
                        write_report=self.report_var.get(),
                    )
                except EncapError as exc:
                    self.append_log("")
                    self.append_log(f"Error: {exc}")
                    messagebox.showerror("E.N.C.A.P. failed", str(exc), parent=self.root)
                    return

                self.append_log("")
                for plan in plans:
                    self.append_log(f"Wrote stitched WAV: {plan.output_path}")
                    self.append_log(f"Cue markers added: {len(plan.markers)}")
                    if plan.report_path is not None:
                        self.append_log(f"Marker report: {plan.report_path}")
                    self.append_log("")

                if self.launch_when_done_var.get() and plans:
                    if self.launch_output(plans[0].output_path):
                        if len(plans) == 1:
                            self.append_log("Opened output in external application.")
                        else:
                            self.append_log("Opened the first batch output in external application.")
                    else:
                        self.append_log("Could not open output in external application.")
                messagebox.showinfo("E.N.C.A.P. complete", f"Created {len(plans)} batch file(s).", parent=self.root)
                return

            try:
                plan = create_stitched_wav_for_paths(
                    wav_paths=groups[0][1],
                    output_dir=output_dir,
                    output_name=output_name,
                    prompt_for_conversion=self.confirm_conversion,
                    write_report=self.report_var.get(),
                )
            except EncapError as exc:
                self.append_log("")
                self.append_log(f"Error: {exc}")
                messagebox.showerror("E.N.C.A.P. failed", str(exc), parent=self.root)
                return

            self.append_log("")
            self.append_log(f"Wrote stitched WAV: {plan.output_path}")
            self.append_log(f"Cue markers added: {len(plan.markers)}")
            if plan.report_path is not None:
                self.append_log(f"Marker report: {plan.report_path}")
            if self.launch_when_done_var.get():
                if self.launch_output(plan.output_path):
                    self.append_log("Opened output in external application.")
                else:
                    self.append_log("Could not open output in external application.")
            messagebox.showinfo("E.N.C.A.P. complete", f"Created {plan.output_path.name}", parent=self.root)

        def launch_output(self, output_path: Path) -> bool:
            program = self.launch_program_var.get().strip()
            try:
                if program:
                    if sys.platform == "darwin" and program.lower().endswith(".app"):
                        subprocess.Popen(["open", "-a", program, str(output_path)])
                        return True
                    subprocess.Popen([program, str(output_path)])
                    return True

                if os.name == "nt":
                    os.startfile(str(output_path))
                    return True
                if sys.platform == "darwin":
                    subprocess.Popen(["open", str(output_path)])
                    return True
                subprocess.Popen(["xdg-open", str(output_path)])
                return True
            except Exception as exc:
                messagebox.showwarning(
                    "Could not open output",
                    f"Finished writing the WAV, but failed to open it:\n{exc}",
                    parent=self.root,
                )
                return False


def main() -> int:
    if missing_gui_dependency is not None:  # pragma: no cover
        print(
            "tkinter is required for the GUI, but this Python build does not include Tk support.",
            file=sys.stderr,
        )
        return 1

    root = tk.Tk()
    EncapApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

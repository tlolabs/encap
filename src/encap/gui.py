from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from encap.service import create_stitched_wav
    from encap.wav_tools import EncapError
else:
    from .service import create_stitched_wav
    from .wav_tools import EncapError

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ModuleNotFoundError as exc:  # pragma: no cover
    missing_gui_dependency = exc
else:
    missing_gui_dependency = None


if missing_gui_dependency is None:

    class EncapApp:
        def __init__(self, root: tk.Tk) -> None:
            self.root = root
            self.root.title("E.N.C.A.P.")
            self.root.geometry("760x500")
            self.root.minsize(680, 420)

            self.source_var = tk.StringVar()
            self.output_var = tk.StringVar()
            self.name_var = tk.StringVar(value="encap-output.wav")
            self.report_var = tk.BooleanVar(value=False)

            self._build_ui()

        def _build_ui(self) -> None:
            outer = ttk.Frame(self.root, padding=16)
            outer.pack(fill=tk.BOTH, expand=True)
            outer.columnconfigure(1, weight=1)
            outer.rowconfigure(4, weight=1)

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

            ttk.Button(outer, text="Build WAV", command=self.run_encap).grid(
                row=4, column=0, columnspan=3, sticky="ew", pady=(0, 12)
            )

            ttk.Label(outer, text="Run log").grid(row=5, column=0, columnspan=3, sticky="w")
            self.log_output = tk.Text(outer, wrap="word", height=12, state="disabled")
            self.log_output.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
            outer.rowconfigure(6, weight=1)

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

        def choose_output_dir(self) -> None:
            folder = filedialog.askdirectory(title="Select output folder")
            if folder:
                self.output_var.set(folder)

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
            self.append_log(f"Output file: {output_name}")

            try:
                plan = create_stitched_wav(
                    source_dir=source_dir,
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
            messagebox.showinfo("E.N.C.A.P. complete", f"Created {plan.output_path.name}", parent=self.root)


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

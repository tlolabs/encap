"""Out-of-process atomic-ish installer for Windows and Linux onedir builds."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _wait_for_exit(pid: int, timeout_seconds: float = 120.0) -> None:
    if sys.platform == "win32":
        import ctypes

        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        synchronize = 0x00100000
        wait_object_0 = 0x00000000
        wait_timeout = 0x00000102
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            # ERROR_INVALID_PARAMETER means the process no longer exists.
            if ctypes.get_last_error() == 87:
                return
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            result = kernel32.WaitForSingleObject(
                handle,
                int(timeout_seconds * 1000),
            )
        finally:
            kernel32.CloseHandle(handle)
        if result == wait_object_0:
            return
        if result == wait_timeout:
            raise RuntimeError("Timed out waiting for EnCap to exit.")
        raise RuntimeError("Windows could not wait for EnCap to exit.")

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.25)
    raise RuntimeError("Timed out waiting for EnCap to exit.")


def _remove_with_retries(path: Path) -> None:
    for attempt in range(20):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == 19:
                return
            time.sleep(0.5)


def apply_update(instruction_path: Path) -> int:
    instruction = json.loads(instruction_path.read_text(encoding="utf-8"))
    target = Path(instruction["target_dir"]).resolve()
    staged = Path(instruction["staged_dir"]).resolve()
    executable_name = str(instruction["executable_name"])
    pid = int(instruction["pid"])

    if target.name != "EnCap" or staged.parent != target.parent:
        raise RuntimeError("Refusing an update outside the expected EnCap directory.")
    expected_executable = "EnCap.exe" if sys.platform == "win32" else "EnCap"
    if executable_name != expected_executable:
        raise RuntimeError("The update instruction has an invalid executable name.")
    if not staged.name.startswith(".encap-update-"):
        raise RuntimeError("The staged update directory has an invalid name.")
    if not (target / executable_name).is_file() or not (staged / executable_name).is_file():
        raise RuntimeError("The installed or staged EnCap executable is missing.")

    _wait_for_exit(pid)
    backup = target.parent / f".encap-backup-{int(time.time())}"
    os.replace(target, backup)
    try:
        os.replace(staged, target)
    except Exception:
        os.replace(backup, target)
        raise

    executable = target / executable_name
    kwargs = {"cwd": str(target), "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen([str(executable)], **kwargs)
    except Exception:
        failed = target.parent / f".encap-failed-{int(time.time())}"
        os.replace(target, failed)
        os.replace(backup, target)
        _remove_with_retries(failed)
        raise
    _remove_with_retries(backup)
    instruction_path.unlink(missing_ok=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 2 or arguments[0] != "--apply-update":
        raise SystemExit("Usage: encap_updater --apply-update INSTRUCTION.json")
    return apply_update(Path(arguments[1]))


if __name__ == "__main__":
    raise SystemExit(main())

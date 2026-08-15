"""Minimal Objective-C bridge to Sparkle for the PySide macOS build."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from .update_service import UpdateConfigurationError, UpdateError


class SparkleUpdater:
    """Own Sparkle's standard updater controller for the application's lifetime."""

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise UpdateConfigurationError("Sparkle is only available on macOS.")
        framework = self._framework_binary()
        try:
            self._sparkle = ctypes.CDLL(str(framework))
            self._objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        except OSError as exc:
            raise UpdateConfigurationError(f"Could not load Sparkle: {exc}") from exc

        self._objc.objc_getClass.restype = ctypes.c_void_p
        self._objc.objc_getClass.argtypes = [ctypes.c_char_p]
        self._objc.sel_registerName.restype = ctypes.c_void_p
        self._objc.sel_registerName.argtypes = [ctypes.c_char_p]
        self._send = self._objc.objc_msgSend
        self._send.restype = ctypes.c_void_p

        controller_class = self._objc.objc_getClass(b"SPUStandardUpdaterController")
        if not controller_class:
            raise UpdateConfigurationError("Sparkle did not register its updater controller.")
        allocated = self._message(controller_class, b"alloc")
        self._send.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        controller = self._send(
            allocated,
            self._selector(b"initWithStartingUpdater:updaterDelegate:userDriverDelegate:"),
            True,
            None,
            None,
        )
        if not controller:
            raise UpdateError("Sparkle could not initialize its updater controller.")
        self._controller = controller

    @staticmethod
    def _framework_binary() -> Path:
        executable = Path(sys.executable).resolve()
        candidates = [
            executable.parent.parent / "Frameworks" / "Sparkle.framework" / "Sparkle",
            executable.parent.parent / "Frameworks" / "Sparkle.framework" / "Versions" / "B" / "Sparkle",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise UpdateConfigurationError("Sparkle.framework is missing from this app bundle.")

    def _selector(self, name: bytes) -> int:
        return self._objc.sel_registerName(name)

    def _message(self, receiver: int, selector: bytes) -> int:
        self._send.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        return self._send(receiver, self._selector(selector))

    def check_for_updates(self) -> None:
        self._send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        self._send(
            self._controller,
            self._selector(b"checkForUpdates:"),
            None,
        )

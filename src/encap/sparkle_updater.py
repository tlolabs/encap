"""Minimal Objective-C bridge to Sparkle for the PySide macOS build."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from .update_service import UpdateConfigurationError, UpdateError


_OBJC_ID = ctypes.c_void_p
_OBJC_SELECTOR = ctypes.c_void_p
_SEND_ID = ctypes.CFUNCTYPE(_OBJC_ID, _OBJC_ID, _OBJC_SELECTOR)
_SEND_VOID_ID = ctypes.CFUNCTYPE(None, _OBJC_ID, _OBJC_SELECTOR, _OBJC_ID)
_SEND_ID_BOOL_ID_ID = ctypes.CFUNCTYPE(
    _OBJC_ID,
    _OBJC_ID,
    _OBJC_SELECTOR,
    ctypes.c_bool,
    _OBJC_ID,
    _OBJC_ID,
)


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
        send_address = ctypes.cast(self._objc.objc_msgSend, ctypes.c_void_p).value
        if send_address is None:
            raise UpdateConfigurationError("Objective-C message dispatch is unavailable.")
        self._send_id = _SEND_ID(send_address)
        self._send_void_id = _SEND_VOID_ID(send_address)
        self._send_id_bool_id_id = _SEND_ID_BOOL_ID_ID(send_address)

        controller_class = self._objc.objc_getClass(b"SPUStandardUpdaterController")
        if not controller_class:
            raise UpdateConfigurationError("Sparkle did not register its updater controller.")
        allocated = self._message(controller_class, b"alloc")
        controller = self._send_id_bool_id_id(
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
        return self._send_id(receiver, self._selector(selector))

    def check_for_updates(self) -> None:
        self._send_void_id(
            self._controller,
            self._selector(b"checkForUpdates:"),
            None,
        )

"""Keep a Windows PC from going to sleep while Wizard answers a question.

An answer can take many minutes, much of it waiting on Gemini, and nobody touches the PC meanwhile, so Windows' idle
timer can put it to sleep in the middle of an answer. Nothing runs while it sleeps, and the answer fails on waking (the
likely end of the owner's run of 22 Oct 2026: its last step at 23 minutes, then nothing until it failed at 59). While a
question runs, Wizard asks Windows to keep the system awake, as a download or a backup does. The screen still turns
off, and closing the lid or choosing Sleep still puts the PC to sleep.

SetThreadExecutionState belongs to the thread that calls it: runs start and end on the event loop's thread, so both
calls come from there. Elsewhere than Windows this does nothing."""
from __future__ import annotations

import logging
import os
from collections.abc import Callable

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
log = logging.getLogger("wizard.awake")


def _windows() -> Callable[[int], int] | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        windll = getattr(ctypes, "windll")  # noqa: B009 - Windows-only attribute; getattr keeps type checks platform-neutral
        function = windll.kernel32.SetThreadExecutionState
        function.argtypes, function.restype = [ctypes.c_uint32], ctypes.c_uint32  # EXECUTION_STATE is a DWORD
    except (ImportError, AttributeError, OSError):
        return None
    return function


class KeepAwake:
    """Counts the questions running; the PC is kept awake while there is at least one."""

    def __init__(self, set_state: Callable[[int], int] | None = None):
        self.set_state = set_state if set_state is not None else _windows()
        self.running = 0

    def _set(self, flags: int) -> None:
        if self.set_state is None:
            return
        try:
            if not self.set_state(flags):
                log.warning("Windows did not accept the request to keep the PC awake (flags %#x)", flags)
        except Exception:  # noqa: BLE001 - staying awake is a courtesy; the question runs either way
            log.exception("could not ask Windows to keep the PC awake")

    def __enter__(self) -> KeepAwake:
        self.running += 1
        if self.running == 1:
            self._set(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        return self

    def __exit__(self, *_: object) -> None:
        self.running -= 1
        if self.running == 0:
            self._set(ES_CONTINUOUS)  # back to normal: Windows may sleep when idle

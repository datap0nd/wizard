"""Per-user secret storage for OAuth refresh tokens.

Windows: DPAPI (CryptProtectData) bound to the Wizard service account, so a copied file is useless elsewhere.
Other platforms (CI, development): plain files with owner-only permissions, reported as "plaintext-dev" in readiness so
nobody mistakes it for an approved secret store. The production secret store is an IT decision (Step 02)."""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    buffer = ctypes.create_string_buffer(data, len(data))
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = _Blob()
    entropy_bytes = b"wizard-oauth-v1"
    entropy_buffer = ctypes.create_string_buffer(entropy_bytes, len(entropy_bytes))
    entropy = _Blob(len(entropy_bytes), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_char)))
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    args = (ctypes.byref(source), None, ctypes.byref(entropy), None, None, 0x1, ctypes.byref(target))  # UI_FORBIDDEN
    if not function(*args):
        raise OSError("DPAPI operation failed")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(target.pbData)


class SecretBox:
    def __init__(self, force_plain: bool = False):
        self.kind = "dpapi" if sys.platform == "win32" and not force_plain else "plaintext-dev"

    def write(self, path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = value.encode("utf-8")
        blob = _dpapi(data, True) if self.kind == "dpapi" else data
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        if self.kind != "dpapi":
            os.chmod(tmp, 0o600)
        tmp.replace(path)

    def read(self, path: Path) -> str | None:
        if not path.is_file():
            return None
        blob = path.read_bytes()
        try:
            return (_dpapi(blob, False) if self.kind == "dpapi" else blob).decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    @staticmethod
    def delete(path: Path) -> None:
        path.unlink(missing_ok=True)

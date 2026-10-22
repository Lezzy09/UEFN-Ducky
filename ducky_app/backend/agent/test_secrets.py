"""Credential persist is Windows DPAPI; other OS stays in memory."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from backend.agent import secrets as secrets_mod


def test_non_windows_save_does_not_write_plaintext() -> None:
    secrets_mod.clear_memory_cache()
    orig_dpapi = secrets_mod._dpapi_available
    orig_path = secrets_mod.credentials_path
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "credentials.dat"
        secrets_mod._dpapi_available = lambda: False  # type: ignore[assignment]
        secrets_mod.credentials_path = lambda: dest  # type: ignore[assignment]
        try:
            secrets_mod.set_key("duckyos_account", '{"device_key":"dky_v1_test"}')
            assert not dest.exists()
            assert secrets_mod.get_key("duckyos_account") == '{"device_key":"dky_v1_test"}'
            secrets_mod.clear_key("duckyos_account")
        finally:
            secrets_mod._dpapi_available = orig_dpapi  # type: ignore[assignment]
            secrets_mod.credentials_path = orig_path  # type: ignore[assignment]
            secrets_mod.clear_memory_cache()


def _process_heap_allocated() -> int:
    """Bytes allocated in this process's default heap (where DPAPI's LocalAlloc results live)."""
    import ctypes
    from ctypes import wintypes

    class HeapSummary(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("cbAllocated", ctypes.c_size_t), ("cbCommitted", ctypes.c_size_t),
                    ("cbReserved", ctypes.c_size_t), ("cbMaxReserve", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32")
    k32.GetProcessHeap.restype = wintypes.HANDLE
    k32.HeapSummary.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(HeapSummary)]
    s = HeapSummary()
    s.cb = ctypes.sizeof(s)
    assert k32.HeapSummary(k32.GetProcessHeap(), 0, ctypes.byref(s))
    return int(s.cbAllocated)


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI")
def test_sealing_and_opening_big_rows_frees_dpapis_buffers() -> None:
    """Every sealed chat save and read goes through DPAPI. Its output buffer must be freed,
    or each call leaks the whole row: 40 x 1 MB here would leave ~80 MB behind."""
    row = bytes(range(256)) * 4096  # 1 MB
    entropy = b"account-data-key"
    assert secrets_mod.unprotect_bytes(secrets_mod.protect_bytes(row, entropy), entropy) == row
    before = _process_heap_allocated()
    for _ in range(40):
        assert secrets_mod.unprotect_bytes(secrets_mod.protect_bytes(row, entropy), entropy) == row
    grew = _process_heap_allocated() - before
    assert grew < 16 * 1024 * 1024, f"process heap grew {grew / 2**20:.0f} MB"


if __name__ == "__main__":
    test_non_windows_save_does_not_write_plaintext()
    print("ok")

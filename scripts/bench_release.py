"""Windows release baseline, isolated from the real ledger. No third-party modules.

python scripts/bench_release.py EXE --output docs/perf-python-empty.json [--ledger LEDGER]
Window discovery is a first-window proxy, not proof that pixels have reached the display.
"""
import argparse
import ctypes as c
from contextlib import closing
from ctypes import wintypes as w
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time

k32 = c.WinDLL("kernel32", use_last_error=True)
u32 = c.WinDLL("user32", use_last_error=True)
psapi = c.WinDLL("psapi", use_last_error=True)
SIZE = c.c_size_t


class ProcessEntry(c.Structure):
    _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD),
                ("heap", SIZE), ("module", w.DWORD), ("threads", w.DWORD),
                ("parent", w.DWORD), ("priority", w.LONG), ("flags", w.DWORD),
                ("exe", w.WCHAR * 260)]


class Memory(c.Structure):
    _fields_ = [("size", w.DWORD), ("faults", w.DWORD)] + [
        (key, SIZE) for key in ("peak_ws", "ws", "peak_paged", "paged", "peak_nonpaged",
                               "nonpaged", "pagefile", "peak_pagefile", "private")]


k32.CreateToolhelp32Snapshot.restype = w.HANDLE
k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [w.HANDLE, c.POINTER(ProcessEntry)]
k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k32.OpenProcess.restype = w.HANDLE
k32.CloseHandle.argtypes = [w.HANDLE]
k32.GetProcessTimes.argtypes = [w.HANDLE] + [c.POINTER(w.FILETIME)] * 4
psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, c.POINTER(Memory), w.DWORD]
u32.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
u32.IsWindowVisible.argtypes = [w.HWND]
u32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
u32.GetWindowRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
u32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
CALLBACK = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
u32.EnumWindows.argtypes = [CALLBACK, w.LPARAM]


def tree(root):
    handle = k32.CreateToolhelp32Snapshot(2, 0)
    if handle == c.c_void_p(-1).value:
        raise c.WinError(c.get_last_error())
    parents = {}
    try:
        entry = ProcessEntry()
        entry.size = c.sizeof(entry)
        ok = k32.Process32FirstW(handle, c.byref(entry))
        while ok:
            parents[entry.pid] = entry.parent
            ok = k32.Process32NextW(handle, c.byref(entry))
    finally:
        k32.CloseHandle(handle)
    ids = {root}
    while True:
        added = {pid for pid, parent in parents.items() if parent in ids} - ids
        if not added:
            return ids
        ids |= added


def sample(ids):
    result = {"working_set_bytes": 0, "private_bytes": 0, "cpu_seconds": 0.0}
    for pid in ids:
        handle = k32.OpenProcess(0x410, False, pid)
        if not handle:
            continue
        try:
            mem = Memory()
            mem.size = c.sizeof(mem)
            if psapi.GetProcessMemoryInfo(handle, c.byref(mem), mem.size):
                result["working_set_bytes"] += mem.ws
                result["private_bytes"] += mem.private
            times = [w.FILETIME() for _ in range(4)]
            if k32.GetProcessTimes(handle, *(c.byref(t) for t in times)):
                result["cpu_seconds"] += sum((t.dwHighDateTime << 32) | t.dwLowDateTime
                                             for t in times[2:]) / 10_000_000
        finally:
            k32.CloseHandle(handle)
    return result


def windows(ids):
    found = []

    @CALLBACK
    def visit(hwnd, _):
        pid = w.DWORD()
        u32.GetWindowThreadProcessId(hwnd, c.byref(pid))
        if pid.value in ids and u32.IsWindowVisible(hwnd):
            title, rect = c.create_unicode_buffer(512), w.RECT()
            u32.GetWindowTextW(hwnd, title, len(title))
            if u32.GetWindowRect(hwnd, c.byref(rect)) and title.value.startswith("LootLedger") and rect.right - rect.left >= 300 and rect.bottom - rect.top >= 200:
                found.append(hwnd)
        return True

    u32.EnumWindows(visit, 0)
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--settle", type=float, default=60)
    parser.add_argument("--idle", type=float, default=30)
    args = parser.parse_args()
    exe = args.exe.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="lootledger-bench-") as temp:
        data = Path(temp) / "LootLedger"
        data.mkdir()
        replay_folder = Path(temp) / "Demos"
        replay_folder.mkdir()
        rows = {}
        if args.ledger:
            with closing(sqlite3.connect(args.ledger.resolve().as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(data / "ledger.sqlite")) as dest:
                    source.backup(dest)
                    rows = {t: dest.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                            for t in ("events", "matches", "match_meta")}
        (data / "config.json").write_text(json.dumps({
            "replay_folder": str(replay_folder), "auto_watch": False,
            "hotkey_add": "", "hotkey_undo": ""}), encoding="utf-8")
        (data / "ui-settings.json").write_text(json.dumps({
            "seen_version": "0.7.1", "live_tracking": False, "overlay": False,
            "hotkey_overlay": "", "motion": "full"}), encoding="utf-8")
        env = {**os.environ, "LOCALAPPDATA": temp}
        start = time.perf_counter()
        proc = subprocess.Popen([str(exe)], env=env)
        ids = {proc.pid}
        try:
            hwnds = []
            while not hwnds and time.perf_counter() - start < 60:
                if proc.poll() is not None:
                    raise RuntimeError(f"App exited before opening a window ({proc.returncode})")
                ids = tree(proc.pid)
                hwnds = windows(ids)
                time.sleep(0.01)
            if not hwnds:
                raise TimeoutError("No visible window after 60 seconds")
            first_window_ms = (time.perf_counter() - start) * 1000
            print(f"Visible window after {first_window_ms:.0f}ms; settling {args.settle}s", flush=True)
            time.sleep(args.settle)
            ids = tree(proc.pid)
            before = sample(ids)
            idle_start = time.perf_counter()
            time.sleep(args.idle)
            after = sample(tree(proc.pid))
            elapsed = time.perf_counter() - idle_start
            result = {"measured_utc": datetime.now(timezone.utc).isoformat(),
                      "exe_bytes": exe.stat().st_size, "first_visible_window_ms": round(first_window_ms, 1),
                      "first_paint_ms": None, "launch_cache": "uncontrolled (not a cold-cache claim)",
                      "settle_seconds": args.settle, "idle_sample_seconds": round(elapsed, 3),
                      "processes": len(ids), "ledger_rows": rows, **before,
                      "idle_cpu_percent_one_core": round(100 * (after["cpu_seconds"] - before["cpu_seconds"]) / elapsed, 3)}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, indent=2), flush=True)
        finally:
            for hwnd in windows(tree(proc.pid)):
                u32.PostMessageW(hwnd, 0x10, 0, 0)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                proc.wait(timeout=10)


if __name__ == "__main__":
    main()

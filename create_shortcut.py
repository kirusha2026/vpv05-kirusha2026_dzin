"""Создаёт ярлык приложения на рабочем столе Windows."""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ICON_PATH = APP_DIR / "icon.ico"
MAIN_PY = APP_DIR / "main.py"


def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", _crc32(tag + data))


def write_clock_icon(path: Path, size: int = 64) -> None:
    """Простая иконка-часы в формате ICO (PNG внутри)."""
    rows = []
    cx = cy = (size - 1) / 2
    r_outer = size * 0.42
    r_inner = size * 0.34
    for y in range(size):
        row = bytearray()
        for x in range(size):
            dx = x - cx
            dy = y - cy
            dist = (dx * dx + dy * dy) ** 0.5
            # фон прозрачный
            r, g, b, a = 0, 0, 0, 0
            if dist <= r_outer + 1:
                if dist >= r_inner:
                    r, g, b, a = 37, 99, 235, 255  # обод
                elif dist <= r_inner:
                    r, g, b, a = 239, 246, 255, 255  # циферблат
                # стрелки
                hour = abs(dx * 0.15 + dy * 0.99) < 1.6 and 0 <= -dy <= r_inner * 0.45
                minute = abs(dx * 0.95 - dy * 0.32) < 1.4 and 0 <= dx <= r_inner * 0.62
                if hour or minute:
                    r, g, b, a = 30, 64, 175, 255
                if dist < 3:
                    r, g, b, a = 30, 64, 175, 255
            row.extend((r, g, b, a))
        rows.append(bytes(row))

    raw = b"".join(b"\x00" + row for row in rows)
    compressed = zlib.compress(raw, 9)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", compressed) + _png_chunk(b"IEND", b"")

    # ICO: header + one PNG image
    header = struct.pack("<HHH", 0, 1, 1)
    directory = struct.pack(
        "<BBBBHHII",
        size if size < 256 else 0,
        size if size < 256 else 0,
        0,
        0,
        1,
        32,
        len(png),
        6 + 16,
    )
    path.write_bytes(header + directory + png)


def desktop_path() -> Path:
    import ctypes
    from ctypes import wintypes

    buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    # CSIDL_DESKTOPDIRECTORY = 0x10 — реальная папка рабочего стола
    result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)
    if result != 0:
        raise OSError("Не удалось найти папку рабочего стола")
    return Path(buf.value)


def pythonw_path() -> Path:
    candidate = Path(sys.executable)
    if candidate.name.lower() == "python.exe":
        pythonw = candidate.with_name("pythonw.exe")
        if pythonw.exists():
            return pythonw
    return candidate


def create_shortcut(name: str, arguments: str = "") -> Path:
    write_clock_icon(ICON_PATH)
    desktop = desktop_path()
    shortcut_path = desktop / f"{name}.lnk"
    target = str(pythonw_path())
    workdir = str(APP_DIR)
    icon = str(ICON_PATH)
    args = f'"{MAIN_PY}" {arguments}'.strip()

    # PowerShell COM: стандартный способ создать .lnk на Windows
    ps = f"""
$s = New-Object -ComObject WScript.Shell
$sc = $s.CreateShortcut('{shortcut_path}')
$sc.TargetPath = '{target}'
$sc.Arguments = '{args}'
$sc.WorkingDirectory = '{workdir}'
$sc.WindowStyle = 1
$sc.Description = 'Напоминания'
$sc.IconLocation = '{icon}'
$sc.Save()
"""
    import subprocess

    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or "Не удалось создать ярлык")
    return shortcut_path


if __name__ == "__main__":
    path = create_shortcut("Напоминания", arguments="--add")
    print(f"Ярлык создан: {path}")

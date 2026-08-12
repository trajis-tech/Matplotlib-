# -*- coding: utf-8 -*-
"""Thin entry for PyInstaller. Does not modify the app; runs server from adjacent tree.

Frozen layout (exe beside project root contents)::

    PortablePlotTool/
      離線繪圖工具.exe
      _internal/          (PyInstaller runtime, if onedir)
      app/
      portable_python/    (preferred interpreter + site-packages)
      stats_kb/
      ...

When portable_python\\python.exe exists, re-exec with it (same as 點此開始.bat).
Otherwise run app\\backend\\server.py in-process (frozen site-packages).
"""
from __future__ import annotations

import os
import runpy
import subprocess
import sys
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def main() -> int:
    root = project_root()
    os.chdir(root)

    server = root / "app" / "backend" / "server.py"
    if not server.is_file():
        print(f"ERROR: server not found: {server}")
        print("Place this exe in the packaged project root (next to the app\\ folder).")
        return 1

    portable_py = root / "portable_python" / "python.exe"
    if portable_py.is_file():
        # Prefer the bundled portable runtime (complete offline product).
        return int(subprocess.call([str(portable_py), str(server)], cwd=str(root)))

    # Fallback: in-process (PyInstaller-collected packages).
    runpy.run_path(str(server), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

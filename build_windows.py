#!/usr/bin/env python3
"""
PyInstaller Build Script for LoL Remote Pick (Windows Standalone Executable).

Creates a standalone executable distribution in dist/LoL-Remote-Pick/
containing all dependencies, FastAPI backend, and frontend static assets.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT_DIR / "frontend"
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"


def check_pyinstaller() -> None:
    """Ensure PyInstaller is installed in the current Python environment."""
    try:
        import PyInstaller
    except ImportError:
        print("[INFO] Installing PyInstaller...")
        try:
            subprocess.check_call(["uv", "pip", "install", "pyinstaller"])
        except Exception:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

def build_executable() -> None:
    """Build the standalone executable with PyInstaller."""
    import PyInstaller.__main__

    print("================================================================================")
    print("  Building LoL Remote Pick Standalone Executable for Windows...")
    print("================================================================================")

    # Clean prior builds
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR, ignore_errors=True)
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR, ignore_errors=True)

    # PyInstaller arguments
    # On Windows, add-data separator is ';'
    sep = ";" if sys.platform == "win32" else ":"
    frontend_data = f"{FRONTEND_DIR}{sep}frontend"

    args = [
        str(ROOT_DIR / "run.py"),
        "--name=LoL-Remote-Pick",
        "--onedir",
        f"--add-data={frontend_data}",
        "--hidden-import=uvicorn.logging",
        "--hidden-import=uvicorn.loops",
        "--hidden-import=uvicorn.loops.auto",
        "--hidden-import=uvicorn.protocols",
        "--hidden-import=uvicorn.protocols.http",
        "--hidden-import=uvicorn.protocols.http.auto",
        "--hidden-import=uvicorn.protocols.websockets",
        "--hidden-import=uvicorn.protocols.websockets.auto",
        "--hidden-import=uvicorn.lifespans",
        "--hidden-import=uvicorn.lifespans.on",
        "--hidden-import=qrcode",
        "--hidden-import=qrcode.image.svg",
        "--hidden-import=psutil",
        "--hidden-import=websockets",
        "--hidden-import=httpx",
        "--hidden-import=pydantic",
        "--hidden-import=pydantic_settings",
        "--noconfirm",
    ]

    print(f"[INFO] Running PyInstaller with args: {' '.join(args)}")
    PyInstaller.__main__.run(args)

    out_folder = DIST_DIR / "LoL-Remote-Pick"

    # Create Quick-Start guide inside distribution folder
    quick_start = out_folder / "Quick-Start.txt"
    quick_start.write_text(
        "LoL Remote Pick - Portable Windows Edition\n"
        "==========================================\n\n"
        "HOW TO USE:\n"
        "1. Double-click 'LoL-Remote-Pick.exe'.\n"
        "2. Scan the QR code shown on screen with your phone camera (must be on the same Wi-Fi).\n"
        "3. Accept matches, pick/ban champions, and swap spells from your phone!\n\n"
        "Note: You do NOT need Python or Git installed to use this application.\n",
        encoding="utf-8",
    )

    # Create zip archive for easy release sharing
    zip_output = DIST_DIR / "LoL-Remote-Pick-windows-x64"
    print("[INFO] Creating ZIP archive for release distribution...")
    shutil.make_archive(str(zip_output), "zip", root_dir=str(DIST_DIR), base_dir="LoL-Remote-Pick")

    print("\n================================================================================")
    print("  BUILD COMPLETE!")
    print(f"  Folder: {out_folder}")
    print(f"  Release ZIP: {zip_output}.zip")
    print("================================================================================\n")
if __name__ == "__main__":
    check_pyinstaller()
    build_executable()

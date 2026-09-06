#!/usr/bin/env python
"""Format a single file after Claude Code writes it (PostToolUse hook).

Reads the hook payload on stdin, formats the edited file with Ruff (Python) or
Prettier (frontend JS/CSS), and always exits 0 so a missing tool never blocks an edit.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])


def find_ruff() -> str | None:
    for candidate in (ROOT / ".venv/Scripts/ruff.exe", ROOT / ".venv/bin/ruff"):
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ruff")


def find_prettier() -> str | None:
    for candidate in (ROOT / "node_modules/.bin/prettier.cmd", ROOT / "node_modules/.bin/prettier"):
        if candidate.is_file():
            return str(candidate)
    return None  # never fall back to npx: downloading mid-edit is too slow


def run(*cmd: str) -> None:
    subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    raw = payload.get("tool_input", {}).get("file_path") or payload.get("tool_response", {}).get("filePath")
    if not raw:
        return 0

    path = Path(raw)
    if not path.is_file():
        return 0

    if path.suffix == ".py":
        ruff = find_ruff()
        if ruff:
            run(ruff, "format", str(path))
            run(ruff, "check", "--fix", str(path))
    elif path.suffix in (".js", ".css"):
        prettier = find_prettier()
        if prettier:
            run(prettier, "--write", str(path))

    return 0


if __name__ == "__main__":
    sys.exit(main())

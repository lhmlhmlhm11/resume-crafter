"""Shared environment bootstrap for the resume-crafter skill.

Resolves the Python interpreter to use and makes sure the third-party packages
the skill needs are available.

Resolution order:
1. An already-running interpreter that already has the dependencies (fast path).
2. The WorkBuddy-managed virtualenv, when the skill runs inside WorkBuddy.
3. The current interpreter (system Python / venv) — this is the path taken by
   GitHub users who clone the repository and run the scripts directly.

The third-party dependencies are intentionally tiny:
    - python-docx  : DOCX output
    - pypdf        : PDF text-layer inspection (ATS check)
Pillow is only needed by ``make_sample_photo.py`` and is therefore optional.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REQUIRED_PACKAGES = ["pypdf", "python-docx"]
OPTIONAL_PACKAGES = ["pillow"]

WORKBUDDY_ROOT = Path.home() / ".workbuddy"
VENV_DIR = WORKBUDDY_ROOT / "binaries" / "python" / "envs" / "default"
RUNTIME_DIR = WORKBUDDY_ROOT / "binaries" / "python" / "versions"


def os_name_is_windows() -> bool:
    import os

    return os.name == "nt"


def venv_python() -> Path:
    """Return the interpreter inside the managed virtualenv."""
    if os_name_is_windows():
        candidate = VENV_DIR / "Scripts" / "python.exe"
    else:
        candidate = VENV_DIR / "bin" / "python"
    if candidate.exists():
        return candidate
    raise RuntimeError(
        "Managed virtualenv missing. Run: python -m venv "
        f'"{VENV_DIR}" then install {", ".join(REQUIRED_PACKAGES)}'
    )


def base_python() -> Path:
    """Best-effort location of a managed base interpreter (used to create the venv)."""
    if VENV_DIR.exists():
        pass
    versions = sorted(RUNTIME_DIR.glob("*/python.exe"), reverse=True)
    if versions:
        return versions[0]
    versions = sorted(RUNTIME_DIR.glob("*/bin/python3"), reverse=True)
    if versions:
        return versions[0]
    return Path(sys.executable)


def _missing_packages(python: Path, packages: list[str]) -> list[str]:
    if not packages:
        return []
    mods = ",".join(
        f"'{p}':'{p.replace('-', '_')}'" for p in packages
    )
    probe = (
        "import importlib.util as u;"
        f"mods={{{mods}}};"
        "print(','.join([m for m,p in mods.items() if u.find_spec(p) is None]))"
    )
    try:
        out = subprocess.run(
            [str(python), "-c", probe], capture_output=True, text=True, timeout=120
        )
    except Exception:
        return list(packages)
    missing = [m.strip() for m in (out.stdout or "").strip().split(",") if m.strip()]
    return missing


def ensure_deps(python: Path | None = None) -> Path:
    """Install any missing packages and return the interpreter to use.

    When running inside WorkBuddy, the managed virtualenv is preferred so that
    the user's own environment stays untouched. Outside WorkBuddy (e.g. a plain
    GitHub clone), the current interpreter is used as-is.
    """
    if python is None:
        python = _pick_interpreter()
    missing = _missing_packages(python, REQUIRED_PACKAGES)
    if missing:
        print(f"[resume-crafter] installing: {', '.join(missing)}", file=sys.stderr)
        subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet", *missing],
            check=False,
        )
    return python


def _pick_interpreter() -> Path:
    """Choose the interpreter to run the skill with."""
    # 1. Current interpreter already satisfies the requirements → use it.
    if not _missing_packages(Path(sys.executable), REQUIRED_PACKAGES):
        return Path(sys.executable)
    # 2. WorkBuddy managed virtualenv (only exists inside WorkBuddy).
    try:
        managed = venv_python()
        if not _missing_packages(managed, REQUIRED_PACKAGES):
            return managed
    except RuntimeError:
        pass
    # 3. Managed base interpreter, or fall back to the current one.
    try:
        return base_python()
    except Exception:
        return Path(sys.executable)


def run_script(script: Path, *args: str) -> int:
    """Run another script of this skill with the resolved interpreter."""
    python = ensure_deps()
    cmd = [str(python), str(script), *[str(a) for a in args]]
    return subprocess.run(cmd, check=False).returncode

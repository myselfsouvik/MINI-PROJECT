"""
First-run setup, called by start.bat / start.sh before the server starts:

    python backend/setup_env.py

1. Makes the .venv folder (a private Python environment for this project) if it is missing.
2. Installs requirements.txt into it, the first time and again whenever requirements.txt changes.
   On Linux without an NVIDIA GPU it first installs the small CPU-only PyTorch, which saves about 2 GB.

Uses only the standard library, so it runs on a fresh Python with nothing installed.
Exit code 0 when .venv is ready, 1 when something failed (the message says what to do).
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
STAMP_NAME = "dogwatch-requirements.sha256"     # inside .venv: which requirements.txt was installed
SUPPORTED = ((3, 10), (3, 12))                  # what we test with; newer may work too
CPU_TORCH = "https://download.pytorch.org/whl/cpu"


def venv_python(venv_dir: Path = VENV) -> Path:
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def requirements_hash(path: Path = REQUIREMENTS) -> str:
    """Same on every computer: line endings don't count."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def needs_install(venv_dir: Path = VENV, req: Path = REQUIREMENTS) -> bool:
    stamp = venv_dir / STAMP_NAME
    return not stamp.is_file() or stamp.read_text().strip() != requirements_hash(req)


def wants_cpu_torch(system: str = platform.system(), which=shutil.which) -> bool:
    """PyPI's default PyTorch on Linux bundles CUDA (~2.5 GB). Windows and macOS get a small one anyway."""
    return system == "Linux" and not which("nvidia-smi")


# PyTorch's longest file is about 145 characters below the project folder (.venv\Lib\site-packages\torch\
# include\...). Windows refuses paths over 260 characters unless "long paths" is switched on, so the
# project folder's own path must stay under about 100 characters. The margin covers pip's temp files.
LONGEST_INSIDE_VENV = 160
WINDOWS_PATH_LIMIT = 260


def long_paths_enabled() -> bool:
    if os.name != "nt":
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return bool(winreg.QueryValueEx(key, "LongPathsEnabled")[0])
    except OSError:
        return False


def path_too_long(root: Path = ROOT, enabled=long_paths_enabled) -> bool:
    return len(str(root)) + LONGEST_INSIDE_VENV > WINDOWS_PATH_LIMIT and not enabled()


def run(cmd: list) -> bool:
    print("  > " + " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd).returncode == 0


def main() -> int:
    version = sys.version_info[:2]
    if version < SUPPORTED[0]:
        print(f"This is Python {version[0]}.{version[1]}; DogWatch needs Python 3.10 or newer (3.11 recommended).\n"
              "Install it from https://www.python.org/downloads/ and run the start script again.")
        return 1

    if path_too_long():
        print(f"This folder's path is too long for Windows ({len(str(ROOT))} characters):\n  {ROOT}\n"
              "Some of PyTorch's files would go past Windows' 260-character limit. Move the project folder\n"
              r"somewhere shorter, for example C:\DogWatch, and start again." + "\n"
              "(Or switch on Windows long paths: https://pip.pypa.io/warnings/enable-long-paths)")
        return 1

    py = venv_python()
    if not py.exists():
        if version > SUPPORTED[1]:
            print(f"Note: Python {version[0]}.{version[1]} is newer than the versions we test with (3.10 to 3.12). "
                  "If the install below fails, install Python 3.11 and delete the .venv folder.")
        print(f"Making a private Python environment in {VENV.name}/ ...", flush=True)
        try:
            venv.EnvBuilder(with_pip=True).create(VENV)
        except Exception as e:                       # e.g. Debian/Ubuntu without python3-venv
            print(f"Could not make {VENV.name}/: {e}\n"
                  "On Ubuntu/Debian run: sudo apt install python3-venv   then start again.")
            return 1

    if not needs_install():
        return 0

    print("\nInstalling what DogWatch needs (first time only: about 1 GB, 5 to 15 minutes, needs internet)...\n",
          flush=True)
    steps = []
    if wants_cpu_torch():
        steps.append([py, "-m", "pip", "install", "torch", "torchvision", "--index-url", CPU_TORCH])
    steps.append([py, "-m", "pip", "install", "--disable-pip-version-check", "-r", REQUIREMENTS])
    for cmd in steps:
        if not run(cmd):
            print("\nThe install did not finish (the error is just above). Usually the internet connection\n"
                  "dropped: run the start script again and it carries on where it stopped. If it keeps failing,\n"
                  "delete the .venv folder, install Python 3.11 from python.org and start again.")
            return 1
    (VENV / STAMP_NAME).write_text(requirements_hash() + "\n")
    print("\nEverything is installed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

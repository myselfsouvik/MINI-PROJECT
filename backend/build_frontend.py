"""
Build the React dashboard (frontend/) when it is missing or older than its source code.

    python -m backend.build_frontend           # build only if needed (start.bat / start.sh do this)
    python -m backend.build_frontend --force   # always rebuild

The server serves frontend/dist at http://127.0.0.1:8000/. Without a build (or without
Node.js) the classic console is shown there instead, so this never stops the server
from starting: every problem is printed and the exit code is still 0.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SOURCES = ("src", "public", "index.html", "package.json", "package-lock.json", "vite.config.js")


def newest_source(frontend: Path = FRONTEND) -> float:
    """Modification time of the newest file the build depends on (0 if there are none)."""
    newest = 0.0
    for name in SOURCES:
        p = frontend / name
        files = [f for f in p.rglob("*") if f.is_file()] if p.is_dir() else [p] if p.is_file() else []
        newest = max([newest, *(f.stat().st_mtime for f in files)])
    return newest


def needs_build(frontend: Path = FRONTEND) -> str | None:
    """Why the dashboard should be (re)built, or None if the build is up to date."""
    if not (frontend / "package.json").is_file():
        return None                                  # no dashboard in this checkout
    built = frontend / "dist" / "index.html"
    if not built.is_file():
        return "the dashboard hasn't been built yet"
    if newest_source(frontend) > built.stat().st_mtime:
        return "the dashboard code changed since the last build"
    return None


def build(frontend: Path = FRONTEND, run=subprocess.run, which=shutil.which) -> bool:
    npm = which("npm")
    if not npm:
        print("Node.js is not installed, so http://127.0.0.1:8000 shows the classic console.\n"
              "Install Node.js LTS from https://nodejs.org to get the dashboard.")
        return False
    steps = [[npm, "run", "build"]]
    if not (frontend / "node_modules").is_dir():
        steps.insert(0, [npm, "ci", "--no-fund", "--no-audit"])
        print("Installing the dashboard's packages (first time only, needs internet)...")
    for cmd in steps:
        if run(cmd, cwd=frontend).returncode != 0:
            print(f"'{' '.join(cmd[1:])}' failed. The classic console is shown instead. "
                  f"To see the error, run it yourself in {frontend}.")
            return False
    return True


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--force", action="store_true", help="rebuild even if the build looks up to date")
    args = p.parse_args(argv)
    reason = "--force" if args.force and (FRONTEND / "package.json").is_file() else needs_build()
    if reason:
        print(f"Building the dashboard ({reason})...")
        if build():
            print("Dashboard built.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

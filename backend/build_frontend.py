"""
Build the React dashboard (frontend/) when its code changed since the build in frontend/dist.

    python -m backend.build_frontend           # build only if needed (start.bat / start.sh do this)
    python -m backend.build_frontend --force   # always rebuild

frontend/dist is kept in git, so a fresh clone works without Node.js. Each build writes a
fingerprint of the code it was built from (frontend/dist/source.sha256, also written by
`npm run build` through frontend/scripts/stamp.mjs); when the code no longer
matches it, the dashboard is rebuilt here if Node.js is installed. Without any build, the classic
console is shown at http://127.0.0.1:8000. This never stops the server from starting: every
problem is printed and the exit code is still 0.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SOURCES = ("src", "public", "index.html", "package.json", "package-lock.json", "vite.config.js")
STAMP = "source.sha256"


def source_hash(frontend: Path = FRONTEND) -> str:
    """Fingerprint of everything the build depends on. Line endings don't count, so it is the
    same on Windows and macOS/Linux checkouts."""
    h = hashlib.sha256()
    for name in SOURCES:
        p = frontend / name
        files = [f for f in p.rglob("*") if f.is_file()] if p.is_dir() else [p] if p.is_file() else []
        files.sort(key=lambda f: f.relative_to(frontend).as_posix())   # same order on every system
        for f in files:
            h.update(f.relative_to(frontend).as_posix().encode() + b"\0")
            h.update(f.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def write_stamp(frontend: Path = FRONTEND) -> None:
    if (frontend / "dist").is_dir():
        (frontend / "dist" / STAMP).write_text(source_hash(frontend) + "\n")


def needs_build(frontend: Path = FRONTEND) -> str | None:
    """Why the dashboard should be (re)built, or None if the build matches the code."""
    if not (frontend / "package.json").is_file():
        return None                                  # no dashboard in this checkout
    dist = frontend / "dist"
    if not (dist / "index.html").is_file():
        return "the dashboard hasn't been built yet"
    stamp = dist / STAMP
    if not stamp.is_file() or stamp.read_text().strip() != source_hash(frontend):
        return "the dashboard code changed since the last build"
    return None


def build(frontend: Path = FRONTEND, run=subprocess.run, which=shutil.which) -> bool:
    npm = which("npm")
    if not npm:
        if (frontend / "dist" / "index.html").is_file():
            print("Node.js is not installed, so the dashboard that came with the code is used\n"
                  "(without the newest changes in frontend/). Install Node.js LTS from\n"
                  "https://nodejs.org to rebuild it.")
        else:
            print("Node.js is not installed, so http://127.0.0.1:8000 shows the classic console.\n"
                  "Install Node.js LTS from https://nodejs.org to get the dashboard.")
        return False
    steps = [[npm, "run", "build"]]
    if not (frontend / "node_modules").is_dir():
        steps.insert(0, [npm, "ci", "--no-fund", "--no-audit"])
        print("Installing the dashboard's packages (first time only, needs internet)...")
    for cmd in steps:
        if run(cmd, cwd=frontend).returncode != 0:
            print(f"'{' '.join(cmd[1:])}' failed, so the previous dashboard (or the classic console) "
                  f"is shown. To see the error, run it yourself in {frontend}.")
            return False
    write_stamp(frontend)
    return True


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--force", action="store_true", help="rebuild even if the build looks up to date")
    p.add_argument("--check", action="store_true",
                   help="only say whether frontend/dist matches the code (exit code 1 if not)")
    args = p.parse_args(argv)
    reason = needs_build()
    if args.check:
        print(f"Out of date: {reason}." if reason else "frontend/dist matches the code.")
        return 1 if reason else 0
    if args.force and (FRONTEND / "package.json").is_file():
        reason = "--force"
    if reason:
        print(f"Building the dashboard ({reason})...")
        if build():
            print("Dashboard built.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Tests for building the dashboard from start.bat / start.sh: when a build is needed and what
happens without Node.js or when npm fails (the server must still start).
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace

from backend.build_frontend import build, needs_build


def make_frontend(tmp_path, built=False, modules=False):
    fe = tmp_path / "frontend"
    (fe / "src").mkdir(parents=True)
    (fe / "package.json").write_text("{}")
    (fe / "src" / "main.jsx").write_text("x")
    if built:
        (fe / "dist").mkdir()
        (fe / "dist" / "index.html").write_text("<html>")
    if modules:
        (fe / "node_modules").mkdir()
    return fe


def test_needs_build(tmp_path):
    assert needs_build(tmp_path / "nothing") is None                      # no dashboard in this checkout
    fe = make_frontend(tmp_path)
    assert "hasn't been built" in needs_build(fe)
    (fe / "dist").mkdir()
    (fe / "dist" / "index.html").write_text("<html>")
    assert needs_build(fe) is None
    later = time.time() + 60                                             # someone pulled new code
    os.utime(fe / "src" / "main.jsx", (later, later))
    assert "changed" in needs_build(fe)


def test_build_installs_packages_once(tmp_path):
    calls = []
    run = lambda cmd, cwd: calls.append(cmd[1:]) or SimpleNamespace(returncode=0)       # noqa: E731
    fe = make_frontend(tmp_path)
    assert build(fe, run=run, which=lambda _: "npm") is True
    assert calls == [["ci", "--no-fund", "--no-audit"], ["run", "build"]]
    calls.clear()
    fe2 = make_frontend(tmp_path / "b", modules=True)
    assert build(fe2, run=run, which=lambda _: "npm") is True
    assert calls == [["run", "build"]]


def test_build_without_node_or_with_errors(tmp_path, capsys):
    fe = make_frontend(tmp_path, modules=True)
    assert build(fe, which=lambda _: None) is False
    assert "classic console" in capsys.readouterr().out
    assert build(fe, run=lambda cmd, cwd: SimpleNamespace(returncode=1), which=lambda _: "npm") is False
    assert "failed" in capsys.readouterr().out

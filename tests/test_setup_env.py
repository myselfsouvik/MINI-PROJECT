"""Tests for the first-run setup that start.bat / start.sh call (backend/setup_env.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("setup_env", Path(__file__).parent.parent / "backend" / "setup_env.py")
setup_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup_env)


def test_installs_again_only_when_requirements_change(tmp_path):
    req, venv_dir = tmp_path / "requirements.txt", tmp_path / ".venv"
    venv_dir.mkdir()
    req.write_bytes(b"fastapi\nnumpy\n")
    assert setup_env.needs_install(venv_dir, req)                    # never installed
    (venv_dir / setup_env.STAMP_NAME).write_text(setup_env.requirements_hash(req))
    assert not setup_env.needs_install(venv_dir, req)
    req.write_bytes(b"fastapi\r\nnumpy\r\n")                         # same file, Windows line endings
    assert not setup_env.needs_install(venv_dir, req)
    req.write_bytes(b"fastapi\nnumpy\npandas\n")                     # someone added a package
    assert setup_env.needs_install(venv_dir, req)


def test_small_pytorch_on_linux_without_nvidia():
    assert setup_env.wants_cpu_torch("Linux", which=lambda _: None)
    assert not setup_env.wants_cpu_torch("Linux", which=lambda _: "/usr/bin/nvidia-smi")
    assert not setup_env.wants_cpu_torch("Windows", which=lambda _: None)
    assert not setup_env.wants_cpu_torch("Darwin", which=lambda _: None)


def test_warns_about_folders_too_deep_for_windows(tmp_path):
    short, deep = Path("C:/Users/Asha/Downloads/MINI-PROJECT"), Path("C:/" + "very-long-folder-name/" * 6)
    assert not setup_env.path_too_long(short, enabled=lambda: False)
    assert setup_env.path_too_long(deep, enabled=lambda: False)
    assert not setup_env.path_too_long(deep, enabled=lambda: True)       # Windows long paths switched on


def test_setup_runs_without_any_packages():
    """It must run on a bare Python, before requirements.txt is installed."""
    src = (Path(setup_env.__file__)).read_text(encoding="utf-8")
    imports = {line.split()[1].split(".")[0] for line in src.splitlines() if line.startswith(("import ", "from "))}
    assert imports <= {"__future__", "hashlib", "os", "platform", "shutil", "subprocess", "sys", "venv", "pathlib"}

from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib

import openplot
from openplot import server


def test_package_version_matches_pyproject() -> None:
    pyproject_data = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert openplot.__version__ == pyproject_data["project"]["version"]


def test_frontend_package_version_matches_pyproject() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    pyproject_data = tomllib.loads(
        (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    frontend_package = json.loads(
        (repo_root / "frontend" / "package.json").read_text(encoding="utf-8")
    )

    assert frontend_package["version"] == pyproject_data["project"]["version"]


def test_frontend_lockfile_version_matches_pyproject() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    pyproject_data = tomllib.loads(
        (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    frontend_lock = json.loads(
        (repo_root / "frontend" / "package-lock.json").read_text(encoding="utf-8")
    )

    assert frontend_lock["version"] == pyproject_data["project"]["version"]
    assert (
        frontend_lock["packages"][""]["version"] == pyproject_data["project"]["version"]
    )


def test_server_module_uses_package_version_binding() -> None:
    assert server.__version__ == openplot.__version__


def test_flake_contains_single_npm_deps_hash_binding() -> None:
    flake_contents = (Path(__file__).resolve().parents[1] / "flake.nix").read_text(
        encoding="utf-8"
    )

    assert len(re.findall(r'(?m)^\s*npmDepsHash\s*=\s*"[^"]+";', flake_contents)) == 1

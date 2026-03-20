from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from openplot.release_versioning import (
    bump_version,
    compute_target_version,
    main,
    sync_repo_versions,
    validate_exact_version,
)


def _write_repo(
    repo_root: Path,
    *,
    pyproject_version: str = "1.2.3",
    frontend_version: str | None = None,
    frontend_lock_version: str | None = None,
    uv_lock_version: str | None = None,
    flake_versions: tuple[str, str, str] | None = None,
    init_version: str | None = None,
) -> Path:
    frontend_version = frontend_version or pyproject_version
    frontend_lock_version = frontend_lock_version or frontend_version
    uv_lock_version = uv_lock_version or pyproject_version
    flake_versions = flake_versions or (
        pyproject_version,
        pyproject_version,
        pyproject_version,
    )
    init_version = init_version or pyproject_version

    (repo_root / "src" / "openplot").mkdir(parents=True)
    (repo_root / "frontend").mkdir(parents=True)

    (repo_root / "pyproject.toml").write_text(
        textwrap.dedent(
            f"""\
            [project]
            name = "openplot"
            version = "{pyproject_version}"
            """
        ),
        encoding="utf-8",
    )
    (repo_root / "frontend" / "package.json").write_text(
        textwrap.dedent(
            f"""\
            {{
              "name": "openplot",
              "version": "{frontend_version}"
            }}
            """
        ),
        encoding="utf-8",
    )
    (repo_root / "frontend" / "package-lock.json").write_text(
        textwrap.dedent(
            f"""\
            {{
              "name": "openplot",
              "version": "{frontend_lock_version}",
              "lockfileVersion": 3,
              "requires": true,
              "packages": {{
                "": {{
                  "name": "openplot",
                  "version": "{frontend_lock_version}"
                }},
                "node_modules/example": {{
                  "version": "9.9.9"
                }}
              }}
            }}
            """
        ),
        encoding="utf-8",
    )
    (repo_root / "uv.lock").write_text(
        textwrap.dedent(
            f"""\
            version = 1

            [[package]]
            name = "openplot"
            version = "{uv_lock_version}"
            source = {{ editable = "." }}

            [[package]]
            name = "proxy-tools"
            version = "0.1.0"
            source = {{ registry = "https://pypi.org/simple" }}
            """
        ),
        encoding="utf-8",
    )
    (repo_root / "flake.nix").write_text(
        textwrap.dedent(
            f"""\
            {{
              frontend = {{ version = "{flake_versions[0]}"; }};
              app = {{ version = "{flake_versions[1]}"; }};
              desktop = {{ version = "{flake_versions[2]}"; }};
            }}
            """
        ),
        encoding="utf-8",
    )
    (repo_root / "src" / "openplot" / "__init__.py").write_text(
        f'__version__ = "{init_version}"\n',
        encoding="utf-8",
    )
    return repo_root


def test_bump_version_supports_patch_minor_and_major() -> None:
    assert bump_version("1.2.3", "patch") == "1.2.4"
    assert bump_version("1.2.3", "minor") == "1.3.0"
    assert bump_version("1.2.3", "major") == "2.0.0"


def test_validate_exact_version_accepts_higher_version() -> None:
    validate_exact_version("1.2.3", "1.2.4")
    validate_exact_version("1.2.3", "1.3.0")


@pytest.mark.parametrize("requested", ["1.2.3", "1.2.2", "invalid", "1.2"])
def test_validate_exact_version_rejects_invalid_requests(requested: str) -> None:
    with pytest.raises(ValueError):
        validate_exact_version("1.2.3", requested)


def test_compute_target_version_reads_pyproject_as_source_of_truth(
    tmp_path: Path,
) -> None:
    repo_root = _write_repo(
        tmp_path, pyproject_version="2.4.6", frontend_version="9.9.9"
    )

    assert compute_target_version(repo_root, "patch", None) == "2.4.7"


def test_sync_repo_versions_updates_all_targets_and_enforces_replacement_counts(
    tmp_path: Path,
) -> None:
    repo_root = _write_repo(
        tmp_path,
        pyproject_version="1.2.3",
        frontend_version="0.0.0",
        frontend_lock_version="0.0.0",
        uv_lock_version="0.0.0",
    )

    changed_files = sync_repo_versions(repo_root, "1.2.4", write=True)

    assert changed_files == [
        "pyproject.toml",
        "frontend/package.json",
        "frontend/package-lock.json",
        "uv.lock",
        "flake.nix",
        "src/openplot/__init__.py",
    ]
    assert 'version = "1.2.4"' in (repo_root / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert '"version": "1.2.4"' in (repo_root / "frontend" / "package.json").read_text(
        encoding="utf-8"
    )
    frontend_lock_text = (repo_root / "frontend" / "package-lock.json").read_text(
        encoding="utf-8"
    )
    assert frontend_lock_text.count('"version": "1.2.4"') == 2
    assert '"version": "9.9.9"' in frontend_lock_text
    uv_lock_text = (repo_root / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "openplot"\nversion = "1.2.4"' in uv_lock_text
    assert 'name = "proxy-tools"\nversion = "0.1.0"' in uv_lock_text
    flake_text = (repo_root / "flake.nix").read_text(encoding="utf-8")
    assert flake_text.count('version = "1.2.4"') == 3
    assert '__version__ = "1.2.4"' in (
        repo_root / "src" / "openplot" / "__init__.py"
    ).read_text(encoding="utf-8")


def test_sync_repo_versions_write_is_atomic_on_validation_failure(
    tmp_path: Path,
) -> None:
    repo_root = _write_repo(tmp_path)
    original_pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    original_frontend = (repo_root / "frontend" / "package.json").read_text(
        encoding="utf-8"
    )
    original_frontend_lock = (repo_root / "frontend" / "package-lock.json").read_text(
        encoding="utf-8"
    )
    original_uv_lock = (repo_root / "uv.lock").read_text(encoding="utf-8")
    original_flake = (repo_root / "flake.nix").read_text(encoding="utf-8")
    original_init = (repo_root / "src" / "openplot" / "__init__.py").read_text(
        encoding="utf-8"
    )

    flake_path = repo_root / "flake.nix"
    flake_path.write_text(
        flake_path.read_text(encoding="utf-8").replace(
            'version = "1.2.3"', 'appVersion = "1.2.3"', 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="flake.nix"):
        sync_repo_versions(repo_root, "1.2.4", write=True)

    assert (repo_root / "pyproject.toml").read_text(
        encoding="utf-8"
    ) == original_pyproject
    assert (repo_root / "frontend" / "package.json").read_text(
        encoding="utf-8"
    ) == original_frontend
    assert (repo_root / "frontend" / "package-lock.json").read_text(
        encoding="utf-8"
    ) == original_frontend_lock
    assert (repo_root / "uv.lock").read_text(encoding="utf-8") == original_uv_lock
    assert (repo_root / "flake.nix").read_text(encoding="utf-8") != original_flake
    assert (repo_root / "src" / "openplot" / "__init__.py").read_text(
        encoding="utf-8"
    ) == original_init


def test_sync_repo_versions_write_rolls_back_if_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = _write_repo(
        tmp_path,
        pyproject_version="1.2.3",
        frontend_version="0.0.0",
        frontend_lock_version="0.0.0",
        uv_lock_version="0.0.0",
    )
    original_pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    original_frontend = (repo_root / "frontend" / "package.json").read_text(
        encoding="utf-8"
    )
    original_frontend_lock = (repo_root / "frontend" / "package-lock.json").read_text(
        encoding="utf-8"
    )
    original_uv_lock = (repo_root / "uv.lock").read_text(encoding="utf-8")
    original_flake = (repo_root / "flake.nix").read_text(encoding="utf-8")
    original_init = (repo_root / "src" / "openplot" / "__init__.py").read_text(
        encoding="utf-8"
    )
    original_replace = Path.replace

    def failing_replace(self: Path, target: Path) -> Path:
        if (
            self.name.startswith(".__openplot_versioning")
            and target == repo_root / "flake.nix"
        ):
            raise OSError("simulated replace failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        sync_repo_versions(repo_root, "1.2.4", write=True)

    assert (repo_root / "pyproject.toml").read_text(
        encoding="utf-8"
    ) == original_pyproject
    assert (repo_root / "frontend" / "package.json").read_text(
        encoding="utf-8"
    ) == original_frontend
    assert (repo_root / "frontend" / "package-lock.json").read_text(
        encoding="utf-8"
    ) == original_frontend_lock
    assert (repo_root / "uv.lock").read_text(encoding="utf-8") == original_uv_lock
    assert (repo_root / "flake.nix").read_text(encoding="utf-8") == original_flake
    assert (repo_root / "src" / "openplot" / "__init__.py").read_text(
        encoding="utf-8"
    ) == original_init


@pytest.mark.parametrize(
    ("broken_file", "mutator"),
    [
        (
            "flake.nix",
            lambda text: text.replace('version = "1.2.3"', 'appVersion = "1.2.3"', 1),
        ),
        (
            "pyproject.toml",
            lambda text: text.replace('version = "1.2.3"', '# version = "1.2.3"'),
        ),
        (
            "frontend/package.json",
            lambda text: text.replace('"version": "1.2.3"', '"pkgVersion": "1.2.3"'),
        ),
        (
            "frontend/package-lock.json",
            lambda text: text.replace(
                '"version": "1.2.3"', '"lockVersion": "1.2.3"', 1
            ),
        ),
        (
            "uv.lock",
            lambda text: text.replace(
                'name = "openplot"\nversion = "1.2.3"',
                'name = "openplot"\npackage_version = "1.2.3"',
            ),
        ),
        (
            "src/openplot/__init__.py",
            lambda text: text.replace('__version__ = "1.2.3"', 'VERSION = "1.2.3"'),
        ),
    ],
)
def test_sync_repo_versions_raises_on_replacement_count_drift(
    tmp_path: Path,
    broken_file: str,
    mutator,
) -> None:
    repo_root = _write_repo(tmp_path)
    path = repo_root / broken_file
    path.write_text(mutator(path.read_text(encoding="utf-8")), encoding="utf-8")

    with pytest.raises(ValueError, match=broken_file):
        sync_repo_versions(repo_root, "1.2.4", write=False)


def test_main_check_reports_consistency_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = _write_repo(tmp_path, pyproject_version="1.2.3")
    old_cwd = Path.cwd()

    try:
        os.chdir(repo_root)
        exit_code = main(["--check"])
    finally:
        os.chdir(old_cwd)

    assert exit_code == 0
    assert "1.2.3" in capsys.readouterr().out


def test_main_check_ignores_missing_exact_version_for_exact_release_type(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = _write_repo(tmp_path, pyproject_version="1.2.3")
    old_cwd = Path.cwd()

    try:
        os.chdir(repo_root)
        exit_code = main(["--check", "--release-type", "exact"])
    finally:
        os.chdir(old_cwd)

    assert exit_code == 0
    assert "1.2.3" in capsys.readouterr().out


def test_main_dry_run_reports_changes_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = _write_repo(
        tmp_path,
        pyproject_version="1.2.3",
        frontend_version="0.0.0",
        frontend_lock_version="0.0.0",
    )
    old_cwd = Path.cwd()

    try:
        os.chdir(repo_root)
        exit_code = main(["--release-type", "patch", "--dry-run"])
    finally:
        os.chdir(old_cwd)

    assert exit_code == 0
    assert '"version": "0.0.0"' in (repo_root / "frontend" / "package.json").read_text(
        encoding="utf-8"
    )
    assert "1.2.4" in capsys.readouterr().out


def test_main_writes_target_version_to_github_output_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = _write_repo(tmp_path, pyproject_version="1.2.3")
    github_output = repo_root / "github-output.txt"
    old_cwd = Path.cwd()

    try:
        os.chdir(repo_root)
        exit_code = main(
            [
                "--release-type",
                "patch",
                "--dry-run",
                "--github-output",
                str(github_output),
            ]
        )
    finally:
        os.chdir(old_cwd)

    assert exit_code == 0
    assert github_output.read_text(encoding="utf-8") == "target_version=1.2.4\n"
    assert "DRY_RUN 1.2.4" in capsys.readouterr().out


def test_main_requires_exact_version_for_exact_release_type(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = _write_repo(tmp_path)
    old_cwd = Path.cwd()

    try:
        os.chdir(repo_root)
        exit_code = main(["--release-type", "exact"])
    finally:
        os.chdir(old_cwd)

    assert exit_code == 2
    assert "--exact-version" in capsys.readouterr().err


def test_main_rejects_invalid_semver(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = _write_repo(tmp_path, pyproject_version="bad.version")
    old_cwd = Path.cwd()

    try:
        os.chdir(repo_root)
        exit_code = main(["--release-type", "patch"])
    finally:
        os.chdir(old_cwd)

    assert exit_code == 1
    assert "bad.version" in capsys.readouterr().err


def test_main_reports_missing_target_file_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = _write_repo(tmp_path)
    old_cwd = Path.cwd()
    (repo_root / "frontend" / "package.json").unlink()

    try:
        os.chdir(repo_root)
        exit_code = main(["--release-type", "patch"])
    finally:
        os.chdir(old_cwd)

    assert exit_code == 1
    assert "frontend/package.json" in capsys.readouterr().err


def test_main_discovers_repo_root_from_current_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = _write_repo(tmp_path, pyproject_version="1.2.3")
    nested_dir = repo_root / "src" / "openplot"
    monkeypatch.chdir(nested_dir)

    exit_code = main(["--release-type", "minor", "--dry-run"])

    assert exit_code == 0
    assert "1.3.0" in capsys.readouterr().out

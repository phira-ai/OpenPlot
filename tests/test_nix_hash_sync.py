from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from openplot.nix_hash_sync import main, sync_npm_deps_hash


def _write_repo(
    repo_root: Path,
    *,
    flake_hash: str = "sha256-oldhash1234567890+/=",
    include_flake: bool = True,
    include_hash_binding: bool = True,
) -> Path:
    (repo_root / "frontend").mkdir(parents=True)
    (repo_root / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "openplot"
            version = "1.2.3"
            """
        ),
        encoding="utf-8",
    )
    (repo_root / "frontend" / "package-lock.json").write_text(
        '{"name": "openplot", "lockfileVersion": 3}\n',
        encoding="utf-8",
    )
    if include_flake:
        binding = (
            f'npmDepsHash = "{flake_hash}";'
            if include_hash_binding
            else 'version = "1.2.3";'
        )
        (repo_root / "flake.nix").write_text(
            textwrap.dedent(
                f"""\
                {{
                  outputs = {{ self }}: {{
                    packages.x86_64-linux.default = {{
                      {binding}
                    }};
                  }};
                }}
                """
            ),
            encoding="utf-8",
        )
    return repo_root


def _stub_prefetch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdout: str = "sha256-newhash1234567890+/=\n",
    stderr: str = "",
    returncode: int = 0,
) -> None:
    def fake_run(cmd: list[str], *, check: bool, capture_output: bool, text: bool):
        assert cmd[:3] == ["nix", "run", "nixpkgs#prefetch-npm-deps"]
        assert cmd[3] == "--"
        assert cmd[4].endswith("package-lock.json")
        assert check is False
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(
            cmd, returncode, stdout=stdout, stderr=stderr
        )

    monkeypatch.setattr("subprocess.run", fake_run)


def test_sync_npm_deps_hash_updates_flake_nix_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = _write_repo(tmp_path)
    _stub_prefetch(monkeypatch)

    result = sync_npm_deps_hash(repo_root, write=True)

    assert result.hash_value == "sha256-newhash1234567890+/="
    assert result.changed is True
    assert 'npmDepsHash = "sha256-newhash1234567890+/=";' in (
        repo_root / "flake.nix"
    ).read_text(encoding="utf-8")


def test_sync_npm_deps_hash_is_noop_when_hash_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = _write_repo(tmp_path, flake_hash="sha256-newhash1234567890+/=")
    _stub_prefetch(monkeypatch)

    result = sync_npm_deps_hash(repo_root, write=True)

    assert result.hash_value == "sha256-newhash1234567890+/="
    assert result.changed is False


def test_sync_npm_deps_hash_requires_flake_nix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = _write_repo(tmp_path, include_flake=False)
    _stub_prefetch(monkeypatch)

    with pytest.raises(ValueError, match="Missing target file: flake.nix"):
        sync_npm_deps_hash(repo_root, write=False)


def test_sync_npm_deps_hash_requires_npm_deps_hash_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = _write_repo(tmp_path, include_hash_binding=False)
    _stub_prefetch(monkeypatch)

    with pytest.raises(ValueError, match="flake.nix replacement count mismatch"):
        sync_npm_deps_hash(repo_root, write=False)


def test_sync_npm_deps_hash_surfaces_prefetch_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = _write_repo(tmp_path)
    _stub_prefetch(monkeypatch, returncode=1, stderr="prefetch exploded\n")

    with pytest.raises(ValueError, match="prefetch exploded"):
        sync_npm_deps_hash(repo_root, write=False)


def test_sync_npm_deps_hash_rejects_malformed_hash_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = _write_repo(tmp_path)
    _stub_prefetch(monkeypatch, stdout="not-a-hash\n")

    with pytest.raises(ValueError, match="Malformed nix hash output"):
        sync_npm_deps_hash(repo_root, write=False)


def test_main_dry_run_reports_pending_hash_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = _write_repo(tmp_path)
    original_flake = (repo_root / "flake.nix").read_text(encoding="utf-8")
    _stub_prefetch(monkeypatch)
    monkeypatch.chdir(repo_root / "frontend")

    exit_code = main(["--dry-run"])

    assert exit_code == 0
    assert capsys.readouterr().out == "DRY_RUN sha256-newhash1234567890+/=\n"
    assert (repo_root / "flake.nix").read_text(encoding="utf-8") == original_flake


def test_main_check_reports_drift_when_flake_hash_is_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = _write_repo(tmp_path, flake_hash="sha256-oldhash1234567890+/=")
    _stub_prefetch(monkeypatch)
    monkeypatch.chdir(repo_root)

    exit_code = main(["--check"])

    assert exit_code == 1
    assert capsys.readouterr().out == "DRIFT sha256-newhash1234567890+/=\n"


def test_main_check_reports_ok_when_flake_hash_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = _write_repo(tmp_path, flake_hash="sha256-newhash1234567890+/=")
    _stub_prefetch(monkeypatch)
    monkeypatch.chdir(repo_root)

    exit_code = main(["--check"])

    assert exit_code == 0
    assert capsys.readouterr().out == "OK sha256-newhash1234567890+/=\n"


def test_main_reports_ok_for_noop_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = _write_repo(tmp_path, flake_hash="sha256-newhash1234567890+/=")
    _stub_prefetch(monkeypatch)
    monkeypatch.chdir(repo_root)

    exit_code = main([])

    assert exit_code == 0
    assert capsys.readouterr().out == "OK sha256-newhash1234567890+/=\n"


def test_main_reports_errors_on_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = _write_repo(tmp_path)
    _stub_prefetch(monkeypatch, stdout="oops\n")
    monkeypatch.chdir(repo_root)

    exit_code = main([])

    assert exit_code == 1
    assert "Malformed nix hash output" in capsys.readouterr().err

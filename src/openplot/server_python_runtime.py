"""Python runtime helper seam extracted from openplot.server."""

from __future__ import annotations

import json
import os
import pkgutil
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Literal, cast

from .models import PlotSession


def _load_python_interpreter_preference(server_module: ModuleType) -> str | None:
    preferences = server_module._load_preferences_data()
    return server_module._normalize_preference_value(
        preferences.get(server_module._python_interpreter_preference_key)
    )


def _save_python_interpreter_preference(
    server_module: ModuleType, path: str | None
) -> None:
    preferences = server_module._load_preferences_data()
    if path is None:
        preferences.pop(server_module._python_interpreter_preference_key, None)
    else:
        preferences[server_module._python_interpreter_preference_key] = path

    preferences_path = server_module._preferences_path()
    tmp_path = preferences_path.with_name(f".{preferences_path.name}.tmp")
    tmp_path.write_text(
        json.dumps(preferences, indent=2, sort_keys=True), encoding="utf-8"
    )
    tmp_path.replace(preferences_path)


def _python_context_dir(
    server_module: ModuleType, session: PlotSession | None = None
) -> Path:
    if session is not None and session.source_script_path:
        script_path = server_module._resolve_session_file_path(
            session, session.source_script_path
        )
        return script_path.parent.resolve()
    if session is not None:
        return server_module._workspace_for_session(session)
    return server_module._workspace_dir


def _is_executable_file(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _should_probe_with_current_runtime(
    server_module: ModuleType, interpreter_path: Path
) -> bool:
    if not server_module._is_openplot_app_launcher_path(interpreter_path):
        return False

    try:
        return interpreter_path.resolve() == Path(sys.executable).resolve()
    except OSError:
        return False


def _probe_current_runtime_packages() -> list[str]:
    modules: set[str] = set()
    for module in pkgutil.iter_modules():
        modules.add(module.name)

    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    packages: list[str] = []
    for name in modules:
        if not isinstance(name, str):
            continue
        if not name or name in stdlib or name.startswith("_"):
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        packages.append(name)

    return sorted(set(packages))


def _probe_python_interpreter(
    server_module: ModuleType,
    interpreter_path: Path,
    *,
    timeout_s: float = 4.0,
) -> tuple[str | None, str | None]:
    if not _is_executable_file(interpreter_path):
        return None, f"Interpreter is not executable: {interpreter_path}"

    if _should_probe_with_current_runtime(server_module, interpreter_path):
        return sys.version.split()[0], None

    probe_code = (
        "import json,sys; print(json.dumps({'version': sys.version.split()[0], "
        "'executable': sys.executable}))"
    )

    try:
        no_window_kwargs = server_module._no_window_kwargs()
        creationflags = cast(int, no_window_kwargs.get("creationflags", 0))
        result = server_module.run_text_subprocess(
            [str(interpreter_path), "-c", probe_code],
            timeout=timeout_s,
            check=False,
            creationflags=creationflags,
        )
    except OSError as exc:
        return None, str(exc)
    except subprocess.TimeoutExpired:
        return None, f"Timed out validating interpreter: {interpreter_path}"
    except UnicodeDecodeError as exc:
        return None, f"Failed to decode interpreter probe output: {exc}"

    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip() or (
            f"Interpreter exited with code {result.returncode}"
        )
        return None, details

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return None, f"Interpreter probe returned no output: {interpreter_path}"

    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        return None, f"Failed to parse interpreter probe output: {exc}"

    version = payload.get("version") if isinstance(payload, dict) else None
    if not isinstance(version, str) or not version.strip():
        return None, "Interpreter probe did not report a valid Python version"

    return version.strip(), None


def _validated_python_candidate(
    server_module: ModuleType,
    candidate_path: Path,
    *,
    source: str,
) -> tuple[dict[str, str] | None, str | None]:
    expanded = candidate_path.expanduser()
    if not expanded.exists():
        return None, f"Interpreter not found: {expanded}"

    absolute_path = (
        expanded
        if expanded.is_absolute()
        else (server_module._workspace_dir / expanded)
    )
    absolute_path = absolute_path.absolute()
    version, error = server_module._probe_python_interpreter(absolute_path)
    if version is None:
        return None, error

    return {
        "path": str(absolute_path),
        "source": source,
        "version": version,
    }, None


def _auto_python_search_dirs(
    server_module: ModuleType, context_dir: Path
) -> list[Path]:
    ancestry = [context_dir, *context_dir.parents]
    marker_index = next(
        (
            index
            for index, directory in enumerate(ancestry)
            if any(
                (directory / marker).exists()
                for marker in server_module._python_project_markers
            )
        ),
        None,
    )

    if marker_index is None:
        return [context_dir]

    return ancestry[: marker_index + 1]


def _discover_python_interpreter_candidates(
    server_module: ModuleType, context_dir: Path
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen_paths: set[str] = set()

    def append_candidate(path: Path, *, source: str) -> None:
        candidate, _error = server_module._validated_python_candidate(
            path, source=source
        )
        if candidate is None:
            return
        key = candidate["path"]
        if key in seen_paths:
            return
        seen_paths.add(key)
        candidates.append(candidate)

    for directory in _auto_python_search_dirs(server_module, context_dir):
        for relative in server_module._auto_python_relative_paths:
            append_candidate(directory / relative, source="nearest-venv")

    append_candidate(Path(sys.executable), source="app-runtime")

    virtual_env = os.getenv("VIRTUAL_ENV")
    if virtual_env:
        append_candidate(
            Path(virtual_env) / "bin" / "python", source="active-virtualenv"
        )

    python3_from_path = shutil.which("python3")
    if python3_from_path:
        append_candidate(Path(python3_from_path), source="path-python3")

    python_from_path = shutil.which("python")
    if python_from_path:
        append_candidate(Path(python_from_path), source="path-python")

    return candidates


def _built_in_python_candidate(
    server_module: ModuleType,
) -> tuple[dict[str, str] | None, str | None]:
    built_in_override = server_module._normalize_preference_value(
        os.getenv("OPENPLOT_BUILTIN_PYTHON")
    )
    built_in_path = (
        Path(built_in_override).expanduser()
        if built_in_override
        else Path(sys.executable).expanduser().resolve()
    )
    return server_module._validated_python_candidate(built_in_path, source="built-in")


def _probe_python_packages(
    server_module: ModuleType,
    interpreter_path: Path,
    *,
    timeout_s: float = 8.0,
) -> tuple[list[str], str | None]:
    if not _is_executable_file(interpreter_path):
        return [], f"Interpreter is not executable: {interpreter_path}"

    if _should_probe_with_current_runtime(server_module, interpreter_path):
        try:
            return _probe_current_runtime_packages(), None
        except Exception as exc:
            return [], str(exc)

    probe_code = (
        "import json, pkgutil, site, sys\n"
        "paths = []\n"
        "seen = set()\n"
        "def add_path(raw):\n"
        "    if not isinstance(raw, str):\n"
        "        return\n"
        "    value = raw.strip()\n"
        "    if not value or value in seen:\n"
        "        return\n"
        "    seen.add(value)\n"
        "    paths.append(value)\n"
        "for item in (getattr(site, 'getsitepackages', lambda: [])() or []):\n"
        "    add_path(item)\n"
        "user_site = getattr(site, 'getusersitepackages', lambda: '')()\n"
        "if isinstance(user_site, str):\n"
        "    add_path(user_site)\n"
        "for item in sys.path:\n"
        "    if isinstance(item, str) and ('site-packages' in item or 'dist-packages' in item):\n"
        "        add_path(item)\n"
        "modules = set()\n"
        "for path in paths:\n"
        "    try:\n"
        "        for mod in pkgutil.iter_modules([path]):\n"
        "            modules.add(mod.name)\n"
        "    except Exception:\n"
        "        continue\n"
        "stdlib = set(getattr(sys, 'stdlib_module_names', ()))\n"
        "available = sorted(\n"
        "    name\n"
        "    for name in modules\n"
        "    if isinstance(name, str) and name and name not in stdlib\n"
        ")\n"
        "print(json.dumps(available))\n"
    )

    try:
        no_window_kwargs = server_module._no_window_kwargs()
        creationflags = cast(int, no_window_kwargs.get("creationflags", 0))
        result = server_module.run_text_subprocess(
            [str(interpreter_path), "-c", probe_code],
            timeout=timeout_s,
            check=False,
            creationflags=creationflags,
        )
    except OSError as exc:
        return [], str(exc)
    except subprocess.TimeoutExpired:
        return [], f"Timed out validating packages for interpreter: {interpreter_path}"
    except UnicodeDecodeError as exc:
        return [], f"Failed to decode package probe output: {exc}"

    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip() or (
            f"Interpreter exited with code {result.returncode}"
        )
        return [], details

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return [], f"Interpreter package probe returned no output: {interpreter_path}"

    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        return [], f"Failed to parse package probe output: {exc}"

    if not isinstance(payload, list):
        return [], "Package probe did not return a list"

    packages: list[str] = []
    for item in payload:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name:
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        packages.append(name)

    return sorted(set(packages)), None


def _resolve_python_interpreter_state(
    server_module: ModuleType,
    session: PlotSession | None = None,
) -> dict[str, object]:
    context_dir = server_module._python_context_dir(session)
    candidates = server_module._discover_python_interpreter_candidates(context_dir)
    configured_path = server_module._load_python_interpreter_preference()
    mode: Literal["builtin", "manual"] = "manual" if configured_path else "builtin"
    configured_error: str | None = None

    built_in_candidate, _built_in_error = _built_in_python_candidate(server_module)
    if built_in_candidate is not None:
        default_runtime = built_in_candidate
        if all(
            candidate.get("path") != built_in_candidate["path"]
            for candidate in candidates
        ):
            candidates = [built_in_candidate, *candidates]
    else:
        default_runtime = {
            "path": str(Path(sys.executable).expanduser().resolve()),
            "source": "built-in",
            "version": "",
        }
        candidates = [default_runtime, *candidates]

    resolved = default_runtime

    if configured_path:
        manual_candidate, manual_error = server_module._validated_python_candidate(
            Path(configured_path),
            source="manual",
        )
        if manual_candidate is None:
            configured_error = manual_error or (
                f"Configured interpreter is unavailable: {configured_path}"
            )
        else:
            resolved = manual_candidate
            if all(
                candidate.get("path") != manual_candidate["path"]
                for candidate in candidates
            ):
                candidates = [*candidates, manual_candidate]

    default_path = str(default_runtime.get("path", "")).strip()
    default_available_packages: list[str]
    default_package_probe_error: str | None
    if default_path:
        default_available_packages, default_package_probe_error = (
            server_module._probe_python_packages(
                Path(default_path),
            )
        )
    else:
        default_available_packages = []
        default_package_probe_error = "Default runtime path is empty"

    resolved_path = str(resolved.get("path", "")).strip()
    available_packages: list[str]
    package_probe_error: str | None
    if resolved_path == default_path:
        available_packages = list(default_available_packages)
        package_probe_error = default_package_probe_error
    elif resolved_path:
        available_packages, package_probe_error = server_module._probe_python_packages(
            Path(resolved_path),
        )
    else:
        available_packages = []
        package_probe_error = "Resolved interpreter path is empty"

    return {
        "mode": mode,
        "configured_path": configured_path,
        "configured_error": configured_error,
        "resolved_path": resolved_path,
        "resolved_source": str(resolved.get("source", "")),
        "resolved_version": str(resolved.get("version", "")),
        "default_path": default_path,
        "default_version": str(default_runtime.get("version", "")),
        "default_available_packages": default_available_packages,
        "default_available_package_count": len(default_available_packages),
        "default_package_probe_error": default_package_probe_error,
        "available_packages": available_packages,
        "available_package_count": len(available_packages),
        "package_probe_error": package_probe_error,
        "data_root": str(server_module._data_root()),
        "state_root": str(server_module._state_root()),
        "context_dir": str(context_dir),
        "candidates": candidates,
    }

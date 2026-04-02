"""Import-safe path picker helpers extracted from openplot.server."""

from __future__ import annotations

import os
from pathlib import Path
from types import ModuleType

from fastapi import HTTPException


def _resolved_home_dir(server_module: ModuleType) -> Path | None:
    try:
        return Path.home().resolve()
    except RuntimeError:
        return None


def _picker_default_base_dir(server_module: ModuleType) -> Path:
    return server_module._resolved_home_dir() or Path.cwd().resolve()


def _common_parent_dir(server_module: ModuleType, paths: list[Path]) -> Path | None:
    resolved_dirs: list[Path] = []
    for path in paths:
        resolved = server_module._expanduser_if_needed(path).resolve()
        resolved_dirs.append(resolved if resolved.is_dir() else resolved.parent)

    if not resolved_dirs:
        return None

    try:
        return Path(os.path.commonpath([str(path) for path in resolved_dirs])).resolve()
    except ValueError:
        return resolved_dirs[0]


def _expanduser_if_needed(server_module: ModuleType, path: Path) -> Path:
    if not str(path).startswith("~"):
        return path
    return path.expanduser()


def _resolve_local_picker_path(
    server_module: ModuleType,
    raw_path: str,
    *,
    base_dir: Path | None = None,
) -> Path:
    resolved_base_dir = (base_dir or server_module._workspace_dir).resolve()
    text = raw_path.strip()
    if not text:
        return resolved_base_dir

    try:
        candidate = server_module._expanduser_if_needed(Path(text))
    except RuntimeError as exc:
        raise HTTPException(
            status_code=422,
            detail="Cannot resolve '~' because the home directory is unavailable.",
        ) from exc
    if candidate.is_absolute():
        return candidate.resolve()
    return (resolved_base_dir / candidate).resolve()


def _picker_parent_and_fragment(
    server_module: ModuleType,
    raw_query: str,
    *,
    base_dir: Path | None = None,
) -> tuple[Path, str]:
    resolved_base_dir = (base_dir or server_module._workspace_dir).resolve()
    query = raw_query.strip()
    if not query:
        return resolved_base_dir, ""

    normalized = query.replace("\\", "/")
    resolved = server_module._resolve_local_picker_path(
        query, base_dir=resolved_base_dir
    )
    if normalized.endswith("/"):
        return resolved, ""
    return resolved.parent, resolved.name


def _display_picker_path(server_module: ModuleType, path: Path, *, as_dir: bool) -> str:
    resolved = path.resolve()
    home = server_module._resolved_home_dir()

    if home is None:
        display = resolved.as_posix()
    else:
        try:
            relative_to_home = resolved.relative_to(home)
            if str(relative_to_home) == ".":
                display = "~"
            else:
                display = f"~/{relative_to_home.as_posix()}"
        except ValueError:
            display = resolved.as_posix()

    if as_dir and not display.endswith("/"):
        return f"{display}/"
    return display


def _is_fuzzy_subsequence(
    server_module: ModuleType, needle: str, haystack: str
) -> bool:
    if not needle:
        return True
    index = 0
    for char in haystack:
        if char == needle[index]:
            index += 1
            if index == len(needle):
                return True
    return False


def _path_suggestion_score(
    server_module: ModuleType, name: str, fragment: str
) -> int | None:
    if not fragment:
        return 0

    lower_name = name.lower()
    lower_fragment = fragment.lower()

    if lower_name.startswith(lower_fragment):
        return 0

    contains_index = lower_name.find(lower_fragment)
    if contains_index != -1:
        return 10 + contains_index

    if server_module._is_fuzzy_subsequence(lower_fragment, lower_name):
        return 100 + len(lower_name)

    return None


def _list_path_suggestions(
    server_module: ModuleType,
    *,
    query: str,
    selection_type: str,
    base_dir: Path | None = None,
    limit: int = 120,
) -> tuple[Path, list[dict[str, object]]]:
    parent_dir, fragment = server_module._picker_parent_and_fragment(
        query, base_dir=base_dir
    )
    if not parent_dir.is_dir():
        return parent_dir, []

    show_hidden = fragment.startswith(".")
    ranked: list[tuple[int, int, str, dict[str, object]]] = []
    try:
        entries = list(parent_dir.iterdir())
    except OSError:
        return parent_dir, []

    for entry in entries:
        name = entry.name
        if not show_hidden and name.startswith("."):
            continue

        try:
            is_dir = entry.is_dir()
            is_file = entry.is_file()
        except OSError:
            continue

        if not is_dir and not is_file:
            continue

        if is_file:
            suffix = entry.suffix.lower()
            if selection_type == "script" and suffix != ".py":
                continue
            if selection_type == "data" and suffix == ".py":
                continue

        score = server_module._path_suggestion_score(name, fragment)
        if score is None:
            continue

        resolved_entry = entry.resolve()
        ranked.append(
            (
                score,
                0 if is_dir else 1,
                name.lower(),
                {
                    "path": str(resolved_entry),
                    "display_path": server_module._display_picker_path(
                        resolved_entry, as_dir=is_dir
                    ),
                    "is_dir": is_dir,
                    "is_file": is_file,
                },
            )
        )

    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    suggestions = [item[3] for item in ranked[:limit]]
    return parent_dir, suggestions


def _resolve_selected_file_path(
    server_module: ModuleType,
    *,
    raw_path: str,
    selection_type: str,
    base_dir: Path | None = None,
) -> Path:
    normalized = raw_path.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="File path cannot be empty")

    resolved = server_module._resolve_local_picker_path(normalized, base_dir=base_dir)
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=422, detail=f"File not found: {resolved}")

    suffix = resolved.suffix.lower()
    if selection_type == "script" and suffix != ".py":
        raise HTTPException(
            status_code=422,
            detail=f"Script selection requires a .py file: {resolved}",
        )
    if selection_type == "data" and suffix == ".py":
        raise HTTPException(
            status_code=422,
            detail=(
                "Data-file selection does not accept .py scripts. "
                "Use selection_type='script' for Python files."
            ),
        )

    return resolved.resolve()

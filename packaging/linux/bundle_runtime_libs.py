#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple


_GLIBC_PREFIXES = (
    "linux-vdso.so",
    "ld-linux",
    "libc.so.",
    "libm.so.",
    "libpthread.so.",
    "libdl.so.",
    "librt.so.",
    "libutil.so.",
    "libresolv.so.",
)

_SCAN_PATTERNS = (
    "OpenPlot",
    "_internal/PyQt6/*.so",
    "_internal/PyQt6/Qt6/lib/*.so*",
    "_internal/PyQt6/Qt6/plugins/**/*.so*",
    "_internal/PyQt6/Qt6/libexec/QtWebEngineProcess",
)

_REQUIRED_QT_ASSETS = (
    "_internal/PyQt6/Qt6/plugins/platforms/libqxcb.so",
    "_internal/PyQt6/Qt6/libexec/QtWebEngineProcess",
    "_internal/PyQt6/Qt6/resources/qtwebengine_resources.pak",
)


def _is_glibc_runtime(lib_name: str) -> bool:
    normalized = Path(lib_name).name
    return normalized.startswith(_GLIBC_PREFIXES)


def _discover_ldconfig_entries() -> dict[str, Path]:
    try:
        output = subprocess.check_output(
            ["ldconfig", "-p"], text=True, stderr=subprocess.DEVNULL
        )
    except (OSError, subprocess.CalledProcessError):
        return {}

    entries: dict[str, Path] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if " => " not in line:
            continue
        left, right = line.split(" => ", 1)
        soname = left.split(" ", 1)[0]
        path = Path(right.strip())
        if path.is_file() and soname not in entries:
            entries[soname] = path
    return entries


def _existing_bundle_match(bundle_dir: Path, soname: str) -> Path | None:
    direct_candidates = [
        bundle_dir / "_internal" / soname,
        bundle_dir / "_internal" / "PyQt6" / "Qt6" / "lib" / soname,
    ]
    for candidate in direct_candidates:
        if candidate.is_file():
            return candidate

    stem = soname.split(".so", 1)[0]

    def _name_matches(candidate_name: str) -> bool:
        if not candidate_name.startswith(stem):
            return False
        if len(candidate_name) == len(stem):
            return True
        return candidate_name[len(stem)] in (".", "-")

    for candidate in (bundle_dir / "_internal").glob(f"{stem}*.so*"):
        if candidate.is_file() and _name_matches(candidate.name):
            return candidate
    return None


def _resolve_system_lib(
    soname: str,
    *,
    ldconfig_map: dict[str, Path],
    search_roots: list[Path],
) -> Path | None:
    if soname in ldconfig_map:
        return ldconfig_map[soname]

    for root in search_roots:
        candidate = root / soname
        if candidate.is_file():
            return candidate

    for root in search_roots:
        for candidate in root.glob(f"**/{soname}"):
            if candidate.is_file():
                return candidate

    nix_store = Path("/nix/store")
    if nix_store.is_dir():
        for pattern in (f"*/lib/{soname}", f"*/lib64/{soname}"):
            for candidate in nix_store.glob(pattern):
                if candidate.is_file():
                    return candidate
    return None


def _copy_shared_lib(src: Path, soname: str, dest_lib_dir: Path) -> Path:
    dest_lib_dir.mkdir(parents=True, exist_ok=True)

    resolved = src.resolve()
    resolved_dest = dest_lib_dir / resolved.name
    if not resolved_dest.exists():
        shutil.copy2(resolved, resolved_dest)

    link_dest = dest_lib_dir / soname
    if link_dest.exists():
        return resolved_dest
    if link_dest.name == resolved_dest.name:
        return resolved_dest
    link_dest.symlink_to(resolved_dest.name)
    return resolved_dest


def _scan_targets(bundle_dir: Path) -> list[Path]:
    seen: set[Path] = set()
    targets: list[Path] = []
    for pattern in _SCAN_PATTERNS:
        for candidate in bundle_dir.glob(pattern):
            if not candidate.is_file():
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            targets.append(candidate)
    return targets


class _LinkedLibrary(NamedTuple):
    soname: str
    resolved_path: Path | None


def _linked_libraries(
    target: Path, runtime_lib_dirs: list[Path]
) -> list[_LinkedLibrary]:
    env = os.environ.copy()
    existing = env.get("LD_LIBRARY_PATH", "")
    runtime = ":".join(str(path) for path in runtime_lib_dirs)
    env["LD_LIBRARY_PATH"] = f"{runtime}:{existing}" if existing else runtime

    try:
        output = subprocess.check_output(
            ["ldd", str(target)], text=True, stderr=subprocess.STDOUT, env=env
        )
    except subprocess.CalledProcessError as exc:
        output = exc.output

    linked: list[_LinkedLibrary] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line == "statically linked":
            continue

        if "=>" in line:
            left, right = line.split("=>", 1)
            soname = left.strip().split(" ", 1)[0]
            path_text = right.strip().split(" (", 1)[0].strip()
            if path_text == "not found":
                linked.append(_LinkedLibrary(soname=soname, resolved_path=None))
                continue
            if path_text.startswith("/"):
                linked.append(
                    _LinkedLibrary(soname=soname, resolved_path=Path(path_text))
                )
                continue

        token = line.split(" ", 1)[0]
        if not token:
            continue
        if token.startswith("/"):
            linked.append(
                _LinkedLibrary(soname=Path(token).name, resolved_path=Path(token))
            )
            continue
        linked.append(_LinkedLibrary(soname=token, resolved_path=None))

    return linked


def _path_within_dirs(path: Path, dirs: list[Path]) -> bool:
    resolved = path.resolve()
    for base in dirs:
        try:
            resolved.relative_to(base)
            return True
        except ValueError:
            continue
    return False


def _runtime_issues(
    targets: list[Path], runtime_lib_dirs: list[Path]
) -> tuple[set[str], dict[str, set[Path]]]:
    unresolved: set[str] = set()
    external: dict[str, set[Path]] = {}

    for target in targets:
        for linked in _linked_libraries(target, runtime_lib_dirs):
            if _is_glibc_runtime(linked.soname):
                continue
            if linked.resolved_path is None:
                unresolved.add(linked.soname)
                continue
            if _path_within_dirs(linked.resolved_path, runtime_lib_dirs):
                continue
            external.setdefault(linked.soname, set()).add(linked.resolved_path)

    return unresolved, external


def _validate_qt_assets(bundle_dir: Path) -> None:
    missing_assets = [
        asset for asset in _REQUIRED_QT_ASSETS if not (bundle_dir / asset).is_file()
    ]
    if missing_assets:
        joined = "\n  - ".join(missing_assets)
        raise SystemExit(
            "Missing Qt runtime assets in PyInstaller bundle. "
            "Check packaging/pyinstaller/OpenPlot.spec:\n"
            f"  - {joined}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bundle missing Linux shared libraries for OpenPlot AppImage"
    )
    parser.add_argument(
        "--bundle-dir",
        required=True,
        type=Path,
        help="Path to PyInstaller bundle directory",
    )
    parser.add_argument(
        "--dest-lib-dir", required=True, type=Path, help="Destination library directory"
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Validate that dependencies resolve within the bundle without copying",
    )
    args = parser.parse_args()

    bundle_dir = args.bundle_dir.resolve()
    dest_lib_dir = args.dest_lib_dir.resolve()

    if not bundle_dir.is_dir():
        raise SystemExit(f"Bundle directory not found: {bundle_dir}")

    _validate_qt_assets(bundle_dir)

    raw_search_paths = os.environ.get(
        "OPENPLOT_LIB_SEARCH_PATHS",
        "/lib:/lib64:/usr/lib:/usr/lib64:/lib/x86_64-linux-gnu:/usr/lib/x86_64-linux-gnu:/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu",
    )
    env_paths = []
    for env_key in ("NIX_LD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
        value = os.environ.get(env_key)
        if value:
            env_paths.extend(part for part in value.split(":") if part)

    search_roots = [Path(path) for path in raw_search_paths.split(":") if path]
    search_roots.extend(Path(path) for path in env_paths)
    search_roots = [path for path in search_roots if path.is_dir()]

    ldconfig_map = _discover_ldconfig_entries()
    runtime_lib_dirs = [
        dest_lib_dir.resolve(),
        (bundle_dir / "_internal").resolve(),
        (bundle_dir / "_internal" / "PyQt6" / "Qt6" / "lib").resolve(),
    ]

    targets = [target.resolve() for target in _scan_targets(bundle_dir)]
    if not targets:
        raise SystemExit(f"No scan targets found in bundle: {bundle_dir}")

    scanned_targets = set(targets)
    unresolved: set[str] = set()
    external: dict[str, set[Path]] = {}
    for _ in range(24):
        unresolved, external = _runtime_issues(targets, runtime_lib_dirs)
        if not unresolved and not external:
            return 0
        if args.verify_only:
            break

        progress = False

        for soname in sorted(external):
            candidates = sorted(external[soname], key=str)
            if not candidates:
                continue

            copied = _copy_shared_lib(candidates[0], soname, dest_lib_dir)
            if copied not in scanned_targets:
                scanned_targets.add(copied)
                targets.append(copied)
            progress = True

        for soname in sorted(unresolved):
            if (dest_lib_dir / soname).exists():
                continue

            source = _existing_bundle_match(bundle_dir, soname)
            if source is None:
                source = _resolve_system_lib(
                    soname, ldconfig_map=ldconfig_map, search_roots=search_roots
                )
            if source is None:
                continue

            copied = _copy_shared_lib(source, soname, dest_lib_dir)
            if copied not in scanned_targets:
                scanned_targets.add(copied)
                targets.append(copied)
            progress = True

        if not progress:
            break

    unresolved, external = _runtime_issues(targets, runtime_lib_dirs)

    problems: list[str] = []
    if unresolved:
        unresolved_text = "\n  - ".join(sorted(unresolved))
        problems.append(f"Unresolved shared libraries:\n  - {unresolved_text}")
    if external:
        external_lines: list[str] = []
        for soname in sorted(external):
            for path in sorted(external[soname], key=str):
                external_lines.append(f"{soname} -> {path}")
        problems.append(
            "Libraries resolved outside bundle runtime paths:\n  - "
            + "\n  - ".join(external_lines)
        )

    if args.verify_only:
        raise SystemExit(
            "Runtime library closure check failed:\n" + "\n".join(problems)
        )
    raise SystemExit(
        "Unable to bundle runtime shared libraries:\n" + "\n".join(problems)
    )


if __name__ == "__main__":
    raise SystemExit(main())

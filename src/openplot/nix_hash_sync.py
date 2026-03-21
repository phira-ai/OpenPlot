from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from openplot.release_versioning import _discover_repo_root

HASH_RE = re.compile(r"^sha256-[A-Za-z0-9+/=]+$")
NPM_DEPS_HASH_RE = re.compile(r'(?m)^([ \t]*npmDepsHash = ")(?P<hash>[^"]+)(";)$')


@dataclass(frozen=True)
class SyncResult:
    hash_value: str
    changed: bool


def run_prefetch_npm_deps(package_lock_path: Path) -> str:
    completed = subprocess.run(
        ["nix", "run", "nixpkgs#prefetch-npm-deps", "--", str(package_lock_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or "prefetch-npm-deps failed"
        raise ValueError(stderr)

    hash_value = completed.stdout.strip()
    if HASH_RE.fullmatch(hash_value) is None:
        raise ValueError(f"Malformed nix hash output: {hash_value}")
    return hash_value


def sync_npm_deps_hash(repo_root: Path, *, write: bool) -> SyncResult:
    package_lock_path = repo_root / "frontend" / "package-lock.json"
    flake_path = repo_root / "flake.nix"

    if not flake_path.exists():
        raise ValueError("Missing target file: flake.nix")

    hash_value = run_prefetch_npm_deps(package_lock_path)
    original = flake_path.read_text(encoding="utf-8")
    rewritten, count = NPM_DEPS_HASH_RE.subn(
        lambda match: f"{match.group(1)}{hash_value}{match.group(3)}", original
    )
    if count != 1:
        raise ValueError(
            f"flake.nix replacement count mismatch: expected 1, got {count}"
        )

    changed = rewritten != original
    if write and changed:
        flake_path.write_text(rewritten, encoding="utf-8")
    return SyncResult(hash_value=hash_value, changed=changed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m openplot.nix_hash_sync")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        repo_root = _discover_repo_root()
        result = sync_npm_deps_hash(
            repo_root, write=not args.dry_run and not args.check
        )

        if args.check:
            label = "DRIFT" if result.changed else "OK"
            print(f"{label} {result.hash_value}", file=sys.stdout)
            return 1 if result.changed else 0

        if args.dry_run:
            print(f"DRY_RUN {result.hash_value}", file=sys.stdout)
            return 0

        label = "UPDATED" if result.changed else "OK"
        print(f"{label} {result.hash_value}", file=sys.stdout)
        return 0
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        return 1
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

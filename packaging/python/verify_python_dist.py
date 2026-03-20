from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def _verify_source_static_dir(static_dir: Path) -> int:
    static_dir = static_dir.resolve()
    index_file = static_dir / "index.html"
    assets_dir = static_dir / "assets"

    if not index_file.is_file():
        return _fail(
            f"missing frontend entrypoint: {index_file}; run `npm run build --prefix frontend`"
        )

    if not assets_dir.is_dir():
        return _fail(
            f"missing frontend assets directory: {assets_dir}; run `npm run build --prefix frontend`"
        )

    if not any(assets_dir.iterdir()):
        return _fail(f"frontend assets directory is empty: {assets_dir}")

    print(f"ok: frontend assets present at {static_dir}")
    return 0


def _latest_wheel(dist_dir: Path) -> Path | None:
    wheels = sorted(
        dist_dir.glob("openplot-*.whl"), key=lambda path: path.stat().st_mtime
    )
    if not wheels:
        return None
    return wheels[-1]


def _verify_wheel_contains_frontend(wheel_path: Path) -> int:
    with zipfile.ZipFile(wheel_path) as archive:
        names = set(archive.namelist())

    if "openplot/static/index.html" not in names:
        return _fail(f"wheel is missing openplot/static/index.html: {wheel_path}")

    if not any(name.startswith("openplot/static/assets/") for name in names):
        return _fail(f"wheel is missing openplot/static/assets/* files: {wheel_path}")

    print(f"ok: wheel contains frontend assets: {wheel_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify that OpenPlot frontend assets are present in source and wheel outputs."
    )
    parser.add_argument(
        "--source-static-dir",
        type=Path,
        default=Path("src/openplot/static"),
        help="Path to the built frontend assets directory in source tree.",
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=None,
        help="Optional path to dist directory containing openplot-*.whl.",
    )
    args = parser.parse_args()

    source_status = _verify_source_static_dir(args.source_static_dir)
    if source_status != 0:
        return source_status

    if args.dist_dir is None:
        return 0

    dist_dir = args.dist_dir.resolve()
    if not dist_dir.is_dir():
        return _fail(f"dist directory not found: {dist_dir}")

    wheel_path = _latest_wheel(dist_dir)
    if wheel_path is None:
        return _fail(f"no wheel found matching openplot-*.whl in: {dist_dir}")

    return _verify_wheel_contains_frontend(wheel_path)


if __name__ == "__main__":
    raise SystemExit(main())

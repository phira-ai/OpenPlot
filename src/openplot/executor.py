"""Execute user plot scripts and auto-detect the output file."""

from __future__ import annotations

import contextlib
import hashlib
import json
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .runtime_text import read_python_source, run_text_subprocess

# Image extensions we look for, ordered by preference (SVG first).
IMAGE_EXTENSIONS: list[str] = [".svg", ".png", ".jpg", ".jpeg", ".pdf"]

_INTERNAL_EXECUTE_SCRIPT_OPTION = "--internal-execute-script"
_INTERNAL_WORK_DIR_OPTION = "--internal-work-dir"
_INTERNAL_CAPTURE_DIR_OPTION = "--internal-capture-dir"


@dataclass
class ExecutionResult:
    """Result of running a plot script."""

    success: bool
    plot_path: str | None = None
    plot_type: Literal["svg", "raster"] | None = None
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    duration_s: float = 0.0
    error: str | None = None


def _classify(ext: str) -> Literal["svg", "raster"]:
    return "svg" if ext == ".svg" else "raster"


def _snapshot_images(directory: Path) -> dict[Path, float]:
    """Return {path: mtime} for every image file under *directory*."""
    result: dict[Path, float] = {}
    for root, _dirs, files in os.walk(directory):
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in IMAGE_EXTENSIONS:
                result[p] = p.stat().st_mtime
    return result


def _find_new_or_modified(
    before: dict[Path, float], after: dict[Path, float]
) -> list[Path]:
    """Return image files that are new or have a newer mtime."""
    changed: list[Path] = []
    for p, mtime in after.items():
        if p not in before or mtime > before[p]:
            changed.append(p)
    return changed


def _pick_best(candidates: list[Path]) -> tuple[Path, Literal["svg", "raster"]]:
    """Pick the best candidate output file, preferring SVG."""

    # Sort by extension preference, then by newest mtime (descending)
    def sort_key(p: Path) -> tuple[int, float]:
        try:
            idx = IMAGE_EXTENSIONS.index(p.suffix.lower())
        except ValueError:
            idx = len(IMAGE_EXTENSIONS)
        return (idx, -p.stat().st_mtime)

    candidates.sort(key=sort_key)
    best = candidates[0]
    return best, _classify(best.suffix.lower())


def _restore_changed_images(
    before: dict[Path, float],
    before_bytes: dict[Path, bytes],
    after: dict[Path, float],
    *,
    protected_dirs: list[Path] | None = None,
) -> None:
    """Restore image files in work_dir to their pre-execution state."""

    protected_dirs = protected_dirs or []

    def _is_protected(path: Path) -> bool:
        for root in protected_dirs:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    changed = _find_new_or_modified(before, after)
    for path in changed:
        if _is_protected(path):
            continue
        if path in before:
            original = before_bytes.get(path)
            if original is not None:
                path.write_bytes(original)
        else:
            path.unlink(missing_ok=True)

    for path in before:
        if _is_protected(path):
            continue
        if path not in after:
            original = before_bytes.get(path)
            if original is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(original)


def _unique_destination(base_dir: Path, preferred_name: str) -> Path:
    candidate = base_dir / preferred_name
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    index = 1
    while True:
        attempt = base_dir / f"{stem}_{index}{suffix}"
        if not attempt.exists():
            return attempt
        index += 1


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_protected_paths(paths: list[Path]) -> dict[Path, tuple[bool, str | None]]:
    snapshot: dict[Path, tuple[bool, str | None]] = {}
    for path in paths:
        resolved = path.resolve()
        if resolved.exists() and resolved.is_file():
            snapshot[resolved] = (True, _hash_file(resolved))
        else:
            snapshot[resolved] = (False, None)
    return snapshot


def _set_read_only(paths: list[Path]) -> dict[Path, int]:
    original_modes: dict[Path, int] = {}
    for path in paths:
        resolved = path.resolve()
        if not resolved.exists() or not resolved.is_file():
            continue
        try:
            current_mode = resolved.stat().st_mode
            original_modes[resolved] = current_mode
            resolved.chmod(current_mode & ~0o222)
        except OSError:
            continue
    return original_modes


def _restore_file_modes(modes: dict[Path, int]) -> None:
    for path, mode in modes.items():
        try:
            if path.exists():
                path.chmod(mode)
        except OSError:
            continue


def _detect_mutated_protected_paths(
    before: dict[Path, tuple[bool, str | None]],
) -> list[str]:
    changed: list[str] = []
    for path, (existed_before, digest_before) in before.items():
        exists_after = path.exists()
        if existed_before != exists_after:
            changed.append(str(path))
            continue
        if not exists_after or digest_before is None:
            continue
        try:
            digest_after = _hash_file(path)
        except OSError:
            changed.append(str(path))
            continue
        if digest_after != digest_before:
            changed.append(str(path))
    return changed


def _is_openplot_app_executable(path: Path) -> bool:
    if getattr(sys, "frozen", False):
        try:
            return path.resolve() == Path(sys.executable).resolve()
        except OSError:
            return False
    normalized = str(path).lower()
    return path.name.lower() == "openplot" and ".app/contents/macos/" in normalized


def _next_capture_output_path(capture_dir: Path, preferred_name: str | None) -> Path:
    if preferred_name:
        base_name = Path(str(preferred_name)).name
    else:
        base_name = "openplot_output.svg"

    name, ext = os.path.splitext(base_name)
    if not ext:
        ext = ".png"
        base_name = f"{name}{ext}"

    candidate = capture_dir / base_name
    if not candidate.exists():
        return candidate

    index = 1
    while True:
        attempt = capture_dir / f"{name}_{index}{ext}"
        if not attempt.exists():
            return attempt
        index += 1


def _prepare_matplotlib_runtime(capture_dir: Path) -> Path:
    config_dir = capture_dir / "mplconfig"
    config_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ.setdefault("MPLCONFIGDIR", str(config_dir))
    return config_dir


@contextlib.contextmanager
def _patched_matplotlib_capture(capture_dir: Path):
    _prepare_matplotlib_runtime(capture_dir)

    try:
        import matplotlib.pyplot as plt
        from matplotlib.figure import Figure
    except Exception:
        yield
        return

    original_show = plt.show
    original_plt_savefig = plt.savefig
    original_figure_savefig = Figure.savefig

    def patched_figure_savefig(self, fname=None, *args, **kwargs):
        output_path = _next_capture_output_path(
            capture_dir, str(fname) if fname else None
        )
        return original_figure_savefig(self, str(output_path), *args, **kwargs)

    def patched_savefig(fname=None, *args, **kwargs):
        fig = plt.gcf()
        return patched_figure_savefig(fig, fname, *args, **kwargs)

    def patched_show(*args, **kwargs):
        _ = args, kwargs
        figures = [plt.figure(number) for number in plt.get_fignums()]
        for index, figure in enumerate(figures):
            default_name = (
                f"openplot_show_{index}.svg"
                if len(figures) > 1
                else "openplot_show.svg"
            )
            output_path = _next_capture_output_path(capture_dir, default_name)
            original_figure_savefig(figure, str(output_path), bbox_inches="tight")

    Figure.savefig = patched_figure_savefig
    plt.savefig = patched_savefig
    plt.show = patched_show

    try:
        yield
    finally:
        Figure.savefig = original_figure_savefig
        plt.savefig = original_plt_savefig
        plt.show = original_show


def execute_script_inline(
    script_path: str | Path,
    *,
    work_dir: str | Path | None = None,
    capture_dir: str | Path | None = None,
) -> ExecutionResult:
    script_path = Path(script_path).resolve()
    if not script_path.exists():
        return ExecutionResult(success=False, error=f"Script not found: {script_path}")

    if work_dir is None:
        work_dir = script_path.parent
    work_dir = Path(work_dir).resolve()

    if capture_dir is None:
        capture_dir = Path(tempfile.mkdtemp(prefix="openplot_capture_"))
    capture_dir = Path(capture_dir).resolve()
    capture_dir.mkdir(parents=True, exist_ok=True)

    before = _snapshot_images(work_dir)
    before_bytes = {path: path.read_bytes() for path in before}
    before_capture = _snapshot_images(capture_dir)

    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    return_code = 0

    original_cwd = Path.cwd()
    original_argv = list(sys.argv)
    t0 = time.monotonic()

    try:
        script_source = read_python_source(script_path)
        os.chdir(work_dir)
        sys.argv = [str(script_path)]
        with contextlib.redirect_stdout(stdout_buffer):
            with contextlib.redirect_stderr(stderr_buffer):
                with _patched_matplotlib_capture(capture_dir):
                    exec(
                        compile(script_source, str(script_path), "exec"),
                        {
                            "__name__": "__main__",
                            "__file__": str(script_path),
                        },
                    )
    except Exception:
        return_code = 1
        traceback.print_exc(file=stderr_buffer)
    finally:
        sys.argv = original_argv
        os.chdir(original_cwd)

    duration = time.monotonic() - t0
    stdout_text = stdout_buffer.getvalue()
    stderr_text = stderr_buffer.getvalue()

    after = _snapshot_images(work_dir)
    after_capture = _snapshot_images(capture_dir)

    if return_code != 0:
        _restore_changed_images(
            before,
            before_bytes,
            after,
            protected_dirs=[capture_dir],
        )
        return ExecutionResult(
            success=False,
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=return_code,
            duration_s=duration,
            error=f"Script exited with code {return_code}",
        )

    capture_candidates = _find_new_or_modified(before_capture, after_capture)
    work_candidates = _find_new_or_modified(before, after)

    if capture_candidates:
        candidates = capture_candidates
    else:
        candidates = work_candidates

    if not candidates:
        _restore_changed_images(
            before,
            before_bytes,
            after,
            protected_dirs=[capture_dir],
        )
        return ExecutionResult(
            success=True,
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=0,
            duration_s=duration,
            error="Script ran successfully but no output image was detected.",
        )

    plot_path, plot_type = _pick_best(candidates)

    if plot_path.parent != capture_dir:
        destination = _unique_destination(capture_dir, plot_path.name)
        shutil.copy2(plot_path, destination)
        plot_path = destination

    _restore_changed_images(
        before,
        before_bytes,
        after,
        protected_dirs=[capture_dir],
    )

    return ExecutionResult(
        success=True,
        plot_path=str(plot_path),
        plot_type=plot_type,
        stdout=stdout_text,
        stderr=stderr_text,
        returncode=0,
        duration_s=duration,
    )


def _parse_internal_execution_payload(raw_stdout: str) -> dict[str, object] | None:
    lines = [line.strip() for line in raw_stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("type") != "openplot_internal_script_result":
            continue
        return payload
    return None


# ---------------------------------------------------------------------------
# Matplotlib show() wrapper
# ---------------------------------------------------------------------------

_WRAPPER_TEMPLATE = """\
import os
import sys
import tokenize

_openplot_capture_dir = {capture_dir!r}
os.makedirs(_openplot_capture_dir, exist_ok=True)
_openplot_mpl_config_dir = os.path.join(_openplot_capture_dir, "mplconfig")
os.makedirs(_openplot_mpl_config_dir, exist_ok=True)

# Force a writable non-interactive matplotlib runtime so bundled apps can run
# user scripts without depending on a global font cache location.
os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", _openplot_mpl_config_dir)

def _next_output_path(preferred_name=None):
    if preferred_name:
        base_name = os.path.basename(str(preferred_name))
    else:
        base_name = "openplot_output.svg"

    name, ext = os.path.splitext(base_name)
    if not ext:
        ext = ".png"
        base_name = name + ext

    candidate = os.path.join(_openplot_capture_dir, base_name)
    if not os.path.exists(candidate):
        return candidate

    idx = 1
    while True:
        attempt = os.path.join(_openplot_capture_dir, name + "_" + str(idx) + ext)
        if not os.path.exists(attempt):
            return attempt
        idx += 1

# Monkey-patch plt.show to save the figure instead.
def _patch_matplotlib():
    try:
        import matplotlib.pyplot as plt
        from matplotlib.figure import Figure
    except Exception:
        return

    _original_show = plt.show
    _original_plt_savefig = plt.savefig
    _original_figure_savefig = Figure.savefig

    def _patched_figure_savefig(self, fname=None, *args, **kwargs):
        out_path = _next_output_path(fname)
        return _original_figure_savefig(self, out_path, *args, **kwargs)

    def _patched_savefig(fname=None, *args, **kwargs):
        fig = plt.gcf()
        return _patched_figure_savefig(fig, fname, *args, **kwargs)

    def _patched_show(*args, **kwargs):
        figs = [plt.figure(n) for n in plt.get_fignums()]
        for i, fig in enumerate(figs):
            default_name = f"openplot_show_{{i}}.svg" if len(figs) > 1 else "openplot_show.svg"
            path = _next_output_path(default_name)
            _original_figure_savefig(fig, path, bbox_inches="tight")
        # Don't call _original_show — it would try to display.

    Figure.savefig = _patched_figure_savefig
    plt.savefig = _patched_savefig
    plt.show = _patched_show

_patch_matplotlib()

# Now exec the real script.
_script_path = {script_path!r}
sys.argv = [_script_path]
with tokenize.open(_script_path) as _f:
    _code = _f.read()
exec(compile(_code, _script_path, "exec"), {{"__name__": "__main__", "__file__": _script_path}})
"""


def execute_script(
    script_path: str | Path,
    *,
    timeout: float = 60.0,
    work_dir: str | Path | None = None,
    capture_dir: str | Path | None = None,
    python_executable: str | Path | None = None,
    protected_paths: Sequence[str | Path] | None = None,
) -> ExecutionResult:
    """Run a Python plot script and auto-detect its output image.

    Strategy:
    1. Snapshot image files in the working directory.
    2. Execute the script via a wrapper that patches ``plt.show()``.
    3. Diff the directory for new / modified image files.
    4. Pick the best match (prefer SVG).
    """
    script_path = Path(script_path).resolve()
    if not script_path.exists():
        return ExecutionResult(success=False, error=f"Script not found: {script_path}")

    if work_dir is None:
        work_dir = script_path.parent
    work_dir = Path(work_dir).resolve()

    if capture_dir is None:
        capture_dir = Path(tempfile.mkdtemp(prefix="openplot_capture_"))
    capture_dir = Path(capture_dir).resolve()
    capture_dir.mkdir(parents=True, exist_ok=True)

    before = _snapshot_images(work_dir)
    before_bytes = {path: path.read_bytes() for path in before}
    before_capture = _snapshot_images(capture_dir)
    normalized_protected_paths = [
        Path(item).expanduser().resolve() for item in (protected_paths or [])
    ]
    protected_snapshot = _snapshot_protected_paths(normalized_protected_paths)
    protected_modes = _set_read_only(normalized_protected_paths)

    interpreter_path = (
        Path(python_executable).expanduser()
        if python_executable is not None
        else Path(sys.executable).expanduser()
    )
    if python_executable is None:
        interpreter = str(interpreter_path)
    elif interpreter_path.is_absolute():
        interpreter = str(interpreter_path)
    else:
        interpreter = str((Path.cwd() / interpreter_path).resolve())

    wrapper_file: Path | None = None
    if _is_openplot_app_executable(Path(interpreter)):
        command = [
            interpreter,
            _INTERNAL_EXECUTE_SCRIPT_OPTION,
            str(script_path),
            _INTERNAL_WORK_DIR_OPTION,
            str(work_dir),
            _INTERNAL_CAPTURE_DIR_OPTION,
            str(capture_dir),
        ]
        use_internal_command = True
    else:
        wrapper_code = _WRAPPER_TEMPLATE.format(
            capture_dir=str(capture_dir),
            script_path=str(script_path),
        )
        wrapper_file = Path(tempfile.mktemp(suffix=".py", prefix="openplot_wrap_"))
        wrapper_file.write_text(wrapper_code, encoding="utf-8")
        command = [interpreter, str(wrapper_file)]
        use_internal_command = False

    t0 = time.monotonic()
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        proc = run_text_subprocess(
            command,
            timeout=timeout,
            cwd=str(work_dir),
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(
            success=False,
            error=f"Script timed out after {timeout}s",
            duration_s=timeout,
        )
    except Exception as exc:
        return ExecutionResult(success=False, error=str(exc))
    finally:
        if wrapper_file is not None:
            wrapper_file.unlink(missing_ok=True)
        _restore_file_modes(protected_modes)

    duration = time.monotonic() - t0

    stdout_text = proc.stdout
    stderr_text = proc.stderr
    return_code = proc.returncode

    if use_internal_command:
        internal_payload = _parse_internal_execution_payload(proc.stdout)
        if internal_payload is not None:
            payload_stdout = internal_payload.get("stdout")
            payload_stderr = internal_payload.get("stderr")
            payload_return_code = internal_payload.get("returncode")

            if isinstance(payload_stdout, str):
                stdout_text = payload_stdout
            if isinstance(payload_stderr, str):
                stderr_text = payload_stderr
            if isinstance(payload_return_code, int):
                return_code = payload_return_code

    # Look for new / modified image files.
    after = _snapshot_images(work_dir)
    after_capture = _snapshot_images(capture_dir)
    mutated_protected_paths = _detect_mutated_protected_paths(protected_snapshot)

    if mutated_protected_paths:
        _restore_changed_images(
            before,
            before_bytes,
            after,
            protected_dirs=[capture_dir],
        )
        return ExecutionResult(
            success=False,
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=return_code,
            duration_s=duration,
            error=(
                "Source data files are immutable in plot mode. "
                "The script attempted to change: "
                + ", ".join(mutated_protected_paths[:5])
            ),
        )

    if return_code != 0:
        # Ensure execution does not leave auto-generated plot files in work_dir.
        _restore_changed_images(
            before,
            before_bytes,
            after,
            protected_dirs=[capture_dir],
        )
        return ExecutionResult(
            success=False,
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=return_code,
            duration_s=duration,
            error=f"Script exited with code {return_code}",
        )

    # Prefer files produced in the dedicated capture directory.
    capture_candidates = _find_new_or_modified(before_capture, after_capture)
    work_candidates = _find_new_or_modified(before, after)

    if capture_candidates:
        candidates = capture_candidates
    else:
        candidates = work_candidates

    if not candidates:
        _restore_changed_images(
            before,
            before_bytes,
            after,
            protected_dirs=[capture_dir],
        )
        return ExecutionResult(
            success=True,
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=0,
            duration_s=duration,
            error="Script ran successfully but no output image was detected.",
        )

    plot_path, plot_type = _pick_best(candidates)

    if plot_path.parent != capture_dir:
        destination = _unique_destination(capture_dir, plot_path.name)
        shutil.copy2(plot_path, destination)
        plot_path = destination

    # Ensure execution does not leave auto-generated plot files in work_dir.
    _restore_changed_images(
        before,
        before_bytes,
        after,
        protected_dirs=[capture_dir],
    )

    return ExecutionResult(
        success=True,
        plot_path=str(plot_path),
        plot_type=plot_type,
        stdout=stdout_text,
        stderr=stderr_text,
        returncode=0,
        duration_s=duration,
    )

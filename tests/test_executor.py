from __future__ import annotations

import json
import subprocess
from pathlib import Path

from openplot.executor import _prepare_matplotlib_runtime, execute_script


def test_execute_script_captures_output_outside_workdir(tmp_path: Path) -> None:
    script_path = tmp_path / "plot.py"
    script_path.write_text(
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "plt.figure(figsize=(3, 2))\n"
        "plt.plot([1, 2, 3], [1, 3, 2], color='navy')\n"
        "plt.tight_layout()\n"
        "plt.savefig('plot.png')\n"
    )

    capture_dir = tmp_path / "state" / "runs" / "capture"
    result = execute_script(
        script_path,
        work_dir=tmp_path,
        capture_dir=capture_dir,
    )

    assert result.success
    assert result.plot_path is not None

    output_path = Path(result.plot_path)
    assert output_path.exists()
    assert capture_dir in output_path.parents
    assert not (tmp_path / "plot.png").exists()


def test_execute_script_uses_internal_mode_for_packaged_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    script_path = tmp_path / "plot.py"
    script_path.write_text("print('hello from script')\n")

    app_binary = tmp_path / "OpenPlot.app" / "Contents" / "MacOS" / "OpenPlot"
    app_binary.parent.mkdir(parents=True)
    app_binary.write_text("#!/bin/sh\nexit 0\n")
    app_binary.chmod(0o755)

    seen_command: list[str] = []

    def fake_run(command, **kwargs):
        del kwargs
        nonlocal seen_command
        seen_command = [str(item) for item in command]
        payload = {
            "type": "openplot_internal_script_result",
            "stdout": "captured-stdout",
            "stderr": "captured-stderr",
            "returncode": 0,
        }
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr("openplot.executor.subprocess.run", fake_run)
    monkeypatch.setattr("openplot.executor._snapshot_images", lambda directory: {})
    monkeypatch.setattr(
        "openplot.executor._find_new_or_modified",
        lambda before, after: [],
    )

    result = execute_script(
        script_path,
        work_dir=tmp_path,
        capture_dir=tmp_path / "capture",
        python_executable=app_binary,
    )

    assert len(seen_command) >= 2
    assert seen_command[0] == str(app_binary.resolve())
    assert seen_command[1] == "--internal-execute-script"
    assert result.stdout == "captured-stdout"
    assert result.stderr == "captured-stderr"


def test_prepare_matplotlib_runtime_sets_writable_config_dir(tmp_path: Path) -> None:
    capture_dir = tmp_path / "capture"

    config_dir = _prepare_matplotlib_runtime(capture_dir)

    assert config_dir == capture_dir / "mplconfig"
    assert config_dir.is_dir()

from __future__ import annotations

import subprocess
from pathlib import Path

import openplot.runtime_text as runtime_text


def test_decode_bytes_never_raises_on_undecodable_input() -> None:
    decoded = runtime_text.decode_bytes(b"\x8chello")

    assert isinstance(decoded, str)
    assert "hello" in decoded


def test_read_python_source_honors_declared_encoding(tmp_path: Path) -> None:
    script_path = tmp_path / "latin1-script.py"
    script_path.write_bytes(
        b"# -*- coding: latin-1 -*-\nmessage = 'ol\xe1'\nprint(message)\n"
    )

    source = runtime_text.read_python_source(script_path)

    assert "ol\xe1" in source


def test_run_text_subprocess_decodes_binary_output(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=b"\x8chello",
            stderr=b"\x8cwarning",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runtime_text.run_text_subprocess(["dummy", "command"])

    assert result.returncode == 0
    assert "hello" in result.stdout
    assert "warning" in result.stderr

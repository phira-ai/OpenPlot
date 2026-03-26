from __future__ import annotations

import locale
import subprocess
import tokenize
from pathlib import Path
from typing import Any


def decode_bytes(raw: bytes, *, fallback_encoding: str | None = None) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass

    candidates: list[str] = []
    if fallback_encoding:
        candidates.append(fallback_encoding)

    preferred = locale.getpreferredencoding(False)
    if preferred:
        normalized_preferred = preferred.lower().replace("-", "")
        if normalized_preferred != "utf8" and preferred not in candidates:
            candidates.append(preferred)

    for encoding in candidates:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue

    return raw.decode("utf-8", errors="replace")


def decode_optional_text(
    value: bytes | str | None,
    *,
    fallback_encoding: str | None = None,
) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return decode_bytes(value, fallback_encoding=fallback_encoding)


def read_text_file(path: Path, *, fallback_encoding: str | None = None) -> str:
    return decode_bytes(path.read_bytes(), fallback_encoding=fallback_encoding)


def read_python_source(path: Path) -> str:
    try:
        with tokenize.open(str(path)) as handle:
            return handle.read()
    except (SyntaxError, UnicodeDecodeError, LookupError):
        return read_text_file(path)


def run_text_subprocess(
    command: Any,
    *,
    shell: bool = False,
    fallback_encoding: str | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        shell=shell,
        capture_output=True,
        text=False,
        **kwargs,
    )
    return subprocess.CompletedProcess(
        args=completed.args,
        returncode=completed.returncode,
        stdout=decode_optional_text(
            completed.stdout,
            fallback_encoding=fallback_encoding,
        ),
        stderr=decode_optional_text(
            completed.stderr,
            fallback_encoding=fallback_encoding,
        ),
    )

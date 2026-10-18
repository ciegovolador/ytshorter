"""Smoke test F1: CLI existe, --help y doctor --json no revientan."""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "ytshorter", *args],
        capture_output=True,
        text=True,
        cwd=REPO,
    )


def test_help():
    r = run("--help")
    assert r.returncode == 0
    assert "download" in r.stdout and "pipeline" in r.stdout


def test_doctor_json_runs():
    r = run("--json", "doctor")
    # 0 = entorno OK, 1 = falta GEMINI_API_KEY (aceptable en F1), nunca crash
    assert r.returncode in (0, 1)
    assert "ffmpeg" in r.stdout

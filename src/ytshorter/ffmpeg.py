"""ffmpeg.py — corre un comando ffmpeg reportando % en vivo vía `-progress`.

El % sale de `out_time_ms` contra la duración esperada del clip. Best-effort:
si no hay duración o el progreso no aparece, simplemente espera como antes.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path


def _last_out_ms(path: str) -> int | None:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    ms: int | None = None
    for line in text.splitlines():
        if line.startswith("out_time_ms="):
            try:
                ms = int(line.split("=", 1)[1])
            except ValueError:
                continue
    return ms


def probe_duration(path: str) -> float | None:
    """Duración en segundos vía ffprobe, o None si no se puede leer."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True)
        return float(r.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None


def is_valid_video(path: str, expected_s: float = 0.0) -> bool:
    """True si el archivo abre y su duración cuadra con la esperada (±20%, mín 2s).

    Detecta parciales/corruptos (p.ej. `moov atom not found` por kills) que el
    simple `exists()` daría por buenos y envenenarían el cache.
    """
    dur = probe_duration(path)
    if dur is None or dur < 0.5:
        return False
    if expected_s and expected_s > 0:
        return abs(dur - expected_s) <= max(2.0, 0.2 * expected_s)
    return True


def run_with_progress(cmd: list[str], total_s: float = 0.0,
                      on_tick=None, tick_s: float = 2.0) -> None:
    """Ejecuta ffmpeg; llama `on_tick(frac 0..1)` throttled. Errores como `run(check=True)`."""
    if not total_s or total_s <= 0 or on_tick is None:
        subprocess.run(cmd, check=True)
        if on_tick is not None:
            on_tick(1.0)
        return
    fd, prog = tempfile.mkstemp(prefix="ffprog_", suffix=".txt")
    os.close(fd)
    try:
        cmd2 = [cmd[0], "-progress", prog] + cmd[1:]
        proc = subprocess.Popen(cmd2)
        last = 0.0
        while proc.poll() is None:
            ms = _last_out_ms(prog)
            now = time.time()
            if ms is not None and now - last >= tick_s:
                last = now
                try:
                    on_tick(min(max(ms / 1_000_000 / total_s, 0.0), 0.999))
                except Exception:
                    pass
            time.sleep(0.5)
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd)
        try:
            on_tick(1.0)
        except Exception:
            pass
    finally:
        try:
            Path(prog).unlink()
        except OSError:
            pass

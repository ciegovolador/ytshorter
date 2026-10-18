"""frames.py — muestreo variable de frames para los LLMs multimodales.

analyze/review los usan para vetar encuadre/sujeto/texto en pantalla antes de
decidir; judge los usa como evidencia de auditoría. Cantidad variable: ~1 frame
cada 12s con piso 4 (evidencia mínima) y techo 10 (costo).
"""
from __future__ import annotations

import shutil
import subprocess


def frame_count(duration_s: float, per_s: float = 12.0, lo: int = 4,
                hi: int = 10) -> int:
    """Cantidad variable de frames: ~1 cada `per_s`, acotada a [lo, hi]."""
    if duration_s <= 0:
        return lo
    return max(lo, min(hi, round(duration_s / per_s)))


def probe_duration(video: str) -> float:
    """Duración en segundos; 0.0 si ffprobe falla."""
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", video], capture_output=True, text=True, check=True)
        return max(float(probe.stdout.strip()), 0.0)
    except (subprocess.CalledProcessError, ValueError, OSError):
        return 0.0


def sample_frames(video: str, n: int | None = None, width: int = 480,
                  span: "tuple[float, float] | None" = None) -> list[bytes]:
    """N JPEGs repartidos en [3%, 97%] del clip (incluye el hook).

    `span=(a,b)` limita el muestreo a ese rango absoluto (candidato dentro de
    un video largo); `n=None` → cantidad variable por duración del tramo.
    Devuelve [] si ffmpeg falta, no hay duración, o `n<=0` (tests sin video)."""
    if not shutil.which("ffmpeg") or (n is not None and n <= 0):
        return []
    if span is not None:
        base, dur = float(span[0]), max(float(span[1]) - float(span[0]), 0.0)
    else:
        base, dur = 0.0, probe_duration(video)
    if dur <= 0:
        return []
    if n is None:
        n = frame_count(dur)
    if n == 1:
        positions = [base + dur * 0.5]
    else:
        positions = [base + dur * (0.03 + 0.94 * i / (n - 1)) for i in range(n)]
    out = []
    for t in positions:
        try:
            r = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", video,
                 "-frames:v", "1", "-vf", f"scale={width}:-1",
                 "-f", "mjpeg", "-"], capture_output=True, check=True)
            if r.stdout:
                out.append(r.stdout)
        except (subprocess.CalledProcessError, OSError):
            continue
    return out

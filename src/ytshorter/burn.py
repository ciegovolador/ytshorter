"""burn.py — quemado de captions en video.mp4 + thumbnail.jpg (ffmpeg).

Cache por hash del .ass (no por mtime: el ass recién escrito siempre sería
"más nuevo"): si el quemado no corresponde a ESTE ass, se rehace.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def _ass_vf(ass_path: Path) -> str:
    # filtro ass= necesita ':' y "'" escapados; en Windows además el path usa
    # backslashes, que el parser de filtros interpreta como escape.
    esc = str(ass_path).replace("\\", "/").replace(":", "\\:")
    esc = esc.replace("'", "\\'\"'\\''")
    return f"ass='{esc}'"


def burn_and_thumb(cdir: Path, force: bool = False, total_s: float = 0.0,
                   on_tick=None) -> dict:
    from .ffmpeg import is_valid_video, run_with_progress

    cut = cdir / "cut.mp4"
    final = cdir / "video.mp4"
    ass_path = cdir / "subtitles.ass"
    burn_hash = cdir / "burn.hash"
    ass_bytes = ass_path.read_bytes() if ass_path.exists() else b""
    digest = hashlib.sha256(ass_bytes).hexdigest()
    if final.exists() and not force:
        # El .ass se regenera siempre: el quemado solo vale si se hizo con
        # ESTE ass (hash) y el video abre. Si no, re-quemar (no basta mtime:
        # el ass recién escrito siempre sería "más nuevo").
        if (burn_hash.exists() and burn_hash.read_text(encoding="utf-8").strip() == digest
                and is_valid_video(str(final), total_s)):
            return {"id": cdir.name, "video": str(final), "cached": True}
        final.unlink()  # quemado rancio o inválido: no envenenar el cache
    if not is_valid_video(str(cut), total_s):
        return {"id": cdir.name, "video": "", "cached": False,
                "error": f"cut inválido {cut} (re-corre clip)"}
    has_subs = ass_path.exists() and "Dialogue: 0," in ass_path.read_text(encoding="utf-8")
    if has_subs:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(cut),
               "-vf", _ass_vf(ass_path),
               "-c:v", "libx264", "-preset", "fast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-c:a", "copy",
               "-movflags", "+faststart", str(final)]
    else:  # sin subtítulos: no re-encodear, solo renombrar vía copia
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(cut),
               "-c", "copy", "-movflags", "+faststart", str(final)]
    run_with_progress(cmd, total_s, on_tick=on_tick)
    # thumbnail en la mitad del clip final
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(final)], capture_output=True, text=True, check=True)
    mid = max(0.5, float(probe.stdout.strip()) / 2)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{mid:.2f}",
                    "-i", str(final), "-frames:v", "1",
                    str(cdir / "thumbnail.jpg")], check=True)
    burn_hash.write_text(digest, encoding="utf-8")
    return {"id": cdir.name, "video": str(final), "cached": False}



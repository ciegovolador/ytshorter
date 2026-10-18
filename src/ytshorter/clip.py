"""clip.py (F4) — corta cada clip de clips.json a workdir/short_XX/cut.mp4 (9:16, h264)."""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .ffmpeg import is_valid_video, run_with_progress
from .reframe import VERTICAL_VF


def prune_short_dirs(workdir: str, keep: "set[str] | None" = None) -> list[str]:
    """Poda workdir/short_XX que ya no están en clips.json (ids vigentes).

    Sin clips.json no borra nada (un workdir sin plan no se toca). Se usa en
    pipeline antes de caption/judge (los dirs viejos de un run anterior no
    deben auditarse) y en package para el dist. Devuelve los ids podados."""
    wd = Path(workdir)
    if not wd.is_dir():
        return []
    if keep is None:
        try:
            keep = {c["id"] for c in
                    json.loads((wd / "clips.json").read_text(encoding="utf-8"))
                    .get("clips", []) if c.get("id")}
        except (OSError, ValueError):
            return []
    removed = []
    for d in sorted(wd.iterdir()):
        if d.is_dir() and d.name.startswith("short_") and d.name not in keep:
            shutil.rmtree(d)
            removed.append(d.name)
    return removed


def build_cut_cmd(source: Path, start: float, end: float, out: Path,
                  vf: str | None = None) -> list[str]:
    from .reframe import VERTICAL_VF

    return [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(source),
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
        "-vf", vf or VERTICAL_VF,
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-movflags", "+faststart",
        str(out),
    ]


def cut_all(workdir: str, force: bool = False, on_item=None, on_tick=None) -> dict:
    wd = Path(workdir)
    clips_path = wd / "clips.json"
    source = wd / "source.mp4"
    if not clips_path.exists():
        return {"ok": False, "error": f"falta {clips_path} (corre analyze primero)"}
    if not source.exists():
        return {"ok": False, "error": f"falta {source}"}

    clips = json.loads(clips_path.read_text()).get("clips", [])
    total = len(clips)
    done, cached = [], 0
    for i, c in enumerate(clips):
        cid = c.get("id") or f"short_{len(done) + 1:02d}"
        cdir = wd / cid
        cdir.mkdir(exist_ok=True)
        cut = cdir / "cut.mp4"
        dur = max(float(c["end"]) - float(c["start"]), 0.0)
        start, end = float(c["start"]), float(c["end"])
        if cut.exists() and not force and is_valid_video(str(cut), dur):
            cached += 1
            done.append({"id": cid, "cut": str(cut), "cached": True})
            if on_item:
                on_item(i + 1, total, cid, True)
            continue
        if cut.exists() and not force:
            print(f"[clip] {cid}: cut.mp4 inválido (trunco?), re-generando", file=sys.stderr)
            cut.unlink()
        from .reframe import choose_crop

        vf, framing = choose_crop(str(source), start, end)
        (cdir / "reframe.json").write_text(
            json.dumps(framing, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[clip] {cid}: crop x={framing.get('x', '?')} ({framing.get('reason', '?')})",
              file=sys.stderr)
        cmd = build_cut_cmd(source, start, end, cut, vf)
        (cdir / "ffmpeg_cmd.sh").write_text(
            "#!/bin/sh\n# generado por ytshorter clip (reproducible)\n"
            + " ".join(shlex.quote(x) for x in cmd) + "\n")
        try:
            run_with_progress(cmd, dur, on_tick=on_tick)
        except subprocess.CalledProcessError as e:
            cut.unlink(missing_ok=True)  # no dejar parcial que envenene el cache
            return {"ok": False, "error": f"ffmpeg {cid}: {e}"}
        done.append({"id": cid, "cut": str(cut), "cached": False})
        if on_item:
            on_item(i + 1, total, cid, False)
    try:  # framing → clips.json → metadata.json (señal para editor/QA)
        data = json.loads(clips_path.read_text())
        by_id = {c.get("id"): c for c in data.get("clips", [])}
        for d in done:
            rf = wd / d["id"] / "reframe.json"
            if rf.exists() and d["id"] in by_id:
                by_id[d["id"]]["framing"] = json.loads(rf.read_text())
        clips_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except (OSError, ValueError):
        pass
    return {"ok": True, "cuts": done, "cached_n": cached}

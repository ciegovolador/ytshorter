"""package.py (F5) — arma dist/<video_id>/short_XX/ lista para subir. Solo copia+escribe, sin re-encode."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

COPY_FILES = ("video.mp4", "subtitles.srt", "subtitles.ass", "thumbnail.jpg", "ffmpeg_cmd.sh")


def package_workdir(workdir: str, out_root: str = "dist", force: bool = False) -> dict:
    wd = Path(workdir)
    clips_path = wd / "clips.json"
    if not clips_path.exists():
        return {"ok": False, "error": f"falta {clips_path}"}
    data = json.loads(clips_path.read_text())
    clips = data.get("clips", [])
    if not clips:
        return {"ok": False, "error": "clips.json sin clips"}
    video_id = data.get("video_id", wd.name)

    dest_root = Path(out_root) / video_id
    manifest = dest_root / "manifest.json"
    if manifest.exists() and not force:
        m = json.loads(manifest.read_text())
        return {"ok": True, "cached": True, "out": str(dest_root), "n": len(m.get("shorts", []))}

    shorts = []
    for c in clips:
        cid = c.get("id") or f"short_{len(shorts) + 1:02d}"
        src = wd / cid
        final_video = src / "video.mp4"
        if not final_video.exists():
            return {"ok": False, "error": f"falta {final_video} (corre caption primero)"}
        d = dest_root / cid
        d.mkdir(parents=True, exist_ok=True)
        for f in COPY_FILES:
            s = src / f
            if s.exists():
                shutil.copy2(s, d / f)
        (d / "title.txt").write_text((c.get("title") or cid) + "\n", encoding="utf-8")
        (d / "description.txt").write_text((c.get("description") or "") + "\n", encoding="utf-8")
        (d / "tags.txt").write_text("\n".join(c.get("tags") or []) + "\n", encoding="utf-8")
        meta = {"video_id": video_id, "prompts_version": data.get("prompts_version", "?"),
                "model": data.get("model", "?"), **c}
        (d / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
        shorts.append({"id": cid, "dir": str(d), "title": c.get("title", ""),
                       "duration": c.get("duration", 0), "score": c.get("score", 0)})

    manifest.write_text(json.dumps(
        {"video_id": video_id, "n": len(shorts), "shorts": shorts},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "cached": False, "out": str(dest_root), "n": len(shorts)}

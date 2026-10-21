"""web.py (F6) — FastAPI mínima. No procesa video: solo encola y reporta. POC."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import __version__


def _static_dir() -> Path:
    import os
    import sys

    override = os.getenv("YT_SHORTER_WEB_STATIC", "")
    if override:
        return Path(override)
    candidates = [
        Path(__file__).resolve().parents[2] / "web" / "static",
        Path(sys.executable).resolve().parent / "web" / "static",
        Path("/app/web/static"),
        Path.cwd() / "web" / "static",
    ]
    meipass = getattr(sys, "_MEIPASS", "")  # PyInstaller (Windows exe)
    if meipass:
        candidates.insert(0, Path(meipass) / "web" / "static")
    for c in candidates:
        if (c / "index.html").exists():
            return c
    return candidates[0]


STATIC = _static_dir()

app = FastAPI(title=f"ytshorter POC v{__version__}")


class JobIn(BaseModel):
    url: str


def _roots() -> tuple[str, str]:
    import os

    return os.getenv("YT_SHORTER_OUT", "dist"), os.getenv("YT_SHORTER_WORK", "work")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/version")
def version():
    from .pipeline import STAGES

    return {"version": __version__, "stages": len(STAGES)}


@app.post("/api/jobs")
def post_job(body: JobIn):
    from .queue import create_job

    out_root, work_root = _roots()
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(400, "url debe empezar con http(s)://")
    return create_job(body.url, out_root=out_root, work_root=work_root)


@app.get("/api/jobs")
def get_jobs():
    from .queue import list_jobs

    _, work_root = _roots()
    return {"jobs": list_jobs(work_root)}


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    from .queue import get_job as _get

    _, work_root = _roots()
    job = _get(jid, work_root)
    if job is None:
        raise HTTPException(404, "job no existe")
    return job

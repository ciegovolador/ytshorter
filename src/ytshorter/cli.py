"""CLI ytshorter — un subcomando = una cosa (UNIX). Solo parsea args y delega."""
from __future__ import annotations

import argparse
import json
import sys


def _not_implemented(name: str) -> int:
    print(json.dumps({"ok": False, "stage": name, "error": "no implementado aún (ver PLAN.md)"}))
    return 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ytshorter", description="YouTube largo -> carpeta de shorts")
    p.add_argument("--json", action="store_true", help="salida JSON en stdout")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download", help="descarga video+audio con yt-dlp")
    d.add_argument("url")
    d.add_argument("-o", "--out", default="work")
    d.add_argument("--force", action="store_true")

    t = sub.add_parser("transcribe", help="transcribe a transcript.json")
    t.add_argument("input", help="work/<id>/ (o source.mp4; se usa su carpeta)")
    t.add_argument("--use-yt-subs-first", action="store_true", default=True)
    t.add_argument("--no-yt-subs", action="store_true", help="fuerza whisper local")
    t.add_argument("--whisper-model", default=None)
    t.add_argument("--force", action="store_true")

    a = sub.add_parser("analyze", help="LLM elige clips -> clips.json")
    a.add_argument("transcript", help="work/<id>/ (o transcript.json; se usa su carpeta)")
    a.add_argument("--prompts", default="v1")
    a.add_argument("--min-score", type=int, default=70)
    a.add_argument("--max-clips", type=int, default=20)
    a.add_argument("--force", action="store_true")

    c = sub.add_parser("clip", help="corta+reframes con ffmpeg")
    c.add_argument("workdir", help="work/<id>/ con source.mp4 + clips.json")
    c.add_argument("--force", action="store_true")

    s = sub.add_parser("caption", help="genera .srt/.ass y quema subtítulos")
    s.add_argument("workdir", help="work/<id>/ con short_XX/cut.mp4")
    s.add_argument("--force", action="store_true")

    k = sub.add_parser("package", help="arma carpeta upload-ready")
    k.add_argument("workdir")
    k.add_argument("--out", default="dist")
    k.add_argument("--force", action="store_true")

    pl = sub.add_parser("pipeline", help="orquesta todo: URL -> carpeta shorts")
    pl.add_argument("url")
    pl.add_argument("-o", "--out", default="dist")
    pl.add_argument("-w", "--work", default="work")
    pl.add_argument("--job-id", default="")
    pl.add_argument("--force", action="store_true")

    sub.add_parser("doctor", help="chequea entorno")
    j = sub.add_parser("jobs", help="lista trabajos background")
    j.add_argument("--watch", action="store_true")

    jd = sub.add_parser("judge", help="LLM-as-judge sobre shorts terminados")
    jd.add_argument("input", help="dist/<video_id>/ o short_XX/")
    jd.add_argument("--frames", type=int, default=3)

    sv = sub.add_parser("serve", help="web POC mínima")
    sv.add_argument("--port", type=int, default=8000)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "doctor":
        from .doctor import run_doctor

        return run_doctor(as_json=args.json)
    if args.cmd == "download":
        from .download import download_url

        res = download_url(args.url, out_root=args.out, force=args.force)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res.get("ok") else 2
    if args.cmd == "transcribe":
        from pathlib import Path

        from .config import load_settings
        from .transcribe import transcribe_workdir

        p = Path(args.input)
        workdir = str(p if p.is_dir() else p.parent)
        settings = load_settings()
        res = transcribe_workdir(
            workdir,
            whisper_model=args.whisper_model or settings.whisper_model,
            use_yt_subs_first=(not args.no_yt_subs),
            force=args.force,
        )
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res.get("ok") else 2
    if args.cmd == "analyze":
        from pathlib import Path

        from .analyze import analyze_workdir

        p = Path(args.transcript)
        workdir = str(p if p.is_dir() else p.parent)
        res = analyze_workdir(workdir, prompts_version=args.prompts,
                              min_score=args.min_score, max_clips=args.max_clips,
                              force=args.force)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res.get("ok") else 2
    if args.cmd == "clip":
        from .clip import cut_all

        res = cut_all(args.workdir, force=args.force)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res.get("ok") else 2
    if args.cmd == "caption":
        from .caption import caption_all

        res = caption_all(args.workdir, force=args.force)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res.get("ok") else 2
    if args.cmd == "package":
        from .package import package_workdir

        res = package_workdir(args.workdir, out_root=args.out, force=args.force)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res.get("ok") else 2
    if args.cmd == "pipeline":
        from .pipeline import run_pipeline

        res = run_pipeline(args.url, out_root=args.out, work_root=args.work,
                           job_id=args.job_id, force=args.force)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res.get("ok") else 2
    if args.cmd == "jobs":
        import time as _time

        from .queue import list_jobs

        from .config import load_settings

        def _line(j: dict) -> str:
            p = j.get("progress") or {}
            if not p:
                return f"{j['id']}  {j['status']:8s}  {j.get('out') or j['url']}"
            eta = p.get("eta_s")
            src = p.get("eta_source", "")
            eta_s = f" eta~{eta:.0f}s({src})" if isinstance(eta, (int, float)) else ""
            times = p.get("stage_times") or {}
            detail = ""
            if times:
                detail = " [" + " ".join(f"{k[:4]}:{v:.0f}s" for k, v in times.items()) + "]"
            cur = f" +{p.get('stage_elapsed_s', 0):.0f}s@{p.get('stage')}" if j["status"] == "running" else ""
            sub = ""
            if p.get("sub_total"):
                pct = p.get("sub_pct")
                pct_s = f" {pct * 100:.0f}%" if isinstance(pct, (int, float)) else ""
                sub = (f" · {p.get('substage')} {p.get('sub_idx')}/{p.get('sub_total')}"
                       f"{pct_s} +{p.get('sub_elapsed_s', 0):.0f}s")
            return (f"{j['id']}  {j['status']:8s} {p.get('stage')} "
                    f"{p.get('stage_idx')}/{p.get('total_stages')} {p.get('elapsed_s', 0):.0f}s"
                    f"{eta_s}{cur}{sub}{detail}  {j.get('out') or j['url']}")

        if args.json:
            print(json.dumps({"jobs": list_jobs(load_settings().work_dir)},
                             ensure_ascii=False, indent=1))
            return 0
        if not args.watch:
            for j in list_jobs(load_settings().work_dir):
                print(_line(j))
            return 0
        seen: set[str] = set()
        while True:
            jobs = list_jobs(load_settings().work_dir)
            for j in jobs:
                key = j["id"] + j["status"] + str((j.get("progress") or {}).get("stage_idx"))
                if key not in seen:
                    print(_line(j))
                    seen.add(key)
            if not any(j["status"] == "running" for j in jobs):
                break
            _time.sleep(2)
        return 0
    if args.cmd == "judge":
        from pathlib import Path as _P

        from .config import load_settings as _ls
        from .judge import judge_short, judge_video

        settings = _ls()
        if not settings.llm_configured():
            print(json.dumps({"ok": False, "error": "falta GEMINI_API_KEY en entorno"}))
            return 2
        target = _P(args.input)
        if (target / "video.mp4").exists():
            res = {"ok": True,
                   "shorts": [judge_short(str(target), settings.gemini_model,
                                          settings.gemini_api_key, args.frames)]}
            res["n"] = 1
            res["ships"] = sum(1 for s in res["shorts"] if s["ship"] and s["score"] >= 0)
        else:
            res = {"ok": True, **judge_video(str(target), settings.gemini_model,
                                             settings.gemini_api_key, args.frames)}
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "serve":
        import uvicorn

        from .web import app

        uvicorn.run(app, host="0.0.0.0", port=args.port)
        return 0
    return _not_implemented(args.cmd)


if __name__ == "__main__":
    sys.exit(main())

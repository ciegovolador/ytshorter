"""judge.py — LLM-as-judge independiente sobre shorts terminados.

Segunda opinión multimodal (frames + título + captions + framing): no decide
qué producir (eso es analyze+review), audita lo producido. Asesor, no puerta:
escribe `judgment.json` por short, jamás borra nada.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

JUDGE_VERSION = "v1"

JUDGE_SYSTEM = """Rol: juez independiente de shorts verticales (segunda instancia).
No editaste ni elegiste estos clips: los auditas con ojos frescos.

Responde SOLO JSON válido: {"score": 0-100, "ship": true|false,
"issues": ["..."], "notes": "..."}.

Rúbrica (resta por cada fallo):
- Hook (30): ¿los primeros 3s atrapan? ¿título/hook autocontenido?
- Encuadre (25): ¿rostro completo y centrado en su tercio? Si habla de algo
  en pantalla (mapa, tabla, flechas), ¿SE VE? Cara cortada o gráfico ausente = fallo.
- Captions (20): ¿legibles, sincronizados, sin líneas que empiecen en coma ni
  palabras colgadas? Bloques cortos (1-2 líneas).
- Cierre (15): ¿termina en idea cerrada, no en muletilla ni corte seco?
- Audio/visual (10): ¿thumbnail y frames coherentes con el título?

`ship: true` solo si score >= 70 Y ningún issue bloqueante (cara cortada,
gráfico referenciado invisible, hook incomprensible). Sé estricto: mejor
marcar que aprobar basura. `issues` corto (máx 3), `notes` 1-2 líneas."""


def extract_frames(video: str, n: int = 3, width: int = 480) -> list[bytes]:
    """N JPEGs repartidos del clip. Vacío si ffmpeg falla."""
    import shutil

    if not shutil.which("ffmpeg"):
        return []
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", video], capture_output=True, text=True, check=True)
        dur = max(float(probe.stdout.strip()), 1.0)
    except (subprocess.CalledProcessError, ValueError, OSError):
        return []
    out = []
    for i in range(1, n + 1):
        t = dur * i / (n + 1)
        try:
            r = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.1f}", "-i", video,
                 "-frames:v", "1", "-vf", f"scale={width}:-1",
                 "-f", "mjpeg", "-"], capture_output=True, check=True)
            if r.stdout:
                out.append(r.stdout)
        except (subprocess.CalledProcessError, OSError):
            continue
    return out


def caption_stats(srt_path: str) -> dict:
    """Bloques, CPS pico y líneas largas del .srt (lo que el juez 'lee')."""
    try:
        text = Path(srt_path).read_text(encoding="utf-8")
    except OSError:
        return {"blocks": 0, "max_cps": 0.0, "long_lines": 0}
    blocks, max_cps, long_lines = 0, 0.0, 0
    for block in text.strip().split("\n\n"):
        parts = block.splitlines()
        if len(parts) < 3 or "-->" not in parts[1]:
            continue
        times, body = parts[1], [l for l in parts[2:] if l.strip()]
        if not body:
            continue
        try:
            a, b = times.split(" --> ")
            def ts(t):
                h, m, s = t.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s.replace(",", "."))
            dur = max(ts(b) - ts(a), 0.01)
            chars = sum(len(l) for l in body)
            max_cps = max(max_cps, chars / dur)
            blocks += 1
            long_lines += sum(1 for l in body if len(l) > 42)
        except (ValueError, IndexError):
            continue
    return {"blocks": blocks, "max_cps": round(max_cps, 1), "long_lines": long_lines}


def judge_call(system: str, user: str, images: list[bytes],
               model: str, api_key: str) -> dict:
    """Gemini con imágenes (bytes JPEG). Sin imágenes → solo texto."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    parts: list = [user]
    for img in images:
        try:
            parts.append(types.Part.from_bytes(data=img, mime_type="image/jpeg"))
        except Exception:
            continue
    resp = client.models.generate_content(
        model=model,
        contents=parts,
        config=types.GenerateContentConfig(
            system_instruction=system, response_mime_type="application/json"),
    )
    text = (resp.text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def judge_short(sdir: str, model: str, api_key: str, n_frames: int = 3) -> dict:
    """Audita un short_XX/ terminado. Escribe judgment.json. Nunca borra."""
    d = Path(sdir)
    meta = {}
    try:
        meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    title = (d / "title.txt").read_text(encoding="utf-8").strip() if (d / "title.txt").exists() else meta.get("title", "")
    desc = (d / "description.txt").read_text(encoding="utf-8").strip()[:500] if (d / "description.txt").exists() else ""
    stats = caption_stats(str(d / "subtitles.srt"))
    framing = meta.get("framing", {})
    user = (f"Título: {title}\nDescripción: {desc}\n"
            f"Duración: {meta.get('duration', '?')}s | score editor: {meta.get('score', '?')}\n"
            f"Encuadre elegido: {framing.get('reason', '?')} (x={framing.get('x', '?')})\n"
            f"Captions: {stats['blocks']} bloques, CPS pico {stats['max_cps']}, "
            f"líneas >42 chars: {stats['long_lines']}\n"
            f"Hook: {meta.get('hook_text', '')}\n"
            f"Juzga con la rúbrica. Adjunto {n_frames} frames (inicio/medio/fin).")
    images = extract_frames(str(d / "video.mp4"), n=n_frames)
    try:
        verdict = judge_call(JUDGE_SYSTEM, user, images, model, api_key)
        verdict = {"ship": bool(verdict.get("ship", False)),
                   "score": int(verdict.get("score", 0)),
                   "issues": list(verdict.get("issues", []))[:3],
                   "notes": str(verdict.get("notes", ""))[:300],
                   "judge": JUDGE_VERSION, "model": model,
                   "frames": len(images)}
    except Exception as e:  # noqa: BLE001 — el juez nunca rompe nada
        verdict = {"ship": True, "score": -1, "issues": [],
                   "notes": f"juez no disponible: {str(e)[:150]}",
                   "judge": JUDGE_VERSION, "model": model, "frames": len(images)}
    (d / "judgment.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    return {"id": d.name, **verdict}


def judge_video(vdir: str, model: str, api_key: str, n_frames: int = 3) -> dict:
    """Audita dist/<video_id>/ entero. Devuelve resumen."""
    shorts = sorted(p for p in Path(vdir).iterdir()
                    if p.is_dir() and (p / "video.mp4").exists())
    results = [judge_short(str(s), model, api_key, n_frames) for s in shorts]
    ships = sum(1 for r in results if r["ship"] and r["score"] >= 0)
    return {"video": Path(vdir).name, "n": len(results), "ships": ships,
            "shorts": results}

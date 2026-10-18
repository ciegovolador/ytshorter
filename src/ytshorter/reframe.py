"""reframe.py (F4) — crop 9:16 guiado por contenido (rostro / gráficos / textura).

V1 era crop-center: cortaba media cara (short_13) y dejaba fuera los gráficos
de los que habla el presentador (short_20, flechas rojas en x≈900/1280).

Sin dependencias nuevas pesadas (solo numpy): muestrea frames pequeños,
combina máscara de piel + saturación + bordes por columna y elige la ventana
9:16 con más información, con leve prior al centro. Un crop estático por clip
(evita mareo). Fallback a centro si algo falla.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

OUT_W, OUT_H = 1080, 1920

# V1 legacy (fallback y fuentes verticales): centro.
VERTICAL_VF = "crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)',scale=1080:1920,setsar=1"

# Contenido distribuido (gráfico/texto a lo ancho): en vez de recortar y dejar
# cosas afuera, se muestra el frame COMPLETO a lo ancho sobre fondo cover
# (zoom-crop, sin estirar) desenfocado y oscurecido. El blur corre sobre una
# miniatura 270x480 (~16× menos píxeles): mismo look, ~10× más barato que
# boxblur a 1080x1920 (que costaba 5-8 min/clip).
# Garantía dura: nada referenciado queda fuera de cuadro.
CONTAIN_VF = ("split[a][b];[a]scale=270:480:force_original_aspect_ratio=increase,"
              "crop=270:480,gblur=sigma=12,scale=1080:1920,"
              "eq=brightness=-0.12:saturation=0.85[bg];"
              "[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")

SAMPLE_W = 320
SAMPLE_H = 180
SAMPLE_FPS = 0.5
MAX_FRAMES = 24
CENTER_BIAS = 0.10  # prioriza centro salvo contenido claramente lateral
FACE_MIN_FRAC = 0.03  # cara <3% del frame = público, no sujeto → mandan gráficos
FACE_HIT_RATIO = 0.3
COVERAGE_MIN = 0.55  # si la ventana 9:16 cubre <55% de la saliencia → contain


def _sample_frames(source: str, start: float, end: float) -> "list":
    """Frames RGB pequeños del rango vía ffmpeg. Lista de arrays (H,W,3)."""
    import numpy as np

    dur = max(end - start, 0.5)
    nfps = min(SAMPLE_FPS, MAX_FRAMES / dur)
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-to", f"{end:.2f}",
           "-i", source, "-vf", f"fps={nfps:.3f},scale={SAMPLE_W}:{SAMPLE_H}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    r = subprocess.run(cmd, capture_output=True, check=True)
    raw, w, h = r.stdout, SAMPLE_W, SAMPLE_H
    if not raw or len(raw) % (w * h * 3) != 0:
        return []
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, h, w, 3)
    return [f.astype(float) for f in frames[:MAX_FRAMES]]


def _detect_faces(frames: "list") -> "list":
    """Cajas (cx, frac) con Haar frontal. [] sin cv2, sin cascade o sin caras."""
    try:
        import cv2
    except ImportError:
        return []
    try:
        fc = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if fc.empty():
            return []
    except Exception:
        return []
    hits = []
    for f in frames:
        gray = f.mean(axis=2).astype("uint8")
        for (x, y, w, h) in fc.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30)):
            hits.append(((x + w / 2) / f.shape[1], (w * h) / f.size))
    return hits


def _column_scores(frames: "list") -> "tuple":
    """Saliencia por columna (0..1): piel 40% + rojo 25% + saturación 20% + bordes 15%.

    Devuelve (score, skin_col, red_col). La piel aproxima rostros; el rojo caza
    gráficos de alerta (flechas); la saturación, colorido; los bordes, texto.
    """
    import numpy as np

    agg, skin_agg, red_agg, n = None, None, None, 0
    for f in frames:
        R, G, B = f[:, :, 0], f[:, :, 1], f[:, :, 2]
        mx, mn = f.max(axis=2), f.min(axis=2)
        sat = (mx - mn) / 255.0
        skin = ((R > 95) & (G > 40) & (B > 20) & (R > G) & (R > B)
                & ((R - G) > 15) & (sat < 0.4))  # sat gate: el rojo puro no es piel
        red = (R > 150) & (R > 1.5 * G) & (R > 1.5 * B)  # gráficos de alerta
        gray = f.mean(axis=2)
        edge = np.abs(np.diff(gray, axis=1))
        edge = np.pad(edge, ((0, 0), (0, 1)))
        def norm(v):
            v = v.mean(axis=0)
            m = v.max()
            return v / m if m > 0 else v
        col = (0.40 * norm(skin.astype(float)) + 0.25 * norm(red.astype(float))
               + 0.20 * norm(sat) + 0.15 * norm(edge))
        scol = skin.astype(float).mean(axis=0)
        rcol = red.astype(float).mean(axis=0)
        agg = col if agg is None else agg + col
        skin_agg = scol if skin_agg is None else skin_agg + scol
        red_agg = rcol if red_agg is None else red_agg + rcol
        n += 1
    agg, skin_agg, red_agg = agg / n, skin_agg / n, red_agg / n
    return agg, skin_agg, red_agg


def _probe_wh(source: str) -> "tuple[int, int]":
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", source],
        capture_output=True, text=True, check=True)
    w, h = r.stdout.strip().split(",")[:2]
    return int(w), int(h)


def _window_at(cx_full: float, iw: int, ww: int) -> "tuple[str, dict]":
    x_full = min(max(round(cx_full - ww / 2), 0), iw - ww)
    x_full -= x_full % 2  # crop par (yuv420p)
    cx = (x_full + ww / 2) / iw
    side = "izquierda" if cx < 0.38 else ("derecha" if cx > 0.62 else "centro")
    return x_full, cx, side


def choose_crop(source: str, start: float, end: float) -> "tuple[str, dict]":
    """Devuelve (filtro_vf, info). info → reframe.json + metadata (editor/QA).

    Prioridad: 1) rostro grande (Haar) → ventana sobre la cara; 2) gráfico de
    alerta concentrado (rojo) → ventana sobre el gráfico; 3) saliencia general.
    """
    import numpy as np

    try:
        iw, ih = _probe_wh(source)
    except (subprocess.CalledProcessError, ValueError, OSError):
        return VERTICAL_VF, {"mode": "center", "reason": "sin ffprobe"}
    ww = min(iw, round(ih * 9 / 16))
    if ww >= iw:  # fuente vertical/angosta: no hay de dónde elegir
        return VERTICAL_VF, {"mode": "center", "reason": "fuente angosta"}
    try:
        frames = _sample_frames(source, start, end)
        if not frames:
            raise ValueError("sin frames")
        W = frames[0].shape[1]

        hits = _detect_faces(frames)
        if len(hits) >= max(2, int(len(frames) * FACE_HIT_RATIO)):
            big = [cx for cx, frac in hits if frac >= FACE_MIN_FRAC]
            if big:
                face_cx = float(np.median(big))
                x_full, cx, side = _window_at(face_cx * iw, iw, ww)
                vf = f"crop=w={ww}:h={ih}:x={x_full}:y=0,scale=1080:1920,setsar=1"
                return vf, {"mode": "smart", "reason": f"rostro a la {side}"
                            if side != "centro" else "rostro centrado",
                            "x": x_full, "w": ww, "cx": round(cx, 3),
                            "face_cx": round(face_cx, 3),
                            "face_frac": round(float(np.median(
                                [f for _, f in hits])), 4)}

        score, skin, red = _column_scores(frames)
        red_mass, red_xs = red.sum(), np.where(red > red.max() * 0.5)[0]
        if red_mass > 0.005 * W and len(red_xs) and (red_xs.max() - red_xs.min()) < 0.25 * W:
            gx = float(np.median(red_xs)) / W
            x_full, cx, side = _window_at(gx * iw, iw, ww)
            vf = f"crop=w={ww}:h={ih}:x={x_full}:y=0,scale=1080:1920,setsar=1"
            return vf, {"mode": "smart",
                        "reason": f"gráfico a la {side}" if side != "centro" else "gráfico centrado",
                        "x": x_full, "w": ww, "cx": round(cx, 3),
                        "graphic_cx": round(gx, 3)}

        wwin = max(round(W * ww / iw), 8)
        xs = np.arange(0, W - wwin + 1)
        win = np.array([score[x:x + wwin].mean() for x in xs])
        win = win - CENTER_BIAS * np.abs(xs + wwin / 2 - W / 2) / W
        x = int(xs[int(np.argmax(win))])
        total = float(score.sum())
        coverage = float(score[x:x + wwin].sum()) / total if total > 0 else 1.0
        if coverage < COVERAGE_MIN:
            return CONTAIN_VF, {
                "mode": "contain",
                "reason": "contenido distribuido: contain (nada queda fuera)",
                "coverage": round(coverage, 3)}
        x_full = min(max(round(x / W * iw), 0), iw - ww)
        x_full -= x_full % 2  # crop par (yuv420p)
        cx = (x_full + ww / 2) / iw
        if abs(cx - 0.5) > 0.12:
            side = "izquierda" if cx < 0.5 else "derecha"
            reason = f"contenido a la {side}"
        else:
            reason = "centrado"
        vf = f"crop=w={ww}:h={ih}:x={x_full}:y=0,scale=1080:1920,setsar=1"
        info = {"mode": "smart", "reason": reason, "x": x_full, "w": ww,
                "cx": round(cx, 3)}
        return vf, info
    except Exception as e:  # noqa: BLE001 — el crop nunca debe matar el clip
        return VERTICAL_VF, {"mode": "center", "reason": f"fallback: {e}"}

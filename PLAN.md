# PLAN ytshorter — CLI-first + Web POC mínima

> Estado: EN EJECUCIÓN. Este archivo es la fuente de verdad. Actualizar Calidad y Trazabilidad en cada fase.

## 0. Visión

Recibir link de YouTube largo y devolver carpeta con N subcarpetas, cada una un short listo para subir (video 9:16 + título/descripción/tags/subtítulos/thumbnail/metadata + comando ffmpeg reproducible). Análisis con LLM (Gemini Flash). Todo el procesamiento por consola en background. Web = solo GUI fina (1 campo URL → ruta carpeta). CLI usable 100% por terminal, filosofía UNIX, módulos separados, SOLID/DRY/KISS/YAGNI, dockerizable.

## 1. Requerimientos (origen: usuario 2026-10-15/16)

| ID | Requerimiento | Prioridad | Fase que lo cumple | Estado |
|----|---------------|-----------|--------------------|--------|
| R1 | Input: link YouTube largo | alta | F2 download | implementado, pendiente e2e con red real (bot-check 2026) |
| R2 | Output: carpeta con N subcarpetas upload-ready (`video.mp4`, `title.txt`, `description.txt`, `tags.txt`, `subtitles.srt/.ass`, `thumbnail.jpg`, `metadata.json`, `ffmpeg_cmd.sh`) | alta | F5 package | **verificado e2e local** (2 shorts 1080x1920, 9 archivos c/u) |
| R3 | LLM analiza video y decide cantidad de shorts (no N fijo), autocontenidos y conceptualmente relevantes, mentalidad editor youtuber | alta | F3 analyze | implementado, pendiente llamada real con GEMINI_API_KEY |
| R4 | Prompts versionados para sistematizar calidad editorial | alta | F3 prompts/v1 | **hecho** (editor+virality+packaging, VERSION) |
| R5 | Edición con ffmpeg generado por el sistema, ejecutado en background por consola | alta | F4 clip/reframe/caption | **verificado e2e local** (corte preciso + burn libass + thumbnail) |
| R6 | App web es solo interfaz gráfica (POC: 1 campo URL input, ruta carpeta output) | alta | F6 serve | **verificado** (index 200, POST/GET jobs OK) |
| R7 | Usable por terminal, filosofía UNIX (un comando=una cosa, pipes, JSON stdout, idempotente+cache) | alta | F1-F6 CLI | **hecho** (10 subcomandos, 21 tests) |
| R8 | Dividido en submódulos y componentes (SOLID/DRY/KISS/YAGNI) | media | todas | **hecho** (12 módulos <300 líneas c/u) |
| R9 | Dockerizable | media | F7 | k8s manifest + compose + .env.example listos; build/apply pendiente de entorno |
| R10 | V2 (NO MVP): publicar/programar automáticamente en YouTube, TikTok/Reels | baja | fuera de alcance | diferido YAGNI |

## 2. Decisiones del usuario (2026-10-16)

- LLM: **Gemini Flash (API gratuita)** (`gemini-2.5-flash`).
- Shorts: estándar, **la mayor cantidad que el análisis determine**, duración la que pida cada idea (piso 10s, techo 170s), 9:16 1080x1920, subtítulos quemados + .srt.
- Stack: **solo CLI primero, web POC mínima**.
- Alcance: solo generar carpeta local. Upload = V2.

## 3. OSS investigado (reutilizar patrones, no forks)

- `SamurAIGPT/AI-Youtube-Shorts-Generator --mode local`: pipeline yt-dlp → faster-whisper → LLM → ffmpeg/OpenCV, chunking >30min overlap 60s, VIRALITY_CRITERIA.
- `vitalii-honchar/youtube-shorts-creator`: esquema metadata SEO (título/desc 300+ chars/tags 20-50), -14 LUFS.
- `artbyjazi/autoclip`: diseño CLI `doctor/clip/jobs/providers/config/serve`.
- `junaidify/video_clipper`: Flask + CLI + Dockerfile + gunicorn.
- `DontHash/ClipClipper`: fusión señales (LLM+replay+audio) — reservado V2.

## 4. Arquitectura UNIX

```
URL → download → transcribe → analyze → review → clip → caption → judge → package
      yt-dlp     faster-whisper gemini  gemini  ffmpeg  ffmpeg   gemini  carpeta/
```

Comandos (cada uno idempotente, `--json` a stdout, logs a stderr, cache en `work/<id>/`):

```bash
ytshorter download "URL" -o work/<id>/
ytshorter transcribe work/<id>/source.mp4 [--use-yt-subs-first]
ytshorter analyze work/<id>/transcript.json --prompts v2
ytshorter review work/<id>/
ytshorter clip work/<id>/source.mp4 --clips work/<id>/clips.json
ytshorter caption work/<id>/short_01/cut.mp4
ytshorter package work/<id>/ --out dist/<id>/
ytshorter pipeline "URL" -o dist/<id>/
ytshorter doctor
ytshorter jobs
ytshorter serve --port 8000
```

## 5. Estructura de archivos

```
ytshorter/
  PLAN.md (este archivo)
  QUALITY_LOG.md (registro calidad por fase)
  pyproject.toml
  Dockerfile / compose.yml
  prompts/v1/{editor,virality,packaging}.md + VERSION
  src/ytshorter/{cli,config,download,transcribe,analyze,review,clip,reframe,caption,package,ffmpeg,queue,web,judge,doctor}.py
  web/static/index.html
  work/ dist/ (gitignored)
  tests/test_smoke.py
```

Output final:

```
dist/<video_id>/manifest.json
dist/<video_id>/short_01/{video.mp4,title.txt,description.txt,tags.txt,subtitles.srt,subtitles.ass,thumbnail.jpg,metadata.json,ffmpeg_cmd.sh}
```

## 6. Fases y subtareas

- [ ] F1 scaffold: pyproject, config, cli argparse, doctor, tests smoke
- [ ] F2 download (yt-dlp, cookies-from-browser, cache) + transcribe (yt-subs primero, fallback faster-whisper base CPU, transcript.json palabra/frase)
- [ ] F3 prompts/v1 (editor, virality, packaging) + analyze Gemini JSON-mode, scoring 0-100, dedupe >50%, snap a frase
- [ ] F4 clip (ffmpeg corte preciso) + reframe 9:16 crop-center (face-track → V2) + caption .srt/.ass + burn libass + thumbnail
- [ ] F5 package (arma short_XX/ + manifest.json, normalización -14 LUFS, h264 yuv420p)
- [ ] F6 queue (jobs.json + subprocess background) + serve FastAPI (POST /api/jobs, GET /api/jobs/{id}) + index.html 1-campo
- [ ] F7 Dockerfile/compose + README + e2e video <10min + cierre QUALITY_LOG

## 7. Criterios de calidad por fase (Definition of Done)

- KISS: ningún módulo >300 líneas sin justificar; sin dependencias JS build.
- DRY: un solo lugar para invocar ffmpeg/yt-dlp/LLM.
- YAGNI: sin upload, sin auth, sin React, sin face-track en V1.
- UNIX: cada comando funciona aislado, `--help` claro, re-ejecutable sin duplicar trabajo.
- Verificación: `doctor` OK, `pipeline --help` OK, e2e genera ≥1 short válido (`ffprobe` 1080x1920 + .srt no vacío) antes de cerrar F7.

## 8. Registro de calidad y cumplimiento

Ver `QUALITY_LOG.md`. Cada fase registra: fecha, verificación ejecutada, resultado, deuda.
Trazabilidad R1-R10 se actualiza en la tabla §1 al completar cada fase.

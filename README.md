# ytshorter

Link de YouTube largo → carpeta con shorts 9:16 listos para subir (video + título + descripción + tags + subtítulos + thumbnail + metadata + comando ffmpeg reproducible).

CLI-first, filosofía UNIX: cada subcomando hace una cosa, componible, idempotente. La web es solo una GUI fina sobre el mismo CLI. LLM: Gemini Flash con prompts versionados.

## Requisitos

- Python 3.10+ (3.11 en Docker), `ffmpeg` + `ffprobe` con libass, fuentes DejaVu.
- `GEMINI_API_KEY` ([Google AI Studio](https://aistudio.google.com), free-tier suficiente).
- Opcional: `YT_SHORTER_COOKIES=/ruta/cookies.txt` si YouTube bloquea descargas anónimas.

## Quickstart local

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[test]"
export GEMINI_API_KEY=...
.venv/bin/python -m ytshorter doctor
.venv/bin/python -m ytshorter pipeline "https://www.youtube.com/watch?v=..." -o dist/
ls dist/<video_id>/short_01/
```

Por etapas (cada una re-ejecutable, `--force` para repetir):

```bash
ytshorter download "URL" -o work/
ytshorter transcribe work/<id>/
ytshorter analyze work/<id>/ --prompts v3
ytshorter review work/<id>/          # 2ª instancia audita el plan (stage 4/8)
ytshorter clip work/<id>/
ytshorter caption work/<id>/
ytshorter judge work/<id>            # juez asesor de shorts terminados (stage 7/8)
ytshorter package work/<id>/ --out dist/
ytshorter jobs
```

## Web POC

```bash
ytshorter serve --port 8000  # abre http://localhost:8000
```

Un campo URL → encola el pipeline en background → muestra la ruta de la carpeta al terminar. La versión del build (`vX.Y.Z`) se muestra junto al título vía `GET /api/version` y en la 1ª línea del log del pipeline — si no coincide con `pyproject.toml`, la imagen/instancia está vieja (rebuild: BR-020).

## Run with containers (podman-first)

Setup once:

```bash
cp .env.example .env   # put your GEMINI_API_KEY
```

**Podman** (3 commands, no compose plugin needed):

```bash
podman build -t ytshorter .   # slim: sin faster-whisper, transcribe vía subtítulos de YouTube
podman run -p 9000:9000 --env-file .env -v ./data:/data:Z ytshorter
# open http://localhost:9000
```

Full image with local whisper fallback (videos sin subtítulos, ~1GB extra):

```bash
podman build --build-arg WITH_LOCAL=1 -t ytshorter-full .
```

**Docker** (if you use docker instead):

```bash
docker compose up --build  # http://localhost:9000, datos en ./data/
```

**Kubernetes** (any cluster; image must be pushed to a registry first):

```bash
podman build -t ghcr.io/<you>/ytshorter:latest . && podman push ghcr.io/<you>/ytshorter:latest
# set the same image: in k8s/ytshorter.yaml
kubectl create secret generic ytshorter-secrets --from-env-file=.env
kubectl apply -f k8s/
kubectl port-forward svc/ytshorter 8000:8000
```

## Estructura

```
src/ytshorter/  download transcribe subs analyze sentences review clip reframe caption subtitles burn package pipeline queue web config doctor cli judge frames vision ffmpeg
prompts/v3/     editor.md virality.md reviewer.md packaging.md vision.md VERSION  # prompts versionados (v1/v2 conservados)
web/static/     index.html                                   # POC 1-campo, sin build
docs/           business-rules.md specs/ evals.md            # decisiones + evals de sesión
tests/          test_smoke test_fase{2,3,4,5,6} test_evals test_config test_judge test_vision
```

## Salida (`dist/<id>/short_XX/`)

`video.mp4` (1080x1920 h264, -14 LUFS) · `title.txt` · `description.txt` · `tags.txt` ·
`subtitles.srt` + `subtitles.ass` · `thumbnail.jpg` · `judgment.json` (juez) · `metadata.json` · `ffmpeg_cmd.sh` · `manifest.json` global.

## V2 (YAGNI, fuera del MVP)

Auto-upload/programación YouTube, TikTok/Reels, face-tracking, single-pass ffmpeg, fusión de señales (MostReplayed + energía audio).

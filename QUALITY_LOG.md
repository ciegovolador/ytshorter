# QUALITY_LOG ytshorter — registro de calidad y cumplimiento

Formato por entrada: fecha UTC, fase, verificación (comando), resultado, deuda/riesgo, requerimientos tocados.

---

## 2026-10-16 — Inicio proyecto

- Fase: F0 plan persistido.
- Verificación: `PLAN.md` creado y legible. Pendiente: ejecución.
- Resultado: OK.
- Deuda: ninguna aún.
- Requerimientos: ninguno cumplido todavía (R1-R9 pendientes, R10 diferido).

---

## 2026-10-16 — F1 scaffold CLI OK

- Fase: F1 (pyproject, config, cli, doctor, smoke tests, .venv editable).
- Verificación: `.venv/bin/python -m pytest tests/ -q` → **2 passed**; `.venv/bin/python -m ytshorter --json doctor` → ffmpeg/ffprobe OK, `GEMINI_API_KEY=MISSING` (esperado sin .env).
- Resultado: OK.
- Deuda: `setup.py` shim necesario por pip 22/setuptools viejo; `yt-dlp` binario también en `~/.local/bin` además del pip (duplicado inofensivo).
- Requerimientos: R7 parcial (CLI existe con 9 subcomandos), R8 parcial (módulos creados). R1-R6, R9 siguen pendientes.

---

## 2026-10-16 — F2 download + transcribe OK

- Fase: F2 (yt-dlp idempotente + captions-YouTube-primero + fallback faster-whisper).
- Verificación: `pytest tests/ -q` → **4 passed**; e2e sintético `transcribe /tmp/ytstest/work/synth --no-yt-subs --whisper-model tiny` → `ok:true, source:whisper` (0 segmentos en tono seno = esperado, sin habla); `extract_video_id` OK en watch/youtu.be/shorts.
- Resultado: OK.
- Deuda: sin e2e contra YouTube real (riesgo bot-check 2026; mitigación prevista `YT_SHORTER_COOKIES`). Modelo whisper `base` por defecto, `tiny` solo para tests rápidos.
- Requerimientos: R1 implementado (pendiente e2e real), R7 avanza (2 subcomandos reales).

---

## 2026-10-16 — F3 analyze Gemini + prompts/v1 OK

- Fase: F3 (prompts/v1 editor+virality+packaging, chunking 20min/60s overlap, JSON-mode, dedupe >50%, snap a frase, filtro score>=70 y 15-90s).
- Verificación: `pytest tests/ -q` → **10 passed** (6 nuevos F3); e2e con `call_gemini` mockeado → 2 candidatos entran, 1 se filtra por score<70, `clips.json` con `short_01` + `duration` + packaging.
- Resultado: OK.
- Deuda: sin llamada real a Gemini (requiere `GEMINI_API_KEY`; gasto ~$0 o free-tier). Chunking probado solo unitariamente.
- Requerimientos: R3+R4 implementados (pendiente validación con key real), R7 avanza (3/7 etapas reales).

---

## 2026-10-16 — F4 clip + reframe + caption OK

- Fase: F4 (corte preciso post-`-i`, reframe 9:16 crop-center→1080x1920, loudnorm -14LUFS, .srt/.ass DejaVu quemados con libass, thumbnail a mitad).
- Verificación: `pytest tests/ -q` → **15 passed** (5 nuevos F4); e2e sintético 1280x720/12s → `cut.mp4` y `video.mp4` en `1080,1920` vía ffprobe, `.srt` con texto, `thumbnail.jpg` existe.
- Resultado: OK.
- Deuda: 2 re-encodes por clip (cut + burn); optimización single-pass → V2. Sin face-tracking (crop-center V1, YAGNI).
- Requerimientos: R5 implementado (pendiente video real largo), R7 avanza (5/7 etapas reales).

---

## 2026-10-16 — F5 package OK

- Fase: F5 (copia artefactos + title/description/tags .txt + metadata.json por clip + manifest.json; sin re-encode).
- Verificación: `pytest tests/ -q` → **17 passed** (2 nuevos F5, fixture sin ffmpeg); cada `short_XX/` contiene los 9 archivos exigidos en R2.
- Resultado: OK.
- Deuda: ninguna nueva.
- Requerimientos: R2 implementado (pendiente video real), R7 casi completo (6/7 etapas reales; falta `pipeline` orquestador).

---

## 2026-10-16 — F6 pipeline + queue + web POC OK

- Fase: F6 (orquestador con corte en fallo, jobs.json + subprocess background, FastAPI 3 endpoints, index.html 1-campo con polling).
- Verificación: `pytest tests/ -q` → **21 passed** (4 nuevos F6: orden/corte del pipeline mockeado, queue refresh→done, web 200/400).
- Resultado: OK.
- Deuda: `serve` sin auth (POC local, documentado); job `running` detectado por PID (reinicios del server marcan error, aceptable V1).
- Requerimientos: R6 implementado, R7 completo (pipeline + jobs + serve), R8 OK (web/queue no tocan ffmpeg).

---

## 2026-10-16 — F7 Docker + README + e2e cierre MVP

- Fase: F7 (Dockerfile/compose/.dockerignore, README, extras test httpx, pyproject `[test]`).
- Verificación: `pytest` **21 passed**; e2e `/tmp/yte2e` (video 1280x720/30s + transcript/clips fixture) vía CLI real `clip→caption→package` → `dist/e2e1/{short_01,short_02}/` con 9 archivos c/u, `video.mp4` en `1080,1920` (ffprobe x2); `serve:8123` → `index:200` + `{"jobs":[]}`.
- Resultado: OK. MVP CLI+POC completo.
- Deuda: (1) sin e2e YouTube real ni llamada Gemini real (requieren red + `GEMINI_API_KEY`); (2) `docker build` no ejecutado (sin docker en este entorno); (3) 2 re-encodes por clip (V2).
- Requerimientos: R2/R4/R5/R6/R7/R8 hechos y verificados; R1/R3 implementados pendientes de key+red; R9 parcial (archivos listos, build pendiente); R10 diferido.

---

## 2026-10-16 — Contenedores: .env.example + k8s manifest + README podman

- Fase: F7-extra (`.env.example`, `k8s/ytshorter.yaml` PVC+Deployment+Service, README podman/k8s).
- Verificación: `yaml.safe_load_all` OK en `compose.yml` y `k8s/` (3 docs: PVC, Deployment, Service); `podman 3.4.4` presente → ruta `build+run` (sin compose plugin en v3); `kubectl --dry-run` sin cluster aquí (manifiesto usa solo APIs estables v1/apps/v1).
- Resultado: OK.
- Deuda: `podman build` / cluster apply pendientes de entorno con daemon+red (comandos mínimos documentados en README).
- Requerimientos: R9 avanza (dockerfile+compose+k8s listos; build/apply pendiente de entorno).

---

## 2026-10-16 — transcribe resiliente: reintentos + fallback yt-dlp subs (v0.3.1)

- Fase: post-MVP (bugfix transcribe: bloqueos transitorios de YouTube).
- Verificación: `pytest tests/ -q` → **57 passed** (5 nuevos: parsers json3/srt, reintento solo transitorio vs corte inmediato, fallback yt-dlp→`source=yt-dlp-subs`, error con motivos). E2E real en contenedor con video `J8KLI2FEhaU`: API OK (1149 segs); `_ytdlp_subs` OK (1146 segs, `subs.es.json3`); orquestación con API forzada a fallar → fallback yt-dlp → `transcript.json source=yt-dlp-subs` (1048 segs, texto correcto desde 17.8s); re-run `--force` sin red (subs locales) y sin `--force` (cache) OK.
- Resultado: OK.
- Deuda: sin timeout explícito en `youtube-transcript-api` (si YouTube cuelga, el reintento no aplica); el contenido de auto-captions es/en varía entre variantes de YouTube (chunks vs ventanas rodantes) — ambos parseados.
- Requerimientos: R1/R2 (la corrida de 337s ya no se pierde por un 429 transitorio), R7 (error honesto).

---

## 2026-10-16 — review explícita + versión visible (v0.3.0)

- Fase: post-MVP (builds verificables + puerta review visible en UI).
- Verificación: `pytest tests/ -q` → **52 passed** (test nuevo: `STAGES` con `review` entre `analyze` y `clip`; `/api/version` responde `version`+`stages`; `/` con `Cache-Control: no-store`; pipeline mockeado verifica orden review→clip). Local: `serve:8123` → `/api/version` `{"version":"0.3.0","stages":7}`, header `no-store` OK; `ytshorter --version` → `0.3.0`.
- Resultado: OK.
- Deuda: la imagen `ytshorter:latest` debe rebuildearse para verse (BR-020); tests de la puerta review actualizados al flujo explícito (plan `pending` → stage audit).
- Requerimientos: R6 (web muestra versión del build), R3 (review etapa 4/7 explícita y verificable).

---

## 2026-10-16 — analyze resiliente a 503 de Gemini (v0.3.2)

- Fase: post-MVP (bugfix analyze: 503 UNAVAILABLE "high demand" transitorio).
- Verificación: `pytest tests/ -q` → **60 passed** (3 nuevos: 503 reintenta y termina OK, 400 falla rápido, 503 agota `LLM_ATTEMPTS`). E2E contenedor v0.3.1: transcribe arreglado en vivo (cached 1.0s, `source=youtube-captions`).
- Resultado: OK.
- Deuda: el backoff total (65s) puede no alcanzar si la saturación dura más; siguiente nivel sería cola/reenvío del job (fuera de scope POC).
- Requerimientos: R3 (análisis no se pierde por saturación de Gemini), R7 (error honesto + observabilidad de reintentos).

---

## 2026-10-17 — calidad de decisión y render: captions sin coma, encuadre garantizado, doble instancia runtime (v0.4.0)

- Fase: post-MVP (sesión de calidad: bug de coma quemada, contenido fuera de cuadro, coherencia interna; juez independiente como auditoría del propio dev session).
- Verificación: `pytest tests/ -q` → **72 passed** (nuevos: Format de [Events] vs Dialogue, ancho de línea paginado, ventana rolling/vacía en `words_of`, contain por cobertura de saliencia, `should_replan`/`critique_from_review` + reciclado e2e mockeado, cache por mtime de `judge_all`, `judge_call` reintenta transitorio y falla rápido en definitivo). E2E contenedor `v0.4.0` con `J8KLI2FEhaU` (job-20261017-034939-1): analyze prompts v2 n=20 → review 9 keep/8 adjust/3 drop (15% < 40% → sin reciclado) → clip 17/17 (mix `contain` cuando saliencia distribuida, `x=0/874` gráfico, `x=548/468` rostro) → caption 287s → judge 57s (cuota diaria Gemini agotada: 2 veredictos reales + 15 fallback `-1`, ships=1) → package 17. `.ass` final: 273 diálogos, **0 desalineados, 0 empiezan con coma, 0 vacíos**. Auditoría independiente de los renders viejos (juez, 7 shorts con cuota disponible): **0/7 ship**, scores 40-65, con la coma de caption confirmada visualmente en frames (short_02/04/06) + caras fuera de cuadro/hooks débiles.
- Resultado: OK (fixes verificados a nivel contrato y e2e).
- Deuda: (1) encode `contain` carísimo: 500-1100s/clip vs 65-130s en crop — próximo paso: blur sobre frame downscaleado; (2) cuota diaria Gemini se agotó a mitad de auditoría → completar auditoría de `-i--5e4JfHM`/`qJxtOQdnRAY` cuando resetee; (3) re-render de dists v0.3.2 pendiente (tienen la coma quemada).
- Requerimientos: R3 (decisión con doble instancia + reciclado acotado Evaluator-Optimizer), R6 (captions sin coma y ≤2 líneas garantizadas por contrato `.ass`), R7 (juez asesor no bloqueante, con evidencia en frames).

---

## 2026-10-18 — P4.0 volumen garantizado + encodes baratos (v0.6.0, local sin cuota)

- Fase: rethink "volumen y calidad" (`docs/plan-volumen-calidad.md`), fase local (0 cuota).
- Verificación: `pytest tests/ -q` → **119 passed** (nuevos: contain v2 barato + humo ffmpeg real; cut_all/caption_all paralelos con detección de solape real; `fallback_clips` determinista sin solape; piso de volumen con LLM mockeado tacaño; funnel en manifest con invariante propuestos=final+drops; contrato prompts v4). Benchmark contain (10s): **9.9s → 5.7s** (1.7×) + 4 workers en paralelo. Contenedor v0.6.0 `/api/version` OK.
- Cambios: `CONTAIN_VF` v2 (blur gaussiano sobre miniatura cover 270x480, fondo oscurecido/desaturado — mata "blur masivo" y el coste 5-8 min/clip); encode paralelo en clip/caption (`YT_SHORTER_JOBS`, default min(4, nproc//2), callbacks desde el hilo principal); **BR-030** piso de volumen (`max(8, min//4)`, respaldo local determinista score ≤62 que nunca desplaza al LLM); **BR-031** funnel en manifest; **BR-032** entrega resiliente; **prompts/v4** (editor cobertura total 12-25 sin cupo propio, reviewer solo drops por causa dura); plan P4 documentado.
- Resultado: OK local. Pendiente con cuota: smoke de v4 (3.8-flash agotado hasta ~2026-10-18 noche), flip de default, re-run de los 3 videos.
- Deuda: judge por lote + ledger de cuota (P4.2); prepass señales/cropdetect "nunca UI visible" (P4.3).
- Requerimientos: pedido 2026-10-18 (una corrida → TODOS los shorts, como v0.4.0 pero mejor), R6/R7.

---

<!-- Nuevas entradas se agregan arriba de esta línea al cerrar cada fase -->

# FEEDBACK ytshorter — recolección de feedback

Copia una entrada por prueba / bug / idea. Una línea por campo, sin ensayos.

## Cómo usar

1. Duplica la plantilla de abajo.
2. Rellena: fecha UTC, entorno, video/comando, resultado, severidad.
3. Para bugs pega el log mínimo (`podman logs` / traceback corto).

Severidad: `blocker` (no arranca) / `major` (pipeline no completa) / `minor` (sale pero feo) / `idea`.

---

## Plantilla

```md
## YYYY-MM-DD — título corto

- Entorno: podman / docker / local (.venv) + OS:
- Versión/imagen: `ytshorter:latest` (rebuild? sí/no):
- Comando: `...`
- Video URL / ID (si aplica):
- Esperado:
- Obtenido:
- Severidad: blocker / major / minor / idea
- Log (corto):
  ```
  ...
  ```
- Calidad shorts (1-5, si aplica): video: / título: / subs: / thumbnail:
- Comentario libre (1-2 líneas):
```

---

## Entradas

### 2026-10-16 — ejemplo

- Entorno: podman 3.4.4 + Linux
- Versión/imagen: `ytshorter:latest` (rebuild? sí)
- Comando: `podman run -p 9000:9000 --env-file .env ytshorter`
- Video URL / ID (si aplica): -
- Esperado: `GET /` 200 con `index.html`
- Obtenido: `500 FileNotFoundError: .../web/static/index.html`
- Severidad: blocker
- Log (corto):
  ```
  RuntimeError: File at path /usr/local/lib/python3.11/web/static/index.html does not exist.
  ```
- Calidad shorts (1-5, si aplica): video: - / título: - / subs: - / thumbnail: -
- Comentario libre (1-2 líneas): path estático no resuelve en imagen pip install.

<!-- Nuevas entradas debajo de esta línea -->

### 2026-10-16 — ETA del proceso

- Entorno: podman + web POC (`http://localhost:9000`)
- Versión/imagen: `ytshorter:latest`
- Comando: `POST /api/jobs` → polling `GET /api/jobs/{id}`
- Video URL / ID (si aplica): -
- Esperado: ver etapa actual (x/6), tiempo transcurrido y ETA restante.
- Obtenido: solo `Procesando... (running)` + log tail, sin progreso ni ETA.
- Severidad: idea (major para UX en videos largos)
- Log (corto):
  ```
  $('out').textContent = ... 'Procesando... (' + j.status + ')';
  ```
- Calidad shorts (1-5, si aplica): video: - / título: - / subs: - / thumbnail: -
- Comentario libre (1-2 líneas): transcribe/analyze dominan el tiempo; con solo "running" el usuario no sabe si va 10% o 90%.

### 2026-10-16 — FutureWarning google.generativeai deprecated

- Entorno: podman imagen `ytshorter` (python:3.11-slim)
- Versión/imagen: `ytshorter:latest` (rebuild? sí)
- Comando: pipeline web → `analyze` (Gemini)
- Video URL / ID (si aplica): `q1xt00DnRAY` (70MB, 1600 segs youtube-captions)
- Esperado: `analyze ok` sin warnings.
- Obtenido: `analyze ok n=20` pero con `FutureWarning: All support for google.generativeai ended... switch to google.genai`.
- Severidad: minor (funciona, ruido + riesgo EOL 2025-11-30)
- Log (corto):
  ```
  [pipeline] analyze ok n=20
  FutureWarning: ... switch to the `google.genai` package ...
  import google.generativeai as genai
  ```
- Calidad shorts (1-5, si aplica): video: - / título: - / subs: - / thumbnail: -
- Comentario libre (1-2 líneas): migrar `call_gemini` a `google-genai` (`genai.Client` + `GenerateContentConfig`).

### 2026-10-16 — no re-descargar video ya bajado

- Entorno: podman imagen `ytshorter` (sin `-v` en el `run`)
- Versión/imagen: `ytshorter:latest`
- Comando: `podman run -p 9000:9000 --env-file .env ytshorter` (rebuild entre pruebas)
- Video URL / ID (si aplica): `q1xt00DnRAY` (70MB)
- Esperado: 2ª vez `download ok cached=True`, sin tráfico.
- Obtenido: re-descarga 70MB en cada contenedor nuevo.
- Severidad: major (tiempo + ancho de banda; peor en videos largos)
- Log (corto):
  ```
  [pipeline] download ok video_id=q1xt00DnRAY cached=False
  ```
- Calidad shorts (1-5, si aplica): video: - / título: - / subs: - / thumbnail: -
- Comentario libre (1-2 líneas): `download.py` ya es idempotente si `source.mp4+info.json` existen; falta persistir `/data/work` con volumen.

### 2026-10-16 — más logs y observabilidad (ETA total y por etapa)

- Entorno: podman + web POC + `ytshorter jobs`
- Versión/imagen: `ytshorter:latest`
- Comando: `POST /api/jobs` → polling; `ytshorter jobs [--watch]`
- Video URL / ID (si aplica): -
- Esperado: saber etapa actual, ETA total y por etapa.
- Obtenido: solo `running` + `eta` lineal total (sin desglose ni histórico).
- Severidad: idea (major UX en videos largos)
- Log (corto):
  ```
  Etapa analyze 3/6... 45s transcurridos · ETA ~30s
  ```
- Calidad shorts (1-5, si aplica): video: - / título: - / subs: - / thumbnail: -
- Comentario libre (1-2 líneas): implementado: `stage_times` por etapa en `progress.json`, historial de medianas en `jobs/stage_history.json`, tabla por etapa en web, `jobs --watch`.

### 2026-10-16 — granularidad ffmpeg (qué short se procesa)

- Entorno: podman + web POC, video `qJxtOQdnRAY` (20 shorts)
- Versión/imagen: `ytshorter:latest`
- Comando: `POST /api/jobs` → polling
- Video URL / ID (si aplica): `qJxtOQdnRAY`
- Esperado: ver qué hace ffmpeg ahora (p. ej. `short_07/20`) y ETA por etapa.
- Obtenido: `Etapa clip 4/6...` 1319s sin detalle; columna ETA en `–` (sin historial en 1ª corrida); log tapado por spam `[download] 83%...`.
- Severidad: major UX (parece colgado 20+ min)
- Log (corto):
  ```
  [pipeline] [4/6] clip start
  (silencio 1319s: 20× ffmpeg corte+reframe sin reporte)
  ```
- Calidad shorts (1-5, si aplica): video: - / título: - / subs: - / thumbnail: -
- Comentario libre (1-2 líneas): implementado: callback `on_item` en `cut_all`/`caption_all`, sub-etapa `short_07/20` en `progress.json`/web/CLI, `[clip 7/20] short_07 63s` en log, `noprogress` en yt-dlp, tail 30→50.

### 2026-10-16 — % en vivo dentro de cada ffmpeg

- Entorno: podman + web POC (`Etapa clip 4/6 · short_07/20`)
- Versión/imagen: `ytshorter:latest`
- Comando: `POST /api/jobs` → polling
- Video URL / ID (si aplica): -
- Esperado: ver % del encode actual (no solo `short_07/20` parado minutos).
- Obtenido: sub-etapa sin % (solo conteo de shorts).
- Severidad: idea
- Log (corto):
  ```
  Etapa clip 4/6 · short_07/20...
  ```
- Calidad shorts (1-5, si aplica): video: - / título: - / subs: - / thumbnail: -
- Comentario libre (1-2 líneas): implementado: `ffmpeg.py:run_with_progress` (`-progress` + `out_time_ms`/duración, throttled 2s), `on_tick` en `cut_all`/`caption_all`/`burn_and_thumb`, `sub_pct` en `progress.json`/web (`short_07/20 45%`)/CLI; `ffmpeg_cmd.sh` sigue limpio (reproducible).

### 2026-10-16 — caption falla: cut.mp4 corrupto (moov atom not found)

- Entorno: podman, video `qJxtOQdnRAY`, rerun con `cut.mp4` parciales de un kill anterior
- Versión/imagen: `ytshorter:latest`
- Comando: pipeline → `caption short_10`
- Video URL / ID (si aplica): `qJxtOQdnRAY`
- Esperado: re-generar o reportar el corte malo.
- Obtenido: `Error opening input file .../short_10/cut.mp4: moov atom not found` → job a `error`.
- Severidad: blocker (mata el pipeline entero por 1 archivo)
- Log (corto):
  ```
  [mov,mp4,m4a,3gp,3g2,mj2 @ ...] moov atom not found
  Error opening input file .../short_10/cut.mp4
  ```
- Calidad shorts (1-5, si aplica): video: - / título: - / subs: - / thumbnail: -
- Comentario libre (1-2 líneas): causa: cache solo miraba `exists()`. Fix: `ffmpeg.py:is_valid_video` (ffprobe duración ±20%) en `cut_all`/`burn_and_thumb`, parciales borrados al fallar, `cut` inválido en caption → error claro. Bonus: corregido shadowing `total`=duración en `cut_all`/`caption_all` (el `[20/37.36]` del log) y `0.0s` ya no muestra `–` en web.

### 2026-10-16 — subtítulos listos para marketing (karaoke, CPS, fuente)

- Entorno: local + podman
- Versión/imagen: `ytshorter:latest`
- Comando: `caption` → `video.mp4`
- Video URL / ID (si aplica): -
- Esperado: subtítulos estilo shorts virales: 2-4 palabras, highlight amarillo, legibles en móvil.
- Obtenido: frase completa fija, DejaVu 64, pegado al borde inferior (lo tapa el UI de TikTok).
- Severidad: idea (major para "listo para subir")
- Log (corto): -
- Calidad shorts (1-5, si aplica): video: - / título: - / subs: 2 / thumbnail: -
- Comentario libre (1-2 líneas): implementado según canon 2026 (Submagic/Hormozi/Netflix 20 CPS): karaoke `\k` (amarillo #FFEB00 sobre blanco, sweep hasta la palabra siguiente), bloques ≤8 palabras / máx 2 líneas, word-timings de whisper o estimados por caracteres, mín 120ms/palabra, lead 40ms, hold +200ms, mín 0.5s/bloque; Montserrat > Inter > Poppins > DejaVu (`YT_SHORTER_FONT` override, `fonts-montserrat` en imagen); SRT también troceado; filtro `ass` (no `subtitles`, que aplana karaoke).

### 2026-10-16 — cortes a mitad de frase + encuadre fijo + docs/evals

- Entorno: local + podman, video `qJxtOQdnRAY`
- Versión/imagen: `ytshorter:latest`
- Comando: pipeline completo + revisión de `short_13`/`short_20`
- Video URL / ID (si aplica): `qJxtOQdnRAY`
- Esperado: cortes en frases completas; cara y gráficos dentro de cuadro.
- Obtenido: `short_20` 2966.68 cortaba `estas|flechitas`, fin en `todas estas|flechitas`; `short_13` media cara fuera; flechas rojas fuera de cuadro (crop-center).
- Severidad: major (calidad visible del producto)
- Log (corto):
  ```
  short_20 snapped: 2963.04 → 3008.75 (bordes de frase reales)
  s13 crop x=242 (rostro a la izquierda) | s20 crop x=678 (gráfico a la derecha)
  ```
- Calidad shorts (1-5, si aplica): video: 3 / título: - / subs: - / thumbnail: -
- Comentario libre (1-2 líneas): implementado: `merge_stream` (overlap join) + `build_sentences` + snap a frase (≤12s, 15-90s); trim de palabras de borde en captions; crop smart (Haar > rojo concentrado > saliencia, estático, `reframe.json`→`metadata.json`, nunca falla); `opencv+ numpy` en deps. Consolidado en `docs/` (BR-001…020, 6 specs, evals) + `tests/test_evals.py` (EVAL-01…07).

### 2026-10-16 — download muere en timeout + URL truncada

- Entorno: podman, video nuevo `i--5e4JfHM`
- Versión/imagen: `ytshorter:latest`
- Comando: `POST /api/jobs` → `download 1/6`
- Video URL / ID (si aplica): `https://www.youtube.com/watch?v=i--5e4JfHM` (ID de 10 chars, truncado)
- Esperado: reintentar ante `Read timed out`; rechazar URL mala al instante.
- Obtenido: `DownloadError: Read timed out` tras reintentos internos → job a `error`; el ID inválido nunca se validó.
- Severidad: major (red flaky = corrida perdida)
- Log (corto):
  ```
  yt_dlp.utils.DownloadError: ERROR: Got error: HTTPSConnectionPool(...): Read timed out.
  ```
- Calidad shorts (1-5, si aplica): video: - / título: - / subs: - / thumbnail: -
- Comentario libre (1-2 líneas): fix en `download.py`: validación temprana de ID (11 chars o archivo), `retries`/`fragment_retries` 10 + `socket_timeout` 60, 3 intentos con backoff retomando `.part`, `info.json` corrupto re-descarga. Docs: `specs/download.md` + BR-021.

### 2026-10-16 — coma inicial + quemado rancio + doble instancia (review + judge)

- Entorno: local + podman, videos `qJxtOQdnRAY` (20 shorts) y `-i--5e4JfHM` (18 shorts)
- Versión/imagen: `ytshorter:latest`
- Comando: revisión visual de `dist/*/video.mp4` + `ytshorter judge`
- Video URL / ID (si aplica): ambos
- Esperado: captions karaoke nuevos quemados; clips cuestionados por 2ª instancia.
- Obtenido: frame real `,río desde allá, desde / el río Iguazú hasta` (coma inicial + crop viejo); `video.mp4` 03:32 vs `.ass` 04:05 (quemado rancio por cache solo-`exists`).
- Severidad: major (lo que se sube ≠ lo que genera el código actual)
- Log (corto):
  ```
  judge short_13: ship=false score=65 (cara cortada, comas iniciales)
  judge short_20: ship=false score=2 (flechas fuera de cuadro en ese render)
  ```
- Calidad shorts (1-5, si aplica): video: 2 / título: 4 / subs: 2 / thumbnail: 3
- Comentario libre (1-2 líneas): fix: `burn.hash` (sha del ass) invalida quemados rancios; `split_lines` (sin colgadas, sin coma inicial); puerta plan→review→execute (`reviewer.md`, keep/drop/adjust, nunca rompe); `ytshorter judge` multimodal (frames+título+captions+framing → `judgment.json`, asesor). Docs: `specs/review.md` + BR-022/023. 49 tests.

### 2026-10-16 — la duración la dicta la idea (no al revés)

- Entorno: local + podman
- Versión/imagen: `ytshorter:latest`
- Comando: `analyze` (puerta review incluida)
- Video URL / ID (si aplica): -
- Esperado: ideas completas de cualquier largo; prioridades relevancia > viral > autocontención > congruencia > consistencia.
- Obtenido: cotas duras 15-90s en filtro+snap+review y objetivo 25-60s en prompt (una idea de 2min se mutilaba; un fragmento de 4s se rellenaba a 10s).
- Severidad: idea (major editorial)
- Log (corto):
  ```
  s20 2963.04 → 3008.75 (45.7s) | 51 tests verdes
  ```
- Calidad shorts (1-5, si aplica): video: - / título: - / subs: - / thumbnail: -
- Comentario libre (1-2 líneas): `config.min/max_short_s` (10/170, antes muertos en 25/60) ahora mandan filtro+snap+veredictos; `editor.md` con las 5 prioridades; snap ya no rellena al piso (descarta); `VERSION` changelog + `PLAN.md` actualizados. Docs: BR-017. Para verlo en los mp4: rebuild + re-cortar/re-quemar (los `cut.mp4`/`video.mp4` viejos son válidos y no se tocan solos).

### 2026-10-16 — review explícita (4/7) + versión visible (builds viejos)

- Entorno: podman + web POC (`http://localhost:9000`)
- Versión/imagen: `ytshorter:latest` (rebuild? pendiente)
- Comando: abrir la web y lanzar pipeline (`POST /api/jobs`)
- Video URL / ID (si aplica): -
- Esperado: ver `review` como etapa propia entre `analyze` y `clip` (4/7) y saber si la instancia es la última build.
- Obtenido: la UI corría una imagen vieja (6 etapas, `stages=6`) sin `review` ni forma de detectarlo a simple vista.
- Severidad: minor (confusión de builds; la review ya existía en código pero no corría)
- Log (corto):
  ```
  [pipeline] url=... stages=6
  Etapa download 1/6...
  ```
- Calidad shorts (1-5, si aplica): video: - / título: - / subs: - / thumbnail: -
- Comentario libre (1-2 líneas): implementado: `GET /api/version` (`version`+`stages`) y versión junto al título en la web (`/` con `no-store`, así nunca queda HTML viejo); `vX.Y.Z` en la 1ª línea del log del pipeline; `--version` ya existía. `review` ya era etapa 4/7 en código: rebuild para verla. Tests de la puerta actualizados al flujo plan→review explícito. Docs: BR-024. Versión `0.3.0`.

### 2026-10-16 — transcribe falla por bloqueo transitorio de YouTube (mensaje mentía)

- Entorno: podman + pipeline (`stages=6`), video `J8KLI2FEhaU` (49min, 204MB)
- Versión/imagen: `ytshorter:latest` (rebuild? sí)
- Comando: `POST /api/jobs` → `download ok 337.7s` → `transcribe FAIL 0.7s`
- Video URL / ID (si aplica): `https://www.youtube.com/watch?v=J8KLI2FEhaU` ("Fenómeno del niño")
- Esperado: transcribir con subtítulos (el video tiene auto-captions es; luego se comprobó: API 1149 / yt-dlp 1048-1146 segmentos).
- Obtenido: `sin subtítulos de YouTube y faster-whisper no instalado (imagen slim)` — falso: el video sí tiene; fue un bloqueo transitorio (yt-dlp sufrió `HTTP 429 Too Many Requests` en la misma sesión).
- Severidad: major (corrida de 337s perdida por error engañoso; sin reintento ni fallback)
- Log (corto):
  ```
  [pipeline] [2/6] transcribe FAIL 0.7s
  "error": "sin subtítulos de YouTube y faster-whisper no instalado (imagen slim)..."
  ```
- Calidad shorts (1-5, si aplica): video: - / título: - / subs: - / thumbnail: -
- Comentario libre (1-2 líneas): fix en `transcribe.py`: `_try_youtube_captions` devuelve `(segs, motivo)` y reintenta 3× con backoff solo errores transitorios (RequestBlocked/IpBlocked/429/timeouts); nuevo fallback `_ytdlp_subs` (json3/srt, un idioma por intento para sobrevivir 429s, reusa cookies) con parser propio `_parse_json3`/`_parse_srt` + `_dedupe_rolling`; cache `subs.*` local; error final con motivos reales. Docs: BR-016 + `specs/transcribe.md`. Versión `0.3.1`.

### 2026-10-16 — analyze muere con 503 de Gemini (high demand)

- Entorno: podman `v0.3.1` (rebuild hecho), video `J8KLI2FEhaU` (cached: download 2.2s, transcribe 1.0s)
- Versión/imagen: `ytshorter:latest` = v0.3.1 (rebuild? sí)
- Comando: `POST /api/jobs` → `[3/7] analyze start` → FAIL 3.2s
- Video URL / ID (si aplica): `https://www.youtube.com/watch?v=J8KLI2FEhaU`
- Esperado: analyze completa (o reintenta si Gemini está saturado).
- Obtenido: `gemini chunk 1: 503 UNAVAILABLE ... "Spikes in demand are usually temporary. Please try again later."` → job a `error` sin un solo reintento.
- Severidad: major (503 "high demand" es transitorio por definición; se perdía todo el pase de análisis)
- Log (corto):
  ```
  [pipeline] [3/7] analyze FAIL 3.2s
  "error": "gemini chunk 1: 503 UNAVAILABLE {'error': {'code': 503, ... 'status': 'UNAVAILABLE'}}"
  ```
- Calidad shorts (1-5, si aplica): video: - / título: - / subs: - / thumbnail: -
- Comentario libre (1-2 líneas): implementado en `call_gemini` (analyze + review): `_is_transient_llm_error` (por `code` 429/5xx o texto UNAVAILABLE/RESOURCE_EXHAUSTED/timeout/overloaded) + 4 intentos con backoff 5/15/45s, log   `[analyze] gemini intento i/4 …` a stderr (visible en la web); errores definitivos (400/403) fallan rápido. Docs: BR-025. Versión `0.3.2`.

### 2026-10-17 — captions quemados arrancaban con coma y bloque de 3 líneas (todos los shorts)

- Entorno: podman `v0.3.2`, video `J8KLI2FEhaU` (dists `-i--5e4JfHM`, `qJxtOQdnRAY`)
- Versión/imagen: `ytshorter:latest` = v0.3.2 (rebuild? sí)
- Comando: inspección de `dist/*/short_XX/` (quemado en player vs `.srt`/`.ass` fuente)
- Video URL / ID (si aplica): `https://www.youtube.com/watch?v=J8KLI2FEhaU`
- Esperado: el texto de subtítulo = transcript, máx 2 líneas/bloque.
- Obtenido: cada bloque renderizado empezaba `,un frente cálido…` (coma fantasma SOLO en el `.ass` quemado; el `.srt` y los bytes del `.ass` estaban limpios) y algunos bloques mostraban una 3ª fila por auto-wrap de libass.
- Severidad: major (defecto visible en todos los shorts entregados; el juez no lo veía porque lee el `.srt`)
- Log (corto):
  ```
  Format: Layer, Start, End, Style, MarginL, MarginR, MarginV, Effect, Text   ← 9 campos
  Dialogue: 0,0:00:00.04,0:00:01.94,Default,,0,0,0,,hola mundo               ← 10 campos (Name vacío)
  ```
- Calidad shorts (1-5, si aplica): video: 3 / título: - / subs: 2 / thumbnail: -
- Comentario libre (1-2 líneas): causa raíz doble: (1) `[Events] Format` declaraba 9 campos sin `Name` pero los `Dialogue` traían el campo extra → libass corre el texto y quema la coma; (2) líneas con ancho >frame → libass re-envuelve a 3ª fila. Fix: `Format` alineado al writer + paginación por ancho (`MAX_LINE_UNITS=20`, `_render_lines` codicioso que achica chunks). En la misma corrida: timeline monótono (segmentos rolling de whisper recortados a ventana efectiva `[start_n, start_{n+1}]`) — arregló karaoke con 2 palabras encendidas y CPS pico real 38.9→19.4 (el `end` rolling no es audio propio). Verificado quemando sobre negro y regenerando un short e2e. Docs: BR-014/BR-023. Versión `0.4.0`.

### 2026-10-17 — contenido fuera de cuadro e clips irrelevantes sin coherencia interna

- Entorno: podman `v0.3.2`, video `J8KLI2FEhaU` ("Fenómeno del niño", 49min)
- Versión/imagen: `ytshorter:latest` = v0.3.2 (rebuild? sí)
- Comando: revisión de `dist/J8KLI2FEhaU/short_XX/` + auditoría con juez independiente
- Video URL / ID (si aplica): `https://www.youtube.com/watch?v=J8KLI2FEhaU`
- Esperado: (a) si el clip habla de algo en pantalla (mapa/flechas), que SE VEA; (b) clips autocontenidos de UNA idea continua, sin arranques anafóricos ("como les decía", "este mapa" sin referente) ni momentos irrelevantes.
- Obtenido: crops estáticos 9:16 dejaban gráficos referenciados fuera de cuadro (p. ej. flechas laterales); el editor devolvía clips con saltos de tema y hooks huérfanos, y ningún control de calidad se aplicaba a lo producido.
- Severidad: major (calidad editorial y de encuadre por debajo del estándar del canal)
- Log (corto):
  ```
  [judge] short_13 score=65 ship=false issue="cara cortada"
  [judge] short_20 score=0  ship=false issue="flechas fuera de cuadro"
  ```
- Calidad shorts (1-5, si aplica): video: 3 / título: 4 / subs: 3 / thumbnail: -
- Comentario libre (1-2 líneas): fix en dos frentes. Determinista (encuadre): saliencia dispersa (cobertura <0.55) → `CONTAIN_VF` (blur de fondo + contenido completo a 1080 de ancho), nunca más contenido referenciado invisible. Agentic (decisión): prompts `v2` con coherencia interna dura (un rango = una idea continua; salto de tema → recorte/descarte), bordes exactos en frase, prohibición de anáforas huérfanas y autochequeo obligatorio; runtime con Evaluator-Optimizer acotado (drops ≥40% y ≥4 clips → `analyze` re-corre UNA vez con críticas Reflexion + re-review `force`) y etapa `judge` 7/8 asesora (`judgment.json` viaja en el paquete). Técnica respaldada por evidencia: el juez LLM como asesor acotado, gates deterministas mandan. Docs: BR-014 (timeline), BR-017 (v2), BR-026/027, `specs/review.md`. Versión `0.4.0`.

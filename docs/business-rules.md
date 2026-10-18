# Reglas de negocio (BR)

Contratos estables. Cambiar código sin romper estas reglas; si una regla debe
cambiar, actualizar regla + spec + eval juntos.

## Contenedores y entorno

- **BR-001 Puertos**: la imagen escucha `9000` (`Dockerfile` + `compose.yml`
  `9000:9000`). CLI local `serve` sigue en `8000` por defecto.
- **BR-002 Persistencia**: `/data/work` (intermedios) y `/data/dist` (finales)
  viven en volumen (`./data:/data:Z`). Sin `-v`, todo es efímero.
- **BR-003 Estructura `data/` en repo**: `data/work/` + `data/dist/` con
  `.gitkeep`; contenidos ignorados. Nunca commitear videos.
- **BR-004 Layout instalado**: el código resuelve `web/static` y `prompts/`
  en repo-root, `/app/...` (imagen pip) y `$CWD` — nunca una sola ruta fija.
- **BR-005 Secretos**: `GEMINI_API_KEY` solo por entorno (`.env` gitignored,
  `secret` en k8s). Jamás en código ni logs.
- **BR-006 Slim por defecto**: la imagen no trae faster-whisper (ahorra ~1GB).
  Full con `--build-arg WITH_LOCAL=1`. `doctor` reporta `whisper_local`.

## Pipeline (idempotencia + observabilidad)

- **BR-007 Idempotencia**: cada etapa re-ejecutable; `source.mp4+info.json`,
  `transcript.json`, `clips.json`, `cut.mp4`, `video.mp4`, `manifest.json`
  existentes y válidos → `cached`. `--force` para repetir.
- **BR-008 Cache validado**: `exists()` no basta. Video cacheado debe abrir
  con ffprobe y cuadrar duración ±20% (mín 0.5s). Parciales se borran al fallar.
- **BR-009 Progreso**: todo job escribe `work/jobs/<jid>.progress.json` con
  `stage/stage_idx/8` (download→transcribe→analyze→review→clip→caption→judge→package),
  `stage_times`, tiempos y `status`. Nunca bloquea el pipeline.
- **BR-010 ETA honesta**: con historial (`stage_history.json`, últimas 50) →
  `eta_source: history` total + por etapa. Sin historial → `linear` rotulada.
  Jamás un número sin fuente.
- **BR-011 Sub-etapas ffmpeg**: `clip`/`caption` reportan `short_XX/N` y `%`
  en vivo (`-progress`, throttled 2s). `ffmpeg_cmd.sh` guardado queda limpio.
- **BR-012 Logs**: `[pipeline] vX.Y.Z url=… stages=8` + `[pipeline] [i/8] <etapa> start|ok|FAIL <s>` a stderr.
  yt-dlp con `noprogress`. `GET /api/jobs/{id}` devuelve `log_tail` (50 líneas).

## Contenido (calidad de shorts)

- **BR-013 Cortes en frase**: ningún short empieza/termina a mitad de idea.
  Snap a bordes de frase sobre flujo fusionado (ver `specs/clip-boundaries.md`).
- **BR-014 Captions marketing**: karaoke `\k` amarillo sobre blanco, ≤8
  palabras/bloque, máx 2 líneas, ≥0.5s/bloque, CPS ≤20, fuente pesada,
  tercio medio-bajo. SRT troceado igual. Sin `Dialogue` si no hay habla.
  Timeline global monótono: los segmentos rolling de whisper (cada uno arranca
  antes de cerrar el anterior) se recortan a su ventana efectiva `[start_n,
  start_{n+1}]`; una sola palabra encendida a la vez y sin bloques comprimidos.
- **BR-015 Encuadre con contenido**: prioridad rostro grande > gráfico de
  alerta > saliencia; un crop estático por clip; `reframe.json` → `metadata.json`.
  El crop nunca falla el clip (fallback a centro).
- **BR-016 Transcripción**: subtítulos de YouTube primero: `youtube-transcript-api`
  (es/en, manuales antes que auto) con reintentos solo en errores transitorios,
  fallback a subs vía `yt-dlp` (json3/srt, reusa cookies), y whisper
  local (`base`, int8) como último recurso y solo si está instalado. El error
  final nombra el motivo real de cada vía, nunca "sin subtítulos" a ciegas.
- **BR-017 Selección**: score ≥70; la duración la dicta la idea (piso 10s,
  techo 170s = tope técnico de Shorts); prioridades en orden: relevancia,
  factor viral, autocontención, coherencia interna, congruencia, consistencia.
  Cada rango es UN pasaje continuo de una sola idea (saltos de tema → recorte
  o descarte) y sin anáforas huérfanas ("como les decía", "este mapa" sin
  referente propio). Dedupe solape >50%, prompts versionados (`prompts/v3`,
  override por id en `prompts/<v>/`, `YT_SHORTER_PROMPTS`), chunking
  20min/overlap 60s. Un fragmento corto no se rellena: se descarta.
- **BR-018 Paquete**: por short `video.mp4` 1080x1920 h264 -14 LUFS +
  `title/description/tags.txt` + `subtitles.srt/.ass` + `thumbnail.jpg` +
  `judgment.json` (si el juez corrió) + `metadata.json` + `ffmpeg_cmd.sh`
  reproducible + `manifest.json` global.

## Proceso

- **BR-019 Trazabilidad**: hallazgo → `FEEDBACK.md` → (regla BR) → (eval en
  `tests/test_evals.py` con fixture de sesión si aplica).
- **BR-020 Rebuild**: tocar `src/` o `web/` exige rebuild de imagen; el código
  nunca se monta como volumen en `compose`/run.
- **BR-021 Descarga resiliente**: ID inválido se rechaza sin red; timeouts se
  reintentan (yt-dlp 10 + función 3 con backoff) retomando `.part`; cache con
  `info.json` corrupto se re-descarga.
- **BR-022 Doble instancia**: todo plan de clips pasa por revisor independiente
  antes de ffmpeg (`reviewer.md`); el revisor puede podar/ajustar, nunca romper
  (fallo → vale el plan). El juez (`judge`) audita shorts terminados y solo
  anota (`judgment.json`), jamás bloquea ni borra.
- **BR-026 Reciclado acotado (Evaluator-Optimizer)**: si la review poda ≥40%
  de un plan de ≥4 clips, `analyze` se re-ejecuta UNA vez con las críticas del
  revisor concatenadas (Reflexion) y el plan pasa por segunda review
  (`force`). Máximo una vuelta; si la re-review falla se restaura el plan
  previo (`YT_SHORTER_NO_REVISION` desactiva el bucle). Determinista y
  visible: el reciclado se loguea.
- **BR-027 Juez en pipeline**: la etapa `judge` (7/8, entre `caption` y
  `package`) corre `judge_all`: audita cada short con video, tomando contexto
  de `clips.json` cuando el paquete aún no existe, cachea por mtime
  del mp4 (`JUDGE_VERSION`), resume `ships/total` en logs y copia
  `judgment.json` al paquete. Sin `GEMINI_API_KEY` o con `YT_SHORTER_NO_JUDGE`
  se omite con aviso; un juez caído nunca frena la entrega.
- **BR-023 Captions sin ruidos**: ninguna línea renderizada empieza en `,;:.`;
  ninguna línea (salvo la última del bloque) cierra en palabra colgada
  (artículo/preposición/conjunción); el quemado se invalida por hash del `.ass`
  (`burn.hash`), no por existencia.
- **BR-024 Versión visible**: la app expone `GET /api/version` (`version` +
  `stages`) y la muestra junto al título; el pipeline loguea `vX.Y.Z` en su
  primera línea y `ytshorter --version` la reporta. Fuente única:
  `src/ytshorter/__init__.py:__version__` = `pyproject.toml`. Si la web no
  muestra la versión esperada, la instancia está vieja → rebuild (BR-020).
- **BR-025 LLM resiliente**: toda llamada Gemini (`analyze` + `review` vía
  `call_gemini` y `judge` vía `judge_call`) reintenta errores transitorios
  (429/5xx/`UNAVAILABLE`/`RESOURCE_EXHAUSTED`/timeouts) con backoff (4×
  5/15/45s en analyze/review; 3× 5/15s en judge); definitivos (400/403/JSON
  inválido) fallan rápido. Cada reintento se loguea a stderr
  (`[analyze]`/`[judge] gemini intento i/N …`) y es visible en el log de la web.
  Cuando la cadena entera del juez falla (429 persistente), degrada a asesor
  sin veredicto (`score: -1`), nunca bloquea la entrega.
- **BR-029 Verificación visual (analyze/review, prompts v3)**: con `source.mp4`
  presente y prompts v3+, `analyze` (tras proponer el plan) y `review` (tras
  los verdicts de texto) corren `vision_review`: pase multimodal por lotes de
  6 candidatos con frames reales de cada rango (cantidad variable, `frames.py`);
  veta solo bloqueantes visuales (sujeto invisible, gráfico referenciado
  invisible, encuadre roto, incoherencia con título) aplicando `drop`,
  anotando `vision` por clip y `{status, kept, dropped}` en clips.json.
  Asesor: sin video/API/prompt o con `YT_SHORTER_NO_VISION` vale el plan
  textual. Prompts: v3 (default hasta validar) / v4 (`prompts/v4/vision.md`) — v4 = cobertura total + reviewer no-estético.
- **BR-030 Piso de volumen (v4)**: todo run entrega ≥ `max(8, duración//4min)`
  clips (tope `MAX_CLIPS`, override `YT_SHORTER_MIN_CLIPS`); si el editor LLM
  propone menos, `fallback_clips` (determinista, sin red, alineado a frases,
  score ≤62) completa el piso sin desplazar a los clips del LLM. El volumen
  no depende del humor ni de la cuota del modelo.
- **BR-031 Funnel visible**: `manifest.json` incluye `funnel` con propuestos,
  drops de cada etapa (visión analyze / review / visión review), ajustes,
  piso y respaldo local; invariante `propuestos = final + drops`. Ninguna
  etapa descarta en silencio.
- **BR-032 Entrega resiliente**: con API caída, sin cuota o sin claves, el
  pipeline completa igual: las etapas LLM son asesoras y degradan (se anota
  el motivo), el volumen y los renders salen del camino local.
- **BR-028 Juez independiente y umbral en código**: el juez no comparte
  prompt/rúbrica con el editor y su cadena es configurable:
  `GEMINI_JUDGE_MODEL` (default `gemini-3.6-flash`) con respaldo
  `GEMINI_JUDGE_FALLBACK` (default `gemini-2.5-flash`); el primero que responde
  firma el veredicto y `judgment.json` registra `model`. Nota 2026-10-17/18: la
  API retiró `gemini-2.5-pro` (404 para keys nuevas), el free tier da
  `limit: 0` a los pro y 20 req/día por modelo (bucket separado por modelo):
  el editor usa 3.8-flash y el juez 3.6-flash para no competir por cuota y
  mantener generación distinta. El umbral
  `ship ⇔ score ≥ 70` se aplica en código (`SHIP_MIN_SCORE`), no se delega al
  modelo: un `ship:true` con score menor se degrada y se anota. Frames de
  evidencia variables por duración (~1 cada 12s, piso 4, techo 10, `frames.py`).

# Investigación: herramientas para ytshorter (v0.6.0, 2026-10-18)

Estado: investigado y **verificado contra fuentes primarias** (docs oficiales, PyPI, repos).
Los precios/límites de los proveedores cambian: las cifras llevan fecha y fuente.

## 0. Correcciones tras el doble chequeo (lo que NO era cierto o era impreciso)

| Claim inicial | Realidad verificada |
|---|---|
| Cerebras tiene free tier | No desde ~jul 2026: es trial de $5 que expira a 30 días y pide tarjeta. No sirve como fallback permanente. |
| "WhisperX o stable-ts para word timestamps" | Groq ya devuelve timestamps **por palabra** (`response_format=verbose_json` + `timestamp_granularities=["word"]`). No hace falta traer torch+wav2vec2 (~2-3GB) para el camino principal. |
| pysubs2 como writer ASS | MIT y sin deps, pero **requiere Python >=3.12** (contenedor usa 3.11). O se sube la base a 3.12, o se baja a pysubs2 1.8.1, o se mantiene nuestro writer (que ya está validado). |
| Silero VAD "liviano" | El paquete pip `silero-vad` **requiere torch>=1.12** (pesado). El modelo en sí son ~2MB; se puede usar el ONNX directo con onnxruntime sin el paquete. |
| Groq vision libre | Existe (`qwen/qwen3.8-27b` multimodal: texto+imagen, JSON mode) pero **máximo 3 imágenes por request** (2048 tokens c/u) — nuestros lotes de visión usan ~6 frames/candidato × 6 candidatos. |
| promptfoo "solo Node" | Es MIT, corre con npm/brew **y `pip install promptfoo`**; el CLI pide Node >=22.22 igual (el wrapper pip es de conveniencia). |
| LiteLLM "budgets como ledger" | Fallbacks/prioridad/cooldowns/rpm-tpm **sí** son SDK. Budgets persistentes y caching semántico son features del **proxy+DB** (Postgres/Redis) — para nosotros overkill. |
| auto-vertical-reframe como dependencia | Beta, **solo testado en macOS** (default `h264_videotoolbox`), sin tests. Sirve como **referencia de algoritmo**, no como dependencia. |
| OpenRouter free | Límites **no confirmados** en docs oficiales (plantillas vacías). Tercer fallback con pinzas. |

## 1. Cuota LLM — Groq cambia el juego (ADD, verificado)

Fuente: https://console.groq.com/docs/rate-limits (free plan, sin tarjeta, no expira)

| Modelo | RPM | RPD | TPM | TPD | Notas |
|---|---|---|---|---|---|
| `openai/gpt-oss-120b` | 30 | 1.000 | 8K | 200K | contexto 131K; **structured outputs strict** (JSON schema garantizado) |
| `openai/gpt-oss-20b` | 30 | 1.000 | 8K | 200K | ídem, más rápido/barato |
| `qwen/qwen3.8-27b` | 30 | 1.000 | 8K | 200K | multimodal (3 imgs/req), JSON mode, structured outputs |
| `whisper-large-v3-turbo` | 20 | 2.000 | — | — | ASH 7.2K / **ASD 28.8K** (8h audio/día), 25MB por archivo (free) |
| `whisper-large-v3` | 20 | 2.000 | — | — | ídem, más preciso, $0.111/h en dev |

- **Strict JSON schema** en los 3 modelos de texto (docs: https://console.groq.com/docs/structured-outputs) → nuestro contrato de JSON deja de ser "parseá y rezó".
- Whisper turbo acepta mp4/m4a directo, devuelve palabras con tiempos (`timestamp_granularities=["word"]`) y metadatos de calidad (`no_speech_prob`, `avg_logprob`). Precio dev: $0.04/h.
- Caveat real: **8K TPM por minuto** es bajo para prompts de select con chunks largos (~8-9K tokens) → 1 request c/min efectivo por modelo, o chunks más chicos. Con 2 modelos + 2 buckets hay margen.
- Términos free: revisar https://console.groq.com/docs/your-data antes de decidir (pendiente).

### Presupuesto de cuota por video (40 min, estimación con P4/P5)
| Etapa | Proveedor sugerido | Llamadas |
|---|---|---|
| select (por chunk) | Groq gpt-oss-120b | 3-5 |
| review + vision-review | Groq (texto) + Gemini (imágenes) | 1-2 + 6-10 |
| judge (batch 3-4 shorts) | Groq gpt-oss-20b | 3-5 |
| transcribe (sin subs YT) | Groq whisper turbo | 2-3 (chunks de ~20 min) |
| **Gemini** | solo visión | ~15 llamadas/día máximo → 2 videos/día sin tocar los 20/día de 3.8-flash |

### LiteLLM (opcional, REPLACE de `_judge_chain`)
SDK `Router` da: fallbacks por grupo, orden/prioridad (`order: 1,2,3`), cooldowns y retries, límites rpm/tpm por deployment. Sin proxy no hay budgets persistentes ni semantic cache. Recomendación: **no adoptar todavía** (nuestras cadenas son simples); si en P5.1 el hand-rolled se ensucia, migrar. Licencia MIT.

## 2. Transcripción (REPLACE + ADD local barato)

- **Groq whisper-large-v3-turbo** (verificado arriba): camino nuevo "sin subs": yt-dlp audio → m4a → Groq (chunks <25MB) con palabras + metadata de confianza. Reemplaza a faster-whisper como fallback 1.
- **faster-whisper local** queda como fallback offline, pero con modelo moderno: `WhisperModel("turbo")` es alias válido (README SYSTRAN); conversiones CT2: `dropbox-dash/faster-whisper-large-v3-turbo`, `deepdml/faster-whisper-large-v3-turbo-ct2`, y oficial `distil-whisper/distil-large-v3.5-ct2` (1.5× turbo, WER short-form mejor).
- **loudnorm pre-ASR** (`-af loudnorm=I=-16:TP=-1.5:LRA=11`): caso documentado de 14 min perdidos en 1h por audio bajo; mejora WER gratis. (Vía Qraft/blog, verificado como práctica estándar.)
- VAD: Silero (MIT) si aceptamos torch; alternativa sin dep: `ffmpeg silencedetect` para silencios + no_speech_prob de Groq para filtrar alucinaciones. Recomendado empezar por esto último.

## 3. Selección de clips (ADD)

- **PySceneDetect 0.7.2** (BSD-3-Clause, py>=3.10, `scenedetect-headless` para servidores): cortes de escena → (a) bordes de clip alineados a cortes, (b) "super-bloques" ~120s con metadata (cortes, diálogo, RMS) para el prompt de select — patrón MovieShort-AI; menos tokens, mejor grounding. https://www.scenedetect.com
- **RMS de audio sin librosa**: `ffmpeg -af astats` (metadata por frame) o `ebur128` — evita la dependencia pesada de librosa/numba. Sirve para rankear `fallback_clips` y anotar el prompt.
- "Tighten": remover muletillas/silencios largos y re-timear captions (patrón chopify, MIT). Con nuestros word timings (0.07-0.19s MAE) esto es barato y sube percepción de calidad.

## 4. Reframe vertical (REPLACE, donde el juez nos mató 4/4)

Doctrina AutoFlip + One Euro filter: **"no muevas la cámara salvo que haga falta"** — por escena decidir `static | pan | track` (hotclip lo implementa así; el One Euro filter es algoritmo público, implementar propio ~30 líneas, NO copiar de hotclip que es AGPL-3.0).
- Tracking: **MediaPipe** (Apache-2.0, detección cara+pose) y/o YOLO11-seg+ByteTrack (`ultralytics` es **AGPL-3.0** → ojo si algún día esto se distribuye).
- Layouts por video (patrón OpenShorts MIT): `TRACK` (hablante), `GENERAL` (blur), `SPLIT` (dos personas apiladas, captions en la unión), `SCREENCAST` (pantalla + presentador chico). Esto ataca directo el rechazo por "UI visible / infografía ilegible".
- Referencia CLI: auto-vertical-reframe (MIT, pero macOS-only y beta: solo ideas).

## 5. Subtítulos (mantener; 1 suma opcional)

- Nuestro ASS custom con karaoke continua queda (validado con ground truth). No cambiar de motor.
- Estilos preset tipo "hormozi/mrbeast" (colores) por ser el formato que retiene en shorts (chopify). Config, no dependencia.
- Si Python se sube a 3.12+: `pysubs2` (MIT, sin deps) como writer ASS más robusto. Opcional.

## 6. Evals (ADD)

- **promptfoo** (MIT; `pip install promptfoo` o npm; CLI corre local): evalúa v3 vs v4 vs v5 con `llm-rubric`, caching, matriz, CI y `optimize` para proponer mejoras de prompt. Juez de las evals: Groq gratis. https://www.promptfoo.dev
- Nuestro QUALITY_LOG queda como bitácora humana; promptfoo agrega regresión automatizada de prompts.

## 7. Audio final (ADD)

- `loudnorm I=-14:TP=-1.5` en el render final (estándar TikTok/Shorts/Reels; todos los competidores lo hacen).
- **DeepFilterNet** (MIT, pip `deepfilternet` 0.5.6, sin dep de torch) solo si hay ruido — flag opcional, no default (trata música como ruido).

## 8. SUBTRACT (adelgazar)

1. **faster-whisper fuera del build default** si Groq+subs YT cubren: -1GB de imagen, `WITH_LOCAL=0` deja de ser "gimped" (whisper queda como extra).
2. `youtube-transcript-api` pasa a 3er fallback (mismo rol que hoy pero menos crítico).
3. Judge por lote (P4.2) + cache por hash existente: menos llamadas.
4. No sumar torch/torchaudio/librosa/whisperx: mantener imagen slim.

## 9. Licencias (resumen)

| Herramienta | Licencia | Uso |
|---|---|---|
| Groq API / promptfoo / LiteLLM / PySceneDetect / silero-vad / DeepFilterNet / MediaPipe / pysubs2 / One Euro (algoritmo) | MIT / BSD / Apache → compatible | Usar/adaptar sin problema |
| ultralytics YOLO | AGPL-3.0 | Solo uso interno; si se distribuye el binario, obliga AGPL |
| hotclip | AGPL-3.0 | Solo leer ideas, no copiar código |
| chopify / OpenShorts / clippyme | MIT | Patrones y snippets reutilizables con atribución |
| ytshorter (este repo) | sin LICENSE | Decidir (sugerido MIT para repo privado mantenido) |

## 10. Pendientes de verificar (al implementar)

- [ ] Términos free de Groq (`/docs/your-data`): retención/entrenamiento con datos free.
- [ ] OpenRouter free: límites reales (docs con placeholders).
- [ ] Precio Gemini paid (escape hatch si free no alcanza): ~$1.5/M in flash (fuente terciaria, verificar en pricing).
- [ ] pysubs2 en py3.11 → usar 1.8.1 o subir base a 3.12.
- [ ] YouTube Data API para auto-upload (fuera de alcance P5; quota conocida ~10K units/día, upload=1600 → ~6/día).

## Fases P5 propuestas (orden por dependencia)

| Fase | Qué | Criterio de aceptación |
|---|---|---|
| **P5.1** | Proveedor Groq texto (select/review/judge) con cadena Groq→Gemini; `GROQ_API_KEY`; provider en config; BR "proveedores intercambiables, quota por proveedor" | Suite verde; run real de 1 video con select/review/judge 100% Groq; funnel igual o mejor |
| **P5.2** | Transcribe v2: loudnorm pre-ASR; fallback Groq whisper (palabras+confianza) antes que local; local `turbo` en extras | Mismo transcript del video 2; karaoke MAE ≤0.25s con palabras Groq |
| **P5.3** | Select v5: PySceneDetect headless + RMS con ffmpeg astats en el prompt | +2-4 clips/run con scores ≥70; sin tocar cuota extra |
| **P5.4** | Reframe v3: escenas + One Euro propio + modos static/pan/track + layout SPLIT/SCREENCAST | Juez deja de marcar "UI visible/encuadre roto" en 2 de 3 videos |
| **P5.5** | promptfoo: evals v4 vs v5 (select/judge) sobre Groq | Baseline de wins/regresiones commiteado en repo |
| **P5.6** | Pulido: loudnorm final, tighten muletillas/silencios, presets de estilo | Mejora perceptible en A/B ciego del juez |

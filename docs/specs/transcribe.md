# SPEC: transcripción

## Contrato (`transcribe.py`)

Orden de intentos (el error final siempre incluye el motivo real de cada vía):

1. Subs ya bajados en el workdir (`subs.<lang>.json3/.srt`) — cache del fallback.
2. `yt-dlp` de subtítulos (`json3/srt/best`, un idioma por intento: `es`,
   `es-orig`, `en`, `en-orig`). **Primero** porque el json3 de auto-captions
   es la única vía con word-timings reales (`segs[].tOffsetMs` → `words`),
   de donde sale la sincronía del karaoke. Reusa `YT_SHORTER_COOKIES`. Un 429
   en `en` no invalida un `es` ya bajado. Parser json3 propio (eventos chunk o
   ventanas rodantes → `_dedupe_rolling`, word-aware). `source: yt-dlp-subs`.
3. `youtube-transcript-api` (es/en, manuales antes que auto). Gratis,
   instantáneo, con puntuación real (solo texto: sin words). Reintenta 3× con
   backoff solo errores transitorios (`RequestBlocked`, `IpBlocked`, 429,
   timeouts…); un `NoTranscriptFound`/`TranscriptsDisabled` corta al instante
   (no se arregla reintentando).
4. Fallback whisper local (`faster-whisper`, `base`, int8, CPU) solo si no hay
   subtítulos. Import perezoso: el path de cache/captions nunca lo toca.
   Un transcript cacheado sin `words` se enriquece solo (json3 local o yt-dlp)
   en el próximo `transcribe` sin exigir `--force` (`_enrich_words`).
5. Sin whisper instalado (imagen slim) → error claro con los motivos reales
   (`api RequestBlocked: …; yt-dlp …`) + qué hacer (reintentar, cookies,
   extra `local`), nunca `ModuleNotFoundError` crudo ni un "sin subtítulos"
   que oculte un bloqueo transitorio.

Salida `transcript.json` `{video_id, source, segments[]}`; segmentos con
`words` cuando hay (whisper) o sin ellos (captions → se estiman después).
`source`: `youtube-captions` | `yt-dlp-subs` | `whisper`.
`doctor` reporta `whisper_local` sin exigirlo (slim es válido).

## Casos borde

- YouTube limita por IP (429) después de una descarga larga: la API suele
  fallar ahí; el fallback yt-dlp (cookies) o el reintento lo salvan.
- Video sin subtítulos generados aún (upload fresco) y slim → `transcribe`
  falla con el motivo; el pipeline corta ahí (correcto: sin timings no hay clips).
- `force` re-transcribe aunque exista `transcript.json` (reusa `subs.*` locales
  si están: sin red).

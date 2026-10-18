# SPEC: descarga resiliente

**Problema (sesión 2026-10-16)**: `Read timed out` de googlevideo mató un job
en `download 1/6` tras agotar reintentos; además la URL traía un ID de 10
caracteres (truncado) que debió rechazarse antes de 70s de descarga condenada.

## Contrato (`download.download_url`)

1. **Validación temprana**: `video_id == "unknown"` (ni 11 chars de YouTube ni
   archivo local) → `ok: False` inmediato, sin red, sin crear carpetas.
2. **Reintentos en 2 niveles**: yt-dlp con `retries`/`fragment_retries` 10 y
   `socket_timeout` 60; además hasta 3 intentos a nivel función con backoff
   5s/10s. Los `.part` se conservan: cada intento **retoma**, no re-descarga.
3. **Cache validado**: `info.json` corrupto → se re-descarga (no crash).
4. Error final corto (últimas 300 chars), nunca el traceback entero de yt-dlp.

## Casos borde

- Bot-check / login requerido → falla igual tras reintentos; el mensaje
  conserva la pista (`Sign in to confirm`) y el remedio es `YT_SHORTER_COOKIES`.
- Interrupción a mitad (kill) → `.part` huérfano; siguiente corrida retoma.

## Evals

`tests/test_fase2.py`: id inválido sin red, reintento tras timeout, info
corrupto re-descarga.

# SPEC: observabilidad del pipeline

**Problema (sesión 2026-10-16)**: jobs solo decían `running`; 20+ min de
ffmpeg en silencio; ETA inexistente. Evolucionó en 3 iteraciones
(etapa x/8 → tiempos por etapa → `%` por encode). La 1ª línea del log incluye
la versión (`vX.Y.Z`) para detectar builds viejos (BR-024).

## Contrato

- `work/jobs/<jid>.progress.json`: `stage/stage_idx/8` (con `review` entre
  `analyze` y `clip`, y `judge` entre `caption` y `package`), `status`,
  `started/updated/elapsed_s`, `stage_times{}`, `stage_start`,
  `eta_s` + `eta_by_stage{}` + `eta_source` (`history|linear|none|done`),
  `substage/sub_idx/sub_total/sub_pct` en clip/caption.
- ETA histórica: `stage_history.json` (últimas 50 duraciones/etapa, solo
  éxitos). Sin historial → lineal rotulada.
- `ffmpeg.run_with_progress`: `-progress` inyectado solo en ejecución
  (`ffmpeg_cmd.sh` queda reproducible), `on_tick(frac)` throttled 2s,
  errores como `run(check=True)` con el comando limpio.
- Logs: `[pipeline] vX.Y.Z url=… stages=8` y `[pipeline] [i/8] <etapa>
  start|ok|FAIL <s>` y `[clip i/N] <id> <s>`
  a stderr; yt-dlp `noprogress`; `log_tail` 50 líneas.
- Superficies: web (tabla etapa/estado/t/ETA + sub-barra), `jobs` (+`--watch`),
  JSON (`--json`).

## Casos borde

- Sin `job_id` (CLI directo) → sin progress, todo funciona igual.
- Primeras corridas sin historial → ETA lineal aproximada (rotulada).
- `progress.json` corrupto → se ignora (job sigue `running` por PID/log).

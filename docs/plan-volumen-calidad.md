# Plan P4 — volumen garantizado + calidad auditada (v0.6.0)

**Pedido (2026-10-18)**: "volumen y calidad": una corrida de un video largo
debe entregar TODOS los shortcuts buenos (como la experiencia v0.4.0: ~15-20),
no 4. La calidad (captions, framing, coherencia) se audita, no se usa para
podar el set.

## Principio rector

Separar **generar** (determinista, sin cuota) de **auditar** (LLM asesor que
jamás recorta el set). Si la API falla o no hay cuota, el volumen no se cae:
se degrada el juicio, no la entrega.

## Límites reales (free tier, 2026-10)

- `gemini-*.pro`: `limit: 0` (no existe en free tier); `gemini-2.5-pro`
  retirado (404 para keys nuevas).
- Flash: **20 requests/día POR MODELO** (bucket separado por modelo).
- Un run de ~20 shorts debe caber en un día: repartir etapas por modelo
  (`GEMINI_MODEL_SELECT/REVIEW/VISION/JUDGE` → 3.8/3.7/3.6/3.5-flash) y
  batchear llamadas (select por lote, judge 3-4 shorts/llamada).

## Fases

### P4.0 — local, 0 cuota (esta sesión)

1. **contain v2** (`reframe.py`): fondo = copia miniatura desenfocada
   (`scale=270:480,gblur`), oscurecida; encode ~10× más barato que
   `boxblur=30` a 1080x1920. Mata el "blur masivo" que el juez rechazó.
2. **encode paralelo** (`clip.py`, `caption.py`): pool de workers
   (`YT_SHORTER_JOBS`, default `min(4, nproc//2)`), progreso thread-safe.
   Hoy: 23 min/4 clips → objetivo <10 min/20.
3. **piso de volumen local** (`sentences.py` + `analyze.py`): si el LLM
   propone menos de `min_candidates = max(8, minutos//4)`, un fallback
   determinista propone ventanas por densidad de habla alineadas a frases
   (sin cuota). El volumen deja de depender del humor del modelo.
4. **manifest con funnel** (`package.py`): propuestos → post-review →
   post-vision → final, con razones de cada drop. Transparencia: "¿dónde se
   fue mi volumen?".
5. Tests RED→GREEN de lo anterior; suite completa verde; rebuild contenedor.

### P4.1 — prompts v4 + re-run (necesita cuota)

6. `prompts/v4/`: editor con objetivo de volumen explícito ("todos los
   pasajes autocontenidos, típico 12-25"); reviewer solo arregla
   bordes/anáforas y descarta incoherencia dura (nunca estética).
7. Smoke de 1 llamada (analizar video corto) → si el volumen sube, flip
   `prompts_version` default a v4.
8. Re-run de los 3 videos + QUALITY_LOG comparando vs `data/regress/`.

### P4.2 — auditoría barata (cuota acotada)

9. **judge por lote**: 1 llamada audita 3-4 shorts (collage de frames por
   short) → 20 shorts ≈ 5-7 llamadas en vez de 20.
10. **quota ledger** (`work/quota.json`): contador por modelo/día; el
    pipeline avisa antes de arrancar etapas con LLM si no alcanza y degrada
    limpio (asesor).
11. Modelos por etapa vía env (`GEMINI_MODEL_SELECT/REVIEW/VISION/JUDGE`).

### P4.3 — señales locales + framing escena-aware

12. **prepass** (`signals.py`, 0 cuota): energía audio, cambios de escena,
    densidad de habla, `cropdetect` (barras negras) → `signals.json`.
    Alimenta: sugerencias al select, cortes por escena, y "nunca UI visible":
    pre-crop de barras/letterbox de la fuente antes de decidir crop/contain.
13. Framing por escena: cara → crop con seguimiento; infografía → contain v2
    (o zoom a región activa).

## Contratos (BR nuevas)

- **BR-030 piso de volumen**: todo run entrega ≥ `min_candidates` clips
  (LLM + fallback local); los drops son solo por causa dura y quedan en el
  funnel con razón.
- **BR-031 funnel**: `manifest.json` incluye el embudo por etapa; ninguna
  etapa puede descartar en silencio.
- **BR-032 cuota**: con la API caída o sin cuota, el pipeline completa
  igual (juicio asesor degradado, volumen intacto).

## Evals

- Volumen: `analyze` con `call_gemini` mockeado devolviendo 1 clip → el
  fallback local completa hasta el piso (determinista, sin red).
- Framing: filtro contain v2 (miniatura antes del blur, sin `boxblur` a
  resolución completa) + encode humo real de 1s.
- UI visible: pendiente P4.3 (cropdetect) — eval de barras detectadas.
- Regresión: los 3 videos de `data/regress/` (comparación por funnel y
  ships, no por igualdad exacta: los modelos no son deterministas).

## Riesgos

- v4 sin validar hasta que resetee la cuota (default queda v3 hasta el
  smoke).
- Paralelismo: RAM/CPU; se limita con `YT_SHORTER_JOBS` y se mide.
- Judge por lote: más tokens por llamada; medir contra el límite por minuto.

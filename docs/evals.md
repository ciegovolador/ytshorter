# Evals

Tres niveles, distintos propósitos:

| Nivel | Dónde | Qué verifica |
|-------|-------|--------------|
| unit | `tests/test_fase*.py`, `test_smoke.py` | Lógica pura y contratos de función |
| e2e | `tests/test_fase4.py::test_e2e_*`, `test_fase6.py` | Etapas reales con ffmpeg / pipeline mockeado |
| **eval** | `tests/test_evals.py` + `tests/fixtures/` | Reglas de negocio contra **datos reales de sesión** |

## Reglas de un buen eval

1. Nombrado `EVAL-NN` + referencia a la sesión (`short_20`, `short_13`…).
2. Fixture mínimo extraído de datos reales (slice, no el mp4 de 70MB —
   no cabe en el repo; lo pesado se sintetiza).
3. Bloquea el comportamiento observado: valores exactos (regresión) **y**
   propiedades (la regla general).
4. Si falla, mirar primero `FEEDBACK.md` (contexto del hallazgo original).

## Dataset de sesión

| Fixture / caso | Origen | Evals |
|----------------|--------|-------|
| `tests/fixtures/short20_transcript.json` | slice 2950-3015s de `qJxtOQdnRAY` (21 segs) | EVAL-01–04 |
| caja roja lateral (sintético) | proxy del caso short_20/flechas | EVAL-05 |
| testsrc plano (sintético) | fallback sin caras | EVAL-06 |
| `cut.mp4` trunco (sintético) | caso short_10/moov | EVAL-07 |
| frames short_13/20 | verificación visual manual (ver `specs/framing.md`) | manual |

## Comandos

```bash
python3 -m pytest tests/test_evals.py -q   # solo evals
python3 -m pytest tests/ -q                # todo: unit + e2e + evals
```

## Agregar un eval

1. Entrada en `FEEDBACK.md` (qué se vio en producción).
2. Fixture mínimo en `tests/fixtures/` (si es dato real).
3. Test `test_eval_*` con ID EVAL-NN.
4. Regla BR + línea en el spec correspondiente.

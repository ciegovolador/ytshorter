# docs — ytshorter

Fuente de verdad de decisiones. `PLAN.md` dice *qué* se construye; aquí vive
*por qué* funciona así y *cómo* se verifica.

## Mapa

| Doc | Qué responde |
|-----|--------------|
| `business-rules.md` | Reglas BR-001…: contratos que todo cambio debe respetar |
| `specs/containers.md` | Puertos, volúmenes, imagen slim/full |
| `specs/pipeline-observability.md` | Progreso, ETA, logs, jobs |
| `specs/clip-boundaries.md` | Snap a frase (short_20) |
| `specs/captions.md` | Subtítulos marketing (karaoke, CPS, fuente) |
| `specs/framing.md` | Crop por contenido (short_13, short_20) |
| `specs/transcribe.md` | Captions-primero, fallback whisper opcional |
| `specs/download.md` | Descarga resiliente (reintentos, ID válido) |
| `specs/review.md` | Doble instancia: review en runtime + judge asesor |
| `evals.md` | Metodología de evals + dataset de sesión |

## Convenciones

- Módulos <300 líneas, un subcomando = una cosa (UNIX), idempotente + cache.
- Logs de pipeline a stderr con prefijo `[pipeline] [i/8]`; stdout solo JSON.
- Cada hallazgo de sesión → entrada en `FEEDBACK.md` + regla BR + eval si aplica.
- Evals viven en `tests/test_evals.py` con fixtures en `tests/fixtures/`.

## Loop de desarrollo

```bash
python3 -m pytest tests/ -q            # unit + e2e + evals (todo)
python3 -m pytest tests/test_evals.py -q  # solo evals de sesión
podman build -t ytshorter .            # requerido tras tocar src/ o web/
podman run -d -p 9000:9000 --env-file .env -v ./data:/data:Z --name ytshorter ytshorter
```

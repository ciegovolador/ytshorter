# SPEC: doble instancia — review en runtime + judge asesor

**Problema (sesión 2026-10-16)**: clips irrelevantes o mal encuadrados llegaban
a `dist/` sin que nadie los cuestionara; el editor (instancia 1) no se
auto-corrige. Veredicto real del juez sobre short_13: 65 no-ship (cara
cortada); short_20: 2 no-ship (flechas fuera de cuadro en ese render).

## Puerta plan→review→execute (etapa 4/8, entre `analyze` y `clip`)

1. `analyze` propone clips (plan) con prompts editor/virality/packaging y deja
   `review: {status: pending}`.
2. La etapa explícita `review` (`ytshorter review work/<id>/`, `review.py`)
   llama a `review_clips` (2ª llamada, prompt `prompts/v3/reviewer.md`):
   keep/drop/adjust con motivo. Sin LLM o con error → vale el plan (log).
   El prompt v2 agregó coherencia interna dura (salto de tema o anáfora
   huérfana → `drop`, no `adjust`); v3 agrega criterios visuales.
2b. Verificación visual (BR-029, prompts v3): analyze y review corren
   `vision_review` por lotes con frames reales de cada rango y vetan
   bloqueantes visuales (`drop` + anotación `vision`). Asesor: si falla,
   vale el plan.
3. `apply_verdicts`: drop permitido; adjust solo si 10-170s y válido; resto keep.
   Todo veredicto queda en `clips.json: review + clip.review`.
4. Reciclado acotado (Evaluator-Optimizer, BR-026): drops ≥40% y ≥4 clips →
   `analyze` re-corre UNA vez con las críticas (Reflexion) y review pasa de
   nuevo con `force`; si algo falla se restaura el plan previo.
5. Skip con `YT_SHORTER_NO_REVIEW=1` (y reciclado con `YT_SHORTER_NO_REVISION=1`).

## Juez asesor (`judge` 7/8 en pipeline; CLI `ytshorter judge dist/<vid>/`)

- Multimodal: 3 frames JPEG + título/hook + stats de captions + framing.
  El contexto sale de `title.txt`/`metadata.json` si existen (dist) o de la
  entrada de `clips.json` si el paquete aún no está (la etapa 7/8 corre antes
  que `package`); jamás audita a ciegas.
- Rúbrica hook 30 / encuadre 25 / captions 20 / cierre 15 / coherencia 10.
  `ship` solo con score ≥70 y sin bloqueante.
- Escribe `judgment.json` por short (cacheado por mtime del `video.mp4` y
  `JUDGE_VERSION`; `force` re-audita). **Asesor, no puerta**: jamás borra ni
  bloquea (fallo del juez → `ship: true, score: -1` + nota); el pipeline lo
  corre como etapa no fatal (skip `YT_SHORTER_NO_JUDGE=1`).
- `package` copia `judgment.json` al dist (BR-018/027).
- Limitación honesta v1: 3 frames pueden caer en gaps sin caption; el juez
  puede reportar "sin captions" erróneamente en clips ralos.

## Evals

Puerta: `test_fase3.py` (apply keep/drop/adjust, inválidos→keep, LLM roto→plan,
integración con `call_gemini` mockeado). Juez: `tests/test_judge.py` (guarda
veredicto, API caída no bloquea, cache por mtime, `caption_stats`). Bucle:
`test_fase6.py` (should_replan, critique_from_review, reciclado end-to-end
mockeado con Reflexion).

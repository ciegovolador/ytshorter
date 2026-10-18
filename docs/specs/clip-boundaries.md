# SPEC: límites de clip en frase (short_20)

**Problema (sesión 2026-10-16)**: `short_20` empezaba en `...estas flechitas`
(mitad de frase) y terminaba en `todas estas | flechitas con rojo`. El `snap`
anterior ajustaba a bordes de *segmento*, pero los auto-subtítulos llegan como
ventanas que también cortan a mitad de frase. Evals EVAL-01/02/03.

## Contrato

- `analyze.merge_stream(segments) -> words[{start,end,text}]`: une ventanas
  solapadas por coincidencia de texto (overlap join); whisper-words se
  respetan tal cual.
- `analyze.build_sentences(segments) -> [{start,end,text}]`: parte por
  `[.?!…]`. Sin puntuación, el bloque entero es una frase.
- `analyze.snap_to_sentences(clips, segments, max_dur=170)`: inicio → inicio de la frase
  que lo contiene (salvo >60% avanzada → siguiente frase); fin → fin de su
  frase (salvo <40% → frase anterior). Ajuste total ≤~12s; techo 170s. El piso
  (10s) lo aplica el filtro: un fragmento no se rellena hasta el piso,
  se descarta (rellenar fabricaría contenido fuera de la idea).

## Casos borde

- Sin frases (vacío) → clips intactos.
- `etc.` parte frase (falso positivo aceptado: auto-captions raramente puntúan).
- Whisper con palabras reales → gaps >1.2s también podrían partir (no
  implementado; documentado como mejora).

## Evals

`tests/test_evals.py::test_eval_short20_*`, `test_eval_merge_no_duplica`
(fixture `tests/fixtures/short20_transcript.json`, slice real 2950-3015s).

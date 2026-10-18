# SPEC: subtítulos marketing (karaoke, CPS, fuente)

**Problema (sesión 2026-10-16)**: frase completa fija en DejaVu 64 al borde
inferior (lo tapa el UI de TikTok). Referencias: canon Hormozi/Submagic,
Netflix ≤20 CPS adultos, guías libass `\k`. Eval EVAL-04.

**Fix sync (sesión 2026-10-17)**: el json3 trae `tOffsetMs` real por palabra
(se materializa en `words`; MAE 0.07-0.19s vs whisper); y el `\k` multilínea
ahora usa reloj CONTINUO entre líneas (`_karaoke_lines`), sin el salto de ~1s
que reiniciaba el sweep al cruzar `\N`.

## Contrato (`subtitles.py` + `burn.py`, orquestados por `caption.py`)

- Karaoke `\k` por palabra: sweep de cada palabra llega al inicio de la
  siguiente (absorbe silencios) — incluso cruzando de línea (reloj continuo a
  través de `\N`); suma de `\k` == duración del evento (cs).
  Amarillo `#FFEB00` (dicha) sobre blanco (por decir).
- Timings: palabras reales (json3 `tOffsetMs` o whisper) se confían tal cual;
  si no, reparto ponderado por caracteres. Rolling duplicado se descarta
  (recientes 12 palabras, tolerancia 0.05s). Mín 120ms/palabra, lead 40ms,
  hold +200ms última, mín 0.5s/bloque.
- Bloques ≤8 palabras (2 líneas × 4), CPS objetivo ≤20, ≥0.5s.
- Estilo ASS: fontsize 84, outline 6, shadow 2, Alignment 2, MarginV 480
  (tercio medio-bajo, libre del UI). Fuente: Montserrat > Inter > Poppins >
  DejaVu (`pick_font()`, override `YT_SHORTER_FONT`); `fonts-montserrat` en imagen.
- Quemado con filtro `ass=` (nunca `subtitles`: aplana el karaoke).
- SRT con el mismo troceado. Sin palabras → sin `Dialogue` → caption usa
  copia sin re-encode (`has_subs` falso).
- `clip_segments` recorta palabras a medio decir en el borde (<0.3s fuera se cae).

## Casos borde

- Idiomas sin espacios (zh/ja/th): la estimación por palabras no aplica.
- Fuente sin glyphs non-latin → fallback DejaVu (documentar si se pide).

## Evals

`test_eval_caption_marketing_rules` (fixture real: 92 palabras, pico 19.4 CPS),
tests de suma `\k`, chunking y `has_subs` en `test_fase4.py`.

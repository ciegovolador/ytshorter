# SPEC: encuadre por contenido (short_13, short_20)

**Problema (sesión 2026-10-16)**: crop-center cortaba media cara (short_13,
rostro en x≈270-630/1280) y dejaba fuera las flechas rojas de las que habla
el presentador (short_20, columna x≈890-950). Verificado con frames reales.
Evals EVAL-05/06.

## Contrato (`reframe.choose_crop(source, start, end) -> (vf, info)`)

1. **Rostro grande**: Haar frontal en frames 320px; detecciones en ≥30% de
   frames con área mediana ≥3% → ventana sobre el rostro.
2. **Gráfico de alerta**: píxeles rojos concentrados (<25% del ancho) →
   ventana sobre el gráfico.
3. **Saliencia**: piel (con gate de saturación: el rojo no es piel) 40% +
   rojo 25% + saturación 20% + bordes 15%, con leve prior al centro.
4. Un crop **estático** por clip (x par, yuv420p). Excepción → `VERTICAL_VF`
   centro. **El crop nunca falla el clip.**
5. `info` → `short_XX/reframe.json` → campo `framing` en `clips.json` →
   `metadata.json` (señal para editor/QA; `reason` en español corto).

## Casos borde

- Fuente vertical/angosta → centro (no hay de dónde elegir).
- Sin cv2 → se salta rostros (saliencia igual funciona).
- Múltiples rostros → mediana de centros (mejora documentada: hablante activo).
- Texto denso sin picos (tablas) → ventana central con prior; aceptado.

## Evals

`test_eval_crop_sigue_grafico_lateral` (caja roja sintética → x > centro),
`test_eval_crop_no_mata_sin_caras` (ventana válida siempre). Caso real
documentado arriba (no cabe el mp4 de 70MB en el repo).

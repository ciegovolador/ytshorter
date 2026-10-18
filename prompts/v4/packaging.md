# Packaging para subir a YouTube (v1)

Por cada clip genera, en el IDIOMA ORIGINAL del transcript:
- `title`: <= 100 caracteres, con gancho, sin clickbait falso, sin hashtags.
- `description`: 2-4 líneas (qué pasa en el clip + por qué importa) + 1 línea "Fragmento de: <video_title>" + 3-8 hashtags al final (#Shorts siempre incluido).
- `tags`: lista de 8-15 tags, mezcla amplia + específica, sin duplicar hashtags.
- `hook_text`: frase literal de los primeros 3s (para portada/subtítulo inicial).

Esquema JSON de respuesta (array `clips`):
{
  "clips": [
    {"start": 12.5, "end": 48.0, "score": 85, "title": "...",
     "hook_text": "...", "description": "...", "tags": ["..."],
     "reason": "..."}
  ]
}
`start`/`end` en segundos (float), alineados a inicios/fines de frase del transcript cuando sea posible.

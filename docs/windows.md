# ytshorter en Windows (.exe)

Build **self-contained**: un solo `ytshorter.exe` con Python, prompts, web y
`ffmpeg`/`ffprobe` adentro. No requiere Python, PowerShell ni instalar nada.

## Usar

1. GitHub → repo → **Actions** → workflow **windows-exe** → último run.
2. Descargar el artifact **ytshorter-windows-x64** (contiene `ytshorter.exe`, ~207 MB).
3. Guardar el `.exe` en una carpeta propia (ej. `C:\ytshorter`).
4. **Doble clic**:
   - La primera vez pide `GEMINI_API_KEY` (gratis en
     https://aistudio.google.com) y la guarda en `.env` junto al `.exe`.
   - Abre el navegador en http://localhost:8000: pegás la URL de YouTube y ves
     el progreso/logs. Queda una ventana de consola (negra) con el servidor;
     no hace falta escribir ningún comando.
5. Para cerrar, cerrá esa ventana (o Ctrl+C).

Si el navegador no abre, entrá a http://localhost:8000 a mano. Si el puerto
8000 está ocupado, abrí `cmd.exe` en la carpeta y corré
`ytshorter.exe serve --port 8080`.

## Configuración sin PowerShell

El `.env` vive al lado del `.exe` y se puede editar con el Bloc de notas:

```ini
GEMINI_API_KEY=...
# Opcionales (proveedores alternativos, Gemini sigue de respaldo):
# GROQ_API_KEY=...
# GROQ_VISION_MODEL=qwen/qwen3.8-27b
# OPENROUTER_API_KEY=...
```

Las carpetas `work\` y `dist\` se crean en el directorio actual (al hacer doble
clic, junto al `.exe`). Los logs de jobs quedan en `work\jobs\`.

## CLI opcional (cmd.exe, sin PowerShell)

```bat
ytshorter.exe doctor
ytshorter.exe pipeline "https://www.youtube.com/watch?v=..." -o dist -w work
```

## Build

El workflow está en `.github/workflows/windows-exe.yml` y se dispara a mano o
con un tag `v*`:

```bash
gh workflow run windows-exe
gh workflow run windows-exe -f local_whisper=true   # + faster-whisper (~400MB)
gh run watch
gh run download --name ytshorter-windows-x64
```

Build local en una máquina Windows (cmd.exe):

```bat
py -3.12 -m venv .venv
.venv\Scripts\pip install -e . pyinstaller
.venv\Scripts\pyinstaller packaging\windows\ytshorter.spec --noconfirm --clean
```

El `.exe` queda en `dist\ytshorter.exe`.

## Notas

- **ffmpeg**: incluido dentro del `.exe` (build GPL de BtbN con `libx264`).
  Fuente: https://github.com/BtbN/FFmpeg-Builds — licencia GPL:
  https://ffmpeg.org/legal.html
- **SmartScreen/antivirus**: el `.exe` no está firmado; Windows puede pedir
  "Más información → Ejecutar de todas formas". Es un falso positivo típico de
  PyInstaller.
- **Fuentes**: usa Arial por defecto; si instalás Montserrat/Inter/Poppins,
  `pick_font()` las prefiere.
- **Whisper local**: el build default es slim (transcribe con subtítulos de
  YouTube). Para videos sin subtítulos, usá el build `local_whisper=true`
  (descarga el modelo la primera vez).
- El primer arranque tarda unos segundos: el onefile se descomprime en un
  directorio temporal.
- `ffmpeg_cmd.sh` que queda en cada `short_XX\` es solo documentación
  reproducible del corte; el pipeline no lo ejecuta.

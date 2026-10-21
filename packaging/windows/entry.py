"""Entry point del .exe Windows.

Doble clic (sin argumentos) = primera configuración + web local, sin
PowerShell: pide la API key una vez y la guarda en `.env` junto al .exe.
Con argumentos se comporta como el CLI normal (`ytshorter.exe doctor`, etc.).
"""
import os
import sys
import threading
import webbrowser

WEB_URL = "http://localhost:8000"


def _save_key(key: str) -> None:
    from pathlib import Path

    p = Path(sys.executable).resolve().parent / ".env"
    lines = []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        pass
    out = [ln for ln in lines if not ln.strip().startswith("GEMINI_API_KEY=")]
    out.append(f"GEMINI_API_KEY={key}")
    p.write_text("\n".join(out).strip() + "\n", encoding="utf-8")


def _bootstrap() -> None:
    from ytshorter.config import load_settings

    if load_settings().llm_configured():
        return
    print("=" * 64)
    print(" ytshorter — primera configuración (una sola vez)")
    print(" Pegá tu GEMINI_API_KEY (gratis: https://aistudio.google.com)")
    print(" Se guarda en .env junto al .exe; no hace falta PowerShell.")
    print("=" * 64)
    key = input("GEMINI_API_KEY: ").strip().strip('"').strip("'")
    if not key:
        print("Sin clave: la web abre igual, pero analyze/judge van a fallar.")
        return
    os.environ["GEMINI_API_KEY"] = key
    try:
        _save_key(key)
        print("Clave guardada en .env.")
    except OSError as e:
        print(f"No pude guardar .env ({e}); vale solo para esta sesión.")


def _run_web() -> int:
    from ytshorter.cli import main

    print(f"ytshorter listo en {WEB_URL}  (Ctrl+C para salir)")
    timer = threading.Timer(1.5, lambda: webbrowser.open(WEB_URL))
    timer.daemon = True
    timer.start()
    return main(["serve", "--port", "8000"])


def _utf8_stdio() -> None:
    """Consola/redirecciones Windows: evita UnicodeEncodeError con → y emojis."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    frozen = getattr(sys, "frozen", False)
    if frozen:
        _utf8_stdio()
    if frozen and len(sys.argv) == 1:
        _bootstrap()
        sys.exit(_run_web())
    from ytshorter.cli import main

    sys.exit(main())

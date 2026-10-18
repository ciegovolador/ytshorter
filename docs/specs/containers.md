# SPEC: contenedores

**Problema (sesión 2026-10-16)**: puerto 8000 ocupado → se movió a `9000:9000`
en código; `web/static` 500 en imagen (ruta de repo-root vs `pip install`);
disco lleno por builds (imágenes dangling + 34 volúmenes huérfanos + 64GB ollama).

## Contrato

- Imagen escucha `9000` (`EXPOSE` + `CMD --port 9000`); `compose.yml`
  `9000:9000`; datos en `/data` (`YT_SHORTER_WORK/OUT`).
- `web/static` y `prompts/` se resuelven en repo-root, `/app/...`, `$CWD`
  (overrides `YT_SHORTER_WEB_STATIC`, `YT_SHORTER_PROMPTS_DIR`).
- `data/work` + `data/dist` con `.gitkeep` en repo; contenidos ignorados.
- Run canónico: `podman run -d -p 9000:9000 --env-file .env -v ./data:/data:Z
  --name ytshorter ytshorter`. Re-nombrar/recrear: `stop + rm` antes (el nombre
  queda ocupado).
- Slim por defecto (ver `transcribe.md`); `.dockerignore` excluye
  venv/work/dist/data.

## Higiene de disco (lección de sesión)

- `podman container/image prune` tras builds fallidos; volúmenes anónimos
  (`VOLUME /data` sin `-v`) se acumulan: inspeccionar antes de borrar
  (pueden guardar la única copia de una corrida) y rescatar a `./data`.
- El verdadero hog suele estar fuera: aquí `ollama` 64GB (no tocar sin aviso).

FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core fonts-montserrat \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml setup.py README.md ./
COPY src/ ./src/
COPY prompts/ ./prompts/
COPY web/ ./web/
# Slim por defecto (sin faster-whisper: ~1GB menos). Full local:
#   podman build --build-arg WITH_LOCAL=1 -t ytshorter .
ARG WITH_LOCAL=0
RUN if [ "$WITH_LOCAL" = "1" ]; then pip install --no-cache-dir ".[local]"; \
    else pip install --no-cache-dir .; fi

ENV YT_SHORTER_WORK=/data/work \
    YT_SHORTER_OUT=/data/dist \
    YT_SHORTER_WHISPER_MODEL=base

VOLUME ["/data"]
EXPOSE 9000
CMD ["ytshorter", "serve", "--port", "9000"]

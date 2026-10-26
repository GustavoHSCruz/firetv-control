FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends adb ffmpeg ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /usr/local/share/scrcpy \
    && curl --fail --location --retry 3 \
       https://github.com/Genymobile/scrcpy/releases/download/v5.0.1/scrcpy-server-v5.0.1 \
       --output /usr/local/share/scrcpy/scrcpy-server \
    && echo '764eb6f79811d5211fe9df341120882ba9994c7a61b897d7bf3fb662e53bc536  /usr/local/share/scrcpy/scrcpy-server' | sha256sum --check \
    && useradd --uid 1000 --home-dir /data --no-create-home firetv \
    && mkdir -p /data/.android /data/tmp \
    && chown -R 1000:1000 /data

WORKDIR /app
COPY firetv_control/ ./firetv_control/
COPY run.py ./run.py

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HOME=/data TMPDIR=/data/tmp FIRETV_CONFIG=/data/device.json \
    FIRETV_BIND=0.0.0.0 FIRETV_RECONNECT=1 \
    FIRETV_SCRCPY_SERVER=/usr/local/share/scrcpy/scrcpy-server

USER 1000:1000
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=3)"
CMD ["python", "-u", "run.py", "web", "--no-browser"]

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends curl ffmpeg libmagic1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 pocket \
    && useradd --system --uid 10001 --gid pocket --home-dir /app pocket

WORKDIR /app

COPY services/api/requirements.txt /tmp/requirements.txt
RUN python3.12 -m pip install --requirement /tmp/requirements.txt

COPY --chown=pocket:pocket services/api/ /app/
COPY --chown=pocket:pocket fixtures/manifest.json /fixtures/manifest.json
COPY --chown=pocket:pocket fixtures/media/pocket-demo-fixture.wav /fixtures/media/pocket-demo-fixture.wav
COPY --chown=pocket:pocket fixtures/sidecars/pocket-demo-fixture.json /fixtures/sidecars/pocket-demo-fixture.json
RUN mkdir --parents /data/blobs \
    && chown --recursive pocket:pocket /data

USER pocket

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
  CMD curl --fail --silent --show-error http://localhost:8000/healthz || exit 1

CMD ["python3.12", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

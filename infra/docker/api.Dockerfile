FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends curl ffmpeg libmagic1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app app

WORKDIR /app

COPY services/api/requirements.txt /tmp/requirements.txt
RUN python3.12 -m pip install --requirement /tmp/requirements.txt

COPY --chown=app:app services/api/ /app/
COPY --chown=app:app fixtures/manifest.json /fixtures/manifest.json
COPY --chown=app:app fixtures/media/intelligent-audio-analysis-fixture.wav /fixtures/media/intelligent-audio-analysis-fixture.wav
COPY --chown=app:app fixtures/sidecars/intelligent-audio-analysis-fixture.json /fixtures/sidecars/intelligent-audio-analysis-fixture.json
RUN mkdir --parents /data/blobs \
    && chown --recursive app:app /data

USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
  CMD curl --fail --silent --show-error http://localhost:8000/healthz || exit 1

CMD ["python3.12", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

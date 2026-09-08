FROM node:22-bookworm-slim AS web-build

ENV CI=1 \
    EXPO_NO_DOTENV=1

WORKDIR /workspace/apps/client
COPY apps/client/package.json apps/client/package-lock.json ./
RUN npm ci
COPY apps/client/ ./

# An empty API URL intentionally means same-origin. Cloud Run serves the web app
# and API from one HTTPS origin, so no workstation hostname or deployment URL is
# embedded in the client bundles.
ARG EXPO_PUBLIC_API_URL=
ARG EXPO_PUBLIC_DEMO_MODE=true
ARG EXPO_PUBLIC_STATUS_POLL_INTERVAL_MS=1500
ARG EXPO_PUBLIC_MEDIA_GRANT_REFRESH_SECONDS=45
ENV EXPO_PUBLIC_API_URL=${EXPO_PUBLIC_API_URL} \
    EXPO_PUBLIC_DEMO_MODE=${EXPO_PUBLIC_DEMO_MODE} \
    EXPO_PUBLIC_STATUS_POLL_INTERVAL_MS=${EXPO_PUBLIC_STATUS_POLL_INTERVAL_MS} \
    EXPO_PUBLIC_MEDIA_GRANT_REFRESH_SECONDS=${EXPO_PUBLIC_MEDIA_GRANT_REFRESH_SECONDS}

RUN npm run export -- --clear


FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    FIXTURE_ROOT=/fixtures \
    WEB_DIST_ROOT=/app/web

RUN apt-get update \
    && apt-get install --yes --no-install-recommends curl ffmpeg libmagic1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app app

WORKDIR /app
COPY services/api/requirements.txt /tmp/requirements.txt
RUN python3.12 -m pip install --requirement /tmp/requirements.txt

COPY --chown=app:app services/api/ /app/
COPY --chown=app:app fixtures/ /fixtures/
COPY --from=web-build --chown=app:app /workspace/apps/client/dist/ /app/web/

USER app
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
  CMD curl --fail --silent --show-error http://localhost:8080/healthz || exit 1

CMD ["python3.12", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]

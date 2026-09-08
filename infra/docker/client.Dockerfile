FROM node:22-bookworm-slim AS build

ENV CI=1 \
    EXPO_NO_DOTENV=1

WORKDIR /workspace/apps/client

COPY apps/client/package.json apps/client/package-lock.json ./
RUN npm ci

COPY apps/client/ ./

ARG EXPO_PUBLIC_API_URL=http://localhost:8000
ARG EXPO_PUBLIC_DEMO_MODE=true
ARG EXPO_PUBLIC_STATUS_POLL_INTERVAL_MS=1500
ARG EXPO_PUBLIC_MEDIA_GRANT_REFRESH_SECONDS=45
ARG EXPO_PUBLIC_SENTRY_DSN=
ARG EXPO_APP_NAME="Intelligent Audio Analysis"
ARG EXPO_APP_SLUG=intelligent-audio-analysis
ARG EXPO_APP_SCHEME=intelligentaudioanalysis
ENV EXPO_PUBLIC_API_URL=${EXPO_PUBLIC_API_URL} \
    EXPO_PUBLIC_DEMO_MODE=${EXPO_PUBLIC_DEMO_MODE} \
    EXPO_PUBLIC_STATUS_POLL_INTERVAL_MS=${EXPO_PUBLIC_STATUS_POLL_INTERVAL_MS} \
    EXPO_PUBLIC_MEDIA_GRANT_REFRESH_SECONDS=${EXPO_PUBLIC_MEDIA_GRANT_REFRESH_SECONDS} \
    EXPO_PUBLIC_SENTRY_DSN=${EXPO_PUBLIC_SENTRY_DSN} \
    EXPO_APP_NAME=${EXPO_APP_NAME} \
    EXPO_APP_SLUG=${EXPO_APP_SLUG} \
    EXPO_APP_SCHEME=${EXPO_APP_SCHEME}

RUN npm run export

FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/apps/client/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=5 \
  CMD wget --quiet --tries=1 --spider http://localhost:8080/healthz || exit 1

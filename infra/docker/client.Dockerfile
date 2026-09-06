FROM node:22-bookworm-slim AS build

ENV CI=1 \
    EXPO_NO_DOTENV=1

WORKDIR /workspace/apps/client

COPY apps/client/package.json apps/client/package-lock.json ./
RUN npm ci

COPY apps/client/ ./

ARG EXPO_PUBLIC_API_URL=http://localhost:8000
ENV EXPO_PUBLIC_API_URL=${EXPO_PUBLIC_API_URL}

RUN npm run export

FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/apps/client/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=5 \
  CMD wget --quiet --tries=1 --spider http://localhost:8080/healthz || exit 1

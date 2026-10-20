# Static frontend built with bun, served by nginx.
# Build context is the repository root: docker build -f deploy/web.Dockerfile .

FROM oven/bun:1 AS builder

WORKDIR /app

# Manifests first so the install layer is cached separately.
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile

COPY frontend/ ./
RUN bun run build

FROM nginx:alpine AS runtime

COPY --from=builder /app/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

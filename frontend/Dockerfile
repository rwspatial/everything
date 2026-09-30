# syntax=docker/dockerfile:1
# Static SvelteKit build, served by Caddy. The main proxy forwards everything that
# isn't /tiles/* or /projects/* here. In Phase 6 the same build/ goes to S3 + CloudFront.
ARG NODE_TAG=24.21.0-bookworm-slim
ARG CADDY_TAG=2.11.4-alpine

FROM node:${NODE_TAG} AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM caddy:${CADDY_TAG}
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/build /srv

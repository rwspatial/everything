# Reporter: headless Chromium (the same Playwright image the e2e tests use) + node-postgres.
ARG PLAYWRIGHT_TAG
FROM mcr.microsoft.com/playwright:${PLAYWRIGHT_TAG}
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund
COPY reporter.mjs ./
ENV NODE_ENV=production HOME=/tmp
CMD ["node", "reporter.mjs"]

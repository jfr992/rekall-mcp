# Cockpit UI — multi-stage build producing a slim standalone Next.js server.
# Build context is the repo root (so we can COPY ui/); see docker-compose.yaml.

FROM node:22-slim AS deps
WORKDIR /app
COPY ui/package.json ui/package-lock.json ./
RUN npm ci

FROM node:22-slim AS build
WORKDIR /app
# Next rewrites are baked at build time under output:standalone — the proxy
# target must be known here, not just at runtime.
ARG MEMENTO_API_URL=http://mcp:8000
ENV MEMENTO_API_URL=${MEMENTO_API_URL}
COPY --from=deps /app/node_modules ./node_modules
COPY ui/ ./
RUN npm run build

FROM node:22-slim AS run
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3333
# Standalone output bundles only what the server needs.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3333
CMD ["node", "server.js"]

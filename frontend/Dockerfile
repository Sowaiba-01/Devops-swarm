# syntax=docker/dockerfile:1.7

# ── Dependencies ───────────────────────────────────────────────────────
FROM node:22-alpine AS deps
WORKDIR /app
# The lockfile is copied so `npm ci` installs exactly what is pinned. The
# previous image copied only package.json and ran `npm install`, which resolved
# fresh versions on every build — the image was not reproducible.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund


# ── Build ──────────────────────────────────────────────────────────────
FROM node:22-alpine AS builder
WORKDIR /app

# Next inlines NEXT_PUBLIC_* at build time, so it must be an ARG here. Without
# this declaration the compose build-arg was silently discarded and the bundle
# fell back to http://localhost:8000 — fine locally, broken everywhere else.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN mkdir -p public && npm run build


# ── Runtime ────────────────────────────────────────────────────────────
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN apk add --no-cache curl \
    && addgroup -g 10001 -S nodejs \
    && adduser -u 10001 -S nextjs -G nodejs

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:3000/ || exit 1

CMD ["node", "server.js"]

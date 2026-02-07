# syntax=docker/dockerfile:1

FROM node:20-alpine AS deps
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . ./

# Allows configuring the API URL at build time.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production

# If provided at runtime, Next will expose NEXT_PUBLIC_* to the browser as well
# (but note some values may be baked at build time).
ENV NEXT_PUBLIC_API_URL=http://localhost:8000

COPY --from=builder /app/.next ./.next
# `public/` is optional in Next.js apps; repo may not have it.
# Avoid failing the build when the directory is absent.
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/next.config.ts ./next.config.ts

EXPOSE 3000

CMD ["npm", "run", "start"]

# ---- Stage 1: Builder ----
FROM node:20-alpine AS builder
WORKDIR /app

# NEXT_PUBLIC_* vars must exist at build time (baked into the JS bundle)
ARG NEXT_PUBLIC_FASTAPI_URL
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY

ENV NEXT_PUBLIC_FASTAPI_URL=$NEXT_PUBLIC_FASTAPI_URL
ENV NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL
ENV NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---- Stage 2: Runner ----
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
# Required: standalone server binds to localhost by default — must set 0.0.0.0
ENV HOSTNAME=0.0.0.0

# Copy standalone output (does NOT include static assets — must copy explicitly)
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]

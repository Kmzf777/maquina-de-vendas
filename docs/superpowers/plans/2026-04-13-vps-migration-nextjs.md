# VPS Migration — Next.js (crm/) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mover o frontend Next.js de `crm/` do Vercel para a VPS, exposto em `canastrainteligencia.com` via Docker Swarm + Traefik.

**Architecture:** Stack Swarm separado (`crm`) na mesma rede overlay `canastrainteligencia` que o backend. Traefik roteia o domínio e gerencia SSL (Let's Encrypt). Variáveis `NEXT_PUBLIC_*` são passadas como `--build-arg` no `docker build` porque são baked in no bundle em tempo de build.

**Tech Stack:** Next.js 16.2.1, Node.js 20 Alpine, Docker Swarm, Traefik (já rodando), `output: 'standalone'`

---

## File Map

| Ação | Arquivo | Responsabilidade |
|------|---------|-----------------|
| Modify | `crm/next.config.ts` | Habilitar `output: 'standalone'` |
| Create | `crm/Dockerfile` | Build multi-stage: builder (next build) + runner (node server.js) |
| Create | `crm/.env.build.example` | Template das vars de build (commitado; `.env.build` real fica só na VPS) |
| Create | `crm/docker-compose.yml` | Stack Swarm: serviço crm + labels Traefik + redirect www→non-www |

---

## Task 1: Habilitar standalone output no Next.js

**Files:**
- Modify: `crm/next.config.ts`

- [ ] **Step 1: Editar `next.config.ts`**

Substituir o conteúdo atual por:

```ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
};

export default nextConfig;
```

- [ ] **Step 2: Verificar que o build local funciona**

```bash
cd crm && npm run build
```

Esperado: build termina sem erros. Verificar que a pasta `crm/.next/standalone/` foi criada:

```bash
ls crm/.next/standalone/
```

Esperado: ver `server.js` na listagem.

- [ ] **Step 3: Commit**

```bash
git add crm/next.config.ts
git commit -m "feat(crm): enable standalone output for self-hosted deployment"
```

---

## Task 2: Criar o Dockerfile multi-stage

**Files:**
- Create: `crm/Dockerfile`

- [ ] **Step 1: Criar `crm/Dockerfile`**

```dockerfile
# ---- Stage 1: Builder ----
FROM node:20-alpine AS builder
WORKDIR /app

# Variáveis públicas — devem existir em tempo de build (baked in no bundle JS)
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

# Copiar apenas o necessário do build standalone
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
```

- [ ] **Step 2: Criar `crm/.env.build.example`** (template commitado — a VPS usa `.env.build` real)

```bash
cat > crm/.env.build.example << 'EOF'
NEXT_PUBLIC_FASTAPI_URL=https://api.canastrainteligencia.com
NEXT_PUBLIC_SUPABASE_URL=https://tshmvxxxyxgctrdkqvam.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<cole aqui a anon key do Supabase>
EOF
```

- [ ] **Step 3: Verificar que o build Docker funciona (rodar na VPS)**

Na VPS, com o `.env.build` preenchido:

```bash
cd /home/Kelwin/Maquinadevendascanastra
source crm/.env.build

sg docker -c "docker build \
  --build-arg NEXT_PUBLIC_FASTAPI_URL=$NEXT_PUBLIC_FASTAPI_URL \
  --build-arg NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL \
  --build-arg NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY \
  -t canastra-crm:latest ./crm"
```

Esperado: build termina com `Successfully tagged canastra-crm:latest` (ou equivalente).

- [ ] **Step 4: Verificar que o container inicia e responde**

```bash
sg docker -c "docker run --rm -p 3000:3000 canastra-crm:latest" &
sleep 5
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000
```

Esperado: `200`. Matar o container depois:

```bash
sg docker -c "docker ps" # pegar o container ID
sg docker -c "docker stop <container_id>"
```

- [ ] **Step 5: Commit**

```bash
git add crm/Dockerfile crm/.env.build.example
git commit -m "feat(crm): add multi-stage Dockerfile with NEXT_PUBLIC build args"
```

---

## Task 3: Criar o docker-compose.yml do stack crm

**Files:**
- Create: `crm/docker-compose.yml`

- [ ] **Step 1: Criar `crm/docker-compose.yml`**

```yaml
services:
  crm:
    image: canastra-crm:latest
    networks:
      - canastrainteligencia
    deploy:
      labels:
        - "traefik.enable=true"
        - "traefik.docker.network=canastrainteligencia"

        # Router principal — non-www (HTTPS)
        - "traefik.http.routers.frontend.rule=Host(`canastrainteligencia.com`)"
        - "traefik.http.routers.frontend.entrypoints=websecure"
        - "traefik.http.routers.frontend.tls.certresolver=letsencryptresolver"
        - "traefik.http.services.frontend.loadbalancer.server.port=3000"

        # Router www — redireciona 301 para non-www antes de chegar ao Next.js
        # (evita problema de CORS: backend só autoriza a origem sem www)
        - "traefik.http.routers.frontend-www.rule=Host(`www.canastrainteligencia.com`)"
        - "traefik.http.routers.frontend-www.entrypoints=websecure"
        - "traefik.http.routers.frontend-www.tls.certresolver=letsencryptresolver"
        - "traefik.http.routers.frontend-www.middlewares=redirect-www"
        - "traefik.http.middlewares.redirect-www.redirectregex.regex=^https://www\\.(.*)"
        - "traefik.http.middlewares.redirect-www.redirectregex.replacement=https://$${1}"
        - "traefik.http.middlewares.redirect-www.redirectregex.permanent=true"

networks:
  canastrainteligencia:
    external: true
```

- [ ] **Step 2: Commit**

```bash
git add crm/docker-compose.yml
git commit -m "feat(crm): add Swarm docker-compose with Traefik routing and www redirect"
```

---

## Task 4: Deploy do stack na VPS

**Pré-requisito:** `canastra-crm:latest` já foi buildada na Task 2.

- [ ] **Step 1: Confirmar que o DNS aponta para a VPS**

```bash
dig +short canastrainteligencia.com
dig +short www.canastrainteligencia.com
```

Esperado: ambos retornam o IP da VPS (não um IP do Vercel como `76.76.x.x`).

Se ainda apontar para o Vercel: mudar o registro A no Cloudflare para o IP da VPS antes de continuar.

- [ ] **Step 2: Deploy do stack**

```bash
cd /home/Kelwin/Maquinadevendascanastra
sg docker -c "docker stack deploy -c crm/docker-compose.yml crm"
```

Esperado:

```
Creating service crm_crm
```

- [ ] **Step 3: Verificar que o serviço subiu**

```bash
sg docker -c "docker service ls"
```

Esperado: linha com `crm_crm` mostrando `1/1` em REPLICAS.

Se mostrar `0/1`, ver logs:

```bash
sg docker -c "docker service logs crm_crm --tail 50"
```

- [ ] **Step 4: Verificar resposta HTTP via domínio**

```bash
curl -s -o /dev/null -w "%{http_code}" https://canastrainteligencia.com
```

Esperado: `200`.

- [ ] **Step 5: Verificar redirect www → non-www**

```bash
curl -s -o /dev/null -w "%{http_code} %{redirect_url}" https://www.canastrainteligencia.com
```

Esperado: `301 https://canastrainteligencia.com/`

---

## Task 5: Atualizar FRONTEND_URL no backend e verificar CORS

- [ ] **Step 1: Atualizar a variável no serviço do backend**

```bash
sg docker -c "docker service update --env-add FRONTEND_URL=https://canastrainteligencia.com canastra_api"
```

Esperado: serviço faz rolling update — `canastra_api` reinicia com a nova var.

- [ ] **Step 2: Confirmar que a variável foi aplicada**

```bash
CONTAINER=$(sg docker -c "docker ps --filter name=canastra_api --format '{{.ID}}'" | head -1)
sg docker -c "docker exec $CONTAINER env" | grep FRONTEND_URL
```

Esperado: `FRONTEND_URL=https://canastrainteligencia.com`

- [ ] **Step 3: Verificar CORS na prática**

Abrir o site em `https://canastrainteligencia.com`, abrir DevTools → Network, navegar pela interface e confirmar que não há erros de CORS nas chamadas para `api.canastrainteligencia.com`.

- [ ] **Step 4: Desativar o projeto no Vercel** (após confirmar que tudo funciona)

Acessar o painel do Vercel e pausar ou deletar o projeto `crm`. Isso é manual — não há comando CLI necessário.

---

## Checklist de verificação final

- [ ] `https://canastrainteligencia.com` carrega o CRM (200)
- [ ] `https://www.canastrainteligencia.com` redireciona para sem-www (301)
- [ ] SSL válido nos dois subdomínios
- [ ] Chamadas para `api.canastrainteligencia.com` funcionam sem erro de CORS
- [ ] Realtime Supabase funciona (testar página `/conversas`)
- [ ] Stack backend (`canastra`) continua saudável: `docker service ls` mostra `3/3` (api, worker, redis)

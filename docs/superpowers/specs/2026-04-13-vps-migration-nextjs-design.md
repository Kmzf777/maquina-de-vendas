# Design: Migração Next.js (crm/) — Vercel → VPS

**Data:** 2026-04-13  
**Branch:** feature/crm-vps-migration (a criar)  
**Status:** Aprovado, aguardando implementação

---

## Contexto

O frontend Next.js (`crm/`) roda atualmente no Vercel. O backend FastAPI já está na VPS (Hostinger, Linux) via Docker Swarm + Traefik, exposto em `api.canastrainteligencia.com`. A migração move o frontend para a mesma VPS, seguindo o mesmo padrão de infraestrutura já estabelecido.

**Motivação:** Dois desenvolvedores trabalham na mesma VPS e querem acessar o resultado de cada deploy diretamente no domínio, sem precisar de conta Vercel compartilhada. O build Docker leva alguns minutos — não é hot-reload, mas o resultado fica imediatamente disponível no domínio assim que o deploy termina.

---

## Arquitetura

```
Navegador → www.canastrainteligencia.com (443)
               ↓
           Traefik — redirect 301 www → non-www
               ↓
Navegador → canastrainteligencia.com (443)
               ↓
           Traefik (Docker Swarm, já rodando)
           Rede: canastrainteligencia (overlay, external)
               ↓
       Stack "crm" — serviço Next.js (porta 3000)
               ↓
       Supabase (tshmvxxxyxgctrdkqvam.supabase.co)
       Backend FastAPI (api.canastrainteligencia.com) — stack "canastra", inalterado
```

---

## Componentes

### 1. `crm/Dockerfile` (novo)

Build multi-stage para imagem enxuta:

- **Stage `builder`** — `node:20-alpine`: instala dependências (`npm ci`), recebe as variáveis `NEXT_PUBLIC_*` como `ARG`/`ENV` e executa `next build`. As variáveis públicas são **baked in** no bundle JavaScript nesse momento — não podem ser injetadas em runtime.
- **Stage `runner`** — `node:20-alpine`: copia apenas `.next/standalone/`, `.next/static/` e `public/`. Executa `node server.js` (servidor embutido do standalone output).
- Porta exposta: `3000`.
- Sem dependência de `sharp`: o projeto não usa `next/image`, então otimização de imagem via sharp não é necessária.

**ARGs declarados no Dockerfile (stage builder):**
```dockerfile
ARG NEXT_PUBLIC_FASTAPI_URL
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
ENV NEXT_PUBLIC_FASTAPI_URL=$NEXT_PUBLIC_FASTAPI_URL
ENV NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL
ENV NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY
```

### 2. `crm/docker-compose.yml` (novo)

Stack Swarm para o frontend. Inclui middleware Traefik para redirect www → non-www, mantendo o CORS do backend simples (uma única origem):

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
        # Router principal — só non-www
        - "traefik.http.routers.frontend.rule=Host(`canastrainteligencia.com`)"
        - "traefik.http.routers.frontend.entrypoints=websecure"
        - "traefik.http.routers.frontend.tls.certresolver=letsencryptresolver"
        - "traefik.http.services.frontend.loadbalancer.server.port=3000"
        # Router www → redirect 301 para non-www
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

**Por que redirect em vez de aceitar os dois no router:** o CORS do backend (`main.py:41`) aceita apenas `settings.frontend_url`. Com o redirect, quem acessa `www.` é redirecionado antes de chegar ao Next.js — o browser sempre faz as chamadas de API a partir de `canastrainteligencia.com`, evitando bloqueio de CORS.

### 3. `crm/.env.build` (novo, na VPS)

Variáveis usadas **apenas no build** (`--build-arg`). Arquivo não commitado (`.gitignore`):

```
NEXT_PUBLIC_FASTAPI_URL=https://api.canastrainteligencia.com
NEXT_PUBLIC_SUPABASE_URL=https://tshmvxxxyxgctrdkqvam.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<chave do Supabase>
```

### 4. `crm/next.config.ts` (modificar)

Adicionar `output: 'standalone'` para habilitar o build standalone:

```ts
const nextConfig: NextConfig = {
  output: 'standalone',
};
```

### 5. Backend — atualização de env var

O backend tem `FRONTEND_URL=http://localhost:5173` (valor legado). Após o deploy do frontend, atualizar:

```bash
docker service update --env-add FRONTEND_URL=https://canastrainteligencia.com canastra_api
```

Isso atualiza o CORS em `main.py:41` para a origem correta.

---

## Workflow de Deploy (pós-migração)

```bash
# 1. Carregar vars de build do arquivo
source crm/.env.build

# 2. Build da imagem passando as variáveis públicas como --build-arg
sg docker -c "docker build \
  --build-arg NEXT_PUBLIC_FASTAPI_URL=$NEXT_PUBLIC_FASTAPI_URL \
  --build-arg NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL \
  --build-arg NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY \
  -t canastra-crm:latest ./crm"

# 3. Deploy no Swarm
sg docker -c "docker stack deploy -c crm/docker-compose.yml crm"

# 4. Verificar
sg docker -c "docker service ls"
```

O Claude Code executa esses comandos quando solicitado.

---

## O que NÃO muda

- Stack `canastra` (backend, worker, redis) — nenhuma alteração estrutural; apenas atualização do `FRONTEND_URL` via `docker service update`
- Traefik — nenhum arquivo de configuração novo; os labels no docker-compose são suficientes
- Supabase — nenhuma alteração
- DNS/Cloudflare — `canastrainteligencia.com` e `www.canastrainteligencia.com` devem apontar para o IP da VPS (verificar antes do deploy)

---

## Pré-requisitos antes do deploy

1. Confirmar que `canastrainteligencia.com` e `www.canastrainteligencia.com` no Cloudflare apontam para o IP da VPS (não para o Vercel)
2. Ter a `NEXT_PUBLIC_SUPABASE_ANON_KEY` para criar o `.env.build` na VPS
3. Desativar o projeto no Vercel após confirmar que o site funciona na VPS

---

## Fora do escopo

- CI/CD automático (push → deploy) — workflow atual: Claude Code executa manualmente
- Múltiplas réplicas / load balancing do frontend
- Preview deployments por branch
- Otimização de imagens via `sharp` — projeto não usa `next/image`

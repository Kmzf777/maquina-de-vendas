# Opt8 + P4 — Higiene de infra e observabilidade estruturada

**Data:** 2026-07-10
**Status:** aprovado para implementação

## Opt8 — Higiene de infra

### Healthchecks (intervalos conservadores — VPS única, não drenar CPU)

- **api** (`backend/docker-compose.yml`): `curl -fsS http://localhost:8000/health` — `interval: 30s`, `timeout: 5s`, `retries: 3`, `start_period: 40s`. O endpoint `/health` já existe e é barato. Curl entra no Dockerfile (slim não tem).
- **redis**: `redis-cli ping` — `interval: 30s`, `timeout: 3s`, `retries: 3`.
- **worker**: sem healthcheck HTTP (processo sem porta); o Swarm já reinicia em crash e o watchdog cobre travamento lógico. Inventar um check de processo agora é complexidade sem sinal novo.
- **crm** (`frontend/docker-compose.yml`): `wget -q --spider http://localhost:3000/login` — `interval: 30s`, `timeout: 5s`, `retries: 3`, `start_period: 30s` (alpine tem wget busybox).

### Usuário não-root

- `backend/Dockerfile`: criar `appuser` (uid 1000) e `USER appuser` após o COPY. Uvicorn na 8000 (não-privilegiada) — sem impacto.
- `frontend/Dockerfile`: idem no estágio runner (`node` user já existe na imagem node:alpine → `USER node`), com `chown` no COPY do standalone.

### Limpeza do repositório

- `git rm --cached data/` (4 arquivos, incl. `valeriafotos.json` 1,3 MB — **zero uso em runtime**, verificado por grep em backend/frontend) e adicionar `data/` ao `.gitignore` (arquivos permanecem no disco do dev).
- `.gitignore` ganha também `TREE.md` e `tsconfig.tsbuildinfo`/`build_output.log` do frontend se ainda não cobertos.

## P4 — Observabilidade estruturada

### Logging JSON (stdlib, sem dependência)

- Novo `backend/app/logging_setup.py`: `JsonFormatter` (stdlib) emitindo uma linha JSON por registro — `{"ts", "level", "logger", "msg"}` + `exc_info` serializado quando presente. `setup_logging()` lê `LOG_FORMAT` (env): `json` (default) ou `text` (formato atual, para dev local; documentado no `.env.example`).
- Trocar os `logging.basicConfig` de `app/main.py` e `app/campaign/worker.py` por `setup_logging()`. Scripts one-off mantêm texto (são interativos).
- As mensagens existentes não mudam (prefixos `[FOLLOWUP]` etc. continuam dentro de `msg` — grep-áveis e agora parseáveis por máquina via campo).

### Sentry (fail-open por construção)

- Dependência: `sentry-sdk[fastapi]` no `requirements.txt`.
- Novo `backend/app/observability.py`: `init_sentry()` — se `SENTRY_DSN` vazio/ausente, loga um info e retorna sem inicializar (**o sistema funciona identicamente sem a chave**). Com DSN: `sentry_sdk.init(dsn, environment=ENV_TAG, traces_sample_rate=0.0)` — só captura de erros, sem tracing (custo/free tier).
- Chamado no início do lifespan da API e no entrypoint do worker. `SENTRY_DSN` documentado no `.env.example`; secret adicionada ao serviço via env quando o usuário criar o projeto Sentry (nenhum bloqueio até lá).
- **Watchdog intocado** — Sentry cobre exceções/stack traces; o watchdog segue cobrindo estados de negócio (IA muda, SLA, billing).

### Frontend

Fora desta fase (o `@sentry/nextjs` exige mudanças no build/next.config e interage com o output standalone — iteração própria).

## Testes

- `logging_setup`: unit tests do formatter (linha é JSON válido, campos presentes, exceção serializada) e do toggle `LOG_FORMAT=text`.
- `observability`: init sem DSN é no-op que não levanta; com DSN chama `sentry_sdk.init` (mock).
- Suítes completas verdes; build de imagem validado com `docker build` local se o Docker estiver disponível (senão, validação no deploy — os Dockerfiles são exercitados pelo pipeline).

## Riscos

- **Healthcheck no Swarm reinicia containers unhealthy** → intervalos/retries conservadores + `start_period` cobrem boots lentos; `/health` não depende de LLM/Supabase (barato e estável).
- **USER não-root quebrar escrita em runtime** → backend não escreve em disco (logs vão a stdout); CRM standalone só lê.
- **Logs JSON quebrarem leitura humana no `docker service logs`** → `LOG_FORMAT=text` disponível; produção ganha parseabilidade (o custo de leitura é compensado por `jq`).

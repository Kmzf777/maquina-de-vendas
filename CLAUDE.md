# DIRETRIZES PARA AGENTES DE IA — Maquina de Vendas Canastra

Repositório com deploy crítico em Docker Swarm. Siga as regras abaixo sem exceção.

---

## 🚀 1. Fluxo Git — Sem Pull Requests (REGRA INEGOCIÁVEL)

**NÃO USAMOS Pull Requests (PRs).** O fluxo de trabalho é exatamente:

```
1. Criar branch.
2. Implementar e testar.
3. git pull origin master   (atualizar com a master remota)
4. git push origin nome_da_branch:master   (subir DIRETO para produção)
```

- **Passo 1 — Branch:** crie uma branch local para organizar o trabalho. O destino final é sempre `master` no remoto.
- **Passo 2 — Implementar e testar:** use as VS Code tasks (ex: `Run All Dev (CRM & Backend)`) e rode a suíte de testes. Valide o comportamento antes de commitar.
- **Passo 3 — `git pull origin master`:** sempre atualize com a master remota antes de subir, para evitar divergência/conflito.
- **Passo 4 — `git push origin nome_da_branch:master`:** sobe direto para produção. **O push aciona deploy de produção via GitHub Actions.**
- **Autorização:** o push para `master` (passo 4) é feito mediante autorização do usuário — ele decide quando subir após validar.

---

## 📞 2. Dev Router — Isolamento de Testes

Números na whitelist Redis (`dev:phone_routes`) devem ser redirecionados para o backend dev (`DEV_SERVER_URL`). **Nunca processados pela produção.**

- **O Dev Router DEVE operar no payload bruto, antes de qualquer parsing.**

  | ✅ Correto | ❌ Errado |
  |---|---|
  | Extrair `from_number` do JSON bruto → checar whitelist → encaminhar → `return` | Parsear mensagens primeiro → checar whitelist no loop (tipos não suportados nunca chegam ao router) |

- Ao alterar qualquer arquivo em `backend/app/webhook/`, confirme que o Dev Router ainda opera antes do parsing.
- O header `x-dev-routed: 1` no payload encaminhado previne loop infinito.

---

## 🚦 3. Redes e Docker — Regra do Endereço

A regra depende de **onde o processo está rodando:**

### Se o processo roda DENTRO de um container Docker (produção, docker-compose, Swarm):
**NUNCA use `localhost` ou `127.0.0.1`.** Use o nome do serviço do `docker-compose.yml`:

| Serviço  | URL correta                      |
|----------|----------------------------------|
| Redis    | `redis://redis:6379`             |
| Postgres | `postgresql://user:pass@db:5432` |
| API      | `http://api:8000`                |

### Se o processo roda NO HOST (backend dev fora do Docker — `.env.local`):
**Use `127.0.0.1` + a porta publicada pelo Docker.** O DNS de serviço (`redis`, `db`) não resolve fora da rede Docker.

> **`.env.local` é o único arquivo onde `127.0.0.1` é permitido.** Ele está no `.dockerignore` e nunca chega à produção.

### Paridade de código:
O **código** deve funcionar em ambos os ambientes sem modificação. Os arquivos de ambiente (`.env`, `.env.local`) existem para separar as configurações — isso não viola a paridade.

### Outras restrições:
- Não altere configurações do GitHub Actions sem alertar explicitamente o usuário.

---

## 🌐 4. Ambiente de Desenvolvimento — URL Pública Oficial

O backend dev está exposto via **Cloudflare Tunnel permanente**. A URL pública oficial é:

```
https://dev.canastrainteligencia.com
```

**Regras críticas:**

- **NUNCA use `172.18.0.1:8001`** como `DEV_SERVER_URL` em código, scripts ou registros Redis. Esse IP é o gateway Docker do servidor Linux de produção — não tem relação com a máquina de desenvolvimento.
- **NUNCA use `127.0.0.1:8001`** para referências externas ao dev backend. Esse endereço só é válido dentro do próprio processo local.
- Ao registrar o número de dev na whitelist Redis de produção (`POST /api/dev/whitelist/{phone}`), o campo `dev_url` deve ser sempre `https://dev.canastrainteligencia.com`.
- O arquivo `.env` (produção) contém `DEV_SERVER_URL=http://172.18.0.1:8001` por razões históricas — esse valor é ignorado em tempo de execução porque o `dev_url` real vem do Redis, não do env. Não altere o `.env` para corrigir isso; o Redis é a fonte de verdade.

**Mapeamento de ambientes:**

| Ambiente | URL | Onde usar |
|---|---|---|
| Produção | `https://api.canastrainteligencia.com` | Webhooks Meta, integrações externas |
| Dev (público) | `https://dev.canastrainteligencia.com` | `dev_url` no Redis, testes de roteamento |
| Dev (local) | `http://127.0.0.1:8001` | Apenas `.env.local` e health checks locais |

---

## ⚛️ 5. Frontend — Next.js

- Esta versão usa **App Router e Server Components**. Convenções, APIs e estrutura de pastas podem diferir dos seus dados de treinamento.
- **Consulte os padrões existentes em `frontend/src/app` antes de criar lógica nova.** Não confie em memória para APIs e estrutura de rotas.

---

## 📲 6. Provedor de WhatsApp — Meta Graph API é a fonte única

O provedor **Evolution API está temporariamente desativado/obsoleto.** Todo o foco de
desenvolvimento, debug e integrações de WhatsApp deve ser direcionado **exclusivamente
para a Meta Graph API oficial** (`backend/app/whatsapp/meta.py`, `backend/app/webhook/meta_*`).

- **Ignore arquivos ou lógicas focadas apenas no Evolution API** (ex.: `backend/app/whatsapp/evolution.py`, `backend/app/webhook/parser.py` no formato `messages.upsert`, caminhos `provider == "evolution"`). Não invista tempo corrigindo, otimizando ou estendendo esse código.
- Ao investigar bugs de mensagens (parsing, envio, citação/reply, mídia), assuma o **fluxo Meta** como o ativo: parser `meta_parser.py`, roteador `meta_router.py`, cliente `MetaCloudClient`.
- Código novo de envio deve passar pela interface `WhatsAppProvider`, mas o comportamento de referência é sempre o do `MetaCloudClient`.

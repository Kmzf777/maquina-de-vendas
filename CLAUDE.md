# DIRETRIZES PARA AGENTES DE IA — Maquina de Vendas Canastra

Repositório com deploy crítico em Docker Swarm. Siga as regras abaixo sem exceção.

---

## 🚀 1. Fluxo Git — Sem Pull Requests

**NÃO usamos PRs.** Fluxo obrigatório:

```
Codificar → Commitar (branch local opcional) → PARAR → Usuário testa no Dev → Push master (só com autorização)
```

- **Branch local** para organizar o trabalho é recomendada, mas não obrigatória. O destino final é sempre `master` no remoto.
- **Testar:** use as VS Code tasks (ex: `Run All Dev (CRM & Backend)`). Valide o comportamento manualmente antes de commitar.
- **⛔ REGRA DE OURO:** Após commitar, **pare e avise o usuário.** Aguarde ele testar no dev. Só faça push após **autorização expressa** ("pode fazer o push", "faça isso", etc.).
- **Push para master:** `git push origin master` ou `git push origin minha-branch:master`. O push aciona deploy de produção via GitHub Actions.

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

## ⚠️ 4. Login Temporariamente Desativado (REATIVAR!)

> **Status:** Login Supabase está **desativado** desde 2026-05-18 na branch `fix/disable-login-temp` (mergeada em master).
> O sistema foi implementado mas apresentava bugs em produção.

**Para reativar o login:**
1. Restaurar `frontend/src/middleware.ts` com a lógica completa de auth (ver git history antes do commit de desativação — buscar "disable-login-temp").
2. O arquivo original usava `createServerClient` do `@supabase/ssr`, `supabase.auth.getUser()`, verificação de role (`admin` | `vendedor`) e redirecionamento para `/login`.
3. A página de login já existe em `frontend/src/app/login/page.tsx` — não remover.
4. Os helpers de role estão em `frontend/src/lib/auth/roles.ts` — não remover.

**O que foi desativado:** apenas `middleware.ts` — o middleware agora retorna `NextResponse.next()` sem nenhuma verificação. Todo o restante do código (supabase client, login page, roles) foi **preservado**.

---

## ⚛️ 5. Frontend — Next.js

- Esta versão usa **App Router e Server Components**. Convenções, APIs e estrutura de pastas podem diferir dos seus dados de treinamento.
- **Consulte os padrões existentes em `frontend/src/app` antes de criar lógica nova.** Não confie em memória para APIs e estrutura de rotas.

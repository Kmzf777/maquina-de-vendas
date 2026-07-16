# Cobertura de autenticação no proxy — fechar rotas fora do matcher

**Data:** 2026-07-09
**Status:** aprovado para implementação

## Problema

O gating de sessão do CRM é feito por `frontend/src/proxy.ts` (sucessor do `middleware.ts` no Next 16): valida `getUser()` via cookie Supabase, exige role `admin`/`vendedor` e aplica restrições admin-only (`lib/auth/roles.ts`). Porém o `config.matcher` é uma **allowlist explícita** — o que não está listado não passa pelo proxy e fica **público**, e as API routes rodam com `SUPABASE_SERVICE_ROLE_KEY` (bypass de RLS, `lib/supabase/api.ts`).

**Fora do matcher hoje (verificado por enumeração de `route.ts` vs matcher):**

| Rota | Exposição sem o proxy |
|---|---|
| `/api/quick-replies`, `/api/quick-replies/[id]` | CRUD aberto (service-role) |
| `/api/sales`, `/api/sales/[id]`, `/api/sales/metrics` | CRUD de vendas aberto |
| `/api/system-alerts` | leitura de alertas aberta |
| `/api/model-pricing`, `/api/model-pricing/[model]` | proxy p/ FastAPI aberto (GET/PUT de preços) |
| `/api/lp-webhook/settings` | proxy p/ FastAPI aberto (GET/PUT de config do funil LP) |
| `/api/conversions/dashboard`, `/stats`, `/google-export` | dashboard/stats abertos (`google-export` tem check admin interno) |
| `/api/me/allowed-channels` | protegido internamente (fail-closed), mas fora do padrão |
| Página `/painel-vendas` | renderiza sem sessão (dados via APIs acima) |

Consumidores de todas essas rotas são componentes do browser (cookies presentes) — confirmado por grep. Nenhum sistema externo as chama. O webhook público do funil de aquisição é `app/webhook/landing-page/route.ts`, **fora de `/api` e fora do matcher — não é tocado**.

## Design

Três mudanças pequenas e um guard-rail permanente. Sem dependência nova, sem tocar as 83 rotas service-role individualmente (defesa em profundidade por rota fica para fase posterior — o proxy já dá o corte de 401 na borda).

### 1. Completar o matcher (`proxy.ts`)

Adicionar:

```
"/painel-vendas/:path*",
"/api/conversions/:path*",
"/api/lp-webhook/:path*",
"/api/me/:path*",
"/api/model-pricing/:path*",
"/api/quick-replies/:path*",
"/api/sales/:path*",
"/api/system-alerts/:path*",
```

O matcher continua allowlist explícita (exigência do Next: `config` estaticamente analisável; inverter para negative-matcher arriscaria capturar `/webhook/landing-page` e o funil — rejeitado).

### 2. Admin-only para rotas de configuração (`lib/auth/roles.ts`)

- `ADMIN_API_PREFIXES` += `/api/model-pricing`, `/api/lp-webhook` (ambas são UI da página `/config`, que já é admin-only; um vendedor autenticado não deve editar preços de modelo nem config do webhook de LP).
- `/api/quick-replies` **não** entra: o `chat-view` (vendedor) consome o GET.
- `ROLE_PAGES` += `/painel-vendas` em `admin` e `vendedor` (documenta a página; não muda `isAdminOnlyPage`).

### 3. Guard-rail: teste de cobertura do matcher

Novo `frontend/src/lib/auth/proxy-coverage.test.ts` (vitest, node env — já é o padrão da suíte):

- Lê `src/proxy.ts` como texto e extrai as entradas do `config.matcher` (regex sobre literais de string — o matcher precisa permanecer literal estático de qualquer forma).
- Enumera via `fs` os diretórios de primeiro nível de `src/app/api/` e as páginas de `src/app/(authenticated)/`.
- Falha se existir prefixo de API ou página fora do matcher e fora de uma allowlist `PUBLIC` explícita no teste (inicialmente vazia).

Com o gate de CI (spec `2026-07-09-ci-test-gate-design.md`), toda rota futura criada fora do matcher **quebra o deploy** — o modelo passa de "lembrar de listar" para "esquecer é erro de build".

## Comportamento resultante

- Sem sessão: rotas novas do matcher respondem `401 {"error":"Não autenticado"}`; `/painel-vendas` redireciona para `/login`.
- Vendedor autenticado: tudo funciona como hoje, exceto `model-pricing`/`lp-webhook` (403 — coerente com a página `/config` que já não vê).
- Admin: sem mudança.

## Verificação

1. `npm run test` (inclui o guard novo) + `type-check` + `build`.
2. Runtime: `next dev` local → `curl` sem cookie em `/api/system-alerts` e `/api/sales/metrics` deve retornar 401; login no browser e smoke das páginas conversas/painel-vendas/config.

## Fora de escopo (YAGNI)

`getUser()` por rota nas 83 rotas service-role (fase posterior, incremental), rate-limiting, CSRF, remoção das rotas Evolution mortas (item separado do backlog), mudança no formato do matcher.

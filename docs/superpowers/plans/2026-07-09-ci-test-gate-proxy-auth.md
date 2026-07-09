# CI Test Gate + Cobertura de Auth no Proxy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bloquear deploy de produção quando qualquer teste falhar (pytest backend + vitest frontend) e fechar as rotas/páginas do CRM que hoje ficam fora do gating de autenticação do `proxy.ts`.

**Architecture:** Duas mudanças independentes e incrementais: (1) novos steps bloqueantes nos dois jobs existentes do `.github/workflows/deploy.yml`, sem jobs novos; (2) completar a allowlist do `config.matcher` do `proxy.ts` + prefixos admin-only em `roles.ts`, com um teste-guarda vitest que falha se qualquer rota/página futura ficar fora do matcher.

**Tech Stack:** GitHub Actions, pytest 9 (marker `not integration`), vitest 3 (node env), Next.js 16 (`proxy.ts` = sucessor do middleware).

## Global Constraints

- Specs de origem: `docs/superpowers/specs/2026-07-09-ci-test-gate-design.md` e `docs/superpowers/specs/2026-07-09-proxy-auth-coverage-design.md`.
- Sem dependências novas, sem serviços externos, sem jobs novos no workflow (critério do usuário: menor custo operacional).
- NÃO tocar em `app/webhook/landing-page/route.ts` nem capturar `/webhook` no matcher (funil de aquisição).
- O `config.matcher` do `proxy.ts` deve permanecer array de literais de string (exigência do Next: estaticamente analisável).
- CLAUDE.md: alertar o usuário sobre mudanças em GitHub Actions (feito nas specs); push para master só com autorização.
- Pré-condição verificada: `npm run test` (135 passed) e `tsc --noEmit` verdes localmente; pytest local em execução — Task 1 só conclui com suíte verde.

---

### Task 1: Gate de testes no CI — backend

**Files:**
- Modify: `.github/workflows/deploy.yml:104-125` (job `deploy-backend`)
- Modify: `backend/requirements-dev.txt`

**Interfaces:**
- Produces: step "Run backend tests" que bloqueia o step "Deploy Backend via SSH" (sequência de steps do mesmo job).

- [ ] **Step 1: Confirmar suíte backend verde localmente**

Run: `cd backend && python -m pytest -q -m "not integration" -p no:cacheprovider` (já em execução em background)
Expected: `NNNN passed` (memória do projeto registra 1837 em 09/07), zero failed/error.

- [ ] **Step 2: Adicionar pytest explícito ao requirements-dev**

`backend/requirements-dev.txt`:

```
pytest>=8.0,<10
fakeredis>=2.26.0
pytest-asyncio>=0.23.0
respx>=0.21.0
```

- [ ] **Step 3: Editar o job `deploy-backend`**

Em `.github/workflows/deploy.yml`:

(a) `python-version: '3.11'` → `'3.12'` (alinha com `backend/Dockerfile` `python:3.12-slim`).

(b) Step "Install backend dependencies" passa a instalar dev deps:

```yaml
      - name: Install backend dependencies
        if: steps.backend_changed.outputs.changed == 'true'
        working-directory: backend
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt -r requirements-dev.txt
```

(c) Novo step entre "Run backend smoke checks" e "Deploy Backend via SSH":

```yaml
      - name: Run backend tests
        if: steps.backend_changed.outputs.changed == 'true'
        working-directory: backend
        env:
          SUPABASE_URL: https://example.supabase.co
          SUPABASE_SERVICE_KEY: ci-dummy-supabase-service-key
        run: python -m pytest -q -m "not integration" -p no:cacheprovider
```

- [ ] **Step 4: Validar sintaxe YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml', encoding='utf-8')); print('yaml-ok')"`
Expected: `yaml-ok`

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/deploy.yml backend/requirements-dev.txt
git commit -m "ci(backend): suite pytest como gate bloqueante do deploy (py3.12 = prod)"
```

---

### Task 2: Gate de testes no CI — frontend

**Files:**
- Modify: `.github/workflows/deploy.yml:8-46` (job `deploy-crm`)

**Interfaces:**
- Produces: step "Run frontend tests" (`npm run test` = `vitest run`) que bloqueia o deploy do CRM. O teste-guarda da Task 3 roda dentro deste gate.

- [ ] **Step 1: Adicionar setup-node com cache antes de "Install dependencies"**

```yaml
      - name: Set up Node
        if: steps.crm_changed.outputs.changed == 'true'
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: npm
          cache-dependency-path: frontend/package-lock.json
```

- [ ] **Step 2: Adicionar step de testes entre "TypeScript type-check" e "Next.js build validation"**

```yaml
      - name: Run frontend tests
        if: steps.crm_changed.outputs.changed == 'true'
        working-directory: frontend
        run: npm run test
```

- [ ] **Step 3: Validar sintaxe YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml', encoding='utf-8')); print('yaml-ok')"`
Expected: `yaml-ok`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci(crm): vitest como gate bloqueante + setup-node 20 com cache npm"
```

---

### Task 3: Teste-guarda de cobertura do matcher (TDD) + fechar o matcher

**Files:**
- Create: `frontend/src/lib/auth/proxy-coverage.test.ts`
- Modify: `frontend/src/proxy.ts:70-101` (config.matcher)
- Modify: `frontend/src/lib/auth/roles.ts` (ADMIN_API_PREFIXES, ROLE_PAGES)

**Interfaces:**
- Consumes: `src/proxy.ts` lido como TEXTO (fs) — o matcher precisa continuar literal estático, então o teste extrai as entradas por regex em vez de importar o módulo.
- Produces: teste que enumera `src/app/api/*` (dirs de 1º nível) e `src/app/(authenticated)/*` (dirs de página) e falha para qualquer item fora do matcher e fora das listas `PUBLIC_*` do próprio teste.

- [ ] **Step 1: Escrever o teste-guarda (deve FALHAR contra o matcher atual)**

`frontend/src/lib/auth/proxy-coverage.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

// vitest roda com cwd = frontend/ (root do projeto); a suíte inteira depende disso.
const SRC = path.resolve(process.cwd(), "src");

// Itens deliberadamente públicos (sem sessão). Adicionar aqui exige revisão consciente.
const PUBLIC_API_PREFIXES: string[] = [];
const PUBLIC_PAGES: string[] = [];

function matcherEntries(): string[] {
  const source = fs.readFileSync(path.join(SRC, "proxy.ts"), "utf8");
  const block = source.match(/matcher:\s*\[([\s\S]*?)\]/);
  if (!block) throw new Error("config.matcher não encontrado em src/proxy.ts");
  return [...block[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}

function topLevelDirs(relative: string): string[] {
  return fs
    .readdirSync(path.join(SRC, relative), { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name);
}

function covered(prefix: string, entries: string[]): boolean {
  return entries.some((e) => e === prefix || e.startsWith(`${prefix}/`));
}

describe("cobertura do config.matcher do proxy (gating de auth)", () => {
  const entries = matcherEntries();

  it("toda rota /api/* de 1º nível está no matcher ou é pública explícita", () => {
    const missing = topLevelDirs("app/api")
      .map((dir) => `/api/${dir}`)
      .filter((p) => !covered(p, entries) && !PUBLIC_API_PREFIXES.includes(p));
    expect(missing, `Rotas de API fora do matcher do proxy.ts: ${missing.join(", ")}`).toEqual([]);
  });

  it("toda página autenticada está no matcher ou é pública explícita", () => {
    const missing = topLevelDirs("app/(authenticated)")
      .map((dir) => `/${dir}`)
      .filter((p) => !covered(p, entries) && !PUBLIC_PAGES.includes(p));
    expect(missing, `Páginas fora do matcher do proxy.ts: ${missing.join(", ")}`).toEqual([]);
  });
});
```

- [ ] **Step 2: Rodar e confirmar falha listando os gaps conhecidos**

Run: `cd frontend && npx vitest run src/lib/auth/proxy-coverage.test.ts`
Expected: FAIL — mensagem citando `/api/conversions, /api/lp-webhook, /api/me, /api/model-pricing, /api/quick-replies, /api/sales, /api/system-alerts` e `/painel-vendas`.

- [ ] **Step 3: Completar o matcher em `proxy.ts`**

No array `config.matcher`, adicionar (mantendo os existentes, ordem alfabética não exigida):

```ts
    "/painel-vendas/:path*",
    "/api/conversions/:path*",
    "/api/lp-webhook/:path*",
    "/api/me/:path*",
    "/api/model-pricing/:path*",
    "/api/quick-replies/:path*",
    "/api/sales/:path*",
    "/api/system-alerts/:path*",
```

- [ ] **Step 4: Prefixos admin-only e ROLE_PAGES em `roles.ts`**

```ts
export const ADMIN_API_PREFIXES = [
  "/api/stats",
  "/api/evolution",
  "/api/admin",
  "/api/users",
  "/api/model-pricing",
  "/api/lp-webhook",
];
```

E em `ROLE_PAGES`, adicionar `"/painel-vendas"` **às duas listas** (admin e vendedor) — não muda `isAdminOnlyPage` (a página não vira admin-only), apenas documenta.

- [ ] **Step 5: Rodar o teste-guarda e a suíte inteira**

Run: `cd frontend && npm run test`
Expected: PASS (136+ testes, incluindo os 2 novos), zero failed.

Run: `cd frontend && npm run type-check`
Expected: sem erros.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/proxy.ts frontend/src/lib/auth/roles.ts frontend/src/lib/auth/proxy-coverage.test.ts
git commit -m "fix(auth): fecha rotas e /painel-vendas fora do matcher do proxy + teste-guarda de cobertura"
```

---

### Task 4: Verificação de runtime (comportamento real, não só testes)

**Files:** nenhum (verificação).

- [ ] **Step 1: Build de produção local**

Run: `cd frontend && npm run build`
Expected: build conclui sem erro (valida que o matcher novo é aceito estaticamente pelo Next).

- [ ] **Step 2: Subir dev server e provar o 401/redirect sem sessão**

Run: `cd frontend && npm run dev` (background, porta 3000), depois:

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/api/system-alerts      # esperado: 401
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/api/sales/metrics      # esperado: 401
curl -s -o /dev/null -w "%{http_code}" -H "accept: text/html" http://localhost:3000/painel-vendas  # esperado: 307 (Location: /login)
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/login                  # esperado: 200 (público)
```

`getUser()` sem cookie falha localmente ("Auth session missing") sem depender de rede — resultado determinístico.

- [ ] **Step 3: Derrubar o dev server e relatar resultados**

Matar o processo do dev server. Nenhum arquivo temporário deve restar.

---

### Task 5: Docs + fechamento

**Files:**
- Commit: `docs/superpowers/specs/2026-07-09-ci-test-gate-design.md`, `docs/superpowers/specs/2026-07-09-proxy-auth-coverage-design.md`, `docs/superpowers/plans/2026-07-09-ci-test-gate-proxy-auth.md`

- [ ] **Step 1: Commitar specs e plano**

```bash
git add docs/superpowers/specs/2026-07-09-ci-test-gate-design.md docs/superpowers/specs/2026-07-09-proxy-auth-coverage-design.md docs/superpowers/plans/2026-07-09-ci-test-gate-proxy-auth.md
git commit -m "docs: specs e plano do gate de testes no CI + cobertura de auth do proxy"
```

- [ ] **Step 2: Apresentar diff consolidado ao usuário e aguardar autorização para `git push origin feat/ci-test-gate-api-auth:master`** (regra inegociável do CLAUDE.md — o push aciona deploy).

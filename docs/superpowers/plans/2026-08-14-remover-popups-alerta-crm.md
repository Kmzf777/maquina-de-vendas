# Remoção dos pop-ups de alerta do CRM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar todo pop-up de `system_alerts` do CRM (qualquer severidade, qualquer usuário), sem tocar no backend de alertas.

**Architecture:** Remoção pontual no frontend. O `SystemAlertBanner` é desmontado do `RootLayout` e o arquivo é deletado — a rota `/api/system-alerts` permanece viva mas sem consumidor. Todo o `backend/app/alerts/` fica intocado: a gravação em `system_alerts`, o despacho Sentry e o WhatsApp ao admin (já restrito a `llm_down`/`llm_budget_exceeded` pelo commit `54577b7`) seguem funcionando.

**Tech Stack:** Next.js App Router (React 19, Tailwind).

**Spec:** `docs/superpowers/specs/2026-08-14-remover-popups-alerta-crm-design.md`

## Global Constraints

- **Não usamos Pull Requests.** Fluxo: branch → implementar/testar → `git pull origin master` → `git push origin feat/remover-popup-crm:master`. O push é de produção e depende de autorização explícita do usuário.
- Branch de trabalho: `feat/remover-popup-crm`, criada a partir de `origin/master` (`74e0b22`).
- **Nenhum arquivo em `backend/` pode ser alterado.** A versão anterior deste plano previa remover o despacho WhatsApp ao admin; a decisão foi revertida ao descobrir que `3bbdb14` e `54577b7` já haviam restringido o despacho aos dois alertas de LLM. Ver a seção "Decisão revisada" na spec.
- `frontend/src/app/api/system-alerts/route.ts` e `frontend/src/proxy.ts` **não** são alterados.
- Comentários e docstrings em PT-BR.

## File Structure

| Arquivo | Ação | Responsabilidade após a mudança |
|---|---|---|
| `frontend/src/app/layout.tsx` | Modificar | `RootLayout` renderiza só `{children}` — sem overlay global |
| `frontend/src/components/SystemAlertBanner.tsx` | **Deletar** | — |

---

### Task 1: Remover o banner de alertas do frontend

**Files:**
- Modify: `frontend/src/app/layout.tsx:4` (import) e `:28` (JSX)
- Delete: `frontend/src/components/SystemAlertBanner.tsx`

**Interfaces:**
- Consumes: nada.
- Produces: `RootLayout` continua exportado como default com a mesma assinatura `({ children }: { children: React.ReactNode })`.

**Contexto:** não há suíte React configurada para este componente neste repo. A verificação é o typecheck do TypeScript e a varredura por referências órfãs — por isso os passos de verificação substituem o ciclo TDD aqui.

- [x] **Step 1: Remover o import e o JSX do layout**

Em `frontend/src/app/layout.tsx`, apagar a linha 4:

```tsx
import SystemAlertBanner from "@/components/SystemAlertBanner";
```

E apagar a linha 28 (`<SystemAlertBanner />`), deixando o `<body>` assim:

```tsx
      <body suppressHydrationWarning className={`${geist.variable} ${geist.className}`}>
        {children}
      </body>
```

- [x] **Step 2: Deletar o componente**

```bash
git rm frontend/src/components/SystemAlertBanner.tsx
```

- [x] **Step 3: Verificar que não sobrou referência órfã**

```bash
grep -rn "SystemAlertBanner" frontend/src
```

Expected: nenhuma saída (exit 1 do grep).

- [x] **Step 4: Verificar que compila**

```bash
cd frontend && npx tsc --noEmit
```

Expected: nenhuma saída (sucesso).

- [x] **Step 5: Commit**

```bash
git add frontend/src/app/layout.tsx
git commit -m "feat(crm): remove pop-up global de alertas de sistema"
```

---

### Task 2: Registrar spec e plano

**Files:**
- Create: `docs/superpowers/specs/2026-08-14-remover-popups-alerta-crm-design.md`
- Create: `docs/superpowers/plans/2026-08-14-remover-popups-alerta-crm.md` (este arquivo)

**Interfaces:**
- Consumes: nada. Produces: nada.

- [x] **Step 1: Commit da documentação**

```bash
git add docs/superpowers/specs/2026-08-14-remover-popups-alerta-crm-design.md docs/superpowers/plans/2026-08-14-remover-popups-alerta-crm.md
git commit -m "docs: spec e plano da remocao do pop-up de alertas"
```

- [x] **Step 2: Confirmar que o diff não toca o backend**

```bash
git diff origin/master --stat
```

Expected: apenas `frontend/src/app/layout.tsx`, `frontend/src/components/SystemAlertBanner.tsx` e arquivos em `docs/`.

---

### Task 3: Deploy

- [ ] **Step 1: Atualizar com a master e subir**

```bash
git pull origin master
git push origin feat/remover-popup-crm:master
```

O push dispara o deploy de produção via GitHub Actions.

- [ ] **Step 2: Verificar o deploy**

Acompanhar a run do GitHub Actions até o fim e confirmar que o serviço `crm` do Swarm subiu com a nova imagem.

---

## Critérios de aceitação (verificação final)

1. `grep -rn "SystemAlertBanner" frontend/src` → vazio.
2. `npx tsc --noEmit` no frontend → limpo.
3. `git diff origin/master --stat` não lista nenhum arquivo em `backend/`.
4. Deploy do GitHub Actions conclui com sucesso.

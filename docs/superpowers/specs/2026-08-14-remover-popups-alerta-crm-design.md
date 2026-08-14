# Remoção dos pop-ups de alerta do CRM

**Data:** 2026-08-14 · **Escopo:** frontend (banner global) · **Branch:** `feat/remover-popup-crm`

## Problema

O `SystemAlertBanner`, montado globalmente em `frontend/src/app/layout.tsx:28`, sequestra a
tela de **todo** usuário do CRM com um modal bloqueante de backdrop preto sempre que existe
qualquer linha em `system_alerts` com `resolved = false`. Na prática:

1. **O modal é inescapável e recorrente.** "Dispensar" grava só no `localStorage`
   (`crm_dismissed_alerts`) do navegador de quem clicou — o próprio banner admite isso no
   texto ("outros usuários continuam vendo este alerta"). O alerta volta em outro
   navegador, em aba anônima e para qualquer colega.
2. **O alerta não é acionável pelo operador de vendas.** O conteúdo é diagnóstico de
   infraestrutura ("Verifique backend/worker/LLM"). Quem usa o CRM para atender lead não
   tem o que fazer com isso, mas paga o custo de ter a tela bloqueada a cada 60s de polling.

## O quê (comportamento-alvo)

### F1 — Nenhum pop-up de `system_alerts` no CRM

- Nenhum alerta de sistema renderiza no CRM, para nenhum usuário, em nenhuma tela e em
  nenhuma severidade: nem o modal vermelho (`critical`/`error`), nem o modal âmbar
  (`warning`), nem o cartão azul discreto (`info`).
- O CRM deixa de fazer o polling de 60s contra `/api/system-alerts`.
- O endpoint `GET|PATCH /api/system-alerts` e sua entrada no `proxy.ts` **permanecem**,
  para consulta e resolução manual via HTTP.

## Por quê (regras de negócio)

- Alerta que bloqueia a tela de quem não pode resolvê-lo não reduz MTTR: gera
  dessensibilização e treina o time a clicar "Entendido" sem ler.
- A dispensa por `localStorage` torna o banner estruturalmente incapaz de "sumir" —
  qualquer alerta não resolvido reaparece indefinidamente para toda a base de usuários.
  Não existe ajuste de severidade que conserte isso; o canal está errado.
- O histórico em `system_alerts` continua sendo a fonte de verdade para auditoria; o
  WhatsApp do admin e o Sentry continuam sendo os canais de incidente.

## Decisão revisada sobre o backend (14/08/2026)

A versão original desta spec previa também **remover o despacho WhatsApp ao admin**
(`_notify_whatsapp_admin` em `backend/app/alerts/service.py`), sob a premissa de que todo
alerta `critical` virava mensagem no WhatsApp do operador — o mesmo ruído em outro canal.

Essa premissa estava **desatualizada**. Os commits `3bbdb14` (11/08, template utility para
entrega fora da janela de 24h) e `54577b7` (11/08, allowlist
`_DEFAULT_WHATSAPP_ADMIN_ALERT_TYPES = "llm_down,llm_budget_exceeded"`) já haviam resolvido
o problema na master: hoje só os dois alertas do domínio "o LLM não vai atender" acordam o
admin. `ai_unresponsive`, `handoff_sla_*` e `billing_payment_issue` já não disparam WhatsApp.

**Decisão:** o backend fica intocado. `create_system_alert`, `_notify_external`,
`_notify_whatsapp_admin` e a allowlist permanecem como estão na master. O escopo desta
mudança é exclusivamente o pop-up do CRM.

Consequência positiva: o canal de incidente **não** passa a depender só do e-mail do
Sentry. Quando o LLM cai, o admin continua sendo avisado no WhatsApp — que era o risco
levantado na versão anterior desta spec e agora não se aplica.

## Design

### F1.1 Desmontagem do banner (`frontend/src/app/layout.tsx`)

Remover o `import SystemAlertBanner from "@/components/SystemAlertBanner"` e o
`<SystemAlertBanner />` do `<body>`. O `RootLayout` passa a renderizar apenas `{children}`.

### F1.2 Remoção do componente

Deletar `frontend/src/components/SystemAlertBanner.tsx`. É o único consumidor de
`/api/system-alerts` no frontend (verificado por varredura: apenas `proxy.ts:110` e o
próprio `route.ts` mencionam a rota). Deletar o arquivo garante que a remontagem seja uma
decisão consciente, não um `git revert` de uma linha.

### F1.3 O que NÃO muda

- `frontend/src/app/api/system-alerts/route.ts` — intocado.
- `frontend/src/proxy.ts:110` — intocado.
- Tabela `system_alerts` e as linhas existentes — intocadas.
- Todo o `backend/app/alerts/` — intocado.

## Limitação conhecida: propagação

Usuários com a aba do CRM **já aberta** no momento do deploy continuam executando o bundle
antigo até um reload (ou até uma navegação que puxe o novo build). O pop-up pode aparecer
mais uma vez para eles. Não há ação necessária — resolve no primeiro refresh.

## Critérios de aceitação

1. `grep -r "SystemAlertBanner" frontend/src` não retorna nada.
2. Nenhum elemento com `z-[9999]` renderiza no CRM (o banner era o único uso).
3. `npx tsc --noEmit` no frontend compila sem erro de import órfão.
4. `git diff origin/master --stat` toca apenas `frontend/src/app/layout.tsx`,
   `frontend/src/components/SystemAlertBanner.tsx` e `docs/`.

# Desligar o pop-up de SLA ("Lead sem resposta há…")

Cartão: "Desativar aviso pop up que aparece quando o lead está esperando há um tempo" (ca54ae27).

## Problema

Hoje o vendedor vê, no CRM, um pop-up laranja que abre sozinho:
**"SLA de atendimento — Lead sem resposta há X"**. Ele aparece quando um lead passa de
40 min de atendimento sem resposta (`SLA_REMINDER_MINUTES`). O Rafael quer **desativar esse aviso pop-up**.
Decisão dele (opção A): desligar de vez, para todos, sem botão liga/desliga.

## O que muda

- `frontend/src/components/authenticated-shell.tsx`: deixa de montar `<SlaReminderPopup />`
  e remove o import. É a única mudança de comportamento.
- Teste novo: `frontend/src/components/authenticated-shell.test.tsx` (ou o teste que já
  existir do shell). Ele afirma que o shell, renderizado como vendedor e com um lead
  atrasado, **não** mostra o texto "Lead sem resposta há". Esse teste falha antes da
  mudança e passa depois (TDD).
- `sla-reminder-popup.tsx`, `lib/sla-reminder.ts` e os testes deles **ficam no repositório**,
  sem uso, para religar depois com uma linha. Uma linha de comentário no shell registra isso.

## O que fica de fora

- O painel de leads atrasados no dashboard (`overdue-leads-section`, `use-overdue-leads`)
  e a tabela de SLA continuam iguais.
- O `NotificationToast` (aviso de mensagem nova) continua igual.
- Não há botão liga/desliga, nem mudança no banco ou no backend.

## Como testar em modo teste

- No worktree `ValerIA-agente-ca54ae27` (branch `agente/ca54ae27`):
  `cd frontend && npx vitest run` (a suíte inteira passa, inclusive o teste novo e os testes
  do pop-up, que continuam testando o componente isolado), `npx tsc --noEmit` e `npm run lint`.
- Print: subir o CRM local (`npm run dev` no frontend, apontando para o Supabase de sempre)
  e tirar o print de `/conversas` logado. O usuário de teste do print é admin, e para admin o
  pop-up já não aparecia. Por isso o print só mostra que a tela abre normal; quem prova a
  ausência para o vendedor é o teste automático.

## Como publicar

1. `git pull origin master` no branch, merge de `agente/ca54ae27` em `master` e `git push origin master`.
2. O GitHub Actions (`.github/workflows/deploy.yml`, job `deploy-crm`) detecta a mudança em
   `frontend/`, roda lint/testes/build e na VPS recompila `canastra-crm:latest` e atualiza `crm_crm`.
   O backend não muda.
3. Acompanhar o run (`gh run watch`) e conferir na VPS: `docker service ps crm_crm` (task nova
   Running) e `docker service logs crm_crm --tail 50` sem erro.
4. Para voltar atrás: `git revert` do merge e push em `master`. O mesmo pipeline republica a versão anterior.

## Como testar em produção

- Conferir que o bundle publicado não monta mais o pop-up: buscar "Lead sem resposta há" nos chunks
  JS servidos pelo CRM em produção. O texto não pode aparecer, porque o componente sem uso sai do bundle.
  Se aparecer por algum motivo, a prova passa a ser o print abaixo.
- Print de `/conversas` em produção logado, mostrando a tela normal.
- Nenhuma ação com efeito externo: nada de mensagem a cliente, venda, pedido, NF ou cobrança.
  Só leitura de tela e de logs.

# Envio do CRM para o número real do WhatsApp + motivo da falha na bolha

Cartão: "URGENTE: mensagens do vendedor não chegam ao cliente no WhatsApp do CRM (ícone vermelho de erro)" (7c6b70e7). Opção escolhida pelo Rafael: **B** (corrigir o envio + mostrar o motivo da falha).

## Problema

Relato do João (06/11 15:05): "Por que essa cliente não recebe as minhas mensagens? Eu acho que eu estava respondendo ela e não está chegando nada."

O que a investigação mostrou:

- O WhatsApp da Carolaine (MVX Rótulos) é **número fixo**. O endereço dela na Meta é `553732140027`: é o `from` de todas as mensagens dela e o `recipient_id` das entregas feitas pela Valeria.
- No cadastro, `leads.phone` ficou `5537932140027`, porque a normalização colocou o 9º dígito. `leads.wa_id` guarda o endereço certo, `553732140027`, com procedência (`wa_id_confirmed_at` = 23/09).
- O backend (Valeria, follow-up, disparo) já envia pelo `resolve_send_target` (`backend/app/leads/service.py`), que prefere o `wa_id`. Por isso a Valeria entregou.
- As rotas de envio do CRM (Next.js) usam `lead.phone`. A Meta responde HTTP 200 com wamid e, depois, manda pelo webhook o status `failed` com **131026 "Message undeliverable"**. Está nos `meta_webhook_logs`: as 5 mensagens do João para a Carolaine (23/09, 24/09 e 06/11) falharam assim, com `recipient_id` `5537932140027`.
- A linha do número do João está conectada: em 06/11 ele entregou 77 mensagens.
- O ícone vermelho está **certo**: a mensagem não chegou. O que falta é o motivo. O webhook recebe o erro, mas só grava esse erro para mensagens de disparo (broadcast_leads). Nas outras mensagens o erro se perde.
- Outros clientes que o João não alcançou pelo mesmo motivo, todos com número fixo: Roger/Cooper-Arts, Vitta Belle e Alex (24/09).

## O que muda

### 1. Envio do CRM para o endereço entregável (frontend)

- Novo helper `frontend/src/lib/whatsapp/send-target.ts`, espelho do `resolve_send_target` do backend:
  - `resolveSendTarget(lead, { requireInboundProvenance })` devolve o `wa_id` quando ele existe. Quando `requireInboundProvenance = true`, o `wa_id` só vale se o lead tiver `wa_id_confirmed_at` ou `last_customer_message_at`.
  - Sem `wa_id` aceito, devolve `phone` e depois `bsuid`, igual ao backend.
- As rotas abaixo passam a selecionar `leads(id, phone, wa_id, wa_id_confirmed_at, last_customer_message_at, bsuid, opt_out)` e a enviar para `resolveSendTarget(...)`. Hoje enviam para `lead.phone`:
  - `frontend/src/app/api/conversations/[id]/send/route.ts`: texto, só o ramo `meta_cloud`. Os caminhos Evolution (desativados, CLAUDE.md §6) não mudam.
  - `frontend/src/app/api/conversations/[id]/send-media/route.ts`
  - `frontend/src/app/api/conversations/[id]/react/route.ts`
  - `frontend/src/app/api/conversations/[id]/send-template/route.ts`, com `requireInboundProvenance: true`, porque o modelo pode ser o primeiro contato (caminho frio), igual ao disparo do backend.
- O bloqueio de lead (`isLeadBlocked`), o registro da mensagem, o follow-up e o recibo de leitura continuam como estão.

### 2. Gravar o motivo da falha (backend)

- `backend/app/webhook/meta_router.py`, em `_handle_delivery_status`: quando o status é `failed`, além de mudar o `delivery_status`, grava em `messages.metadata.delivery_error` o objeto `{code, title, details, at}`, tirado de `errors[0]`.
  - Faz *merge* no `metadata` que já existe: lê, junta e grava, só nesse caminho, que é raro. Assim não apaga `metadata.interativo` e outras chaves.
  - Vale para todas as mensagens, não só disparo. A lógica atual de broadcast fica igual.
  - Se a linha ainda não existe (corrida com a persistência), usa as mesmas retentativas do status.

### 3. Mostrar o motivo na bolha (frontend)

- `frontend/src/lib/delivery-error.ts`: `deliveryErrorText(status, metadata)` devolve o texto em pt-BR:
  - 131026: "Não entregue: número sem WhatsApp, número errado ou o cliente bloqueou."
  - 131047: "Não entregue: passou a janela de 24h. Só dá para enviar modelo aprovado."
  - 131042: "Não entregue: problema de pagamento na conta da Meta."
  - 131049: "Não entregue: a Meta limitou mensagens de marketing para este cliente."
  - Outro código: "Não entregue: <title da Meta> (código <code>)."
  - `failed` sem erro gravado: "Não entregue (motivo não registrado)."
  - `undelivered`: "Entrega não confirmada pela Meta."
- `frontend/src/components/conversas/message-bubble.tsx`: mensagem com `failed` ou `undelivered` ganha uma linha pequena em vermelho logo abaixo da bolha, com esse texto. Ela aparece sempre, sem depender de passar o mouse, para funcionar também no celular. O ícone ganha `title` com o mesmo texto.

### 4. Preencher o motivo das falhas antigas (dado, uma vez)

- Script SQL único, versionado em `backend/scripts/backfill_delivery_error.sql`. Para cada status `failed` com `errors` nos `meta_webhook_logs` dos últimos 90 dias, grava `metadata.delivery_error` na mensagem com o mesmo `wamid` que esteja `failed` e ainda não tenha `delivery_error`.
- Só **acrescenta** uma chave no jsonb. Não apaga nem altera nenhuma outra coluna nem mensagem.
- Para desfazer: `update messages set metadata = metadata - 'delivery_error' where metadata ? 'delivery_error'`.

## O que fica de fora

- Não altera `leads.phone` nem a normalização do telefone (o 9º dígito). O `wa_id` já resolve o envio, e mexer na normalização afeta importação, busca e deduplicação.
- Não reenvia nada automaticamente. Quem decide reenviar é o vendedor.
- Valdemar, Gustavo e outros: os follow-ups do backend já foram enviados para o `wa_id` e mesmo assim deram 131026. Esses números de fato não recebem, então não é este defeito. Depois do deploy, a linha vermelha vai mostrar o motivo.
- Evolution (desativado) e `/api/media`: não mudam. O Dev Router do `meta_router.py` continua antes do parsing; a mudança fica só no handler de status.

## Como testar em modo teste

Tudo no worktree `.claude/worktrees/agente-7c6b70e7`, branch `agente/7c6b70e7`, sem tocar em produção:

1. **vitest** (`cd frontend && npm test`):
   - `resolveSendTarget`: lead com `wa_id` ≠ `phone` devolve `wa_id`. Sem `wa_id`, devolve `phone`. Sem `phone`, devolve `bsuid`. Com `requireInboundProvenance` e sem procedência, devolve `phone`.
   - Rota `send`, com fetch e Supabase mockados e o lead da Carolaine (`phone 5537932140027`, `wa_id 553732140027`): o corpo enviado à graph.facebook.com tem `to: "553732140027"`. Este teste falha antes da correção. O mesmo vale para `send-media`, `react` e `send-template`, este último com e sem procedência.
   - `deliveryErrorText`: cada código, o caso sem erro e o `undelivered`.
2. **pytest** (`cd backend && pytest`): `_handle_delivery_status` com `failed` + errors 131026 grava `metadata.delivery_error` e mantém `metadata.interativo`. Com `delivered`, não grava nada. A suíte inteira continua verde.
3. `npx tsc --noEmit` e `npm run build` do frontend.
4. **Print** do frontend local (`npm run dev`, mesmo `.env.local`, só leitura) da conversa da Carolaine em `/conversas` no canal do João. Antes do preenchimento das falhas antigas, as bolhas mostram a linha vermelha "Não entregue (motivo não registrado)", o que prova o layout. O print vai para `.claude/worktrees/prints/agente-7c6b70e7`.

Nenhum envio real nem gravação no banco em modo teste.

## Como publicar

1. No worktree: `git pull origin master` (merge) e testes de novo.
2. `git push origin agente/7c6b70e7:master`, conforme o CLAUDE.md do repo. O GitHub Actions (`deploy.yml`) roda type-check, testes e build, e atualiza `crm_crm` (frontend) e `canastra_api` + `canastra_worker` (backend).
3. Acompanhar o workflow até ficar verde e conferir `docker service ls` / `docker service ps` dos 3 serviços na VPS.
4. Rodar o `backfill_delivery_error.sql` no `supabase_db`, com contagem antes e depois.
5. **Voltar atrás:** `git revert <commit>` + push para master, que dispara novo deploy. Em emergência, `docker service rollback crm_crm` / `canastra_api` / `canastra_worker`. Para o dado, o `update` de desfazer da seção 4.

## Como testar em produção

- **Sem mensagem a cliente feita por mim.** Não há número nosso em linha fixa para reproduzir o caso.
- Tela: print de `/conversas` na conversa da Carolaine (só leitura), com a linha "Não entregue: número sem WhatsApp, número errado ou o cliente bloqueou." nas 5 bolhas antigas, vinda do preenchimento.
- Logs: `docker service logs canastra_api` sem erro novo no `_handle_delivery_status`. No banco, as próximas falhas reais passam a nascer com `delivery_error`.
- Prova de entrega: o João reenvia a resposta à Carolaine. Isso é atendimento dele, não teste, e a conversa está aberta até 07/11 14:58. Eu confiro nos `meta_webhook_logs` que o `recipient_id` é `553732140027` e o status chega a `delivered`/`read`, e mostro a bolha sem a linha vermelha.
- Regressão: comparar entregues e falhas das mensagens `seller` do canal do João nas horas seguintes ao deploy com o padrão de hoje (quase tudo `delivered`/`read`).

## O que dizer ao João

Depois do deploy: "O WhatsApp da Carolaine é número fixo e o CRM mandava com um 9 a mais, por isso nada chegou. Já corrigimos: pode reenviar. Agora, quando uma mensagem não chegar, o CRM mostra o motivo embaixo dela." Roger/Cooper-Arts, Vitta Belle e Alex também não receberam as mensagens de 24/09. Como já passaram 24h, para falar com eles de novo é preciso usar modelo aprovado.

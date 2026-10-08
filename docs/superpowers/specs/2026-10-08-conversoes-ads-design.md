# Devolução de conversões para Meta e Google Ads — spec

**Data:** 2026-10-08
**Branch:** `feat/conversoes-ads` (de `origin/master` em `f9cff5de`)
**Substitui:** a entrega de `2026-07-02-ad-conversion-attribution-design.md` (gatilho por etapa do
Kanban + CSV manual do Google), que nunca disparou: `conversion_events` tem 0 linhas e nenhuma
etapa tem `conversion_event` (conferido em 08/10/2026).

---

## 1. Problema

O CRM sabe quem virou lead qualificado, quem recebeu orçamento e quem comprou, mas Meta e Google
não sabem. As campanhas otimizam para "conversa iniciada", e a call de 01/10 registrou o efeito:
R$ 5–6 mil/mês de investimento sem retorno medido, com a venda de kit como "a única chance de essas
campanhas ficarem positivas".

O objetivo é devolver às plataformas, automaticamente, as etapas do funil de cada lead que veio de
um clique de anúncio, com valor, para que (a) a medição no Gerenciador/Google Ads mostre vendas e
(b) os lances aprendam a buscar quem qualifica e compra.

## 2. Decisões (brainstorming de 07–08/10/2026)

| Tema | Decisão |
|---|---|
| Etapa "qualificado" | **Repasse ao vendedor** (`leads.metadata.handoff` gravado), venha do LLM, da ValerIA de botões v1/v2 (inclusive `T_KIT` e repasse automático de parados). Exclui o fluxo de Recuperação (reativação da base). |
| Valor nas etapas intermediárias | **Valor estimado calculado do histórico**, por segmento, aprovado pelo Rafael antes de valer. Venda vai com o valor real. |
| Entrega no Google | **Automática pela Data Manager API.** O CSV manual sai. |
| Visibilidade | **Aba "Conversões enviadas" no /trafego.** Sem reenvio nem liga/desliga pela tela. |
| Arquitetura | **Fila no banco + tarefa no worker.** |
| Captura | **Varredura periódica no worker**, não trigger no banco: pega venda lançada pelo Bling num lead duplicado que só é mesclado depois (caso "Jovens com uma missão"), e o backfill vira a mesma varredura. |
| Quem já era cliente | **Só a venda** é enviada (`leads.ja_era_cliente = true`). Lead/qualificado/oportunidade não — ensinariam o algoritmo a buscar a base atual. `NULL` conta como cliente novo. |

## 3. Restrições das plataformas (pesquisa de 07/10/2026)

**Meta — Conversions API for Business Messaging** (o "Conversion Leads" só serve para formulário
instantâneo, não CTWA).
- `action_source: "business_messaging"`, `messaging_channel: "whatsapp"`,
  `user_data: {whatsapp_business_account_id, ctwa_clid, ph[]}`.
- Eventos padrão aceitos: `LeadSubmitted`, `InitiateCheckout`, `Purchase` (entre outros; não usamos
  `QualifiedLead`). Nome customizado não.
- Destino: dataset ligado ao WABA (criado uma vez pela Dataset API). Token de system user com
  `whatsapp_business_management` + `whatsapp_business_manage_events`.
- `event_time` no máximo **7 dias** antes do envio; um evento fora da janela derruba o request
  inteiro. A Meta não deduplica nesse produto — a dedup é nossa.
- Otimização: a meta "Maximizar o número de leads por mensagens" otimiza em eventos de lead enviados
  pela API (mín. 10 eventos de lead ou compra em 30 dias, marcados em até 7 dias do clique). Por isso
  o `LeadSubmitted` vai no **repasse ao vendedor** (`qualified`), não no clique: mandar um por clique
  viraria "maximizar conversas", que a Meta já conta sozinha. `QualifiedLead` não está confirmado como
  evento de otimização em CTWA e não é usado. **Confirmar no Gerenciador** (ver §12).

**Google — Data Manager API** (desde 15/06/2026 o `UploadClickConversions` da Google Ads API recusa
developer tokens que não o usavam; vale para nós).
- `POST https://datamanager.googleapis.com/v1/events:ingest`, OAuth com escopo
  `https://www.googleapis.com/auth/datamanager`. Não exige developer token.
- `destinations[].operatingAccount` = conta `1861416291`; `productDestinationId` = ID da conversion
  action, tipo **"Importar de cliques"** (UPLOAD_CLICKS).
- Evento: `adIdentifiers.{gclid|gbraid|wbraid}`, `userData.userIdentifiers` (e-mail e telefone
  SHA-256 hex), `transactionId`, `eventTimestamp` RFC 3339 com fuso, `conversionValue` em reais
  (não micros), `currency: "BRL"`, `consent` GRANTED.
- Sem `partial_failure`: um erro rejeita o lote. Clique com até **90 dias**.

## 4. Dados que já existem (não reconstruir)

- `leads.ctwa_clid`, `gclid`, `meta_ad_id`, `email`, `wa_id`, `phone`, `stage`, `ja_era_cliente`,
  `metadata.handoff = {vendedor_id, vendedor, segmento, motivo, at}`.
- **Histórico de cliques:** `lead_events` com `event_type='entrada'`, `occurred_at` = hora do clique,
  `metadata.{ctwa_clid, gclid, meta_ad_id, campanha_id, campanha_nome}` (trigger de
  `20261006b_lead_timeline_triggers.sql`). 695 dos 699 leads com `gclid` dos últimos 90 dias têm a
  entrada correspondente. Fallback para lead sem entrada: `leads.created_at` com o clique atual.
- `sales` (value, sold_at, status, lead_id) + `sale_items` (kit = `descricao ~* 'kit degust'`),
  `quotes` (status `enviado`), `deals` + `pipeline_stages.key = 'proposta_enviada'`.
- WABA: os 3 canais `meta_cloud` usam o mesmo `waba_id` (`channels.provider_config`).
- OAuth do Google: `campaigns/google_ads.py` (refresh token → access token).
- Hash SHA-256 de e-mail/telefone: `campaigns/capi_dispatcher.py:59-80`.

## 5. Etapas e elegibilidade

| Etapa | Fonte (varredura) | Hora do evento | Meta | Google |
|---|---|---|---|---|
| `lead` | `lead_events` `entrada` com `ctwa_clid` ou `gclid` | `occurred_at` | não enviado (a Meta já conta a conversa) | ação LEAD |
| `qualified` | `leads.metadata.handoff.at` preenchido | `handoff.at` | `LeadSubmitted` | ação QUALIFIED |
| `opportunity` | 1º entre `quotes.status in ('enviado','aprovado','convertido')` (`quoted_at`) e entrada do deal em `proposta_enviada` (`lead_events` `etapa`) | o que vier primeiro | `InitiateCheckout` | ação OPPORTUNITY |
| `purchase` | `sales` com `status <> 'cancelada'` | `sold_at`, ajustado (abaixo) | `Purchase` | ação PURCHASE |

**Hora da venda.** `sales.sold_at` é só a data (Bling, CRM e manual gravam 12:00 ou 15:00 UTC —
conferido em produção). Lido cru, uma venda do mesmo dia do clique pareceria anterior a ele (clique
14:00 BRT, `sold_at` = 09:00 BRT) e nunca teria clique atribuído. Regra (mesma ideia de
`quotes.quoted_at`): se `sales.created_at` cai no mesmo dia de São Paulo que o `sold_at`, a hora do
evento é `max(sold_at, created_at)`; se a venda foi lançada em outro dia (retroativa), vale o
`sold_at`.

**Clique atribuído** = a `entrada` mais recente do lead com ID de clique da plataforma e
`occurred_at <= hora do evento`.

**Regras de elegibilidade** (função pura, testada):
1. Existe clique atribuído da plataforma (Meta: `ctwa_clid`; Google: `gclid`/`gbraid`/`wbraid`).
2. Janela clique→evento: Meta ≤ 7 dias (janela de atribuição padrão por clique); Google ≤ 90 dias.
3. `ja_era_cliente = true` → só `purchase`.
4. `qualified` não elegível quando `handoff.motivo` começa com `bot de recuperação` (reativação da
   base), `IA temporariamente indisponível` (fallback de LLM fora do ar — 510 repasses no total, 20
   com clique em 30 dias) ou `ESCALONAMENTO` (reclamação). Com clique, sobram ~280 repasses em 30
   dias (~65/semana).
5. Varredura olha só eventos dos últimos 90 dias (Google) / 7 dias (Meta).

Dados de 08/10/2026: 31 das 40 vendas com clique fecharam até 7 dias depois da entrada.

## 6. Modelo de dados

```sql
create table ad_conversions (
  id              uuid primary key default gen_random_uuid(),
  lead_id         uuid not null references leads(id) on delete cascade,
  platform        text not null check (platform in ('meta','google')),
  stage           text not null check (stage in ('lead','qualified','opportunity','purchase')),
  sale_id         uuid null references sales(id) on delete set null,
  click_id        text not null,          -- ctwa_clid | gclid | gbraid | wbraid
  click_id_type   text not null,          -- 'ctwa_clid' | 'gclid' | 'gbraid' | 'wbraid'
  click_at        timestamptz not null,
  campaign_name   text null,              -- campanha_nome da entrada, senão utm_campaign (para a aba)
  dedupe_key      text not null unique,   -- '{platform}:{stage}:{click_id}' | '{platform}:purchase:{sale_id}'
  event_at        timestamptz not null,
  event_id        text not null,          -- determinístico; vira event_id (Meta) / transactionId (Google)
  segment         text not null,          -- 'atacado' | 'private_label' | 'geral'
  value           numeric null,
  currency        text not null default 'BRL',
  status          text not null default 'pendente'
                  check (status in ('pendente','enviado','erro','fora_da_janela','ignorado')),
  attempts        int not null default 0,
  next_attempt_at timestamptz not null default now(),
  claimed_at      timestamptz null,
  last_error      text null,
  last_response   jsonb null,
  sent_at         timestamptz null,
  created_at      timestamptz not null default now()
);
-- dedup por dedupe_key (coluna UNIQUE simples: o upsert do PostgREST não mira índice parcial)
create index ad_conversions_due_idx on ad_conversions (next_attempt_at) where status = 'pendente';

create table ad_conversion_values (
  segment     text not null,
  stage       text not null check (stage in ('lead','qualified','opportunity')),
  value       numeric not null,
  updated_at  timestamptz not null default now(),
  updated_by  text not null,
  primary key (segment, stage)
);
```

- `event_id` = `{stage}:{lead_id}:{sha256(click_id)[:12]}` para funil, `purchase:{sale_id}` para venda.
- **Leads:** colunas novas `gbraid`, `wbraid` + `TRACKING_COLUMNS`, `lp_webhook` e o trigger de
  `entrada` passam a considerá-las.
- **Aposentado:** `conversion_events` (vazia) fica no banco sem uso — o script de mesclagem a referencia;
  `pipeline_stages.conversion_event/value` ficam no banco sem uso (sem DROP de coluna).
- Migrations seguem o padrão do repo: aplicadas à mão, idempotentes, `begin … commit`.

## 7. Componentes

Tudo em `backend/app/conversions/` (pacote novo; `campaigns/` já está grande):

| Arquivo | Responsabilidade |
|---|---|
| `eligibility.py` | Funções puras: clique atribuído, janelas, regras de §5, segmento. |
| `sweep.py` | Varredura: lê fontes dos últimos 90 dias (paginado — teto de 1000 do PostgREST), monta candidatos, `insert … on conflict do nothing`. Lê `ad_conversion_values` direto (uma query por rodada) e copia o valor na inserção; sem linha para a célula, o valor fica `null` (envia sem valor). |
| `meta.py` | Monta e envia o evento Business Messaging (reaproveita os hashes do `capi_dispatcher`). |
| `google.py` | Monta e envia o evento Data Manager; access token pelo mesmo OAuth do `google_ads.py`. |
| `sender.py` | Claim atômico das pendentes (`claimed_at`, como follow-ups), checa janela de novo antes de enviar, classifica erro, agenda retentativa. |
| `router.py` | `GET /api/conversions/ads` (lista + contadores, filtros) para a aba. **Só admin**: exige o JWT de admin no backend (`exigir_admin` de `traffic_router`); a proxy do Next o repassa pelo `adminProxy`. |

**Worker:** duas entradas em `TASK_SPECS`: `conversions-sweep` (periódica, 1800 s) e
`conversions-send` (periódica, 300 s, até 100 pendentes por tick). 30 min de latência é irrelevante
numa janela de 7 dias, e a varredura relê ~3 mil leads de 90 dias — não precisa rodar a cada 5 min.
Dados pessoais (e-mail, telefone) **não** vão para a fila: o sender lê o lead e aplica o hash na hora.

**Normalização para hash:** Meta → telefone só dígitos com DDI (`5534...`); Google → E.164 com `+`
(`+5534...`) e e-mail Gmail sem pontos antes do `@`. Venda com `status='cancelada'` na hora do envio
→ `ignorado`.

**Retentativa:** 1 min, 5 min, 30 min, 2 h, 12 h; na 6ª falha → `erro`. Erro permanente (4xx de
validação) → `erro` direto. Token/permissão (401/403, códigos OAuth da Meta), limite, 5xx, rede e
variável de ambiente faltando **não** são permanentes (backoff). Evento que saiu da janela antes do
envio → `fora_da_janela`. Venda cancelada ou apagada (`sale_id` nulo) antes do envio → `ignorado`.
Plataforma desligada → nada sai da fila (fica `pendente`). Plataforma ligada mas sem configuração
(credenciais ausentes; na Meta, também modo teste sem `META_CAPI_TEST_EVENT_CODE`, que mandaria
evento real) → pulada inteira pelo sender, sem reivindicar linha, com aviso no log a cada tick.

**Removido:** `campaigns/conversions.py`, `conversion_log.py`, `google_export.py`, a parte de envio
de `capi_dispatcher.py`, as chamadas em `automation/triggers.py:96-115`, `automation/engine.py:672-679`
e `leads/router.py:160-191` (`/won` mantém o resto, perde o disparo), o botão de CSV
(`conversions-section.tsx`) e o campo de evento no `pipeline-edit-modal.tsx`.
`conversion_analytics.py` passa a ler `ad_conversions`.

## 8. Valores estimados

Script `backend/scripts/conversoes/calcular_valores.py` (só leitura, imprime proposta):

> valor(segmento, etapa) = receita das vendas em até 30 dias dos leads com clique que atingiram a
> etapa ÷ número desses leads — janela de 180 dias.

O script propõe só **`lead` e `qualified`**. `lead` usa só leads com clique **Google** (só o Google
recebe `lead`), na hora do 1º clique Google; `qualified` usa repasses válidos com clique de qualquer
plataforma. O valor de **`opportunity` é definido à mão** (`insert … on conflict` em
`ad_conversion_values`, ver `docs/setup/conversoes-ads.md`).

Mostra, por segmento, a receita separada em kit e não-kit, o N de cada célula e marca células com
N < 20 (o Rafael decide se usa `geral` no lugar). Grava em `ad_conversion_values` só com `--aplicar`
depois da aprovação. Recálculo é manual — cada mudança de valor reinicia o aprendizado.

Segmento = `leads.stage` no momento da varredura: `atacado`, `private_label`; o resto vira `geral`.

## 9. Aba "Conversões enviadas" (/trafego)

- **Acesso:** só admin — o endpoint exige o JWT de admin no backend (não só na proxy), porque o
  backend é público e a lista expõe nome de lead e valor de venda.
- **Contadores:** etapa × plataforma × status no período do filtro do /trafego, calculados sobre
  **todas** as linhas do filtro (select leve paginado), não sobre a lista. A lista para em 1000
  linhas (teto do PostgREST) e devolve `truncated`.
- **Lista:** data do evento, lead (link para a conversa), etapa, plataforma, campanha (`meta_ad_id` →
  `meta_ad_campaigns`; Google pela `campanha_nome` da entrada; sem ela, o `utm_campaign` cru da
  entrada), valor, status, erro traduzido (o conserto de token depende da plataforma).
- **Filtros:** etapa, plataforma, status.
- Frontend em `src/components/trafego/conversoes-enviadas.tsx` + proxy `src/app/api/traffic/conversoes`.

## 10. Configuração

| Variável | Uso |
|---|---|
| `CONVERSIONS_META_ENABLED`, `CONVERSIONS_GOOGLE_ENABLED` | Liga o envio por plataforma (default `false`). |
| `CONVERSIONS_TEST_MODE` | Meta com `test_event_code`; Google com `validateOnly: true`. |
| `META_CAPI_DATASET_ID`, `META_CAPI_ACCESS_TOKEN`, `META_CAPI_TEST_EVENT_CODE` | Meta. `META_WABA_ID` já existe. |
| `GOOGLE_ADS_CONVERSION_ACTION_{LEAD,QUALIFIED,OPPORTUNITY,PURCHASE}` | IDs das 4 ações. |
| `GOOGLE_ADS_REFRESH_TOKEN` | Regerado com os escopos `adwords` + `datamanager`. |

Roteiro passo a passo em `docs/setup/conversoes-ads.md`:
- **Meta:** token de system user com `whatsapp_business_manage_events`; o dataset é criado por
  script (`scripts/conversoes/criar_dataset_meta.py`).
- **Google:** criar 4 ações "Importar de cliques"; regerar o refresh token; recomendação à Tati de
  deixar a conversão importada de **qualificado como primária** e "Conversa iniciada" como
  secundária (hoje ela soma com o formulário e conta a mesma pessoa duas vezes).

## 11. Rollout

1. Migrations à mão + deploy com as duas plataformas desligadas. A varredura enche a fila
   (inclusive os 90 dias); conferência no banco do que **seria** enviado.
2. `calcular_valores.py` → aprovação do Rafael → `--aplicar`. Linhas já na fila recebem o valor
   (update único das `pendente`).
3. `CONVERSIONS_TEST_MODE=true`: Meta aparece na aba Test Events; Google valida sem registrar.
4. Liga o Google (ganha o histórico de 90 dias na hora), depois a Meta.

## 12. Verificações pendentes (antes do passo 3)

- Se a meta "Maximizar o número de leads por mensagens" aparece para a conta e passa a otimizar nos
  `LeadSubmitted` do repasse (precisa de ≥10 eventos de lead ou compra em 30 dias). `QualifiedLead`
  não é usado. Se a meta não aparecer, a Meta recebe os eventos para medição e otimiza por Purchase
  quando houver volume.
- Se a conta Google exige algum aceite/termo para a Data Manager API.

## 13. Testes

- Unitários (puros): elegibilidade (clique atribuído, janelas, já era cliente, fluxo de
  Recuperação), montagem dos payloads Meta e Google (hash, fuso `-03:00`, nomes, valor), `event_id`,
  classificação de erro e backoff.
- Varredura: **com Supabase mockado** (query builder falso — não há banco de teste): upsert com
  `ignore_duplicates` na `dedupe_key` (rodar 2× não duplica — a garantia é a UNIQUE do banco),
  paginação, blocos de 200 ids, lead com dado ruim não derruba a rodada, hora da venda do mesmo dia;
  venda cancelada não entra.
- Sender com HTTP e Supabase mockados: retentativa, erro permanente, `fora_da_janela`, plataforma
  desligada ou sem configuração, venda cancelada/apagada, modo teste.
- Router com Supabase mockado: contadores com mais de 1000 linhas, 401/403 sem admin.
- Rodar no container da imagem `canastra-api` (venv local quebrado).

## 14. Fora de escopo

- Retração/cancelamento nas plataformas (venda cancelada depois de enviada fica só na aba).
- Lead sem ID de clique casado só por telefone (exige a tag do Google na LP — outro repo).
- Tráfego de site da Meta (`fbclid`): 0 leads em 30 dias.
- Recálculo automático de valores.

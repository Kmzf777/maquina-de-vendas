# Avaliação: o banco está 100% em sincronia com as duas contas Bling?

Data: 13/10/2026 (consultas rodadas às 01:00 UTC de 14/10). Código: `origin/master` @ `8fd32fc0`.
Escopo: só avaliação. Nada foi corrigido, nenhuma escrita em produção e nenhuma chamada à API do Bling.

Contas: `default` = Bling Café Canastra (1) e `secundaria` = Bling Café Rural (2) (`backend/app/bling/config.py:27-30`).

---

## 1. Resumo executivo

**Não está em sincronia.** Nenhuma das duas contas está. Os pedidos novos chegam bem pelo webhook, mas faltam pedidos em quatro pontos: um buraco do backfill, falhas definitivas do webhook, o histórico da conta 2 e o estado dos pedidos depois que entram.

| | `default` (Café Canastra) | `secundaria` (Café Rural) |
|---|---|---|
| Pedidos no banco | 1.047 (27/08/2025 → 12/10/2026) | 77 (09/09/2026 → 13/10/2026) |
| **Pedidos que faltam (pela numeração)** | **115**, sendo 114 entre 23/07 e 19/08/2026 (buraco do backfill) e 1 depois que o webhook entrou | **15**, sendo 14 entre 09/09 e 16/09 (estreia da conta) e 1 em 30/09 |
| Histórico anterior | 12 meses importados | **nenhum**: os pedidos nº 1 a 3.644 nunca foram importados (decisão 4 da spec) |
| Pedido com webhook que falhou e nunca entrou | 2 (mais 1 com evento `done` que também não está em `sales`) | 1 |
| Pedido **Cancelado** no Bling contado como venda | **54 (R$ 58.708)** | **3 (R$ 1.134)** |
| Situação congelada ("Em aberto"/"Em andamento" com mais de 30 dias) | 37 | 0 |
| Frete gravado | 0 em 100% dos pedidos | 0 em 100% dos pedidos |
| Vendedor (`sold_by`) | nulo em 100% | nulo em 84% (só as 12 vendas criadas pelo CRM têm) |
| Itens | 100% com `sale_items` | 100% com `sale_items` |
| Último pedido / último webhook | 12/10 / 13/10 19:49 UTC | 13/10 / 13/10 19:33 UTC |

Leitura do buraco da conta 1: o pedido nº 5874 é de 22/07 e o próximo no banco é o nº 5951, de 09/08. Os números são contíguos de abril a julho, com no máximo 1 falta por mês, então a numeração serve como prova. Pelo ticket médio de julho (R$ 1.535), os 114 pedidos ausentes valem por volta de **R$ 175 mil**. É uma estimativa, porque o valor real só sai do Bling.

O que **não** é problema de sincronia: a conta 1 caiu de ~25 para ~6 pedidos por semana a partir de setembro, enquanto a conta 2 passou a ter ~15 a 20. Depois de 20/08 a numeração da conta 1 tem só um buraco (nº 6008). A queda é operação migrando para o Café Rural, não perda de dados.

---

## 2. Como funciona hoje, por conta

O código trata as duas contas da mesma forma. Elas só diferem em configuração e no backfill.

| Peça | Como é | Por conta? |
|---|---|---|
| Credenciais | `BLING_CLIENT_ID/SECRET` globais, com override `BLING_SECUNDARIA_*` (`config.py:118-133`). Tokens em `bling_credentials` (Postgres) com cache no Redis. | Sim |
| Refresh do token | `auth.get_access_token` (`auth.py:297`) renova sob demanda, com lock Redis por conta (`auth.py:53,265`). Refresh token vale 30 dias (`auth.py:192`). Como o sync diário chama a API todo dia, a renovação acontece todo dia. Não há alerta de falha. | Sim |
| Rate limit | Token bucket Redis 3 req/s + 110 mil/dia **por conta**, fail-closed (`ratelimit.py`, `config.py:33-38`). O cliente faz retry de 429/5xx com backoff 1/2/4 s e de 401 com uma renovação. | Sim |
| Webhook | `POST /webhook/bling` (legado → `default`) e `POST /webhook/bling/{conta}` (`webhook_router.py:123-139`). HMAC com o secret da conta, grava em `bling_webhook_events` (PK `account,event_id`) e responde 200. | Sim |
| Eventos tratados | Só `order.*` e `product.*` (`webhook_processor.py:162-168`). `invoice.*` chega da conta 2 e é descartado como `skipped` (284 eventos). `stock`/`virtual_stock` não são assinados nem tratados. | — |
| Processamento | Tick por evento com varredura de fallback a cada 60 s (`worker/main.py:107`). Faz `GET /pedidos/vendas/{id}`, `ensure_lead` e `upsert_from_bling`. Até 6 tentativas **sem backoff** e depois `failed` para sempre (`webhook_processor.py:36,170-180`). | Conta lida da linha |
| Ordem dos eventos | Descarta evento com `event_date` anterior a `sales.bling_event_date` (`webhook_processor.py:104-108`). | Sim |
| Sync diário | Tick a cada 86.400 s, ancorado no start do worker (`worker/main.py:103`). Por conta, em sequência: produtos (incremental por `dataAlteracaoInicial`), contatos (incremental), formas de pagamento, vendedores e situações (`sync.py:245-280`). **Não sincroniza pedidos.** | Sim, com isolamento de falha |
| Backfill de pedidos | `backfill.run` em janelas de 30 dias por **data do pedido**, retomável por cursor em `bling_sync_state(resource='backfill')` (`backfill.py:78-116`). O endpoint `POST /api/bling/backfill` só aceita `months`, sem conta, então roda só na `default` (`router.py:665-668`). | Só `default` |
| Idempotência | `sales` UNIQUE `(bling_account, bling_order_id)` e upsert (`orders.py:631-649`). Itens apagados e regravados quando o detalhe traz `itens`. Espelhos com PK `(account, id)`. | Sim |
| Outbox de criação | `bling_jobs` para `create_order` com chave de idempotência (`jobs.py`). Hoje está vazia. | Sim |

`bling_sync_state` em produção: as 5 linhas de cada conta foram atualizadas em 13/10 às 22:02 UTC, então o sync diário e os tokens das duas contas estão funcionando. A linha `backfill/default` tem `last_cursor = 2026-07-22`, gravada em 21/08 às 15:43, e não existe linha `backfill/secundaria`.

---

## 3. Lacunas que quebram o "100% em sincronia"

### G1. O backfill da conta 1 parou no meio da última janela
- `backfill.py:112` só grava o cursor ao **fim** de cada janela. O cursor ficou em `2026-07-22`, ou seja, a janela 23/07–21/08 nunca terminou. Os pedidos dela que existem no banco vieram pelo webhook a partir de 20/08 ou por `order.updated` posteriores.
- Nada avisa que o backfill não terminou e nada o retoma sozinho.
- Efeito: 114 pedidos ausentes (nº 5875–5950 e trechos de 5952–5999).
- Rodar o mesmo endpoint de novo retomaria de 23/07 (`backfill.py:89-90`), porque o filtro é `j[0] > cursor`.

### G2. Pedido de cliente novo falha em definitivo
- O webhook busca o contato no espelho `bling_contacts` (`webhook_processor.py:118-124`). Esse espelho só é atualizado **uma vez por dia** (não existe webhook de contato).
- Contato criado no mesmo dia → `lead_id=None` → `upsert_from_bling` grava `sales.lead_id` nulo (`orders.py:682`) → `23502 not-null`. As 6 tentativas se esgotam em minutos (`webhook_processor.py:36`), bem antes do próximo sync de contatos, e o evento vira `failed`.
- Nenhum processo reprocessa eventos `failed`.
- Em produção: 31 eventos `failed`, todos com esse erro (21 na `default` e 10 na `secundaria`). Envolvem 19 pedidos. Dezesseis entraram depois, por um `order.updated` posterior que pegou o contato já sincronizado. **Três não entraram** (2 na `default` e 1 na `secundaria`), além de mais 1 pedido da `default` com evento e sem linha em `sales`.
- O último caso é de 10/10, então o problema continua acontecendo.

### G3. Não existe varredura periódica de pedidos
- Depois do backfill, a única porta de entrada é o webhook. Webhook perdido (fora do ar mais de 3 dias, configuração desabilitada pelo Bling, deploy, assinatura inválida) ou falho (G2) não é recuperado.
- O sync diário (`sync.py:245`) não lista `/pedidos/vendas`.
- Também não há reconciliação de contagem nem de soma por dia contra o Bling.

### G4. A situação do pedido não vira status, e o cancelamento não é espelhado
- `status` só vira `cancelada` por `order.deleted` (`webhook_processor.py:110`, `orders.py:724`). A situação "Cancelado" só atualiza `bling_situacao_id`/`nome` (`orders.py:690-694`).
- Em produção, nenhuma venda Bling tem `status='cancelada'`, e 57 pedidos "Cancelado" (R$ 59.842) contam como venda. É o bug B10 do card de dados.
- O status também nunca volta a `registrada` (`orders.py:690-691`).

### G5. A situação congela nos pedidos do backfill que não recebem webhook
- O pedido importado em 21/08 com "Em andamento"/"Em aberto" só muda se chegar um `order.updated` depois. Há 37 pedidos da conta 1 nessas situações com mais de 30 dias.
- A varredura por `dataAlteracao` resolveria isso.

### G6. A conta 2 não tem histórico
- É a decisão 4 da spec `2026-09-13-bling-segunda-conta-design.md:27`. O backfill aceita conta (`backfill.py:78-79`), mas o endpoint não a expõe (`router.py:666`).
- A conta 2 já existia: o primeiro pedido no banco é o nº 3645. Recompra, RFM e coortes do Café Rural começam em 09/09/2026.
- Também faltam 14 pedidos da semana de estreia (nº 3646–3661), anteriores ao webhook da conta 2, cujo primeiro evento é de 16/09.

### G7. Campos que o import não grava
- **Frete:** `upsert_from_bling` não lê `transporte.frete` (`orders.py:679-697`). Resultado: 1.124 pedidos com `freight=0`.
- **Vendedor:** não lê `vendedor.id` (B1). Resultado: `sold_by` nulo em todas as vendas `origin='bling'`.
- **Vendedor do contato:** `bling_contacts.vendedor_id` (`sync.py:106`) está **vazio nas 6.689 linhas das duas contas**. A listagem `/contatos` não traz o vendedor, então o fallback "vendedor do contato" da regra D8 não funciona sem buscar o detalhe.
- **Desconto, outras despesas e taxas no nível do pedido:** não são gravados. `value` = `total` do Bling, com frete e desconto já aplicados.
- **NF-e:** os eventos `invoice.*` da conta 2 são descartados, e a conta 1 nem os assina.

### G8. Estoque é uma foto possivelmente velha
- `saldo_virtual` vem da listagem de produtos (`products.py:38`), filtrada por `dataAlteracaoInicial` (`products.py:85`). Webhooks `stock`/`virtual_stock` não são tratados.
- Não verificado: se uma movimentação de estoque altera a `dataAlteracao` do produto. Se não alterar, o saldo só se renova quando alguém edita o produto ou num sync `full`.

### G9. Robustez e observabilidade
- **Webhook sem backoff:** as 6 tentativas acontecem em sequência, a cada tick (`webhook_processor.py:170-180`), e o claim só pega `pending` (`webhook_processor.py:45-49`).
- **Sync em sequência:** uma exceção em `sync_products` aborta contatos, vendedores e situações daquela conta no dia (`sync.py:250-255`).
- **Sem visibilidade:** não há tabela ou view de saúde da sincronia nem alerta. Falha de refresh de token, evento `failed`, backfill parado e webhook silencioso só aparecem no log.
- **Agente de consulta:** o `consulta_ro` não enxerga nenhuma view no schema `analytics` relacionada a isso.

### G10. Pedido apagado
- Só é tratado se chegar `order.deleted`. A `default` nunca recebeu um. Sem varredura, um pedido apagado no Bling fica `registrada` para sempre.

---

## 4. Evidência (produção, só agregados)

Pedidos Bling por mês (`sales` com `bling_order_id`):

| Conta | Mês | Pedidos | Soma R$ | Frete R$ | Sem vendedor | Sem itens | `cancelada` |
|---|---|---|---|---|---|---|---|
| default | 2026-04 | 99 | 117.840 | 0 | 100% | 0 | 0 |
| default | 2026-05 | 109 | 127.954 | 0 | 100% | 0 | 0 |
| default | 2026-06 | 111 | 130.730 | 0 | 100% | 0 | 0 |
| default | 2026-07 | 86 | 132.022 | 0 | 100% | 0 | 0 |
| default | **2026-08** | **18** | 24.494 | 0 | 100% | 0 | 0 |
| default | 2026-09 | 25 | 7.935 | 0 | 100% | 0 | 0 |
| default | 2026-10 | 9 | 3.053 | 0 | 100% | 0 | 0 |
| secundaria | 2026-09 | 50 | 60.140 | 0 | 90% | 0 | 0 |
| secundaria | 2026-10 | 27 | 34.075 | 0 | 74% | 0 | 0 |

De 08/2025 a 03/2026 a conta 1 teve entre 39 e 128 pedidos por mês, sempre com frete 0 e sem vendedor.

Buracos na numeração (≥ 1 número faltando, a partir de jul/2026):

| Conta | Depois do nº (data) | Próximo nº (data) | Faltam |
|---|---|---|---|
| default | 5874 (22/07) | 5951 (09/08) | 76 |
| default | 5951 → 5960 → 5971 → 5987 (09/08 a 01/09) | | 8 + 10 + 15 |
| default | 5987–6001 (18/08 a 20/08) | | 1 + 1 + 2 + 1 |
| default | 6007 (27/08) | 6009 (01/09) | 1 |
| secundaria | 3645 (09/09) | 3662 (16/09) | 6 + 2 + 6 |
| secundaria | 3707 (30/09) | 3709 (30/09) | 1 |

Ressalva: um número pode faltar porque o pedido foi apagado no Bling antes de chegar ao banco. Para confirmar, é preciso consultar o Bling.

Eventos de webhook (`bling_webhook_events`):

| Conta | Evento | done | failed | skipped | Desde | Último |
|---|---|---|---|---|---|---|
| default | order.created | 30 | 10 | 1 | 20/08 | 13/10 |
| default | order.updated | 96 | 11 | 0 | 20/08 | 13/10 |
| default | product.* | 92 | 0 | 0 | 20/08 | 13/10 |
| secundaria | order.created | 62 | 8 | 0 | 16/09 | 13/10 |
| secundaria | order.updated | 140 | 2 | 0 | 16/09 | 13/10 |
| secundaria | product.* | 12 | 0 | 0 | 22/09 | 08/10 |
| secundaria | invoice.* | 0 | 0 | 284 | 16/09 | 13/10 |

Os 31 `failed` têm todos o mesmo erro: `null value in column "lead_id"`. Toda venda criada depois de 22/08 tem pelo menos um evento: 37 na `default` e 77 na `secundaria`. Pedidos com evento: 62 na `default` (59 em `sales`) e 78 na `secundaria` (77 em `sales`).

Situação × status:

| Conta | Situação Bling | Status CRM | Pedidos | R$ |
|---|---|---|---|---|
| default | Atendido | registrada | 955 | 1.069.232 |
| default | **Cancelado** | **registrada** | **54** | **58.708** |
| default | Em andamento | registrada | 24 (23 > 30 dias) | 3.270 |
| default | Em aberto | registrada | 13 (13 > 30 dias) | 14.059 |
| default | Em digitação | registrada | 1 | 1.211 |
| secundaria | Atendido | registrada | 68 | 72.345 |
| secundaria | Em aberto | registrada | 6 | 20.736 |
| secundaria | **Cancelado** | **registrada** | **3** | **1.134** |

Espelhos:

| Espelho | default | secundaria |
|---|---|---|
| `bling_products` (ativos) | 537 (445) | 460 (442) |
| `bling_contacts` (com `vendedor_id`) | 2.867 (0) | 3.822 (0) |
| `bling_sellers` / `bling_seller_map` | 16 / 1 | 13 / 1 |
| `bling_situacoes` | 9 | 7 |
| `lead_bling_contacts` | 1.482 | 78 |
| `bling_jobs` | 0 | 0 |

Não foi possível verificar, porque exigiria a API do Bling (proibida nesta avaliação):
- o total real de pedidos por dia e por conta;
- se os números ausentes são pedidos apagados;
- o tamanho do histórico da conta 2 nos últimos 12 meses;
- se a movimentação de estoque altera a `dataAlteracao` do produto;
- o `refresh_expires_at` de cada conta (`bling_credentials` não é legível pelo `consulta_ro`).

---

## 5. Opções

Base de custo (por conta, 3 req/s). A listagem `/pedidos/vendas` devolve até 100 pedidos por chamada. O detalhe custa 1 chamada por pedido. A conta 1 tem ~30 pedidos por semana hoje, e a conta 2 tem ~20.

### Opção A. Fechar os buracos uma vez (backfill por conta), sem mudança estrutural
- **O que é:**
  - rodar de novo o backfill da `default`, que retoma de 23/07;
  - expor `account` no `/backfill` e rodar 12 (ou 24) meses da `secundaria`;
  - reprocessar os 4 pedidos `failed`/ausentes.
- **Esforço:** pequeno (~0,5 dia, mais aprovação do dono).
- **Custo de API:** ~2 chamadas por pedido. São ~230 chamadas na conta 1 e no máximo ~7 mil na conta 2, ou seja, menos de 40 min a 3 req/s.
- **Risco:** baixo, porque é idempotente por `(bling_account, bling_order_id)`. Cria leads para clientes antigos da conta 2 (`ensure_lead`), o que incha "leads" (bug B8). Rodar fora do horário comercial.
- **Corrige:** G1 e G6. **Não corrige:** G2–G5 e G7–G10. Os buracos voltam na próxima falha.

### Opção B. Endurecer o webhook
- **O que é:**
  - quando o contato faltar no espelho, buscar `GET /contatos/{id}` na hora e gravar no espelho;
  - backoff exponencial por evento (`next_attempt_at`);
  - job que reabre `failed` com mais de 1 h;
  - mapear situação → status via `bling_situacoes` por conta (cancelado e devolvido → `cancelada`, com reversão);
  - gravar frete e vendedor.
- **Esforço:** médio (~2 dias com TDD).
- **Risco:** baixo. É +1 chamada só para contato novo.
- **Corrige:** G2, G4 e G7 (na entrada), e parte de G9. **Não corrige:** webhook que nunca chega (G3), G5 nem G10.

### Opção C. Varredura incremental por `dataAlteracao` (por conta)
- **O que é:**
  - novo recurso `orders` em `bling_sync_state`;
  - a cada 1–3 h, listar `/pedidos/vendas` com `dataAlteracaoInicial = last_sync_at − margem` (o mesmo `to_bling_datetime` dos produtos);
  - comparar situação e total de cada pedido listado com `sales`;
  - buscar o detalhe só do que for novo ou divergente.
- **Esforço:** médio (~1,5 dia).
- **Custo de API:** baixo. São 1–2 chamadas de listagem por rodada mais os detalhes das mudanças, algo como ~100–300 chamadas por dia por conta.
- **Risco:** confirmar no portão da spec que o filtro de alteração existe no endpoint de pedidos da API v3. Ele existe em produtos e contatos, e para pedidos é preciso conferir na documentação, sem chamar a API. Se não existir, varrer por `dataInicial` dos últimos 60–90 dias.
- **Corrige:** G3, G5 e G10 (pedido que some da listagem → marcar), e recupera G2 sozinho.

### Opção D. Reconciliação diária com prova e alerta (por conta e por dia)
- **O que é:**
  - todo dia de madrugada, para cada conta e cada dia dos últimos N dias (ex.: 35), listar os pedidos do Bling e comparar com `sales`: contagem, soma do total e conjunto de ids;
  - gravar o resultado numa tabela `bling_reconciliacao (account, dia, bling_qtd, bling_soma, db_qtd, db_soma, faltando[], sobrando[], status, checado_em)`;
  - dia divergente → reimportar só os ids faltantes ou divergentes e checar de novo;
  - se continuar divergente, avisar (Discord ou watchdog);
  - view `analytics.vw_saude_bling` com `GRANT SELECT` ao `consulta_ro`, para o agente de consulta dizer "dados da conta X conferidos até D-1".
- **Esforço:** médio (~2 dias), sobre a C.
- **Custo de API:** 35 dias × ~5 pedidos por dia = 2 listagens por conta por noite, mais a reimportação.
- **Risco:** baixo. A janela longa pega edição retroativa. O alerta precisa de canal definido.
- **Corrige e prova:** é a única opção que transforma "achamos que está sincronizado" em "conferido até ontem, por conta". Cobre também o que as outras deixarem passar.

Coordenação comum a B, C e D:
- usar sempre `BlingClient(account=...)`, que já passa pelo rate limit e pelo lock de refresh por conta;
- nunca rodar duas varreduras da mesma conta em paralelo (lock Redis `bling:sweep:{conta}`);
- nunca chamar `/oauth/token` fora de `auth.get_access_token`;
- a margem de 8% do teto diário já existe.

---

## 6. Recomendação: B + C + D, em fases, depois de A

1. **Fase 0 (já):** opção A. Rodar de novo o backfill da `default` para fechar 23/07–21/08. Decidir com o dono se a `secundaria` ganha histórico. A recomendação é sim, 24 meses, porque recompra, RFM e coortes do Café Rural dependem disso. Reprocessar os pedidos `failed`. Conferir pela numeração que os buracos fecharam.
2. **Fase 1:** opção B, que estanca a perda nova. Busca de contato sob demanda, backoff e reabertura de `failed`, situação → status (é o B10), frete e vendedor (é o B1). Junto vem o backfill aprovado de frete, vendedor e cancelados.
3. **Fase 2:** opção C, que pega o webhook perdido e a situação congelada.
4. **Fase 3:** opção D, que prova e alerta, com a view no `analytics` para o agente de consulta.

Por que nessa ordem: A recupera ~R$ 175 mil de vendas ausentes com quase nenhum código. B fecha a única perda que ainda acontece toda semana. C e D só fazem sentido com B, senão a reconciliação reimporta e falha no mesmo `lead_id` nulo.

---

## 7. Rascunho de card para o agente CRM

> **CRM Canastra: sincronia completa e comprovada das duas contas Bling**
>
> **Contexto.** Avaliação em `docs/avaliacao/2026-10-13-sync-bling-duas-contas.md`, com o código em `8fd32fc0`. Hoje:
> - a conta `default` tem 114 pedidos ausentes entre 23/07 e 19/08/2026, porque o backfill parou com cursor em `2026-07-22`;
> - a `secundaria` não tem histórico anterior ao nº 3645 e tem 15 números ausentes;
> - 31 eventos de webhook estão `failed` com `lead_id` nulo, porque o contato novo ainda não está no espelho; 4 desses pedidos nunca entraram;
> - 57 pedidos "Cancelado" contam como venda;
> - frete e vendedor nunca são gravados;
> - não existe varredura nem reconciliação de pedidos.
>
> Fluxo obrigatório: spec → aprovação do dono → TDD → produção. Toda escrita em produção precisa de contagem esperada, teto, valor anterior e rollback, e só roda com OK explícito do dono.
>
> **Entregas**
> 1. **Fechar buracos.**
>    - Expor `account` em `POST /api/bling/backfill` (`backend/app/bling/router.py:666`) e no proxy do Next.
>    - Rodar o backfill da `default`, que retoma de 23/07.
>    - Com aprovação, rodar o da `secundaria` (decidir 12 ou 24 meses).
>    - Script para reprocessar os eventos `failed`.
>    - Aceite: sem buracos de numeração a partir de 23/07 na `default`, nem a partir do início escolhido na `secundaria`, exceto pedidos apagados confirmados no Bling.
> 2. **Webhook robusto.**
>    - Em `webhook_processor.py:118-124`, quando o contato faltar no espelho, buscar `GET /contatos/{id}` e gravar no espelho antes do `ensure_lead`.
>    - Backoff exponencial por evento.
>    - Reabrir `failed` periodicamente.
>    - Aceite: zero `failed` por `lead_id` nulo em 7 dias.
> 3. **Situação → status** (B10). Mapear as situações de cancelamento e devolução por conta (`bling_situacoes`) para `cancelada`, com reversão, em `orders.py:689-691`. Também gravar `freight` (`transporte.frete`) e o vendedor (B1).
> 4. **Varredura incremental de pedidos por conta.**
>    - Recurso `orders` em `bling_sync_state`, com `dataAlteracaoInicial` (confirmar o filtro na documentação da API v3) e margem de `to_bling_datetime`.
>    - A cada 1–3 h, upsert do que mudou.
>    - Lock por conta e sempre pelo `BlingClient`. Nunca chamar `/oauth/token` direto.
> 5. **Reconciliação diária.**
>    - Tabela `bling_reconciliacao` por conta e dia (contagem, soma, ids faltando e sobrando, status).
>    - Reimportar o que divergir.
>    - Alerta quando continuar divergente.
>    - View `analytics.vw_saude_bling` com `GRANT SELECT` ao `consulta_ro`.
>    - Aceite: 35 dias × 2 contas com `status='ok'`.
>
> **Riscos.**
> - 3 req/s por conta: rodar backfill e varredura fora do horário comercial e nunca em paralelo na mesma conta.
> - Não quebrar o `on_conflict (bling_account, bling_order_id)`.
> - O backfill da conta 2 cria leads de clientes antigos. Coordenar com o B8 (marcar `origem_cadastro='bling_import'`) para não inflar KPIs de marketing.
> - Não remover a rota legada `/webhook/bling`.

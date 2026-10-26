# CRM Canastra: vendas e receita corretas (vendedor, frete, cancelados do Bling, painel de vendas)

Cartão 1e6381fe, desmembrado do 7b143561 (itens B1 restante, B10 e B12). Branch `agente/1e6381fe`, base `origin/master` 870da9ab.

## 1. Problema

Nas palavras do cartão: "vendas e receita corretas". Hoje o CRM soma como receita:
- **47 pedidos que estão cancelados no Bling** (R$ 54.740, conta 1, de 29/08/2025 a 20/07/2026). Eles seguem `status='registrada'`, porque foram importados antes de a situação virar status e nunca foram relidos;
- o **frete** dentro do valor da venda;
- vendas canceladas em vários relatórios, que não filtram status.

Além disso, **995 pedidos antigos da conta 1** (27/08/2025 a 13/10/2026) não têm frete, desconto nem vendedor, e o `/painel-vendas` soma só as **primeiras 1.000 vendas** do período (o PostgREST corta em `PGRST_DB_MAX_ROWS=1000`).

Números de produção em 26/10/2026 (consulta só leitura):

| Conta | Pedidos | Desde | Frete = 0 | Desconto nulo (nunca relidos) | Sem `vendedor_fonte` |
|---|---|---|---|---|---|
| default (Café Canastra) | 1.175 | 27/08/2025 | 1.134 | 995 | 1.108 |
| secundaria (Café Rural) | 186 | 20/08/2026 | 116 | 0 | 63 |

## 2. Decisões

Definições D7 a D10 do cartão (13/10) valem como estão. Decidido com o Rafael neste cartão:

1. **Situações do Bling (gate 0.1 do runbook), 26/10.** Confirmada a lista das duas contas, que vêm de `bling_situacoes`:
   - `Cancelado` (ids 12 e 34, nas duas contas) → `cancelada`;
   - `Em devolução` (id 729685, só na conta 1) → continua venda, com `devolucao_parcial=true` (a revisar);
   - `Em aberto`, `Em andamento`, `Atendido`, `Verificado`, `Em digitação`, `Venda Agenciada` e `Pagamento aprovado` → venda.

   Não há "Devolvido" em nenhuma das contas. A regra de `classificar_situacao` (`backend/app/bling/orders.py`) já faz exatamente isso: o código não muda.
2. **Histórico: reler no Bling, 26/10.** Os pedidos antigos da conta 1 são relidos pelo backfill do runbook (opção A). A alternativa de só fazer UPDATE no banco foi descartada. Antes da releitura, guardamos uma cópia dos valores atuais para poder voltar atrás.
3. **"Frete zero" × "frete desconhecido".** Não entra coluna nova: o código novo sempre grava `discount`, então `origin='bling' and discount is null` = pedido nunca relido (hoje são exatamente os 995). Depois do backfill o esperado é 0. O que sobrar é listado ao dono.
4. **Funil do dashboard.** "Ganho" continua sendo oportunidade (deal) marcada como ganha (D7). Só ganha um texto de ajuda explicando a diferença para vendas.

## 3. O que muda

### 3.1 Dados em produção (cada passo só com OK explícito do dono)

**P0. Cópia de segurança `backup_1e63_vendas`** (SQL à mão, antes do P2):
```sql
begin;
create table public.backup_1e63_vendas as
select id, status, bling_situacao_id, bling_situacao_nome, value, freight, freight_mode,
       discount, sold_by, vendedor_fonte, devolucao_parcial, sold_at, now() as copiado_em
  from public.sales where bling_account = 'default' and bling_order_id is not null;
do $$ declare n int; begin
  select count(*) into n from public.backup_1e63_vendas;
  if n < 1100 or n > 1300 then raise exception 'backup_1e63_vendas: % linhas, esperado ~1.175', n; end if;
end $$;
revoke all on public.backup_1e63_vendas from anon, authenticated;
commit;
```
Rollback do P2 (volta só as colunas que o backfill mexe, e só nas vendas que mudaram):
```sql
update public.sales s set status=b.status, bling_situacao_id=b.bling_situacao_id,
  bling_situacao_nome=b.bling_situacao_nome, value=b.value, freight=b.freight,
  freight_mode=b.freight_mode, discount=b.discount, sold_by=b.sold_by,
  vendedor_fonte=b.vendedor_fonte, devolucao_parcial=b.devolucao_parcial, sold_at=b.sold_at
  from public.backup_1e63_vendas b
 where b.id = s.id
   and (s.status, s.value, s.freight, s.discount, s.sold_by, s.vendedor_fonte, s.sold_at)
       is distinct from (b.status, b.value, b.freight, b.discount, b.sold_by, b.vendedor_fonte, b.sold_at);
```
A tabela fica até o aceite. Depois, apagá-la é decisão do dono.

**P1. Vendedor do contato (condicional).** Testar com **1 chamada** `GET /contatos/{id}` na conta 1, num contato cujo pedido tem vendedor, se o detalhe traz `vendedor.id` (a listagem não traz: `sync.py` lê só a listagem, e `vendedor_id` está nulo em 6.695 de 6.695).
- **Se trouxer:** comando novo `python -m app.bling.ops contatos-vendedor --conta X [--estimar]`. Ele lê o detalhe de cada contato sem `vendedor_id`, grava só `bling_contacts.vendedor_id`, usa a mesma trava e o mesmo limitador do Bling, retoma por cursor (`bling_sync_state`, resource `contacts_vendedor`) e é idempotente. Custo: ~1 chamada por contato, ~6.700 no total (≈ 6% da cota diária de uma conta, ~40 min a 3 req/s), à noite. A sincronia periódica de contatos passa a **não apagar** um `vendedor_id` já preenchido quando a listagem vier sem ele. Roda **antes** do P2, para que a cascata D8 já use o degrau 2.
- **Se não trouxer:** nada é gravado. O degrau 2 da D8 fica registrado como "indisponível na API" e sai da conta.

**P2. Backfill da conta 1** (runbook, passo A com `--reiniciar`), fora do horário comercial:
```bash
sg docker -c "$OPS backfill --conta default --desde 2025-08-01 --ate 2026-10-13 --reiniciar --estimar"
sg docker -c "$OPS backfill --conta default --desde 2025-08-01 --ate 2026-10-13 --reiniciar" | tee ~/bling_1e63_backfill.log
```
O cursor não recua (sem `--recuar-cursor`). Custo esperado: ~15 listagens, ~1.000 detalhes e de 0 a algumas dezenas de contatos, ~1.100 chamadas (~1% da cota) em ~7 min. É upsert por `(bling_account, bling_order_id)`. Não cria venda nova para pedido que já existe, não abre card de Reposição e não sobrescreve `sold_by` preenchido nem venda `crm`/`manual`.

Esperado depois:
- os 47 `Cancelado` viram `cancelada` (consulta F do runbook: nenhuma linha `Cancelado` com `registrada`);
- `discount is null` na conta 1 cai de 995 para perto de 0;
- `freight > 0` aparece nas vendas antigas;
- `vendedor_fonte` é preenchido onde houver vendedor no pedido.

Teto: se mais de 80 vendas mudarem para `cancelada`, pare e leve ao dono antes de seguir. Conferência: `select count(*) from sales s join backup_1e63_vendas b using(id) where s.status='cancelada' and b.status<>'cancelada'`.

Efeito colateral conhecido: o trigger `fn_lead_events_sales_venda` grava o evento `venda_cancelada` na timeline dos leads dos 47 e atualiza `occurred_at` quando o `sold_at` muda (3.2). Antes do P2, conferir que nenhuma automação ativa dispara em `venda_cancelada`. Se alguma disparar, parar e levar ao dono.

**P3. Lista ao dono:** vendas não canceladas sem `sold_by` depois do P2, por conta e por motivo (sem vendedor no pedido, vendedor do Bling sem linha em `bling_seller_map`, mais de 60 dias). Vem com os ids de vendedor do Bling sem mapa e a quantidade de vendas de cada. Mapear vendedor é do cartão "leads e vendedor": aqui só entregamos a lista.

### 3.2 Backend (`backend/`)

| Onde | Mudança |
|---|---|
| `bling/orders.py` `_sold_at_iso` e `create_order` | `sold_at` passa a ser **meio-dia em Brasília** (`T12:00:00-03:00`), e não meio-dia UTC. A data do pedido não muda. |
| `bling/reconciliacao.py` | Dias em America/Sao_Paulo (hoje são em UTC). Passa a comparar também a **situação**: pedido cujo `situacao.id` da listagem difere de `sales.bling_situacao_id` entra como divergente e é reimportado, o que faz o cancelamento chegar em até 1 dia mesmo sem webhook. O resto da lógica não muda. |
| `bling/sync.py` + `bling/ops.py` | Só se o P1 der certo: o comando `contatos-vendedor` e a sincronia que não apaga `vendedor_id`. |
| `campaigns/traffic_report.py` | Receita = `value − freight` em `_sales_by_lead`, no resumo, no ROAS e no detalhe da campanha. No modo lead, só conta a venda dentro da janela da D10 (entrada → +30 dias B2C, +90 dias B2B; B2B pela D9, mesma regra de `fn_lead_b2b`). O frete do período sai à parte no resumo (`frete`). |
| `automation/engine.py`, `automation/test_runner.py`, `automation/variables.py` | `sale_count`, `total_spend`, `last_sale_value`, `repurchase_days`, `{{valor_ultima_venda}}` e `{{dias_sem_compra}}` ignoram vendas canceladas, e os valores saem sem frete. Consequência: uma automação com condição de "total gasto" pode disparar para menos leads. |
| `leads/service.py` (cliente consolidado, ~l.269; "CLIENTE ATIVO", ~l.2178) | Venda cancelada não faz do lead um cliente. O valor mostrado sai sem frete. |
| `conversions/sweep.py` | `ad_conversions.value = value − freight`, só para conversões **novas**. As já enviadas às plataformas não são reenviadas. |
| `follow_up/service.py` (~l.1144) | Conferir se a regra de compra filtra cancelada, como a de ~l.1524. Se não filtrar, aplicar `_venda_cancelada`. |

### 3.3 Frontend (`frontend/`)

| Onde | Mudança |
|---|---|
| `app/api/sales/metrics/route.ts` + `components/sales/sales-metrics-cards.tsx` (`/painel-vendas`) | Ignora canceladas. "Faturamento do período" vira **"Receita (sem frete)"** = `Σ(value − freight)`, com um card **"Frete"** à parte. "Vendas" e "Ticket médio" contam só as válidas, e o ticket sai sem frete. Limites do período em Brasília (00:00 a 23:59:59.999 −03:00), não em UTC. Filtro de vendedor sem diferenciar maiúscula (`ilike`). Soma **todas** as linhas, paginando de 1.000 em 1.000. A lista `app/api/sales/route.ts` passa a usar os mesmos limites em Brasília. |
| `lib/lead-overview.ts` (`computeVitals`, funil "comprou", timeline) e `app/api/leads/[id]/overview/route.ts` | Receita e pedidos do lead sem canceladas e sem frete. A venda cancelada continua na timeline, marcada como cancelada. |
| `app/api/search/route.ts` + `search_sales` | O resultado mostra o valor sem frete e marca a venda cancelada. A data da busca vai para Brasília, se hoje estiver em UTC. |
| `components/dashboard/conversion-funnel.tsx` | Texto de ajuda no "Ganho": "oportunidades marcadas como ganhas no funil. Vendas do Bling sem oportunidade não entram aqui; veja a receita no Painel de vendas." |

### 3.4 Banco (migrations à mão, `supabase/migrations/20261026*_1e63_*.sql`)

Todas são `CREATE OR REPLACE`, sem tabela nem coluna nova (fora a cópia do P0). Cada arquivo traz no topo o SQL de rollback, que é a definição anterior copiada da migration de origem.

| Objeto | Mudança | Definição atual |
|---|---|---|
| `get_avg_repurchase_cycle_days` | Só vendas não canceladas. Intervalo em dias de calendário de Brasília, ignorando intervalos de 0 dia. | `20260824_repurchase_por_vendedor.sql` |
| `get_leads_for_repurchase` | Só vendas não canceladas no `EXISTS` e no `MAX(sold_at)`. | `20260904_esteiras_vendedor.sql` |
| `get_leads_no_sale_in_stage` | Venda cancelada não conta como venda. | `20260904_esteiras_vendedor.sql` |
| `search_sales` | Devolve `status` e `freight`. As colunas atuais continuam (a assinatura muda; se o retorno for `TABLE`, `DROP` + `CREATE` na mesma transação e `GRANT` refeito, conferido objeto a objeto). | `20260818_universal_search.sql` |
| `analytics.fct_vendas` | Ver 3.5. | `central-claude/sql/analytics/001_analytics.sql:467` |

### 3.5 `analytics.fct_vendas` (agente de consulta)

`CREATE OR REPLACE VIEW` com as **mesmas colunas, na mesma ordem**, em `supabase/migrations/20261026c_1e63_fct_vendas.sql`. Ele não precisa de GRANT novo, porque não lê tabela nova.
- `cancelada` = `status = 'cancelada'`. Sai o contorno por nome de situação: "Em devolução" deixa de ser cancelada (D7).
- `vendedor` vem de `sold_by` → `dim_vendedor`. `vendedor_fonte` = o `sales.vendedor_fonte` gravado (`bling_pedido`, `bling_contato`, `lead_assigned`), ou `crm` quando a venda é `crm`/`manual` com `sold_by`, ou `sem`. Sai a derivação paralela pelo contato e pelo responsável do lead sem limite de 60 dias.
- `alerta_frete` só quando `origin='bling' and discount is null` (pedido nunca relido).
- `alerta_vendedor`: sai o texto "o import do Bling não grava o vendedor do pedido". Venda sem vendedor passa a dizer "pedido sem vendedor no Bling e sem fonte na cascata D8".
- O comentário da view é atualizado.

Não edito o central-claude. A fonte em `001_analytics.sql` fica desatualizada até alguém copiar a nova definição. Isso vai no entregável 3.6.

### 3.6 Entregável: glossário

`docs/superpowers/specs/2026-10-26-glossario-consulta-vendas.md`, no formato do `2026-10-22-glossario-consulta.md`. Traz o novo sentido de `cancelada`, `vendedor_fonte` e `alerta_frete`, o "Receita (sem frete)" do painel e a nova definição da view para copiar no `001_analytics.sql` do central-claude.

## 4. Como testar em modo teste

Tudo no worktree `agente/1e6381fe`, antes de qualquer push. Testes primeiro (TDD).

1. **pytest (`backend/`):**
   - `_sold_at_iso` gera 12:00 −03:00;
   - reconciliação: dia em BRT e pedido com situação diferente vira divergente e é reimportado (cliente Bling falso);
   - `_sales_by_lead` com frete, venda cancelada e venda fora da janela de 30/90 dias;
   - ROAS sem frete;
   - condições da automação e variáveis com venda cancelada e frete;
   - `build_candidates` com valor sem frete;
   - cliente consolidado com só venda cancelada;
   - se o P1 der certo: `contatos-vendedor` com retomada e sincronia que não apaga `vendedor_id`.

   Suíte inteira verde.
2. **vitest (`frontend/`):**
   - `route.test.ts` da rota de métricas: cancelada fora, frete à parte, venda às 23:30 BRT do dia 31 dentro do mês e 00:30 BRT do dia 1 fora, `sold_by` com caixa diferente, mais de 1.000 linhas somadas;
   - `lead-overview` sem cancelada e sem frete;
   - card do painel com "Receita (sem frete)" e "Frete".

   `npm run test`, `npm run lint` e `npm run build` verdes.
3. **SQL num Postgres descartável** (`crm-scratch-pg-1e6381fe` na VPS, com o schema de produção, no padrão do `test_analytics_b67f_pg.py`): `backend/tests/test_vendas_d7_1e63_pg.py` cobre o ciclo de recompra (cancelada fora, intervalo de 0 dia fora), `get_leads_for_repurchase`, `get_leads_no_sale_in_stage`, `search_sales` e `fct_vendas`. Cada cenário roda em transação com ROLLBACK. O container é apagado ao fim.
4. **Contra produção, só leitura:** rodar a nova definição de `fct_vendas` como `SELECT` (sem criar) e a soma D7 do mês, para comparar com o que a rota nova calcularia.
5. **Prints:** em modo teste não há CRM rodando com este código. O print do `/painel-vendas` (cards "Receita (sem frete)" e "Frete") e o do `/trafego` saem em produção, depois da publicação.

## 5. Como publicar (só depois do [Liberar produção])

1. **Pré-checagem:** `docker service ls`, `docker service logs --since 1h canastra_worker`, `pm2 ls`. Se `origin/master` andou, `git pull origin master` no branch e testes de novo.
2. **Merge e push:** merge de `agente/1e6381fe` em `master` e `git push origin agente/1e6381fe:master`, sem force. O GitHub Actions faz o deploy de `crm_crm`, `canastra_api` e `canastra_worker`. Acompanhar até estabilizar. O código novo funciona com as funções SQL antigas, e vice-versa.
3. **Migrations à mão** pelo `psql` do `supabase_db`, uma por vez, com `SET LOCAL lock_timeout='5s'`. Depois, recarregar o PostgREST com SIGUSR1 (o NOTIFY é ignorado nesta VPS) e conferir objeto a objeto (`pg_get_functiondef`, `pg_get_viewdef`, grants).
4. **Dados, à noite, cada um com o seu OK:**
   - P0 (cópia);
   - teste de 1 contato e, se for o caso, P1;
   - P2 (backfill), com a conferência do teto;
   - P3 (lista ao dono).
5. **Voltar atrás:**
   - código: `git revert` do merge e push, que redeploya a versão anterior;
   - SQL: o rollback no topo de cada migration;
   - dados: o UPDATE do P0;
   - P1: `update bling_contacts set vendedor_id = null` só nas linhas gravadas pelo comando (ele registra os ids no log/JSON).

## 6. Como testar em produção

Só leitura e dado real já existente. **Nenhuma ação com efeito externo:** nada de venda, pedido ou NF no Bling, nem mensagem a cliente. As chamadas ao Bling são só `GET`.
- As três consultas de conferência do cartão:
  - nenhuma situação de cancelamento com `registrada`;
  - vendas sem `sold_by` por `origin`/`vendedor_fonte`;
  - soma D7 do mês igual no `/painel-vendas`, no `/trafego` e no `fct_vendas`.
- Prints do `/painel-vendas` (mês atual e um mês com cancelados, ex. 07/2026) e do `/trafego`.
- Uma rodada manual de `reconciliar --conta default` (idempotente) mostrando o dia em BRT e nenhum divergente por situação.
- Efeito real e esperado daqui para frente: as conversões **novas** enviadas ao Meta/Google saem sem frete.

## 7. Fora do escopo

- Cadastro de vendedores, `bling_seller_map` e `deals.assigned_to` (cartão "leads e vendedor").
- Repasse, SLA e closer (cartão 7b143561).
- CMV.
- Backfill de 24 meses e releitura da conta 2 (já relida pelo código novo).
- Reenviar ou corrigir conversões já enviadas às plataformas.
- As 4 vendas com valor 0.
- Editar o central-claude.

## 8. Riscos

- Não quebrar o `on_conflict (bling_account, bling_order_id)` nem regredir `origin`: os testes do upsert existentes continuam verdes.
- Automação ligada a `venda_cancelada` ou a "total gasto": conferir antes do P2 (3.1).
- O `/painel-vendas` vai mudar os números de hoje: menores sem cancelados e sem frete, maiores em períodos com mais de 1.000 vendas. É o efeito desejado, mas avisar o time.

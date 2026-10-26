# Vendas e receita pela D7: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer toda tela e relatório do CRM contar receita pela D7 (`value − freight`, sem canceladas, dia em Brasília), deixar a reconciliação do Bling pegar mudança de situação e preparar os scripts da releitura do histórico.

**Architecture:** Um helper de receita por lado (`backend/app/utils/receita_venda.py` e `frontend/src/lib/sales/receita.ts`), usado por todos os consumidores. Funções SQL e a view `analytics.fct_vendas` mudam por `CREATE OR REPLACE` em migrations aplicadas à mão. Os passos de dados (P0, P2, P3) ficam como scripts SQL/comandos documentados e rodam só na publicação.

**Tech Stack:** FastAPI + supabase-py (pytest), Next.js App Router (vitest), Postgres 15 (Supabase self-hosted), testes SQL num Postgres descartável na VPS.

Spec: `docs/superpowers/specs/2026-10-26-vendas-receita-d7-design.md`.

## Resultado do P1 (feito em 26/10, só leitura)

`GET /contatos/{id}` na conta 1, em 2 contatos cujos pedidos têm o João como vendedor, devolve `vendedor: {"id": 0}`. O detalhe tem o campo, mas o vendedor não está preenchido no contato no Bling. Conforme a spec, o degrau 2 da D8 fica "indisponível na API": **não** se cria o comando `contatos-vendedor`, nem se mexe em `sync.py`. Isso é registrado no glossário (Tarefa 7) e no runbook.

## Helpers compartilhados (Tarefa 0, feita antes das demais)

- `backend/app/utils/receita_venda.py`:
  - `venda_cancelada(sale) -> bool`: `status` em minúsculas e sem espaços começa com `"cancel"`;
  - `receita_da_venda(sale) -> float`: `0.0` se cancelada, senão `value − (freight or 0)`, com Decimal arredondado a 2 casas e devolvido como float;
  - `frete_da_venda(sale) -> float`: `0.0` se cancelada, senão `freight or 0`.
- `frontend/src/lib/sales/receita.ts`:
  - `vendaCancelada(sale)`, `receitaDaVenda(sale)` e `freteDaVenda(sale)`, com o mesmo contrato do backend;
  - `limitesDoDiaBRT(from, to)`: devolve `{ gte, lte }` em ISO com offset `-03:00` (`AAAA-MM-DDT00:00:00.000-03:00` e `AAAA-MM-DDT23:59:59.999-03:00`) e deixa passar valor que não tenha 10 caracteres.
- Testes: `backend/tests/test_receita_venda.py` e `frontend/src/lib/sales/receita.test.ts`.

## Tarefas (1 a 6 independentes entre si, em arquivos separados; podem rodar em paralelo)

### Tarefa 1: Bling, `sold_at` em Brasília e reconciliação por situação

**Files:**
- Modify: `backend/app/bling/orders.py` (`_sold_at_iso` ~l.626 e `create_order` ~l.488)
- Modify: `backend/app/bling/reconciliacao.py` (`_vendas_do_banco`, `_por_dia_bling`, `_por_dia_banco`, `_comparar`, `_diverge`, `_reconciliar`)
- Test: `backend/tests/test_bling_1e63_reconciliacao.py` (novo). Ajustar os testes que esperam `T12:00:00+00:00`.

Comportamento:
1. `sold_at` de pedido Bling = `f"{data}T12:00:00-03:00"`, nos dois lugares. O docstring de `_vendas_do_banco` passa a dizer meio-dia de Brasília. As vendas antigas (12:00Z = 09:00 BRT) caem no mesmo dia em BRT.
2. `_vendas_do_banco`:
   - limites `inicio T00:00:00-03:00` ≤ sold_at < `(fim+1) T00:00:00-03:00`;
   - passa a selecionar também `bling_situacao_id`.
3. `_por_dia_banco`: dia = `datetime.fromisoformat(sold_at).astimezone(ZoneInfo("America/Sao_Paulo")).date().isoformat()` (`_TZ` já existe no módulo). Não usar o `[:10]` da string UTC.
4. Situação:
   - `_por_dia_bling` guarda, além do total, `situacao.id` de cada pedido da listagem;
   - `_comparar` ganha a chave `situacao_diferente` (ids presentes nos dois lados, com `situacao.id` do Bling ≠ `bling_situacao_id` do banco, ignorando quando um dos lados é nulo);
   - `_diverge` considera essa chave, e os pedidos dela entram no `alvo` da reimportação.

   Mantenha as estruturas atuais se possível, por exemplo com um dict paralelo de situação por dia, para não quebrar `test_bling_sync_fase3.py`.

Testes (pytest, com duble do cliente Bling e do supabase no padrão de `tests/test_bling_sync_fase3.py`):
- `_sold_at_iso({"data": "2026-10-13"}, None) == "2026-10-13T12:00:00-03:00"`;
- `_por_dia_banco` põe `"2026-10-14T01:30:00+00:00"` no dia `2026-10-13` e `"2026-10-13T12:00:00+00:00"` no dia `2026-10-13`;
- um pedido com o mesmo valor, mas `situacao.id=12` no Bling e `bling_situacao_id=9` no banco, vira divergente e é passado a `pedido_import.importar_pedido`;
- situação igual e valor igual → `ok` e nenhuma reimportação;
- `_vendas_do_banco` monta os limites com `-03:00`.

Rodar: `cd backend && python -m pytest -q tests/test_bling_1e63_reconciliacao.py tests/test_bling_sync_fase3.py tests/test_bling_orders.py tests/test_bling_backfill.py`.

Commit: `fix(bling): sold_at ao meio-dia de Brasilia e reconciliacao compara situacao (1e6381fe)`.

### Tarefa 2: `/trafego`, receita sem frete e janela D10

**Files:**
- Modify: `backend/app/campaigns/traffic_report.py` (receita ~l.306, ROAS ~l.331/350/357/431/446, `_sales_by_lead` ~l.687, `campaign_detail` ~l.923, resumo)
- Modify: `frontend/src/components/trafego/campaign-kpis.tsx` (+ tipo do resumo, se houver) para mostrar "Frete" ao lado de "Receita"
- Test: `backend/tests/test_traffic_report_1e63.py` (novo) e ajuste dos testes existentes que somam `value`

Comportamento:
1. Toda soma de receita usa `receita_da_venda(s)`. A cancelada continua fora (`_cancelada`, que pode delegar a `venda_cancelada`).
2. O resumo ganha `frete` (soma de `frete_da_venda` das mesmas vendas que entram na receita). `ticket_medio` e ROAS usam a receita sem frete.
3. Modo lead (`_sales_by_lead`): só conta a venda com `sold_at` (dia BRT) entre o dia de entrada do lead e entrada + 30 dias (B2C) ou + 90 dias (B2B). B2B pela D9:
   - usar a RPC/consulta já existente se `traffic_report.py` tiver o segmento ou o pipeline do lead;
   - senão, `leads.segmento in ('atacado','private_label')` OU o deal no pipeline de atacado/private label OU CNPJ (14 dígitos) no documento do contato Bling do lead;
   - procure `fn_lead_b2b` em `supabase/migrations/` e replique a mesma regra em Python, com comentário apontando para ela.

   A data de entrada é a que o relatório já usa para pôr o lead na janela.
4. No frontend, o KPI "Receita" fica com a legenda "sem frete" e entra o KPI "Frete".

Testes:
- `_sales_by_lead` com uma venda de valor 500 e frete 50 → 450;
- venda cancelada → fora;
- B2C com venda 31 dias após a entrada → fora, com 30 dias → dentro;
- B2B com 89 dias → dentro;
- ROAS = receita sem frete / investimento;
- resumo com `frete`.

Rodar: `cd backend && python -m pytest -q tests/test_traffic_report*.py` e `cd frontend && npx vitest run src/components/trafego`.

Commit: `fix(trafego): receita sem frete, frete a parte e janela D10 no modo lead (1e6381fe)`.

### Tarefa 3: automação, cliente consolidado, follow-up e conversões

**Files:**
- Modify: `backend/app/automation/engine.py` (~l.521-571), `backend/app/automation/test_runner.py` (~l.344-367), `backend/app/automation/variables.py` (~l.35)
- Modify: `backend/app/leads/service.py` (~l.269 cliente consolidado; ~l.2178 "CLIENTE ATIVO")
- Modify: `backend/app/follow_up/service.py` (~l.1144: conferir e, se faltar, aplicar `_venda_cancelada`)
- Modify: `backend/app/conversions/sweep.py` (~l.165)
- Test: `backend/tests/test_receita_consumidores_1e63.py` (novo) e ajustes nos testes existentes

Comportamento:
- `sale_count`, `total_spend`, `last_sale_value` e `repurchase_days` (engine e test_runner), e `{{valor_ultima_venda}}`/`{{dias_sem_compra}}`:
  - só vendas não canceladas;
  - valores por `receita_da_venda`;
  - "última venda" = a última não cancelada.
- Cliente consolidado: só existe se houver venda não cancelada. "CLIENTE ATIVO" usa a última venda não cancelada e mostra o valor sem frete.
- `build_candidates`: `value = receita_da_venda(s)`. Só muda conversão nova.

Testes:
- lead com vendas [500 com frete 50 registrada; 300 cancelada] → `sale_count=1`, `total_spend=450`, `last_sale_value=450`;
- `valor_ultima_venda` ignora a cancelada mais recente;
- lead com só venda cancelada não é cliente consolidado;
- candidato de conversão com value 200 e frete 20 → 180.

Rodar: `cd backend && python -m pytest -q tests/test_automation_engine*.py tests/test_conversions_*.py tests/test_receita_consumidores_1e63.py` e a suíte toda ao fim.

Commit: `fix(vendas): automacao, cliente e conversoes ignoram cancelada e frete (1e6381fe)`.

### Tarefa 4: `/painel-vendas`

**Files:**
- Modify: `frontend/src/app/api/sales/metrics/route.ts`
- Modify: `frontend/src/app/api/sales/route.ts` (só os limites de data → `limitesDoDiaBRT`)
- Modify: `frontend/src/components/sales/sales-metrics-cards.tsx` e o tipo em `frontend/src/app/(authenticated)/painel-vendas/page.tsx`
- Test: `frontend/src/app/api/sales/metrics/route.test.ts` (novo; mockar `getServiceSupabase`, `resolverEscopoDeVendas` e `vendedorDaRecompra` com `vi.mock`, no padrão de outro `route.test.ts` do repo)

Comportamento da rota:
- `select("value, freight, status")`, com limites por `limitesDoDiaBRT`;
- `sold_by` com `.ilike("sold_by", soldBy)`, escapando `%` e `_`;
- `.neq("status", "cancelada")`, sem esquecer que `status` nulo deve contar: use `.or("status.is.null,status.neq.cancelada")` combinado ao escopo (o escopo já usa `.or`; dois `.or` no PostgREST viram AND, confira no teste);
- pagina com `.range(i, i+999)` e `.order("id")` até vir página com menos de 1.000;
- resposta: `{ total_value, freight_value, count, avg_value, avg_repurchase_cycle_days }`. `total_value` = Σ `receitaDaVenda`, `freight_value` = Σ `freteDaVenda` e `avg_value` = `total_value/count`.

Cards: "Receita (sem frete)" (`total_value`), "Frete" (`freight_value`), "Vendas", "Ticket médio" e o ciclo de recompra como já está.

Testes da rota:
- cancelada fora;
- frete à parte;
- `from=2026-10-01` gera `gte` com `2026-10-01T00:00:00.000-03:00`;
- `sold_by` usa `ilike`;
- 1.500 linhas em duas páginas somadas;
- ticket sem frete.

Rodar: `cd frontend && npx vitest run src/app/api/sales src/components/sales src/lib/sales`.

Commit: `fix(painel-vendas): receita sem frete e sem canceladas, frete a parte, dia em Brasilia e sem corte de 1000 (1e6381fe)`.

### Tarefa 5: ficha do lead, busca e funil

**Files:**
- Modify: `frontend/src/lib/lead-overview.ts` (`computeVitals` ~l.312, funil "comprou" ~l.399, timeline ~l.476)
- Modify: `frontend/src/app/api/leads/[id]/overview/route.ts` (selecionar `freight`, `status`)
- Modify: `frontend/src/app/api/search/route.ts` (+ o componente que mostra o resultado de venda): valor sem frete e selo "cancelada" quando `status = 'cancelada'`. Sem `status`/`freight` no retorno (função SQL antiga), cai no comportamento atual. Datas: se `startOfDayIso`/`endOfDayIso` forem UTC, trocar por `limitesDoDiaBRT`.
- Modify: `frontend/src/components/dashboard/conversion-funnel.tsx`: texto de ajuda no "Ganho" (texto exato da spec 3.3), no mesmo padrão de tooltip/`title` já usado no dashboard.
- Test: `frontend/src/lib/lead-overview.test.ts` (casos novos)

Testes:
- vitals com [500/frete 50 registrada, 300 cancelada] → receita 450 e pedidos 1;
- "comprou" falso se só há cancelada;
- a timeline mantém a cancelada, marcada.

Rodar: `cd frontend && npx vitest run src/lib src/components/dashboard src/app/api/search`.

Commit: `fix(lead): ficha, busca e funil seguem a D7 (1e6381fe)`.

### Tarefa 6: SQL, funções e `analytics.fct_vendas`

**Files:**
- Create:
  - `supabase/migrations/20261026a_1e63_vendas_d7_funcoes.sql`: `get_avg_repurchase_cycle_days`, `get_leads_for_repurchase`, `get_leads_no_sale_in_stage` e `search_sales`;
  - `supabase/migrations/20261026c_1e63_fct_vendas.sql`;
  - `backend/tests/test_vendas_d7_1e63_pg.py`.
- Base: a definição atual de cada função na migration mais nova (`20260824_repurchase_por_vendedor.sql`, `20260904_esteiras_vendedor.sql`, `20260818_universal_search.sql`), **conferida contra produção** com `pg_get_functiondef` (só leitura, `psql` do `supabase_db`). Produção vence se divergir. A da view vem de `pg_get_viewdef('analytics.fct_vendas')` em produção, conferida com `central-claude/sql/analytics/001_analytics.sql:467` (só ler o central-claude).

Regras:
- Cada arquivo começa com um bloco de comentário "ROLLBACK", que é a definição de produção copiada, e roda em `begin; set local lock_timeout='5s'; ... commit;`.
- `get_avg_repurchase_cycle_days`:
  - só `coalesce(status,'') <> 'cancelada'`;
  - intervalo = diferença de `(sold_at at time zone 'America/Sao_Paulo')::date` entre vendas consecutivas do lead, descartando 0;
  - mesma assinatura e mesmo `lower()` do vendedor.
- `get_leads_for_repurchase` e `get_leads_no_sale_in_stage`: o filtro de não cancelada em todo `EXISTS`/`MAX` sobre `sales`.
- `search_sales`: devolve também `status` e `freight`. Se o retorno for `RETURNS TABLE`, `DROP FUNCTION` + `CREATE` na mesma transação, refazendo os `GRANT EXECUTE` que existem em produção (`\df+`/`information_schema.routine_privileges`).
- `fct_vendas`: mesmas colunas, mesma ordem e mesmos tipos (exigência do `CREATE OR REPLACE VIEW`), conforme a spec 3.5:
  - `cancelada` = `coalesce(status,'')='cancelada'`;
  - vendedor por `sold_by` → `dim_vendedor`;
  - `vendedor_fonte` = `sales.vendedor_fonte` mapeado: `lead_assigned`→`lead_responsavel`; `crm` se `sold_by` e origin em (`crm`,`manual`) sem fonte; `sem` se não houver vendedor;
  - `alerta_frete` só com `origin='bling' and discount is null`;
  - textos novos de `alerta_vendedor`;
  - `COMMENT` atualizado;
  - sai o `LATERAL` do contato e o `vendedor_responsavel` sem limite;
  - `dim_lead` continua no join (b2b, segmento, entrada...).

Testes SQL (Postgres descartável `crm-scratch-pg-1e6381fe` na VPS, no padrão de `backend/tests/test_analytics_b67f_pg.py`; env `E1E63_PSQL`; sem ele, os testes pulam):
- montar o container com `docker run -d --name crm-scratch-pg-1e6381fe postgres:15` (mesma major de produção; confira `select version()`);
- carregar o schema de produção com `pg_dump --schema-only` dos schemas `public`, `analytics` e das dependências (`auth.users` mínimo), como o b67f fez (ver o docstring/README dele);
- aplicar as duas migrations;
- casos (cada um em transação com ROLLBACK, ids com prefixo `1e6381fe-`):
  - recompra: vendas em 01/10 e 01/10 (mesmo dia) e 11/10 + uma cancelada em 05/10 → média 10;
  - repurchase: lead com só cancelada não aparece;
  - no_sale_in_stage: lead com só cancelada aparece;
  - search_sales devolve `status`/`freight`;
  - fct_vendas:
    - "Em devolução" com `status='registrada'` → `cancelada=false`;
    - `vendedor_fonte='bling_pedido'` aparece;
    - `alerta_frete` nulo quando `discount` não é nulo.
- ao fim, `docker rm -f crm-scratch-pg-1e6381fe`, que é só o container descartável criado por esta tarefa.

Leitura contra produção: rodar o `SELECT` da nova view (sem `CREATE`) com `sum(receita)` do mês corrente e comparar com a consulta D7 do cartão. Anotar os dois números no log da tarefa.

Commit: `feat(db): funcoes de venda e fct_vendas pela D7 (migrations a mao) (1e6381fe)`.

### Tarefa 7: scripts de dados e glossário (docs)

**Files:**
- Create: `docs/superpowers/specs/2026-10-26-dados-1e63.sql`, com:
  - P0 (backup com RAISE, da spec 3.1);
  - rollback do P2;
  - conferências antes/depois;
  - teto de 80 cancelamentos;
  - consulta de automações ligadas a `venda_cancelada`;
  - P3 (lista de vendas sem `sold_by` por conta/motivo e ids de vendedor do Bling sem mapa).
- Create: `docs/superpowers/specs/2026-10-26-glossario-consulta-vendas.md`, no formato de `2026-10-22-glossario-consulta.md`:
  - `cancelada`, `vendedor_fonte` (com `bling_pedido`), `alerta_frete`, "Receita (sem frete)", frete à parte;
  - o resultado do P1 (degrau 2 indisponível);
  - a nova definição de `fct_vendas` para copiar no central-claude.
- Modify: `docs/avaliacao/runbook-sync-bling.md`: nota curta no fim com o resultado do P1 e a releitura de 26/10 (`--reiniciar` da conta 1).

Commit: `docs: scripts de dados P0-P3 e glossario de vendas (1e6381fe)`.

## Verificação final

1. `cd backend && python -m pytest -q`: suíte inteira verde (anotar a contagem).
2. `cd frontend && npm run test && npm run lint && npm run build`: verdes.
3. Testes SQL com `E1E63_PSQL` verdes.
4. Revisão de código do diff inteiro (superpowers:requesting-code-review).
5. Prints: em modo teste não há CRM com este código. Rodar o frontend local (`npm run dev`, com o `.env.local` existente, que aponta para o Supabase de produção só para leitura) e tirar o print do `/painel-vendas` com o script de print, se o login de teste funcionar em `localhost`. Se não funcionar, os prints ficam para depois da publicação, como diz a spec.

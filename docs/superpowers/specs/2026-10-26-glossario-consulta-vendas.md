# Glossário do agente de consulta: mudanças do cartão 1e6381fe (vendas e receita)

Entregável da spec `2026-10-26-vendas-receita-d7-design.md` (seção 3.6). Este arquivo lista o que muda em vendas e receita para quem consulta com o papel `consulta_ro`. O glossário do agente de consulta (central-claude) **não** foi editado aqui; copie de lá o que fizer sentido. A seção 6 traz a definição nova completa das duas views, para copiar em `central-claude/sql/analytics/001_analytics.sql`.

Vale a partir da aplicação das migrations `20261026a`, `20261026c` e `20261026d` (à mão; as views como `supabase_admin`) e da releitura da conta 1 (P2, `backfill --reiniciar`). Antes da releitura, os 995 pedidos antigos da conta 1 continuam sem frete, desconto e vendedor gravados, e os 47 pedidos `Cancelado` continuam `registrada`.

## 1. Receita (D7)

- **Receita = `value − freight`**, só de vendas **não canceladas**. Venda cancelada tem receita 0.
- **Dia = dia em Brasília**: `(sold_at at time zone 'America/Sao_Paulo')::date`. Não use `sold_at::date`, que é o dia em UTC.
- **Frete à parte**: o frete não é receita da empresa. Quando for preciso, ele é somado separado (`freight` em `sales`, `frete` na `fct_vendas`).
- `sold_at` de pedido do Bling passou a ser gravado ao **meio-dia de Brasília** (`AAAA-MM-DDT12:00:00-03:00`). As vendas antigas foram gravadas ao meio-dia UTC (09:00 em Brasília) e caem no mesmo dia em Brasília.

No **/painel-vendas**:

| Card | O que é |
|---|---|
| **Receita (sem frete)** | Antes "Faturamento do período". Σ(`value − freight`) das vendas não canceladas do período |
| **Frete** | Card novo. Σ `freight` das mesmas vendas |
| Vendas | Quantidade de vendas não canceladas |
| Ticket médio | Receita (sem frete) ÷ vendas |

O período vai de 00:00 a 23:59:59.999 de Brasília, o filtro de vendedor não diferencia maiúsculas e a soma pega **todas** as vendas do período (antes parava nas primeiras 1.000). O `/trafego` usa a mesma receita, com o frete à parte no resumo. Os mesmos números saem da `fct_vendas` com `sum(receita)` e `sum(frete) filter (where not cancelada)` pelo `venda_data`.

## 2. `public.sales`

| Coluna | O que é |
|---|---|
| `status` | `cancelada` = situação **Cancelado** do Bling. Qualquer outra situação é venda (`registrada`) |
| `bling_situacao_id`, `bling_situacao_nome` | Situação atual do pedido no Bling. Informativas: para saber se cancelou, use `status` |
| `devolucao_parcial` | `true` = devolução a revisar (parcial ou "Em devolução"). A venda continua contando |
| `freight` | Frete do pedido. Não entra na receita |
| `discount` | Desconto do pedido. O import atual **sempre** grava. Nulo em pedido do Bling = pedido nunca relido pelo código novo |
| `vendedor_fonte` | De onde veio `sold_by` (seção 3) |

Situações confirmadas pelo dono em 26/10/2026 (tabela `bling_situacoes`):
- `Cancelado` (ids 12 e 34, nas duas contas) → `cancelada`;
- `Em devolução` (id 729685, só na conta 1) → continua venda, com `devolucao_parcial = true` (a revisar);
- `Em aberto`, `Em andamento`, `Atendido`, `Verificado`, `Em digitação`, `Venda Agenciada` e `Pagamento aprovado` → venda.

Não há "Devolvido" em nenhuma das contas.

## 3. Vendedor da venda (D8) e `vendedor_fonte`

O import do Bling (webhook, varredura, backfill e reconciliação) grava `sold_by` (e-mail) e `vendedor_fonte` pela cascata D8, nesta ordem:

| `sales.vendedor_fonte` | Origem |
|---|---|
| `bling_pedido` | `pedido.vendedor.id` do próprio pedido no Bling, traduzido pelo `bling_seller_map` da conta |
| `bling_contato` | Vendedor do contato no Bling (`bling_contacts.vendedor_id`). **Indisponível hoje** (ver abaixo) |
| `lead_assigned` | Responsável atual do lead (`leads.assigned_to`), só para venda dos últimos 60 dias (`BLING_VENDEDOR_LEAD_DIAS`) |
| NULL | Sem vendedor no pedido, no contato nem no lead dentro da janela. Também as vendas `crm`/`manual`, que gravam só `sold_by` |

Vendedor do Bling sem linha em `bling_seller_map` não resolve o degrau: a venda cai no degrau seguinte.

**Resultado do P1 (26/10/2026, só leitura):** `GET /contatos/{id}` na conta 1, em 2 contatos cujos pedidos têm o João como vendedor, devolveu `vendedor: {"id": 0}`. O detalhe do contato tem o campo, mas o vendedor não está preenchido no Bling. Por isso o **degrau 2 da D8 (`bling_contato`) está indisponível na API**: `bling_contacts.vendedor_id` continua nulo e nenhuma venda sai com essa fonte. Não foi criado comando para preencher o vendedor do contato.

## 4. `analytics.fct_vendas`

As colunas, a ordem e os tipos não mudaram. Muda o sentido de algumas:

| Coluna | Antes | Agora |
|---|---|---|
| `cancelada` | `status = 'cancelada'` **ou** situação do Bling de cancelamento/devolução pelo nome (contorno do B10) | **Só `status = 'cancelada'`**. "Em devolução" **deixa de ser cancelada** e entra na receita (D7) |
| `receita` | `value − freight`, 0 se cancelada | Igual, com o novo `cancelada` |
| `vendedor` | `sold_by`, senão vendedor do contato no Bling, senão responsável atual do lead (sem limite de data) | Só `sold_by` casado com `dim_vendedor` por e-mail. A cascata roda no import, não na view |
| `vendedor_fonte` | `crm`, `bling_contato`, `lead_responsavel` ou `sem`, derivados na view | A fonte gravada na venda: `bling_pedido`, `bling_contato`, `lead_responsavel` (gravado como `lead_assigned`), `crm` (venda com `sold_by` e sem fonte, ou fonte `crm`/`manual`) ou `sem` (sem vendedor, ou `sold_by` sem cadastro) |
| `alerta_frete` | Toda venda Bling com frete 0 | Só pedido **nunca relido**: `origin = 'bling' and discount is null`. Frete 0 com `discount` gravado é frete 0 de verdade |
| `alerta_vendedor` | "vendedor inferido pelo vendedor do contato no Bling", "... pelo responsável atual do lead", "venda sem vendedor: o import do Bling não grava o vendedor do pedido" | Ver a tabela abaixo |

Textos de `alerta_vendedor`:

| Texto | Quando |
|---|---|
| NULL | Vendedor registrado: `bling_pedido` ou `crm` |
| `vendedor pelo responsável do lead (cascata D8, lead_assigned)` | `vendedor_fonte = 'lead_responsavel'` |
| `vendedor pelo vendedor do contato no Bling (cascata D8)` | `vendedor_fonte = 'bling_contato'` (hoje não ocorre) |
| `sold_by sem vendedor cadastrado (vendedores/bling_seller_map)` | Tem `sold_by`, mas o e-mail não está em `dim_vendedor` |
| `pedido sem vendedor no Bling e sem fonte na cascata D8` | Sem `sold_by` |

Texto de `alerta_frete`: `pedido Bling nunca relido (desconto e frete não gravados): a receita pode incluir o frete`. Depois da releitura da conta 1, o esperado é perto de 0 linhas com esse alerta.

## 5. `analytics.vw_vendedores_semana`

As colunas, a ordem e os tipos não mudaram. Muda só `pct_vendas_sem_vendedor_confiavel`:
- **antes:** % das vendas com `vendedor_fonte <> 'crm'`;
- **agora:** % das vendas com `vendedor_fonte` fora de (`crm`, `bling_pedido`). O vendedor do próprio pedido no Bling é registrado, logo **confiável**. `bling_contato`, `lead_responsavel` e `sem` continuam não confiáveis.

Sem esse ajuste, o indicador pioraria só porque a `fct_vendas` nova passa a rotular essas vendas como `bling_pedido`.

## 6. Definições novas para copiar no central-claude

Substituem as de `central-claude/sql/analytics/001_analytics.sql` (a da `fct_vendas` fica perto da linha 467). As duas views são de `supabase_admin`, com `security_invoker = true` e `SELECT` para `consulta_ro`, e o `CREATE OR REPLACE` preserva dono e grant. Fonte: `supabase/migrations/20261026c_1e63_fct_vendas.sql` e `supabase/migrations/20261026d_1e63_vendedores_semana.sql`.

### 6.1 `analytics.fct_vendas`

```sql
CREATE OR REPLACE VIEW analytics.fct_vendas WITH (security_invoker = true) AS
 WITH s AS (
         SELECT s.id,
            s.lead_id,
            s.sold_at,
            s.value,
            s.sold_by,
            s.deal_id,
            s.bling_situacao_nome,
            s.origin,
            s.status,
            s.bling_account,
            s.freight,
            s.discount,
            s.vendedor_fonte AS fonte_gravada,
            -- D7: só o status. "Em devolução" segue venda (devolucao_parcial).
            COALESCE(s.status, ''::text) = 'cancelada'::text AS cancelada,
            (s.sold_at AT TIME ZONE 'America/Sao_Paulo'::text)::date AS venda_data
           FROM public.sales s
        ), v AS (
         SELECT s.*,
            dv.vendedor,
            NULLIF(TRIM(BOTH FROM s.sold_by), ''::text) IS NOT NULL AS tem_sold_by,
            dl.b2b,
            dl.segmento,
            dl.eh_lead_marketing,
            dl.entrada_data,
            dl.plataforma_primeiro_toque,
            dl.campanha_id_primeiro_toque,
            dl.campanha_primeiro_toque
           FROM s
             LEFT JOIN analytics.dim_lead dl ON dl.lead_id = s.lead_id
             -- D8: o vendedor é o sold_by gravado pela cascata no import (ou pelo CRM).
             LEFT JOIN analytics.dim_vendedor dv ON NULLIF(TRIM(BOTH FROM s.sold_by), ''::text) IS NOT NULL
                   AND lower(TRIM(BOTH FROM s.sold_by)) = ANY (dv.emails)
        )
 SELECT id AS venda_id,
    lead_id,
    sold_at AS vendida_em,
    venda_data,
    origin AS origem,
    bling_account AS conta_bling,
    status,
    bling_situacao_nome AS situacao_bling,
    cancelada,
    value AS valor_bruto,
    COALESCE(freight, 0::numeric) AS frete,
        CASE
            WHEN cancelada THEN 0::numeric
            ELSE value - COALESCE(freight, 0::numeric)
        END AS receita,
    vendedor,
        CASE
            WHEN vendedor IS NULL THEN 'sem'::text
            WHEN fonte_gravada = 'lead_assigned'::text THEN 'lead_responsavel'::text
            WHEN fonte_gravada IN ('bling_pedido'::text, 'bling_contato'::text) THEN fonte_gravada
            -- crm/manual gravados, ou sold_by sem fonte (vendas crm/manual): registrado no CRM.
            ELSE 'crm'::text
        END AS vendedor_fonte,
    COALESCE(b2b, false) AS b2b,
    segmento,
    COALESCE(eh_lead_marketing, false) AS eh_lead_marketing,
    plataforma_primeiro_toque,
    campanha_id_primeiro_toque,
    campanha_primeiro_toque,
    COALESCE(entrada_data IS NOT NULL AND venda_data >= entrada_data AND venda_data <= (entrada_data +
        CASE
            WHEN b2b THEN 90
            ELSE 30
        END), false) AS dentro_janela_atribuicao,
        CASE
            WHEN entrada_data IS NOT NULL THEN venda_data - entrada_data
            ELSE NULL::integer
        END AS dias_desde_entrada,
    (EXISTS ( SELECT 1
           FROM public.sale_items i
          WHERE i.sale_id = v.id)) AS tem_itens,
    deal_id IS NOT NULL AS tem_deal,
        CASE
            WHEN NOT cancelada THEN row_number() OVER (PARTITION BY lead_id, cancelada ORDER BY sold_at, id)::integer
            ELSE NULL::integer
        END AS numero_compra,
        CASE
            -- O import novo sempre grava discount: nulo = pedido Bling nunca relido.
            WHEN origin = 'bling'::text AND discount IS NULL THEN 'pedido Bling nunca relido (desconto e frete não gravados): a receita pode incluir o frete'::text
            ELSE NULL::text
        END AS alerta_frete,
        CASE
            WHEN vendedor IS NULL AND tem_sold_by THEN 'sold_by sem vendedor cadastrado (vendedores/bling_seller_map)'::text
            WHEN vendedor IS NULL THEN 'pedido sem vendedor no Bling e sem fonte na cascata D8'::text
            WHEN fonte_gravada = 'lead_assigned'::text THEN 'vendedor pelo responsável do lead (cascata D8, lead_assigned)'::text
            WHEN fonte_gravada = 'bling_contato'::text THEN 'vendedor pelo vendedor do contato no Bling (cascata D8)'::text
            ELSE NULL::text
        END AS alerta_vendedor
   FROM v;

COMMENT ON VIEW analytics.fct_vendas IS 'Uma linha por venda (inclusive canceladas; filtre NOT cancelada). D7: receita = valor - frete, zero se cancelada; cancelada = status cancelada (situação Cancelado do Bling); "Em devolução" continua venda. venda_data = dia em Brasília. D8: vendedor = sold_by casado com dim_vendedor por e-mail; vendedor_fonte = a fonte gravada na venda pela cascata do import: bling_pedido (vendedor do pedido no Bling), bling_contato (vendedor do contato), lead_responsavel (responsável do lead, até 60 dias), crm (registrado no CRM) ou sem. D10: dentro_janela_atribuicao = venda entre a entrada e 30 dias (B2C) ou 90 dias (B2B) depois. Alertas: alerta_frete (pedido Bling nunca relido, sem desconto/frete gravados) e alerta_vendedor (vendedor inferido ou ausente).';
```

### 6.2 `analytics.vw_vendedores_semana`

```sql
CREATE OR REPLACE VIEW analytics.vw_vendedores_semana WITH (security_invoker = true) AS
 WITH rc AS (
         SELECT r.lead_id,
            r.repasse_em,
            r.repasse_data,
            r.vendedor,
            r.vendedor_fonte,
            r.segmento,
            r.b2b,
            r.conversation_id,
            r.primeira_resposta_humana_em,
            r.minutos_corridos,
            r.minutos_uteis,
            r.respondeu,
            r.minutos_uteis_em_aberto,
            r.horario_fonte,
            r.alerta_cobertura,
            date_trunc('week'::text, r.repasse_data::timestamp with time zone)::date AS semana,
            (EXISTS ( SELECT 1
                   FROM analytics.fct_vendas f
                  WHERE f.lead_id = r.lead_id AND NOT f.cancelada AND f.venda_data >= r.repasse_data AND f.venda_data <= (r.repasse_data +
                        CASE
                            WHEN r.b2b THEN 90
                            ELSE 30
                        END))) AS virou_venda
           FROM analytics.vw_resposta_closer r
        ), u AS (
         SELECT rc.semana,
            COALESCE(rc.vendedor, '(sem vendedor)'::text) AS vendedor,
            count(*) AS repasses_recebidos,
            count(*) FILTER (WHERE rc.respondeu) AS respondidos,
            percentile_cont(0.5::double precision) WITHIN GROUP (ORDER BY (rc.minutos_uteis::double precision)) FILTER (WHERE rc.respondeu) AS mediana_minutos_uteis,
            count(*) FILTER (WHERE rc.virou_venda) AS repasses_com_venda,
            0::bigint AS vendas,
            0::numeric AS receita,
            0::bigint AS vendas_sem_vendedor_confiavel
           FROM rc
          GROUP BY rc.semana, (COALESCE(rc.vendedor, '(sem vendedor)'::text))
        UNION ALL
         SELECT date_trunc('week'::text, f.venda_data::timestamp with time zone)::date AS date_trunc,
            COALESCE(f.vendedor, '(sem vendedor)'::text) AS "coalesce",
            0,
            0,
            NULL::double precision AS float8,
            0,
            count(*) AS count,
            sum(f.receita) AS sum,
            -- Confiável = registrado no CRM (crm) ou vendedor do próprio pedido no Bling (bling_pedido).
            count(*) FILTER (WHERE f.vendedor_fonte <> ALL (ARRAY['crm'::text, 'bling_pedido'::text])) AS count
           FROM analytics.fct_vendas f
          WHERE NOT f.cancelada
          GROUP BY (date_trunc('week'::text, f.venda_data::timestamp with time zone)::date), (COALESCE(f.vendedor, '(sem vendedor)'::text))
        )
 SELECT semana,
    vendedor,
    sum(repasses_recebidos)::integer AS repasses_recebidos,
    sum(respondidos)::integer AS respondidos,
    round(max(mediana_minutos_uteis)::numeric, 1) AS mediana_minutos_uteis,
    sum(vendas)::integer AS vendas,
    sum(receita) AS receita,
    round(sum(receita) / NULLIF(sum(vendas), 0::numeric), 2) AS ticket_medio,
    round(100.0 * sum(repasses_com_venda) / NULLIF(sum(repasses_recebidos), 0::numeric), 1) AS conversao_repasse_venda,
    round(100.0 * sum(vendas_sem_vendedor_confiavel) / NULLIF(sum(vendas), 0::numeric), 1) AS pct_vendas_sem_vendedor_confiavel
   FROM u
  GROUP BY semana, vendedor;

COMMENT ON VIEW analytics.vw_vendedores_semana IS 'Semana (segunda-feira, horário de Brasília) x vendedor. Repasses recebidos = primeiros repasses do lead na semana (D3); respondidos e mediana de minutos úteis vêm de vw_resposta_closer (D4); conversao_repasse_venda = % desses repasses que viraram venda não cancelada em até 30 dias (B2C) ou 90 dias (B2B). Vendas, receita sem frete e ticket vêm de fct_vendas pela data da venda e pelo vendedor da cascata D8; pct_vendas_sem_vendedor_confiavel = % das vendas cujo vendedor não é confiável, isto é, cujo vendedor_fonte não é crm (registrado no CRM) nem bling_pedido (vendedor do próprio pedido no Bling): bling_contato, lead_responsavel e sem contam como não confiáveis. "(sem vendedor)" agrupa o que não tem vendedor.';
```

## 7. Consultas-exemplo

```sql
-- Receita D7 e frete do mês (dia em Brasília); deve bater com o /painel-vendas
select sum(receita) receita, sum(frete) filter (where not cancelada) frete,
       count(*) filter (where not cancelada) vendas
  from analytics.fct_vendas
 where venda_data between '2026-10-01' and '2026-10-31';

-- A mesma conta direto em sales
select sum(value - coalesce(freight, 0)) receita, sum(coalesce(freight, 0)) frete, count(*) vendas
  from sales
 where coalesce(status, '') <> 'cancelada'
   and (sold_at at time zone 'America/Sao_Paulo')::date between '2026-10-01' and '2026-10-31';

-- Nenhuma situação de cancelamento ainda como registrada (depois da releitura: 0 linhas)
select bling_account, bling_situacao_nome, status, count(*)
  from sales where bling_situacao_nome ilike '%cancel%' and status <> 'cancelada'
 group by 1, 2, 3;

-- Vendas por fonte do vendedor
select origem, vendedor_fonte, count(*) from analytics.fct_vendas
 where not cancelada group by 1, 2 order by 1, 3 desc;

-- Pedidos Bling nunca relidos (alerta_frete)
select conta_bling, count(*) from analytics.fct_vendas where alerta_frete is not null group by 1;

-- Vendas "Em devolução": contam como venda, a revisar
select venda_id, vendida_em, receita from analytics.fct_vendas where situacao_bling = 'Em devolução';

-- % de vendas sem vendedor confiável por semana e vendedor
select semana, vendedor, vendas, pct_vendas_sem_vendedor_confiavel
  from analytics.vw_vendedores_semana where vendas > 0 order by semana desc, vendas desc;
```

# Glossário do agente de consulta: mudanças do cartão b67f1c6b

Entregável da spec `2026-10-22-crm-leads-vendedor-design.md` (seção 6). Este arquivo lista o que muda no banco para quem consulta com o papel `consulta_ro`. O glossário do agente de consulta (central-claude) **não** foi editado aqui; copie de lá o que fizer sentido.

Vale a partir da aplicação das migrations `20261022a` a `20261022f` e dos backfills F1 a F7. Antes do F2, `leads.segmento` está vazio. Antes do F1, `vendedores` está vazia.

## 1. Tabelas e colunas

### `public.vendedores` (nova)

Cadastro único de vendedores. Cada linha é um usuário do CRM (`auth.users`).

| Coluna | Significado |
|---|---|
| `id` | uuid do usuário (`auth.users.id`). É a chave usada em `deals.assigned_to`, `leads.assigned_to` e `lead_events.metadata.vendedor_id` |
| `email` | e-mail em minúsculas, único. Casa com `sales.sold_by` e `quotes.created_by`, que continuam em e-mail |
| `nome` | nome de exibição ("João Brás") |
| `apelidos` | outros nomes que aparecem no histórico ("Joao Bras") |
| `segmentos` | segmentos que o vendedor atende: `atacado`, `private_label`, `exportacao` |
| `atende_no_crm` | `false` = atende fora do CRM (o Arthur atende pelo fixo). Fica fora do SLA de resposta |
| `ativo` | `false` = só resolve o histórico (Rafael, Comercial 2) |

Vendedores ativos depois do F1: João (atacado e private label) e Arthur (exportação).

### `public.leads`

| Coluna | O que é |
|---|---|
| `segmento` (nova) | O que o lead quer comprar: `atacado`, `private_label`, `consumo`, `exportacao`, ou NULL (= ainda não sabemos). Nenhum outro valor é aceito. "secretaria" deixou de ser segmento |
| `stage` (mudou de sentido) | Agora só guarda a **fase** do lead: `pending` (chegou, ninguém falou ainda), `novo` (criado pelo Bling), `triagem` (a Valeria está descobrindo o que ele quer; antes "secretaria"), `qualificando` (já tem segmento e está em atendimento), `perdido`. Depois da migration f, nenhum outro valor é aceito. Para filtrar por segmento, use `segmento`, e não `stage` |
| `origem_cadastro` (nova) | Como o lead entrou no CRM: `inbound` (escreveu no WhatsApp; padrão), `manual` (criado na tela), `bling_import` (contato importado do Bling), `reativacao_import` (lista da reativação), `csv_import` (importação de planilha). Importados não contam como lead de marketing |

### `public.deals`

- `assigned_to` passou de texto para **uuid** com FK para `vendedores(id)`. Para ver o nome do vendedor, faça join com `vendedores`.

### `public.bling_seller_map`

- `vendedor_id` (nova): o vendedor do CRM ligado a cada vendedor do Bling.

### `public.lead_events`: evento `qualificado` (novo)

- 1 por lead: `dedupe_key = 'qualificado:<lead_id>'`. `occurred_at` é a data em que o lead foi qualificado.
- `metadata.criterio`:
  - `repasse`: foi repassado ao vendedor por um motivo que não é de falha (IA indisponível, bot de recuperação e escalonamento não contam);
  - `score`: é B2B e o score fechou em `final_score >= 5`, sem ser provisório.
- `metadata` também traz `segmento`, `b2b`, `motivo` (do repasse) e `vendedor_id`.
- `source` = o mesmo do repasse, ou `'score'`.
- Interesse "morno" não qualifica.
- Os históricos (até out/2026) foram gravados pelo backfill F7, com a data do 1º repasse ou do `updated_at` do score.

### `public.valeria_score_directory` (view)

- As colunas são as mesmas. Antes mostrava só leads com `stage='atacado'`, inclusive os sem score. Agora mostra **todo lead que tem linha em `lead_qualification_scores`**, em qualquer fase.
- O score só é gravado para lead B2B (veja `fn_lead_b2b`).

## 2. Funções

| Função | O que faz |
|---|---|
| `fn_lead_b2b(p_lead uuid) → boolean` | **D9.** Verdadeiro se o lead tem segmento `atacado` ou `private_label`, OU tem deal num funil cujo nome contém "Atacado" ou "Private Label", OU tem contato Bling com CNPJ (`doc_digits` de 14 dígitos, via `lead_bling_contacts` ou `leads.bling_contact_id`). **Ter score não basta.** |
| `fn_vendedor_id(p text) → uuid` | Resolve um vendedor por uuid, e-mail ou nome/apelido, sem diferenciar acento nem maiúsculas. Também casa pelo 1º nome. Devolve NULL se não casar ou se casar com mais de um ("Vendedor", "Comercial") |
| `fn_lead_canal(..., p_origem text default null)` | Ganhou o último parâmetro, `p_origem`. Com `bling_import`/`reativacao_import`, o canal é "Bling" (depois das regras de click-id) |
| `dashboard_kpis(p_start, p_end, p_tz)` | `leads_new`/`leads_prev` agora seguem a D1: leads distintos com a 1ª `entrada` no período, sem importados e sem `ja_era_cliente`. **Nova coluna** `contacts_new`, a contagem antiga por `leads.created_at` ("Todos os contatos"). `qualification_rate` = leads com evento `qualificado` no período ÷ leads atendidos no período (mensagem do lead respondida pela IA ou pelos botões) |
| `dashboard_funnel_conversion` | O cohort passou a ser o conjunto D1 |

## 3. Views `analytics`

As colunas, a ordem e os tipos não mudaram. As definições anteriores estão em `scripts/leads_vendedor/defs_antes/analytics.*.sql`.

| View | O que mudou |
|---|---|
| `analytics.dim_vendedor` | Agora é lida de `public.vendedores`. Antes era montada juntando sla_seller_config, canais, donos de funil, bling_seller_map, sales e quotes pelo primeiro nome. Campos: `vendedor_chave` = 1º nome sem acento e minúsculo; `user_id` = `vendedores.id`; `emails` = e-mail do cadastro + e-mails do `bling_seller_map` ligados por `vendedor_id`. Inclui os inativos, para resolver o histórico |
| `analytics.dim_lead` | `segmento` = `leads.segmento`. Antes vinha de `stage` ou de `metadata.handoff.segmento`, e podia ser 'secretaria'. `b2b` = `fn_lead_b2b`: lead que só tem score **deixou de ser B2B**. `b2b_fonte` ∈ `segmento`, `pipeline`, `cnpj` ou NULL. Os valores antigos `score_atacado` e `cnpj_bling` não existem mais |
| `analytics.vw_leads` | Mesma definição; ela herda `segmento` e `b2b` de `dim_lead`. A coluna `qualificado` continua calculada (B2B: score ≥ 5 definitivo ou repasse por qualificação; B2C: repasse). O dashboard usa o evento `qualificado` |
| Dependentes (`fct_vendas`, `vw_repasses`, `vw_resposta_closer`, `vw_funil_mes`, `vw_vendedores_semana`, `vw_clientes`, `vw_campanhas_dia`, `vw_disparos`, `vw_produtos_mes`) | A definição não mudou. Elas herdam o novo `segmento`/`b2b` de `dim_lead` e os vendedores de `dim_vendedor` |

Efeito esperado: os números B2B de `vw_funil_mes` e de `vw_leads` caem um pouco, porque o score sozinho não marca mais o lead como B2B. Repasses citando "Vendedor" ou "Comercial" continuam caindo no responsável do lead.

## 4. Grants

`consulta_ro` tem SELECT em `vendedores` e nas views acima, e EXECUTE em `fn_lead_b2b` e `fn_vendedor_id`.

## 5. Consultas-exemplo

```sql
-- Leads por fase e segmento (nenhum stage fora das fases, nenhum segmento fora do enum)
select stage, segmento, count(*) from leads group by 1, 2 order by 3 desc;

-- Origem do cadastro x já era cliente
select origem_cadastro, ja_era_cliente, count(*) from leads group by 1, 2;

-- Leads novos (D1) e todos os contatos em outubro
select leads_new, contacts_new, qualification_rate
  from dashboard_kpis('2026-10-01', '2026-10-31');

-- Qualificados por dia e critério
select (occurred_at at time zone 'America/Sao_Paulo')::date as dia,
       metadata->>'criterio' as criterio, count(*)
  from lead_events where event_type = 'qualificado'
 group by 1, 2 order by 1 desc, 2;

-- Qualificados do dia x repasses do dia
select (select count(*) from lead_events where event_type = 'qualificado'
          and occurred_at >= current_date) as qualificados,
       (select count(*) from lead_events where event_type = 'repasse'
          and occurred_at >= current_date) as repasses;

-- Venda sem vendedor no cadastro (deve dar 0)
select count(*) from sales s
 where s.sold_by is not null
   and not exists (select 1 from vendedores v where v.email = lower(s.sold_by));

-- Deal com vendedor fora do cadastro (deve dar 0)
select count(*) from deals
 where assigned_to is not null and assigned_to not in (select id from vendedores);

-- Deals por vendedor (nome a partir do uuid)
select v.nome, count(*) from deals d join vendedores v on v.id = d.assigned_to group by 1;

-- B2B e de onde vem
select b2b_fonte, count(*) from analytics.dim_lead where b2b group by 1;

-- Um lead é B2B?
select fn_lead_b2b('<lead_id>'::uuid);
```

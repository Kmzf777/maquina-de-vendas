# Runbook: sincronia de pedidos das duas contas Bling

Acompanha a avaliação `docs/avaliacao/2026-10-13-sync-bling-duas-contas.md`. Diz o que rodar **depois do deploy**, em que ordem, quanto custa em chamadas à API e como conferir antes e depois.

Contas: `default` = Bling Café Canastra (1) e `secundaria` = Bling Café Rural (2). Todo comando abaixo vale igual para as duas; só muda `--conta`.

Regras que valem para tudo aqui:
- Nada roda sozinho. Cada passo de escrita em produção precisa do OK explícito do dono.
- Todos os comandos são idempotentes. `sales` faz upsert por `(bling_account, bling_order_id)`, então repetir um passo não duplica venda.
- Os jobs de pedidos (backfill, varredura e reconciliação) usam a mesma trava por conta (`bling:pedidos:{conta}` no Redis). Se um estiver rodando, o outro devolve `"status": "ocupado"` e não chama o Bling. Contas diferentes não se bloqueiam.
- Limite do Bling: 3 req/s e 120 mil por dia, **por conta**. O limitador local recusa acima de 110 mil por dia. As estimativas abaixo usam 3 req/s, ou seja, 180 chamadas por minuto.
- As conferências SQL são só agregados. Rode no SQL editor do Supabase ou pelo `consulta_ro`.

---

## 0. Antes do deploy: aplicar as migrations

As migrations **não** rodam no deploy. Aplique à mão, nesta ordem, **antes** do push. O código novo grava colunas que só existem depois delas. Sem a primeira, todo `upsert` de venda do Bling falha e o webhook para.

| Ordem | Arquivo | O que faz |
|---|---|---|
| 1 | `supabase/migrations/20261014_bling_sync_webhook_vendedor.sql` | `sales.vendedor_fonte` e `sales.discount`, mais `bling_webhook_events.next_attempt_at` e o índice da fila (Fase 1). Só aditiva. |
| 2 | `supabase/migrations/20261014b_bling_reconciliacao.sql` | Tabela `bling_reconciliacao` (Fase 3). Só aditiva. |

```bash
# na pasta backend/, com SUPABASE_PROJECT_REF e SUPABASE_ACCESS_TOKEN do ambiente-alvo
python -m scripts.apply_migrations --status
python -m scripts.apply_migrations --apply --dry-run
python -m scripts.apply_migrations --apply
```

Conferência depois de aplicar:

```sql
select column_name from information_schema.columns
 where table_name = 'sales' and column_name in ('vendedor_fonte','discount');          -- 2 linhas
select column_name from information_schema.columns
 where table_name = 'bling_webhook_events' and column_name = 'next_attempt_at';        -- 1 linha
select to_regclass('public.bling_reconciliacao');                                       -- não nulo
```

---

## 1. Como rodar os comandos

Os comandos rodam **dentro do container do worker**, que já tem as credenciais e o Redis. O comando mora em `app/bling/ops.py`, porque `scripts/` fica fora da imagem.

```bash
CONTAINER=$(sg docker -c "docker ps --filter name=canastra_worker --format '{{.ID}}'" | head -1)
OPS="docker exec $CONTAINER python -m app.bling.ops"
# exemplo:
sg docker -c "$OPS backfill --conta default --desde 2026-07-23 --estimar"
```

- A saída é um JSON com contagens, datas e ids de pedido. Não sai segredo nenhum.
- Código de saída `1` = `interrompido` ou `ocupado`. Nesse caso o comando também gravou um alerta em `system_alerts` (`bling_backfill_interrompido`) e logou em ERROR.
- Para jobs longos, use `| tee ~/bling_<passo>.log` e rode dentro de `tmux`. Se o container reiniciar no meio (deploy), o `exec` morre. Rodar o mesmo comando de novo retoma do cursor da conta.

---

## 2. Conferência "antes" (rodar uma vez, guardar o resultado)

```sql
-- A. Pedidos por conta
select bling_account, count(*) pedidos, min(bling_order_number) menor_numero,
       max(bling_order_number) maior_numero, round(sum(value)::numeric, 2) soma
  from sales where bling_order_id is not null group by 1 order by 1;

-- B. Números que faltam na sequência, desde 01/07/2026 (prova do buraco)
with s as (
  select bling_account, bling_order_number n
    from sales
   where bling_order_id is not null and bling_order_number is not null
     and sold_at >= '2026-07-01')
select bling_account, count(*) filter (where gap > 1) buracos,
       coalesce(sum(gap - 1) filter (where gap > 1), 0) numeros_faltando
  from (select bling_account, n - lag(n) over (partition by bling_account order by n) gap from s) x
 group by 1 order by 1;

-- C. Cursores
select account, resource, last_cursor, last_sync_at
  from bling_sync_state
 where resource in ('backfill', 'orders_sweep', 'reconciliacao')
 order by 1, 2;

-- D. Eventos de webhook por conta e status
select account, status, count(*) from bling_webhook_events group by 1, 2 order by 1, 2;

-- E. Leads criados pelo import (para medir o efeito do backfill da conta 2 no B8)
select count(*) from leads where metadata->>'origem' = 'bling_webhook';

-- F. Situação x status (B10)
select bling_account, bling_situacao_nome, status, count(*), round(sum(value)::numeric, 2)
  from sales where bling_order_id is not null group by 1, 2, 3 order by 1, 4 desc;
```

Valores esperados hoje (avaliação de 13/10):
- A: `default` 1.047 e `secundaria` 77.
- B: `default` com ~115 números faltando e `secundaria` com ~15.
- C: `backfill/default` com `last_cursor = 2026-07-22`, e nenhuma linha `backfill/secundaria`.
- D: 21 `failed` na `default` e 10 na `secundaria`.

---

## 3. Passo A: retomar o backfill da conta 1 a partir de 23/07/2026

O cursor parou em `2026-07-22` (G1). O intervalo vai de 23/07 até hoje. O backfill relê também os pedidos que já estão no banco, o que é inofensivo: é upsert e vale como reconferência.

```bash
# 1. custo (só lista, não grava): ~3-4 chamadas
sg docker -c "$OPS backfill --conta default --desde 2026-07-23 --estimar"
# 2. com o OK do dono:
sg docker -c "$OPS backfill --conta default --desde 2026-07-23" | tee ~/bling_backfill_default.log
```

Custo esperado:

| Item | Chamadas |
|---|---|
| Listagem: 3 janelas de 30 dias (23/07–21/08, 22/08–20/09, 21/09–hoje), menos de 100 pedidos cada | 3–4 |
| Detalhe: 1 por pedido, de ~150 pedidos (nº 5875 a ~6020) | ~150 |
| Contato sob demanda: só para contato fora do espelho (Fase 1) | 0–20 |
| **Total** | **~155–175 chamadas, cerca de 1 minuto a 3 req/s** |

Resultado esperado no JSON: `"status": "concluido"`, `"pedidos"` perto de 150 e `"concluido_ate"` = hoje.

Conferência "depois": repita A, B e C.
- A: `default` sobe ~114.
- B: os buracos de julho e agosto da `default` caem para perto de 0. O que sobrar deve ser pedido apagado no Bling (confirmar no painel).
- C: `backfill/default.last_cursor` = data de hoje.

---

## 4. Passo B: histórico da conta 2 (decisão do dono: 12 ou 24 meses)

A conta 2 não tem histórico anterior ao nº 3645 (G6). No banco, os pedidos começam em 09/09/2026. O intervalo vai de `hoje − N meses` até 08/09/2026, e o resto já está coberto. A semana de estreia, 09/09 a 16/09, tem 14 números faltando. Por isso o intervalo vai até **hoje**: assim ela é fechada também.

```bash
# 1. custo das duas opções (só listagem: ~13 a ~40 chamadas cada)
sg docker -c "$OPS backfill --conta secundaria --meses 12 --estimar"
sg docker -c "$OPS backfill --conta secundaria --meses 24 --estimar"
# 2. com o OK do dono, UMA das duas (rodar fora do horário comercial):
sg docker -c "$OPS backfill --conta secundaria --meses 12" | tee ~/bling_backfill_secundaria.log
#   ou
sg docker -c "$OPS backfill --conta secundaria --meses 24" | tee ~/bling_backfill_secundaria.log
```

Custo esperado. `P` é o `pedidos_no_bling` que o `--estimar` devolve. A numeração dá um teto de ~3.750 pedidos para a vida toda da conta.

| Item | 12 meses | 24 meses |
|---|---|---|
| Listagem (12 ou 24 janelas, mais 1 página a cada 100 pedidos) | 12 + P/100 | 24 + P/100 |
| Detalhe (1 por pedido) | P | P |
| Contato sob demanda (só os que faltam no espelho, que tem 3.822 contatos da conta 2) | 0 a P | 0 a P |
| **Total, com o teto P ≈ 3.750** | **≤ ~7.600 chamadas, ≤ ~42 min** | **≤ ~7.600 chamadas, ≤ ~42 min** |
| **Total provável (P ≈ 1.500–2.500)** | **~1.600–2.600, ~9–15 min** | **~2.500–3.800, ~14–21 min** |

Mesmo o teto fica abaixo de 7% da cota diária. Duas observações:
- Leads: cada cliente antigo sem lead vira lead novo (`ensure_lead`, `metadata.origem = 'bling_webhook'`). A conferência E mostra quantos. Coordene com o B8 antes de ler KPIs de marketing.
- Card de Reposição: o backfill não abre card de Reposição (só o webhook abre, e só para venda de até 7 dias).

Conferência "depois":
- A: `secundaria` sobe para ~77 + P.
- B: os buracos da `secundaria` caem para perto de 0.
- C: `backfill/secundaria.last_cursor` = hoje.
- E: o aumento deve ser menor ou igual ao número de clientes distintos importados.

Se parar no meio (`"status": "interrompido"`):
1. Leia `erro` e `falhas` no JSON (ou no alerta `bling_backfill_interrompido`).
2. Corrija a causa.
3. Rode o **mesmo** comando. Ele retoma da janela que falhou.

Para refazer um trecho já concluído, use `--reiniciar` com `--desde` e `--ate`.

---

## 5. Passo C: reprocessar os eventos de webhook `failed`

Os 31 eventos `failed` (21 na `default` e 10 na `secundaria`) têm todos o erro `lead_id` nulo, de contato ainda fora do espelho. Com a Fase 1, o contato é buscado sob demanda, então o reprocessamento deve fechar todos.

```bash
sg docker -c "$OPS reprocessar-falhas --conta default"
sg docker -c "$OPS reprocessar-falhas --conta secundaria"
```

- O comando só devolve os eventos para a fila (`pending`, tentativas zeradas). Quem processa é o worker, no tick de webhook (≤ 60 s).
- Custo: até 2 chamadas por evento (detalhe e, se faltar, contato). São ≤ 62 chamadas no total.
- Idempotente: a segunda execução devolve `"reabertos": 0`.
- Depois da Fase 2, a varredura também reabre sozinha os `failed` com mais de 6 h, recebidos nos últimos 7 dias. Este passo serve para o estoque antigo.

Conferência "depois" (esperar ~2 min): a consulta D deve mostrar `failed` = 0 nas duas contas.

```sql
-- pedidos que tinham evento e continuam sem venda (esperado: 0)
select e.account, count(distinct (e.payload->'data'->>'id')) pedidos_sem_venda
  from bling_webhook_events e
  left join sales s on s.bling_account = e.account
                   and s.bling_order_id = (e.payload->'data'->>'id')::bigint
 where e.event like 'order.%' and e.event <> 'order.deleted' and s.id is null
 group by 1;
```

---

## 6. Varredura periódica (Fase 2): automática, só conferir

O worker roda `bling-pedidos` a cada `BLING_VARREDURA_HORAS` horas. O padrão é 2 h, e o valor fica limitado entre 1 e 3 h. A primeira rodada sai no start do worker, e o tick fica ancorado nele, como os outros. Para cada conta, em sequência:
1. Lista os pedidos alterados desde o cursor `bling_sync_state(account, 'orders_sweep')`, menos 6 h de margem.
2. Importa cada pedido listado, com o detalhe e o contato sob demanda.
3. Avança o cursor **só** se todos entraram. Se algum falhar, o cursor fica onde estava e sai o alerta `bling_varredura_falhou`.
4. Reabre os eventos de webhook `failed` da conta parados há mais de 6 h e recebidos nos últimos 7 dias.

> **VERIFICAR ANTES DO DEPLOY: o filtro da API.** A varredura usa `GET /pedidos/vendas?dataAlteracaoInicial=AAAA-MM-DD HH:MM:SS`, o mesmo formato que já funciona em `/produtos` e `/contatos`. Não deu para confirmar na documentação oficial da API v3 (developer.bling.com.br/referencia) que o endpoint de pedidos aceita esse filtro. Confira lá antes do push, sem chamar a API com token de produção.
>
> - Se o filtro **existir**, nada a fazer.
> - Se **não existir**, o Bling pode ignorá-lo e devolver a base inteira. A guarda `MAX_PEDIDOS_POR_RODADA = 500` para a rodada sem importar nada e grava o alerta `bling_varredura_filtro`. Nesse caso, desligue a varredura com `BLING_VARREDURA_ATIVA=false` no worker (`docker service update --env-add BLING_VARREDURA_ATIVA=false canastra_worker`) e peça a troca do filtro para `dataInicial`/`dataFinal` dos últimos 60–90 dias.
> - Se o Bling responder **400** ao filtro, a rodada para com o alerta `bling_varredura_falhou` e nada é gravado.

Custo por conta e por rodada: 1 listagem a cada 100 pedidos alterados, mais 1 detalhe por pedido alterado, mais 1 contato por cliente novo fora do espelho. Hoje são ~30 pedidos por semana na `default` e ~20 na `secundaria`. Com a margem de 6 h, cada pedido aparece em ~3 rodadas seguidas. Dá por volta de **100–300 chamadas por dia por conta**, menos de 0,3% da cota.

Rodar uma rodada na mão (idempotente):

```bash
sg docker -c "$OPS varrer --conta default"
sg docker -c "$OPS varrer --conta secundaria"
```

Conferência:

```sql
-- o cursor anda a cada 1-3 h nas duas contas
select account, last_sync_at, now() - last_sync_at atraso
  from bling_sync_state where resource = 'orders_sweep' order by 1;
-- situação congelada: "Em aberto"/"Em andamento" com mais de 30 dias deve cair (G5)
select bling_account, bling_situacao_nome, count(*)
  from sales where bling_order_id is not null and sold_at < now() - interval '30 days'
   and bling_situacao_nome in ('Em aberto', 'Em andamento')
 group by 1, 2;
-- alertas da varredura
select type, metadata->>'conta' conta, count(*), max(created_at)
  from system_alerts where type like 'bling_%' and created_at > now() - interval '7 days'
 group by 1, 2 order by 1, 2;
```

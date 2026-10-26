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

## 0. Antes do deploy: gates, migrations e configuração

As migrations **não** rodam no deploy. Tudo desta seção acontece **antes** do push, nesta ordem. As consultas marcadas "só leitura" podem rodar pelo `consulta_ro`; as migrations precisam do OK do dono.

### 0.1 Gate: situações de cada conta (obrigatório, só leitura)

O status da venda passa a depender do **nome** da situação no Bling. Regra:
- nome com "cancelad" → `cancelada`;
- nome com "devolv"/"devoluc" **sem** "parcial" e **sem** "em " (devolução total **concluída**, ex.: "Devolvido") → `cancelada`;
- nome com "devolv"/"devoluc" **e** "parcial" (ex.: "Devolvido parcialmente") **ou** "em devolução" (devolução em andamento, ainda pode não se concretizar) → continua venda (`registrada`), com `sales.devolucao_parcial = true` e o alerta `bling_devolucao_parcial` para revisão (decisão do dono). Atenção: a coluna e o alerta têm "parcial" no nome por razões históricas, mas significam "devolução a revisar" (parcial ou em andamento);
- situação padrão 12 ("Cancelado") cancela mesmo sem o espelho;
- nome desconhecido (fora do espelho) não muda nada: venda cancelada continua cancelada.

```sql
-- só leitura: liste e confira, conta por conta, o que cada situação vai virar
select account, id, nome,
       case
         when unaccent(lower(nome)) like '%cancelad%' then 'cancelada'
         when unaccent(lower(nome)) ~ '(devolv|devoluc)'
              and (unaccent(lower(nome)) like '%parcial%' or unaccent(lower(nome)) like '%em devoluc%')
           then 'venda + devolucao_parcial (a revisar)'
         when unaccent(lower(nome)) ~ '(devolv|devoluc)' then 'cancelada'
         else 'registrada'
       end efeito
  from bling_situacoes order by 1, 2;
-- (sem a extensão unaccent, troque unaccent(lower(nome)) por lower(nome) e confira os acentos à mão)
```

**Não fazer o push** enquanto o dono não confirmar a lista das duas contas, inclusive as devoluções parciais e em andamento. Situação de cancelamento ou devolução com outro nome → ajustar `_TRECHOS_CANCELAMENTO`/`_TRECHO_PARCIAL`/`_TRECHO_EM_ANDAMENTO` em `backend/app/bling/orders.py` antes.

### 0.2 Gate: formato da data do webhook (só leitura)

A ordem dos eventos agora compara **instantes** (aceita `Z`, offset e fração de segundo; data sem fuso é tratada como UTC). Confira o formato real que o Bling manda em cada conta:

```sql
select account, payload->>'date' exemplo, count(*)
  from bling_webhook_events
 where received_at > now() - interval '7 days'
 group by 1, 2 order by 1, 3 desc limit 20;
```

Esperado: ISO 8601 com `Z` ou offset (ex.: `2026-10-13T19:49:00Z`). Se vier **sem fuso** (`2026-10-13 16:49:00`), ele é hora de Brasília e a comparação o trata como UTC: avise antes do deploy para ajustar `_instante` em `webhook_processor.py`.

### 0.3 Migrations, nesta ordem

| Ordem | Arquivo | O que faz |
|---|---|---|
| 1 | `supabase/migrations/20261013_sales_freight.sql` | `sales.freight` e `sales.freight_mode`. Já está em `origin/master`, mas **confirme se foi aplicada em produção** (consulta abaixo): `upsert_from_bling` grava `freight`. Só aditiva. |
| 2 | `supabase/migrations/20261014_bling_sync_webhook_vendedor.sql` | `sales.vendedor_fonte` (check `NOT VALID` + `VALIDATE` separado), `sales.discount`, `sales.devolucao_parcial`, `bling_webhook_events.next_attempt_at` e o índice dos `failed` (Fase 1). Só aditiva. |
| 3 | `supabase/migrations/20261014b_bling_reconciliacao.sql` | Tabela `bling_reconciliacao`, RLS, `GRANT` e policy de leitura para `consulta_ro` se o role existir (Fase 3). Só aditiva. |

Antes de aplicar (só leitura), veja se a 1 já está em produção:

```sql
select column_name from information_schema.columns
 where table_name = 'sales' and column_name in ('freight', 'freight_mode');   -- 2 linhas = já aplicada
```

Sem a 1 ou a 2, todo `upsert` de venda do Bling falha (`PGRST204`/`42703`) e o webhook para.

```bash
# na pasta backend/, com SUPABASE_PROJECT_REF e SUPABASE_ACCESS_TOKEN do ambiente-alvo
python -m scripts.apply_migrations --status
python -m scripts.apply_migrations --apply --dry-run
python -m scripts.apply_migrations --apply
```

Conferência depois de aplicar:

```sql
select column_name from information_schema.columns
 where table_name = 'sales'
   and column_name in ('freight','freight_mode','vendedor_fonte','discount','devolucao_parcial'); -- 5 linhas
select column_name from information_schema.columns
 where table_name = 'bling_webhook_events' and column_name = 'next_attempt_at';        -- 1 linha
select conname, convalidated from pg_constraint
 where conname = 'sales_vendedor_fonte_check';                                          -- convalidated = true
select to_regclass('public.bling_reconciliacao');                                       -- não nulo
select policyname, roles from pg_policies where tablename = 'bling_reconciliacao';      -- _select e _consulta_ro
```

### 0.4 Deploy com a varredura DESLIGADA (já é o padrão)

O filtro `dataAlteracaoInicial` de `GET /pedidos/vendas` ainda não foi confirmado (seção 6). Por isso `BLING_VARREDURA_ATIVA` **assume DESLIGADA quando ausente**: faça o deploy como está, sem adicionar variável nenhuma. A reconciliação diária tem chave própria, `BLING_RECONCILIACAO_ATIVA`, **ligada por padrão** (usa `dataInicial`/`dataFinal`, que já funcionam em produção) e roda no job `bling-pedidos` mesmo com a varredura desligada.

Para ligar a varredura mais tarde, depois de confirmar o filtro: adicione `BLING_VARREDURA_ATIVA=true` ao `.env` do backend na VPS e faça redeploy/restart do worker.

### 0.5 Logo depois do deploy: reprocessar os `failed` (obrigatório)

Por conta, assim que o worker novo subir (`$OPS` da seção 1; detalhes na seção 5):

```bash
sg docker -c "$OPS reprocessar-falhas --conta default"
sg docker -c "$OPS reprocessar-falhas --conta secundaria"
```

Os eventos `failed` antigos não têm o contato sob demanda da Fase 1 e só voltam para a fila por este comando (a varredura, desligada no 0.4, não os reabre).

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
- Código de saída `1` = `interrompido`, `ocupado`, `sem_redis`, `parcial`, `divergente` ou `nada_a_fazer`. Em `interrompido` o comando também gravou um alerta em `system_alerts` (`bling_backfill_interrompido`) e logou em ERROR. Em `nada_a_fazer` leia o `aviso`: o intervalo pedido já estava todo antes do cursor salvo da conta e nada foi importado.
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

Pedido com falha **permanente** (sem lead, 4xx ou 404 do Bling) não para mais o backfill: vai para `ignorados` no JSON, fica registrado no alerta `bling_pedido_ignorado` (com a conta e os ids em `metadata.pedidos`) e o backfill segue. Só erro transitório (429, 5xx, timeout, token, teto diário) ou desconhecido para e segura o cursor.

Para refazer um trecho já concluído, use `--reiniciar` com `--desde` e `--ate`. O `--reiniciar` **não recua o cursor** da conta: ele só grava cursor que passe do salvo. Recuar só com `--recuar-cursor` junto, de propósito.

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
3. Avança o cursor se não houve erro transitório nem desconhecido. Se houver, o cursor fica onde estava e sai o alerta `bling_varredura_falhou`. Pedido com falha **permanente** (sem lead, 4xx) não segura o cursor: fica no alerta `bling_pedido_ignorado` (ids em `metadata.pedidos`, dedup pelo conjunto de pedidos) e a reconciliação continua apontando o dia.
   - Pedido **novo e recente** (até 7 dias) recuperado pela varredura abre o card de Reposição, como o webhook abriria.
   - Redis fora: a rodada é pulada com WARNING; depois de 3 pulos seguidos sai o alerta `bling_redis_indisponivel`.
4. Reabre os eventos de webhook `failed` da conta parados há mais de 6 h e recebidos nos últimos 7 dias.

> **VERIFICAR ANTES DO DEPLOY: o filtro da API.** A varredura usa `GET /pedidos/vendas?dataAlteracaoInicial=AAAA-MM-DD HH:MM:SS`, o mesmo formato que já funciona em `/produtos` e `/contatos`. Não deu para confirmar na documentação oficial da API v3 (developer.bling.com.br/referencia) que o endpoint de pedidos aceita esse filtro. Confira lá antes do push, sem chamar a API com token de produção.
>
> - Se o filtro **existir**, nada a fazer.
> - Se **não existir**, o Bling pode ignorá-lo e devolver a base inteira. A guarda `MAX_PEDIDOS_POR_RODADA = 500` para a rodada sem importar nada e grava o alerta `bling_varredura_filtro`. Nesse caso, desligue a varredura (remova `BLING_VARREDURA_ATIVA` do `.env` do backend ou ponha `false`, e reinicie o worker; a reconciliação continua rodando) e peça a troca do filtro para `dataInicial`/`dataFinal` dos últimos 60–90 dias.
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

---

## 7. Reconciliação diária (Fase 3): automática, só conferir

Ela roda no mesmo tick (job `bling-pedidos`) da varredura, mas **independe** dela: funciona com a varredura desligada (o padrão) e tem chave própria, `BLING_RECONCILIACAO_ATIVA` (ligada por padrão). Roda uma vez por dia por conta, a partir das 03:00 de Brasília, e, quando a varredura está ligada, depois da varredura da conta. Para cada conta:
1. Lista os pedidos do Bling dos últimos 35 dias fechados, até ontem, pela data do pedido. Usa `dataInicial`/`dataFinal`, o mesmo filtro que o backfill já usa em produção.
2. Compara com `sales` **por dia**: quantidade, soma (`total` × `value`) e ids. Os ids podem estar faltando no banco, sobrando no banco ou com valor diferente.
3. Dia divergente: reimporta só os pedidos envolvidos e confere de novo.
4. Grava todos os dias em `bling_reconciliacao`, com status `ok`, `reimportado` ou `divergente`.
5. Se sobrar dia divergente, grava o alerta `bling_reconciliacao_divergente`, com dedup de 12 h por conta.

Pedido que sobra no banco e não existe mais no Bling (apagado, G10) **não** é cancelado automaticamente. Ele fica em `divergentes.apagados_no_bling` e o dia continua `divergente` até o dono decidir. Exceção: se a venda **já está `cancelada`** no banco, o dia fica `ok` com `divergentes.observacao = 'apagado'`, e nas noites seguintes o pedido não é reimportado nem alerta.

Erro transitório na reimportação (429, 5xx, timeout, token) não grava o dia nem marca a conta como reconciliada: o próximo tick tenta de novo. Redis fora: mesmo tratamento da varredura (WARNING e alerta depois de 3 pulos).

Custo por conta e por dia: 1 a 3 listagens (35 dias × ~5 pedidos = ~175 pedidos, menos de 2 páginas), mais 1–2 chamadas por pedido divergente. Com tudo em dia, são **2–3 chamadas por conta por noite**.

Rodar na mão (idempotente; grava `bling_reconciliacao` e pode reimportar):

```bash
sg docker -c "$OPS reconciliar --conta default"
sg docker -c "$OPS reconciliar --conta secundaria --dias 35"
```

Rodar a primeira vez **depois** dos passos A, B e C. Antes deles, todo dia de julho e agosto da conta 1 sai divergente e é reimportado ali mesmo. O resultado final é o mesmo, mas o alerta polui.

Conferência:

```sql
-- "Bling conferido até X", por conta: último dia sem nenhum divergente antes dele
select account,
       max(dia) filter (where status <> 'divergente') ultimo_dia_ok,
       count(*) filter (where status = 'divergente') dias_divergentes,
       count(*) filter (where status = 'reimportado') dias_corrigidos,
       max(verificado_em) verificado_em
  from bling_reconciliacao
 where dia >= current_date - 35
 group by 1 order by 1;

-- dias que continuam divergentes (só agregados)
select account, dia, qtd_bling, qtd_banco, soma_bling, soma_banco,
       jsonb_array_length(coalesce(divergentes->'faltando', '[]')) faltando,
       jsonb_array_length(coalesce(divergentes->'sobrando', '[]')) sobrando,
       jsonb_array_length(coalesce(divergentes->'apagados_no_bling', '[]')) apagados
  from bling_reconciliacao where status = 'divergente' order by 1, 2;
```

Critério de aceite da avaliação: 35 dias × 2 contas sem `divergente`, exceto os apagados confirmados no painel do Bling.

---

## 8. Variáveis de ambiente novas (worker)

| Variável | Padrão | Efeito |
|---|---|---|
| `BLING_VARREDURA_HORAS` | `2` | Intervalo da varredura, limitado a 1–3 h. Lido no start do worker. |
| `BLING_VARREDURA_ATIVA` | **desligada** | Controla SÓ a varredura periódica. `true` liga. Só ligar depois de confirmar o filtro `dataAlteracaoInicial` (seção 0.4/6): adicionar ao `.env` do backend na VPS e reiniciar o worker. |
| `BLING_RECONCILIACAO_ATIVA` | ligada | Controla SÓ a reconciliação diária. `false` desliga (reiniciar o worker). Independe da varredura. |
| `BLING_VENDEDOR_LEAD_DIAS` | `60` | Decisão do dono: o 3º degrau do vendedor (`leads.assigned_to`, responsável atual do lead) só vale para venda com `sold_at` nesses últimos dias. Venda mais antiga sem vendedor no pedido nem no contato fica sem vendedor (`sold_by`/`vendedor_fonte` nulos). Vale para webhook, varredura, backfill e reconciliação. |

Nenhuma credencial nova. Varredura e reconciliação usam o `BlingClient` de cada conta: o mesmo token, o mesmo refresh com lock por conta (`auth.get_access_token`) e o mesmo rate limit.

---

## 9. Antes do push: checklist

1. **Filtro da API.** Conferir que `GET /pedidos/vendas` aceita `dataAlteracaoInicial` (seção 6).
2. **Nomes das situações por conta (gate 0.1).** "cancelad" e devolução total viram `cancelada`; devolução **parcial** continua venda com `devolucao_parcial = true`. A situação padrão 12, "Cancelado", também cancela, mesmo sem espelho. Confirmar a lista com o dono (consulta da seção 0.1).
3. **Efeito em cancelados.** Medir antes quanto vai mudar quando os pedidos forem relidos pelo backfill ou pela varredura. Na avaliação eram 57 pedidos, R$ 59.842.
   ```sql
   select bling_account, count(*), round(sum(value)::numeric, 2)
     from sales where bling_order_id is not null and status <> 'cancelada'
      and (bling_situacao_nome ilike '%cancelad%' or bling_situacao_nome ilike '%devol%')
    group by 1;
   ```
   Os pedidos antigos só mudam quando forem relidos. O backfill dos passos A e B relê a janela dele. O resto da base precisa de `--reiniciar` com o intervalo inteiro, que é uma decisão do dono.
4. **Mapa de vendedores.** Só há 1 linha por conta em `bling_seller_map`. Sem mapear os ids do Bling para os e-mails, o 1º e o 2º degraus da cascata D8 não acham ninguém e a venda cai em `leads.assigned_to` (só venda dos últimos 60 dias) ou fica sem vendedor.
   ```sql
   select account, count(*) from bling_seller_map group by 1;
   ```
5. **Formato da data do webhook** (gate 0.2).
6. **Aplicar as três migrations**, na ordem (seção 0.3), e conferir.
7. **Deploy como está** (varredura desligada por padrão, reconciliação ligada; seção 0.4).
8. **Depois do deploy: `reprocessar-falhas` nas duas contas** (seção 0.5).

---

## Cartão 1e6381fe (26/10/2026)

Spec `docs/superpowers/specs/2026-10-26-vendas-receita-d7-design.md`. Glossário para o agente de consulta: `docs/superpowers/specs/2026-10-26-glossario-consulta-vendas.md`.

**Situações (gate 0.1), lista confirmada pelo dono em 26/10:**
- `Cancelado` (ids 12 e 34, nas duas contas) → `cancelada`;
- `Em devolução` (id 729685, só na conta 1) → continua venda, com `devolucao_parcial = true` (a revisar);
- `Em aberto`, `Em andamento`, `Atendido`, `Verificado`, `Em digitação`, `Venda Agenciada` e `Pagamento aprovado` → venda.

Não há "Devolvido" em nenhuma conta. A regra de `classificar_situacao` (`backend/app/bling/orders.py`) já fazia isso e não mudou.

**Resultado do P1 (vendedor do contato, só leitura):** `GET /contatos/{id}` na conta 1, em 2 contatos cujos pedidos têm o João como vendedor, devolveu `vendedor: {"id": 0}`. O vendedor não está preenchido no contato no Bling, então o degrau 2 da D8 (`bling_contato`) fica **indisponível na API**. Não há comando `contatos-vendedor` e `sync.py` não mudou.

**Releitura da conta 1 (P2), fora do horário comercial e com o OK do dono:**

```bash
sg docker -c "$OPS backfill --conta default --desde 2025-08-01 --ate 2026-10-13 --reiniciar --estimar"
sg docker -c "$OPS backfill --conta default --desde 2025-08-01 --ate 2026-10-13 --reiniciar" | tee ~/bling_1e63_backfill.log
```

Relê os pedidos da conta 1 dessa janela (os 47 `Cancelado` viram `cancelada`, os 995 sem desconto/frete gravados passam a ter). Antes e depois, seguir `docs/superpowers/specs/2026-10-26-dados-1e63.sql`, um bloco por vez: conferência C0, cópia P0 (`backup_1e63_vendas`), automações A1, conferência C1, teto de 80 cancelamentos novos (passou disso, parar e levar ao dono), lista P3 ao dono e o rollback do P2.

**Reconciliação diária (seção 7), a partir deste cartão:**
- os dias são de Brasília (`America/Sao_Paulo`), não UTC, no banco e na comparação;
- compara também a **situação**: pedido com `situacao.id` da listagem diferente de `sales.bling_situacao_id` entra em `situacao_diferente`, o dia fica divergente e o pedido é reimportado. Assim um cancelamento chega em até 1 dia mesmo sem webhook. Situação nula num dos lados não conta como divergência.

**`sold_at`:** pedido do Bling passa a ser gravado ao meio-dia de Brasília (`AAAA-MM-DDT12:00:00-03:00`), e não mais meio-dia UTC. A data do pedido não muda. As vendas antigas (12:00Z = 09:00 em Brasília) caem no mesmo dia em Brasília; a releitura do P2 regrava o `sold_at` delas no formato novo.

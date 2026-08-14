# Lote completo do Bling — runbook

Cria **1.218 leads** no CRM com funil, 8 etapas, deals, tags e nota de briefing.
**Não dispara nada** — nenhum registro em `broadcasts`/`broadcast_leads`.

- Spec: `docs/superpowers/specs/2026-08-14-reativacao-bling-lote-completo-design.md`
- Plano: `docs/superpowers/plans/2026-08-14-reativacao-bling-lote-completo.md`
- Código: `scripts/reativacao/lote_completo.py` (só gera arquivos, não executa)
- Não confundir com `README.md`, que é o runbook do lote de 10/08 (`generate_sql.py`),
  ainda pendente de aplicação e independente deste.

## 0. Backup — obrigatório

O banco não tem backup automático (`archive_mode = off`, sem cron). Não é "seria bom":
é o único jeito de voltar atrás do que o rollback não cobre.

```bash
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker exec \$D pg_dump -U postgres --no-owner postgres > /root/backup-pre-lote-completo-\$(date +%F).sql; ls -lh /root/backup-pre-lote-completo-*.sql"
```

Esperado: arquivo de ~106 MB. Muito menor que isso = dump truncado, **pare**.

## 1. Extrair os telefones que já existem no CRM

```bash
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker exec \$D psql -U postgres -A -t -c \"select phone from leads union select wa_id from leads where wa_id is not null\"" > /tmp/telefones_crm.txt
wc -l /tmp/telefones_crm.txt
```

Esperado: ~4.200 linhas (`phone` + `wa_id` dos 2.339 leads). Arquivo vazio faz o CLI abortar
com `ValueError` — comportamento certo: "CRM vazio" nunca é estado normal, e tratá-lo como
tal criaria 1.218 leads duplicados sobre uma base que já os tem.

> Sem acesso SSH, dá para gerar o mesmo arquivo pela API REST do Supabase com a
> `SUPABASE_SERVICE_KEY` (`GET /rest/v1/leads?select=phone,wa_id`, paginando de 1.000 em
> 1.000 — o PostgREST corta aí). Foi assim que a rodagem de conferência de 14/08/2026 foi
> feita, e ela bateu os mesmos 1.218.

## 2. Gerar o SQL

```bash
python scripts/reativacao/lote_completo.py \
  --csv "leads-bling-completo-2026-08-08-br (1).csv" \
  --telefones-crm /tmp/telefones_crm.txt \
  --esperado-novos 1218 \
  --saida /tmp/lote_completo
```

Saída esperada:

```
linhas no CSV:        2771
ja no CRM:            288
sem telefone:         1231
duplicados no CSV:    34
leads a criar:        1218
```

`--esperado-novos` não é documentação: se a contagem não bater exatamente, o CLI sai com
código 1 e **não escreve arquivo nenhum**. Se divergir, investigue antes de mudar o número
— a causa provável é a base ter ganhado leads desde 14/08/2026, e aí a diferença tem que se
explicar por eles.

## 3. Conferir os guardrails

```bash
cd /tmp/lote_completo
grep -c "INSERT INTO leads"           preparar.sql   # 1218
grep -c "INSERT INTO lead_notes"      preparar.sql   # 1218
grep -c "INSERT INTO deals"           preparar.sql   # 1218
grep -c "INSERT INTO pipelines"       preparar.sql   # 1
grep -c "INSERT INTO pipeline_stages" preparar.sql   # 8
grep -c "INSERT INTO tags"            preparar.sql   # 4
grep -c "INSERT INTO lead_tags"       preparar.sql   # 5
grep -c "RAISE EXCEPTION"             preparar.sql   # 4
grep -cE "broadcasts|broadcast_leads" preparar.sql   # 0  <- obrigatório
grep -c "assigned_to"                 preparar.sql   # 0  <- obrigatório
wc -l preparar.sql                                   # ~19.275
wc -l rollback.sql                                   # ~24
```

Divergiu? **Não aplique.** Volte ao `lote_completo.py` — o `.sql` nunca deve ser editado à
mão; o próprio cabeçalho do arquivo diz isso.

Leia também duas ou três notas de briefing à mão (`grep -m3 -A 12 "REATIVAÇÃO BLING" preparar.sql`)
e confira que o nome do lead não é razão social crua, que a linha `ICP` não aparece (este
lote não tem esse enriquecimento) e que a linha de débito aparece em quem tem valor vencido.

## 4. Aplicar

```bash
scp /tmp/lote_completo/preparar.sql root@173.249.15.11:/tmp/
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker cp /tmp/preparar.sql \$D:/tmp/; docker exec \$D psql -U postgres -v ON_ERROR_STOP=1 -f /tmp/preparar.sql"
```

**Se terminar sem erro, tudo foi aplicado e committado. Se aparecer
`ERROR: esperado N ..., encontrado M`, a transação inteira foi revertida e nada persistiu**
— nem lead, nem nota, nem deal, mesmo que os `\echo` de sucesso tenham aparecido antes.
Não existe meio-termo: ou o `COMMIT;` rodou, ou não rodou.

## 5. Verificar

Os quatro blocos `RAISE EXCEPTION` já conferiram as contagens antes do `COMMIT`. O que resta
é confirmar que **cada etapa é selecionável na UI de disparo**. Isso importa porque
`GET /api/leads` não pagina e o PostgREST corta em 1.000: o filtro por funil/etapa é
server-side e reduz o conjunto antes do corte, mas só funciona se nenhuma etapa passar de
1.000 deals.

```bash
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker exec \$D psql -U postgres -c \"select s.label, count(d.id) from pipeline_stages s left join deals d on d.stage_id = s.id where s.pipeline_id = 'b2f9c31d-8a47-4e26-95c0-3d7a1f6e8b09' group by s.label, s.order_index order by s.order_index\""
```

Esperado — **nenhuma linha pode passar de 1.000**:

| Etapa | Deals |
|---|---|
| Ativo (0-3m) | 76 |
| Inativo 3-6m | 68 |
| Inativo 6-12m | 71 |
| Inativo 12-24m | 63 |
| Inativo 24-36m | 102 |
| Inativo 36m+ | 670 |
| Pedido sem faturar | 62 |
| Nunca comprou | 106 |

E a tag fixa de inadimplência, que o modal de disparo lê para avisar:

```bash
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker exec \$D psql -U postgres -c \"select count(*) from lead_tags where tag_id = '3d1b8e6c-7a24-4f95-b8d1-5c0e9a47f210'\""
```

Esperado: **182**.

## 6. Rollback

```bash
scp /tmp/lote_completo/rollback.sql root@173.249.15.11:/tmp/
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker cp /tmp/rollback.sql \$D:/tmp/; docker exec \$D psql -U postgres -v ON_ERROR_STOP=1 -f /tmp/rollback.sql"
```

Desfaz, nesta ordem: vínculos de tag dos leads criados, as 4 tags novas, os deals do funil,
as 8 etapas, o funil, as notas de briefing e os leads que este lote criou (chaveado em
`metadata->>'criado_por_lote'`).

**Não toca no lote de 10/08.** Essa separação é deliberada e vale conhecer, porque a
primeira versão não a tinha:

- **A tag `B2B` não é apagada** — ela já existia e é usada por outros 271 leads. Só o
  vínculo dos leads deste lote sai.
- **As notas do lote de 10/08 não são apagadas.** Este lote usa
  `author = 'Sistema — Reativação Bling 08/26'`, enquanto o de 10/08 usa
  `'Sistema — Reativação Bling'`. Com a string repetida, o `DELETE` por autor levaria junto
  as notas do outro lote, que não têm `criado_por_lote` para protegê-las.

Ao contrário do lote de 10/08, aqui o rollback é completo: este lote só cria, nunca atualiza
lead pré-existente nem normaliza telefone alheio. O único caso não coberto é um lead deste
lote que já tenha recebido mensagem antes do rollback rodar — aí a conversa some junto com
ele. Se isso for possível, restaure o dump do passo 0 em vez de rodar o rollback.

## Duas coisas que valem saber antes de disparar

**244 dos 1.218 são telefone fixo** e ficam gravados com 12 dígitos, sem o 9º dígito
injetado. Isso é proposital: injetá-lo em `(68) 3302-0386` produziria `68 9 3302-0386`, um
celular válido que provavelmente pertence a outra pessoa — e este lote alimenta disparo de
template. `metadata->>'whatsapp_tipo'` marca esses leads, e vale filtrá-los ao montar o
disparo: fixo raramente tem WhatsApp, então eles tendem a virar falha de entrega, o que
pesa na saúde do número.

**182 têm débito vencido** e carregam a tag `Débito vencido` mais os valores em `metadata`.
Eles entram no lote por decisão explícita (D2 do spec), e o modal de disparo avisa quando
algum deles estiver na seleção — mas quem monta a campanha decide.

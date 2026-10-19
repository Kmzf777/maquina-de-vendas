# Backfills R1, R2 e R3 do cartão 7b143561

Spec: `docs/superpowers/specs/2026-10-19-repasse-sla-closer-design.md`, seção 7. Plano: Tarefa 7.

**Nenhum destes scripts foi rodado em produção.** Cada um roda só depois do OK do Rafael no
Discord, um por vez, com a contagem prévia na mão. Antes deles:

1. a migration `supabase/migrations/20261019_repasse_sla.sql` aplicada;
2. o deploy do código.

Testados no Postgres descartável (`scratch_pg.md`) por `backend/tests/test_repasse_sla_backfill_pg.py`.
Em cada script o teste confere quatro coisas: ele escreve o esperado, a 2ª execução não muda nada,
o teto aborta sem escrever e o rollback devolve o estado anterior.

Todos seguem o mesmo formato:

- uma transação (`BEGIN … COMMIT`) com `SET LOCAL lock_timeout = '5s'`;
- `RAISE NOTICE` com a contagem antes e depois;
- teto com `RAISE EXCEPTION`: o erro aborta a transação e nada fica gravado.

Rodar sempre com `-v ON_ERROR_STOP=1`.

## Ordem e contagens esperadas

As contagens foram medidas em 19/10/2026, por volta das 17h BRT, em produção, só com SELECT dentro de `BEGIN READ ONLY … ROLLBACK`.

| # | Script | Esperado hoje | Teto | Backup / valor anterior | Rollback |
|---|---|---|---|---|---|
| R1 | `r1_eventos_repasse.sql` | **1.809** marcadores sem evento: 1.807 da auditoria mais os repasses novos do dia. Desses, **1.719** têm carimbo `metadata.handoff` que bate (±5 min) e ganham vendedor/segmento/motivo. Há 1.111 com `assigned_to`, e o resto fica com `vendedor_id` nulo. Nenhum `at` tem formato inválido. | 2.100 | não há (insert puro, `source='backfill'`) | `r1_rollback.sql` |
| R2 | `r2_first_response.sql` | **1.257** leads a preencher, 0 a corrigir e 0 divergentes. São 1.771 leads repassados, e `first_response_at` está 100% nulo. | 1.900 | `backup_r2_first_response_20261019` (lead_id, anterior, gravado) | `r2_rollback.sql` |
| R3 | `r3_deals_fechado_ganho.sql` | **30** deals, R$ 6.950,82, todos no funil "João - Reposição Atacado" (`79e35e6b-…`). Esse funil tem exatamente 1 etapa `fechado_ganho`: "Fechado Ganho", `02daf8a7-0096-4ca3-aec9-1a1748812c10`. | exato: 30 | `backup_r3_deals_20261019` (deal_id, stage_id/entered_stage_at anteriores, stage_id novo) | `r3_rollback.sql` |

A ordem é R1, depois R2, depois R3.

Os 26 marcadores de 27/04/2026, das 01:31 às 01:32 UTC, são todos do lead de teste
`16ef5c38-af18-4da6-aef5-58c6d79894e5` (telefone 5511900000002, sem nome). Eles foram mantidos
e entram no R1 como qualquer outro.

### O que cada um faz

- **R1.** Insere um evento `lead_events` com `event_type='repasse'` e `source='backfill'` para cada mensagem `role='system' AND content LIKE '[encaminhar\_humano] Lead encaminhado%'` que ainda não tem evento. Os campos ficam assim:
  - `occurred_at` = `created_at` da mensagem;
  - `dedupe_key='repasse:'||message_id`;
  - `metadata` = `{vendedor_id: leads.assigned_to::text, vendedor, segmento, motivo, conversation_id, message_id}`.

  `vendedor`, `segmento`, `motivo` e `new_value` só são preenchidos quando o `at` do carimbo está a até 5 min do marcador. O insert usa `ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING`.
- **R2.** Grava em `leads.first_response_at` a 1ª mensagem `sent_by='seller'` (sem reação), em qualquer conversa do lead, com `created_at >=` o 1º marcador do lead. É a mesma regra do trigger, e usa o marcador, não `lead_events`. Mexe em leads com o campo `NULL` e também nos que têm valor **posterior** ao da regra. Esse segundo caso aparece porque o trigger, ativo desde a migration, grava a próxima mensagem do vendedor num lead que já tinha sido respondido antes do deploy.

  O script aborta se achar um valor **anterior** à regra, ou um valor preenchido quando a regra não dá nenhum, porque nem o trigger nem o R2 gravam isso. Isso diverge do texto do plano ("aborta se o alvo já tiver valor"): seguido ao pé da letra, o script não poderia rodar depois do trigger e a 2ª execução seria um erro.
- **R3.** Pega os deals em `chamado_reposicao` com `closed_at` não nulo e `broadcast_leads.deal_moved_at > closed_at` e muda `stage_id` para a etapa `fechado_ganho` do mesmo `pipeline_id`, com `entered_stage_at = closed_at`. São dois UPDATEs, porque o gatilho `trg_update_deal_entered_stage_at` grava `now()` quando o `stage_id` muda.

  O script aborta em três casos: contagem ≠ esperado, pipeline sem exatamente 1 `fechado_ganho`, ou deals atualizados ≠ esperado. Com alvo vazio (já aplicado), ele não faz nada e não dá erro. O gatilho `trg_lead_events_deals_etapa` grava um evento `etapa` por deal, o que é esperado. O esperado só muda com novo OK, e se muda assim: `SET repasse.r3_esperado = 'N';` na mesma sessão, antes do script.

As tabelas de backup ficam em `public`, mas com RLS ligada e `REVOKE ALL` de `anon`/`authenticated`, então ficam fora da API.

## Como rodar (na VPS, um por vez)

```bash
ssh -i "C:\Users\rafae\.ssh\agente_crm" root@173.249.15.11
P=$(docker ps -q -f name=supabase_db | head -1)
# copiar o script para a VPS (scp) e então:
docker exec -i $P psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 < r1_eventos_repasse.sql
docker exec -i $P psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 < r2_first_response.sql
docker exec -i $P psql -U postgres -d postgres -X -v ON_ERROR_STOP=1 < r3_deals_fechado_ganho.sql
```

Confira os NOTICE. Por exemplo, o R1 deve imprimir `R1 marcadores sem evento: N` e depois `R1 inseridos: N | marcadores sem evento depois: 0`.

## SQL de aceite (spec, "Como testar em produção")

Depois do **R1** (B3), o resultado esperado é 0:

```sql
select count(*) from messages m
 where m.role='system' and m.content like '[encaminhar\_humano] Lead encaminhado%'
   and not exists (select 1 from lead_events e where e.dedupe_key='repasse:'||m.id);
```

Depois do **R2** (B5), o resultado esperado é 0. Também vale conferir à mão 5 leads, comparando o campo com a 1ª mensagem `seller` depois do repasse.

```sql
select count(*) from leads l
 where first_response_at is null
   and exists (select 1 from lead_events e where e.lead_id=l.id and e.event_type='repasse')
   and exists (select 1 from messages m where m.lead_id=l.id and m.sent_by='seller'
                 and coalesce(m.message_type,'')<>'reaction'
                 and m.created_at > (select min(occurred_at) from lead_events e2
                                      where e2.lead_id=l.id and e2.event_type='repasse'));
```

Depois do **R3** (B7), o resultado esperado é 0:

```sql
select count(*) from deals d join pipeline_stages s on s.id=d.stage_id
 where s.key='chamado_reposicao' and d.closed_at is not null;
```

Para o **B6**, `dashboard_kpis` de out/2026 deve ter `sla_samples > 0` e mediana igual à de `analytics.vw_resposta_closer` (±1 min).

## Rollback

Cada rollback é idempotente e roda numa transação com `lock_timeout` e teto.

| Script | O que faz |
|---|---|
| `r1_rollback.sql` | `DELETE FROM lead_events WHERE event_type='repasse' AND source='backfill'`. Os eventos gravados pelo código (`ia`/`button_flow`) ficam. |
| `r2_rollback.sql` | Volta `first_response_at` ao valor anterior do backup só onde o valor atual ainda é o que o R2 gravou. Os outros são contados como "mantidos". Depois apaga a tabela de backup. |
| `r3_rollback.sql` | Volta `stage_id` e `entered_stage_at` do backup só nos deals que ainda estão na etapa que o R3 pôs. Depois apaga a tabela de backup. O gatilho grava mais um evento `etapa` por deal. |

Os rollbacks são rodados com o mesmo comando, trocando o arquivo. Para desfazer a migration, use `rollback_migration.sql`.

## Testes (Postgres descartável)

```bash
REPASSE_PSQL='ssh -i C:/Users/rafae/.ssh/agente_crm -o BatchMode=yes root@173.249.15.11 docker exec -i crm-scratch-pg-7b143561 psql -U postgres -h localhost -d postgres' \
  python backend/tests/test_repasse_sla_backfill_pg.py
```

Os scripts fazem COMMIT de verdade. Por isso o teste semeia dados com o nome `Backfill 7b143561`
e limpa tudo antes e depois. Ele também se recusa a rodar se achar mais de 50 leads que não são
da semente.

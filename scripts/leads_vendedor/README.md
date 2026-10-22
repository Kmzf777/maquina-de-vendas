# scripts/leads_vendedor — backfills do cartão b67f1c6b

Cada parte edita só a sua seção.

## F2, F3, F4 (segmento, fase, origem)

Contagem em produção em 22/10/2026, só SELECT (`f2_/f3_/f4_contagem_producao.sql`, regra equivalente
sem as colunas novas). Teto = contagem + 10%, arredondado para cima; é o default de `\set teto` no
topo de cada script (para mudar: `-v teto=N`).

| Script | O quê | Hoje | Teto |
|---|---|---|---|
| `f2_segmento.sql` | `segmento := stage` quando stage é segmento e segmento é NULL: private_label 1.088, atacado 623, consumo 209, exportacao 30 | 1.950 | 2.145 |
| `f3_fase.sql` | stage-segmento → `qualificando` (1.950); `secretaria` → `triagem` (420); contato 3 / negociacao 3 / ja_chamado 2 → `qualificando` | 2.378 | 2.616 |
| `f4_origem.sql` | só onde `origem_cadastro='inbound'`: channel bling ou origem `bling_webhook` → `bling_import` (186); origem `reativacao_bling` → `reativacao_import` (1.207); status `ativo` → `active` (186, os mesmos do Bling) | 1.393 leads | 1.533 |

Rodar (psql do `supabase_db`): `psql -U postgres -X -v ON_ERROR_STOP=1 -f <script>`.
Backups: `public.backup_b67f_f2|f3|f4` (id, valor_anterior jsonb, gravado_em), com RLS ligado e
sem grant para anon/authenticated. Os rollbacks (`fN_rollback.sql`) só voltam linhas que ainda têm o
valor gravado pelo backfill e não apagam o backup.

Ordem:
1. migration `20261022b` → `f2_segmento.sql`.
2. `f3_fase.sql` (aborta se algum lead com stage-segmento não tiver o mesmo segmento, ou seja, se o F2 não rodou).
3. Aplicar `supabase/migrations/20261022f_stage_fase_check.sql` (CHECK de fase). O F3 imprime no fim os
   stages fora das fases; precisa sair vazio. Testado no scratch: a f passa depois do F3 e falha antes ("rodar F3 antes").
4. Push do código. Depois: migration `20261022c` → `f4_origem.sql`.

Desfazer: F3 antes do F2 (o `f2_rollback.sql` recusa enquanto houver lead na fase do F3). Se a migration f
já entrou, `ALTER TABLE public.leads DROP CONSTRAINT IF EXISTS leads_stage_fase_check;` antes do `f3_rollback.sql`.

Gatilhos de banco em `leads` (pg_trigger em produção, 22/10/2026):
- `trg_update_entered_stage_at` (BEFORE UPDATE): faz `entered_stage_at = now()` quando stage muda. Não grava
  evento nem move card, então não impede o F3. Mas zeraria o relógio do gatilho de automação `stage_stagnation`
  (`automation/triggers.py`); por isso o F3 devolve `entered_stage_at` ao valor de antes na mesma transação
  (e aborta se algum ficar diferente). O `f3_rollback.sql` faz o mesmo.
- `trg_lead_events_leads_entrada` (AFTER INSERT OR UPDATE OF ctwa_clid, gclid, gbraid, wbraid, fbclid,
  meta_ad_id, utm_source, utm_campaign): não dispara com stage, segmento, origem_cadastro ou status.
- Nenhuma publicação de replicação em `leads`. O F3 é UPDATE direto: as automações `stage_enter` do Python não rodam.

Relatório `relatorios/segmento_inferivel.sql` (só SELECT, requer a migration b): leads `pending` sem segmento
cujo segmento poderia vir do funil do deal, de `metadata.origem` (atacado/site-cafecanastra-atacado* → atacado,
terceirizacao → private_label) ou de `conversations.stage`. Nada disso é gravado. Em produção hoje (regra
equivalente): 981 sugerem atacado, 198 private_label, 13 com fontes em conflito.

Teste: `backend/tests/test_backfill_f2f3f4_b67f_pg.py` (com `B67F_PSQL`): roda, 2ª execução com
alterados=0, rollback devolve o estado (2×), teto pequeno estoura, F3 sem F2 aborta, relógio preservado,
F4 não gera `lead_events`, migration f passa depois do F3.

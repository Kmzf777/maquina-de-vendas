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

## F5, F7 (eventos), relatórios de qualificação/duplicados e rollback das migrations

Contagem em produção em 22/10/2026, só SELECT (`f5_/f7_contagem_producao.sql`, regra equivalente sem as
colunas/funções novas: "inbound" = não é o que o F4 marca como importado). Teto = contagem + 10%,
arredondado para cima; é o default de `\set teto` (para mudar: `-v teto=N`).

| Script | O quê | Hoje | Teto |
|---|---|---|---|
| `f5_entrada_organico.sql` | `entrada` "Orgânico" (source `inbound`, metadata `{canal, sem_rastreio}`, dedupe `entrada:lead:<id>:inicial`, igual ao gatilho da 20261022c) para lead criado desde 01/07/2026 BRT, `origem_cadastro='inbound'`, sem rastreio, sem `entrada`, não `ja_era_cliente` e com msg `role='user'` (172); mais a `entrada` dos leads com `meta_ad_id` sem nenhuma (7, todos "Meta Ads"/`ctwa`, out/2026). `occurred_at = leads.created_at` | 179 | 197 |
| `f7_qualificado.sql` | evento `qualificado` (dedupe `qualificado:<lead_id>`, metadata `criterio/segmento/b2b/motivo/vendedor_id`): 1º repasse não excluído de cada lead (1.289 leads; marcador `[encaminhar_humano] Lead encaminhado%`, `occurred_at` = do marcador; os 28 eventos `lead_events.repasse` são a fonte preferida de source/motivo/segmento/vendedor_id) + score `final_score>=5` não provisório sem repasse (1, `occurred_at = updated_at`) | 1.290 | 1.419 |

Notas:
- F5 roda DEPOIS da migration 20261022c e do F4 (sem o F4, os importados do Bling seriam "inbound" e ganhariam
  entrada "Orgânico"). O F5 é INSERT em `lead_events` (não há gatilho em `lead_events`). A estimativa da spec
  (~199) caiu para 172 porque 14 dos leads sem entrada são `ja_era_cliente`.
- F7 roda depois do F1 (vendedores) e do F2 (segmento), para `vendedor_id` e `segmento` saírem preenchidos.
  "Excluído" = o motivo (texto do marcador, motivo do evento `repasse` ou `metadata.handoff.motivo` quando o
  carimbo é do mesmo repasse, ±2 min) contém um dos `MOTIVOS_EXCLUIDOS` de `app/leads/qualificado.py`.
  Dos 1.804 leads com marcador, 515 só têm repasses excluídos (510 "IA temporariamente indisponível", 5
  escalonamento). A spec estimava "até 1.776". O score: 18 leads têm score ≥5 definitivo, 17 já entram pelo
  repasse. `b2b` = `fn_lead_b2b` na hora do backfill (o caminho ao vivo do repasse grava `null`). O score
  não exige `fn_lead_b2b` verdadeiro (o score só era gravado para lead B2B na época; o único lead está em `pending`).
- Backups `public.backup_b67f_f5|f7` guardam os `lead_events.id` inseridos (`valor_anterior` NULL). Os
  rollbacks apagam só esses ids (e só se ainda forem `entrada`/`qualificado`). Não apagam o backup.
- Índice usado no `on conflict`: `lead_events_dedupe_key_uidx` (único parcial, `where dedupe_key is not null`).

Relatórios (só SELECT, rodam hoje em produção, sem as migrations; `psql -X -A -F '|' -f <arquivo>`):
- `relatorios/qualificado_sem_repasse.sql`: cards na etapa `qualificado` sem repasse qualificado (hoje 145 de
  156; a spec citava 123) e leads só com `[qualificar_lead]` sem repasse qualificado (31).
- `relatorios/duplicados.sql`: mesmo `wa_id` com telefones diferentes (165 grupos), colisão nos últimos 10
  dígitos (189 grupos), `telefone_comercial` com máscara do Bling (793; 1 já é o phone de outro lead),
  leads do Bling sem telefone `bling-<id>` (166), `bling_contacts` com máscara (0), `leads.cnpj` duplicado
  (15 CNPJs), `bling_contacts` com CNPJ duplicado na mesma conta (0).
- `relatorios/human_control_sem_repasse.sql`: `human_control` sem nenhum marcador nem evento de repasse (252;
  a spec citava 248), com msgs do vendedor, carimbo e cards.

`rollback_migrations.sql`: desfaz as migrations f, e, d1, d, c, b, a (nessa ordem), numa transação, com as
definições de `defs_antes/` embutidas (cópia literal). Em produção rodar como `supabase_admin` (dono das views
analytics); as funções recriadas recebem `OWNER postgres` antes dos grants. Antes dele, se os backfills já
rodaram: `f7_rollback`, `f5_rollback`, `f6_rollback` (deals.assigned_to volta a text com o valor convertido),
`f3_rollback`. Some: `leads.segmento`, `leads.origem_cadastro`, `vendedores`, `bling_seller_map.vendedor_id`.
Testado no scratch: depois do rollback, `md5(prosrc)` e ACL de `dashboard_kpis`, `dashboard_funnel_conversion`,
`fn_lead_canal` (9 args), `fn_lead_events_leads_entrada` e `fn_lead_entrada_metadata`, e `md5(pg_get_viewdef)`,
comentário e ACL de `analytics.dim_lead/dim_vendedor/vw_leads` e `valeria_score_directory` iguais aos de
produção (a única diferença é o dono das views analytics, que no scratch já era `postgres`); 2ª execução não
muda nada; reaplicar a..f (2×) volta ao mesmo estado de antes do rollback.

Teste: `backend/tests/test_backfill_f5f7_b67f_pg.py` (com `B67F_PSQL`): roda, 2ª execução com alvo=0 e
alterados=0, rollback devolve o estado (2×), teto pequeno estoura sem gravar.

## F1, F6 (vendedores) e relatório de vendedores ambíguos

Contagem em produção em 22/10/2026, só SELECT (`f1_/f6_contagem_producao.sql`; o do F6 simula `vendedores`
e `fn_vendedor_id` com os 4 uuids e os nomes/apelidos normalizados, e o dono do funil do Arthur que o F1 grava).
Teto = contagem + 10%, arredondado para cima; é o default no topo de cada script.

| Script | O quê | Hoje | Teto |
|---|---|---|---|
| `f1_vendedores.sql` | `vendedores` a partir de `auth.users` (4: João Brás e Arthur ativos; Rafael `rafael@cafecanastra.com` e Comercial 2 inativos — em `auth.users` está `Comercial2@cafecanastra.com`, gravado em minúsculo); `bling_seller_map.vendedor_id` (2 linhas do João: default e secundaria); insert Arthur → vendedor Bling 5845108828 na conta `default` (existe em `bling_sellers` como "Arthur Silva Boaventura"); dono do funil "Arthur - Exportação" (4a0c9f7f-…, hoje NULL) | 4 + 2 + 1 + 1 = 8 | `teto` 9 |
| `f6_vendedor.sql` (leads) | `leads.assigned_to` e `metadata.handoff.vendedor_id` := `fn_vendedor_id(handoff.vendedor)` só em lead sem `assigned_to` e sem `handoff.vendedor_id`: João 524, Arthur 20 | 544 | `teto_leads` 599 |
| `f6_vendedor.sql` (deals) | `deals.assigned_to` (só NULL, fora do funil Blacklist): dono do funil 3.301 (João 3.271 nos 6 funis dele, Arthur 30 depois do F1) + funil sem dono pelo `assigned_to` que o lead já tinha 1 (João, em Importação Leads Frios) | 3.302 | `teto_deals` 3.633 |

Ficam fora do F6 (vão para `relatorios/vendedores_ambiguos.sql`): "Vendedor" 61 (nome não resolve) e "Joao Bras" em
lead de consumo 15 / secretaria 5 / exportacao 2 = 22 (vendedor não atende o segmento: `leads.segmento`,
`handoff.segmento` ou `stage` em consumo/secretaria/exportacao fora de `vendedores.segmentos`).

Notas:
- Ordem: migration `20261022a` → `f1_vendedores.sql` (antes do push). `f6_vendedor.sql` depois do push (F4–F7)
  e depois do F1 (e do F2/F3, para o filtro de segmento enxergar `leads.segmento`).
- Funil **Blacklist** (decisão de 22/10, caminho conservador): o F6 não preenche nenhum deal dele, nem pelo dono
  do funil nem pelo vendedor do lead. Hoje são 177 deals sem vendedor lá, 67 deles com lead do João (seriam o
  fallback pelo lead); todos vão para a seção `blacklist` de `relatorios/vendedores_ambiguos.sql`.
- Diferença da spec (3.278 + 48): os funis do João têm hoje 3.271 deals; o fallback pelo lead, fora da Blacklist,
  dá 1. O fallback usa só o `assigned_to` que o lead já tinha: deals de funil sem dono cujo lead só ganha vendedor
  no próprio F6 (seriam +354) ficam NULL. Isso mantém a 2ª execução com alvo=0.
- Leads: a spec citava 508 + 20; hoje são 524 + 20 (repasses novos desde 20/10).
- Backups: `public.backup_b67f_f1` (id text `<tabela>:<chave>`; valor_anterior com `existia`, o valor anterior e
  `novo`) e `public.backup_b67f_f6` (id do lead ou do deal; valor_anterior com `tabela`, `assigned_to`, `handoff`
  e `novo`). RLS ligado e sem grant para anon/authenticated.
- Desfazer: `f6_rollback.sql` e depois `f1_rollback.sql`. Só voltam valores que ainda são os gravados pelo
  backfill (`novo`); o F6 restaura só a chave `handoff.vendedor_id` (ausente → removida; null → null). O
  `f1_rollback` apaga os vendedores criados e aborta pela FK se algum deal ainda apontar para eles. Não apagam o backup.
- Gatilhos: o F6 só atualiza `assigned_to`/`metadata` (leads) e `assigned_to` (deals); nenhum gatilho reage.

Teste: `backend/tests/test_backfill_f1f6_b67f_pg.py` (com `B67F_PSQL`; usa o banco próprio `b67f1c6b_f16` no
container scratch, clonado do schema do `postgres` com `pg_dump -s`, porque os scripts fazem COMMIT): roda,
2ª execução com alvo=0 e sem mudança, rollback devolve o estado (2×), teto pequeno estoura sem gravar, dono de
funil já preenchido não é tocado, deal da Blacklist não é tocado (nem com dono no funil), sem o vendedor Bling do Arthur não insere o mapa, relatório lista os ambíguos.

# Repasse ao closer, SLA, 1ª resposta, disparo e custo por closer — design

Cartão 7b143561 ("CRM Canastra: corrigir bugs de integridade de dados"), recortado em 15/10/2026 para os itens B3, B5, B6, B7 e B11. Os itens de vendas (B1, B10, B12) e de leads/vendedor (B2, B4, B8, B9) viraram dois cartões próprios no quadro.
Branch: `agente/7b143561`, base `origin/master` 52906ac4.

## Problema

Nas palavras do cartão: "corrigir na origem os defeitos de gravação que distorcem os números do CRM". Quando pediu a revisão, o Rafael disse: "entenda o por trás de todos os dados do crm".

A auditoria somente leitura de 15/10/2026 em produção mostrou isto na parte deste recorte:

- **Repasse sem histórico (B3).** São 1.807 mensagens `[encaminhar_humano] Lead encaminhado…`, mas nenhum evento em `lead_events`. Os dois caminhos de repasse sobrescrevem `leads.metadata.handoff`:
  - `agent/tools.py:855-868` grava `at` em BRT;
  - `button_flow/effects.py:520-533` grava `at` em UTC.
  - Nos 13 leads com 2 repasses, o 1º sumiu do carimbo. Esse 1º repasse é o "foi ao closer" pela D3.
- **SLA do dashboard sem amostra desde julho (B6).** `dashboard_kpis` (`20260712_dashboard_rpcs.sql:127-138`) procura a resposta do vendedor na mesma conversa do repasse. Só que 1.738 dos marcadores estão na conversa da VALERIA, e 71% das respostas estão na conversa do JOÃO. O resultado é `sla_samples = 0` em jul, ago, set e out. Medido pela regra D4, a mediana foi de 104 min úteis em jul e 31 em out.
- **Outros pontos do SLA:**
  - `frontend/src/lib/sla-rounds.ts:19` fecha a rodada também com resposta da IA (`agent`).
  - O watchdog (`watchdog/service.py:509`) usa 08h–20h corrido, em vez do horário do vendedor.
  - O modelo enviado à mão pelo vendedor (`api/conversations/[id]/send-template/route.ts:144`) é gravado como `broadcast`, então nunca conta como resposta. Já são 3.111 mensagens assim no canal do JOÃO.
- **`leads.first_response_at` nunca é gravado (B5).** Está 0 de 5.711, e as telas medem a partir de `leads.created_at`.
- **Disparo move card fechado (B7).** `broadcast/worker.py:1832-1866` move todos os deals do lead no funil-alvo, inclusive os terminais, e grava `deal_moved_at`. Em 29/07, 30 deals em Fechado Ganho do funil João–Reposição Atacado foram para `chamado_reposicao` e continuam com `closed_at`. Somam R$ 6.951; 27 desses leads já têm outro card aberto. A tela mostra "✓ Movido" como se fosse conversão (`broadcast-detail.tsx:726-735`).
- **Custo por closer errado (B11).** `campaigns/traffic_report.py:94,652-670` conta deals com `order_index >=` o de `qualificado` no mesmo funil. Isso inclui `perdido`/`encerrado`, que respondem por cerca de metade, e ignora os 5 funis do João, que não têm essa key. Exemplo de set/26: 104 "closers" contra 469 leads repassados.

## Decisões do Rafael (15–19/10)

| Tema | Decisão |
|---|---|
| Escopo | Este cartão fica só com repasse, SLA, 1ª resposta, disparo e closer (B3, B5, B6, B7, B11). |
| Mensagem digitada no celular | Fora do escopo: João e Arthur respondem só pelo CRM. Fica documentado como limitação. |
| Modelo enviado à mão pelo vendedor | Passa a contar como resposta do vendedor (`sent_by='seller'`, `metadata.template=true`). As 3.111 mensagens antigas ficam como estão. |
| 30 deals tirados de Fechado Ganho | Voltam para Fechado Ganho, com aprovação na hora de rodar. |
| "1ª resposta" nas telas | O relógio começa no 1º repasse e conta em horário comercial do vendedor. Lead sem repasse mostra "—". |

## Definições aplicadas (do cartão)

- **D3, repasse ao closer:** cada mensagem de sistema `[encaminhar_humano] Lead encaminhado%` é um repasse. "Foi ao closer" é o 1º repasse do lead.
- **D4, closer assumiu:** é a 1ª mensagem humana do vendedor (`sent_by='seller'`) ao lead depois do 1º repasse, em qualquer conversa do lead. O tempo conta no horário de `sla_seller_config` (+ `sla_overrides`); sem configuração, vale 10h–16h, seg–sex. Resposta da IA e disparo automático não contam. Reação (`message_type='reaction'`) também não conta.
- **D6:** `leads.first_response_at` = o instante da D4.

## O que muda

### 1. Evento de repasse (B3)

- Novo helper `backend/app/leads/repasse.py::registrar_repasse(lead_id, conversation_id, message_id, occurred_at, source, vendedor_id, vendedor, segmento, motivo)`. Ele insere em `lead_events`:
  - `event_type='repasse'`;
  - `source` = `ia` ou `button_flow`;
  - `occurred_at` = o `created_at` da mensagem;
  - `dedupe_key='repasse:'||message_id`;
  - `metadata{vendedor_id, vendedor, segmento, motivo, conversation_id, message_id}`.
  - O insert é **fail-soft**: se falhar, gera um log e o repasse segue.
- É chamado em `_t_encaminhar_humano` (`tools.py`) e em `_aplicar_handoff` (`effects.py`), logo depois de gravar a mensagem e o carimbo. A mensagem e o `metadata.handoff` continuam como estão, porque o follow-up, o buffer, o watchdog e as conversões os leem.
- `effects.py` passa a gravar `at` em BRT, igual a `tools.py`. Ambos são ISO com offset, então nenhum leitor quebra.
- O tipo de evento se chama `repasse`, em português, como `entrada`, `etapa`, `venda` e `disparo`. A coluna não tem CHECK, então a migration não mexe em constraint.
- `frontend/src/components/leads/lead-timeline.tsx` ganha o card "Repassado ao closer", com vendedor, segmento e motivo.

### 2. Horário comercial e tempo até o closer assumir (B5/B6)

Migration `supabase/migrations/20261019_repasse_sla.sql`. É aditiva, aplicada à mão antes do push.

- **Função `public.fn_minutos_uteis_vendedor(p_user uuid, p_de timestamptz, p_ate timestamptz) returns numeric`.** Usa `sla_seller_config` ativo do usuário, com padrão 600–960 e dias 1–5, desconta os dias em `sla_overrides` e calcula em America/Sao_Paulo. É a mesma conta de `analytics.vw_resposta_closer`, agora versionada no ValerIA.
- **View `public.vw_repasse_resposta`** (`security_invoker`), uma linha por lead com repasse:

  | Coluna | Origem |
  |---|---|
  | `lead_id` | lead |
  | `repasse_em` | min `occurred_at` dos eventos `repasse` |
  | `vendedor_id` | do 1º evento; se vazio, `leads.assigned_to` |
  | `primeira_resposta_em` | `leads.first_response_at` |
  | `minutos_uteis` | conta até a resposta |
  | `minutos_uteis_em_aberto` | conta até agora, quando ainda não respondeu |
  | `respondeu` | se há resposta |

- **Trigger `trg_leads_first_response`** (AFTER INSERT em `messages`). Quando chega uma mensagem com `sent_by='seller'` e `coalesce(message_type,'') <> 'reaction'`, faz `UPDATE leads SET first_response_at = NEW.created_at` somente se `first_response_at IS NULL` e existir evento `repasse` do lead com `occurred_at <= NEW.created_at`. Não depende da conversa. Tem `EXCEPTION WHEN others` com `RAISE WARNING`, para nunca bloquear o insert da mensagem.
- **`dashboard_kpis` (`CREATE OR REPLACE`, mesma assinatura e mesmas chaves de saída):**
  - `handoffs` = leads cujo 1º repasse caiu no período (D3);
  - o bloco de SLA lê `vw_repasse_resposta`: amostras = respondidos com 1º repasse no período; mediana e média em `minutos_uteis`; meta de 20 min.
  - O resto da função não muda. Leads novos e qualificação são do cartão "leads e vendedor".
- **Grants:** `GRANT EXECUTE` na função e `GRANT SELECT` na view para `authenticated`, `service_role` e `consulta_ro`.

### 3. Modelo enviado pelo vendedor (decisão A)

- `send-template/route.ts` passa a gravar `sent_by='seller'` e `metadata{template:true, template_name}`. Quando a Meta devolver o id, grava também `wamid`.
- Os disparos em massa (`broadcast/worker.py`) continuam com `broadcast`.

### 4. Telas e watchdog

- `sla-rounds.ts:19`: só `seller` fecha a rodada. `agent` sai, com teste no vitest existente.
- `kanban-metrics-bar.tsx`, `conversas/tabs/crm-metricas-tab.tsx`, `leads/lead-detail-modal.tsx` e `lib/lead-overview.ts`: o "tempo até a 1ª resposta" passa a vir de `vw_repasse_resposta.minutos_uteis`. Lead sem repasse mostra "—", e `leads.created_at` deixa de ser usado como início.
- `watchdog/service.py::check_handoff_sla`:
  - considera respondida a conversa cujo lead teve mensagem `seller` em **qualquer** conversa depois da última mensagem do cliente;
  - mede os 20 min dentro do horário do vendedor (`sla_seller_config`), não 08h–20h corrido.
  - O alerta continua oculto no CRM, como hoje (o pop-up foi desligado em 032e022a).

### 5. Disparo não mexe em card fechado (B7)

- `broadcast/worker.py`: o UPDATE de etapa exclui deals com `closed_at` não nulo ou etapa com key em (`fechado_ganho`, `fechado_perdido`, `perdido`, `encerrado`).
  - Se todos os deals do lead no funil forem terminais, cria um card novo na etapa-alvo. Isso usa o mesmo caminho de "lead sem deal" que já existe (`worker.py:1832-1857`).
  - `deal_moved_at` só é gravado quando algum deal realmente mudou ou foi criado.
- `broadcast-detail.tsx:726-735`: o rótulo vira "Card movido no envio" ou "Card não movido", em cinza, sem o verde/vermelho de conversão. O desempenho do disparo continua por resposta (`first_replied_at`), que já está na tela.

### 6. Custo por closer (B11)

- `traffic_report.py::_closer_ids`: closer = lead com evento `repasse` cujo `occurred_at` cai no período do relatório (D3, 1º repasse do lead).
- `custo_closer` e "Foi pro closer" (`campaign-kpis.tsx:31`) seguem essa mesma regra.
- `_CLOSER_STAGE_KEY` sai.
- A coluna "estágio" do drill-down (`:990-1006`) não muda.

### 7. Backfills (um por vez, só com o OK do Rafael na hora)

Os três rodam numa transação. Cada um tem teto com `RAISE EXCEPTION`, guarda o valor anterior e tem rollback. Ficam em `scripts/repasse_sla/` como SQL, e cada script imprime a contagem antes e depois.

| # | O quê | Esperado (15–19/10) | Teto | Valor anterior | Rollback |
|---|---|---|---|---|---|
| R1 | Eventos `repasse` a partir das mensagens `role='system' AND content LIKE '[encaminhar\_humano] Lead encaminhado%'`, `source='backfill'`. Metadata: `vendedor_id` = `leads.assigned_to` atual; `vendedor`/`segmento`/`motivo` do `metadata.handoff` só quando o `at` do carimbo bate com a mensagem (±5 min); `ON CONFLICT (dedupe_key) DO NOTHING` | ~1.807 (inclui 26 de um lead de teste de 27/04, mantidos e listados) | 2.100 | não há (insert puro) | `DELETE FROM lead_events WHERE event_type='repasse' AND source='backfill'` |
| R2 | `leads.first_response_at` = 1ª mensagem `seller` (sem reação) depois do 1º repasse, só onde `IS NULL` | ~1.240 | 1.900 | coluna era 100% nula (conferido no script: aborta se encontrar valor) | `UPDATE leads SET first_response_at=NULL WHERE id IN (lista gravada em scripts/repasse_sla/r2_ids.csv)` |
| R3 | 30 deals em `chamado_reposicao` com `closed_at` não nulo e `broadcast_leads.deal_moved_at` posterior ao `closed_at` → `stage_id` = etapa `fechado_ganho` do mesmo funil | 30 | 30 (exato; aborta se ≠) | tabela `backup_r3_deals_20261019(deal_id, stage_id_anterior, entered_stage_at_anterior)` | `UPDATE deals d SET stage_id=b.stage_id_anterior, entered_stage_at=b.entered_stage_at_anterior FROM backup… b WHERE d.id=b.deal_id` |

O R3 gera eventos `etapa` pelo gatilho existente (`trg_lead_events_deals_etapa`), o que é esperado. A ordem é R1, depois R2 (que depende de R1), depois R3.

## Onde

- **Repo:** `ValerIA`, branch `agente/7b143561`.
- **Backend** (`canastra_api` e `canastra_worker`): `agent/tools.py`, `button_flow/effects.py`, `leads/repasse.py` (novo), `broadcast/worker.py`, `campaigns/traffic_report.py`, `watchdog/service.py`.
- **Frontend** (`crm_crm`): `send-template/route.ts`, `sla-rounds.ts`, `lead-timeline.tsx`, `kanban-metrics-bar.tsx`, `crm-metricas-tab.tsx`, `lead-detail-modal.tsx`, `lead-overview.ts`, `broadcast-detail.tsx`, `campaign-kpis.tsx`.
- **Banco:** `supabase/migrations/20261019_repasse_sla.sql` (função, view, trigger, `dashboard_kpis`), aplicada à mão.
- **Não muda:** etapas, keys e `order_index` dos funis do João; o texto das mensagens de repasse; `metadata.handoff`; as views `analytics`.

## Como testar em modo teste

Tudo no worktree `ValerIA-agente-7b143561`, antes de qualquer push.

1. **TDD em pytest** (`backend/tests/`):
   - `registrar_repasse` grava o evento com metadata e `dedupe_key`; uma falha no insert não derruba o repasse. Vale para os dois caminhos (`_t_encaminhar_humano`, `_aplicar_handoff`), usando os dublês que esses testes já usam.
   - O worker de disparo não move deal `fechado_ganho`, `perdido` nem com `closed_at`, e cria card quando só há terminais. `deal_moved_at` não é gravado se nada mudou.
   - `_closer_ids` conta lead repassado em funil do João e não conta deal em `perdido` sem repasse.
   - `check_handoff_sla` não alerta quando a resposta foi em outra conversa do lead e respeita o horário do vendedor.
2. **Postgres descartável na VPS.** Um container temporário `crm-scratch-pg-7b143561`, sem volume e removido no fim, com o schema de produção (`pg_dump --schema-only`, sem dados) mais a migration nova. Os testes seguem o padrão de `backend/tests/test_cs_p3_timeline_pg.py`, com rollback por cenário:
   - repasse na conversa da IA e resposta `seller` na conversa do JOÃO preenchem `first_response_at` e `vw_repasse_resposta.minutos_uteis`;
   - reação, `agent`, `followup` e `broadcast` não preenchem;
   - resposta antes do repasse não conta;
   - `fn_minutos_uteis_vendedor` com virada de dia, fim de semana e override;
   - `dashboard_kpis` devolve `sla_samples > 0` com as mesmas chaves de saída;
   - os scripts R1, R2 e R3 rodados contra dados semeados respeitam o teto, são idempotentes e o rollback funciona.
3. **Vitest:** `sla-rounds` (agent não fecha), `lead-timeline` (card de repasse), rótulo do `broadcast-detail`, rota `send-template` (grava `seller` + `metadata.template`).
4. **Ensaio dos números (só leitura, em produção, via SELECT):** rodar o corpo novo de `dashboard_kpis` e da view como CTE para jul–out e comparar com `analytics.vw_resposta_closer`. Esperado: mediana de out ≈ 31 min úteis e amostra ≈ número de respondidos.
5. `npm run build` do frontend e a suíte completa do backend passando.

**Prints:** em modo teste não há CRM rodando com este código, então os prints são feitos em produção, depois da publicação.

## Como publicar (só depois do [Liberar produção])

1. **Pré-checagem:** `docker service ls`, `docker service logs --since 1h canastra_api`, `pm2 ls`. Conferir que `origin/master` não andou; se andou, `git pull origin master` no branch e rodar os testes de novo.
2. **Migration à mão**, pelo `psql` do container `supabase_db`, antes do push: `20261019_repasse_sla.sql` (`SET LOCAL lock_timeout='5s'`, idempotente). Depois, recarregar o cache do PostgREST com SIGUSR1 (o NOTIFY é ignorado nesta VPS) e conferir que a função, a view e o trigger existem.
3. **Merge e push:** merge de `agente/7b143561` em `master` e `git push origin agente/7b143561:master`. O GitHub Actions faz o deploy de `crm_crm`, `canastra_api` e `canastra_worker`. Acompanhar o job e os logs até os serviços estabilizarem.
4. **Backfills R1 → R2 → R3**, um por vez, cada um só depois do seu OK no Discord com a contagem prévia. Depois de cada um, rodar o SQL de aceite.
5. **Voltar atrás:**
   - código: `git revert` do merge e push (sem force), que redeploya a versão anterior;
   - migration: `DROP TRIGGER trg_leads_first_response`, `DROP VIEW vw_repasse_resposta`, `DROP FUNCTION fn_minutos_uteis_vendedor` e recriar `dashboard_kpis` a partir de `20260712_dashboard_rpcs.sql`, num SQL de rollback que vai junto na pasta `scripts/repasse_sla/`;
   - backfills: o rollback de cada linha da tabela acima.

## Como testar em produção

Nada com efeito externo. Não se envia mensagem a cliente, não se cria disparo e não se mexe no Bling.

- **SQL de aceite:**
  - B3: `select count(*) from messages m where m.role='system' and m.content like '[encaminhar\_humano] Lead encaminhado%' and not exists (select 1 from lead_events e where e.dedupe_key='repasse:'||m.id);` → 0.
  - B5: `select count(*) from leads l where first_response_at is null and exists (select 1 from lead_events e where e.lead_id=l.id and e.event_type='repasse') and exists (select 1 from messages m where m.lead_id=l.id and m.sent_by='seller' and coalesce(m.message_type,'')<>'reaction' and m.created_at > (select min(occurred_at) from lead_events e2 where e2.lead_id=l.id and e2.event_type='repasse'));` → 0. Amostra manual de 5 leads: o campo bate com a 1ª mensagem `seller` depois do repasse.
  - B6: `dashboard_kpis` de out/2026 com `sla_samples > 0` e mediana igual à de `analytics.vw_resposta_closer` (±1 min).
  - B7: `select count(*) from deals d join pipeline_stages s on s.id=d.stage_id where s.key='chamado_reposicao' and d.closed_at is not null;` → 0. Daqui para frente, nenhum evento `etapa` saindo de etapa terminal coincide com `broadcast_leads.deal_moved_at`.
  - B11: `_closer_ids` de set/26 = número de leads com 1º repasse em set/26 (~469).
- **Fluxo real e seguro:** o repasse e o modelo passam a ser conferidos no primeiro caso que acontecer naturalmente depois do deploy, olhando o evento `repasse` e `sent_by='seller'` com `metadata.template`. Não se provoca repasse em lead real.
- **Prints** (`print-frontend.mjs`, usuário de teste): dashboard (card de SLA preenchido), linha do tempo de um lead repassado, Kanban com o tempo até a 1ª resposta, detalhe de um disparo com o rótulo novo, e /trafego com "Foi pro closer".

## Mudanças para o glossário do agente de consulta (a entregar ao Rafael)

O central-claude não é editado. A lista vai no fim da entrega:

- **D6:** `leads.first_response_at` passa a ser preenchido (1ª resposta `seller` depois do 1º repasse). O glossário pode deixar de dizer "nunca use".
- **Novo evento `lead_events.event_type='repasse'`,** com vendedor, segmento e motivo. As views `vw_repasses` e `vw_resposta_closer` podem passar a lê-lo.
- **`public.vw_repasse_resposta` e `public.fn_minutos_uteis_vendedor`** existem e precisam de `GRANT SELECT`/`EXECUTE` ao `consulta_ro`. O grant entra na migration, porque o default ACL não cobre objeto novo.
- **Modelo enviado pelo vendedor** passa a ser `sent_by='seller'` com `metadata.template=true`, e conta como resposta do closer daqui para frente.
- **`broadcast_leads.deal_moved_at`** significa "card movido no envio", não conversão.

## Fora do escopo

- Mensagens digitadas no celular do vendedor (Evolution `fromMe` e ecos da Meta em coexistência). João e Arthur respondem só pelo CRM. O CRM continua cego a respostas fora dele.
- Reclassificar as 3.111 mensagens antigas de modelo.
- Vendas, receita, frete e cancelados (cartão "vendas e receita").
- Segmento, origem, qualificação e cadastro de vendedores (cartão "leads e vendedor"). Por isso o `vendedor_id` do evento usa `leads.assigned_to`, e 590 repasses antigos ficam sem vendedor.
- Leads novos e taxa de qualificação do dashboard.
- Alterar as views `analytics` (só a lista para o glossário).
- Deals duplicados, `closed_at` incoerente fora dos 30, Blacklist sem key.
- A migration `20260909_broadcast_marketing_capped` não aplicada: fica só registrada aqui como achado.

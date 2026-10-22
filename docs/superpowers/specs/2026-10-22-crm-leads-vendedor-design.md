# CRM Canastra: leads e vendedor (segmento, origem, qualificação e cadastro único de vendedores)

Cartão b67f1c6b. Desmembrado do 7b143561, itens B2, B4, B8 e B9. Branch `agente/b67f1c6b`, partindo de `origin/master` c8f04a7b.
Os números abaixo são de produção em 20 a 22/10/2026 e foram levantados só com SELECT. Na execução, toda contagem é refeita antes de gravar.

## O problema

As palavras do cartão: "Roteamento só por `segmento`, sem valor fora do enum; todo vendedor resolve para uma linha de `vendedores`; 'leads novos' = D1; uma única taxa de qualificação."

Hoje:

- **Fase e segmento estão misturados.** `leads.stage` guarda as duas coisas ao mesmo tempo, e o roteamento do repasse lê esse campo. Resultado: 43 leads "consumo" estão no funil Valeria-Atacado e 817 "pending" estão em João-Reposição Atacado.
- **O vendedor não tem chave.** Ele aparece como e-mail em `sales`, uuid em `leads.assigned_to`, nulo em `deals.assigned_to` e texto do LLM no repasse ("Joao Bras" 1.024, "João Brás" 226, "Vendedor" 441).
- **Exportação não chega ao Arthur.** O repasse por texto sempre envia o cartão do João: 21 dos 30 leads de exportação receberam esse cartão. O funil "Arthur - Exportação" não tem dono.
- **"Leads novos" conta errado.** Entram 1.391 importados (184 do Bling e 1.207 da reativação), e ficam de fora os leads orgânicos sem rastreio (40 a 50 por mês).
- **A taxa de qualificação está errada.** Ela é calculada como mensagens `[qualificar_lead]` ÷ conversas da IA, o que dá 18,2% em outubro. Não segue a D2 e ignora o bot de botões.

## Decisões

| # | Decisão | Origem |
|---|---|---|
| D1 | Lead de marketing = 1ª `entrada` do lead no período, sem importados e sem `ja_era_cliente=true` | 13/10 |
| D1b | Lead orgânico sem rastreio ganha `entrada` com canal "Orgânico", mas só se foi criado pelo WhatsApp (inbound) | Rafael, 21/10 (A) |
| D2 | Qualificado: todo repasse conta, exceto os motivos de falha (IA indisponível, bot de recuperação, escalonamento — `_MOTIVOS_EXCLUIDOS`); também conta B2B com `final_score>=5` definitivo. "Morno" não conta | Rafael, 21/10 (A) |
| D8 | Tabela `public.vendedores` é o cadastro único. `deals.assigned_to` vira uuid escolhido em lista | 13/10 |
| D8b | Vendedores ativos: João (atacado e private label) e Arthur (exportação). Rafael e Comercial 2 ficam inativos, só para resolver o histórico | padrão desta spec |
| D8c | Exportação é repassada ao Arthur com o cartão do **fixo (34) 3226-2600**, que fica fora do CRM. O Arthur vira dono do funil "Arthur - Exportação" | Rafael, 22/10 (B) |
| D9 | B2B = segmento atacado/private_label, OU deal em funil Atacado/PL, OU CNPJ no Bling (via `lead_bling_contacts`). Ter score não basta | 13/10 |
| D11 | `leads.segmento` ∈ {atacado, private_label, consumo, exportacao} ou NULL (= ainda não sabe). "secretaria" deixa de ser segmento e vira a fase `triagem` | Rafael, 21/10 (A) |

Padrões que esta spec adota (mude na aprovação se discordar):

- Status dos importados passa a ser `active`. Se fosse `imported`, entraria na lista de disparo.
- `sales.sold_by` e `quotes.created_by` continuam em e-mail. O escopo e o RLS dependem disso, e o resolvedor casa o e-mail com `vendedores`.
- `conversations.stage` não muda, porque continua escolhendo o prompt da Valeria. `deals.stage` (texto legado) e `deals.category` ficam fora.
- Os 123 cards em `qualificado` sem repasse e os 31 leads que só têm a mensagem não mudam de etapa: só entram no relatório.

## O que muda

### 1. Cadastro de vendedores (B2)

- **Migration.**
  - Cria `public.vendedores(id uuid PK → auth.users, email text unique minúsculo, nome, apelidos text[], segmentos text[], atende_no_crm bool, ativo bool, timestamps)`.
  - `bling_seller_map` ganha `vendedor_id`.
  - Cria `fn_vendedor_id(text) → uuid`, que aceita uuid, e-mail ou nome/apelido (unaccent, minúsculo). Devolve NULL quando não casa ou quando casa com mais de um.
  - `deals.assigned_to` passa de `text` para `uuid` com FK. Hoje 0 dos 5.452 está preenchido e nenhuma view depende dele.
- **Backend.**
  - Novo `app/vendedores/service.py` com `resolver_vendedor(chave)`, `vendedor_do_segmento(segmento)` e `nome(id)`, com cache.
  - `vendor_user_id_for_segment` passa a ler `vendedores.segmentos` e perde o uuid do João escrito no código.
  - O repasse (`_t_encaminhar_humano`, `effects._aplicar_handoff` e os 8 repasses com "Joao Bras" fixo) grava `metadata.handoff.vendedor_id` como chave e `vendedor` como rótulo tirado da tabela.
  - `_vendedor_da_ponte` resolve pelo id; o primeiro nome fica só como reserva.
  - `automation/variables._fill_seller_var` lê `vendedores`. Hoje lê `team_users`, que não existe, e por isso `{{vendedor}}` está quebrado.
- **Exportação (D8c).**
  - Quando o segmento é `exportacao`, `_t_encaminhar_humano` envia o cartão `EXPORTACAO_NAME/EXPORTACAO_PHONE` (fixo), e não o do João.
  - A despedida cita o Arthur. `assigned_to` recebe o uuid do Arthur e o card vai para "Arthur - Exportação".
  - Como o Arthur atende fora do CRM (`atende_no_crm=false`), o alerta de SLA (`watchdog.check_handoff_sla`) não dispara para ele. O tempo até o closer o mostra como "fora do CRM", e não como atraso.
- **Frontend.**
  - Nova rota `api/vendedores`.
  - Lista de seleção no lugar do texto livre em `deal-detail-sidebar.tsx`, `lead-detail-modal.tsx` e `crm-perfil-tab.tsx`. Hoje, digitar um nome em `leads.assigned_to` dá erro.
  - `deal-card.tsx` mostra o nome a partir do id.

### 2. Segmento separado da fase (B9)

- **Migration.**
  - `leads.segmento text CHECK (segmento IN ('atacado','private_label','consumo','exportacao'))`, com índice.
  - `fn_lead_b2b(lead_id) → boolean` (D9).
  - CHECK de fase em `leads.stage`: `pending`, `novo`, `triagem`, `qualificando` e `perdido`. Entra **depois** do backfill F3.
- **Backend.**
  - `apply_stage_transition` grava `leads.segmento`. Quando há segmento, a fase vira `qualificando`.
  - `conversations.stage` continua recebendo o segmento, como hoje.
  - Os pontos que leem o segmento passam a usar `segmento`:
    - `vendor_user_id_for_segment`;
    - `move_deal_to_vendor_pipeline`;
    - `create_deal(category=)`;
    - `mark_deal_qualificado`;
    - `_perdido_target_for_category`;
    - `agent/summary.py`;
    - `button_flow/effects.py`;
    - o portão do score em `tools.py`.
  - Os gravadores de fase passam a usar só fases válidas:
    - `reset_lead`: de 'secretaria' para 'triagem';
    - a criação via frontend: de 'secretaria' para 'triagem';
    - o Bling: continua 'novo';
    - `registrar_sem_interesse_atual`: continua 'perdido'.
  - Roteamento: segmento atacado ou private_label vai para o João, exportacao vai para o Arthur, consumo e NULL não vão para vendedor.
  - O que acontece com um lead sem segmento no momento do repasse: o card não é movido para funil de vendedor, e o repasse grava o vendedor que o LLM indicou e o sistema resolveu (resolvedor). Se ele não resolver, grava João, que é a regra de hoje. Os funis do João não mudam (etapas, keys e order_index ficam iguais, conforme o contrato 20260910).
- **Automação.**
  - `move_stage` aceita só fase válida, e o rótulo vira "Mover fase".
  - `node_registry` separa `fase_lead` de `segmento_lead`.
  - A ativação de campanha recusa valor fora da lista. Hoje só 1 nó (em rascunho) usa valor de segmento.
- **Frontend.**
  - `AGENT_STAGES`, o kanban de `qualificacao`, as abas de `conversas` e `api/conversations` (filtro), o filtro de `leads`, a cor do `chat-header` e `lead-overview` passam a ler `segmento`.
  - "Secretaria" aparece como "Em triagem".

### 3. Origem do lead (B8)

- **Migration.**
  - `leads.origem_cadastro text CHECK IN ('inbound','manual','bling_import','reativacao_import','csv_import') DEFAULT 'inbound'`.
  - `fn_lead_canal` ganha `p_origem` e a regra "Bling" (DROP + CREATE na mesma transação, reaplicando os grants; quem chama a função também é ajustado).
  - O gatilho de `entrada` passa a gravar, no INSERT de lead `inbound` sem rastreio, uma `entrada` com canal "Orgânico" (source `inbound`). Se o rastreio chegar depois, a fusão de 30 minutos que já existe atualiza o canal.
  - Corrige o caso "só `meta_ad_id`, sem entrada", que hoje não grava nada (7 leads em outubro).
- **Backend.**
  - `bling/contacts.py` (criação de lead a partir de contato) grava `status 'active'` e `origem_cadastro 'bling_import'`.
  - `traffic_report.derive_channel` ganha a regra "Bling", espelhada no SQL, e `_lead_cols` passa a buscar `origem_cadastro`. O teste de espelho `test_cs_p3_timeline_migration.py` passa a apontar para a migration nova.
- **Frontend.** `api/leads` (POST e import) grava `origem_cadastro` 'manual' ou 'csv_import'. `lib/lead-origin.ts` reconhece a coluna.

### 4. Qualificação (B4)

- **Evento gravado** `lead_events` do tipo `qualificado`: 1 por lead (`dedupe_key 'qualificado:<lead_id>'`), com `metadata.criterio` = `repasse` ou `score`, mais o segmento e `b2b`.
  - É gravado por `registrar_qualificado`, em `app/leads/qualificado.py`, chamado junto com `registrar_repasse` nos dois caminhos de repasse quando o motivo não é de falha. Também é chamado quando o score fecha em `>=5` definitivo e `fn_lead_b2b` é verdadeiro.
  - Se o insert falhar, o repasse não cai.
- `[qualificar_lead]` só é gravado quando há âncora nova não vazia.
- `_t_marcar_interesse` move o card para `qualificado` só com nível "quente"; "morno" não move.
- O score é gravado quando o segmento é atacado/private_label ou `fn_lead_b2b` é verdadeiro, e deixa de depender de `stage='atacado'`. O fluxo de botões usa a mesma regra.
- `valeria_score_directory` e `feeling/route.ts` deixam de filtrar `stage='atacado'` e passam a mostrar todo lead com score.

### 5. Dashboard

- **`dashboard_kpis`.** Parte da versão vigente (`20261019_repasse_sla.sql`, do 7b143561) para não perder o SLA.
  - `leads_new` e `leads_prev` passam a contar leads distintos com a 1ª `entrada` no período, sem importados e sem `ja_era_cliente`.
  - Coluna nova `contacts_new` ("Todos os contatos" = `leads.created_at`, como hoje). A mudança no tipo de retorno exige DROP + CREATE, com grants.
  - Uma única taxa de qualificação: leads com `qualificado` no período ÷ leads atendidos no período (mensagem do lead respondida por `agent` ou `valeria_botoes`). Em outubro ficaria perto de 37% (estimativa). Hoje mostra 18,2%.
- **`dashboard_funnel_conversion`.** O cohort vira a D1.
- **`traffic_report._fetch_leads`.** "Leads" vira a D1, e importados não entram.
- **Frontend.**
  - `dashboard/page.tsx` ganha o card "Todos os contatos".
  - `KpiCard` aceita `hint`, mostrado como tooltip. Os textos dos tooltips:
    - "Leads novos": "leads que chegaram por anúncio, LP ou orgânico; não conta importados nem quem já era cliente".
    - Taxa: "leads qualificados (repasse ao vendedor ou score ≥5 no B2B) ÷ leads atendidos pela Valeria".
  - Ajustes em `mapKpis` e `KpisRow`.
- **Efeito esperado:** "Leads novos" cai cerca de 13% sem mudança real, e a taxa sobe de 18% para perto de 37% só pela troca de fórmula. Os tooltips explicam.

### 6. Views `analytics`

O schema `analytics` não está versionado. A migration grava a definição atual (`pg_get_viewdef`) como comentário de rollback e recria:

- `dim_vendedor` como view sobre `vendedores`;
- `dim_lead.segmento` a partir de `leads.segmento`;
- `dim_lead.b2b` via `fn_lead_b2b`, sem aceitar "qualquer score";
- `vw_leads`.

Também aplica GRANT SELECT ao `consulta_ro` em `vendedores` e nas funções novas. Entregável: o arquivo `docs/superpowers/specs/2026-10-22-glossario-consulta.md` com as mudanças para o glossário do agente de consulta. Não edito o central-claude.

## Backfills (um por vez, cada um com OK seu no Discord)

Para cada backfill:

- script em `scripts/leads_vendedor/`;
- contagem prévia;
- `RAISE EXCEPTION` se passar do teto (esperado +10%);
- tabela `backup_b67f_<n>` com o id e o valor anterior;
- SQL de rollback a partir do backup;
- idempotente.

| # | O quê | Esperado (20/10) |
|---|---|---|
| F1 | Popular `vendedores` (4: João e Arthur ativos, Rafael e Comercial 2 inativos), `bling_seller_map.vendedor_id`, ligar o Arthur ao vendedor Bling 5845108828 e definir o dono do funil "Arthur - Exportação" | 4 + 3 + 1 |
| F2 | `segmento` a partir de `stage` (private_label 1.080, atacado 621, consumo 209, exportacao 30). O resto fica NULL e as inferências (funil, origem) só entram em relatório | cerca de 1.940 |
| F3 | `stage` → fase: segmento vira `qualificando` (cerca de 1.940); secretaria vira `triagem` (420); contato/negociacao/ja_chamado vira `qualificando` (8). Depois aplica o CHECK | cerca de 2.368 |
| F4 | `origem_cadastro`: `bling_import` 184, `reativacao_import` 1.207; status `ativo` → `active` 184 | 1.391 + 184 |
| F5 | `entrada` "Orgânico" de jul a out para inbound sem rastreio, mais os 7 com `meta_ad_id` | cerca de 206 |
| F6 | Vendedor: `deals.assigned_to` pelo dono do funil (3.278) ou pelo `assigned_to` do lead (48); `leads.assigned_to` e `handoff.vendedor_id` pelo nome do repasse, só quando inequívoco (508 João + 20 Arthur). Os ambíguos ("Vendedor" 60, "Joao Bras" fora de segmento 22) vão para relatório | cerca de 3.326 + 528 |
| F7 | Evento `qualificado`: 1º repasse não excluído de cada lead (até 1.776) + score B2B `>=5` definitivo (18, com data de `updated_at`) | até cerca de 1.794 |

Ordem obrigatória: migrations a, b, c, d, d1 e g; F1; F2; migration e (precisa do F1 e do F2); push do código; F3 e, logo depois, a migration f; F4 a F7. F1 e F2 rodam **antes** do push, porque o código novo roteia por `segmento`. O F3 roda **depois** do push, para o código antigo nunca rodar com `stage` já convertido em fase (o código novo lê o `stage` antigo enquanto `segmento` está vazio). Da migration d até o F7, a taxa de qualificação fica perto de 0; o F7 roda no mesmo dia.
O F3 é UPDATE direto no banco: não dispara as automações `stage_enter` do Python. Antes de rodar, confiro que não há gatilho de banco em `leads.stage` que grave evento ou mova card.

## Onde

- Repo `ValerIA`, branch `agente/b67f1c6b`.
- **Migrations novas** em `supabase/migrations/`, aplicadas à mão:
  - `20261022a_vendedores.sql`
  - `20261022b_segmento.sql`
  - `20261022c_origem_cadastro.sql`
  - `20261022d_qualificado_dashboard.sql`
  - `20261022e_analytics.sql`
  - `20261022f_stage_fase_check.sql` (só depois do F3)
  - `20261022g_search_leads_segmento.sql`
- **Backend:** `agent/tools.py`, `leads/service.py`, `leads/repasse.py`, `leads/qualificado.py` (novo), `vendedores/` (novo), `button_flow/effects.py`, `button_flow/valeria_runner.py`, `buffer/processor.py`, `buffer/parking.py`, `follow_up/scheduler.py`, `orchestrator.py`, `automation/engine.py`, `automation/variables.py`, `campaigns/node_registry.py`, `campaigns/traffic_report.py`, `bling/contacts.py`, `watchdog/service.py`, `agent/summary.py`.
- **Frontend:** as telas e rotas listadas acima.
- **Serviços:** `canastra_api`, `canastra_worker` e `crm_crm` (deploy pelo GitHub Actions), mais o Postgres `supabase_db`.

## Como vou executar (agentes em paralelo)

Todos os subagentes rodam com o modelo opus e effort médio, em TDD. Cada um trabalha num worktree próprio derivado de `agente/b67f1c6b`, e eu integro.

1. **Onda 0 (eu, sequencial):** contrato comum, com nomes de colunas e funções, assinaturas de `resolver_vendedor`, `vendedor_do_segmento`, `registrar_qualificado` e `fn_lead_b2b`, e as 6 migrations em esqueleto. Assim os agentes não inventam nomes diferentes.
2. **Onda 1 (4 agentes em paralelo, cada um nos seus arquivos):**
   - A, vendedores: migration a, módulo `vendedores/`, variables, watchdog e as listas no frontend;
   - B, segmento: migration b/f, `leads/service.py`, `node_registry`, `engine` e o frontend de segmento;
   - C, origem e dashboard: migration c e a parte do dashboard da d, `traffic_report`, `bling/contacts.py` e o frontend do dashboard;
   - D, qualificação: o SQL da d, migration e, `qualificado.py`, `valeria_runner`, o diretório de score e o `feeling`.
3. **Onda 2 (1 agente, sequencial):** a integração no caminho do repasse, onde todos colidem: `tools.py` (`encaminhar_humano`, `apply_stage_transition`, `qualificar_lead`, `marcar_interesse`), `effects.py`, `processor.py`/`parking.py`, `scheduler.py`, `orchestrator.py` e o cartão do Arthur.
4. **Onda 3 (paralelo):** 3 agentes escrevem os scripts F1–F7 com teto, backup e rollback, testados no Postgres descartável. Ao mesmo tempo, 1 agente revisor lê o diff inteiro contra esta spec.
5. **Onda 4 (eu):** suíte completa e testes `*_pg` integrados.

## Como testar em modo teste

Tudo no worktree `agente/b67f1c6b`, antes de qualquer push.

1. **pytest (`backend/`).** Testes novos (TDD) para:
   - o resolvedor (uuid, e-mail, apelido, ambíguo → None);
   - `vendedor_do_segmento`;
   - o repasse de exportação mandando o cartão do fixo do Arthur e gravando `vendedor_id`;
   - o repasse sem segmento não movendo o card;
   - `apply_stage_transition` gravando `segmento` e a fase;
   - `move_stage` recusando valor inválido;
   - "morno" não movendo;
   - `[qualificar_lead]` sem âncora não sendo gravado;
   - `registrar_qualificado` ignorando motivos excluídos e não derrubando o repasse;
   - `derive_channel` "Bling";
   - a ponte do Arthur pelo id;
   - o watchdog ignorando quem tem `atende_no_crm=false`.

   Também rodam as suítes existentes que essas mudanças afetam:
   - `test_encaminhar_humano_pipeline`, `test_agent_tools`, `test_repasse_evento`;
   - `test_button_flow_effects_*`, `test_processor_handoff_bridge_*`;
   - `test_qualificar_lead_portao_*`, `test_marcar_interesse`;
   - `test_tags_handoff_segmento_*`, `test_prefill_stage_trigger_*`;
   - `test_traffic_report*`, `test_cs_p3_timeline_migration`;
   - `test_contrato_etapas_joao_migration`, `test_automation_variables`, `test_watchdog_*`.

   Depois, a suíte inteira.
2. **Postgres descartável na VPS:** `crm-scratch-pg-b67f1c6b`, um container próprio sem volume e removido no fim, no padrão de `scripts/repasse_sla/scratch_pg.md`. Leva o schema de produção (`pg_dump --schema-only`) e as 6 migrations. Os testes `*_pg.py` fazem rollback por cenário e cobrem:
   - `fn_vendedor_id`;
   - `fn_lead_b2b` (CNPJ, funil, segmento);
   - os CHECKs;
   - o gatilho de `entrada` Orgânico (INSERT inbound sem rastreio; importado não grava; rastreio posterior funde);
   - `fn_lead_canal` "Bling";
   - `dashboard_kpis` (D1, `contacts_new`, taxa) com dados semeados;
   - `valeria_score_directory`;
   - as views analytics.

   Os scripts F1–F7 rodam no scratch com dados semeados, testando o teto, a idempotência e o rollback.
3. **Frontend:** `npm test` (vitest: `dashboard-mappers`, `lead-origin`, `valeria-score`) e `npm run build`.
4. **Prints:** em modo teste não há CRM rodando com este código. Os prints (dashboard com tooltips, "Todos os contatos", lista de vendedor no deal, filtro de segmento) são tirados em produção depois da publicação.

## Como publicar (só depois do [Liberar produção])

1. **Pré-checagem:** `docker service ls`, `docker service logs --since 1h canastra_api`, `pm2 ls`. Se `origin/master` andou, `git pull origin master` no branch e rodar os testes de novo.
2. **Migrations a, b, c, d, d1 e g à mão** pelo `psql` do `supabase_db`, uma por vez, com `SET LOCAL lock_timeout='5s'`. Todas são aditivas, e o código atual segue funcionando com elas. Depois, recarregar o PostgREST com SIGUSR1 (o NOTIFY é ignorado nesta VPS) e conferir que as funções, colunas e grants existem. Da d até o F7 a taxa de qualificação fica perto de 0: o F7 roda no mesmo dia.
3. **F1 e F2**, cada um com o seu OK. Depois, a migration e (precisa do F1 e do F2).
4. **Merge e push:** merge de `agente/b67f1c6b` em `master` e `git push origin agente/b67f1c6b:master`, sem force. O GitHub Actions faz o deploy de `crm_crm`, `canastra_api` e `canastra_worker`. Acompanhar o job e os logs até os serviços estabilizarem.
5. **F3**, com o seu OK, e logo depois a migration f (CHECK de fase). Depois, **F4 a F7**, um por vez, cada um com o seu OK.
6. **Voltar atrás:**
   - antes do revert do código: `ALTER TABLE public.leads DROP CONSTRAINT IF EXISTS leads_stage_fase_check;` e o `f3_rollback.sql`;
   - código: `git revert` do merge e push, que redeploya a versão anterior;
   - backfills: os demais rollbacks (F7, F6, F5, F4, F2, F1), a partir de `backup_b67f_<n>`;
   - migrations: `scripts/leads_vendedor/rollback_migrations.sql`, que recria `dashboard_kpis`, `dashboard_funnel_conversion`, `fn_lead_canal`, o gatilho e as views analytics a partir das definições guardadas, e remove as colunas e funções novas; a g volta reaplicando a `search_leads` de `20260818_universal_search.sql`. Só roda **depois** do revert do código e dos rollbacks dos backfills.

Ajuste de 22/10 na execução: ordem de publicação revista (push antes do F3) para o código antigo nunca rodar com stage já convertido; F6 não preenche deals do funil Blacklist.

## Como testar em produção

- **Conferência SQL:**
  - `select stage, segmento, count(*) from leads group by 1,2 order by 3 desc;`: nenhum `stage` fora das fases e nenhum segmento fora do enum.
  - `select origem_cadastro, ja_era_cliente, count(*) from leads group by 1,2;`, mais `dashboard_kpis` antes e depois. `leads_new` de 01–15/10 deve ficar perto de 439, e `contacts_new` deve ser igual ao `leads_new` antigo.
  - `select count(*) from sales s where s.sold_by is not null and not exists (select 1 from vendedores v where v.email=lower(s.sold_by));` = 0.
  - `select count(*) from deals where assigned_to is not null and assigned_to not in (select id from vendedores);` = 0.
  - Eventos `qualificado` do dia × repasses do dia.
- **Logs:** `canastra_api` e `canastra_worker` por 1 hora, sem erro em `encaminhar_humano`, `registrar_qualificado` e no gatilho.
- **Telas (prints):** dashboard (Leads novos, Todos os contatos, taxa com tooltip), deal com lista de vendedor, kanban de qualificação por segmento, diretório de score mostrando leads que estavam em `pending`.
- **Teste de repasse de exportação:** com o seu número, conversando com a Valeria como lead de exportação. O efeito externo é só para o seu telefone: a despedida e o cartão do Arthur (fixo) chegam para você, e o card vai para "Arthur - Exportação" com o Arthur como dono. Nenhuma mensagem vai a cliente e nada é gravado no Bling. Depois, devolvo o lead de teste ao estado anterior.
- Nenhuma venda, pedido, NF ou cobrança. As Conversões Ads (`conversions/sweep.py`) continuam lendo `metadata.handoff` como hoje, e esta spec não muda o que vai para a Meta e o Google.

## Fora do escopo

- Receita, frete e cancelados (cartão "vendas e receita").
- Repasse, SLA e closer em si (cartão 7b143561). Aqui só entra o necessário para o Arthur não gerar alerta falso.
- Mesclar duplicados: 165 pares com o mesmo `wa_id`, 189 colisões nos últimos 10 dígitos, 161 telefones Bling com máscara, 11 CNPJs duplicados. 248 leads com `human_control` sem repasse. Tudo isso só vai para o relatório.
- Usar o número "NUMERO ARTHUR" (34) 9155-3110 do CRM. A decisão foi o fixo.
- Inferir o segmento dos 3.130 `pending`: só relatório, sem gravar.
- Ação de automação "definir segmento".
- `deals.stage`/`deals.category` legados, `conversations.stage` e `seller_stage` (coluna morta: listar para remoção futura).
- Mover de volta os 123 cards em `qualificado` sem repasse.

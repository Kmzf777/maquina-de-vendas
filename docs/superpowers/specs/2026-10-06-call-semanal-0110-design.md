# Pendências da call semanal de Ads (01/10) — spec

**Data:** 2026-10-06
**Branch integradora:** `feat/call-semanal-0110` (de `origin/master` em `ba9cb923`)
**Origem:** transcrição `Call semanal Ads Café Canastra.txt` (01/10, Arthur, João, Rafael, Tati) +
mapeamento do código e do banco de produção feito em 05–06/10.

Os itens 5, 6 e 7 da análise da outra sessão (Meta 99×91, Google 14×16/28×34, "2 do Atacado")
**não são bug** e ficam fora. O fix que impede **novas** duplicatas do Bling já está no master
(`ba9cb923`); aqui entra o que ele não cobre.

---

## Decisões tomadas (06/10)

| Tema | Decisão |
|---|---|
| Follow-up de kit | Cadência `kit` dentro dos funis de **Reposição** (não funil novo, não etapa no Atacado). |
| "Já é cliente?" | **Automático quando há evidência; obrigatório para o vendedor só quando o sistema não sabe.** O sistema nunca marca "não" sozinho. |
| Duplicatas do Bling que já existem | Script de **mesclagem com dry-run**; aplica no banco só depois da revisão do Rafael. |
| Preço na ValerIA de botões | **"a partir de R$ 28,70"** — menor preço entre os SKUs que casam. |

---

## Diagnóstico (o que a call viu, e a causa real)

1. **"4 closer e 10 clientes" no /trafego.** As etapas do funil são conjuntos independentes
   (`traffic_report.py:247-255`). O webhook do Bling cria lead novo já com venda, sem conversa e
   sem deal → entra como "cliente" sem ter sido "closer". Closer é o *stage atual* (deal recriado
   na reposição sai da conta) e venda `cancelada` conta como cliente.
2. **Kits "sem origem" (Jovens/Iago, Antônio Sérgio, Velho Hank).** A origem não foi apagada: o
   Bling não achou o lead existente e criou um `bling-<id>`; a venda caiu nele. Restam **261
   leads `bling-*`** no banco. O Iago tem **duas vendas de R$ 60** (Bling + manual, 15 s de
   diferença) — venda contada em dobro. O Velho Hank veio de lista fria: "sem rastreio" está certo
   para ele.
3. **"Meta, campanha não identificada" (Antônio Sérgio).** O lead entrou em 20/08; o `meta_ad_id`
   só passou a ser gravado em 21/08. **748 leads** pagos com `ctwa_clid` e sem `meta_ad_id` são
   recuperáveis pelo `referral.source_id` em `meta_webhook_logs` (dados desde 16/07; o cron de
   retenção de 15 dias **não está agendado** hoje — `cron.job` vazio —, mas não dá para contar
   com isso).
4. **Vida Natural: CNPJ digitado e nada puxado do Bling.** A resolução automática só usa
   `leads.cnpj` (`contacts.py:265-294`). Quando o contato é vinculado pelo modal, o CNPJ **não
   volta** para o lead. A busca manual não tira pontuação (`router.py:150`): CNPJ com máscara
   nunca casa com `doc_digits`.
5. **"Abrir duas abas para copiar".** O cadastro abre com nome/documento/e-mail/telefone vazios:
   os `defaults` leem de uma lista de leads que não é carregada quando o modal vem da conversa
   (`sale-create-modal.tsx:1069`, `quote-create-modal.tsx:808`). E o overlay do `Dialog`
   (`ui/dialog.tsx:41`) borra e bloqueia o chat.
6. **"Limite de 1000 conversas".** Não há `.limit` no código: é o `max-rows` do PostgREST.
   `GET /api/conversations` (`route.ts:157-177`) busca tudo sem paginar. A busca local não olha
   e-mail nem CNPJ e exige a frase contígua.
7. **Follow-up para quem acabou de comprar.** A esteira do João não consulta `sales`; só olha o
   card. Venda em outro deal, venda do Bling (sem deal) ou card não movido → o card de prospecção
   segue recebendo toque. E a venda criada pelo CRM via Bling (`orders.py:486`) não dispara
   `sale_created`, então **não cria o deal de Reposição**.
8. **ValerIA sem preço.** `{classico, 250g}` casa com Moído (R$ 28,70) e Em Grãos (R$ 31,70);
   com 2 candidatos o `preco_do_no` corta a linha (`valeria_runner.py:248-251`).

---

## Arquitetura de execução

Um pacote base sequencial (**P0**) e sete pacotes paralelos (**P1–P7**), cada um num worktree
próprio ramificado de `feat/call-semanal-0110` **depois** do commit do P0. Os pacotes foram
cortados para **não editar o mesmo arquivo**; os pontos de contato são contratos de dados
definidos no P0. A integração é sequencial na branch integradora, com a suíte inteira no fim.

| Pacote | Dono exclusivo de |
|---|---|
| P0 | `supabase/migrations/20261006_call_semanal_base.sql` |
| P1 | `backend/app/bling/*`, `scripts/bling/mesclar_leads_duplicados.py` |
| P2 | `backend/app/campaigns/traffic_*.py`, `frontend/src/components/trafego/*`, `frontend/src/app/(authenticated)/trafego/*`, `scripts/trafego/recuperar_meta_ad_id.py` |
| P3 | `supabase/migrations/20261006b_lead_timeline_triggers.sql`, `scripts/timeline/backfill_lead_events.py`, `frontend/src/components/leads/lead-timeline.tsx`, `frontend/src/app/api/leads/[id]/timeline/route.ts`, `lead-detail-modal.tsx` |
| P4 | `frontend/src/components/sales/*`, `frontend/src/components/quotes/*`, `frontend/src/components/conversas/contact-detail.tsx`, `chat-header.tsx`, `crm-perfil-tab.tsx` |
| P5 | `frontend/src/app/api/conversations/*`, `frontend/src/components/conversas/chat-list.tsx`, `frontend/src/app/(authenticated)/conversas/page.tsx`, `frontend/src/lib/search.ts` |
| P6 | `backend/app/follow_up/*` |
| P7 | `backend/app/button_flow/*` |

Se um pacote precisar tocar arquivo de outro, **para e reporta** em vez de editar.

---

## P0 — Migração base (sequencial, primeiro)

`20261006_call_semanal_base.sql`, idempotente (`if not exists`):

**`leads` — "já era cliente"**
- `ja_era_cliente boolean null` — `null` = desconhecido.
- `ja_era_cliente_fonte text null check in ('auto','vendedor')`
- `ja_era_cliente_em timestamptz null`, `ja_era_cliente_por text null` (e-mail do vendedor).
- **Regra automática no banco** (um lugar só, vale para qualquer caminho de venda): trigger em
  `sales` insert/update — venda não cancelada com `sold_at < leads.created_at` e lead com
  `ja_era_cliente is null` → `true`, `fonte='auto'`. Mesmo `update` roda uma vez na migração
  como backfill. **Nunca grava `false`**, nunca sobrescreve resposta do vendedor. Caso típico:
  cliente antigo do Bling cujo pedido histórico é anterior ao lead. Cliente que só existia no
  WhatsApp (ex.: MR2C) fica `null` → o vendedor responde.

**`leads` — atribuição manual de campanha**
- `campanha_manual_canal text null` (`meta` | `google`), `campanha_manual_id text null`
  (id da campanha em `ad_spend` / `meta_ad_campaigns`), `campanha_manual_nome text null`,
  `campanha_manual_por text null`, `campanha_manual_em timestamptz null`.

**`lead_events` — passa a ser a linha do tempo** (a tabela existe, está vazia; o
`api/leads/[id]/overview/route.ts:133` já a lê — manter compatível)
- `occurred_at timestamptz not null default now()` — quando aconteceu (backfill ≠ inserção).
- `source text null` — `ctwa` | `lp` | `google` | `bling` | `crm` | `sistema` | `disparo`.
- `dedupe_key text null` + índice único parcial `where dedupe_key is not null`.
- índice `(lead_id, occurred_at desc)`.
- Tipos de evento (`event_type`): `entrada`, `etapa`, `venda`, `venda_cancelada`, `disparo`,
  `mesclagem`, `atribuicao_manual`. Payload em `metadata`.

**`meta_referrals_arquivo`** — cópia permanente dos `referral` de `meta_webhook_logs`
(`log_id uuid pk`, `received_at`, `from_number`, `referral jsonb`), preenchida pela própria
migração com `insert … select … on conflict do nothing`. É o seguro contra a retenção: P2 e P3
leem daqui, não do log.

**View `lead_primeira_origem (lead_id, canal, campanha_id, campanha_nome, occurred_at)`** —
primeiro `lead_events` do tipo `entrada` por lead. Começa vazia; P2 programa contra ela com
fallback, P3 a enche.

---

## P1 — Bling e identidade

1. **Mesclagem das duplicatas** — `scripts/bling/mesclar_leads_duplicados.py`.
   - Candidato: lead com `phone like 'bling-%'` **ou** `channel='bling'` e
     `metadata.origem='bling_webhook'`.
   - Par: aplicar ao contato Bling vinculado (`lead_bling_contacts` → `bling_contacts`) as mesmas
     chaves do fix `ba9cb923` (`_chaves_de_celular`, com e sem o 9) contra `leads.phone`, e o
     `doc_digits` contra `leads.cnpj`. Mais de um sobrevivente possível → **não mescla**, lista
     como ambíguo.
   - Sobrevivente = o lead não-Bling (é ele que tem a origem e a conversa).
   - Move todas as linhas com `lead_id` do duplicado para o sobrevivente: `sales`, `sale_items`
     (via sale), `deals`, `quotes`, `lead_bling_contacts` (conflito → mantém o do sobrevivente),
     `lead_notes`, `lead_tags`, `lead_events`, `conversations`, `messages`, `broadcast_leads`,
     `campaign_enrollments`, `follow_up_jobs`, `lead_qualification_scores`,
     `lead_seller_feelings`, `lead_daily_sends`, `conversion_events`. A lista é verificada contra
     `information_schema` na execução; tabela nova com `lead_id` não coberta → aborta.
   - Copia `cnpj`, `razao_social`, `nome_fantasia`, `email` para o sobrevivente **só se vazios**.
   - Grava `lead_events` `mesclagem` no sobrevivente; apaga o duplicado.
   - **Vendas gêmeas** (mesmo lead após mescla, mesmo valor, `sold_at` a ≤ 1 dia, uma `bling` e
     outra `manual`/`crm`): **só relata**, não cancela. Decisão caso a caso do João.
   - Padrão = dry-run: escreve CSV com pares, ambíguos, órfãos (sem par) e gêmeas, e um JSON de
     backup das linhas apagadas. `--aplicar` executa em transação por par.
2. **CNPJ volta para o lead.** Ao vincular um contato (`resolve` com escolha, `create_contact`
   que acha por documento, vínculo manual), gravar `doc_digits` em `leads.cnpj` e
   `razao_social`/`email` **se vazios** no lead.
3. **Busca manual aceita máscara.** `_termo_seguro` / `contacts/search`: se o termo, sem
   pontuação, tiver 11 ou 14 dígitos, busca por `doc_digits = <dígitos>`.
4. **Venda pelo CRM via Bling cria a Reposição.** `create_order` (`orders.py:486`), depois de
   mover o deal para ganho, chama `ensure_reposicao_deal`. Venda vinda do **webhook** do Bling
   chama também, **apenas** se `sold_at >= now() - 7 dias` (backfill histórico não pode criar
   deals em massa).

## P2 — Relatório /trafego

1. **Funil cumulativo.** Cliente conta em closer e em conversa; closer conta em conversa.
   Vendas `status='cancelada'` não contam. No resumo, um stat novo **"Entraram já como
   cliente"** = clientes que não eram closer pelo critério antigo (mantém visível o que o Arthur
   percebeu, em vez de esconder).
2. **Atribuição manual tem prioridade.** Em `build_campaign_report`, `campanha_manual_*`
   preenchido vence `meta_ad_id`, UTMs e tokens. A linha do lead mostra selo "manual".
3. **Colunas novas** em `campaign-leads-table.tsx` (e na listagem de `(sem campanha)`):
   - **Já era cliente** — `ja_era_cliente` (sim/não/—), com selo "auto" quando a fonte é `auto`.
   - **Compras** — nº de vendas não canceladas do lead (todas as datas).
   - **Primeira origem** — de `lead_primeira_origem`; vazio → canal atual (`derive_channel`) em
     cinza com "(atual)".
4. **Atribuir campanha** no `campaign-lead-panel.tsx` (só admin): select de campanhas com gasto
   (`ad_spend`) dos últimos 120 dias, agrupado por canal; "Remover atribuição" limpa. Grava
   `lead_events` `atribuicao_manual`. Endpoint `PATCH /api/traffic/leads/{id}/campanha` em
   `traffic_router.py`.
5. **Recuperar `meta_ad_id`** — `scripts/trafego/recuperar_meta_ad_id.py`: para lead com
   `ctwa_clid` e `meta_ad_id is null`, procura em `meta_referrals_arquivo` o `referral` com o
   mesmo `ctwa_clid` (fallback: mesmo `from_number` e o referral mais próximo **antes** de
   `leads.created_at`, até 24 h) e grava `source_id`. Só preenche nulos. Dry-run padrão com CSV.

## P3 — Linha do tempo do lead

1. **Captura por trigger, não por código espalhado** (migração `20261006b_…`):
   - `leads` insert, ou update que **mude** `ctwa_clid`, `gclid`, `fbclid`, `meta_ad_id`,
     `utm_source`, `utm_campaign` → `entrada` com canal derivado e o snapshot de tracking.
     Limitação aceita: reentrada com tracking idêntico não gera evento.
   - `deals` update de `stage_id` (e insert) → `etapa` (pipeline, de, para).
   - `sales` insert → `venda` (valor, origem, conta Bling, `kit` boolean via `sale_items`);
     update para `cancelada` → `venda_cancelada`.
   - `broadcast_leads` quando `sent_at` passa a ter valor → `disparo`.
   - `dedupe_key` determinística (ex.: `venda:<sale_id>`) para o backfill não duplicar.
   - Trigger **nunca** derruba a escrita original: corpo em `begin … exception when others then
     raise warning … end`.
2. **Backfill** — `scripts/timeline/backfill_lead_events.py`, idempotente: entradas de
   `meta_referrals_arquivo` (por telefone), entrada inicial de cada lead com tracking
   (`created_at`), vendas, deals (`created_at` e `entered_stage_at` atual), disparos. Dry-run
   com contagens por tipo; `--aplicar`.
3. **Tela** — `lead-timeline.tsx`: lista vertical do mais novo ao mais antigo, ícone por tipo,
   canal/campanha nas entradas, valor e "kit" nas vendas, e marcadores diários "conversou"
   (dias com mensagem inbound, calculados na leitura a partir de `messages`). Rota
   `GET /api/leads/[id]/timeline`. Montada como aba no `lead-detail-modal.tsx` (P3) e na
   conversa (P4 monta no `contact-detail.tsx`).

## P4 — Tela de venda e cabeçalho do lead

1. **Pré-preenchimento.** Quando o modal recebe `leadId` (sem `pickLead`), busca o lead por id e
   usa `name`, `phone`, `email`, `cnpj`/`razao_social` como `defaults` do `BlingContactResolver`
   — venda e orçamento.
2. **Não esconder o chat.** Venda e orçamento abrem como painel lateral direito (Sheet) sem
   overlay bloqueante, a conversa continua visível e selecionável para copiar.
3. **Cabeçalho do lead** (topo do `contact-detail.tsx`): telefone (copiar), **e-mail** e
   **CNPJ/CPF** editáveis inline e **"Já é cliente?" Sim/Não** — o mesmo `PATCH /api/leads/{id}`
   do Perfil. Selo "auto" quando `ja_era_cliente_fonte='auto'`; o vendedor pode sobrescrever.
4. **"Já era cliente" obrigatório na dúvida.** A regra automática é o trigger do P0. Na UI,
   salvar venda/pedido com `ja_era_cliente` nulo é **bloqueado**: o modal mostra o Sim/Não
   obrigatório e só habilita "Salvar" com resposta; a resposta grava no lead pelo `PATCH`
   existente (`fonte='vendedor'`, `por`, `em`).
5. **Kits no topo.** No seletor de produtos do `BlingOrderForm`, os SKUs de Kit Degustação
   aparecem num grupo "Kits" fixo no topo — venda direta, sem proposta.
6. **Seletor de lead** dos modais deixa de carregar `/api/leads` inteiro (teto de 1000): usa a
   busca server-side `search-contacts` com debounce.
7. Monta a aba "Linha do tempo" (componente do P3) no `contact-detail.tsx`.

## P5 — Conversas sem teto de 1000

1. `GET /api/conversations` paginado por cursor (`last_message_at desc, id`), página de 200.
   Todo filtro hoje aplicado no cliente sobre a lista inteira (aba, status, vendedor, não lidas)
   vira parâmetro da query; filtro que só reordena/realça a página carregada pode ficar no
   cliente. O plano lista os filtros atuais e classifica cada um.
2. `chat-list.tsx` com rolagem infinita; contadores que dependiam da lista inteira passam a vir
   de uma contagem server-side.
3. Busca: `search-contacts` passa a olhar `email`, `cnpj` (dígitos), e casa por **tokens** (todos
   os termos, em qualquer ordem) em vez de frase contígua; `lib/search.ts` local idem.

## P6 — Follow-up

1. **Não tocar quem comprou.** `motivo_para_pular_joao` ganha a regra: cadências de prospecção
   (`novo`, `em_conversa`, `proposta`) pulam o lead com venda não cancelada em
   `sold_at >= now() - N dias` **ou** depois de `deals.created_at` do card. `N` = ajuste
   `dias_sem_prospeccao_apos_venda` em `followup_joao_ajustes`, default 30. A mesma checagem
   roda **no envio** (`scheduler.py`, ao lado da `card_mudou_de_etapa`) e cancela com motivo
   `lead_comprou`.
2. **Cadência `kit`** nos funis `reposicao_atacado` e `reposicao_private_label`:
   - Gatilho: card em `novo` ("Cliente Ativo") há ≥ 20 dias, e a **última** venda não cancelada
     do lead tem item de kit.
   - Kit = `sale_items.bling_product_id` na lista de SKUs de kit das duas contas (constante em
     `follow_up/kit.py`) **ou** `descricao ilike '%kit degust%'`.
   - Toques: dia 0 e dia 7. Templates `followjoao_kit_*` **não existem na Meta ainda**: a
     cadência nasce com `ativa=false` em `followup_joao_cadencia` e só liga quando os templates
     forem aprovados (ação do Rafael).
   - Convive com a cadência `reposicao` (45 d, mesmo card): as travas existentes (job pendente,
     1 template por lead/dia, cooldown) evitam toque em dobro.
   - Depende do card de Reposição existir: venda feita no CRM já o cria; venda via Bling passa a
     criar com o P1.4.

## P7 — Preço na ValerIA de botões

`preco_do_no`: com mais de um candidato, se todos são do mesmo produto-base (mesmo nome sem o
formato "Moído"/"Em Grãos"), devolve o **menor** preço com o prefixo "a partir de". Mais de um
produto-base continua cortando a linha (comportamento atual). N5/N5b passam a mostrar
"a partir de R$ 28,70".

---

## Tratamento de erros

- Scripts (P1 mesclagem, P2 recuperação, P3 backfill): **dry-run por padrão**, `--aplicar`
  explícito, transação por unidade (par/lead), relatório CSV. Rodar `--aplicar` em produção só
  com OK do Rafael.
- Triggers do P3 nunca propagam exceção para a escrita original.
- `ja_era_cliente` desconhecido nunca vira "não" sem um humano.
- P1.4: falha em `ensure_reposicao_deal` é logada e **não** desfaz a venda.

## Testes

- Backend: TDD por pacote, pytest no container `canastra-api` (memória
  `project_crm_rodar_testes_backend`), base atual **6329 passed**. Cada pacote entrega testes
  dos casos reais da call: Jovens/Iago (mescla + gêmeas), Serginho (meta_ad_id recuperado),
  Vida Natural (CNPJ com máscara + write-back), "4 closer → 10 clientes" (funil cumulativo),
  lead com venda recebendo `joao_proposta` (P6), N5 com 2 SKUs (P7).
- Migrações: aplicar no Postgres de teste do repo; triggers testados com insert/update reais.
- Frontend: os testes existentes do frontend + build (`next build`) verde.
- Integração: merge sequencial P1…P7 na branch integradora, suíte inteira, e só então
  `git push origin feat/call-semanal-0110:master` **com autorização do Rafael** (CLAUDE.md).

## Fora do escopo

- Os itens 5–7 da outra sessão (não são bug).
- "Conversa iniciada" do Google (click-to-WhatsApp sem rastreio) — não há como ler hoje.
- Primeira origem de clientes antigos da base (não existe dado; ficam "—").
- Fundir orçamento e proposta (Bling × CRM) — era confusão de nomenclatura, não defeito.

# Esteiras do Vendedor — design

Data: 2026-09-04
Origem: reunião de 03/09/2026 (Arthur Boaventura, Rafael Reis, Tati Casagrande),
itens 6, 7, 8 e 9 da ata. Transcrição em `Meeting Transcription (2).txt`.
Contexto quantitativo: `Diagnostico-Funil-Canastra-2026-09-01.pdf` — 0 retomadas em
414 leads/mês no número do João; 82% das conversas dele terminam com ele falando por
último.

---

## 1. O problema

O motor de follow-up existe, funciona e faz 684 disparos/mês — **mas só no canal da
Valéria**. No momento do handoff, `agent/tools.py::encaminhar_humano` grava
`ai_enabled=False` e cancela os follow-ups pendentes com `cancel_reason='handoff'`.
A partir daí o lead fica sozinho com o vendedor, e o vendedor não faz follow-up.

O motor de automação (`automation/engine.py`, editável em `/campanhas > cadências`)
saberia fazer esse trabalho — mas é **estruturalmente cego** para essa população:
todo gatilho de polling filtra `leads.ai_enabled = TRUE`, tanto em
`automation/triggers.py` quanto nas RPCs `get_leads_for_repurchase` e
`get_leads_no_sale_in_stage` (`20260521_automation_engine.sql`).

E os gatilhos que existem olham para `leads.stage` — que neste sistema é o
**segmento** (atacado, private label, exportação, consumo), não a coluna do Kanban.
As esteiras pedidas na ata são todas sobre a coluna do Kanban (`deals.stage_id`), e
a tabela `deals` **não registra quando um card entrou na coluna atual**.

---

## 2. Decisões do dono (não re-perguntar)

Tomadas na sessão de brainstorming de 04/09/2026:

1. **Item 6 distingue os dois silêncios** e manda mensagem diferente para cada um:
   o lead ficou sem resposta nossa (caso A) vs. o lead sumiu depois de atendido
   (caso B).
2. **As mensagens são templates Meta novos**, a criar. Não é texto livre.
3. **Arthur e João mudam prazos e templates sozinhos, numa tela** — sem deploy.
4. **No caso A, o João continua dono do lead.** A Valéria NÃO reassume a conversa;
   o que muda é que ele recebe alerta forte. (A alternativa — IA reassumindo — foi
   descartada pelo risco do caso Marcella: a Valéria cotou produto inexistente e
   perdeu a venda.)
5. **Esteira de reposição tem teto de 3 ciclos** (45 dias). No terceiro silêncio o
   card vai sozinho para Perdido, com motivo registrado.
6. **Esteira de proposta para no 2º toque e alerta o vendedor.** Nunca move o card
   sozinho — proposta enviada é ativo caro demais para o sistema descartar.

### Premissas assumidas (corrigíveis, mas assumidas como verdade aqui)

- **As esteiras são por funil e canal, não hardcoded no João.** O Arthur falou em
  migrar faturamento para o Café Rural e o CRM já tem escopo por vendedor
  (`/painel-vendas`, `/orcamento`). Amarrar no `JOAO_PHONE_NUMBER_ID` criaria
  dívida no primeiro vendedor novo.
- **Teto de 1 mensagem automática por lead por dia**, somando as três esteiras,
  via o `check_frequency_cap` que já existe (`campaigns.frequency_cap = 1`).
  Prioridade quando duas esteiras disputam o mesmo lead no mesmo dia:
  proposta (`priority=8`) > etapa Novo (`priority=6`) > reposição (`priority=4`).
  Números maiores ganham; a ordenação por prioridade já é lida em
  `get_due_enrollments`.

---

## 3. Item 9 — já está pronto

`_move_deal_to_proposal()` (`backend/app/quotes/router.py:249`, chamado em `:495`)
move o card para `proposta_enviada` quando o orçamento é criado, e nunca anda para
trás. Coberto por `test_criar_move_o_deal_para_proposta_enviada`.

**Não há código a escrever para o item 9.** O que falta é aplicar
`supabase/migrations/20260825_quotes.sql` no Supabase, que é quem cria a etapa
`proposta_enviada` em todo funil. Enquanto ela não roda, `/orcamento` inteiro
responde PGRST205 — que é exatamente o "não tá usando orçamento aqui dentro" dito
na reunião aos 40:16.

**Esta migration é pré-requisito da esteira E3**, que dispara justamente na etapa
`proposta_enviada`. Sem ela a E3 não tem em que se ancorar.

---

## 4. As três esteiras

Vocabulário: **toque** = um envio de template. **Ciclo** = toque + espera + checagem
de resposta.

### E1 — Etapa inicial do funil (item 6)

Duas campanhas irmãs, porque os públicos são disjuntos e as mensagens são
diferentes. A tela mostra as duas como um só card ("Etapa Novo"), com dois campos de
template.

A etapa de gatilho é **configurável** (§8), como nas outras duas esteiras. O default
do seed é a etapa de menor `order_index` do funil escolhido — que é a coluna "Novo"
no funil padrão, mas os funis são por usuário e o rótulo varia.

**E1a — ninguém respondeu o lead (caso A)**

| | |
|---|---|
| Gatilho | card na etapa inicial do funil, última mensagem **do lead**, silêncio ≥ 3 dias |
| Toque 1 | template de retomada com pedido de continuidade |
| Depois | `alert_seller` (severidade `warning`) e fim |
| Move card | não |

O `alert_seller` é o coração deste caso: o watchdog já detecta o mesmo padrão em
20 minutos (check `handoff_sla_breach` em `watchdog/service.py`) mas só gera alerta
interno, e ninguém agiu sobre ele. Aqui o lead recebe uma mensagem **e** o vendedor
recebe a cobrança.

**E1b — o lead sumiu depois de atendido (caso B)**

| | |
|---|---|
| Gatilho | card na etapa inicial, última mensagem **nossa**, silêncio ≥ 3 dias |
| Toque 1 | template de reengajamento |
| Depois | fim |
| Move card | não |

### E2 — Reposição / "Já chamado" (item 7)

| | |
|---|---|
| Gatilho | card na etapa configurada (default: a que hoje corresponde a "Já chamado"), silêncio ≥ 15 dias, qualquer falante |
| Toque 1 | template de reposição |
| Espera | 15 dias |
| Toque 2 | mesmo template (ou outro, configurável) |
| Espera | 15 dias |
| Toque 3 | idem |
| Espera | 15 dias |
| Depois | `mark_deal_lost` com `lost_reason = "sem resposta na esteira de reposição"` |

Sai da esteira, a qualquer momento, quando: o lead responde, ou o card sai da etapa
de gatilho (virou proposta, foi ganho, foi perdido à mão). Ver §6.3.

### E3 — Proposta enviada (item 8)

| | |
|---|---|
| Gatilho | card em `proposta_enviada` há ≥ 3 dias, última mensagem **nossa** |
| Toque 1 | template de follow-up de proposta (D+3) |
| Espera | 5 dias |
| Toque 2 | segundo template, de tom diferente (D+8) |
| Espera | 2 dias |
| Depois | `alert_seller` (severidade `warning`, "proposta esfriando há 10 dias") e fim |
| Move card | **nunca** |

O gatilho conta a partir de `entered_stage_at` do card (quando o orçamento foi
gerado), não da última mensagem — "proposta enviada conta três dias", como dito na
reunião aos 37:22. O filtro de falante garante que, se o cliente já respondeu à
proposta, a esteira não começa.

---

## 5. Modelo de dados

Migration nova: `supabase/migrations/20260904_esteiras_vendedor.sql`.
Como toda migration deste repo, **não é aplicada pelo deploy** — roda à mão no SQL
editor do Supabase antes do push.

### 5.1 `deals.entered_stage_at`

```sql
ALTER TABLE deals ADD COLUMN IF NOT EXISTS entered_stage_at timestamptz;
```

Trigger `BEFORE UPDATE` que carimba `now()` quando `stage_id` **ou** `stage` muda —
espelha exatamente o que `002_crm_enrichment.sql` faz para `leads.entered_stage_at`.
As duas colunas precisam ser observadas porque o `deals` legado ainda escreve em
`stage` (texto) em alguns caminhos, e o Kanban usa `stage_id`.

**Backfill obrigatório:**

```sql
UPDATE deals SET entered_stage_at = COALESCE(updated_at, created_at)
 WHERE entered_stage_at IS NULL;
```

Sem backfill a coluna nasce NULL e nenhum card entra em esteira nenhuma — as três
ficariam silenciosamente mortas. Com `DEFAULT now()` seria pior de outro jeito: todo
card apareceria como recém-chegado e as esteiras só acordariam 15 dias depois.
`updated_at` é a melhor aproximação disponível da última movimentação real.

**Consequência aceita:** no dia em que a esteira E2 for ligada, todo card parado há
mais de 15 dias fica elegível de uma vez. O amortecedor é triplo — as esteiras
nascem **desligadas** (`status='draft'`), o polling processa no máximo 20 leads por
tick (limite já existente em `triggers.py`), e o `frequency_cap=1` impede segundo
disparo no mesmo dia para o mesmo lead. Quem ligar a esteira deve ser avisado disso
na tela.

### 5.2 `campaigns.audience`

```sql
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS audience text NOT NULL DEFAULT 'ia'
  CHECK (audience IN ('ia', 'humano', 'ambos'));
```

**O default `'ia'` não é decoração — é o que impede uma regressão grave.** Se em vez
de um campo novo simplesmente removêssemos o filtro `ai_enabled = TRUE` dos gatilhos
existentes, toda campanha já criada passaria a enrolar leads sob controle humano,
incluindo os do João, disparando automação por cima de conversa que um vendedor está
conduzindo. O opt-in por campanha preserva o comportamento atual bit a bit.

### 5.3 `campaign_enrollments.metadata`

```sql
ALTER TABLE campaign_enrollments ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}';
```

Guarda a **guarda de etapa** do enrollment (§6.3):
`{"guard": {"deal_id": "...", "stage_id": "...", "stage_key": "..."}}`.

A alternativa seria reler o nó de gatilho da campanha a cada tick para descobrir de
qual etapa aquele enrollment saiu. Gravar no enrollment é uma consulta a menos por
tick e, mais importante, deixa a guarda imune a edição posterior da campanha: quem
mexer no gatilho não muda a regra de saída de quem já está dentro.

### 5.4 RPC `get_deals_stage_stagnant`

Uma única função cobre as três esteiras. Em SQL porque a decisão depende de um
`MAX(created_at)` por conversa — via PostgREST isso seria N+1 sobre centenas de
cards por tick.

```sql
CREATE OR REPLACE FUNCTION get_deals_stage_stagnant(
  p_stage_id      uuid,     -- etapa exata; OU
  p_stage_key     text,     -- key ('proposta_enviada') — vale em todo funil
  p_pipeline_id   uuid,     -- filtro opcional de funil
  p_channel_id    uuid,     -- canal onde o silêncio é medido
  p_stage_days    int,      -- dias parado na etapa (0 = ignora)
  p_silence_days  int,      -- dias sem mensagem (0 = ignora)
  p_last_speaker  text,     -- 'lead' | 'nos' | 'qualquer'
  p_audience      text,     -- 'ia' | 'humano' | 'ambos'
  p_limit         int DEFAULT 20
) RETURNS TABLE(lead_id uuid, deal_id uuid, stage_id uuid, last_speaker text, last_message_at timestamptz)
```

`stage_id` volta no retorno porque é ele que o gatilho grava na guarda de etapa
(§5.3) — a guarda precisa saber de qual coluna o card saiu, e reler isso depois
seria uma corrida com o próprio movimento que ela quer detectar.

Regras dentro da função:

- O card tem de estar **aberto**: a etapa atual não pode ter key em
  (`fechado_ganho`, `fechado_perdido`, `perdido`, `encerrado`). As quatro keys, e não
  duas, porque `20260626_valeria_unify_stage_keys.sql` deixou alguns funis com
  `perdido` em vez de `fechado_perdido`, e o funil "Importação Leads Frios" fecha em
  `encerrado`. A fonte dessa lista é `leads/service.py::_perdido_stage_id`, que já
  trata as quatro.
- `p_stage_days > 0` ⇒ `entered_stage_at <= now() - p_stage_days`.
- `p_silence_days > 0` ⇒ a última mensagem da conversa (lead + canal) é mais velha
  que isso. Conversa **sem nenhuma mensagem** conta como silêncio (a data cai para
  `deals.created_at`), senão card criado por importação nunca entraria em esteira.
- `last_speaker` sai do `role` da última mensagem: `'user'` → `'lead'`, qualquer
  outro → `'nos'`. Filtro aplicado quando `p_last_speaker <> 'qualquer'`.
- `p_audience`: `'ia'` ⇒ `ai_enabled = TRUE`; `'humano'` ⇒ `ai_enabled = FALSE`;
  `'ambos'` ⇒ sem filtro.
- Termina com `LIMIT p_limit`.

Fecha com `NOTIFY pgrst, 'reload schema';`.

---

## 6. Backend

### 6.1 Gatilho `deal_stage_stagnation`

Em `automation/triggers.py::check_polling_triggers`, um bloco novo no mesmo formato
dos existentes. Lê a config do nó de gatilho, chama a RPC, e para cada linha:

1. pula se `is_already_enrolled(campaign_id, lead_id)`;
2. pula se `_conversation_followup_disabled(lead_id, channel_id)` — respeita a
   conversa que o vendedor marcou como finalizada em `/conversas`;
3. **pula se `is_lead_blacklisted(lead_id)`** — guarda que os gatilhos de polling
   atuais não têm e que aqui é indispensável: a esteira de reposição varre a base
   inteira, e é onde mora quem já pediu para não ser incomodado;
4. cria o enrollment com `deal_id` e com o `metadata.guard` de §5.3.

### 6.2 Público (`audience`) nos gatilhos existentes

`no_message` e `stage_stagnation` passam a ler `campaigns.audience` e a montar o
filtro de `ai_enabled` a partir dele, em vez do `TRUE` fixo. As RPCs
`get_leads_for_repurchase` e `get_leads_no_sale_in_stage` ganham um parâmetro
`p_audience text DEFAULT 'ia'` com a mesma semântica — o default preserva a
compatibilidade para quem chamar sem o argumento, inclusive o código que fica em
produção entre o SQL rodar e a imagem subir.

**A migration precisa dropar a assinatura antiga antes de recriar essas duas.**
No Postgres a identidade de uma função inclui a lista de tipos de parâmetros, então
`CREATE OR REPLACE` com um parâmetro a mais **não substitui**: cria uma segunda função, com aridade diferente. Com as duas no catálogo, uma chamada de 2 argumentos
casa com os dois candidatos e o Postgres levanta `function ... is not unique` — o
que derrubaria **todas** as cadências, não só as esteiras novas.

### 6.3 Guarda de etapa

Em `engine._process_one`, antes de executar qualquer nó: se o enrollment tem
`metadata.guard`, relê a etapa atual do `guard.deal_id`. Se o card **saiu** da etapa
guardada, cancela o enrollment (`cancel_reason` implícito no status) e registra no
`campaign_execution_log`.

É isso que implementa, de uma vez, os dois "roda até" da ata: "até entrar em
proposta" (E2) e "até fechado/ganho ou perdido" (E3). O card mudar de coluna é
exatamente o evento que encerra a esteira.

### 6.4 `on_reply = 'cancel'` nas três esteiras

`handle_campaign_reply` hoje **pausa** o enrollment por default. Enrollment pausado
conta como ativo em `is_already_enrolled` e nunca mais é retomado — o lead que
responde ficaria permanentemente inelegível para reentrar na esteira depois.

As três esteiras querem `on_reply='cancel'`: lead que responde sai limpo e pode
voltar meses depois, se o card estagnar de novo.

**Correção (achado da execução das Tasks 2–5):** pôr `on_reply='cancel'` só nos nós
de envio **não resolve**. `campaigns/worker.py::handle_campaign_reply` só honra esse
valor quando o enrollment está parado num nó `type == "send"` — e uma esteira passa
a maior parte da vida parada num nó `wait`, entre um toque e o seguinte. Resposta
que chega nessa janela cai no `pause_enrollment`, exatamente o estado que esta seção
existe para evitar.

Então `on_reply` passa a viver também na config do **nó de gatilho**, que é o lugar
que descreve a esteira inteira em vez de um toque isolado, e `handle_campaign_reply`
consulta esse valor quando o nó atual não define o seu. Um nó `send` com `on_reply`
explícito continua vencendo — nenhuma campanha existente muda de comportamento.

### 6.5 Ação `alert_seller`

`action_type` novo em `_execute_action`:

```
config: { severity: "warning", title: "...", message_template: "..." }
```

Chama `alerts.service.create_system_alert(type="esteira_vendedor", ...)` com
`metadata` contendo `lead_id`, `deal_id` e `campaign_id`, e grava a mesma frase em
`lead_notes` (mesmo caminho do `add_note`) para o histórico ficar no card. Fail-soft:
erro no alerta não derruba o tick.

### 6.6 Correção: `mark_deal_lost` move o card errado

Hoje o bloco `("mark_deal_won", "mark_deal_lost", "move_deal_stage")` de
`_execute_action` escolhe o deal assim:

```python
sb.table("deals").select("id").eq("lead_id", ...).order("created_at", desc=True).limit(1)
```

O deal **mais recente do lead** — não o deal da esteira, mesmo com
`enrollment["deal_id"]` preenchido e disponível. Um lead com card de reposição
antigo e card novo teria o card errado marcado como perdido.

Correção: usar `enrollment.get("deal_id")` quando existir; só cair no
"mais recente" como fallback. Vale para as três ações do bloco.

`mark_deal_lost` também passa a gravar `lost_reason` quando vier na config —
hoje o campo existe na tabela e nunca é preenchido por automação.

### 6.7 Seed das esteiras — `campaigns/esteiras.py`

Módulo novo. Cria as quatro campanhas (E1a, E1b, E2, E3) com UUIDs determinísticos
(`uuid5`, mesmo padrão de `system_cadence.py`), em `status='draft'`.

**Diferença essencial em relação a `system_cadence.py`:** aquele é espelho e
re-sincroniza a cada deploy, desfazendo edição manual. Este **cria uma vez e nunca
sobrescreve** — a decisão 3 é justamente que o Arthur edite. O seed é idempotente
por existência do id, não por conteúdo.

Expõe também as funções de leitura/escrita dos parâmetros que a tela consome, para
que o frontend não precise conhecer o formato do grafo.

### 6.8 API

- `GET /api/automation/esteiras` → as quatro esteiras em formato achatado:
  `{ key, nome, ativa, canal_id, funil_id, etapa, toques: [{ dias, template_name }],
  acao_final }`.
- `PUT /api/automation/esteiras/{key}` → grava os mesmos campos de volta nos
  `campaign_nodes` correspondentes.

Escrita **não** aceita reescrever a topologia do grafo — só os parâmetros. Quem
quiser mudar a forma do fluxo usa o builder.

**Duas regras que a execução do seed obrigou a acrescentar:**

1. **Ligar exige etapa configurada.** Na RPC, `p_stage_id IS NULL` e
   `p_stage_key IS NULL` significam "sem filtro de etapa" — fail-open. Uma esteira
   ativada antes de ser configurada ficaria elegível a **todo card aberto de todo
   funil**, 20 por tick, repetindo. O `status='draft'` do seed protege só até o
   primeiro clique. Então o `PUT` recusa `ativa: true` enquanto o gatilho não tiver
   `stage_id`. O aviso de "quantos cards ficam elegíveis" (§8) é o segundo anteparo,
   não o primeiro.

2. **O `stage_id` de Perdido da E2 é resolvido pela API, não digitado.** O seed
   nasce com `stage_id: None` na ação `mark_deal_lost`, e `_execute_action` retorna
   cedo quando ele falta: a esteira rodaria os três toques e terminaria **sem mover
   o card**, que é justamente a decisão 5 da ata. Como a tela mostra a ação final
   como texto fixo, ninguém preencheria esse campo. Então, ao gravar `funil_id` da
   esteira de reposição, a API resolve sozinha a etapa de perda daquele funil,
   usando o mesmo vocabulário de quatro keys de `leads/service.py::_perdido_stage_id`
   (`fechado_perdido`, `perdido`, `encerrado`, e o fallback que aquela função já
   aplica).

---

## 7. Templates Meta

Cinco templates novos na WABA `1399531671927018` — a mesma que já serve os dois
números, confirmado em `.env` (`META_WABA_ID` e `META_PHONE_NUMBER_ID=1049315514934778`,
que é o número do João). Nada de infra nova: é submissão na conta que já existe.

| Template | Esteira | Params |
|---|---|---|
| `esteira_novo_sem_resposta_v1` | E1a | nome do lead, nome do vendedor |
| `esteira_novo_reengajamento_v1` | E1b | nome do lead, nome do vendedor |
| `esteira_reposicao_v1` | E2 | nome do lead, nome do vendedor |
| `esteira_proposta_d3_v1` | E3 toque 1 | nome do lead, nome do vendedor |
| `esteira_proposta_d8_v1` | E3 toque 2 | nome do lead, nome do vendedor |

Todos categoria **UTILITY**, com os mesmos três `QUICK_REPLY` do corpus atual
("Continuar atendimento", "Tirar dúvidas", "Não tenho interesse") — o terceiro já
alimenta a blacklist e é a saída digna que protege o rating do número.

Script `scripts/create_esteira_templates.py`, modelado no
`scripts/create_utility_templates.py` existente, com uma diferença obrigatória:
**token e WABA_ID vêm de variável de ambiente**. O script atual tem o access token
escrito no arquivo; versionar assim vazaria o token no histórico do git.

**Locale:** submeter em `pt_BR` e conferir no retorno o idioma efetivamente
aprovado. `automacao_valeria_to_joao` foi aprovado só em `en` e o default `pt_BR`
causava 404 #132001 com o job cancelado sem entregar. O `language_code` gravado na
config do nó tem de ser o da aprovação, não o pedido.

Aprovação leva de minutos a 48h e é **fora do nosso controle** — por isso o seed
nasce desligado e a tela mostra o estado do template.

---

## 8. Tela "Esteiras"

Aba nova em `/campanhas`, ao lado de "Cadências" (`VALID_TABS` em
`campanhas/page.tsx`). Não é um builder — é um formulário.

Três cards, um por esteira (E1a e E1b aparecem juntos no card "Etapa Novo"):

- liga/desliga (escreve `campaigns.status` entre `active` e `draft`);
- canal e funil (selects);
- etapa de gatilho (select alimentado por `pipeline_stages` do funil escolhido);
- por toque: dias e template (select alimentado por `message_templates`, mostrando
  só os **aprovados**);
- ação final, como texto fixo não editável ("move para Perdido" / "avisa o vendedor");
- ao ligar uma esteira pela primeira vez, aviso explícito de quantos cards estão
  elegíveis naquele instante — o efeito de §5.1 tem de ser visível antes do clique,
  não descoberto depois;
- link "abrir no builder" para a campanha correspondente.

Antes de escrever qualquer componente, invocar a skill `frontend-design`.

---

## 9. Fora de escopo

- Score de conversa por IA (discutido na reunião aos 37:44 e 43:09) — é outro
  projeto, com outro custo.
- Unificar o handoff num número só (a causa estrutural nº 1 do diagnóstico, 26% de
  perda). Grande demais para caber aqui e não é o que a ata pediu.
- Segundo Bling / Café Rural (reunião aos 40:23).
- Recuperar os 5 pedidos descartados pelo bug de `sales.lead_id NOT NULL`.
- Qualquer mudança no motor de follow-up da Valéria (`follow_up/`). As esteiras
  vivem no motor de campanhas; os dois seguem independentes.

---

## 10. Riscos

1. **Aprovação dos templates na Meta** — bloqueia a entrada em operação, não o
   código. Mitigação: seed desligado, tela mostra o estado.
2. **Avalanche no primeiro "ligar"** (§5.1). Mitigação: aviso na tela + limite de 20
   por tick + `frequency_cap=1`.
3. **`20260825_quotes.sql` continua pendente** — sem ela não existe etapa
   `proposta_enviada` e a E3 não tem gatilho. Pré-requisito duro.
4. **`20260709_cadence_enrollment_hardening.sql`** pode não ter sido aplicada. O
   código do hardening está em `master` (verificado: `MAX_STEPS`, `skip_weekends`,
   `claimed_at`, `recover_stale_enrollments`), mas as colunas que ele usa vêm dessa
   migration. Conferir antes do deploy — sem ela o claim atômico não existe e
   disparo duplicado volta a ser possível.
5. **Número do vendedor é o mesmo que ele usa à mão.** Automação e pessoa
   escrevendo no mesmo número: o `frequency_cap` protege do bombardeio automático,
   mas não impede o toque automático sair logo depois de o vendedor ter escrito.
   Mitigado pelo filtro de silêncio (`p_silence_days`), que só considera elegível
   quem está sem mensagem nenhuma há N dias.

---

## 11. Testes

- **Puro/unitário:** resolução de falante, corte por dias, montagem do filtro de
  audiência, escolha do deal em `mark_deal_lost` (o bug de §6.6), guarda de etapa.
- **Gatilho:** stub do Supabase no padrão da suíte atual — enrolla quem deve,
  ignora já enrolado / blacklist / conversa finalizada.
- **Regressão explícita:** campanha com `audience` ausente ou `'ia'` continua
  filtrando `ai_enabled=TRUE`. Este teste é a rede de segurança de §5.2.
- **Seed:** roda duas vezes e não duplica nem sobrescreve edição manual.
- **Frontend:** a tela lê e grava os parâmetros; template não aprovado não aparece
  no select.
- Suítes inteiras (backend e frontend) verdes antes de qualquer push.

---

## 12. Ordem de entrega

1. Migration + RPC (nada depende de template).
2. Gatilho, `audience`, guarda de etapa, `alert_seller`, correção do
   `mark_deal_lost`.
3. Seed das quatro campanhas.
4. API + tela.
5. Script e submissão dos templates (em paralelo, desde o começo — a aprovação é o
   caminho crítico externo).

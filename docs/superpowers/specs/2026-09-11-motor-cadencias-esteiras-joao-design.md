# Motor de Cadências — fazer rodar, e as esteiras do João dentro dele

Data: 2026-09-11
Antecedentes: `2026-09-10-funil-joao-motor-followup-design.md` (SP0, já em produção) e a
auditoria do builder de 11/09/2026.
Decisão do dono: as esteiras do João rodam **no motor de cadências**, consertado — é o
único caminho que entrega visível **e** personalizável.

---

## 0. O achado que define este trabalho

> **O motor de cadências nunca rodou.** Medição em produção (11/09/2026):
> `campaign_enrollments` = **0 linhas**, `campaign_execution_log` = **0 linhas**,
> campanhas com `status='active'` = **0**.

E não poderia ter rodado. O nó `wait` **não avança a matrícula**:

```python
elif node_type == "wait":
    target = _wait_target(cfg, now)
    _update(enrollment["id"], next_execute_at=target.isoformat(), claimed_at=None)
    _log_exec(...)
    return          # ← engine.py:345
```

Existe **um único ponto** em todo o código que muda `current_node_id` — `engine.py:367` —
e o `return` acima acontece antes dele. Uma cadência `enviar → aguardar → enviar`
estaciona no "aguardar" e reagenda a si mesma a cada tick, para sempre. Nenhuma cadência
de mais de um toque jamais poderia funcionar.

Este documento é sobre fazer o motor rodar pela primeira vez, e deixar as esteiras do
João montadas nele.

### O que NÃO é o motor de cadências (desfazendo uma confusão)

O follow-up da ValerIA **não usa este motor**. Ele tem o seu próprio
(`backend/app/follow_up/`), que funciona: **8.140 jobs, 3.302 nos últimos 30 dias**.
A campanha `d4a7ffa3…` que aparece no builder com o selo `SISTEMA · SOMENTE LEITURA` é um
**espelho** — redesenhada a partir de `follow_up/cadence.py` a cada deploy, permanente em
`draft`, com o router recusando ativar/matricular/apagar. Ela existe só para a lógica da
ValerIA deixar de ser invisível.

São três coisas distintas: o motor da ValerIA (roda), o espelho dele (desenho), e o motor
de cadências (nunca rodou). As esteiras do João vão para o terceiro.

---

## 1. Decisões

| # | Decisão | Origem |
|---|---|---|
| D1 | As esteiras do João rodam no **motor de cadências**, não em Python dedicado | dono, 11/09 |
| D2 | O builder precisa permitir **montar e editar** de verdade | dono, 11/09 |
| D3 | Eu deixo as automações do plano **já montadas** e apontadas para o canal do João, em `draft` | dono, 11/09 |
| D4 | A home de `/campanhas` mostra **quais leads estão em job e de qual cadência** | dono, 11/09 |
| D5 | **O João move os deals** de Private Label à mão. Nenhuma movimentação automática de dado histórico | dono, 11/09 |
| D6 | "Novo" usa **2 dias**, não 36h — cabe no gatilho que funciona, sem mexer no motor | este spec, §3.5 |

### Por que 2 dias e não 36 horas

A reunião de 10/09 decidiu *"36h a dois dias"* — uma faixa. Adotar **2 dias** permite usar
`deal_stage_stagnation`, que é o **único gatilho completo do sistema** (o único com guarda
de blacklist, número errado e conversa finalizada), sem precisar de granularidade em horas
na RPC. É a decisão que troca uma mudança de motor por uma escolha de parâmetro dentro do
que o dono já aprovou.

---

## 2. O que está quebrado — medido, não suposto

| # | Defeito | Evidência | Efeito |
|---|---|---|---|
| 1 | `wait` não avança a matrícula | `engine.py:340-345` vs o único avanço em `:367` | **nenhuma cadência de 2+ toques funciona** |
| 2 | Filtro de etapa grava **rótulo**, motor compara **key** | `inspector.tsx:166,187,413` (`value={s.label}`) vs `triggers.py:168` | gatilho nunca casa; há prova salva em produção: `{"stage_filter": "Novo (Frio)"}` |
| 3 | `audience` não tem campo em tela nenhuma | nasce `'ia'` por default | toda automação montada na tela é **cega para os leads do João** |
| 4 | `UNIQUE(campaign_id, lead_id)` sem cláusula parcial | `pg_constraint` (medido) | um lead entra numa campanha **uma vez na vida** — mata a reposição recorrente |
| 5 | `send_text` não checa blacklist | `engine.py:407-437` | manda para quem pediu para sair |
| 6 | Ação sem alvo loga ✅ | `engine.py:355-356` | operador vê sucesso onde nada aconteceu |
| 7 | `ensure_reposicao_deal` procura funil que não existe mais | `reposicao.py:27` = `"João - Reposição"`; o funil virou `"João - Reposição Atacado"` | `create_deal` cai no **primeiro pipeline por order_index** — card nasce no funil errado |
| 8 | Orçamento → Proposta Enviada é **opt-in** | `quotes/router.py:493` (`if body.deal_id`) + modal nasce em "Não vincular" | `quotes` tem **0 linhas**; o marco nunca foi exercido |

---

## 3. Arquitetura — 6 blocos

### B1 — Os consertos que destravam

Sem estes, nada mais importa.

1. **`wait` avança.** Trocar o `return` por um avanço que grave
   `current_node_id = next_node_id`, mantenha `next_execute_at = target`, incremente
   `step_count` e limpe `last_sent_node_id`. Semântica correta: `wait` = *agende o próximo
   nó para depois*, não *estacione aqui*.
2. **`value={s.label}` → `value={s.key}`** em três linhas do inspector. A `key` **já está
   carregada** no `FlowStage` e nunca é usada.
3. **Campo de público** (`ia` / `humano` / `ambos`) no formulário de campanha, e exposto no
   POST de criação.
4. **Derrubar a `UNIQUE(campaign_id, lead_id)` total**, mantendo só o índice parcial que
   protege matrícula viva. É drift fora de migration — entra numa migration nova.
5. **`send_text` checa blacklist** como o `send` já faz.
6. **Ação no-op loga `skipped` com motivo**, não `done`.

**Critério de pronto do B1:** um grafo `gatilho → enviar → aguardar 1 dia → enviar → fim`
percorre os quatro nós, com `current_node_id` mudando a cada passo.

### B2 — A capacidade nova: `on_reply = "reset"`

É a decisão central da reunião de 10/09 ("se o lead responde, reseta a esteira") e não
existe. Hoje `_apply_reply_policy` (`campaigns/worker.py:171-199`) conhece dois valores:
`cancel` e `pause`.

Acrescentar um terceiro, `reset`, que:
- devolve `current_node_id` ao primeiro nó executável (o `next_node_id` do gatilho);
- zera `step_count` e `last_sent_node_id`;
- agenda `next_execute_at` para agora;
- **mantém o status `active`**.

O último ponto é o que resolve um problema que parecia separado: como a matrícula
permanece ativa, ela **nunca passa pelo caminho de reinscrição**, e o cooldown de 90 dias
da RPC — que trancava o card para fora — deixa de ser obstáculo. Era por isso que
`cancel` + reinscrever não servia.

A precedência existente é preservada: valor no nó vence valor no gatilho.

### B3 — As duas garantias do dono

**G1 — Em conversa → orçamento criado → Proposta Enviada.**
O mecanismo existe (`_move_deal_to_proposal`, `quotes/router.py:249-287`) e o SP0 restaurou
a `key` nos 5 funis. O que falta é adoção: tornar o vínculo obrigatório, **com resolução
automática** do card aberto do funil do vendedor — e não com `get_open_deal`, que devolve o
mais recente de qualquer funil. O dropdown passa a exibir o nome do funil junto do título.

**G2 — Fechado Ganho → card em "Cliente Ativo" no funil de reposição certo.**
Dois consertos numa tacada:
- resolver o funil de destino pelo **funil de origem**: `João - Atacado` → `João - Reposição
  Atacado`; `João - Private Label` → `João - Reposição Private Label`;
- mirar a etapa por **key `novo`** (que é a "Cliente Ativo"), em vez de nome literal.

Substituir `REPOSICAO_PIPELINE_NAME` por um mapa origem→destino resolvido por UUID. E o
`dedupe_open` passa a ser **escopado ao funil de reposição** — hoje ele reaproveita
qualquer card aberto do lead, inclusive o de handoff da ValerIA em outro funil.

> **Nota de escopo (D5):** este bloco conserta o comportamento **daqui para frente**.
> Os 802 cards históricos de "João - Reposição Atacado" ficam como estão — o João os move.
> A classificação histórica é indefensável: medido, **749 dos 802 (93%) não têm nenhuma
> evidência** de segmento (`deals.category` vazia, `leads.stage='pending'` em 86%,
> `metadata.segmento` ausente em 793), e os produtos comprados são todos de marca Canastra,
> o que aponta para atacado. Só 19 têm evidência de Private Label.

### B4 — A tela de matrículas na home de `/campanhas`

`CampaignEnrollmentsTable` (`frontend/src/components/campaigns/cadence-enrollments-table.tsx`)
**já existe e está órfã** — zero referências no repositório. Ela é escopada a uma campanha
(`campaignId`), e o pedido é a visão cruzada.

Entrega: um painel na home de `/campanhas` listando **lead, cadência, etapa atual, status e
próximo disparo**, com filtro por status. Reaproveita o componente existente extraindo a
consulta para aceitar "todas as campanhas".

Isto não é enfeite: sem ele, acompanhar uma esteira exige SQL. É o instrumento que torna a
prova do B6 observável pelo dono.

### B5 — As três esteiras, montadas e apontadas para o João

Todas em `status='draft'`, `audience='humano'`, canal do João, `frequency_cap=1`.

| esteira | gatilho | fluxo | fim |
|---|---|---|---|
| **Novo** | card parado **2 dias** na etapa `novo` | 1 toque de retomada | encerra |
| **Em conversa** | card parado na etapa `respondeu` | 7 toques: D+2, D+4, D+7, D+12, D+18, D+24, D+30; **`on_reply=reset`** | move para `em_atencao` |
| **Reposição** | card em `novo` do funil de reposição há **45 dias** | toque 1 → 3d → toque 2 → 15d → toque 3 → 15d → toque 4 | move para `em_atencao` |

Cada uma existe **duas vezes** — uma para Atacado, uma para Private Label — porque o
gatilho é por funil e as mensagens diferem. Mesmo grafo, parâmetros diferentes. São seis
campanhas ao todo.

**O marco zero dos 45 dias deixa de ser um problema.** Eu havia registrado, no spec de
10/09, que "nenhuma coluna guarda de forma editável quando o lead virou Fechado Ganho".
Com G2 no lugar, o card de reposição **nasce** em "Cliente Ativo" no instante da venda — e
`deals.entered_stage_at`, criado pelo SP0 e mantido por trigger, passa a ser exatamente
esse marco. A esteira de Reposição lê o relógio da etapa, como as outras duas. Nenhuma
coluna nova, nenhum campo editável: **G2 alimenta o relógio que a esteira consome.**

Consequência prática: ligar a esteira de Reposição sem G2 funcionando não faz sentido — os
cards não existiriam. A ordem entre os blocos não é arbitrária.

**Ordem de construção:** a esteira **Novo do Atacado** primeiro, provada ponta a ponta no
B6. Só depois replicar. Se o motor tiver mais defeito escondido, ele aparece numa esteira
barata em vez de em seis.

### B6 — A prova

O botão "⚡ Testar" **não serve**: envia de verdade, pula o `wait` e não registra nada. O
Dev Router também não — ele é 100% inbound e não toca no caminho de cadência.

Procedimento:

1. Backend dev com `REHEARSAL_MODE=true` — troca o provider por `MockProvider` e cobre os
   dois caminhos de envio da cadência (`engine.py:397-404` e `:428`).
2. Campanha de ensaio com `env_tag='dev'` — sandbox limpo dentro do mesmo banco (medição:
   **zero linhas** `env_tag='dev'` hoje), e o motor filtra por ele.
3. Lead de teste `5534988861441`, que já existe.
4. Ações não destrutivas primeiro (`add_note` no lugar de `mark_deal_lost`).
5. **Critério de aprovação: `current_node_id` MUDA ao passar por um `wait`.** Hoje não
   muda — é o teste que reprova o motor atual.

⚠ **Limite honesto do ensaio:** `REHEARSAL_MODE` silencia o WhatsApp mas **não isola o
banco**. `_execute_action` continua gravando em `leads`, `deals`, `lead_tags` e
`lead_notes`, e essas tabelas não têm `env_tag`. WhatsApp fica mudo; CRM não.

Além do ensaio, testes automatizados — incluindo um que **falha hoje** por causa do `wait`.

---

## 4. Fora de escopo, de propósito

- **O caminho n8n estrutural:** ação emitindo evento (automação encadeando automação),
  fan-out, dados entre nós, espera-por-evento como ramo, rascunho×publicado. Cada um é spec
  próprio, e nenhum é necessário para as esteiras do João.
- **Os outros gatilhos quebrados:** `no_message` lê `leads.last_msg_at`, coluna morta
  (**10 de 4.631** preenchidos, contra 4.404 em `conversations.last_msg_at`);
  `sale_created` perde 88% das vendas (as do Bling não chamam `fire_trigger`);
  `stage_enter` é surdo às mudanças que a ValerIA faz. Nenhum é usado pelas esteiras.
- **Mover os 802 deals históricos** (D5).
- **Corrigir as 4 esteiras do seed de 04/09.** Elas carregam o desenho antigo. Este spec
  monta as novas; as antigas viram lixo a apagar depois.

---

## 5. Riscos

| # | Risco | O que evita |
|---|---|---|
| 1 | Estrear um motor que nunca rodou, no número que fecha venda (rating GREEN) | ensaio do B6 antes de qualquer ativação; tudo nasce `draft` |
| 2 | `REHEARSAL_MODE` não isola o banco — ações escrevem de verdade | ações não destrutivas no ensaio; card descartável para as reais |
| 3 | O `wait` consertado libera cadências que estavam paradas | não há matrícula viva hoje (0 na história) — o risco é nulo agora e só existe se alguém ativar antes do conserto |
| 4 | Derrubar a UNIQUE pode permitir matrícula duplicada | o índice parcial `uq_campaign_enrollments_active` continua protegendo o que importa |
| 5 | G2 passa a criar cards de reposição de verdade | é o comportamento desejado, mas muda o volume do board do João — avisar antes |

---

## 6. Pendências do dono

1. **Mover à mão** os deals de Private Label que estão em "João - Reposição Atacado" (D5).
2. **Passar a usar `/orcamento`** — sem adoção, G1 é letra morta mesmo consertada.
3. **Aprovar os templates Meta** das esteiras. Medição: zero templates `esteira_*` na WABA.
4. **Ligar uma esteira de cada vez**, observando o volume do primeiro dia.

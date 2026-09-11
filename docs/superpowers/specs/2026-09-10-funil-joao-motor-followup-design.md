# Motor de Follow-up do Vendedor — design

Data: 2026-09-10
Origem: reunião de 10/09/2026 (Arthur Boaventura, Rafael Reis), 84 min.
Transcrição: `Reuniao-Decisao-Funil-Joao.txt`.
Antecedente: reunião de 03/09 → spec `2026-09-04-esteiras-vendedor-design.md` e branch
`feat/esteiras-vendedor` (20 commits, **nunca publicada**).
Contexto quantitativo: `Diagnostico-Funil-Canastra-2026-09-01.pdf` + medições diretas em
produção feitas em 10/09/2026 e citadas ao longo deste documento.

---

## 0. Sumário — o que levar para a reunião com o João

1. **O follow-up automático não existe no número do vendedor.** Existe só no número da
   ValerIA. O motor é estruturalmente cego para o público do João, e o motivo não
   aparece em log nenhum.
2. **Medido hoje: 792 leads em que nós falamos por último e o lead sumiu.** Só 18 estão
   esperando resposta nossa. O silêncio é de um tipo só.
3. **A reestruturação dos funis foi começada à mão durante a reunião e está pela
   metade — e quebrou o contrato interno de etapas.** Três coisas estão quebradas em
   produção agora (§2). Nenhuma delas dá erro visível.
4. **363 dos 578 cards em "Novo" estão na coluna errada** — o lead já falou com o João.
   Sem reclassificar antes de ligar, eles recebem uma mensagem dizendo "você não me
   respondeu".
5. **O orçamento nunca foi usado — `quotes` tem zero linhas.** A reunião elegeu o
   orçamento como o **único** marco de "Proposta Enviada" (D3), mas os 9 cards que estão
   lá chegaram por arrasto. **É problema de adoção, não de código** — e é a conversa mais
   importante a ter com o João.
6. **O trabalho vira 5 blocos** (§4). O bloco 0 é pré-requisito de todos os outros e
   não manda nenhuma mensagem — dá para fechar e validar sozinho.
7. **Ao ligar, só o fluxo novo entra** (~15 cards/dia). O passivo de 1.488 cards não é
   varrido por essa via; ele é assunto do funil de Recuperação.
8. **Boa notícia medida:** nenhum lead com `opt_out=true` tem card aberto nos funis do
   João. Os 48 opt-outs pendentes conhecidos são da coorte do Bling, não daqui.

---

## 1. O problema, medido

### 1.1 Por que não existe follow-up no número do João

No handoff, `agent/tools.py::encaminhar_humano` grava `ai_enabled=False` e cancela os
follow-ups pendentes. A partir daí o lead fica sozinho com o vendedor.

Os dois motores que poderiam assumir são cegos a esse público:

| Motor | Onde para | Efeito |
|---|---|---|
| Follow-up da ValerIA | `follow_up/scheduler.py:858` — para em `ai_enabled is False` | nunca toca no público do João |
| Cadências (`/campanhas`) | todo gatilho de polling filtra `leads.ai_enabled = TRUE` (`automation/triggers.py`, RPCs de `20260521_automation_engine.sql`) | nunca enrola o público do João |

Não é bug de configuração: **nada dispararia, e o motivo não apareceria em log nenhum.**

### 1.2 O silêncio é de um tipo só

Leads em etapa aberta nos funis do João, no canal humano (medido 10/09/2026):

| Situação | Leads | ≤3d | 3-8d | 8-15d | 15-30d | 30d+ |
|---|---:|---:|---:|---:|---:|---:|
| **Nós falamos por último — o lead sumiu** | **792** | 65 | 25 | 60 | 148 | 494 |
| **O lead falou por último — devemos resposta** | **18** | 1 | 0 | 0 | 0 | 17 |
| Sem conversa datada (importados) | 643 | — | — | — | — | — |

**Consequência de desenho:** o caso "lead esperando por nós" — metade do spec de 04/09,
com alerta forte e a discussão sobre a ValerIA reassumir — tem **18 casos no mundo
inteiro, 17 deles já mortos (30d+)**. Ele sai do escopo. A reunião de 10/09 também não
o menciona em momento nenhum.

### 1.3 O volume que o motor vai gerar

Cards criados nos 4 funis do João nos últimos 60 dias: **924 → 15,4/dia**
(Private Label 8,7/dia · Atacado 4,8/dia · Reposição 1,9/dia).

Vendas fechadas nos últimos 60 dias: **121** → cerca de **91 cards** estarão dentro da
janela de 45 dias da reposição a qualquer momento.

### 1.4 Sem colisão com o Agente Recuperação

O bot de botões que já subiu (desligado) atende o funil "Reativação Bling": 1.208 leads
em etapa aberta. Os funis do João: 1.488. **Interseção medida: zero.** Os dois podem
ligar juntos sem dobrar automação em ninguém.

---

## 2. O achado que reordena o trabalho

> A reestruturação dos funis foi feita à mão, durante a própria reunião, e está pela
> metade. Ela quebrou o contrato que o sistema usa para reconhecer etapas.

### 2.1 A causa raiz

`pipeline_stages` tem duas identificações: `label` (o nome que o operador vê e edita) e
`key` (o identificador estável que todo o código de negócio usa). O próprio código diz:

> *"A key é o contrato estável do estágio; o label é editável pelo operador e o
> `deals.stage` legado está morto."* — `backend/app/leads/service.py:237`

**A tela escreve `key` em um caminho só, e é o que menos se usa.** Há três operações, e
elas se comportam de forma diferente:

| operação | escreve `key`? |
|---|---|
| **Criar um funil** (`POST /api/pipelines`) | **sim, parcialmente** — `DEFAULT_STAGES` traz `proposta_enviada`, `fechado_ganho` e `fechado_perdido`; Novo/Contato/Proposta/Negociação nascem `key: null` |
| **Criar uma etapa avulsa** (`POST /api/pipelines/[id]/stages`) | **não** — aceita só `label` e `dot_color` |
| **Renomear/editar** (`PATCH …/[stageId]`) | **não** — aceita `label`, `dot_color`, `order_index`, `conversion_*` |

Ou seja: **toda etapa que alguém cria à mão no Kanban nasce `key = NULL`, e renomear
nunca cria uma `key`.** Foi exatamente o que aconteceu — as etapas renomeadas
("Já chamado"→"Em Conversa", "Novo"→"Cliente Ativo") continuaram sem key, e as criadas
do zero ("Em ATENÇÃO", "Entrada de Inativos", "Em Follow-UP", "Recuperado") nasceram sem
key. O funil novo "João - Reposição Private Label" ganhou as três keys finais só porque
veio de `DEFAULT_STAGES`.

E o `DELETE` só recusa quando a etapa tem cards
(`api/pipelines/[id]/stages/[stageId]/route.ts:68-73`). **Ele não protege uma etapa que
carrega uma `key`.** Uma etapa-contrato vazia pode ser apagada sem aviso — foi assim que
a `proposta_enviada` da Reposição sumiu.

**Evidência de que a migration `20260825_quotes.sql` foi aplicada:** `proposta_enviada`
existe hoje em **7 funis** — os 4 da ValerIA, o Atacado, o Private Label e o funil novo.
Falta exatamente onde foi apagada à mão (Reposição) e onde a reunião decidiu que não deve
existir (Recuperação).

### 2.2 O estado real dos funis agora (medido 10/09/2026)

```
João - Reposição            João - Atacado           João - Private Label
 0 Cliente Ativo    (0)      0 Novo         (189)     0 Novo            (389)
 1 Em Conversa    (694)      1 Em Conversa  (111)     1 Contato         (150)
 2 Em ATENÇÃO       (0)      · (2 e 3 vazios)         2 Proposta         (12)
 3 Proposta Enviada (2) ⚠    4 Proposta Env.  (6)     3 Negociação       (15)
 4 Fechado Ganho  (105)      5 Fechado Ganho  (5)     4 Proposta Env.     (1)
 5 Perdido          (1)      6 Perdido        (5)     5 Fechado Ganho    (12)
                                                      6 Perdido           (6)

João - Recuperação                    João - Reposição Private Label (novo)
 0 Entrada de Inativos  (5)            0 Novo · 1 Contato · 2 Proposta
 1 Em Follow-UP         (3)            3 Negociação · 4 Proposta Enviada
 2 Recuperado           (1)            5 Fechado Ganho · 6 Perdido
 · (3 vazio)                           (0 cards — nasceu com o esquema ABOLIDO)
 4 Perdido Churn        (1)
```

⚠ = etapa sem `key`, onde o código espera uma.

### 2.3 O que está quebrado agora, em silêncio

1. **`Proposta Enviada` do funil Reposição perdeu a `key`.** A etapa que tinha
   `key='proposta_enviada'` (0 cards) foi apagada, e a etapa "Proposta" (2 cards,
   `key=NULL`) foi renomeada para "Proposta Enviada". `_move_deal_to_proposal`
   (`quotes/router.py:272`) procura por `key`, não acha, e devolve `False` com um log
   `info`. **O orçamento não move mais o card nesse funil** — e a reunião decidiu que o
   orçamento é o *único* marco válido de passagem.

2. **O funil Recuperação não tem `fechado_ganho`.** Isso é intencional pela reunião
   (54:39), mas o código não sabe: `bling/orders.py:316`, `leads/service.py:243` e
   `leads/reposicao.py:62` resolvem essa etapa por `key`. Uma venda registrada para um
   card nesse funil não fecha o card, e `ensure_reposicao_deal` nunca dispara.

3. **Private Label não foi reestruturado — e não podia ter sido.** `deals.stage_id`
   não tem cláusula `ON DELETE` (`012:32`), então apagar "Proposta"/"Negociação" com 27
   cards dentro levanta FK 23503 e a API devolve 409. **A migração obrigatoriamente
   move os cards antes de apagar a etapa.** É por isso que o Atacado (6 cards) passou e
   o Private Label (27 cards) travou.

4. **O funil novo nasceu com o esquema abolido.** `api/pipelines/route.ts:15-23` cria
   todo funil com Novo/Contato/Proposta/Negociação. Enquanto esse template não mudar,
   o próximo funil do João volta ao ponto de partida.

5. **`order_index` com buracos** (Atacado pula 2 e 3; Recuperação pula 3). Três lugares
   comparam `order_index`: o relatório de tráfego, o movimento do orçamento e a
   resolução da etapa de entrada. Em produção **nenhuma etapa tem `is_protected=true`**,
   e `_first_unprotected_stage_id` elege como "etapa de entrada" a de menor
   `order_index` — um arrasta-e-solta infeliz faz todo card novo nascer em "Perdido".

6. **363 dos 578 cards em "Novo" estão na etapa errada.** D2 define "Novo" como *o João
   mandou algo e o lead não respondeu*. Medindo quem já falou **no número do João**
   (não "já mandou mensagem alguma vez" — quase todo lead falou com a ValerIA antes do
   handoff): **363 cards (63%) deveriam estar em "Em conversa"** — 240 no Private Label,
   123 no Atacado. Só 215 estão corretamente em "Novo".
   **Consequência direta:** sem reclassificar, 363 leads que *estão* conversando com o
   João receberiam a mensagem da esteira "Novo" — que diz, em essência, "você não me
   respondeu". Errado e constrangedor.

7. **38 cards fechados moram em etapas sem `key`** e por isso contam como **abertos**
   para a RPC das esteiras (que trata `key` NULL como etapa aberta). São 1.540 cards
   abertos por `closed_at IS NULL` contra 1.578 pela regra da RPC.

### 2.4 Três campanhas para este fim já existem — e nunca saíram do rascunho

O banco tem **6 campanhas no total**, e três delas foram criadas exatamente para o que
esta reunião pediu:

| campanha | status |
|---|---|
| `39d0acbd` — "Reposição Inteligente — João" | `draft` |
| `ecb97097` — "Follow-up Cotação — João" | `draft` |
| `d4a7ffa3` — "Valéria — Follow-up (motor)" | `draft` |

Nenhuma é uma das 4 do seed das esteiras (que usa UUID determinístico), então **o seed
ainda não rodou**. Decidir no SP1 se essas três são reaproveitadas ou apagadas — deixá-las
paradas ao lado das novas é receita para alguém ligar a errada.

### 2.5 O ativo que tudo isto protege

**Quality rating do número do João (+55 34 9146-1669): `GREEN`.** Os três números da
conta estão GREEN, com throughput `STANDARD`. É o melhor estado possível, e é exatamente
o que a decisão de arranque (D15) e o teto de 1 msg/lead/dia existem para preservar — o
número que fecha venda é o mesmo que mandaria os templates.

### 2.6 O que a reestruturação NÃO quebrou (verificado, porque parecia que sim)

`scripts/recuperacao/corrigir_deals_reposicao.sql` — o script que move os 19 deals de
reposição criados no funil errado — tem uma guarda que aborta a transação se a etapa de
entrada da Reposição mudar (`:194`). Como o funil agora começa em "Cliente Ativo" e não
em "Novo", parecia que o script tinha deixado de ser executável.

**Não deixou.** A guarda resolve a primeira etapa não-protegida por `order_index` e
compara o **UUID**, não o rótulo. A etapa `07b4a308-c2ad-4896-99ee-caee30f926b8` continua
sendo `order_index 0`; ela só foi **renomeada** de "Novo" para "Cliente Ativo". A guarda
passa e o script roda.

Melhor ainda: sob o desenho novo, "Cliente Ativo" é **semanticamente o destino certo**
para esses 19 cards — são clientes que acabaram de comprar, esperando o relógio dos 45
dias. O script continua válido como está.

---

## 3. Decisões

### 3.1 Da reunião de 10/09 (não re-perguntar)

| # | Decisão | Timestamp |
|---|---|---|
| D1 | Funis de 1ª compra: **Novo → Em conversa → Proposta Enviada → Ganho/Perdido**. "Negociação" e "Proposta" removidas; "Contato" vira "Em conversa" | 36:55, 1:02:41, 1:05:35 |
| D2 | **Novo** = o João mandou algo e o lead não respondeu. **Em conversa** = houve resposta do lead, movimento **automático** | 1:03:10 |
| D3 | **Proposta Enviada só pelo orçamento.** "O OK não existe. OK é o orçamento ser criado" | 34:22, 38:05 |
| D4 | Funil Reposição: **Novo (cliente ativo) → Já chamado → Ganho/Perdido** | 25:49 |
| D5 | Reposição: **45 dias do marco zero** (= Fechado Ganho), **editável pelo João**; depois **3 dias**; depois **15 em 15** | 33:28, 30:14, 31:09 |
| D6 | Etapa Novo: primeiro toque em **36h a 2 dias** | 1:04:45, 1:07:10 |
| D7 | Esteira "Em conversa" é **longa** e **reseta a cada resposta do lead** | 1:06:53, 1:07:10 |
| D8 | **Sem botão** no funil de 1ª compra ("o cara tem certeza que é um robô"); **com botão** na reposição/recuperação | 35:09, 41:40 |
| D9 | **"Em atenção"** = estado terminal da esteira; vira decisão humana do João (volta à esteira / Recuperação / churn com **motivo obrigatório**); card com cor viva | 41:12, 44:11, 45:51 |
| D10 | **Dois funis de recuperação**: quem já comprou e quem nunca comprou | 1:08:54 |
| D11 | Saída da Recuperação = **orçamento criado** → move para Reposição/`proposta_enviada` e marca "Recuperado". Recuperação **não tem** `proposta_enviada` | 55:20, 58:34 |
| D12 | Atacado e Private Label usam **o mesmo motor**, só mudam as mensagens | 03:37 |

### 3.2 Do dono, em 10/09 (fecham ambiguidades da transcrição)

- **D13 — "Em atenção" é ETAPA do Kanban**, não sinalização sobre o card.
  *Tecnicamente é também a opção barata:* não existe hoje nenhum mecanismo de badge ou
  cor por card no Kanban de deals (só o badge de `category`, com os 4 valores já
  ocupados, e um contador "Xd"). Como etapa, o Kanban já a renderiza.
- **D14 — Cadência da esteira "Em conversa": 7 toques em 30 dias**, escalonada
  `D+2 · D+4 · D+7 · D+12 · D+18 · D+24 · D+30`, e qualquer resposta do lead **reseta
  para D+0**. Ao fim do D+30 o card vai para **Em atenção**. Tudo editável na tela.
- **D15 — Arranque: só o fluxo novo.** A esteira só considera card cujo relógio da etapa
  comece **depois** de a esteira ser ligada. O passivo histórico não é varrido por essa
  via.

### 3.3 O que sai de escopo por medição

- **A esteira do "lead esperando resposta nossa"** (E1a do spec de 04/09): 18 casos, 17
  mortos. Removida.
- **`alert_seller` como está na branch**: grava em `system_alerts`, cuja UI foi removida
  da produção em 14/08/2026, e uma nota em `lead_notes`. **É um alerta que ninguém lê.**
  Ou ganha superfície nova, ou não conta como entrega.

### 3.4 Contradição da própria reunião, a resolver com o Arthur

Sobre a cadência da Recuperação, a reunião diz as duas coisas:

- 38:08 — *"esse cara tem que receber uma mensagem a cada três dias **até ele falar que
  não quer mais**"*
- 1:06:30 — *"esse é o cara que a gente vai mandar mensagem **uma vez na vida outra na
  morte**. Vai ganhar pouco dinheiro com ele"*

Uma cadência de 3 em 3 dias sem teto, no número que fecha venda, é o maior risco de
*quality rating* deste projeto. **Proposta a levar à reunião:** 4 toques (D+0, D+3, D+6,
D+10) e então **Em atenção** — o "até pedir para parar" é honrado pelo opt-out, não por
cadência infinita. Decisão do Arthur.

---

## 4. Arquitetura — 5 blocos

Cada bloco tem spec de implementação próprio. Este documento fixa o contrato entre eles.

### SP0 — Contrato de etapas (pré-requisito, não manda mensagem)

**Objetivo:** deixar os 5 funis do João com a estrutura da reunião e, sobretudo, com
`key` em toda etapa que o motor precisa reconhecer.

Keys a fixar (uma migration SQL, revisada à mão, aplicada pelo dono):

| Funil | Etapa | `key` |
|---|---|---|
| Atacado, Private Label | Novo | `novo` |
| Atacado, Private Label | Em conversa | `respondeu` ¹ |
| Atacado, Private Label | Em atenção | `em_atencao` |
| Atacado, Private Label, Reposição, Reposição PL | Proposta Enviada | `proposta_enviada` |
| Reposição, Reposição PL | Cliente Ativo | `novo` |
| Reposição, Reposição PL | Já chamado | `ja_chamado` ² |
| Reposição, Reposição PL | Em atenção | `em_atencao` |
| Recuperação | Entrada de Inativos | `entrada` |
| Recuperação | Em Follow-UP | `em_followup` |
| Recuperação | Recuperado | `recuperado` |
| todos | Fechado Ganho / Perdido | `fechado_ganho` / `fechado_perdido` |

¹ **`respondeu`, e não `em_conversa`.** É a key que `advance_deal_on_reply` já procura
(`COLD_RESPONDEU_KEY`, `leads/service.py:1192`). Adotá-la faz o movimento automático de
D2 funcionar **sem escrever uma linha de backend**. O rótulo visível continua sendo
"Em conversa" — `label` e `key` são coisas diferentes, e é exatamente para isso.

² **`ja_chamado` — analisado consumidor a consumidor; a conclusão inverteu.**
`move_deal_to_stage_key` grava `deals.stage = key` (`leads/service.py:1309`), e
`deals.stage='ja_chamado'` tem quatro leitores. Examinando cada um, **a semântica bate**:
um card no funil de reposição *é* um cliente ativo.

| leitor | o que faz | é desejável p/ reposição? |
|---|---|---|
| `broadcast/router.py:134,174` | não enfileira disparo frio de prospecção | **sim** — não se faz pitch frio a cliente ativo |
| `tools.py:968` | impede `registrar_sem_interesse_atual` de marcar Perdido (guardrail do caso Kadi Guth) | **sim** — "não quero agora" de cliente não é lead perdido |
| `processor.py:1692` | passa `lead_is_customer: True` ao prompt da ValerIA | **sim** — não roda funil de lead novo com quem já compra |
| `tools.py:1682` via `_lead_had_prior_handoff` | faz a ValerIA usar `retomar_contato_vendedor` em vez de `encaminhar_humano` | **sim** — é literalmente uma retomada |

⚠ **O problema real é outro, e é sério: o sinal nunca se apaga.** O `PATCH` do Kanban
(`api/deals/[id]/route.ts`) escreve `stage_id` e `closed_at` — **nunca `deals.stage`**.
Então, uma vez gravado `ja_chamado`, arrastar o card para Perdido **não limpa nada**: o
lead fica marcado como "relacionamento ativo" para sempre — nunca mais recebe disparo
frio, nunca mais pode ser marcado perdido pela ValerIA. O código já reconhece a
podridão: *"estágio real 'Perdido' carregam stage='novo'/'ja_chamado'"*
(`leads/service.py:273`). Adotar a key para 694 cards aprofunda isso.

**Recomendação: usar `chamado_reposicao`**, uma key que nenhum outro consumidor lê. Os
quatro comportamentos desejáveis acima podem ser obtidos depois, de propósito e com
critério de saída, em vez de herdados por acidente de uma coluna legada que ninguém
limpa. Adotar `ja_chamado` só faz sentido junto com sincronizar `deals.stage` no PATCH do
Kanban — e isso é escopo de outro trabalho.

**Renomeações que faltam** (rótulo, não movimento de card — barato e sem risco de FK):

| Funil | Hoje | Vira |
|---|---|---|
| Private Label | "Contato" (150 cards) | "Em conversa" |
| Reposição | "Em Conversa" (694 cards) | **"Já chamado"** (D4) |
| Reposição | "Em ATENÇÃO" | "Em atenção" (caixa) |

⚠ A "Em Conversa" da Reposição **não é** a mesma coisa que a "Em conversa" dos funis de
1ª compra: lá significa *o lead respondeu*, aqui significa *já foi chamado neste ciclo*.
Manter o mesmo rótulo nos dois faria a tela de configuração de esteira mentir. Por isso a
renomeação para "Já chamado" é obrigatória, não cosmética.

Trabalho do bloco:

1. Migration que **move os cards antes de apagar** as etapas ("Proposta"/"Negociação"
   do Private Label, 27 cards → "Em conversa"). Sem isso: FK 23503.
2. Migration que atribui as `key` da tabela acima e **recria a `proposta_enviada` do
   funil Reposição**, hoje perdida.
3. Criar "Em atenção" nos funis de 1ª compra e reordenar `order_index` sem buracos.
   **"Em atenção" entra logo depois de "Em conversa" e antes de "Proposta Enviada"**, e a
   migration precisa asseverar
   `order_index(Novo) < order_index(Em conversa) < order_index(Em atenção) < order_index(proposta_enviada) < order_index(fechado_*)`
   — se "Em conversa" ficar com `order_index` ≥ o de `proposta_enviada`, o movimento do
   orçamento para de funcionar **em silêncio** (`quotes/router.py:281` devolve `False`).
4. Marcar `is_protected=true` em Fechado Ganho e Perdido nos 5 funis (hoje **nenhuma**
   etapa é protegida).
5. Fazer o `POST /api/pipelines/[id]/stages` aceitar `key`, e o `DELETE` recusar apagar
   etapa que tenha `key` não nula. Trocar o template de funil novo
   (`api/pipelines/route.ts:15-23`) para o esquema da reunião.
6. **Reclassificar os 363 cards** de "Novo" cujo lead já falou no número do João
   (§2.3 item 6). O critério é `EXISTS (mensagem role='user' em conversa de canal
   `mode='human'`)` — **não** "quem falou por último", que classificaria errado todo lead
   que o João respondeu por último.
7. **Fechar os 38 cards fechados parados em etapas sem `key`** (§2.3 item 7), senão a
   esteira os trata como abertos.
8. Trocar a constante `DEAL_STAGES` do frontend (`lib/constants.ts:9-20`), que ainda
   lista `contato`/`proposta`/`negociacao` e **alimenta o dropdown que grava a key alvo
   das cadências** (`cadence-trigger-config.tsx:14-16`) — hoje ela oferece para
   configuração etapas que vão deixar de existir.
9. Terminar a migration com `NOTIFY pgrst, 'reload schema'` — sem isso o CRM responde
   PGRST204 com a coluna já existindo.

**`conversion_event` fica NULL em todas as etapas novas.** Preencher esse campo despacha
o card para a Meta CAPI e para o CSV do Google Ads; a migration `20260909` documenta por
que isso contamina a série "Conversões (Ads)". Não repetir.

**Critério de pronto:** um card arrastado para "Em conversa" em qualquer funil do João
tem `key='respondeu'`; um orçamento criado move o card em todos os 5 funis; nenhum deal
órfão; suíte verde.

### SP1 — Motor do funil de 1ª compra (Atacado + Private Label)

Duas esteiras sobre o mesmo motor, mudando só as mensagens (D12).

**Esteira "Novo"** — o João mandou algo e o lead não respondeu.
Primeiro toque em **36h** (D6). Se o lead responder, o reflexo já existente move o card
para "Em conversa" e esta esteira encerra.

**Esteira "Em conversa"** — 7 toques em 30 dias (D14), reset a cada resposta,
terminal em "Em atenção".

Lacunas a construir (nenhuma existe hoje):

| Lacuna | Onde | Por quê |
|---|---|---|
| **Prazo em horas** | RPC `get_deals_stage_stagnant` usa `make_interval(days => …)` (`20260904:254`) | 36h não é representável em dias |
| **Reset de matrícula** | não existe primitivo: `current_node_id` só anda para frente (`engine.py:364-375`) | D7 é a decisão central da esteira e o motor não a suporta |
| **Reentrada após resposta** | `on_reply='cancel'` + cooldown de 90 dias na RPC trancam o card para fora | é o oposto de "reseta e continua" |
| **Cooldown por esteira** | `p_cooldown_days` existe mas `triggers.py:264-281` nunca o passa — é sempre 90 | prazos de 3, 15 e 45 dias são incompatíveis com 90 |
| **Corte de arranque** | RPC não tem parâmetro de "só a partir de" | é o que implementa D15 |
| **Laço de N toques** | o grafo é linear, sem laço; `step_count` conta nós, não toques | 7 toques hoje = 14 nós escritos à mão |

**Sobre o reset (a decisão de arquitetura deste bloco).** Duas saídas:

- **(a) Primitivo `reset_enrollment`** — `handle_campaign_reply` rebobina
  `current_node_id` para o primeiro nó e zera `step_count`. Mais fiel a D7; exige que o
  reply handler passe a conhecer o primeiro nó da campanha, que hoje ele não conhece.
- **(b) Cancelar + reinscrever** — `on_reply='cancel'` com o cooldown excluído para esta
  esteira. Reaproveita o que existe; mas o card volta pela porta da frente e a métrica de
  "quantos toques este lead já levou" se perde a cada resposta.

**Recomendação: (a).** O reset é o coração da esteira, e (b) transforma o histórico de
toques em algo não auditável — justamente o número que decide a ida para "Em atenção".

⚠ **Armadilhas do reflexo automático** (`advance_deal_on_reply`, hoje em produção):
- **Reação com emoji move o card.** O gate de reação isolada só aparece 87 linhas depois
  (`processor.py:1453`). Um 👍 contaria como "respondeu" e resetaria a esteira.
- **Clique no botão de opt-out move o card.** O reflexo (`:1366`) roda **antes** do
  opt-out determinístico.
- **`get_open_deal` pega o card mais recente do lead**, não o card certo — com Reposição
  e Recuperação gerando cards novos, o reflexo pode mover o card errado.
- **O movimento é mudo:** não emite `deal_stage_enter` (único emissor:
  `api/deals/[id]/route.ts:99`). Qualquer esteira com gatilho de evento de etapa **não
  dispara** quando o lead responde — as esteiras dependem exclusivamente do polling.

### SP2 — Ciclo de reposição (45 dias)

**Estado real:** `ensure_reposicao_deal` existe e está em produção, mas a **entrega é
zero** — não há um único deal de reposição no funil "João - Reposição"; os 19 que a
automação criou estão no funil errado. Dos 4 caminhos que fecham venda, só 2 chamam o
hook; o caminho Bling (`create_order`) e `upsert_from_bling` (1.021 das 1.155 vendas)
não chamam nada.

Trabalho:

1. **Marco zero editável.** Nenhuma coluna guarda "quando este lead virou Fechado Ganho"
   de forma editável (`closed_at` é escrito por 4 caminhos e não é editável na UI;
   `expected_close_date` é editável e **ninguém lê**). Criar `deals.reposicao_em`
   (timestamptz, editável no card) — é o "45 dias mas opção do João editar" de D5.
2. **Fechar os caminhos de venda** que não chamam o hook, e escopar o `dedupe_open` ao
   pipeline de reposição (hoje ele reaproveita qualquer card aberto do lead, inclusive o
   de handoff da ValerIA em outro funil).
3. **Cadência 45 → +3 → 15/15**, com o primeiro toque diferente dos seguintes (o seed
   atual é 15/15/15).
4. **Terminal em "Em atenção"**, não em Perdido automático — a etapa já existe no funil
   Reposição. Isto substitui a regra de 04/09 que mandava o card sozinho para Perdido.
5. **Alerta no card no dia** (D5). Não existe nenhuma estrutura para isso: `system_alerts`
   é banner global sem coluna de deal, e não há tabela de tarefas nem `due_date`. Menor
   caminho: uma coluna em `deals` lida pelo Kanban.

⚠ A RPC de estagnação **exclui explicitamente** cards em `fechado_ganho` (`20260904:172`).
A reposição ancorada no Fechado Ganho **não é observável por ela** — precisa de gatilho
próprio sobre `deals.reposicao_em`.

### SP3 — "Em atenção" e o churn com motivo

"Em atenção" **não existe em lugar nenhum do repositório** (zero ocorrências). Como
etapa (D13), o Kanban a renderiza de graça. Falta:

1. **A lista fechada de motivos de churn.** `deals.lost_reason` existe desde
   `009_deals.sql:15`, é **texto livre, opcional**, e é capturado por **um único**
   caminho de UI (arrastar o card para a coluna `fechado_perdido` em `/vendas`). Os
   outros 4 caminhos que fecham um deal gravam motivo vazio ou string livre do LLM.
2. **A UI de classificação:** o João abre o card em Em atenção e escolhe *voltar à
   esteira* / *mandar para Recuperação* / *churn com motivo*. O painel lateral do deal
   hoje não tem nem seletor de etapa.
3. **Corrigir `mark_deal_lost`**, que move o deal **mais recente** do lead em vez do deal
   do enrollment. Bug **vivo em produção**; a branch corrige o caso `deal_id` e deixa o
   irmão gêmeo (`deal_value`).
4. **Incluir `em_atencao` na lista de etapas fechadas da RPC** (`20260904:172`), senão um
   card em Em atenção continua elegível como card aberto e a esteira o pega de volta.

### SP4 — Os dois funis de recuperação

Quem **já comprou** e quem **nunca comprou** têm esteiras diferentes (D10).

1. **Cadência**: ver a contradição em §3.4 — decisão pendente do Arthur.
2. **Com botão** (D8), diferente dos funis de 1ª compra.
3. **Saída por orçamento (D11)**: não existe gatilho de "orçamento criado" em
   `fire_trigger` (`triggers.py:103-162`), e `_move_deal_to_proposal` **nunca troca de
   pipeline** — lê o `pipeline_id` do próprio deal e só faz UPDATE de `stage_id`. Mover
   de Recuperação para Reposição é **impossível hoje**; é código novo.
4. ⚠ **O marco do orçamento nunca foi exercido — nem uma vez.**
   **Medido: a tabela `quotes` tem ZERO linhas em produção.** Os 9 cards em "Proposta
   Enviada" nos funis do João chegaram lá **por arrasto**. O gancho técnico existe e
   funciona (`quotes/router.py:249-287`), mas:
   - `_move_deal_to_proposal` só roda `if body.deal_id:` (`quotes/router.py:493`);
   - o seletor "Oportunidade" do modal **nasce em "Não vincular"**
     (`quote-create-modal.tsx:154`) e nenhum call site passa `lockedDealId`;
   - o `PUT` grava `deal_id` mas **não move o card** (`:562-579`).

   **Isto é o achado mais consequente do documento para a reunião:** D3 elegeu como
   *único* marco válido um mecanismo que **nunca foi usado**. O problema é **adoção, não
   código** — e sem resolvê-lo, D3 é letra morta e a esteira de proposta nunca dispara
   pelo motivo certo.

   **Proposta:** tornar o vínculo obrigatório **com resolução automática do deal** —
   preencher `deal_id` com o card aberto do funil do vendedor (não com `get_open_deal`,
   que pega o mais recente de qualquer funil), exibir o nome do funil no dropdown (hoje
   ele lista deals de todos os funis sem filtro de `closed_at`, mostrando só `d.title` —
   duas linhas visualmente idênticas), e combinar com o João um plano de adoção. Sem
   plano de adoção, nenhuma mudança de código resolve.

---

## 5. Guardrails — o que toda esteira honra

Em produção, o nó `send` das cadências (`campaigns/worker.py::_execute_send_node`) **não
checa blacklist/opt-out, não checa template aprovado e não checa número errado.** A única
trava de blacklist do sistema vive no broadcast. E `apply_optout_side_effects` **não
cancela enrollments** — um opt-out no meio de uma cadência deixa o próximo toque armado.

A branch `feat/esteiras-vendedor` corrige exatamente esses buracos. **Nada disso está
publicado.** Portanto:

> **Nenhuma esteira liga antes de a camada de guardrails da branch estar em produção.**

Travas exigidas, por esteira: blacklist/opt-out no envio · template aprovado no disparo
(não só no "ligar") · `channel_id` obrigatório na campanha (sem ele o gate de "Finalizar
Conversa" devolve `False` de saída e a mensagem pode sair pelo número da ValerIA
assinada "aqui é o João") · `frequency_cap` de 1 msg/lead/dia · janela comercial
7h-18h BRT · corte de arranque (D15).

Variáveis de template: a lista é **fechada** e resolvida por igualdade exata —
`{{primeiro_nome}}`, `{{nome_completo}}`, `{{telefone}}`, `{{empresa}}`. `{{nome}}` e
`{{vendedor}}` iriam **literalmente** para o cliente. Template com `{{1}}`/`{{2}}` exige
`__params_type__: "positional"`, senão a Meta recusa.

**Opt-out — o furo do canal humano.** Hoje só três trechos gravam `leads.opt_out`, e
nenhum cobre o público do vendedor em produção. O casamento é por **igualdade
normalizada** contra dois rótulos exatos: *"me tira dessa lista"* digitado para o João
não produz nada. Como D8 tira o botão do funil de 1ª compra, **esse público não tem
nenhuma saída digna** — é lacuna a resolver no SP1, não detalhe.

⚠ **Regressão de merge — rastreada ponta a ponta, a corrigir antes de qualquer push.**
Com a branch mergeada, o opt-out determinístico das esteiras (`processor.py:1390`) roda
**antes** do gate do agente de botões (`:1483`). Como o rótulo do botão de saída do bot é
exatamente *"Parar mensagens"* (`button_flow/flows.py:95`), um clique passa pelos **dois**
caminhos:

```
processor.py:1390  handle_optout_reply
   → campaigns/worker.py:288   apply_optout_side_effects
   → leads/service.py:1594     move_lead_deals_to_blacklist  (service.py:1458)
        UPDATE deals SET pipeline_id = BLACKLIST  em TODOS os deals do lead
processor.py:1483  run_button_flow
   → button_flow/effects.py:115  _aplicar_optout
   → button_flow/effects.py:226  _mover_deal
        if pipeline_id != PIPELINE_RECUPERACAO: return False   ← agora recusa
```

A etapa "Descadastrado" nunca recebe ninguém — exatamente a regressão que
`effects.py:147-158` declara ter consertado. **Nenhum teste cobre essa coexistência.**
Há **uma** superfície de colisão hoje, não duas: `"Não tenho interesse"` aparece só em
comentário (`flows.py:9,12`); todas as trilhas ativas usam `BTN_OPTOUT`.

### 5.1 Dois bugs de produção encontrados no caminho (fora do escopo, mas adjacentes)

Nenhum dos dois foi introduzido pela branch — ambos estão em `origin/master` hoje.

1. **O opt-out de higiene de "número errado" nunca acontece.**
   `broadcast/worker.py:1004` chama `apply_optout_side_effects(lead_id)` com **um**
   argumento; a assinatura exige três (`leads/service.py:1594`). O `TypeError` é
   capturado pelo `except` do laço (`:1013`), então a varredura continua e loga
   `[WRONG NUMBER] falha ao processar lead …` — mas **nenhum lead marcado como número
   errado vira opt-out**. Importa aqui porque "número errado" é um dos motivos de parada
   que as esteiras precisam honrar.

2. **`mark_deal_lost` não grava `closed_at`.** O `update` é só
   `{"stage_id": …}` + `lost_reason` opcional (`automation/engine.py:570-574`). Um card
   mandado para Perdido pela automação continua com `closed_at NULL` e **segue contando
   como card aberto** em toda consulta que filtra por `closed_at is null` — inclusive as
   das esteiras. O mesmo vale para `move_lead_deals_to_blacklist`, que troca o
   `pipeline_id` de todos os deals do lead sem fechar nenhum.

---

## 6. Riscos, por gravidade

| # | Risco | Como se manifesta | O que evita |
|---|---|---|---|
| 1 | Ligar esteira antes dos guardrails | mensagem automática para quem pediu para sair, do número que fecha venda | ordem dos blocos: guardrails antes de qualquer esteira |
| 2 | `UPDATE` em massa de `stage_id` na migração | cancela toda esteira em andamento cujo guard aponte para a etapa antiga (`engine.py:150-177`) — a base inteira sai das cadências de uma vez | rodar o SP0 **antes** de ligar qualquer esteira |
| 3 | `stage_id` dentro de JSON não tem FK | apagar etapa vira no-op **silencioso** em `campaign_nodes.config` e `enrollments.metadata.guard`; o gatilho deixa de casar, sem log de erro | varrer os JSON na migração |
| 4 | Reordenação de `order_index` | card novo e handoff passam a nascer em "Perdido"; movimento do orçamento para em silêncio | `is_protected` + asserção de ordem no SP0 |
| 5 | `key='ja_chamado'` | todo card de reposição vira "tratativa humana em aberto" e bloqueia disparo frio | decidir §4/SP0 nota ² |
| 6 | `conversion_event` preenchido por engano | cards despachados para Meta CAPI / Google Ads, contaminando "Conversões (Ads)" | manter NULL |
| 7 | Volume no arranque | centenas de templates em poucos dias → quality rating do número do João | D15 (só fluxo novo) |
| 8 | Migrations não sobem no deploy | o GitHub Actions sobe imagem; `20260904` e as novas são aplicadas à mão | checklist do dono (§8) |

---

## 7. Fora de escopo

- Esteira do "lead esperando resposta nossa" (18 casos — §1.2).
- Reescrever o motor de cadências. Todo o trabalho é **em cima** dele.
- Ciclo médio de recompra **por lead ou por produto** — só existe média por vendedor
  (`get_avg_repurchase_cycle_days`, 51 dias na base; NULL para o João). Os 45 dias são
  parâmetro fixo editável, não cálculo.
- Migrar o passivo de 1.488 cards para as esteiras (D15). Ele é assunto do SP4.
- Substituir a ValerIA no atendimento do lead do João (descartado em 03/09, risco do
  caso Marcella).

---

## 8. Pendências do dono (nada disso é código)

1. **Decidir a cadência da Recuperação** — a contradição de §3.4.
2. ~~Decidir a key `ja_chamado`~~ — **resolvido por análise** (§4/SP0 nota ²):
   usar `chamado_reposicao`. Só confirmar que concorda.
3. **Revisar e aplicar à mão** a migration do SP0 (mexe no funil de trabalho do vendedor).
4. **Aplicar `20260904_esteiras_vendedor.sql`** — hoje `deals.entered_stage_at` e
   `campaigns.audience` não existem no banco, e sem elas o motor de cadências inteiro
   para.
5. **Submeter e aguardar aprovação dos templates.** Consultei a WABA: **zero** templates
   `esteira_*` existem. Conferir o **locale aprovado** de cada um — `automacao_valeria_to_joao`
   foi aprovado só em `en` e o `pt_BR` causou 404 #132001 com job cancelado sem entregar.
6. **Combinar com o João o uso do `/orcamento`** — `quotes` tem **zero** linhas
   (§4/SP4 item 4). Sem adoção, D3 é letra morta e nenhuma mudança de código a salva.
7. **Ligar uma esteira de cada vez**, observando o volume do primeiro dia.

---

## 9. Estado da base

Branch de trabalho: `feat/followup-vendedor` (= `feat/esteiras-vendedor` + `origin/master`
mergeada), em worktree isolado. Merge **sem conflitos**. `origin/master` = `cb88be30`.

Portões do `deploy.yml` reproduzidos localmente:

| portão | resultado |
|---|---|
| backend — `pytest -m "not integration"` | **4186 passed, 4 skipped** (rodei a suíte inteira, que é superconjunto) |
| frontend — `npm ci` | 870 pacotes, limpo |
| frontend — `npm run type-check` (`tsc --noEmit`) | **sem erros** |
| frontend — `npm run test` | **753 passed em 57 arquivos**, incluindo `esteiras-tab.test.tsx` (19) |
| frontend — `npm run build` | **compila limpo** (mesmos placeholders do CI), 0 erros |

A base está sã. O que falta não é código existente quebrado — é o que ainda não existe.

O que se reaproveita da branch de 04/09, sem reescrever: `deals.entered_stage_at` e o
trigger que o mantém · `campaigns.audience` (`ia|humano|ambos`), que remove o veto
histórico a `ai_enabled=False` · o gatilho `deal_stage_stagnation` e sua RPC · a guarda
de etapa no enrollment · a tela `/campanhas > Esteiras` · e os quatro bugs já caçados
(estado terminal ausente, fila envenenada, `on_reply` cego em nó `wait`, opt-out sem
blacklist).

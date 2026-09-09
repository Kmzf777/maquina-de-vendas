# ValerIA Recuperação — agente de botões para o funil Reativação Bling

**Data:** 2026-09-09 · **Branch:** `feat/valeria-recuperacao-botoes` · **Base:** `origin/master = 537e0519`
**Substitui/estende:** `docs/superpowers/specs/2026-08-20-bot-botoes-reativacao-design.md` (cujo código já foi
mergeado nesta branch — ver §10)
**Pesquisa de apoio:** 14 relatórios + dossiê consolidado (scratchpad da sessão), sobre 53k mensagens de
produção, 1.208 leads da coorte, 72 templates da WABA ao vivo e a documentação da Meta.

---

## 1. Problema

O funil **Reativação Bling** (`b2f9c31d-8a47-4e26-95c0-3d7a1f6e8b09`) tem **1.208 leads** importados do ERP
Bling em 14/08/2026, atribuídos ao João. Eles já faturaram **R$ 1.951.716** historicamente. Desde a
importação, o funil está **intocado**: os 1.208 deals seguem em `stage='novo'`, `value=0`,
`assigned_to=NULL`, sem um único movimento.

Enquanto isso, o mesmo João, trabalhando a base antiga **à mão** no funil `João - Reposição`, fechou
**R$ 155.167,76 em 103 vendas entre 30/07 e 04/09** — ticket médio R$ 1.506,48. O tráfego pago, no mesmo
período, fez R$ 1.068 com ROAS 0,27.

O gargalo não é a capacidade de vender. É que ninguém **reabre** conversa dormente: em 5 meses e 6.533
mensagens, o maior intervalo que o João deixou passar antes de escrever foi **23h58m** — ele só responde,
nunca inicia. Fez 8 cutucadas em 5 meses (todas responderam) e deixou **136 leads (12,1%) sem nenhuma
resposta**.

## 2. O que vamos construir

Um agente **determinístico dirigido por botões** que:

1. abre a conversa com um **template aprovado com 3 quick replies**, no **número do próprio João**;
2. captura a intenção em **um toque**, sem LLM e sem persona;
3. entrega o lead ao João **na mesma thread, no mesmo número**, com o produto e o preço já na tela;
4. honra opt-out **imediatamente e de forma auditável**;
5. agenda recontato para quem só quer tempo.

Ele **não é uma terceira persona da ValerIA**. É uma espécie nova de agente, num eixo ortogonal.

### 2.1 Fora de escopo (v1)

- Worker de re-disparo automático a partir de `recontatar_em` (fase 2 — a data fica gravada).
- Métricas por botão na UI de broadcast (v1 usa SQL direto).
- Bolha de clique renderizada no `/conversas` (o chat mostra o texto do botão; o chip é cosmético).
- Ampliar o catálogo do agente além dos 32 SKUs ativos.
- **Disparo real para os 1.208 leads** — a v1 entrega a máquina pronta e o piloto preparado; apertar o
  botão é decisão do dono, com os gates da §8.

## 3. As cinco decisões estruturantes

### D1 — É um `kind` de agente, não um `prompt_key`

`agent_profiles.kind = 'button_flow'`, **não** `prompt_key='valeria_recuperacao'`.

Um terceiro `prompt_key` obrigaria a tocar 8 pontos que só conhecem duas personas (`agent/persona.py:26-27`,
`buffer/processor.py:347-356`, `agent/orchestrator.py:736-737,990`, `templates/intent.py:48`,
`prompts/__init__.py:47`) — e **ainda assim não funcionaria**, porque `_resolve_agent_profile_id`
(`processor.py:334-356`) recomputa a persona do histórico a cada turno e sobrescreveria o pin do disparo.
Pior: `get_stage_prompts` (`prompts/__init__.py:47`) faz
`PROMPT_REGISTRY.get(key, PROMPT_REGISTRY["valeria_inbound"])` — uma chave desconhecida vira **ValerIA
inbound sem erro e sem log**, e 1.208 leads do Bling receberiam a persona errada silenciosamente.

O eixo `kind` é ortogonal e não encosta em nenhum desses pontos.

### D2 — Roda no número do João, com o gate ANTES do gate de canal humano

Canal `a3a607b1-6bff-4370-8609-b275eef270dd` (`553491461669`, `mode='human'`).

- A troca de número no handoff é o maior vazamento medido do funil: **131 de 500 leads (26%) não fazem o
  esforço de migrar** (Diagnóstico 01/09, p.5). Rodar no número do João **elimina o degrau inteiro**.
- O caminho mais curto do dataset até a venda foi exatamente esse: clique às 16:58:19 → João responde na
  mesma thread às 16:59:33 (**74 s**) → venda de R$ 470.
- No número da ValerIA (`owner_user_id = NULL`), a policy RLS `conversations_select_scope` faz o **João não
  conseguir abrir nenhuma dessas conversas** em `/conversas`.
- Os templates aprovados já dizem *"aqui é o João"*.

O bloqueio técnico (`processor.py:1430` mata tudo em `mode='human'`) é resolvido pela **posição** do gate:
depois do gate de reação isolada (`:1421-1427`), **antes** do gate de canal humano. A justificativa é
substantiva, não um contorno: **um fluxo fechado de botões não é IA generativa** — todo texto que sai está
declarado em `flows.py`, revisado uma vez, versionado em código.

**Efeito colateral que dissolve um bloqueio inteiro:** o gate também fica antes de `VALERIA_ENABLED`
(`:1439`) e de `lead.ai_enabled` (`:1447`). Portanto **ninguém precisa ligar `ai_enabled` nos 1.208 leads** —
eles seguem `false`, e a ValerIA continua sem acesso ao número do João.

### D3 — Orçar como MARKETING; UTILITY só onde ela é honesta

Disfarçar reativação de UTILITY **já falhou empiricamente nesta conta**: a Meta reclassificou **28 de 28**
templates de `UTILITY → MARKETING` (campo `previous_category` na Graph API ao vivo). A doc é literal:
*"Retargeting… These are marketing even if requested by users"*, e *"welcome back"* é explicitamente
desqualificado de Utility.

Preço Brasil: **MARKETING $0,0625/msg · UTILITY $0,008 · SERVICE dentro da janela $0,00** (até 30/09/2026).
Custo total da onda 1: **≈ US$ 58 ≈ R$ 315** — irrisório contra R$ 155 mil. **Não otimize custo de template;
otimize qualidade do número.**

UTILITY é honesta em exatamente dois lugares: a trilha do **pedido não faturado** (existe pedido real
pendente) e a trilha de **higienização de cadastro** (não vende nada).

### D4 — O menu pergunta um ESTADO, não pede um COMPROMISSO

O dado mais forte da base sobre desenho de botão:

| Template | Pergunta | Respostas | Positivo | Taxa de resposta |
|---|---|---:|---:|---:|
| `utilidade_22_04_2026_16_40` | *"Falo com {{1}} neste número?"* (estado) | 184 | **104 (74%)** | **33,5%** |
| `utilidade_cafeteria_data_v1` | *"conversa pausada, continuar?"* (compromisso) | 52 | 10 | 9,8% |
| `utilidade_geral_produto_v1` | *"pedido em aberto, continuar?"* (compromisso) | 51 | 9 | 8,6% |

O trio atual (`Continuar atendimento` / `Tirar duvidas` / `Nao tenho interesse`) tem três defeitos medidos:
`Tirar duvidas` é **botão morto** (4 cliques em ~1.300 envios, 0,3%); `Nao tenho interesse` captura gente
que só queria dizer "agora não" (**41% continuaram conversando, 2 compraram depois**); e o trio produz
**2,2× mais recusas do que aceites**.

Menu novo: **`Preciso repor` · `Ainda tenho estoque` · `Parar mensagens`** — um avanço, um **adiamento que
preserva o lead**, e uma saída digna e inequívoca.

### D5 — Texto livre é caminho de primeira classe, e texto de saída VIRA opt-out

No broadcast mais limpo que existe (29/07, 494 entregues, 60 respostas): **24 clicaram botão, 36 digitaram
texto livre — 60% dos respondentes digitam.** Uma máquina de estados pura entende 40% e trava nos outros 60%.

E há uma obrigação legal: hoje **52 pessoas clicaram "Nao tenho interesse" e seguem com `opt_out = false`**.
Elas estão elegíveis para a próxima campanha. Isso é violação prática de LGPD e da Business Messaging Policy
da Meta — e *blocks derrubam a qualidade do número muito mais do que opt-outs*.

Portanto: uma **camada 2 de LLM estreito** — uma classificação, 6 classes, ~300 tokens, **zero geração de
prosa**. Ela não conversa; lê o texto e devolve uma das mesmas `Decisao` que o motor determinístico produz.

E antes dela, uma **camada 1.5**: ~47% desse "texto livre" (17 de 36) é **robô de saudação do WhatsApp
Business do próprio cliente** — 28% de todas as respostas. Responder isso é robô conversando com robô.

## 4. Arquitetura

```
┌── CAMADA 0 — DISPARO (fora da janela de 24h) ────────────────────────────────┐
│  template aprovado com 3 QUICK_REPLY + payload custom por botão              │
│  canal: NUMERO JOÃO (a3a607b1) · agent_profile: kind='button_flow'           │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │  o lead toca um botão → ABRE a janela de 24h
                               ▼
┌── GATE em processor.py ~1428 (ANTES do gate de canal humano :1430) ──────────┐
│  is_button_flow_conversation() → run_button_flow()                           │
│  ⇒ funciona em mode='human' ⇒ dispensa ai_enabled ⇒ ValerIA fica fora        │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               ▼
┌── CAMADA 1 — DETERMINÍSTICA (~40% dos turnos · ZERO token) ──────────────────┐
│  engine.decidir(flow_state, Clique) -> Decisao                               │
│  todo texto de saída declarado em flows.py · nunca gerado                    │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │  evento é Texto, não Clique
                               ▼
┌── CAMADA 1.5 — DETECTOR DE AUTORESPONDER (28% das "respostas") ──────────────┐
│  U+200E · lag<3min · regex · menu numerado ⇒ NÃO responde, NÃO gasta nudge   │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               ▼
┌── CAMADA 2 — CLASSIFICADOR LLM ESTREITO (~60% dos turnos · ~300 tok) ────────┐
│  1 chamada · JSON mode · 6 classes · ZERO geração de prosa                   │
│  SAIR · QUENTE · ADIAR · PERGUNTA · ENGANO · RUIDO → mesma Decisao           │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               ▼
┌── CAMADA 3 — O JOÃO, na MESMA thread, no MESMO número ───────────────────────┘
```

**Por que não é uma ValerIA:** sem `BASE_STATIC` (82.165 chars ≈ 20.541 tokens), sem catálogo injetado, sem
persona, sem loop de tool-calling, sem humanizer, sem bubble splitter. O turno modal custa **0 tokens**; o de
exceção custa ~300 — contra os **35.565 tokens de input médios** que a ValerIA gasta hoje por turno.

## 5. Componentes

| Módulo | Responsabilidade | Depende de |
|---|---|---|
| `button_flow/flows.py` | **dados puros**: nós, botões, rótulos, textos, tags. Leaf module. | — |
| `button_flow/engine.py` | **decisão pura**: `decidir(estado, evento) -> Decisao`. Sem I/O, sem relógio. | `flows` |
| `button_flow/autoreply.py` | detecta autoresponder do cliente. **Função pura.** | — |
| `button_flow/classifier.py` | 1 chamada LLM → 1 de 6 classes. Sem prosa. | `gemini_client` |
| `button_flow/effects.py` | aplica no CRM: tags, opt-out, handoff, recontato. **Todo o I/O de escrita.** | `leads`, `conversations`, `handoff` |
| `button_flow/runner.py` | orquestra: lê `flow_state` → decide → envia → efeitos → grava. | todos acima |
| `button_flow/config.py` | env vars (`os.getenv`, nunca `Settings` — ver §9) | — |

Fronteira: `engine` é testável com a matriz completa de casos **sem nenhum mock**; `runner` é o único que
sabe o que é um banco ou uma rede.

## 6. O fluxo

### 6.1 Templates de primeiro toque

Todos **pt_BR**, 3 QUICK_REPLY, rótulos **≤ 20 chars** (para servirem também na interativa, cujo limite é 20;
o do template é 25). Nome **sem a substring `reativ`** — senão `_hot_lead_guardrail`
(`broadcast/worker.py:991-1022`, disparado por `templates/intent.py:22-23` `_COLD_SUBSTRINGS = ("reativ",)`)
bloqueia silenciosamente os **208 leads que têm venda em `sales`** — a parte mais valiosa da lista.

**T-A · `recuperacao_pedido_v1` — `pedido_sem_faturar` (62) — UTILITY**
```
Olá, {{1}}! Aqui é o João, do Café Canastra.
Consta no nosso sistema um pedido seu de {{2}} que não chegou a ser faturado,
e ninguém te retornou depois disso.
Quer que eu retome esse pedido de onde parou?
[ Retomar o pedido ]  [ Quero outro item ]  [ Parar mensagens ]
```

**T-B · `recuperacao_estoque_v1` — inativos 3-36m (303) — MARKETING**
```
Olá, {{1}}! Aqui é o João, do Café Canastra.
Vi aqui no cadastro que a última compra da {{2}} com a gente foi em {{3}} — {{4}}.
Como está o estoque de café por aí hoje?
[ Preciso repor ]  [ Ainda tenho estoque ]  [ Parar mensagens ]
```
Carrega as duas alavancas maiores: **memória concreta** e **pergunta de estado**. Todo fato afirmado tem
lastro em `sales`/CSV do Bling.

**T-C · `recuperacao_cadastro_v1` — `inativo_36m_mais` (665) — UTILITY, NÃO VENDE**
```
Olá, {{1}}! Aqui é o João, do Café Canastra.
Estamos atualizando nosso cadastro de clientes e o da {{2}} consta sem
movimentação desde {{3}}.
Seguimos mantendo seu contato ativo por aqui?
[ Manter cadastro ]  [ Atualizar dados ]  [ Parar mensagens ]
```
Modelado em `utilidade_joao_cadastro_movimentacao`, que **continua UTILITY na Meta**.

**T-D · `recuperacao_lembrete_v1` — toque D+4 — MARKETING**
```
Olá, {{1}}! Ainda é o João, do Café Canastra.
Minha mensagem de {{2}} ficou sem resposta e não quero te incomodar à toa.
Me dá só um sinal pra eu saber como seguir?
[ Preciso repor ]  [ Ainda tenho estoque ]  [ Parar mensagens ]
```
Nome diferente é **obrigatório**: `_template_dedup_guardrail` (14 dias por `(lead, template)`) pularia um
reenvio do mesmo nome silenciosamente.

> ⚠️ **Não reutilizar** `check_estoque_reposicao` nem `lembrete_reposicao_final`: têm o texto
> **permanentemente corrompido na Meta** (bytes `U+003F` gravados, não mojibake de console — inclusive nos
> rótulos: `N?o atendo mais`). Não é editável; teria de ser recriado.

### 6.2 Rótulos e ids

| Nível | Trilha | Rótulo | chars | `button_id` |
|---|---|---|---:|---|
| 1 | B, D | `Preciso repor` | 13 | `repor` |
| 1 | A | `Retomar o pedido` | 16 | `repor` |
| 1 | C | `Manter cadastro` | 15 | `manter` |
| 1 | B, D | `Ainda tenho estoque` | 19 | `adiar` |
| 1 | A | `Quero outro item` | 16 | `adiar` |
| 1 | C | `Atualizar dados` | 15 | `atualizar` |
| 1 | todas | `Parar mensagens` | 15 | `optout` |
| 2 | — | `Em 30 dias` / `Em 60 dias` / `Em 90 dias` | 10 | `snooze30/60/90` |

Nível 2 em **30/60/90 dias** (não 1/3/6 meses): o intervalo médio entre compras desta coorte é **78-122
dias**.

### 6.3 Máquina de estados

Persistida em `conversations.flow_state jsonb` — **não em Redis**, porque precisa sobreviver a um FLUSHALL
(incidente de 07/06/2026).

```
AGUARDANDO_INTERESSE ──[repor]──────────► ENCERRADO (+ entrega + handoff)
   │                 ──[optout]─────────► ENCERRADO (+ opt-out)  [terminal, imutável]
   │                 ──[adiar]──────────► AGUARDANDO_PRAZO
   │                 ──[texto 1ª vez]───► reoferece botões (interactive) + nudged=true
   │                 ──[texto 2ª vez]───► ENCERRADO (+ tag humano, silencia IA)
   ▼
AGUARDANDO_PRAZO ────[snooze30/60/90]──► ENCERRADO (+ recontatar_em)
   │                 ──[texto]──────────► mesma regra de nudge
   ▼
ENCERRADO  (clique posterior: ignorado com log)
```

**Invariantes do motor** (já implementados e testados):
- `flow_state` de versão diferente ou corrompido → **devolve ao humano**, nunca reinicia. `jsonb` aceita
  escalar e array; tratar `[]` como "não iniciado" renudgearia o lead do zero.
- Clique num botão do fluxo **mas de outro nó** → ignorado, sem efeito e **sem consumir o nudge** — tocar de
  novo não é recusar os botões.
- Botão desconhecido no nível 1 → **retorno inerte**, nunca opt-out. (Antes o opt-out era o fall-through: um
  botão novo desligaria o lead sem ninguém pedir.)
- Falha ao gravar `opt_out=true` **bloqueia o avanço do nó** (fail-CLOSED). Todo o resto é fail-soft.

### 6.4 O clique positivo — o turno que decide o projeto

`Preciso repor` dispara, **numa bolha só, deterministicamente**:

```
perfeito, {primeiro_nome}
você levava {produto_top1} — hoje ele está R${preco_tabela} a unidade
já chamei o João aqui, ele te responde em instantes
```

- **Zero perguntas depois disso.** Autópsia: 14 leads morreram logo após a sequência
  `"cadastro confirmado"` + pergunta aberta; a última coisa que cada um disse foi apenas *"Sim"*. Abrir com
  ack de sistema **dobra a chance de matar a thread** (39% vs 18%) e **corta o handoff pela metade**
  (14% vs 27%).
- Entregar algo concreto é a maior alavanca medida: **1.130 de 1.626 leads (69,5%) nunca viram preço nem
  foto**; quem recebeu chegou ao vendedor em **73-75%** contra 56,5%.
- ⚠️ **Se `produto_top1` não casar com um dos 32 SKUs ativos** (141 leads compravam outras marcas, 123
  cápsula, 47 drip — o Bling tem 444 produtos): **reconhece o item pelo nome e NÃO cota preço.** Foi essa
  improvisação que perdeu as 500 unidades da Ritz (cotou drip a R$27,70 quando o real é R$2,49/sachê).
- Efeitos: tag `Reativação: Quente` · `handoff_system_marker` · deal → stage `Quer repor` ·
  `ai_enabled=false` · **sem cartão de contato** (é o número do próprio João).

### 6.5 Classificador (camada 2)

Uma chamada, `response_mime_type="application/json"`, ~300 tokens, saída de uma palavra. **Não escreve nada
para o cliente** — toda mensagem continua vindo de `flows.py`.

| Classe | Ação determinística |
|---|---|
| **SAIR** | mesmo efeito de `Parar mensagens` (opt-out completo) |
| **QUENTE** | mesmo efeito de `Preciso repor` (entrega + handoff) |
| **ADIAR** | vai para `AGUARDANDO_PRAZO`, oferece 30/60/90 |
| **ENGANO** | aborta o script comercial, desculpa fixa, oferece opt-out, marca `pretexto_contestado` |
| **PERGUNTA** | reoferece botões uma vez + tag humano → João |
| **RUIDO** | reoferece uma vez; na segunda, silêncio + tag humano |

**Desempates aprendidos de incidentes reais:**
- Dúvida entre **SAIR** e **ADIAR** → **ADIAR**. Nunca blacklist de quem só pediu tempo (Rafael Monteiro
  clicou opt-out e comprou R$ 2.490 depois; Verde Vale, R$ 1.178,90).
- Dúvida entre **QUENTE** e **PERGUNTA** → **QUENTE**. Transbordar é vitória; loop não é.
- *"obrigado"*, *"já compro com o João"*, *"acabei de repor"* **nunca** são SAIR.

**Ramificação por idade do clique** (30% chegam fora da janela; máximo observado **43 dias**):
`<24h` segue o fluxo · `24h-7d` reconhece e retoma · `>7d` recomeça limpo · e em qualquer caso, se o deal já
mudou de etapa ou `human_control=true`, **não roda** — só notifica o João.

**Fallback ≤ 2, sempre.** Duas incompreensões seguidas → tag humano + silencia + devolve ao João. **Nenhum nó
existe sem saída para humano ou para opt-out.**

## 7. Dados

### 7.1 Migration `20260909_recuperacao_stages_optout.sql`

- 3 stages de desfecho no funil (order_index 8, 9, 10): `quer_repor` "Quer repor"
  (`conversion_event`=sim), `recontato_agendado` "Recontato agendado", `descadastrado` "Descadastrado".
- `leads.opt_out_at timestamptz`, `leads.opt_out_channel text`, `leads.opt_out_evidence jsonb` — hoje
  `opt_out` é um booleano nu, insuficiente para defender um LIA na ANPD.
- Backfill de `leads.metadata` com `produto_top1`, `cidade_uf`, `ticket_medio`, `data_ultima_compra`,
  `dias_sem_comprar` — hoje esses dados **só existem como texto livre em `lead_notes`**. Fonte preferida: o
  CSV `leads-bling-completo-2026-08-08-br (1).csv` joinado por `metadata.id_bling` (**match 100%**), muito
  mais robusto que parsear nota. **Sem isso o T-B perde `{{4}}` e vira genérico.**

**Não mover o deal no envio.** A etapa de recência registra qual onda o lead pegou; mover na saída destruiria
a segmentação. **Mover só no desfecho.**

### 7.2 Bug bloqueante a corrigir junto

`backend/app/leads/reposicao.py:12` define `REPOSICAO_PIPELINE_NAME = "Reposição - João"`, mas o funil se
chama **`João - Reposição`**. Como `create_deal` cai no fallback "primeiro pipeline por `order_index`", **19
deals automáticos de reposição foram parar em `Valeria - Importação Leads Frios`.**

## 8. Segmentação e rampa

**Poda de contactabilidade, antes de tudo:**
```
1.208 − 241 fixo BR (12 díg.) − 16 não-BR − 4 inválidos − 66 setor público  ≈ 900 alcançáveis
```
Sem ela, ~21-25% do disparo falha com `131026` — foi o que aconteceu em três disparos históricos (19,2%,
33% e 50%). ⚠️ Note que **R$ 1.043.421 (53,5% do valor) está atrás de telefone fixo** — esses viram trilha de
e-mail, não de WhatsApp.

**Escopo da v1:**

| Trilha | Etapas | Leads | Celular | Categoria |
|---|---|---:|---:|---|
| **A · Pedido pendente** | `pedido_sem_faturar` | 62 | 39 | UTILITY |
| **B · Reposição** | inativos 3-36m | 303 | 248 | MARKETING |
| **C · Higienização** | `inativo_36m_mais` | 665 | ~400 | UTILITY (não vende) |
| EXCLUIR | `ativo_0_3m` (75) | — | — | são clientes ativos; o João já trabalha os 9 melhores |
| EXCLUIR | `lead_sem_compra` (103) | — | — | sem relação prévia → LIA frágil; 3 são fornecedores nossos |
| EXCLUIR (dinâmico) | comprou nos últimos 90d (**47**) | — | — | 15 compraram **depois** do corte do CSV, um em 06/09 |

**Cadência:** D0 (ter/qua/qui, 14h-16h BRT) → D+4 para quem não respondeu → **STOP**. Sem terceiro toque;
`metadata.last_reactivation_at` bloqueia o lead por 6 meses.

**Gates por lote, antes de liberar o próximo:** entrega **≥ 85%** · `Parar mensagens` **≤ 5%** · resposta
**≥ 6%**. Falhou → congela e revisa o texto. **Piloto: os 39 celulares de `pedido_sem_faturar`.**
**Teto ≤ 150/dia.**

**Subgrupo que exige cuidado:** os **182 leads com tag `Débito vencido`** (R$ 223.003) são quase certamente
artefato do financeiro do Bling, não inadimplência — 130 dos 182 devem 75-100% de tudo que já compraram e
apenas 21 de 1.208 têm qualquer título baixado. **O agente nunca menciona título ou débito.** Os 11 casos
acima de R$ 5.000 saem da campanha e viram conferência manual.

## 9. Convenções obrigatórias

- Log com prefixo-tag **`[BUTTON FLOW]`**, format string **lazy `%s`** (nunca f-string).
- **Env novo nunca vira campo no `Settings`**: `config.py:65-69` tem `extra:"allow"`, que aceita a var no
  `.env` mas **não cria o atributo** → `AttributeError`. Padrão do repo: `app/<feature>/config.py` com
  `os.getenv` (molde: `app/bling/config.py:27-43`).
- Núcleo de decisão = **leaf module puro** (precedentes: `agent/persona.py`, `agent/handoff.py`,
  `templates/intent.py`).
- Docstring conta **o incidente** com `arquivo:linha`, não o "o quê".
- Migration em `supabase/migrations/YYYYMMDD_slug.sql`, no mesmo commit, **aplicada à mão**.
  ⚠️ O ledger `schema_migrations` parou em 2026-07-11 (12 arquivos aplicados e não registrados) e um
  `--apply` cego morre em `20260818_bling_integration.sql:168`. **Rode `--status` primeiro.**
- Fluxo git: **sem PR** — `branch → implementar+testar → git pull origin master →
  git push origin <branch>:master`, mediante autorização.

## 10. O que já existe (mergeado nesta branch)

A branch `feat/bot-botoes-reativacao` (20 commits, +4.561 linhas) foi mergeada limpa e traz, **com 64 testes
verdes**:

| Pronto | Onde |
|---|---|
| fluxo declarativo | `button_flow/flows.py` (114) |
| motor de decisão puro | `button_flow/engine.py` (208) |
| efeitos de CRM | `button_flow/effects.py` (181) |
| parser preserva o payload do botão | `webhook/meta_parser.py` +26 |
| clique sobrevive ao buffer | `buffer/manager.py` +4, `processor.py` +29 |
| `send_interactive_buttons` nos 3 providers | `whatsapp/{base,meta,mock_provider}.py` +59 |
| migration do `kind` + `flow_state` | `20260820_button_flow_agent.sql` (59) |

**Falta montar:** `runner.py`, o gate no `processor.py`, o classificador, o detector de autoresponder, o
payload custom no disparo, o preflight, e o tratamento de `131049`. Mais o relabel de `flows.py` para os
rótulos da §6.2 e os prazos em dias.

## 11. Riscos principais

| # | Risco | Mitigação |
|---|---|---|
| 1 | **Opt-out não honrado** (52 casos hoje) → LGPD + queda de qualidade | short-circuit determinístico fail-CLOSED; classe SAIR; colunas de evidência; corrigir os 52 **antes** de qualquer disparo |
| 2 | **Queda GREEN→YELLOW nos 3 números** (WABA compartilhada) | poda de contactabilidade; rampa ≤150/dia; gate por lote; piloto de 39 |
| 3 | **Texto falso no template** → contestação e report | 4 templates por trilha, nenhum afirma pedido inexistente; classe ENGANO aborta o script |
| 4 | **`_hot_lead_guardrail` mata os 208 melhores leads** | nomear `recuperacao_*` (sem `reativ`); não disparar sob `valeria_outbound` |
| 5 | **"faz meses que você não compra" para quem comprou anteontem** | recalcular de `sales` **no disparo**, não da etapa congelada em 08/08 |
| 6 | **Rótulo do template diverge de `flows.py`** | preflight: perfil `button_flow` + template sem os rótulos exatos → **400 no start** |
| 7 | **Preço inventado para produto fora do catálogo** | `produto_top1` sem SKU ativo ⇒ reconhece o nome, **não cota** |

## 12. Decisões do dono do negócio (implementação segue o DEFAULT)

| # | Pergunta | DEFAULT adotado |
|---|---|---|
| Q1 | Existe desconto para quem volta? | **Não.** A oferta é memória + reposição + preço de tabela. Pedido de desconto → handoff. |
| Q2 | Frete grátis existe? | **O agente nunca fala de frete** — há 3 versões incompatíveis em circulação. Quem cota é o João. |
| Q3 | Utility ou marketing? | UTILITY em A e C (onde é honesta); **MARKETING em B e D**, orçado como tal. |
| Q4 | Qual número? | **O do João** (§D2). |
| Q5 | Os 182 com "Débito vencido" entram? | **Sim, sem nenhuma menção a débito.** Os 11 acima de R$ 5.000 saem. |
| Q6 | Os 208 com venda em `sales` entram? | **Sim** — são os melhores. O bloqueio é acidental. |
| Q7 | Os 665 de 36m+ recebem oferta comercial? | **Não** — trilha de higienização; quem clicar vira opt-in registrado para uma 2ª campanha. |
| Q8 | `lead_sem_compra` e `ativo_0_3m` entram? | **Nenhum dos dois.** |
| Q9 | Que identidade o agente assume? | Assina **"João, do Café Canastra"**. Sem nome próprio, não conversa. Se perguntarem se é robô, confirma. |
| Q10 | Preço no 1º toque pós-clique? | **Sim, com foto**, e só do item que ele já comprou. |
| Q11 | Quantos por dia? | **≤ 150**, piloto de 39. |
| Q12 | Corrigir os 52 opt-outs retroativos? | **Sim, bloqueante** — mas é escrita em produção e precisa de autorização explícita. |
| Q13 | Produto fora dos 32 SKUs? | Reconhece pelo nome, **não cota**, encaminha ao João. |

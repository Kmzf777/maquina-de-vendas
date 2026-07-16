# Valéria — Ponte de Valor (WIIFM) + Contorno de RBO (Anchor-Disrupt-Ask) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir dois erros estruturais da Valéria no atendimento de lead frio (caso real: lead `5511971052959` / Demétrio, persona `valeria_inbound`, stage `secretaria`): (1) disparar pergunta de qualificação sem Ponte de Valor / WIIFM, e (2) render-se imediatamente a uma negativa reflexa ("não estou comprando") chamando `registrar_sem_interesse_atual` sem nenhum contorno.

**Architecture:** Correção 100% de PROMPT (vibe coding), sem novas tools Python e sem mexer no motor de intenções do orquestrador. Duas frentes: (A) `base.py` ganha duas regras globais — Ponte de Valor (WIIFM) e o framework Anchor-Disrupt-Ask para RBO — mais um guard na regra 18B e um item de checklist; (B) `valeria_inbound/secretaria.py` (o stage onde o caso falhou) ganha a Ponte de Valor explícita na Etapa 2 e um few-shot do contorno de RBO. `base.py` é prefixado a TODO stage via `build_base_prompt` (orchestrator), então as regras globais cobrem inbound e outbound.

**Tech Stack:** Python 3.11, pytest. Testes de conteúdo de prompt (asserções de substring), no padrão de `test_base_prompt.py` e `test_valeria_prompt_correcoes_2026_06_27.py`.

## Global Constraints

- **Aderência ao `gemini-prompting-strategies.md` (INEGOCIÁVEL):** TODA edição de prompt segue a estrutura existente — instrução crítica no início da seção, linguagem direta e precisa, headings/numeração consistentes com o arquivo, e few-shot no formato já presente. Few-shot examples são obrigatórios (o guia recomenda sempre incluí-los).
- **Voz da Valéria (já no `base.py`):** minúsculas, SEM ponto final (quebra de bolha com `\n\n`), no máximo 3 bolhas por turno (Verbosity: Low), no máximo 1 "!" por conversa, sem emoji, sem bullets na mensagem ao cliente. Todo exemplo novo respeita isso. Toda pergunta termina com "?".
- **Sem novas tools, sem mudança de motor:** o contorno de RBO e a Ponte de Valor são resolvidos por regras comportamentais e few-shots. A tool de descarte continua sendo a já existente `registrar_sem_interesse_atual` (regra 18B); apenas adiamos seu disparo até depois do contorno.
- **Sem regressão:** nenhuma regra/seção existente do `base.py` ou do `secretaria.py` pode ser removida ou ter seu sentido invertido. As edições são ADITIVAS (novas regras 17b e 29b, guard na 18B, item de checklist) ou reescrita ampliada da Etapa 2 que PRESERVA a pergunta de mercado.
- **Comandos de teste rodam de dentro de `backend/`** (imports usam `app.`). Ex.: `cd backend && python -m pytest tests/...`.
- **Commits:** ao final de cada task. Mensagens em pt-BR, terminando com a linha de co-autoria padrão do repo (`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`).

---

## File Structure

- `backend/app/agent/prompts/base.py` — prompt global, prefixado a todo stage. Recebe: regra **17b** (Ponte de Valor/WIIFM), regra **29b** (RBO Anchor-Disrupt-Ask), guard de cross-reference na regra **18B**, e item **24** do checklist.
- `backend/app/agent/prompts/valeria_inbound/secretaria.py` — stage do primeiro contato (onde o caso falhou). Recebe: Ponte de Valor na **Etapa 2**, nota de RBO na Etapa 2, e few-shot **Exemplo 7** (contorno Anchor-Disrupt-Ask).
- `backend/tests/test_valeria_rbo_ponte_2026_06_27.py` — NOVO arquivo de testes de conteúdo, cobrindo as duas frentes.

---

### Task 1: `base.py` — Ponte de Valor (WIIFM) + RBO Anchor-Disrupt-Ask (regras globais)

**Files:**
- Modify: `backend/app/agent/prompts/base.py` (regra 17 ~L266; regra 18B ~L279-294; regra 29 ~L428; checklist ~L949)
- Test: `backend/tests/test_valeria_rbo_ponte_2026_06_27.py` (novo)

**Interfaces:**
- Consumes: `from app.agent.prompts.base import build_base_prompt` — `build_base_prompt(lead_name: str|None, lead_company: str|None, now: datetime, lead_context: dict|None=None) -> str`.
- Produces: a string do base prompt passa a conter as regras 17b (Ponte de Valor/WIIFM) e 29b (RBO Anchor-Disrupt-Ask), o guard "regra 29b" dentro da 18B, e o item 24 do checklist.

- [ ] **Step 1: Escrever os testes que falham (RED)**

Criar `backend/tests/test_valeria_rbo_ponte_2026_06_27.py`:

```python
"""Ponte de Valor (WIIFM) + contorno de RBO (Anchor-Disrupt-Ask) — correções de prompt.

Caso real: lead 5511971052959 (Demétrio), persona valeria_inbound, stage secretaria.
Erro 1: pergunta de qualificação sem Ponte de Valor. Erro 2: rendição imediata ao
RBO "não estou comprando" (registrar_sem_interesse_atual precoce).

Testes de conteúdo de prompt (substring), no padrão de test_base_prompt.py.
"""
from datetime import datetime, timezone, timedelta
from app.agent.prompts.base import build_base_prompt

TZ_BR = timezone(timedelta(hours=-3))


def _base() -> str:
    return build_base_prompt(lead_name=None, lead_company=None, now=datetime.now(TZ_BR)).lower()


# --- Erro 1: Ponte de Valor / WIIFM (global) ---

def test_base_tem_regra_ponte_de_valor_wiifm():
    low = _base()
    assert "ponte de valor" in low
    assert "wiifm" in low
    # a justificativa tem que beneficiar o LEAD, não a operação interna
    assert "beneficie o lead" in low


def test_base_ponte_proibe_justificar_so_com_interesse_interno():
    low = _base()
    # proíbe explicitamente "pra eu te direcionar" como única justificativa
    assert "pra eu te direcionar" in low or "interesse interno" in low


# --- Erro 2: RBO Anchor-Disrupt-Ask (global) ---

def test_base_tem_regra_rbo_anchor_disrupt_ask():
    low = _base()
    assert "rbo" in low
    assert "anchor-disrupt-ask" in low
    # os três passos do framework
    assert "ancore" in low
    assert "quebre o padrao" in low or "quebre o padrão" in low
    assert "baixo atrito" in low


def test_base_rbo_proibe_descarte_na_primeira_negativa_reflexa():
    low = _base()
    assert "registrar_sem_interesse_atual" in low
    # cobre o gatilho exato do caso real
    assert "nao estou comprando" in low or "não estou comprando" in low
    # só descarta se reafirmar depois do contorno
    assert "reafirmar" in low


def test_base_rbo_tem_caminho_de_aceite():
    low = _base()
    # happy path: se o lead aceitar o pedido de baixo atrito, não engaveta — entrega valor + 1 pergunta
    assert "se o lead aceitar" in low
    assert "pergunta leve de descoberta" in low


def test_base_18b_guard_referencia_regra_29b():
    low = _base()
    # a regra 18B aponta para a 29b antes de aceitar negativa reflexa inicial
    assert "regra 29b" in low


def test_base_checklist_tem_item_anti_descarte_precoce():
    low = _base()
    # item de checklist que trava o descarte precoce
    assert "negativa reflexa" in low
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd backend && python -m pytest tests/test_valeria_rbo_ponte_2026_06_27.py -v`
Expected: FAIL — as strings "ponte de valor", "wiifm", "anchor-disrupt-ask", "regra 29b" ainda não existem no `base.py`.

- [ ] **Step 3: Implementar — adicionar a regra 17b (Ponte de Valor) logo após a regra 17**

Em `backend/app/agent/prompts/base.py`, a regra 17 (SAUDACAO DO LEAD) termina na linha ~267 e a regra 18 (DESCARTE) começa na ~268. Inserir ENTRE elas o bloco abaixo (note o `\\n` duplo nos exemplos, padrão do arquivo):

```
17b. PONTE DE VALOR (WIIFM) — NUNCA QUALIFIQUE SEM UM MOTIVO QUE BENEFICIE O LEAD:
    Toda pergunta de qualificacao/triagem (mercado, volume, tipo de negocio, demanda, necessidade)
    DEVE vir acompanhada de uma PONTE DE VALOR: um motivo concreto que beneficie O LEAD — nao a sua
    operacao. Lead frio nao gasta esforco de graca: pedir informacao sem entregar um "por que isso te
    ajuda" faz o lead cortar o assunto (falha real: lead 5511971052959 cortou apos pergunta de mercado
    seca).
    - PROIBIDO justificar a pergunta SO com o seu interesse interno: "pra eu te direcionar", "pra eu
      entender", "pro nosso sistema/cadastro". Isso NAO e ponte de valor — e burocracia que pesa no lead.
    - CERTO: ancore a pergunta num GANHO do lead — poupar o tempo dele, nao mandar material irrelevante,
      ja chegar com a solucao certa pra ele. Ex.: "pra eu ja te trazer o que faz sentido e nao te encher
      de coisa que nao tem a ver com voce\\n\\nme diz: ..."
    - Continua valendo UMA pergunta por turno (regra do silencio): ponte + UMA pergunta, e PARE.
```

- [ ] **Step 4: Implementar — adicionar o guard na regra 18B**

Ainda em `base.py`, a regra 18(B) (SOFT REJECTION) lista gatilhos como "nao tenho interesse no momento" / "sem interesse agora" (linhas ~279-285). Imediatamente APÓS a linha que termina o parágrafo de gatilhos da 18(B) (`...objecao de preco/momento que voce ja tentou contornar e o lead manteve.`) e ANTES da linha `PROIBIDO usar registrar_optout...`, inserir:

```
        ANTES de tratar como SOFT uma negativa REFLEXA INICIAL — dita no comeco do contato, antes de
        qualquer diagnostico (ex.: "nao estou comprando", "nao tenho interesse", "ja compramos", "agora
        nao") — aplique PRIMEIRO o contorno da regra 29b (Anchor-Disrupt-Ask). So registre SOFT aqui se
        o lead REAFIRMAR a negativa DEPOIS desse contorno. Negativa reflexa nao contornada = lead perdido
        por reflexo, nao por decisao.
```

- [ ] **Step 5: Implementar — adicionar a regra 29b (RBO Anchor-Disrupt-Ask) após a regra 29**

Ainda em `base.py`, a regra 29 (CONTORNO DE DESCULPAS / BRUSH-OFF) termina na linha ~428 e a regra 30 começa na ~430. Inserir ENTRE elas:

```
29b. RBO (RESISTENCIA REFLEXA INICIAL) — CONTORNE COM ANCHOR-DISRUPT-ASK ANTES DE DESCARTAR:
    Negativas REFLEXAS no inicio do contato — "nao estou comprando", "nao tenho interesse", "ja
    compramos", "ja temos fornecedor", "agora nao", "sem interesse no momento" — ditas ANTES de qualquer
    diagnostico, sao reacoes automaticas (reflex responses / RBO), NAO decisoes ponderadas. PROIBIDO
    chamar registrar_sem_interesse_atual na PRIMEIRA negativa reflexa. Voce tem direito a UM contorno, em
    UMA mensagem, com o framework ANCHOR-DISRUPT-ASK (respeite a regra do silencio: no maximo 3 bolhas,
    depois PARE):
    1. ANCORE — concorde com a emocao/falta de interesse atual, sem resistir nem rebater. Ex.: "tranquilo,
       super entendo\\n\\nninguem gosta de ser abordado pra comprar do nada".
    2. QUEBRE O PADRAO (DISRUPT) — afirme PROATIVAMENTE que o objetivo deste contato NAO e vender nada
       agora. Ex.: "e nem e esse o motivo do meu contato\\n\\nnao to aqui pra te empurrar pedido".
    3. PECA COM BAIXO ATRITO (ASK) — faca UM pedido minimo, de esforco quase zero e voltado pro futuro do
       lead. Ex.: "posso so te deixar salvo aqui um resumo rapido do que a gente faz, numa mensagem so?".
    SE O LEAD ACEITAR o pedido de baixo atrito ("pode mandar", "manda", "ok", "pode"): NAO fique em
    silencio nem largue o lead. Entregue um resumo CURTO (1 bolha) do que a Cafe Canastra faz e, em
    seguida, faca UMA pergunta leve de descoberta com ponte de valor (regra 17b) pra manter a conversa
    viva — sem partir pro interrogatorio. Ex.: "so pra eu te mandar o que faz sentido pra voce, voce
    pensa em cafe mais pro seu negocio ou pro consumo?". A partir dai, siga o funil normal de triagem.
    SO trate como SOFT REJECTION (regra 18B) e chame registrar_sem_interesse_atual se, DEPOIS do
    Anchor-Disrupt-Ask, o lead REAFIRMAR que nao quer ("nao precisa", "nao, obrigado", "pode parar").
    EXCECAO — pule o contorno e va direto pro fluxo de HARD OPT-OUT (regra 18A) se o lead proibir o
    contato explicitamente ("me tira da lista", "para de me mandar mensagem", "vou bloquear/denunciar"):
    isso e proibicao de contato, nao RBO.
```

- [ ] **Step 6: Implementar — adicionar o item 24 ao checklist**

Ainda em `base.py`, no bloco `# CHECKLIST ANTES DE RESPONDER`, o último item é o 23 (linha ~949, sobre "?"). Logo após o item 23 e ANTES da linha `</instructions>`, inserir:

```
24. O lead deu uma negativa REFLEXA logo no inicio ("nao to comprando", "sem interesse", "ja temos fornecedor") e eu ainda NAO contornei? Se sim, PROIBIDO chamar registrar_sem_interesse_atual agora — aplique o Anchor-Disrupt-Ask (regra 29b) primeiro e so descarte se ele reafirmar.
```

- [ ] **Step 7: Rodar os testes da Task 1 (GREEN)**

Run: `cd backend && python -m pytest tests/test_valeria_rbo_ponte_2026_06_27.py -v`
Expected: PASS (7 testes desta task).

- [ ] **Step 8: Rodar a suíte do base prompt para garantir sem regressão**

Run: `cd backend && python -m pytest tests/test_base_prompt.py -v`
Expected: PASS (todos os testes existentes do base prompt continuam verdes — as edições são aditivas).

- [ ] **Step 9: Commit**

```bash
git add backend/app/agent/prompts/base.py backend/tests/test_valeria_rbo_ponte_2026_06_27.py
git commit -m "$(cat <<'EOF'
fix(valeria): Ponte de Valor (WIIFM) + contorno de RBO (Anchor-Disrupt-Ask) no base

Erro 1 (Fanatical Prospecting): regra 17b obriga justificar toda pergunta de
qualificacao com um motivo que beneficie o lead (WIIFM), nunca so o interesse
interno.
Erro 2: regra 29b classifica negativas reflexas iniciais ("nao estou comprando",
"ja compramos") como RBO e exige o contorno Anchor-Disrupt-Ask antes de descartar.
A regra 18B agora adia o registrar_sem_interesse_atual ate o lead reafirmar pos-contorno.
Caso real: lead 5511971052959 (Demetrio).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `valeria_inbound/secretaria.py` — Ponte de Valor na Etapa 2 + few-shot de RBO

**Files:**
- Modify: `backend/app/agent/prompts/valeria_inbound/secretaria.py` (Etapa 2 ~L57-66; few-shot ~L141-203)
- Test: `backend/tests/test_valeria_rbo_ponte_2026_06_27.py` (adiciona testes ao arquivo da Task 1)

**Interfaces:**
- Consumes: `from app.agent.prompts.valeria_inbound.secretaria import SECRETARIA_PROMPT` (string).
- Produces: `SECRETARIA_PROMPT` passa a conter a Ponte de Valor (WIIFM) na Etapa 2, a nota de RBO na Etapa 2, e o few-shot Exemplo 7 (Anchor-Disrupt-Ask).

- [ ] **Step 1: Escrever os testes que falham (RED)**

Adicionar ao final de `backend/tests/test_valeria_rbo_ponte_2026_06_27.py`:

```python
# --- secretaria (stage do caso real): Ponte de Valor + few-shot de RBO ---

from app.agent.prompts.valeria_inbound.secretaria import SECRETARIA_PROMPT


def _sec() -> str:
    return SECRETARIA_PROMPT.lower()


def test_secretaria_etapa2_tem_ponte_de_valor():
    low = _sec()
    assert "ponte de valor" in low
    assert "wiifm" in low
    # ainda faz a pergunta de mercado (sem regressão) — frase completa e exata,
    # não a substring frágil "exporta" (que casaria com qualquer "exportacao")
    assert "sua demanda e pro mercado brasileiro ou pra exportacao/mercado externo?" in low


def test_secretaria_tem_fewshot_rbo_anchor_disrupt_ask():
    low = _sec()
    # cobre o gatilho exato do caso real e o contorno
    assert "nao estou comprando" in low or "não estou comprando" in low
    assert "nao to aqui pra te empurrar" in low or "não to aqui pra te empurrar" in low
    # não descarta na primeira negativa
    assert "primeira negativa" in low or "reafirmar" in low


def test_secretaria_fewshot_rbo_tem_continuacao_de_aceite():
    low = _sec()
    # happy path no few-shot: lead aceita ("pode mandar") e a IA entrega valor + 1 pergunta leve
    assert "pode mandar" in low
    assert "negocio ou" in low or "consumo" in low


def test_secretaria_preserva_triagem_imediata_sem_regressao():
    low = _sec()
    # regressão: a triagem de licitação/laudo e o handoff continuam presentes
    assert "triagem imediata" in low
    assert "encaminhar_humano" in low
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd backend && python -m pytest tests/test_valeria_rbo_ponte_2026_06_27.py -k "secretaria" -v`
Expected: FAIL — "ponte de valor"/"wiifm" e o few-shot de RBO ainda não existem no `secretaria.py`.

- [ ] **Step 3: Implementar — reescrever a Etapa 2 com Ponte de Valor + nota de RBO**

Em `backend/app/agent/prompts/valeria_inbound/secretaria.py`, substituir o bloco atual da ETAPA 2 (linhas ~57-66, que vai de `## ETAPA 2: IDENTIFICACAO DO MERCADO` até a linha da `Regra C — anti-interrogacao...` inclusive) por:

```
## ETAPA 2: IDENTIFICACAO DO MERCADO

Objetivo: Determinar se a demanda e para mercado nacional ou internacional.

1. Reaja ao nome do lead com algo genuino (varie: "que nome bonito", "ah, massa", "legal te conhecer").
2. PONTE DE VALOR (WIIFM) OBRIGATORIA: antes da pergunta, de um motivo concreto que beneficie o LEAD —
   poupar o tempo dele e nao mandar material irrelevante. NUNCA justifique a pergunta so com o seu
   interesse interno ("pra eu te direcionar"). Ancore no ganho dele.
3. Entao pergunte o mercado, ja colado na ponte. Ex.:
   "pra eu ja te trazer o que faz sentido e nao te encher de coisa que nao tem a ver com voce"
   "sua demanda e pro mercado brasileiro ou pra exportacao/mercado externo?"

Aguarde a resposta antes de prosseguir para a Etapa 3.

Regra C — anti-interrogacao: entre a coleta de nome (Etapa 1) e a pergunta de mercado (Etapa 2), voce ja fez 1 pergunta. Nao empilhe uma segunda pergunta no mesmo turno. Reaja ao nome, faca a ponte de valor e entao a pergunta de mercado.

REFLEXO INICIAL (RBO): se neste comeco o lead reagir com negativa reflexa ("nao estou comprando", "nao tenho interesse", "ja compramos", "agora nao"), NAO chame registrar_sem_interesse_atual de imediato — aplique o Anchor-Disrupt-Ask da regra 29b do prompt base, em UMA mensagem, e so descarte se o lead reafirmar.
```

- [ ] **Step 4: Implementar — adicionar o few-shot Exemplo 7 (Anchor-Disrupt-Ask)**

Ainda em `secretaria.py`, dentro de `<few_shot_examples>`, ao final (após o Exemplo 6, antes do fechamento `</few_shot_examples>` na linha ~203), inserir:

```

---

Exemplo 7 — RBO reflexo logo apos confirmar o nome (Anchor-Disrupt-Ask):

User: "nenhuma, nao estou comprando"
Assistant: "tranquilo, ninguem gosta de ser abordado pra comprar do nada"
"e nem e esse o motivo do meu contato, nao to aqui pra te empurrar pedido"
"posso so te deixar salvo aqui um resumo rapido do que a gente faz, pra quando precisar?"

User: "pode mandar"
Assistant: "show, a gente e uma marca de cafe especial da Serra da Canastra, atende desde consumo em casa ate negocio"
"so pra eu te mandar o que faz sentido pra voce e nao te encher de coisa atoa, voce pensa em cafe mais pro seu negocio ou pro consumo?"

Nota: cada passo do Anchor-Disrupt-Ask vai em UMA bolha curta (3 bolhas no total, respeitando Verbosity Low) — NUNCA empilhe disrupt + ask num bloco gigante. As aspas sao so o separador de bolhas do few-shot (a Valeria nao envia aspas no WhatsApp). NAO chamou registrar_sem_interesse_atual na primeira negativa. Quando o lead ACEITA ("pode mandar"), entrega um resumo curto e volta com UMA pergunta leve de descoberta com ponte de valor — nao engaveta o lead nem interroga. So se o lead REAFIRMAR a negativa ("nao precisa", "pode parar") e que se registra sem interesse (regra 29b do base).
```

- [ ] **Step 5: Rodar os testes da Task 2 (GREEN)**

Run: `cd backend && python -m pytest tests/test_valeria_rbo_ponte_2026_06_27.py -v`
Expected: PASS (todos — Task 1 + Task 2).

- [ ] **Step 6: Rodar as suítes de secretaria/base para garantir sem regressão**

Run: `cd backend && python -m pytest tests/test_base_prompt.py tests/test_valeria_secretaria_nome_2026_06_27.py -v`
Expected: PASS (a triagem, a coleta de nome e a pergunta de mercado seguem intactas).

- [ ] **Step 7: Commit**

```bash
git add backend/app/agent/prompts/valeria_inbound/secretaria.py backend/tests/test_valeria_rbo_ponte_2026_06_27.py
git commit -m "$(cat <<'EOF'
fix(valeria): Ponte de Valor na Etapa 2 + few-shot de RBO no secretaria inbound

Stage do caso real (lead 5511971052959). A Etapa 2 agora exige a Ponte de Valor
(WIIFM) antes da pergunta de mercado, e o Exemplo 7 demonstra o contorno
Anchor-Disrupt-Ask para a negativa reflexa "nao estou comprando" — sem disparar
registrar_sem_interesse_atual de imediato.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Verificação final de regressão (suíte completa)

**Files:** nenhum (apenas execução)

**Interfaces:** N/A.

- [ ] **Step 1: Rodar a suíte de testes do backend**

Run: `cd backend && python -m pytest -q`
Expected: toda a suíte verde (sem novas falhas vs. baseline). Atenção às suítes de prompt: `test_base_prompt.py`, `test_valeria_secretaria_nome_2026_06_27.py`, `test_valeria_prompt_correcoes_2026_06_27.py`, `test_inbound_autonomy_2026_06_26.py`.

- [ ] **Step 2: Procurar testes que travem o descarte precoce de RBO**

Run: `cd backend && python -m pytest -q -k "sem_interesse or rbo or secretaria"`
Expected: PASS. Nenhum teste atual asserta que uma negativa reflexa inicial deve disparar `registrar_sem_interesse_atual` de imediato (a investigação não encontrou nenhum — os testes existentes são de substring/mocks de tools disponíveis). Se algum teste falhar por esperar o disparo precoce, atualizá-lo para refletir o novo contrato (contorno Anchor-Disrupt-Ask antes do descarte) e documentar a mudança no commit.

- [ ] **Step 3: Se houver falha pré-existente não relacionada**

Confirmar (via `git stash` + re-run, ou comparando com a baseline) que a falha já existia antes destas mudanças. Documentar; não consertar fora de escopo.

---

## Self-Review

**1. Spec coverage:**
- Identificação do contexto do lead (persona/stage) → feita na investigação: `valeria_inbound` / `secretaria` (campos `agent_persona`/`stage` das mensagens do lead `5511971052959`). ✓
- Diretriz Lógica 1 (Ponte de Valor/WIIFM) → Task 1 regra 17b (global) + Task 2 Etapa 2 (stage específico). ✓
- Diretriz Lógica 2 (identificação de RBOs) → Task 1 regra 29b classifica negativas reflexas como RBO + guard na 18B + checklist item 24. ✓
- Diretriz Lógica 3 (Anchor-Disrupt-Ask em uma única interação) → Task 1 regra 29b (3 passos, 1 mensagem) + Task 2 Exemplo 7 (demonstra os 3 passos em 3 bolhas). ✓
- Diretriz Inegociável de Prompting (gemini-prompting-strategies.md) → Global Constraints + edições usam numeração/headings do arquivo, instrução crítica no topo da regra, few-shot no formato existente. ✓
- Evitar superengenharia (vibe coding, sem novas tools/motor) → só edição de prompt; usa `registrar_sem_interesse_atual` existente, apenas adiando o disparo. ✓
- Ajustar testes que esperavam disparo precoce → Task 3 Step 2 (busca dirigida; nenhum encontrado na investigação, com fallback de atualização). ✓

**2. Placeholder scan:** sem TBD/TODO; todo texto de prompt e todos os testes mostrados por extenso. Os pontos de inserção citam âncoras textuais exatas (ex.: "PROIBIDO usar registrar_optout", "</instructions>", "Regra C — anti-interrogacao") e números de linha aproximados — o implementador localiza pela âncora textual, não pelo número.

**3. Type consistency:** `build_base_prompt(lead_name, lead_company, now, lead_context=None)` usado de forma idêntica nos testes e já existente no código. As strings de asserção (`"ponte de valor"`, `"wiifm"`, `"anchor-disrupt-ask"`, `"regra 29b"`, `"nao estou comprando"`, `"nao to aqui pra te empurrar"`) batem exatamente com o texto inserido nas Tasks 1 e 2 (conferido em minúsculas, sem acento onde o texto do prompt não usa acento). O nome da regra é "29b" tanto no `base.py` quanto na nota da Etapa 2 do `secretaria.py`.

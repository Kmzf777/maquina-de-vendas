# Valéria — Correções de Comportamento (caso Rubens 5531999844461) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir 4 falhas observadas no atendimento do lead Rubens (`5531999844461`, persona `valeria_inbound`, stages `secretaria`→`atacado`): (1) tom robotizado de fórmula fixa "[fato] é [elogio]", (2) ausência de `?` nas perguntas, (3) mensagem de handoff duplicada, (4) message bombing (2 turnos para uma rajada do lead).

**Architecture:** Combinação de ajustes de prompt (comportamental) com redes de segurança determinísticas no código. Tasks 1-3 são baixo risco (prompt + guards pontuais); Task 4 é risco médio (concorrência de buffer). Nenhum módulo é reescrito.

**Tech Stack:** Python 3.11, pytest. LLM: gemini-2.5-flash. Prompts: strings em `backend/app/agent/prompts/`. Humanizer: `backend/app/humanizer/splitter.py`. Buffer/concorrência: `backend/app/buffer/processor.py` + Redis (`aioredis`).

## Global Constraints

- **Aderência ao `gemini-prompting-strategies.md` (INEGOCIÁVEL):** toda edição de prompt segue a estrutura existente do arquivo — instrução crítica no topo da regra, linguagem direta, few-shots no formato já presente (`User:` / `Assistant:` / bolhas entre aspas / bloco `Nota:`). Few-shots são a alavanca principal (o guia recomenda exemplos > instruções).
- **Voz da Valéria:** minúsculas, SEM ponto final nas bolhas (bolha quebra com nova linha), perguntas terminam com `?`, sem emoji, máximo 1 `!` por conversa, máximo 3 bolhas/turno.
- **Aditivo / sem regressão:** não remover regras/exemplos existentes nem inverter seu sentido. As redes determinísticas (splitter `?`, dedup de handoff, peek de buffer) são fail-open: erro nunca quebra o fluxo de atendimento.
- **Sem rewrite:** Task 4 NÃO reescreve a fila de eventos — apenas adiciona um peek do buffer Redis à decisão de re-coalescing já existente. Splitter ganha 3-5 linhas; nenhuma lib de NLP.
- **Comandos de teste rodam de dentro de `backend/`** (imports usam `app.`). Ex.: `cd backend && python -m pytest tests/...`.
- **Commits:** ao final de cada task, mensagem pt-BR terminando com `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Ambiente:** preferir Bash; se git-bash falhar (cygwin fork error), usar PowerShell + `git commit -F <arquivo>`. NÃO fazer push.

## File Structure

- `backend/app/agent/prompts/base.py` — regra global anti-fórmula (tom) + reforço do `?` + regra de handoff no mesmo turno.
- `backend/app/agent/prompts/valeria_inbound/atacado.py` — few-shots diversificados (ir direto ao ponto; `?` consistente; Nota anti-fórmula).
- `backend/app/humanizer/splitter.py` — rede determinística que re-adiciona `?` em bolhas inequivocamente interrogativas.
- `backend/app/agent/tools.py` — dedup no `encaminhar_humano` (pula `send_text` se a despedida ≈ última bolha já enviada).
- `backend/app/buffer/processor.py` — peek do buffer Redis no re-coalescing (anti-bombing).
- Testes: `backend/tests/test_valeria_rubens_*_2026_06_27.py` (um arquivo por task) + `test_splitter.py` (existente, estender se houver).

---

### Task 1: Tom robotizado — regra anti-fórmula + few-shots diversificados

**Files:**
- Modify: `backend/app/agent/prompts/base.py` (após a REGRA DE OURO de reação, ~L159 e ~L220; e a black-list ~L709-720)
- Modify: `backend/app/agent/prompts/valeria_inbound/atacado.py` (`<few_shot_examples>` ~L294-331)
- Test: `backend/tests/test_valeria_rubens_tom_2026_06_27.py` (novo)

**Interfaces:**
- Consumes: `build_base_prompt(...)`; `from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT`.
- Produces: base prompt contém a regra anti-fórmula; ATACADO_PROMPT contém ≥1 few-shot "direto ao ponto" + Nota anti-fórmula.

- [ ] **Step 1: Escrever o teste que falha (RED)** — criar `backend/tests/test_valeria_rubens_tom_2026_06_27.py`:

```python
"""Tom robotizado (caso Rubens 5531999844461): banir a fórmula fixa "[fato] é [elogio]"."""
from datetime import datetime, timezone, timedelta
from app.agent.prompts.base import build_base_prompt
from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT

TZ = timezone(timedelta(hours=-3))


def _base() -> str:
    return build_base_prompt(lead_name=None, lead_company=None, now=datetime.now(TZ)).lower()


def test_base_tem_regra_anti_formula():
    low = _base()
    assert "anti-formula" in low or "anti-fórmula" in low
    # proíbe o molde mecânico elogio-a-cada-turno
    assert "elogio" in low
    assert "todo turno" in low or "toda mensagem" in low or "a cada turno" in low


def test_base_anti_formula_cita_padrao_proibido():
    low = _base()
    # cita o padrão concreto que apareceu na falha (fato repetido + "é" + elogio genérico)
    assert "é um ponto ótimo" in low or "é um grande diferencial" in low or "[fato]" in low or "[elogio]" in low


def test_atacado_fewshot_direto_ao_ponto_sem_elogio():
    low = ATACADO_PROMPT.lower()
    # existe um exemplo que NÃO abre com elogio — vai direto ao ponto
    assert "direto ao ponto" in low
    # a Nota alerta contra elogiar toda fala do lead
    assert "sem elogiar" in low or "nao elogie" in low or "não elogie" in low
```

- [ ] **Step 2: Rodar p/ ver falhar** — `cd backend && python -m pytest tests/test_valeria_rubens_tom_2026_06_27.py -v` → FAIL.

- [ ] **Step 3: Implementar a regra anti-fórmula no `base.py`.** Localizar a black-list crítica de palavras (âncora textual: `## ⛔ BLACK-LIST CRITICA DE PALAVRAS`, ~L709). LOGO APÓS o último item dessa black-list (a regra que proíbe ack em turnos consecutivos, âncora `PROIBIDO usar ack de confirmacao em turnos CONSECUTIVOS`), INSERIR:

```
- ANTI-FORMULA (ritmo robotico — falha real lead 5531999844461): PROIBIDO repetir, a cada turno, o
  molde "[ack/nome], [fato que o lead disse] é [elogio generico]". Ex. do que NAO fazer (turnos
  seguidos): "cafeteria em BH é um ponto ótimo", "área nobre tem um público que valoriza", "ter o
  local próprio já é um grande diferencial". Isso vira jingle e escancara a automacao.
  - NAO elogie toda fala do lead. Reaja com elogio só quando houver algo GENUINO e ESPECIFICO a
    reconhecer — e NUNCA dois turnos seguidos com a mesma estrutura de elogio.
  - Varie: às vezes vá DIRETO ao ponto (sem ack, sem elogio), faça a pergunta ou entregue o valor.
    O blacklist acima ja permite "ir direto, sem ack nenhum" — use isso com frequencia.
  - O elogio nunca pode ser a moldura padrao de abertura de turno. Conteudo > bajulacao.
```

- [ ] **Step 4: Suavizar o absolutismo do "SEMPRE reaja primeiro".** Localizar a âncora `SEMPRE reaja primeiro ao que o cliente disse` (~L220). Substituir essa frase específica por:

```
4. RESPONDER AO QUE FOI DITO — reaja ao que o cliente disse QUANDO houver algo genuino a reagir; senao, va direto ao ponto. NUNCA transforme a reacao num elogio automatico a cada turno (ver ANTI-FORMULA na black-list). Depois pode avancar.
```

(Preserva o sentido — responder ao lead — sem induzir o elogio mecânico.)

- [ ] **Step 5: Diversificar os few-shots do `atacado.py`.** No `<few_shot_examples>`, ANTES do `</few_shot_examples>`, ADICIONAR um exemplo "direto ao ponto" + atualizar a Nota do Exemplo 6. Inserir após o Exemplo 6 (âncora: o bloco `Nota: reagiu ao contexto (publico da loja)`):

```

## Exemplo 7 — direto ao ponto (sem elogio): responder e avancar
User: "vocês entregam em BH?"
Assistant: "entregamos sim, BH ta na nossa area de cobertura"
"qual volume você pensa em começar, pra eu já te indicar o melhor formato?"

Nota: foi DIRETO — sem "que legal", sem "BH é um ótimo mercado", sem elogiar a pergunta. Respondeu o
que foi perguntado e avançou com UMA pergunta. Nem todo turno precisa de elogio; aqui ir direto soa
mais natural e profissional (anti-formula). NAO elogie toda fala do lead.
```

- [ ] **Step 6: GREEN** — `cd backend && python -m pytest tests/test_valeria_rubens_tom_2026_06_27.py -v` → PASS (3).

- [ ] **Step 7: Regressão** — `cd backend && python -m pytest tests/test_base_prompt.py tests/test_valeria_prompt_correcoes_2026_06_27.py tests/test_valeria_rbo_ponte_2026_06_27.py -q` → PASS.

- [ ] **Step 8: Commit**

```
fix(valeria): regra anti-formula + few-shots diretos no atacado (tom robotizado)

Caso Rubens 5531999844461: a IA repetia "[fato] é [elogio]" a cada turno (jingle).
base.py ganha regra ANTI-FORMULA na black-list e suaviza "sempre reaja"; atacado.py
ganha few-shot "direto ao ponto" + Nota contra elogiar toda fala do lead.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

---

### Task 2: Ausência de `?` — reforço de few-shot + rede determinística no splitter

**Files:**
- Modify: `backend/app/humanizer/splitter.py` (novo helper `_ensure_question_mark`, chamado no pipeline)
- Modify: `backend/app/agent/prompts/base.py` (reforço curto da obrigatoriedade do `?` — âncora regra 22)
- Test: `backend/tests/test_valeria_rubens_interrogacao_2026_06_27.py` (novo)

**Interfaces:**
- Consumes: `from app.humanizer.splitter import split_into_bubbles`.
- Produces: `split_into_bubbles` re-adiciona `?` em bolhas que começam com palavra inequivocamente interrogativa e não têm pontuação terminal. `_ensure_question_mark(bubble: str) -> str`.

- [ ] **Step 1: Escrever o teste que falha (RED)** — criar `backend/tests/test_valeria_rubens_interrogacao_2026_06_27.py`:

```python
"""Rede de segurança do '?' (caso Rubens): perguntas inequívocas recebem '?' determinístico."""
from app.humanizer.splitter import split_into_bubbles, _ensure_question_mark


def test_readiciona_interrogacao_em_pergunta_wh():
    assert _ensure_question_mark("quer que eu te passe os detalhes") == "quer que eu te passe os detalhes?"
    assert _ensure_question_mark("qual desses formatos faz mais sentido pro seu negocio") == \
        "qual desses formatos faz mais sentido pro seu negocio?"
    assert _ensure_question_mark("o que te fez querer entrar nesse mercado") == \
        "o que te fez querer entrar nesse mercado?"


def test_nao_mexe_em_declarativa_ou_ja_pontuada():
    # declarativa sem starter interrogativo → não vira pergunta
    assert _ensure_question_mark("a gente entrega em BH") == "a gente entrega em BH"
    # já tem '?' → inalterada
    assert _ensure_question_mark("qual o volume?") == "qual o volume?"
    # reticências (pausa) → não mexe
    assert _ensure_question_mark("deixa eu ver aqui...") == "deixa eu ver aqui..."
    # termina com '!' → não mexe
    assert _ensure_question_mark("que massa!") == "que massa!"


def test_split_into_bubbles_aplica_interrogacao():
    out = split_into_bubbles("qual desses faz mais sentido pro seu negocio")
    assert out == ["qual desses faz mais sentido pro seu negocio?"]
```

- [ ] **Step 2: Rodar p/ ver falhar** — `cd backend && python -m pytest tests/test_valeria_rubens_interrogacao_2026_06_27.py -v` → FAIL (`_ensure_question_mark` não existe).

- [ ] **Step 3: Implementar `_ensure_question_mark` no `splitter.py`.** Adicionar após `_strip_terminal_period` (~L88):

```python
# Palavras/aberturas inequívocas de pergunta (PT-BR informal). Conservador de propósito:
# só re-adicionamos "?" quando a bolha ABRE com um destes — evita falso-positivo em declarativas.
_QUESTION_STARTERS = (
    "qual", "quais", "o que", "o quê", "que ", "como", "quando", "onde", "quanto",
    "quantos", "quantas", "quem", "por que", "por quê", "quer", "prefere", "poderia",
    "consegue", "seria", "te interessa", "faz sentido",
)


def _ensure_question_mark(bubble: str) -> str:
    """Rede de segurança: re-adiciona '?' em bolha inequivocamente interrogativa sem pontuação final.

    O modelo às vezes derruba o '?' por over-aplicar o 'sem ponto final' (falha real lead
    5531999844461). Só agimos quando a bolha ABRE com uma palavra interrogativa clara e NÃO termina
    em pontuação (., ?, !, …) — conservador para nunca transformar uma declarativa em pergunta.
    """
    b = bubble.rstrip()
    if not b or b[-1] in ".?!…":
        return bubble
    low = b.lower()
    if low.startswith(_QUESTION_STARTERS):
        return b + "?"
    return bubble
```

E no `split_into_bubbles`, aplicar como ÚLTIMO passo do pipeline (após `_strip_terminal_period`, ~L74). Trocar:

```python
    bubbles = [_strip_terminal_period(b) for b in bubbles]

    return bubbles
```

por:

```python
    bubbles = [_strip_terminal_period(b) for b in bubbles]

    # Rede de segurança do "?" — vem DEPOIS do strip do ponto final (que nunca toca em "?").
    bubbles = [_ensure_question_mark(b) for b in bubbles]

    return bubbles
```

- [ ] **Step 4: Reforço curto no `base.py`.** Localizar a âncora da regra do `?` (`O "?" NAO E PONTO FINAL E E OBRIGATORIO`, ~L338). Ao final dessa sub-regra (antes de `- "!" continua permitido`), ADICIONAR uma linha:

```
      Esta regra tem o MESMO peso do "sem ponto final": derrubar o "?" de uma pergunta e tao grave
      quanto fechar bolha com ".". Toda bolha interrogativa termina em "?", sem excecao.
```

- [ ] **Step 5: GREEN** — `cd backend && python -m pytest tests/test_valeria_rubens_interrogacao_2026_06_27.py -v` → PASS (3).

- [ ] **Step 6: Regressão do splitter** — `cd backend && python -m pytest tests/test_splitter.py tests/test_base_prompt.py -q` → PASS (se `test_splitter.py` não existir, rodar só `test_base_prompt.py`).

- [ ] **Step 7: Commit**

```
fix(humanizer): rede de seguranca do "?" + reforco no prompt (perguntas sem interrogacao)

Caso Rubens 5531999844461: o modelo derrubava o "?" por over-aplicar o "sem ponto final".
splitter re-adiciona "?" deterministicamente em bolhas que abrem com palavra interrogativa
clara (conservador, nunca toca declarativa). base.py eleva o "?" ao mesmo peso do ponto final.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

---

### Task 3: Mensagem de handoff duplicada — regra de mesmo turno + dedup na tool

**Files:**
- Modify: `backend/app/agent/prompts/base.py` (regra de handoff — âncora regra 16, ~L255-265)
- Modify: `backend/app/agent/tools.py` (`encaminhar_humano`, bloco de envio da despedida ~L735-742)
- Test: `backend/tests/test_valeria_rubens_handoff_dedup_2026_06_27.py` (novo)

**Interfaces:**
- Consumes: `execute_tool("encaminhar_humano", ...)`; `get_conversation_history` / `get_recent_assistant_texts`.
- Produces: `encaminhar_humano` pula o `send_text` da despedida se ela for ~idêntica à(s) última(s) bolha(s) assistant já enviada(s). Helper `_despedida_ja_enviada(conversation_id, despedida) -> bool`.

- [ ] **Step 1: Escrever o teste que falha (RED)** — criar `backend/tests/test_valeria_rubens_handoff_dedup_2026_06_27.py`:

```python
"""Dedup do handoff (caso Rubens 5531999844461): não reenviar a despedida que a IA já disse."""
from unittest.mock import patch
import app.agent.tools as tools


def _norm(s):
    return tools._normalize_for_dedup(s)


def test_normalize_para_dedup_ignora_caixa_e_pontuacao():
    assert _norm("Pra pedir o KIT amostra, fala com o João!") == _norm("pra pedir o kit amostra fala com o joao")


def test_despedida_ja_enviada_detecta_repeticao():
    recent = ["pra pedir o kit amostra, você pode falar direto com o nosso supervisor, o joão bras"]
    with patch("app.agent.tools._recent_assistant_texts", return_value=recent):
        assert tools._despedida_ja_enviada(
            "conv-1",
            "pra pedir o kit amostra, você pode falar direto com o nosso supervisor, o João Brás",
        ) is True


def test_despedida_nova_nao_e_duplicata():
    recent = ["boa, já te mandei as fotos do portfólio"]
    with patch("app.agent.tools._recent_assistant_texts", return_value=recent):
        assert tools._despedida_ja_enviada("conv-1", "vou te passar pro João finalizar o pedido") is False
```

- [ ] **Step 2: Rodar p/ ver falhar** — `cd backend && python -m pytest tests/test_valeria_rubens_handoff_dedup_2026_06_27.py -v` → FAIL (helpers não existem).

- [ ] **Step 3: Implementar os helpers + o guard no `tools.py`.** Adicionar perto do topo dos helpers do módulo (antes de `execute_tool`):

```python
import re as _re_dedup


def _normalize_for_dedup(text: str) -> str:
    """Normaliza p/ comparação de duplicata: minúsculas, sem pontuação, espaços colapsados."""
    t = (text or "").lower()
    t = _re_dedup.sub(r"[^\w\s]", " ", t)        # remove pontuação/acentos-vizinhos de símbolo
    t = _re_dedup.sub(r"\s+", " ", t).strip()
    return t


def _recent_assistant_texts(conversation_id: str, limit: int = 4) -> list[str]:
    """Últimas bolhas 'assistant' já enviadas nesta conversa (para dedup do handoff). Fail-open: []."""
    try:
        history = get_conversation_history(conversation_id, limit=limit * 3) or []
        return [m.get("content") or "" for m in history if m.get("role") == "assistant"][-limit:]
    except Exception:
        return []


def _despedida_ja_enviada(conversation_id: str, despedida: str) -> bool:
    """True se a despedida do handoff é ~idêntica a uma bolha assistant já enviada (evita reenvio).

    Caso real (lead 5531999844461): a IA verbalizou o pitch de handoff num turno e, no turno seguinte,
    chamou encaminhar_humano com o MESMO texto → a tool reenviou (sent_by='handoff') = duplicata.
    Compara o início normalizado (primeiros ~60 chars) — robusto a reticências/truncamento.
    """
    target = _normalize_for_dedup(despedida)
    if not target:
        return False
    head = target[:60]
    for prev in _recent_assistant_texts(conversation_id):
        prev_n = _normalize_for_dedup(prev)
        if head and (head in prev_n or prev_n[:60] == head):
            return True
    return False
```

No `encaminhar_humano`, no bloco que envia a despedida (âncora: `despedida = (args.get("mensagem_despedida") or "").strip() or _HANDOFF_MSG`), ENVOLVER o `send_text` com o guard:

```python
            despedida = (args.get("mensagem_despedida") or "").strip() or _HANDOFF_MSG
            if len(despedida) > _MAX_DESPEDIDA_LEN:
                despedida = despedida[:_MAX_DESPEDIDA_LEN].rstrip() + "…"
            if _despedida_ja_enviada(conversation_id, despedida):
                logger.info(
                    "[HANDOFF DEDUP] despedida ~idêntica a bolha já enviada — pulando send_text "
                    "(conv=%s); cartão de contato segue normalmente.", conversation_id,
                )
            else:
                try:
                    send_result = await provider.send_text(send_to, despedida)
                    save_message(lead_id, "assistant", despedida, sent_by="handoff", conversation_id=conversation_id, wamid=extract_wamid(send_result))
                except Exception as exc:
                    logger.error(
                        "encaminhar_humano: falha ao enviar mensagem de handoff para lead %s: %s",
                        lead_id, exc, exc_info=True,
                    )
```

(O cartão de contato do supervisor continua sendo enviado SEMPRE — só o texto duplicado é suprimido.)

- [ ] **Step 4: Reforço da regra de handoff no `base.py`.** Localizar a regra 16 (âncora: `NAO pergunte nome. NAO pergunte mais nada. NAO ofereca mais informacoes. A conversa automatica esta encerrada apos o handoff.`, ~L265). LOGO APÓS essa linha, ADICIONAR:

```
    DESPEDIDA E TOOL NO MESMO TURNO (anti-duplicata — falha real lead 5531999844461): a mensagem de
    despedida do handoff e a chamada de encaminhar_humano saem JUNTAS, no MESMO turno. PROIBIDO
    verbalizar "vou te passar pro Joao / pra pedir o kit fala com o Joao" num turno e so chamar a tool
    no turno seguinte — isso faz a tool reenviar a despedida (duplicata). Decidiu encaminhar? Escreve a
    despedida no argumento mensagem_despedida E chama a tool AGORA, na mesma resposta.
```

- [ ] **Step 5: GREEN** — `cd backend && python -m pytest tests/test_valeria_rubens_handoff_dedup_2026_06_27.py -v` → PASS (3).

- [ ] **Step 6: Regressão de handoff** — `cd backend && python -m pytest tests/test_agent_tools.py tests/test_base_prompt.py tests/test_newline_handoff_price_2026_06_25.py -q` → PASS (ajustar nomes se algum não existir; rodar os que existirem).

- [ ] **Step 7: Commit**

```
fix(handoff): dedup da despedida + regra de mesmo turno (mensagem duplicada)

Caso Rubens 5531999844461: a IA verbalizou o pitch de handoff num turno e chamou
encaminhar_humano com o mesmo texto no turno seguinte → reenvio (sent_by=handoff).
encaminhar_humano agora pula o send_text se a despedida ~= ultima bolha ja enviada;
base.py exige despedida + tool no MESMO turno.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

---

### Task 4: Message bombing — peek do buffer Redis no re-coalescing

**Files:**
- Modify: `backend/app/buffer/processor.py` (novo helper `_has_pending_buffered_inbound`; usá-lo no re-coalescing de aquisição ~L807 e in-flight ~L913)
- Test: `backend/tests/test_valeria_rubens_bombing_2026_06_27.py` (novo)

**Interfaces:**
- Consumes: `aioredis` (mesma conexão do manager: `buffer:{phone}:{channel_id}`), `settings.redis_url`.
- Produces: `async _has_pending_buffered_inbound(phone: str, channel_id: str) -> bool` — True se há mensagem do lead ainda no buffer Redis (não salva no DB). O re-coalescing passa a abortar/deferir quando há inbound novo no DB **OU** pendente no buffer.

**Root cause (provado por timestamps):** a mensagem-irmã fica ~`buffer_base_timeout` (15s) no buffer Redis ANTES de ser salva no DB. O guard `_has_newer_inbound` consulta só o DB → fica CEGO à mensagem em buffer durante o envio do 1º worker. Resultado: o 1º worker termina e envia; depois a irmã dá flush e gera um 2º turno (bombing). A correção é o guard também espiar o buffer Redis (o usuário pediu "re-checagem do **buffer**/DB").

- [ ] **Step 1: Escrever o teste que falha (RED)** — criar `backend/tests/test_valeria_rubens_bombing_2026_06_27.py`:

```python
"""Anti message-bombing (caso Rubens 5531999844461): peek do buffer Redis no re-coalescing.

A irmã fica ~15s no buffer Redis antes de ir pro DB; o guard só-DB ficava cego a ela durante o
envio do 1º turno → 2º turno empilhado. Agora o guard também consulta o buffer.
"""
import pytest
from unittest.mock import AsyncMock, patch
from app.buffer import processor


@pytest.mark.asyncio
async def test_pending_buffered_inbound_true_quando_buffer_tem_item():
    fake_redis = AsyncMock()
    fake_redis.llen = AsyncMock(return_value=1)
    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis):
        assert await processor._has_pending_buffered_inbound("5531999844461", "ch-1") is True
    fake_redis.llen.assert_awaited()  # consultou buffer:{phone}:{channel}


@pytest.mark.asyncio
async def test_pending_buffered_inbound_false_quando_vazio():
    fake_redis = AsyncMock()
    fake_redis.llen = AsyncMock(return_value=0)
    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis):
        assert await processor._has_pending_buffered_inbound("5531999844461", "ch-1") is False


@pytest.mark.asyncio
async def test_pending_buffered_inbound_failopen_false_em_erro():
    fake_redis = AsyncMock()
    fake_redis.llen = AsyncMock(side_effect=RuntimeError("redis down"))
    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis):
        # fail-open: erro de Redis nunca aborta o atendimento
        assert await processor._has_pending_buffered_inbound("5531999844461", "ch-1") is False
```

- [ ] **Step 2: Rodar p/ ver falhar** — `cd backend && python -m pytest tests/test_valeria_rubens_bombing_2026_06_27.py -v` → FAIL (helper não existe).

- [ ] **Step 3: Implementar `_get_buffer_redis` + `_has_pending_buffered_inbound` no `processor.py`.** Adicionar perto de `_has_newer_inbound` (~L1036):

```python
import redis.asyncio as _aioredis_buf

_buffer_redis_client: "_aioredis_buf.Redis | None" = None


def _get_buffer_redis() -> "_aioredis_buf.Redis":
    """Conexão Redis para espiar o buffer do lead (mesma chave do buffer.manager)."""
    global _buffer_redis_client
    if _buffer_redis_client is None:
        _buffer_redis_client = _aioredis_buf.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )
    return _buffer_redis_client


async def _has_pending_buffered_inbound(phone: str, channel_id: str) -> bool:
    """True se há mensagem do lead AINDA no buffer Redis (recebida, não flushada → invisível ao DB).

    Fecha a cegueira do `_has_newer_inbound` (só-DB): a irmã fica ~buffer_base_timeout no buffer antes
    de ir pro DB; sem espiar o buffer, o 1º worker enviava e a irmã virava um 2º turno (bombing,
    auditoria 5531999844461). Fail-open: erro/sem conexão → False (nunca engole a única resposta).
    """
    try:
        buf_key = f"buffer:{phone}:{channel_id}"
        return bool(await _get_buffer_redis().llen(buf_key))
    except Exception as exc:
        logger.warning(
            "[RECOALESCE] falha ao espiar buffer p/ %s:%s: %s — fail-open (não aborta)",
            phone, channel_id, exc,
        )
        return False
```

- [ ] **Step 4: Ligar o peek no re-coalescing de AQUISIÇÃO do lock.** Na âncora do abort de aquisição (`if _has_newer_inbound(conversation["id"], turn_watermark):`, ~L807), trocar a condição por:

```python
            if _has_newer_inbound(conversation["id"], turn_watermark) or \
               await _has_pending_buffered_inbound(phone, channel["id"]):
```

(O `channel` já está disponível no escopo; `phone` também. O corpo do `if` — log + `pop_interest_marked` + `_update_last_msg` + `return` — fica inalterado.)

- [ ] **Step 5: Ligar o peek no re-coalescing IN-FLIGHT (entre bolhas).** Na âncora da trava in-flight (`if _has_newer_inbound(conversation["id"], turn_watermark):`, ~L913, dentro do `for delay, bubble in zip(...)`), trocar por:

```python
                if _has_newer_inbound(conversation["id"], turn_watermark) or \
                   await _has_pending_buffered_inbound(phone, channel["id"]):
```

(Corpo inalterado: `superseded = True` + log + `break`. Assim, quando a irmã chega e ainda está no buffer, o 1º worker corta a cauda e o worker do flush posterior responde tudo holisticamente.)

- [ ] **Step 6: GREEN** — `cd backend && python -m pytest tests/test_valeria_rubens_bombing_2026_06_27.py -v` → PASS (3).

- [ ] **Step 7: Regressão de buffer/processor** — `cd backend && python -m pytest tests/ -k "processor or buffer or recoalesc or followup" -q` → PASS. Atenção a testes que exercitam o bloco do lock: se algum mockava só `_has_newer_inbound`, garantir que `_has_pending_buffered_inbound` esteja patchado p/ `False` no setup (senão tenta Redis real). Documentar no relatório qualquer mock ajustado.

- [ ] **Step 8: Commit**

```
fix(buffer): peek do buffer Redis no re-coalescing (anti message-bombing)

Caso Rubens 5531999844461: a irmã fica ~15s no buffer antes de ir pro DB; o guard
_has_newer_inbound (so-DB) ficava cego a ela durante o envio do 1o turno → 2o turno
empilhado (5 bolhas/3 perguntas). Agora o re-coalescing (aquisicao do lock + in-flight)
tambem espia o buffer Redis; fail-open. Sem reescrever a fila.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

---

### Task 5: Verificação final de regressão

**Files:** nenhum.

- [ ] **Step 1:** `cd backend && python -m pytest -q` → suíte inteira verde (baseline atual: 1206 passed). Documentar qualquer falha pré-existente não relacionada (via `git stash` + re-run).

---

## Self-Review

**1. Spec coverage:**
- Tom robotizado → Task 1 (regra anti-fórmula base.py + few-shots diversificados atacado.py). ✓
- Ausência de `?` → Task 2 (rede determinística splitter + reforço base.py). ✓
- Handoff duplicado → Task 3 (dedup tools.py + regra mesmo-turno base.py). ✓
- Message bombing → Task 4 (peek buffer Redis no re-coalescing). ✓
- Diretriz gemini-prompting-strategies → Global Constraints + few-shots no formato existente. ✓
- Sem rewrite / anti-superengenharia → splitter +5 linhas, dedup pontual, peek de buffer (sem reescrever fila). ✓
- TDD Red-Green por task. ✓

**2. Placeholder scan:** sem TBD/TODO; todo código e prompt por extenso. Âncoras textuais citadas para cada inserção. Único ponto de investigação dirigida: Task 4 Step 7 (ajuste de mocks de testes que exercitam o lock) — instrução explícita de como tratar.

**3. Type consistency:** `_ensure_question_mark(str)->str`, `_has_pending_buffered_inbound(str,str)->bool` (async), `_despedida_ja_enviada(str,str)->bool`, `_normalize_for_dedup(str)->str`, `_recent_assistant_texts(str,int)->list[str]` — nomes idênticos entre testes e implementação. O peek de buffer usa a mesma chave `buffer:{phone}:{channel_id}` do `manager.py`. `channel["id"]` e `phone` confirmados no escopo do bloco do lock.

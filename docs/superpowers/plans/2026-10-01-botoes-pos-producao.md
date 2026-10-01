# Três defeitos pós-produção — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Fechar os três defeitos lidos nas 10 primeiras conversas reais do fluxo de botões — um deles ignorando lead neste minuto.

**Spec:** `docs/superpowers/specs/2026-10-01-botoes-pos-producao-design.md` — leia antes da Task 1. Ela cita conversa, horário e texto de cada caso.

**Tech Stack:** Python 3 / FastAPI / Supabase, pytest (`asyncio_mode = auto`).

---

## Ondas

| Onda | Task | Arquivos |
|---|---|---|
| 1 | **A** | `button_flow/valeria_runner.py` · `buffer/processor.py` · `button_flow/valeria_registry.py` |
| 1 | **B** | `button_flow/effects.py` |

A e B rodam em paralelo: não compartilham arquivo. Itens 1 e 3 ficaram na mesma task porque
os dois tocam `valeria_runner.py`, e dois agentes no mesmo arquivo divergem.

## Regras de execução

- **Subagente NUNCA toca em git.** Proibido: `add`, `commit`, `checkout`, `restore`, `reset`, `stash`, `rm`, `clean`, `switch`, `branch`.
- **Não rode a suíte inteira** (8 min). Rode o conjunto escopado; o orquestrador roda tudo no fechamento.
- **Se o plano estiver errado, PARE e reporte.** Onze defeitos de plano foram pegos assim nesta base — incluindo um que mandaria boas-vindas a lead com opt-out, e um onde estreitar a minha instrução foi melhor que segui-la.
- Armadilhas: escape `\n` virando newline real em string literal (rode `ast.parse`); escape `\uXXXX` virando caractere invisível literal (monte com `chr(...)`); acento persistido como `?` (decodifique em UTF-8 estrito); e a guarda que proíbe marcador de modelo OpenAI em `app/` (`tests/test_no_openai_provider_2026_07_02.py`).

---

## Task A: o bridge volta a responder, e o nudge para de mandar foto

**Files:**
- Modify: `backend/app/button_flow/valeria_runner.py`
- Modify: `backend/app/buffer/processor.py`
- Modify: `backend/app/button_flow/valeria_registry.py`
- Test: `backend/tests/test_botoes_pos_producao_2026_10_01.py`

**Leia antes:** `processor.py:1676-1800` inteiro (o gate, o `return` incondicional e os
comentários que explicam por que ele existe), `valeria_runner.processar_inbound`,
`button_flow/runner._motivo_para_nao_rodar`, e `processor._maybe_send_handoff_bridge`.

### Item 1 — o motivo sobe, e o gate chama o bridge

- [ ] **Step 1: teste que falha**

```python
"""Lead transbordado que volta a escrever recebe resposta, não silêncio.

Caso real, 01/10: dois leads transbordados em 31/07 e 28/08 escreveram de novo e
NÃO receberam nada. Um deles ("O kilo sai 25 reais", 12:47) ficou sem resposta —
antes da ativação do fluxo o bridge respondia, e está no histórico dele.

Causa: o bridge vive ABAIXO do `return` incondicional do gate de fluxos. O
`return` não sai — é ele que faz "zero IA" ser fato. O gate passa a chamar o
bridge quando o fluxo recusou o turno POR HANDOFF FORMAL, e só nesse motivo.
"""
import pytest

MOTIVO_HUMANO = "human_control"


@pytest.mark.asyncio
async def test_recusa_por_handoff_formal_devolve_o_motivo():
    """O gate precisa saber POR QUE o fluxo não rodou."""
    ...


@pytest.mark.asyncio
async def test_turno_atendido_devolve_none():
    ...


@pytest.mark.asyncio
async def test_blacklist_devolve_motivo_proprio_e_NAO_aciona_o_bridge():
    """Lead que pediu para sair não recebe nada — o oposto do bridge."""
    ...


@pytest.mark.asyncio
async def test_o_gate_chama_o_bridge_uma_vez_no_motivo_human_control():
    ...


@pytest.mark.asyncio
async def test_o_gate_NUNCA_alcanca_run_agent_depois_do_bridge():
    """O `return` incondicional continua valendo: zero IA é fato."""
    ...


@pytest.mark.asyncio
async def test_o_runner_da_recuperacao_devolve_none_e_nada_muda():
    ...


@pytest.mark.asyncio
async def test_reproduz_o_caso_real_do_kilo_sai_25_reais():
    """Lead com human_control=True escrevendo pergunta de preço recebe o bridge."""
    ...
```

Os corpos são seus: escreva-os contra a forma real de `processar_inbound` e do gate, usando
os dublês que `tests/test_valeria_processor_2026_09_30.py` e
`tests/test_valeria_runner_2026_09_29.py` já estabelecem. **Não invente assinatura** — leia.

- [ ] **Step 2:** rode, confirme que falha pelo motivo certo.

- [ ] **Step 3: implemente**

`processar_inbound` passa a devolver `str | None` — o motivo da recusa, ou `None` quando
atendeu o turno. O call site é único e compartilhado: `runner.run_button_flow` (Recuperação)
devolve `None`, e nada muda para ela.

No gate, **depois** do `await _rodar_fluxo(...)` e **antes** do `return`:

```python
                motivo = await _rodar_fluxo(...)
                # O `return` abaixo continua incondicional — é ele que faz "zero IA"
                # ser fato. O bridge entra aqui, num ramo explícito e restrito a UM
                # motivo: handoff formal registrado. Caso real de 01/10 — dois leads
                # transbordados em 31/07 e 28/08 escreveram de novo e receberam
                # SILÊNCIO, porque o bridge vive abaixo deste return. Blacklist e
                # etapa incompatível NÃO entram: a primeira pediu para sair, a
                # segunda não tem promessa pendente ao lead.
                if motivo == MOTIVO_HANDOFF_FORMAL:
                    await _maybe_send_handoff_bridge(
                        lead, phone, conversation, channel, provider,
                        inbound_text=resolved_text, inbound_wamid=wamid,
                        inbound_message_type=_message_type,
                    )
```

**Descubra o valor real do motivo** que `_motivo_para_nao_rodar` devolve para `human_control`
— a spec chama de `"human_control"`, mas a função devolve uma string descritiva
(`"human_control=true (handoff formal já registrado)"` pelo que se lê no código). Não compare
por igualdade com um palpite: leia a função e use uma constante que ela exporte, ou crie a
constante **no módulo que já é dono da string** e importe. String duplicada aqui é a classe
de bug que `campaigns/node_registry.py` documenta.

### Item 3 — nudge sem foto, e corpo neutro

- [ ] **Step 4: teste que falha**

- Nudge num nó `foto_botoes` envia **uma** mensagem e `image_url` é `None`.
- Entrada normal no mesmo nó continua com `image_url` preenchido.
- A foto **não** é republicada no bucket durante um nudge (espione a função de publicação).
- Nudge em nó de botões comum: inalterado.
- `reg.CORPO_NUDGE` não contém a palavra "valor".

- [ ] **Step 5: implemente**

O runner olha `decisao.marcar_nudge` (campo que já existe em `Decisao`) e, quando verdadeiro,
envia texto + botões **sem** header de imagem, mesmo que `no.tela == "foto_botoes"`.

E o default de `CORPO_NUDGE` no registry passa a ser:

```
pra seguir, é só tocar numa das opções abaixo 👇
```

O atual (*"pra eu te passar o valor certo…"*) pressupõe que o lead perguntou preço, e em
produção respondeu a um áudio de número errado e a um vídeo. Segue editável pela chave
`__nudge__`.

- [ ] **Step 6: conjunto escopado**

```
cd backend && python -m pytest tests/test_botoes_pos_producao_2026_10_01.py tests/test_valeria_runner_2026_09_29.py tests/test_valeria_runner_gaps_2026_09_30.py tests/test_valeria_processor_2026_09_30.py tests/test_valeria_engine_2026_09_29.py tests/test_valeria_encerramento_2026_09_30.py tests/test_valeria_handoff_2026_09_30.py tests/test_valeria_bridge_2026_09_30.py tests/test_valeria_registry_2026_09_29.py tests/test_button_flow_runner_2026_09_09.py -q
cd backend && python -m pytest tests/ -q -k "ponte or bridge or handoff"
cd backend && python -m pytest tests/test_no_openai_provider_2026_07_02.py -q
```

`test_valeria_bridge_2026_09_30.py` tem a classe `TestOQueOCarimboAindaNaoAlcanca`, que fixa
de propósito o estado que esta task **conserta**. Ela vai falhar — isso é o sinal de sucesso,
não um incômodo. Leia o docstring, atualize as asserções para o comportamento novo, e
**explique no relatório** o que mudou. Não apague a classe: ela passa a fixar o que o bridge
AGORA alcança.

- [ ] **Step 7: reporte.** NÃO commite.

---

## Task B: a nota do handoff para de mentir

**Files:**
- Modify: `backend/app/button_flow/effects.py`
- Test: `backend/tests/test_botoes_nota_handoff_2026_10_01.py`

**Leia antes:** `effects.aplicar` inteiro e `_silenciar_ia` (`effects.py:365-378`), incluindo o
docstring que explica por que ele existe e por que não usa o carimbo de handoff.

**⚠️ `effects.py` é compartilhado com a Recuperação, que está em produção.** O que ela escreve
tem de ficar byte-idêntico.

- [ ] **Step 1: teste que falha**

- Handoff (`T_HANDOFF`, `T_HANDOFF_PL`, `T_HANDOFF_ARTHUR`) grava as notas de
  `[encaminhar_humano]` e `[TRANSBORDO p/ …]` e **nenhuma** nota contendo "insistiu em texto
  livre".
- `T_HUMANO` (bloqueio após 3 nudges, sem handoff) **continua** gravando a nota — ali é
  verdade.
- `ai_enabled=False` é escrito nos **dois** caminhos.
- Recuperação: a forma completa do que ela escreve num handoff e num `T_HUMANO` é a de hoje.
  Afirme a lista inteira de notas, não só a ausência de uma.

Reproduza o caso real: a conversa `dd221643` chegou ao `T_HANDOFF_PL` com **`nudges=0`** — o
lead clicou em tudo e recebeu a nota dizendo que insistiu em texto livre.

- [ ] **Step 2:** rode, confirme que falha.

- [ ] **Step 3: implemente**

`_silenciar_ia` não grava nota quando o mesmo efeito também é handoff. O desligamento da IA
continua nos dois caminhos — muda só a anotação. O `_aplicar_handoff` já escreve duas notas
verdadeiras, então não há informação perdida.

Decida **como** o sinal chega (parâmetro, ou `aplicar` reordenando as chamadas) lendo
`aplicar`; prefira o que deixa a razão explícita no código a um efeito colateral de ordem.

- [ ] **Step 4: conjunto escopado**

```
cd backend && python -m pytest tests/test_botoes_nota_handoff_2026_10_01.py tests/test_button_flow_effects_2026_08_20.py tests/test_valeria_handoff_2026_09_30.py tests/test_valeria_bridge_2026_09_30.py tests/test_valeria_encerramento_2026_09_30.py tests/test_button_flow_runner_2026_09_09.py -q
cd backend && python -m pytest tests/ -q -k "effects or handoff or transbordo"
cd backend && python -m pytest tests/test_no_openai_provider_2026_07_02.py -q
```

- [ ] **Step 5: reporte.** NÃO commite.

---

## Verificação final (orquestrador)

- [ ] `cd backend && python -m pytest tests/ -q`
- [ ] `cd frontend && npx vitest run` e `npx tsc --noEmit`
- [ ] `git pull origin master` e as duas suítes **depois** do merge
- [ ] Push só se tudo verde

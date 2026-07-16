# Spec — Fix S1 (handoff duplicado) + S2 (ponte engolindo pergunta de negócio)

**Data:** 11/07/2026 · **Origem:** auditoria geral `docs/superpowers/reports/auditoria_geral_valeria_hoje.md`

## Problema

**S1 — Handoff duplicado (caso Prof. Sebastião, 15:29 BRT).** O sentinel do loop de tools
(`orchestrator.py` ~L991) detecta handoff testando `fc.name == "encaminhar_humano"` nos
function_calls do LLM. Quando o handoff acontece em **cascata** — `qualificar_lead` com
âncoras completas chama `encaminhar_humano` DENTRO do `execute_tool` (`tools.py` ~L890) —
o nome não aparece na lista, o sentinel não dispara, o turno segue para a chamada pós-tool,
o LLM verbaliza a transferência e a guarda determinística de handoff verbalizado (~L1414)
executa um SEGUNDO `encaminhar_humano`. Resultado: 2 despedidas + 2 cartões em ~15s
(+ o 3º cartão da ponte). O comentário-invariante da guarda ("chegar aqui garante que
encaminhar_humano não rodou") está quebrado pela cascata.

**S2 — Ponte pós-handoff engole pergunta de negócio (casos Mateus/Leonardo, pós-deploy
do filtro de intenção).** `_maybe_send_handoff_bridge` (`buffer/processor.py`) só distingue
encerramento social (→ ❤️) de "resto" (→ carimbo estático + reenvio de cartão). Pergunta
substantiva ("Qual o valor da unidade", "valor das sacas no grão") recebe o carimbo
enlatado — aborrece o lead e enterra a pergunta.

## Solução

### S1 — Sentinel ciente da cascata (marcador no retorno da tool)

1. `tools.py`: nova constante de módulo `HANDOFF_RESULT_PREFIX = "Lead encaminhado para "`;
   o return final do branch `encaminhar_humano` passa a usá-la
   (`return f"{HANDOFF_RESULT_PREFIX}{vendedor}"` — string resultante idêntica à atual).
   A cascata do `qualificar_lead` já propaga esse retorno verbatim (nenhuma mudança lá).
2. `orchestrator.py` (loop principal): acumular flag `handoff_executed` durante a execução
   das tools do turno — True quando `func_name == "encaminhar_humano"` **ou** quando o
   `tool_result` é `str` e começa com `HANDOFF_RESULT_PREFIX` (cobre a cascata atual e
   qualquer futura). O sentinel (`return None`) e a telemetria [HANDOFF SEM RESPOSTA]
   passam a usar essa flag (telemetria da despedida só quando houver fc explícito de
   `encaminhar_humano`, como hoje).
3. `orchestrator.py` (caminho de retry ~L1190): mesma flag no loop de tools recuperadas —
   `"encaminhar_humano" in _retry_names` **ou** resultado com o prefixo → sentinel None.
4. Guarda verbalizada: sem mudança de código — com o sentinel correto ela volta a ser
   inalcançável quando um handoff já rodou no turno (invariante restaurado). Atualizar o
   comentário-invariante para citar a cascata.

**Alternativas descartadas:** reler `ai_enabled` do DB após as tools (I/O extra por turno
e race com operador humano); ContextVar setada no `execute_tool` (estado implícito
atravessando camadas, pior de testar). O marcador no retorno é puro, explícito e testável.

### S2 — Via do meio na ponte: pergunta de negócio → silêncio (fail-safe)

1. `buffer/processor.py`: nova função pura `_looks_like_business_question(text) -> bool`:
   - normaliza como `_is_social_closing` (minúsculas, sem acento);
   - True se o texto contém `?` em qualquer posição, **ou** se qualquer token do texto
     está no vocabulário de negócio `_BUSINESS_QUESTION_TOKENS` (word-boundary):
     preco(s), valor(es), custo(s), custa(m), caro, cara, barato, quanto(s/as), minimo,
     moq, lote(s), tabela, orcamento, frete, prazo(s), entrega, desconto, pagamento, pix,
     boleto, parcela(s), pedido(s), unidade(s), saca(s), kg, quilo(s), kilo(s), grama(s),
     grao(s), embalagem(ns), catalogo, exportacao, exporta(m), preço implícito etc.;
   - False para texto vazio/None.
2. Nova escada de decisão em `_maybe_send_handoff_bridge` (após o gate de handoff formal):
   1. inbound é reação → silêncio (inalterado);
   2. encerramento social → ❤️ (inalterado);
   3. **pergunta de negócio → silêncio total**: log WARNING
      `[BRIDGE] pergunta de negócio pós-handoff — silêncio (aguardando humano)` +
      `save_message` system `[ponte] pergunta de negócio detectada — silêncio, aguardando
      resposta humana` (sent_by="bridge", fail-soft) para QA/watchdog; **não consome o
      cooldown**; retorna False;
   4. resto (saudação, declaração neutra sem sinal de negócio) → carimbo + cartão como
      hoje (preserva os casos fundadores Maycon/Juliana de vácuo puro).
3. **Fail-safe por construção:** o detector superabrange (um único `?` basta); em caso de
   dúvida a mensagem fica intocada para o humano. Tradeoff aceito por diretriz explícita:
   reclamação-meta com `?` ("Tem algum problema vocês responderem?") também silencia.
   Vocabulários social × negócio são disjuntos e `?` bloqueia o social, então a ordem
   2→3 não cria ambiguidade.

## Testes (pytest)

- **S1 puro:** `execute_tool("qualificar_lead", âncoras completas)` retorna string com
  `HANDOFF_RESULT_PREFIX` (mocks nos moldes de `test_handoff_proativo_2026_07_04.py`).
- **S1 integração (o cenário do bug):** `run_agent` com `fake_tool_calls([("qualificar_lead",
  {finalidade, volume})])` e `execute_tool` mockado retornando
  `"Lead encaminhado para João Brás"` → retorna `None` (sentinel), `execute_tool` chamado
  exatamente 1x e **nunca** com `"encaminhar_humano"` (a guarda verbal não roda; 1 cartão só).
- **S1 regressão:** tool não-terminal com retorno normal não seta a flag (turno segue).
- **S2 puro:** `_looks_like_business_question` — True: "Qual o valor da unidade", "preço?",
  "?", "quanto custa", "valor das sacas no grão", "qual o pedido mínimo"; False: "obrigado",
  "boa tarde", "ok", None, "".
- **S2 comportamento:** ponte com inbound "Qual o valor da unidade" → `send_text` e
  `send_contact` NÃO chamados, cooldown NÃO consumido, marcador system salvo, retorno False.
- **S2 contrato atualizado:** `test_bridge_duvida_real_segue_enviando_texto` (inbound
  "e o orçamento que pedi?") migra para o novo contrato → silêncio; o caso "vácuo puro →
  carimbo" passa a usar texto sem `?`/termo de negócio (ex.: "alô, tem alguém aí").
- Regressões existentes de social closing/reação intactas.

## Fora de escopo

Prompts, SLA humano (Categoria 3 da auditoria), cooldowns da ponte, dedup de despedida
(`_despedida_ja_enviada`), Evolution API.

# Spec — Correções da Auditoria Inbound 10/07/2026

**Origem:** `docs/superpowers/reports/auditoria_inbound_hoje.md`
**Escopo:** 4 achados (1 grave sistêmico + 3 moderados de comportamento). Read-only até aqui; este spec define as correções.

---

## Achado 1 (P1) — Mensagens do vendedor persistidas vazias

### Causa raiz (confirmada no código)

`frontend/src/app/api/conversations/[id]/send-media/route.ts:239` grava:

```ts
content: messageType === "document" ? originalFilename : "",
```

Áudio e imagem enviados pelo vendedor via CRM entram no banco com `content=""`. Além disso, a rota **descarta o wamid** retornado pela Meta (`sendResp` é validado mas o JSON nunca é lido), diferente da rota de texto (`send/route.ts:133`), que persiste `insertData.wamid = sentWamid`.

O CRM renderiza a bolha via `message_type` + `media_url` (sem regressão visual), mas **todo consumidor de `content` fica cego**: histórico do LLM (`app/agent/orchestrator.py:795` ← `conversations/service.get_history`), dossiê/rolling_summary (`app/agent/memory_manager.py:293` ← `leads/service.get_history`), transcrições de QA (`app/agent/tools.py:1185,1236`) e auditorias.

### Solução

**(a) Normalização na leitura (backend — retroativa).** Helper puro `describe_media_placeholder(row) -> str` que, para `content` vazio/whitespace e `message_type != "text"`, devolve placeholder no padrão já usado pelo parser inbound:

| message_type | placeholder |
|---|---|
| audio | `[áudio]` |
| image | `[imagem]` |
| video | `[vídeo]` |
| document | `[documento]` (ou `[documento: <content>]` se houver filename) |
| sticker | `[sticker]` |
| location | `[localização]` |
| contact / contacts | `[contato]` |
| outro não-text | `[mídia]` |

Aplicado dentro de `conversations/service.get_history` **e** `leads/service.get_history` (pontos únicos de montagem de histórico do backend). Mensagens `content` não-vazio passam intocadas. Cobre as 5 linhas já corrompidas em produção e qualquer caminho de escrita futuro que falhe.

**(b) Correção na escrita (frontend).** Em `send-media/route.ts`:
- Ler o JSON de `sendResp` e persistir `wamid` (paridade com a rota de texto, habilita rastreio de status e dedup por autoridade).
- Gravar placeholder no `content` de áudio/imagem/vídeo (`[áudio]`, `[imagem]`...), mantendo documento = filename. A bolha do CRM renderiza por `message_type`, então o placeholder não muda a UI; previews (`conversations-live.ts`, `conversations/route.ts`) passam a mostrar "Vendedor: [áudio]" em vez de vazio.

**Não faz parte:** transcrever áudio do vendedor (custo/latência sem demanda comprovada — YAGNI).

---

## Achado 2 (P2) — Handoff prematuro por sinal fraco

### Causa raiz

Caso Nilson: `encaminhar_humano` chamado com motivo "private label qualificado" após "SIM aaaaaaaaa" + "👏👏👏👏", sem âncora de qualificação. A descrição da tool (`app/agent/tools.py:222`) diz apenas "lead qualificado e pronto para fechar", sem definir o que qualifica. Já existe a tool `qualificar_lead` (âncoras finalidade+volume → handoff proativo determinístico), mas o modelo pode contorná-la chamando `encaminhar_humano` direto.

### Solução (prompt + descrição de tool — SEM bloqueio hard)

- **Descrição de `encaminhar_humano`, caso (1):** explicitar o critério mínimo — o lead declarou **finalidade concreta** (o que quer fazer com o café/marca) E deu **sinal ativo de avanço** (pergunta de preço/prazo/pedido, confirmação verbal de interesse). Emojis, aplausos, monossílabos ("sim", "ok", "top") e simpatia social **não** qualificam sozinhos. Em dúvida, usar `qualificar_lead` para registrar âncoras em vez de encaminhar.
- **Prompt inbound (private_label e atacado):** regra curta espelhando o critério acima + regra de que oferta condicionada ("quer que eu te mostre X?") aguarda resposta afirmativa antes de executar a oferta.
- **Fora do escopo:** guardas determinísticas que bloqueiem o handoff (risco de engessar o funil — diretriz explícita do usuário). O circuit breaker de turnos existente permanece.

---

## Achado 3 (P3) — `mudar_stage`: flapping e lead preso em `pending`

### Causa raiz

- **Preso em `pending` (João Marcos):** a classificação de entrada depende 100% do LLM chamar `mudar_stage`. O mesmo gatilho de prefill ("Olá! Quero saber mais sobre ter a Marca Própria de Café.") moveu 3 leads em ~10s e falhou silenciosamente no 4º. Sem stage de funil, o catálogo não é injetado (`catalog.get_products_by_funnel` retorna "" para `pending`).
- **Flapping (Nilson):** `private_label → atacado → private_label` em ~3 min, reagindo a áudios ambíguos. A descrição da tool manda "executar imediatamente ao identificar o gatilho", sem critério de estabilidade.

### Solução

**(a) Gatilho determinístico de entrada (código).** Mapa `PREFILL_STAGE_TRIGGERS: dict[frase_normalizada -> stage]` com as frases de prefill conhecidas dos anúncios/site (hoje: "olá! quero saber mais sobre ter a marca própria de café." → `private_label`; estrutura extensível). No processamento do buffer, **antes** do agente: se a conversa está em stage de entrada (`pending`/`secretaria`/vazio) e alguma mensagem do lote casa (comparação normalizada: caixa/acentos/espaços), aplica a mesma transição do executor de `mudar_stage` (update conversa+lead, `ensure_segment_deal`, marcador system `stage alterado para: X`). Idempotente e fail-open (erro → segue fluxo LLM normal). O LLM continua responsável por todos os demais casos.

**(b) Anti-flapping (prompt/descrição — sem trava hard).** Na descrição de `mudar_stage`: mudar somente com declaração explícita do lead sobre a própria necessidade; fala ambígua/social (áudio truncado, cortesia) não é gatilho; retornar a um stage anterior da mesma conversa exige correção explícita do lead. Telemetria: `logger.warning("[STAGE FLAP]"...)` no executor quando a transição reverte para um stage visitado na mesma conversa há < 15 min (só observabilidade, sem bloqueio).

---

## Achado 4 (monitorar) — Handoff verbalizado sem tool-call

A guarda determinística (`orchestrator.py:304`) já contém o dano. Ação: **contador no `daily_qa_report`** — ocorrências/dia do marcador `handoff verbalizado sem tool-call (guarda deterministica)` — para acompanhar a saúde do modelo. Nenhuma mudança de comportamento.

---

## Critérios de aceite

1. Linha de `messages` com `content=""` e `message_type="audio"` aparece como `[áudio]` no histórico do LLM e no delta do dossiê (teste unitário do helper + teste dos dois `get_history`).
2. `send-media` persiste `wamid` e `content` placeholder (teste vitest da rota, se houver harness; senão validação manual tipada).
3. Prefill de marca própria em conversa `pending` → stage `private_label` sem depender do LLM (teste unitário do matcher + integração do processor).
4. Descrições de tools/prompts atualizadas; nenhum teste de aderência quebrado.
5. `pytest` (suíte hermética) verde; `vitest` verde.
6. Nenhuma restrição hard nova em handoff/mudar_stage (diretriz: precisão sem engessar).

## Riscos

- Placeholder na escrita poderia duplicar informação em UI que renderize `content` de mídia — mitigado: bolhas renderizam por `message_type`; previews tratam texto e ganham com o placeholder.
- Gatilho determinístico com frase errada moveria stage indevido — mitigado: matching por igualdade normalizada (não substring), restrito a stages de entrada.
- Prompts mais estritos podem reduzir handoffs legítimos — mitigado: critérios descrevem sinais mínimos (finalidade + avanço), não checklists longos; circuit breaker de turnos permanece como rede.

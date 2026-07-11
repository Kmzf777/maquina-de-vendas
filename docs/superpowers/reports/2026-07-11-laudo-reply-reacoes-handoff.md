# Laudo de Diagnóstico Técnico — Reply, Reações e Handoff Inadequado (11/07/2026)

**Escopo:** 5 anomalias relatadas pela operação no fluxo inbound (Meta Graph API), renderização do CRM e comportamento conversacional da Valéria. **Diretriz:** diagnóstico apenas — nenhuma alteração de código nesta rodada.

---

## Item 1 — Reply exibindo "Mensagem original não disponível" e perda de contexto no prompt

### O que funciona (e onde o relato precisa de correção de premissa)

O parsing do reply NÃO está quebrado. O `meta_parser.py:160` extrai `context.id` do payload da Meta para `quoted_wamid`, que atravessa buffer (`manager.py:75-76`), é persistido em `messages.quoted_wamid` (`conversations/service.py:215-216`) e é enriquecido no prompt da Valéria: o orchestrator resolve o wamid citado em lote (`orchestrator.py:800-890`) e prefixa o turno com `[Em resposta a: "<texto original truncado a 120 chars>"]` (`_build_reply_marker`, `orchestrator.py:382-394`). Há suíte dedicada (`test_reply_reaction_context.py`, `test_meta_quoted_messages.py`).

### Causa raiz A (a dominante) — fotos enviadas pela IA não existem como mensagem no banco

`_dispatch_deferred_media` (`processor.py:1541-1584`) envia as fotos do catálogo via `send_image_base64` e **descarta o retorno da Meta** — o wamid de cada imagem nunca é capturado. Nenhuma linha por imagem é gravada em `messages`; o que se persiste é apenas um marcador system `"[enviar_fotos] ... (k/n)"` sem wamid e sem `message_type` (`tools.py:82-86`).

Consequência em cadeia quando o lead responde (reply) a uma foto da Valéria — exatamente o cenário relatado:
- **Frontend:** `enrichWithQuotedMessages` (`frontend/src/lib/messages-window.ts:26-44`) não encontra o wamid em nenhuma mensagem carregada → `quoted = null` → fallback literal **"Mensagem original não disponível"** (`message-bubble.tsx:98`).
- **Valéria:** `resolve_message_text_by_wamid` (`conversations/service.py:265-292`) não acha a linha → marcador degrada para o genérico `[Em resposta a uma mensagem anterior]` → a IA sabe que é reply, mas **não sabe a qual foto/produto**. A suspeita da operação está confirmada, com esse recorte.
- Bônus de dano: a foto em si nunca aparece como bolha no CRM (só o marcador system), então o operador também não vê o que o lead está citando.

### Causa raiz B — janela de resolução do frontend é só a página carregada

A resolução de citação no frontend é 100% client-side, casando `quoted_wamid` contra o map das mensagens **já carregadas** (janela de 100, `messages-window.ts:6`; fetch em `use-realtime-messages.ts:42-53`). Mensagem citada mais antiga que a janela → fallback, mesmo existindo no banco. Não há lookup dirigido ao banco pela mensagem citada.

### Causa raiz C — legado sem wamid

Mídias enviadas pelo operador antes do fix de 10/07 (904e764, que adicionou wamid ao `send-media/route.ts:215-221` e ao send de texto) não têm `wamid` na linha → irresolvíveis para sempre, em ambas as pontas.

### Observação menor

`QuotedBlock` já trata mídia citada com rótulo ("📷 Imagem" etc., `message-bubble.tsx:60-71,104-108`), mas sem thumbnail — `QuotedMessage` não carrega `media_url` (`types.ts:113-118`).

---

## Item 2 — Handoff disparado por "obrigado"

### Causa raiz — é a ponte pós-handoff, não o LLM

A mensagem relatada casa **verbatim** com `_BRIDGE_TEXT` (`processor.py:804-807`), emitida por `_maybe_send_handoff_bridge` a partir do gate de IA desligada (`processor.py:1103-1113`). A ponte dispara para **qualquer** mensagem de lead já em handoff formal (`human_control=True`, `ai_enabled=False`), **sem nenhuma inspeção de conteúdo** — o único freio é cooldown Redis de 4h (`processor.py:802,846-861`). "Obrigado" pós-handoff → ponte responde com o texto de transbordo.

Os prompts e guardas já excluem corretamente agradecimento do handoff via LLM (`tools.py:237`, `prompts/base.py:341,402-408`, personas de consumo/private_label); o frustration-guardrail determinístico (`processor.py:434-488`) também não contém "obrigado". O LLM não é o culpado — o lead nem chega ao LLM nesse estado. A ponte nasceu de casos reais de vácuo (Maycon/Juliana 01-02/07) e a auditoria de drop-offs de hoje mostra que o vácuo pós-handoff segue sendo a causa nº1 de silêncio — a correção é **refinar** a ponte (filtro de intenção), não removê-la.

---

## Itens 3 e 4 — Envio de reações (IA e operador): capacidade inexistente

Não existe `send_reaction` em lugar nenhum: nem no `MetaCloudClient` (`meta.py` — só text/image/audio/contact/template/typing), nem na interface `WhatsAppProvider`, nem nas 16 tools do agent, nem no composer do frontend (`chat-view.tsx` — texto, áudio gravado, mídia, template).

Arquitetura necessária (a Meta suporta nativamente):
- **API Meta:** `POST /{phone_number_id}/messages` com `{"type": "reaction", "reaction": {"message_id": "<wamid alvo>", "emoji": "❤️"}}`; emoji vazio remove a reação; exige janela de 24h aberta e o wamid da mensagem alvo (temos, para inbound — `messages.wamid`).
- **Backend:** `send_reaction(to, target_wamid, emoji)` na interface `WhatsAppProvider` + `MetaCloudClient` + mock; persistência como linha `role=assistant, message_type="reaction", metadata={emoji, target_wamid}` — **zero migração de schema** (o shape já é o das reações inbound).
- **IA:** para o caso "obrigado", o caminho mais barato e determinístico é a própria ponte/gate reagir com ❤️ em vez de texto (sem LLM); uma tool `reagir_mensagem` para a Valéria é possível, mas é segunda prioridade.
- **Frontend:** ação de hover na bolha inbound → picker de emoji → nova rota Next `POST /api/conversations/[id]/react` (mesmo padrão do `send/route.ts`: chamada direta à Graph API + insert em `messages`); renderização estilo WhatsApp = badge de emoji ancorado na bolha alvo (via `target_wamid`→`wamid`), não bolha separada.

---

## Item 5 — Reação inbound sem referência à mensagem reagida

### Causa raiz — o campo de enriquecimento existe, mas nunca é populado

O webhook preserva a referência: `meta_parser.py:130-136` grava `metadata.target_wamid` + `emoji`, e o backend usa isso no prompt da Valéria (`orchestrator.py:421-432` — "O lead reagiu com X à mensagem: ..."). O tipo `Message.reaction_target` existe no frontend (`types.ts:110`) e `ReactionTargetBlock` (`message-bubble.tsx:116-150`) está pronto para renderizar o alvo — porém **nenhum código escreve `reaction_target`**: `enrichWithQuotedMessages` só resolve `quoted_message`, nunca `metadata.target_wamid`. Resultado: `target` chega sempre null e a UI mostra só "Reagiu com 👍". É uma feature meio-construída; o fix é resolver `target_wamid` no mesmo passe de enriquecimento client-side (mesmas limitações de janela do Item 1-B). Casos em que o alvo é foto da IA caem também na causa 1-A (sem linha no banco, irresolvível).

---

## Plano de ação proposto (próxima rodada, ordem sugerida)

1. **Persistir as fotos da IA como mensagens** (`_dispatch_deferred_media`): capturar `send_result` de cada imagem, `save_message` com `wamid`, `message_type="image"`, `content` = caption/placeholder, `media_url` (idealmente cópia no Storage, paridade com send-media). Resolve o pior recorte dos Itens 1 e 5 e dá visibilidade das fotos ao operador. O marcador system k/n permanece (o dedup da tool depende dele).
2. **Filtro de intenção na ponte pós-handoff**: classificador determinístico de encerramento social (obrigado/valeu/ok/👍/emoji-only) antes de `_maybe_send_handoff_bridge`; encerramento → reagir com ❤️ (novo `send_reaction`) ou silêncio; dúvida real → ponte como hoje. Resolve o Item 2 e cria o primeiro consumidor do Item 3.
3. **`send_reaction` no provider + rota Next `react` + UI de reação no chat** (picker no hover, badge na bolha alvo). Resolve Itens 3 e 4.
4. **Resolução de citação/reação além da janela**: no enrich do frontend, fallback de fetch dirigido ao Supabase pelos `quoted_wamid`/`target_wamid` não resolvidos na página; popular `reaction_target` no mesmo passe. Resolve Item 5 e o resíduo do Item 1-B.
5. **Backend — resolver mídia citada com rótulo**: `resolve_message_text(s)_by_wamid` selecionar também `message_type` e aplicar `describe_media_placeholder` quando `content` vazio, para o marcador do prompt dizer "[Em resposta a: [imagem] ...]" em vez de degradar.
6. **Legado sem wamid (pré-10/07)**: aceitar como irrecuperável (a Meta não reexpõe wamid antigo) — sem backfill.

**Riscos/invariantes a respeitar na implementação:** Dev Router antes do parsing em `backend/app/webhook/`; nova rota `/api/*` no frontend exige atenção ao matcher do proxy; reação exige janela 24h (fail-soft se fechada); não reintroduzir paginação/dieta no `/api/conversations`.

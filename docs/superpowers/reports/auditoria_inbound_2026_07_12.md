# Laudo de Auditoria Inbound — 12/07/2026

**Janela:** 11/07 19:00 UTC (fim da janela da auditoria geral de 11/07, commit `8f049f1`) → 12/07 ~16:30 UTC.
**Escopo:** exclusivamente tráfego inbound orgânico (1ª mensagem da conversa `sent_by='user'`), leads de diretriz excluídos (`5567981382707`, `5511987506497`). Caso `5522991014146` (22:47 UTC 11/07) incluído — já diagnosticado nesta data e corrigido em prod (`070dd77`).
**Método:** extração read-only via MCP prod; leitura integral de 100% dos transcritos da janela (21 conversas / 19 leads / ~290 mensagens), cruzada com marcadores de sistema (`[enviar_fotos]`, `[encaminhar_humano]`, `[ponte]`) e com o código vivo (`processor.py`, `base.py`).

## Volumetria e saúde sistêmica

- 23 conversas com atividade na janela; 21 no escopo inbound (19 orgânicas + 2 fragmentos `handoff_context`); 1 broadcast-origem (Fabio, lido como nota secundária — persona inbound assumiu após 1ª resposta) e 1 template de broadcast sem resposta (excluído).
- **Zero ghosting com IA ligada:** todo inbound com `ai_enabled=true` respondido em ~20–55s.
- **Zero falha de entrega** (`delivery_status` só sent/delivered/read), zero vazamento de tool_code, zero loop, zero resposta vazia, zero alucinação de preço (R$25,70/26,70 250g, R$47,70/48,70 500g, 86 SCA microlote, Néctar 75 SCA — todos conferem).
- **8 handoffs na janela (4 por tool, 4 pela guarda determinística) — todos com cartão ÚNICO. S1 (handoff duplicado) NÃO reproduziu: fix validado em produção.**
- **Caso 0 (áudio transcrito) validado em produção:** Maria Socorro, 15:26 UTC (≈1h após o deploy `070dd77`) — áudio transcrito respondido direto ao conteúdo, sem "me manda por texto". Zero regressão.
- Ponte pós-handoff: silêncio para pergunta de negócio funcionou 4x (Alessandro 2x, Fabio, marcadores `[ponte] pergunta de negócio detectada`); reação ❤️ funcionou 3x ("Obrigado", "Ok Obg"). Reaction-gate validado (👍 isolado do AhirNRF não gerou turno).

## Achados NOVOS

### N1 — Alucinação de envio de fotos (Ana Weiss, 11/07 19:59 UTC) — ÚNICO S-novo da janela
A IA escreveu "enviei aqui algumas fotos pra você ver como ficam as embalagens com a marca do cliente" **sem chamar `enviar_fotos`**: zero mensagens de imagem e zero marcador `[enviar_fotos]` em TODAS as conversas do lead (verificado por agregação). O lead respondeu confuso ("Olha eu aí da não sei / Acho que 250").
**Causa raiz:** verbalização de ação sem tool-call. Existe guarda determinística para "handoff verbalizado sem tool-call" (disparou 2 turnos depois nesta mesma conversa), mas NÃO existe guarda análoga para "envio de fotos verbalizado sem tool-call no turno".
**Recomendação:** guarda no pós-turno — se o texto casa com padrão "enviei/mandei ... fotos/imagens/catálogo" e `enviar_fotos`/`enviar_foto_produto` não executou no turno nem antes na conversa, disparar a tool (ou telemetria `[FOTOS VERBALIZADAS SEM TOOL]` para começar).

### N2 — Vocabulário da ponte: 2 gaps de token (3 ocorrências)
1. `_SOCIAL_CLOSING_TOKENS` não contém **"ta"** → "Tá joia" (Bianca 11/07) e "Ta joia / Obrigada" (Rosângela bom 12/07) falham o `all()` e recebem carimbo + reenvio de cartão em vez de ❤️.
2. `_BUSINESS_QUESTION_TOKENS` só tem **"orcamento"** no singular → "Vou esperar os outros orçamentos para comparar" (Ana Weiss) levou carimbo em cima de um sinal comercial que o humano deveria ler em silêncio.
**Causa raiz:** vocabulários estáticos sem variantes ("ta"/"tá" pós-normalização; plurais no vocabulário de negócio).
**Recomendação:** adicionar "ta", "to", "tou" ao social; pluralizar/stemmar o vocabulário de negócio ("orcamentos", "descontos", "precos" já tem…, revisar um a um).

## Achados CONHECIDOS que persistem

### P1 — S4 (corrida texto-antes-das-fotos): 6 ocorrências na janela
Rosangela Borgonovi, lead 5564999289099, AhirNRF, g t, Alessandro e Fabio — a bolha "enviei aqui as fotos…" chega 4–9s antes das imagens. Cosmético, mas foi exatamente essa moldura que virou alucinação no N1 (o modelo aprendeu a verbalizar o envio; quando a tool não roda, a frase vira mentira). O fix do N1 e do S4 se reforçam.

### P2 — Vácuo humano pós-handoff (pendência da auditoria 11/07, segue sem fix)
Alessandro (lead quente, objeção "100 unidades seria muito, queria experimentar" às 13:10 e pergunta de mínimo às 13:11) chamou o João às 13:17 e seguia sem resposta às 16:30+ (3h, sábado). COTAÇÃO (licitação de 600un/500g, com documento de especificações) chamou às 15:34; Rosângela bom às 16:07. Zero resposta humana nos 3 fragmentos `handoff_context`. O silêncio da ponte está correto — o gargalo é o SLA humano (alerta `handoff_sla_escalation` existe desde `6c1add3`; a fila de sábado é o teste real dele).

## Observações menores (não sistêmicas)

- Bolha run-on sem pontuação (humbertocarvao, 08:32): saudação+pitch+pergunta numa bolha única — fusão de parágrafos ainda passa pelo splitter em turno curto.
- Maria Socorro: handoff prometeu que o João "te ajuda com essa parte de registro" logo após a própria Valéria dizer (corretamente) que registro de marca é responsabilidade do cliente — leve overpromise.
- Bianca: imagem do lead ("Eu queria assim") coalescida com texto não foi reconhecida no turno (Caso 1 pede reconhecimento explícito do envio).
- Rosangela Borgonovi: turno final (84 SCA) sem pergunta de avanço; lead esfriou ali com IA ligada.

## Veredito

Fluxo inbound **saudável no núcleo** (latência, entrega, preços, qualificação, handoffs únicos, Caso 0 e ponte-reação/silêncio validados). Um bug comportamental novo (N1, 1 ocorrência), dois gaps de vocabulário baratos (N2, 3 ocorrências) e duas pendências conhecidas (S4 cosmético recorrente; vácuo humano — o maior risco de conversão da janela, com 3 leads quentes parados na fila do João num sábado).

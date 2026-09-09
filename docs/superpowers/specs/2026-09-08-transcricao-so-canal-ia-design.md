# Transcrição de áudio só no canal da IA — corte do gasto no número do João

**Data:** 2026-09-08 · **Origem:** usuário — "remova completamente transcrição de áudios do canal humano, ou seja, número do João; isso dispara os custos, só faz sentido para a Valéria".
**Diretriz dominante:** cortar 100% do gasto de transcrição no canal humano SEM tocar em nada do fluxo da Valéria e SEM quebrar o player de áudio do CRM.

## Problema

Hoje toda mensagem de áudio que entra é transcrita pelo Gemini, e isso acontece ANTES de qualquer gate de IA.

O `_resolve_media` é chamado em `backend/app/buffer/processor.py:1269`, dentro de `process_buffered_messages`, logo depois de resolver lead/canal/conversa. Os gates que decidem se a IA roda vêm todos DEPOIS:

| Gate | Linha |
|---|---|
| canal humano (`channel.mode == "human"`) | ~1418 |
| kill switch global (`VALERIA_ENABLED`) | ~1427 |
| lead pós-handoff (`lead.ai_enabled == false`) | ~1435 |
| allowlist de canal (`ai_phone_number_ids`) | ~1458 |

Consequência: no número do João — canal cadastrado com `mode="human"`, onde a Valéria nunca responde — cada áudio de cliente paga uma chamada `generateContent` cujo texto **nenhum consumidor lê**. O prompt da Valéria (`agent/prompts/base.py:847`), o dossiê e o rolling summary não rodam nesse canal. É desperdício integral, não desperdício parcial.

Agrava: a transcrição também não é exibida no chat. `frontend/src/components/conversas/message-bubble.tsx:313` renderiza apenas o player quando `message_type === "audio"` — a cadeia de ternários nunca chega ao branch de texto. Ou seja, hoje ninguém no canal do João consome esse texto por nenhuma via de leitura direta.

## Decisão de escopo

**Cortar apenas em `channel.mode == "human"`.** Os outros três caminhos sem IA ficam intocados, por decisão consciente:

| Caminho | Decisão | Motivo |
|---|---|---|
| `channel.mode == "human"` | **CORTA** | Canal do João. Nenhum consumidor do texto roda ali. Alvo do pedido. |
| `lead.ai_enabled == false` (pós-handoff no número da Valéria) | **MANTÉM** | A ponte pós-handoff (`_maybe_send_handoff_bridge`, `processor.py:1444`) recebe `inbound_text=resolved_text` e usa o conteúdo para decidir entre mandar o aviso de roteamento ou só reagir com ❤️. Sem transcrição ela fica cega para áudios. |
| `VALERIA_ENABLED == false` (kill switch) | **MANTÉM** | Estado temporário de emergência. Áudios recebidos durante a janela ficariam sem texto para sempre, e o kill switch existe justamente para ser revertido. |
| canal fora da `ai_phone_number_ids` | **MANTÉM** | Allowlist é ferramenta de rollout gradual, não declaração de que o canal é humano. `mode` é quem declara isso. |

`channel.mode` é o conceito já estabelecido no codebase para "esse número é atendido por gente": validado na API (`app/channels/router.py:47`, valores `"ai"` | `"human"`), configurável em tela, e já usado como gate em follow-up (`follow_up/scheduler.py:646`), broadcast (`broadcast/worker.py:384`) e watchdog (`watchdog/service.py:547`). Reusá-lo evita inventar um segundo eixo de configuração para a mesma ideia.

## Arquitetura

`_resolve_media` ganha um parâmetro `transcribe: bool = True`. Quem decide é o call site, onde o canal já é conhecido:

```
# processor.py:1269 (call site)
transcribe=channel.get("mode", "ai") != "human"
```

O default `True` preserva os chamadores existentes e os testes que já fazem monkeypatch da função.

Dentro do bloco de áudio (`processor.py:2144-2184`), o que muda é **só a ETAPA 2**:

| Etapa | Canal `ai` | Canal `human` |
|---|---|---|
| 1. Download do Meta (com retry) | roda | **roda** |
| 1b. Upload pro bucket `audio` do Supabase Storage | roda | **roda** |
| `media_url` / `message_type="audio"` | preenchidos | **preenchidos** |
| 2. Transcrição (`generateContent`) | roda | **NÃO roda** |
| `content` salvo | `[audio transcrito: X]` | `[áudio]` |

Manter download e upload é o que preserva o player de áudio em /conversas. O vendedor continua ouvindo o áudio exatamente como hoje — apenas não se paga um LLM para descrever algo que ninguém lê.

### Escolha do marcador

Constante nova `_AUDIO_NO_TRANSCRIPTION_MARKER = "[áudio]"`, alinhada com `_MEDIA_PLACEHOLDERS["audio"]` (`app/conversations/service.py:366`), que é o texto que a camada de leitura já renderiza para áudio sem conteúdo.

Deliberadamente **não** se reusa o `_AUDIO_FAIL_MARKER` (`processor.py:206`): ele alimenta o contador de insistência `_count_recent_failed_audio` (`processor.py:499`), que a partir do 2º áudio falho escala o lead para humano (`processor.py:1516-1523`). Aqui não houve falha alguma — a transcrição não foi tentada por decisão de projeto. Reusar o marcador de falha plantaria uma métrica mentirosa e um gatilho de escalação espúrio.

Também não se usa string vazia: `content` vazio depende da camada de leitura para virar `[áudio]` e apareceria como bolha muda em qualquer consumidor que leia `content` cru.

## Não-regressão da ValerIA

O único ponto de decisão é `channel.get("mode", "ai") != "human"`. Canal com `mode="ai"` e canal com `mode` nulo (que cai no default `"ai"`) seguem com comportamento idêntico ao atual — mesma chamada, mesmo `call_type="media_transcription"` no `token_usage`, mesmo marcador `[audio transcrito: ...]` que o `base.py:847` (Caso 0) espera.

## Trade-off aceito, explicitamente

No número do João, a busca de mensagens (/conversas e /busca, que consultam `messages.content`) deixa de encontrar áudios pelo que foi falado — eles passam a ser `[áudio]`. Como o chat já não exibia a transcrição, o vendedor não perde nada que conseguisse ler hoje; perde-se a busca por conteúdo falado nesse canal.

Registro de interação futura: se o "score de lead" do Bloco 4 (branch não pushed) vier a ler `messages.content`, ele ficará sem o texto dos áudios no canal humano.

## Testes

1. Canal `mode="human"`: `transcribe_audio` NÃO é chamado; `media_url` continua preenchido (player intacto); `content` volta `[áudio]`.
2. Canal `mode="ai"`: `transcribe_audio` É chamado — não-regressão do fluxo da Valéria.
3. Canal sem `mode` (chave ausente/nula): transcreve, confirmando o default `"ai"`.
4. Canal `mode="human"`: o `content` resultante NÃO contém o `_AUDIO_FAIL_MARKER` — garante que a escalação por áudio insistente não é envenenada.

## Métricas de aceite

- Suíte pytest do backend 100% verde, incluindo `test_transcricao_finops_2026_07_08.py`, `test_prompt_audio_transcrito_2026_07_12.py` e `test_save_message_media.py`.
- Pós-deploy: zero linhas novas em `token_usage` com `call_type="media_transcription"` atribuídas a conversas do canal `mode="human"`.
- Player de áudio em /conversas continua funcionando no canal do João (validação manual).

## Fora de escopo

- Exibir a transcrição no chat do CRM (o gap real de UX descoberto na investigação — `message-bubble.tsx:313`). Item separado.
- Re-transcrição sob demanda / endpoint avulso. Não existe hoje e não é criado aqui.
- Qualquer alteração nos outros três caminhos sem IA (tabela da seção "Decisão de escopo").

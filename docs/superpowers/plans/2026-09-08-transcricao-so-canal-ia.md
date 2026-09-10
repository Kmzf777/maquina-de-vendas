# Transcrição de áudio só no canal da IA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parar de pagar transcrição Gemini para áudios que chegam no canal humano (número do João, `channel.mode == "human"`), onde nenhum consumidor lê o texto — sem tocar no fluxo da Valéria e sem quebrar o player de áudio do CRM.

**Architecture:** `_resolve_media` ganha um parâmetro `transcribe: bool = True`. O call site em `process_buffered_messages` deriva o valor de `channel.mode`. Quando `transcribe=False`, o bloco de áudio mantém download e upload pro Supabase Storage (então `media_url` e `message_type` continuam preenchidos e o player funciona) e pula apenas a chamada `generateContent`, gravando o marcador `[áudio]` no `content`.

**Tech Stack:** Python 3, FastAPI, pytest + pytest-asyncio, `unittest.mock` (AsyncMock/MagicMock/patch), Google GenAI SDK.

**Spec:** `docs/superpowers/specs/2026-09-08-transcricao-so-canal-ia-design.md`

---

## File Structure

| Arquivo | Responsabilidade | Ação |
|---|---|---|
| `backend/app/buffer/processor.py` | Constante do marcador (perto do `_AUDIO_FAIL_MARKER`, ~linha 206); parâmetro `transcribe` e skip em `_resolve_media` (~2118-2184); gate no call site (~1269) | Modificar |
| `backend/tests/test_transcricao_canal_humano_2026_09_08.py` | Toda a cobertura nova: skip, preservação do player, marcador correto, não-regressão do canal IA, derivação do flag no call site | Criar |

Nenhum arquivo novo de produção. A mudança é pequena e pertence ao módulo que já é dono do fluxo de mídia do inbound.

---

## Task 1: `_resolve_media` respeita `transcribe=False`

**Files:**
- Modify: `backend/app/buffer/processor.py` (constante após `_AUDIO_FAIL_MARKER` na linha 206; assinatura e docstring de `_resolve_media` em 2118-2128; bloco de áudio em 2167)
- Test: `backend/tests/test_transcricao_canal_humano_2026_09_08.py`

- [ ] **Step 1: Escrever o teste falhando**

Criar `backend/tests/test_transcricao_canal_humano_2026_09_08.py`:

```python
"""Transcrição de áudio NÃO roda no canal humano (número do João) — 2026-09-08.

Todo áudio era transcrito pelo Gemini ANTES dos gates de IA: `_resolve_media` roda
em processor.py:1269 e o gate de canal humano só aparece ~150 linhas depois. No canal
mode="human" ninguém lê esse texto — o prompt da Valéria não roda ali e o chat do CRM
só mostra o player (message-bubble.tsx:313). Gasto integralmente desperdiçado.

Cobre:
  1. transcribe=False pula o Gemini mas PRESERVA o player (download + upload seguem);
  2. o marcador usado NÃO é o de falha — aquele alimenta _count_recent_failed_audio e
     escalaria o lead para humano por um problema que não existe;
  3. canal de IA segue transcrevendo (não-regressão);
  4. o call site deriva o flag de channel.mode.
"""
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.buffer import processor


def _fake_provider(mime: str = "audio/ogg; codecs=opus"):
    """Provider mínimo: download_media devolve a tupla (bytes, content_type)."""
    provider = MagicMock()
    provider.download_media = AsyncMock(return_value=(b"OGGDATA", mime))
    return provider


@pytest.mark.asyncio
async def test_canal_humano_nao_chama_gemini_mas_preserva_o_player(monkeypatch):
    """transcribe=False: zero chamada de LLM, mas media_url continua vindo."""
    transcribe = AsyncMock(return_value=("nao deveria ser chamado", None))
    monkeypatch.setattr(processor, "transcribe_audio", transcribe)
    monkeypatch.setattr(
        processor, "_upload_audio_to_storage",
        lambda *a, **k: "https://storage.local/audio/mid1.ogg",
    )

    text, media_url, message_type, _doc, _meta = await processor._resolve_media(
        "[audio: media_id=mid1]", _fake_provider(), transcribe=False,
    )

    transcribe.assert_not_awaited()
    assert text == "[áudio]"
    assert message_type == "audio"
    assert media_url == "https://storage.local/audio/mid1.ogg", (
        "upload pro Storage tem que continuar — sem media_url o player do CRM some"
    )


@pytest.mark.asyncio
async def test_canal_humano_nao_usa_o_marcador_de_falha(monkeypatch):
    """Pular por decisão != falhar. O marcador de falha dispara escalação por nada."""
    monkeypatch.setattr(processor, "transcribe_audio", AsyncMock())
    monkeypatch.setattr(processor, "_upload_audio_to_storage", lambda *a, **k: None)

    text, _url, _type, _doc, _meta = await processor._resolve_media(
        "[audio: media_id=mid1]", _fake_provider(), transcribe=False,
    )

    assert processor._AUDIO_FAIL_MARKER not in text
    assert "media_id" not in text, "placeholder cru não pode vazar para o CRM"


@pytest.mark.asyncio
async def test_canal_de_ia_continua_transcrevendo_por_default(monkeypatch):
    """Não-regressão: sem o parâmetro, o comportamento é byte a byte o de hoje."""
    transcribe = AsyncMock(return_value=("quero 5 quilos do microlote", None))
    monkeypatch.setattr(processor, "transcribe_audio", transcribe)
    monkeypatch.setattr(processor, "_upload_audio_to_storage", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.agent.token_tracker.track_token_usage", lambda **k: None,
    )

    text, _url, message_type, _doc, _meta = await processor._resolve_media(
        "[audio: media_id=mid1]", _fake_provider(),
    )

    transcribe.assert_awaited_once()
    assert text == "[audio transcrito: quero 5 quilos do microlote]"
    assert message_type == "audio"
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd backend && python -m pytest tests/test_transcricao_canal_humano_2026_09_08.py -v`

Expected: os dois primeiros testes FALHAM com `TypeError: _resolve_media() got an unexpected keyword argument 'transcribe'`. O terceiro (`..._continua_transcrevendo_por_default`) PASSA — ele descreve o comportamento atual e existe justamente para provar que a Task 1 não o quebra.

- [ ] **Step 3: Adicionar a constante do marcador**

Em `backend/app/buffer/processor.py`, logo depois do bloco do `_AUDIO_FAIL_MARKER` (linha 206), antes do comentário `# B3 (graceful degradation de mídia)`:

```python
# Áudio em canal humano: NÃO é falha — a transcrição não foi sequer tentada, porque
# ninguém lê o texto lá (o prompt da Valéria não roda e o chat só mostra o player).
# Marcador próprio, distinto do _AUDIO_FAIL_MARKER de propósito: aquele alimenta o
# _count_recent_failed_audio e escalaria o lead para humano por um problema inexistente.
# O texto casa com _MEDIA_PLACEHOLDERS["audio"] (app/conversations/service.py), que é o
# que a camada de leitura já renderiza para áudio sem conteúdo.
_AUDIO_NO_TRANSCRIPTION_MARKER = "[áudio]"
```

- [ ] **Step 4: Adicionar o parâmetro na assinatura e na docstring**

Trocar a assinatura de `_resolve_media` (linha 2118-2120) por:

```python
async def _resolve_media(
    text: str, provider, lead_id: str | None = None, stage: str = "",
    transcribe: bool = True,
) -> tuple[str, str | None, str | None, str | None, dict | None]:
```

E, na docstring, substituir a linha `Audio: downloaded, transcribed, uploaded to Supabase Storage.` por:

```
    Audio: downloaded, uploaded to Supabase Storage e — se `transcribe` — transcrito.
    `transcribe=False` (canal humano) pula SÓ a chamada ao Gemini: o download e o
    upload continuam, então `media_url` segue preenchido e o player do CRM não quebra.
```

- [ ] **Step 5: Pular a transcrição quando `transcribe=False`**

No bloco de áudio, imediatamente antes do comentário `# ETAPA 2 — TRANSCRIÇÃO` (linha 2167), inserir:

```python
            # Canal humano (número do João): o texto não tem consumidor — o prompt da
            # Valéria não roda aqui e o chat do CRM só exibe o player. Pagar
            # generateContent por ele é desperdício integral. O áudio já subiu pro
            # Storage acima, então o player continua funcionando normalmente.
            if not transcribe:
                logger.info(
                    "[AUDIO] transcrição pulada (canal humano) para %s", media_ref,
                )
                text = text.replace(match.group(0), _AUDIO_NO_TRANSCRIPTION_MARKER)
                continue
```

- [ ] **Step 6: Rodar os testes**

Run: `cd backend && python -m pytest tests/test_transcricao_canal_humano_2026_09_08.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/buffer/processor.py backend/tests/test_transcricao_canal_humano_2026_09_08.py
git commit -F - <<'EOF'
feat(audio): _resolve_media aceita transcribe=False

Pula so a chamada ao Gemini; download e upload pro Storage seguem, entao
media_url continua preenchido e o player do CRM nao quebra. Marcador
proprio ([audio]) em vez do de falha, que alimentaria a escalacao por
audio insistente sem ter havido falha nenhuma.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

## Task 2: Call site deriva o flag de `channel.mode`

**Files:**
- Modify: `backend/app/buffer/processor.py:1269-1271` (chamada dentro de `process_buffered_messages`)
- Test: `backend/tests/test_transcricao_canal_humano_2026_09_08.py` (append)

- [ ] **Step 1: Escrever o teste falhando**

Adicionar ao fim de `backend/tests/test_transcricao_canal_humano_2026_09_08.py`:

```python
def _patch_pipeline(stack: ExitStack, *, channel: dict) -> AsyncMock:
    """Mocka process_buffered_messages até logo depois do _resolve_media.

    VALERIA_ENABLED=False faz a função retornar no gate seguinte ao de canal humano,
    então tanto o canal 'human' quanto o 'ai' param cedo — o que basta: o objeto sob
    teste é o kwarg `transcribe` com que _resolve_media foi chamado.
    """
    lead = {"id": "L1", "phone": "5534988861441", "wa_id": "5534988861441",
            "ai_enabled": True, "stage": "atacado", "metadata": {}}
    conv = {"id": "conv1", "status": "active", "stage": "atacado", "followup_enabled": False}

    p = lambda name, *args, **kw: stack.enter_context(patch.object(processor, name, *args, **kw))

    p("get_or_create_lead", return_value=lead)
    p("get_channel_by_id", return_value=channel)
    p("get_or_create_conversation", return_value=conv)
    p("get_provider", return_value=MagicMock())
    p("update_conversation", MagicMock())
    p("get_supabase", MagicMock())
    p("run_with_retry", MagicMock(return_value=MagicMock(data={"unread_count": 0})))
    p("_wamid_already_processed", return_value=False)
    p("_is_recent_duplicate", return_value=False)
    p("save_message", MagicMock(return_value={"created_at": "2026-09-08T12:00:00Z"}))
    p("_update_last_msg", MagicMock())
    p("VALERIA_ENABLED", False)

    resolve = p("_resolve_media", new=AsyncMock(return_value=("[áudio]", "u", "audio", None, None)))

    # Efeitos colaterais best-effort (lazy imports) — neutralizados p/ não tocar rede.
    stack.enter_context(patch("app.broadcast.service.record_broadcast_reply", MagicMock()))
    stack.enter_context(patch("app.campaigns.worker.handle_campaign_reply", MagicMock()))
    stack.enter_context(patch("app.automation.triggers.fire_trigger", new=AsyncMock()))

    return resolve


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel, esperado",
    [
        ({"id": "ch1", "mode": "human", "provider_config": {}}, False),
        ({"id": "ch1", "mode": "ai", "provider_config": {}}, True),
        ({"id": "ch1", "provider_config": {}}, True),
    ],
    ids=["canal-humano-nao-transcreve", "canal-ia-transcreve", "sem-mode-default-ai"],
)
async def test_flag_de_transcricao_vem_do_mode_do_canal(channel, esperado):
    with ExitStack() as stack:
        resolve = _patch_pipeline(stack, channel=channel)
        await processor.process_buffered_messages(
            "5534988861441", "[audio: media_id=mid1]", "ch1", wamid="wamid-1",
        )

    assert resolve.await_args.kwargs["transcribe"] is esperado
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd backend && python -m pytest tests/test_transcricao_canal_humano_2026_09_08.py -k flag_de_transcricao -v`
Expected: os 3 casos FALHAM com `KeyError: 'transcribe'` — o call site ainda não passa o kwarg.

Se em vez disso o teste estourar em alguma dependência não mockada (chamada de rede, `AttributeError` num mock), acrescente o nome ao `_patch_pipeline` e rode de novo. O fixture foi modelado no `_patch_pipeline` de `tests/test_content_dedup_bypass.py`, que já exercita este mesmo caminho com `mode="human"` — a lista de patches ali é a referência.

- [ ] **Step 3: Passar o flag no call site**

Em `backend/app/buffer/processor.py`, trocar o bloco da linha 1268-1271 por:

```python
    try:
        # Transcrição só no canal da IA: em canal humano (número do João) ninguém lê o
        # texto — a Valéria não responde ali e o chat do CRM mostra apenas o player.
        # Mesmo gate de `mode` já usado em follow-up, broadcast e watchdog.
        resolved_text, _media_url, _message_type, _document_name, _metadata = await _resolve_media(
            combined_text, provider, lead_id=lead.get("id"), stage=lead.get("stage") or "",
            transcribe=channel.get("mode", "ai") != "human",
        )
```

- [ ] **Step 4: Rodar os testes**

Run: `cd backend && python -m pytest tests/test_transcricao_canal_humano_2026_09_08.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/buffer/processor.py backend/tests/test_transcricao_canal_humano_2026_09_08.py
git commit -F - <<'EOF'
feat(audio): nao transcreve audio no canal humano

process_buffered_messages deriva o flag de channel.mode, o mesmo gate ja
usado em follow-up, broadcast e watchdog. Canal mode=ai (e canal sem mode,
que cai no default) seguem inalterados.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

## Task 3: Suíte completa e verificação de não-regressão

**Files:** nenhum (só verificação)

- [ ] **Step 1: Rodar as suítes vizinhas de áudio primeiro**

Run:
```bash
cd backend && python -m pytest \
  tests/test_transcricao_finops_2026_07_08.py \
  tests/test_prompt_audio_transcrito_2026_07_12.py \
  tests/test_save_message_media.py \
  tests/test_media_placeholder_2026_07_10.py \
  tests/test_content_dedup_bypass.py -v
```
Expected: all passed. São as suítes que tocam o mesmo caminho de áudio/mídia — se alguma quebrar, o problema é a mudança, não o teste.

- [ ] **Step 2: Rodar a suíte inteira do backend**

Run: `cd backend && python -m pytest -q`
Expected: 0 failed. O repositório trabalha com a suíte inteira verde; qualquer falha aqui bloqueia o passo seguinte.

- [ ] **Step 3: Confirmar que não sobrou chamada de transcrição fora do gate**

Run: `cd backend && grep -rn "transcribe_audio\|_transcribe_audio" app/`
Expected: exatamente 4 ocorrências — a definição em `app/agent/gemini_client.py`, o import e a definição de `_transcribe_audio` em `app/buffer/processor.py`, e a única chamada dentro do bloco de áudio de `_resolve_media`. Nenhum outro call site pode existir; se existir, ele não passa pelo gate e precisa entrar no plano.

- [ ] **Step 4: Commit (se houve algum ajuste nos passos acima)**

```bash
git add -A
git commit -F - <<'EOF'
test(audio): suite verde apos o corte de transcricao no canal humano

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

Se nada mudou nos passos 1-3, pular este commit.

---

## Verificação manual pós-deploy (não bloqueia o merge)

1. Abrir uma conversa do canal do João em /conversas que tenha áudio recente e confirmar que **o player toca** (o `media_url` continua sendo gravado).
2. Consultar o `token_usage` procurando linhas novas com `call_type='media_transcription'` atribuídas a conversas do canal `mode='human'` — o esperado é **zero**.
3. Mandar um áudio de teste para o número da Valéria (5534988861441, ver `reference_numero_teste_whatsapp`) e confirmar que a resposta trata o conteúdo falado normalmente — o marcador `[audio transcrito: ...]` continua chegando ao prompt.

## Fora de escopo (não implementar aqui)

- Exibir a transcrição no chat do CRM (`message-bubble.tsx:313` só renderiza o player). É o gap de UX descoberto na investigação, e vira item próprio.
- Cortar transcrição nos outros caminhos sem IA (`lead.ai_enabled=false`, kill switch, allowlist) — decisão consciente registrada na spec.

# Fix enviar_fotos — Meta Media Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir a tool `enviar_fotos` que registra (0/5) envios, substituindo o método `send_image_base64` que usava `data:` URIs inválidas pela Meta Cloud API pelo fluxo correto de Media Upload.

**Architecture:** A Meta Cloud API não aceita `data:` URIs no campo `link`. O fluxo correto é: (1) fazer upload multipart dos bytes da imagem para `/v21.0/{phone_id}/media` e obter um `media_id`, (2) enviar a mensagem usando `{"id": media_id}`. As fotos reais dos produtos são extraídas do backup n8n JSON e salvas nos diretórios locais.

**Tech Stack:** Python 3.11+, httpx (async), pytest, Meta Cloud API v21.0

---

## Arquivos Afetados

| Ação | Arquivo |
|------|---------|
| Modificar | `backend/app/whatsapp/meta.py` |
| Modificar | `backend/app/agent/tools.py` |
| Criar | `backend/tests/test_meta_media_upload.py` |
| Executar e deletar | `backend/scripts/extract_photos_n8n.py` (temporário) |
| Deletar após extração | `Valéria Fotos (2).json` (raiz do projeto) |

---

## Task 1: Extrair fotos do JSON do n8n

**Contexto:** O arquivo `Valéria Fotos (2).json` contém os fluxos do n8n com as imagens reais dos produtos em base64 dentro dos nós `Edit Fields`. O script identifica os nós pela posição (antes/depois dos sentinelas de categoria) e salva os arquivos `.jpg`/`.png` sobrescrevendo os placeholders existentes.

**Mapeamento de nós → arquivos:**
- `Edit Fields` → `atacado/foto_1.jpg`
- `Edit Fields1` → `atacado/foto_2.jpg`
- `Edit Fields2` → `atacado/foto_3.*` (detectar JPEG/PNG pelos magic bytes)
- `Edit Fields3` → `atacado/foto_4.jpg`
- `Edit Fields4` → `atacado/foto_5.jpg`
- `Edit Fields5` = sentinela "fim atacado" (sem imagem)
- `Edit Fields6` → `private_label/foto_1.jpg`
- `Edit Fields7` → `private_label/foto_2.jpg`
- `Edit Fields8` → `private_label/foto_3.jpg`
- `Edit Fields9` → `private_label/foto_4.jpg`
- `Edit Fields10` = sentinela "fim private_label" (sem imagem)

**Files:**
- Create: `backend/scripts/extract_photos_n8n.py`

- [ ] **Step 1: Criar o script de extração**

Criar `backend/scripts/extract_photos_n8n.py` com o conteúdo:

```python
#!/usr/bin/env python3
"""
Script temporário de extração. Executar uma vez e deletar.
Uso: python backend/scripts/extract_photos_n8n.py
"""
import base64
import json
from pathlib import Path

JSON_PATH = Path(__file__).parent.parent.parent / "Valéria Fotos (2).json"
PHOTOS_BASE = Path(__file__).parent.parent / "app" / "photos"

CATEGORY_SENTINEL = "você acabou de enviar as imagens de todos os produtos"

def detect_ext(raw_bytes: bytes) -> str:
    if raw_bytes[:2] == b'\xff\xd8':
        return "jpg"
    if raw_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        return "png"
    return "jpg"

def main():
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    nodes = data.get("nodes", [])

    category = "atacado"
    counters = {"atacado": 0, "private_label": 0}

    for node in nodes:
        params = node.get("parameters", {})
        assignments = params.get("assignments", {}).get("assignments", [])

        # Detectar sentinela de mudança de categoria
        for a in assignments:
            if a.get("name") == "status":
                val = str(a.get("value", ""))
                if "todos os produtos" in val:
                    category = "private_label"
                    continue

        # Processar imagem se existir
        img_value = next(
            (a.get("value", "") for a in assignments if a.get("name") == "imagem"),
            None,
        )
        if not img_value or len(str(img_value)) < 100:
            continue

        raw_b64 = str(img_value)
        # Corrigir padding se necessário
        padding = (4 - len(raw_b64) % 4) % 4
        raw_b64 += "=" * padding

        try:
            decoded = base64.b64decode(raw_b64)
        except Exception as e:
            print(f"  ERRO ao decodificar nó '{node.get('name')}': {e}")
            continue

        counters[category] += 1
        ext = detect_ext(decoded)
        filename = f"foto_{counters[category]}.{ext}"
        dest = PHOTOS_BASE / category / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(decoded)
        print(f"  ✓ {category}/{filename} — {len(decoded):,} bytes")

    print(f"\nResultado: atacado={counters['atacado']} fotos, private_label={counters['private_label']} fotos")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Executar o script**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra"
python backend/scripts/extract_photos_n8n.py
```

Saída esperada (exemplo):
```
  ✓ atacado/foto_1.jpg — 94,xxx bytes
  ✓ atacado/foto_2.jpg — 48,xxx bytes
  ✓ atacado/foto_3.jpg — xx,xxx bytes
  ✓ atacado/foto_4.jpg — 78,xxx bytes
  ✓ atacado/foto_5.jpg — 67,xxx bytes
  ✓ private_label/foto_1.jpg — 107,xxx bytes
  ✓ private_label/foto_2.jpg — 97,xxx bytes
  ✓ private_label/foto_3.jpg — 88,xxx bytes
  ✓ private_label/foto_4.jpg — 163,xxx bytes

Resultado: atacado=5 fotos, private_label=4 fotos
```

- [ ] **Step 3: Verificar arquivos gerados**

```bash
ls -lh "/home/Kelwin/Kelwin - Maquinadevendascanastra/backend/app/photos/atacado/"
ls -lh "/home/Kelwin/Kelwin - Maquinadevendascanastra/backend/app/photos/private_label/"
```

Verificar que todos os arquivos têm tamanho > 0 e são JPEGs/PNGs válidos.

- [ ] **Step 4: Deletar JSON e script temporário**

```bash
rm "/home/Kelwin/Kelwin - Maquinadevendascanastra/Valéria Fotos (2).json"
rm "/home/Kelwin/Kelwin - Maquinadevendascanastra/backend/scripts/extract_photos_n8n.py"
```

- [ ] **Step 5: Commit**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra"
git add backend/app/photos/
git commit -m "feat(photos): extrair fotos reais dos produtos do backup n8n"
```

---

## Task 2: Escrever testes para o novo fluxo de Media Upload

**Contexto:** A Meta Cloud API exige upload prévio da mídia para obter um `media_id`. Vamos testar `upload_media`, `send_image_bytes` e que `send_image_base64` delega corretamente.

**Files:**
- Create: `backend/tests/test_meta_media_upload.py`

- [ ] **Step 1: Criar o arquivo de testes**

Criar `backend/tests/test_meta_media_upload.py`:

```python
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.whatsapp.meta import MetaCloudClient

CONFIG = {
    "phone_number_id": "123456",
    "access_token": "test_token",
    "api_version": "v21.0",
}
FAKE_JPEG = b'\xff\xd8\xff' + b'\x00' * 20
FAKE_B64 = base64.b64encode(FAKE_JPEG).decode()


def _make_mock_resp(json_data: dict, success: bool = True):
    resp = MagicMock()
    resp.is_success = success
    resp.json = MagicMock(return_value=json_data)
    resp.raise_for_status = MagicMock()
    resp.status_code = 200 if success else 400
    resp.reason_phrase = "OK" if success else "Bad Request"
    resp.text = str(json_data)
    return resp


def _patch_httpx(responses: list):
    """Patch httpx.AsyncClient to return a sequence of responses."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=responses)
    return patch("app.whatsapp.meta.httpx.AsyncClient", return_value=mock_client), mock_client


@pytest.mark.asyncio
async def test_upload_media_returns_media_id():
    client = MetaCloudClient(CONFIG)
    upload_resp = _make_mock_resp({"id": "media_abc123"})

    ctx, mock_http = _patch_httpx([upload_resp])
    with ctx:
        media_id = await client.upload_media(FAKE_JPEG, "image/jpeg")

    assert media_id == "media_abc123"
    call = mock_http.post.call_args
    assert "123456/media" in call.args[0]
    assert call.kwargs["data"]["messaging_product"] == "whatsapp"
    assert call.kwargs["data"]["type"] == "image/jpeg"
    assert "file" in call.kwargs["files"]


@pytest.mark.asyncio
async def test_upload_media_logs_error_on_failure():
    client = MetaCloudClient(CONFIG)
    error_resp = _make_mock_resp(
        {"error": {"message": "Invalid token", "code": 190}},
        success=False,
    )
    error_resp.raise_for_status = MagicMock(side_effect=Exception("HTTP 400"))

    ctx, _ = _patch_httpx([error_resp])
    with ctx, pytest.raises(Exception, match="HTTP 400"):
        await client.upload_media(FAKE_JPEG, "image/jpeg")


@pytest.mark.asyncio
async def test_send_image_bytes_uses_media_id_not_data_url():
    client = MetaCloudClient(CONFIG)
    msg_resp = _make_mock_resp({"messages": [{"id": "wamid_xyz"}]})
    msg_resp.raise_for_status = MagicMock()

    with patch.object(client, "upload_media", new_callable=AsyncMock, return_value="media_abc") as mock_upload, \
         patch.object(client, "_post", new_callable=AsyncMock, return_value=msg_resp.json()) as mock_post:
        await client.send_image_bytes("5511999...", FAKE_JPEG, "image/jpeg", caption="Foto 1")

    mock_upload.assert_called_once_with(FAKE_JPEG, "image/jpeg")
    payload = mock_post.call_args[0][0]
    assert payload["image"]["id"] == "media_abc"
    assert payload["image"]["caption"] == "Foto 1"
    assert "link" not in payload["image"]


@pytest.mark.asyncio
async def test_send_image_bytes_no_caption():
    client = MetaCloudClient(CONFIG)

    with patch.object(client, "upload_media", new_callable=AsyncMock, return_value="media_no_cap"), \
         patch.object(client, "_post", new_callable=AsyncMock, return_value={}) as mock_post:
        await client.send_image_bytes("5511999...", FAKE_JPEG)

    payload = mock_post.call_args[0][0]
    assert "caption" not in payload["image"]


@pytest.mark.asyncio
async def test_send_image_base64_delegates_to_send_image_bytes():
    client = MetaCloudClient(CONFIG)

    with patch.object(client, "send_image_bytes", new_callable=AsyncMock, return_value={}) as mock_send:
        await client.send_image_base64("5511999...", FAKE_B64, "image/jpeg", caption="hello")

    mock_send.assert_called_once_with("5511999...", FAKE_JPEG, "image/jpeg", caption="hello")
```

- [ ] **Step 2: Rodar testes para confirmar que falham (métodos ainda não existem)**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/backend"
python -m pytest tests/test_meta_media_upload.py -v 2>&1 | tail -20
```

Esperado: falhas em `upload_media` e `send_image_bytes` (AttributeError ou similar), pois ainda não existem.

---

## Task 3: Implementar upload de mídia em meta.py

**Contexto:** Adicionar `_media_url` no `__init__`, `upload_media` (POST multipart), `send_image_bytes` (usa media_id), e refatorar `send_image_base64` para decodificar e delegar. O método `send_image` (URL direta) permanece inalterado para casos de uso futuros.

**Files:**
- Modify: `backend/app/whatsapp/meta.py`

- [ ] **Step 1: Editar meta.py**

Substituir o conteúdo de `backend/app/whatsapp/meta.py` por:

```python
import base64
import json
import logging
import httpx
from app.whatsapp.base import WhatsAppProvider

META_API_BASE = "https://graph.facebook.com"

logger = logging.getLogger(__name__)


class MetaCloudClient(WhatsAppProvider):
    def __init__(self, config: dict):
        self.phone_number_id = config["phone_number_id"]
        self.access_token = config["access_token"]
        api_version = config.get("api_version", "v21.0")
        self._messages_url = f"{META_API_BASE}/{api_version}/{self.phone_number_id}/messages"
        self._media_url = f"{META_API_BASE}/{api_version}/{self.phone_number_id}/media"

    def _url(self) -> str:
        return self._messages_url

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def _post(self, payload: dict) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._url(), json=payload, headers=self._headers())
            if not resp.is_success:
                try:
                    error_body = resp.json()
                except Exception:
                    error_body = resp.text
                logger.error(
                    "[Meta API] %s %s — payload: %s — response: %s",
                    resp.status_code,
                    resp.reason_phrase,
                    json.dumps(payload),
                    json.dumps(error_body) if isinstance(error_body, dict) else error_body,
                )
            resp.raise_for_status()
            return resp.json()

    async def upload_media(self, image_bytes: bytes, mimetype: str) -> str:
        """Upload image bytes to Meta Media API and return the media_id."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._media_url,
                headers={"Authorization": f"Bearer {self.access_token}"},
                files={"file": ("image", image_bytes, mimetype)},
                data={"messaging_product": "whatsapp", "type": mimetype},
            )
            if not resp.is_success:
                try:
                    error_body = resp.json()
                except Exception:
                    error_body = resp.text
                logger.error(
                    "[Meta API] Media upload failed %s %s — response: %s",
                    resp.status_code,
                    resp.reason_phrase,
                    json.dumps(error_body) if isinstance(error_body, dict) else error_body,
                )
            resp.raise_for_status()
            return resp.json()["id"]

    async def send_image_bytes(self, to: str, image_bytes: bytes, mimetype: str = "image/jpeg", caption: str | None = None) -> dict:
        """Upload image to Meta and send via media_id (required — Meta rejects data: URIs)."""
        media_id = await self.upload_media(image_bytes, mimetype)
        payload: dict = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {"id": media_id},
        }
        if caption:
            payload["image"]["caption"] = caption
        return await self._post(payload)

    async def send_image_base64(self, to: str, base64_data: str, mimetype: str = "image/jpeg", caption: str | None = None) -> dict:
        image_bytes = base64.b64decode(base64_data)
        return await self.send_image_bytes(to, image_bytes, mimetype, caption)

    async def send_image(self, to: str, image_url: str, caption: str | None = None) -> dict:
        payload: dict = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {"link": image_url},
        }
        if caption:
            payload["image"]["caption"] = caption
        return await self._post(payload)

    async def send_audio(self, to: str, audio_url: str) -> dict:
        return await self._post({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "audio",
            "audio": {"link": audio_url},
        })

    async def send_template(self, to: str, template_name: str, components: list | None = None, language_code: str = "pt_BR") -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            }
        }
        if components:
            payload["template"]["components"] = components
        return await self._post(payload)

    async def mark_read(self, message_id: str, remote_jid: str = "") -> dict:
        return await self._post({
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        })
```

- [ ] **Step 2: Rodar os testes — devem passar agora**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/backend"
python -m pytest tests/test_meta_media_upload.py -v
```

Esperado: todos os 5 testes passando (`PASSED`).

- [ ] **Step 3: Commit**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra"
git add backend/app/whatsapp/meta.py backend/tests/test_meta_media_upload.py
git commit -m "fix(meta): implementar Media Upload API para envio de imagens

Meta Cloud API rejeita data: URIs no campo link.
Novo fluxo: upload multipart → media_id → send com {id: media_id}.
send_image_base64 refatorado para decodificar e delegar."
```

---

## Task 4: Melhorar logging de erros em tools.py

**Contexto:** Os blocos `except` em `enviar_fotos` e `enviar_foto_produto` usam `logger.warning` sem `exc_info=True`, escondendo o traceback completo e dificultando o diagnóstico.

**Files:**
- Modify: `backend/app/agent/tools.py:229-233` e `backend/app/agent/tools.py:261-265`

- [ ] **Step 1: Corrigir except em enviar_fotos (linha ~232)**

Localizar o bloco:
```python
            except Exception as e:
                logger.warning(f"Failed to send photo {photo.name}: {e}")
```

Substituir por:
```python
            except Exception as e:
                logger.error(
                    "Failed to send photo %s to %s: %s",
                    photo.name, phone, e, exc_info=True,
                )
```

- [ ] **Step 2: Corrigir except em enviar_foto_produto (linha ~264)**

Localizar o bloco:
```python
        except Exception as e:
            logger.warning(f"Failed to send product photo {produto}: {e}")
            return f"erro ao enviar foto de {produto}"
```

Substituir por:
```python
        except Exception as e:
            logger.error(
                "Failed to send product photo '%s' to %s: %s",
                produto, phone, e, exc_info=True,
            )
            return f"erro ao enviar foto de {produto}"
```

- [ ] **Step 3: Commit**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra"
git add backend/app/agent/tools.py
git commit -m "fix(tools): melhorar logging de erros em enviar_fotos com exc_info"
```

---

## Task 5: Smoke test manual

**Contexto:** Verificar que o fluxo completo funciona — fotos no disco, tool executa, Meta API recebe o upload.

- [ ] **Step 1: Confirmar que as pastas de fotos estão corretas**

```bash
ls -lh "/home/Kelwin/Kelwin - Maquinadevendascanastra/backend/app/photos/atacado/"
ls -lh "/home/Kelwin/Kelwin - Maquinadevendascanastra/backend/app/photos/private_label/"
```

Esperado: atacado tem 5 arquivos (foto_1–5), private_label tem 4 (foto_1–4).

- [ ] **Step 2: Rodar a suite completa de testes**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/backend"
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Esperado: todos os testes passando, sem regressões.

- [ ] **Step 3: Verificar que o JSON e script foram deletados**

```bash
ls "/home/Kelwin/Kelwin - Maquinadevendascanastra/Valéria Fotos (2).json" 2>&1
ls "/home/Kelwin/Kelwin - Maquinadevendascanastra/backend/scripts/extract_photos_n8n.py" 2>&1
```

Esperado: `No such file or directory` para ambos.

- [ ] **Step 4: Avisar usuário para teste no dev**

Comunicar ao usuário que o branch `fix/enviar-fotos-meta-upload` está pronto para teste no ambiente dev. Aguardar autorização para push.

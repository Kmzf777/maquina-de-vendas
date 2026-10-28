# Mídia do cliente permanente + rotação de 6 meses — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Foto, vídeo, documento e figurinha do cliente ganham cópia no Storage na chegada; um job diário apaga mídia de mensagem com mais de 180 dias (estreia em dry-run); a bolha do CRM mostra "Arquivo expirado".

**Spec:** `docs/superpowers/specs/2026-10-27-midia-cliente-permanente-design.md`

**Architecture:** (1) `_resolve_media` em `backend/app/buffer/processor.py` baixa a mídia não-áudio pela Meta e sobe para `whatsapp-media/inbound/<media_id>.<ext>` (fail-soft). (2) Módulo novo `backend/app/media_retention/` parte das **mensagens** (não do bucket): só apaga objeto que é `media_url` de mensagem com mais de 180 dias, num prefixo permitido, e que nenhuma mensagem mais nova usa; marca `metadata.media_expired=true`. Arquivo sem mensagem nunca é apagado. (3) `message-bubble.tsx` mostra "Arquivo expirado" quando `media_expired`, quando é media_id legado da Meta com mais de 7 dias, ou quando a mídia dá erro ao carregar.

**Tech Stack:** Python 3.12 + supabase-py + pytest (backend); Next.js + vitest + testing-library (frontend).

**Decisões técnicas (não mudam o resultado da spec):**
- "Referenciado fora de `messages`" foi resolvido assim: o job só considera objetos que são `media_url` de mensagem. Em 27/10 a varredura de todas as colunas texto/json do schema public achou URL de Storage só em `meta_webhook_logs.payload` (log bruto). `whatsapp-media/valeria-botoes/` fica bloqueado por prefixo (essas URLs aparecem em mensagens, mas são reusadas pelo fluxo).
- Media_id legado com mais de 7 dias é tratado como expirado na tela (medido: 23-24/10 abrem, ≤19/10 dão 400).
- Tabela de log com `unique(bucket, path)` e upsert: o dry-run diário não duplica linhas.

---

## Task 1: Cópia da mídia do cliente na chegada (backend)

**Files:**
- Modify: `backend/app/buffer/processor.py` (helpers perto de `_upload_audio_to_storage` ~linha 2518; loops de image/video/document/sticker em `_resolve_media` ~linhas 2620-2660)
- Test (create): `backend/tests/test_midia_inbound_storage_2026_10_27.py`

- [ ] **Step 1: Teste que falha**

```python
"""Cartão da1f51a7: mídia não-áudio do cliente ganha cópia em whatsapp-media/inbound/."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.buffer import processor as p


def _provider(data=b"\x89PNGfake", ctype="image/jpeg", exc=None):
    prov = MagicMock()
    if exc:
        prov.download_media = AsyncMock(side_effect=exc)
    else:
        prov.download_media = AsyncMock(return_value=(data, ctype))
    return prov


def _sb(public="https://supabase.x/storage/v1/object/public/whatsapp-media/inbound/123.jpg"):
    sb = MagicMock()
    bucket = sb.storage.from_.return_value
    bucket.get_public_url.return_value = public
    return sb, bucket


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,placeholder,ctype,ext", [
    ("image", "[image: media_url=123]", "image/jpeg", "jpg"),
    ("video", "[video: media_url=123]", "video/mp4", "mp4"),
    ("document", "[document: media_url=123]", "application/pdf", "pdf"),
    ("sticker", "[sticker: media_url=123]", "image/webp", "webp"),
])
async def test_copia_para_inbound(kind, placeholder, ctype, ext):
    sb, bucket = _sb()
    with patch("app.db.supabase.get_supabase", return_value=sb), \
         patch("app.buffer.processor.asyncio.sleep", new=AsyncMock()):
        _, url, mtype, _, _ = await p._resolve_media(placeholder, _provider(ctype=ctype))
    assert mtype == kind
    assert url.startswith("https://")
    path = bucket.upload.call_args.args[0]
    assert path == f"inbound/123.{ext}"


@pytest.mark.asyncio
async def test_falha_no_download_mantem_media_id():
    with patch("app.buffer.processor.asyncio.sleep", new=AsyncMock()):
        _, url, mtype, _, _ = await p._resolve_media(
            "[image: media_url=999]", _provider(exc=RuntimeError("400"))
        )
    assert mtype == "image" and url == "999"


@pytest.mark.asyncio
async def test_falha_no_upload_mantem_media_id():
    sb, bucket = _sb()
    bucket.upload.side_effect = RuntimeError("storage down")
    with patch("app.db.supabase.get_supabase", return_value=sb):
        _, url, _, _, _ = await p._resolve_media("[image: media_url=777]", _provider())
    assert url == "777"


@pytest.mark.asyncio
async def test_acima_do_teto_nao_copia():
    sb, bucket = _sb()
    grande = b"x" * (p._INBOUND_MAX_MEDIA + 1)
    with patch("app.db.supabase.get_supabase", return_value=sb):
        _, url, _, _, _ = await p._resolve_media("[image: media_url=555]", _provider(data=grande))
    assert url == "555"
    bucket.upload.assert_not_called()


@pytest.mark.asyncio
async def test_url_http_nao_baixa_de_novo():
    prov = _provider()
    _, url, _, _, _ = await p._resolve_media("[image: media_url=https://x/y.jpg]", prov)
    assert url == "https://x/y.jpg"
    prov.download_media.assert_not_called()
```

- [ ] **Step 2: Rodar e ver falhar** — `cd backend && python -m pytest tests/test_midia_inbound_storage_2026_10_27.py -q` → FAIL (upload não é chamado / `_INBOUND_MAX_MEDIA` não existe).

- [ ] **Step 3: Implementar.** Ao lado de `_upload_audio_to_storage`:

```python
# Cartão da1f51a7 (27/10/2026): foto/vídeo/documento/figurinha do cliente ficavam só como
# media_id da Meta, que some em ~5-7 dias (medido: 23-24/10 abriam, ≤19/10 davam 400).
# Cópia em whatsapp-media/inbound/ — mesmo bucket público que a bolha já carrega.
_INBOUND_MAX_MEDIA = 16 * 1024 * 1024       # teto da Meta p/ imagem/vídeo/figurinha
_INBOUND_MAX_DOCUMENT = 100 * 1024 * 1024   # teto da Meta p/ documento
_INBOUND_EXT = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif",
    "video/mp4": "mp4", "video/3gpp": "3gp", "application/pdf": "pdf",
}
_INBOUND_EXT_PADRAO = {"image": "jpg", "video": "mp4", "sticker": "webp", "document": "bin"}


def _inbound_ext(content_type: str | None, kind: str) -> str:
    base = (content_type or "").split(";")[0].strip().lower()
    if base in _INBOUND_EXT:
        return _INBOUND_EXT[base]
    import mimetypes
    guessed = mimetypes.guess_extension(base) if base else None
    return guessed.lstrip(".") if guessed else _INBOUND_EXT_PADRAO.get(kind, "bin")


async def _copy_inbound_media(provider, media_ref: str, kind: str) -> str | None:
    """Baixa a mídia do cliente na Meta e sobe para whatsapp-media/inbound/. Fail-soft:
    None em qualquer erro ou acima do teto — o chamador mantém o media_id (como antes)."""
    if not media_ref or media_ref.startswith("http") or provider is None \
            or not hasattr(provider, "download_media"):
        return None
    try:
        data, content_type = await _download_media_with_retry(provider, media_ref)
    except Exception as e:  # noqa: BLE001
        logger.warning("[MEDIA-INBOUND] download falhou p/ %s (%s): %s", media_ref, kind, e)
        return None
    teto = _INBOUND_MAX_DOCUMENT if kind == "document" else _INBOUND_MAX_MEDIA
    if not isinstance(data, (bytes, bytearray)) or len(data) > teto:
        logger.warning("[MEDIA-INBOUND] %s (%s) fora do teto/sem bytes — mantém media_id", media_ref, kind)
        return None
    try:
        from app.db.supabase import get_supabase
        sb = get_supabase()
        path = f"inbound/{media_ref}.{_inbound_ext(content_type, kind)}"
        sb.storage.from_("whatsapp-media").upload(
            path, bytes(data),
            file_options={"content-type": content_type or "application/octet-stream", "x-upsert": "true"},
        )
        return sb.storage.from_("whatsapp-media").get_public_url(path)
    except Exception as e:  # noqa: BLE001
        logger.warning("[MEDIA-INBOUND] upload falhou p/ %s (%s): %s", media_ref, kind, e)
        return None
```

Nos 4 loops de `_resolve_media` (image, video, document, sticker), dentro do `if message_type is None:` logo depois de `storage_url = media_ref`, acrescentar (com o `kind` certo de cada loop):

```python
                copied = await _copy_inbound_media(provider, media_ref, "image")
                if copied:
                    storage_url = copied
```

Atualizar a docstring de `_resolve_media`: "Image/video/document/sticker: media_id extracted only, no download." → "Image/video/document/sticker: copiados para whatsapp-media/inbound/ (fail-soft: fica o media_id)."

- [ ] **Step 4: Rodar e ver passar** o arquivo novo, e depois a suíte do backend inteira: `python -m pytest -q -x -p no:cacheprovider` (anotar contagem; comparar com a contagem antes da mudança, rodando `git stash`-free: compare com a mesma suíte na master se algo falhar).
- [ ] **Step 5: Commit** — `feat(midia-cliente): copia foto/video/documento/figurinha do cliente para o Storage`

## Task 2: Rotação de 180 dias (backend + migração)

**Files:**
- Create: `backend/app/media_retention/__init__.py` (vazio), `backend/app/media_retention/service.py`
- Create: `supabase/migrations/20261027_da1f_media_retention_log.sql`
- Modify: `backend/app/worker/main.py` (tick + linha em `TASK_SPECS`)
- Test (create): `backend/tests/test_media_retention_2026_10_27.py`

- [ ] **Step 1: Migração** `supabase/migrations/20261027_da1f_media_retention_log.sql`:

```sql
-- Cartão da1f51a7 — spec docs/superpowers/specs/2026-10-27-midia-cliente-permanente-design.md.
-- Registro da rotação de mídia (backend/app/media_retention). Uma linha por objeto do Storage;
-- o dry-run diário faz upsert na mesma linha (unique bucket+path), sem duplicar.
-- Só cria tabela. Reexecutar é seguro. Depois: SIGUSR1 no PostgREST.
-- ROLLBACK: drop table if exists public.media_retention_log;
create table if not exists public.media_retention_log (
  id bigserial primary key,
  bucket text not null,
  path text not null,
  size_bytes bigint,
  message_count int not null default 0,
  dry_run boolean not null,
  registrado_em timestamptz not null default now(),
  apagado_em timestamptz,
  unique (bucket, path)
);
alter table public.media_retention_log enable row level security;
grant select, insert, update on public.media_retention_log to service_role;
grant usage, select on sequence public.media_retention_log_id_seq to service_role;
```

- [ ] **Step 2: Teste que falha** `backend/tests/test_media_retention_2026_10_27.py`. Fake do supabase em memória:

```python
"""Cartão da1f51a7: rotação de mídia — só mensagem velha, só prefixo permitido, dry-run por padrão."""
from datetime import datetime, timedelta, timezone

import pytest

from app.media_retention import service as s

NOW = datetime(2026, 12, 1, tzinfo=timezone.utc)
BASE = "https://supabase.x/storage/v1/object/public/"


def msg(i, dias, url, md=None):
    return {"id": f"m{i}", "media_url": url, "metadata": md,
            "created_at": (NOW - timedelta(days=dias)).isoformat()}


class FakeSB:
    """Implementa só o que service.py usa — a interface está em service._Store."""
    def __init__(self, msgs):
        self.msgs = msgs
        self.removed: list[tuple[str, list[str]]] = []
        self.updated: dict[str, dict] = {}
        self.logs: list[dict] = []
        self.fail_remove = False


@pytest.fixture
def store_factory(monkeypatch):
    def make(msgs):
        fake = FakeSB(msgs)

        class Store(s._Store):
            def __init__(self):
                pass

            def candidatas(self, cutoff, after, limit):
                rows = [m for m in fake.msgs
                        if m["created_at"] < cutoff and (after is None or m["created_at"] > after)
                        and "/storage/v1/object/public/" in (m["media_url"] or "")
                        and not ((m["metadata"] or {}).get("media_expired"))]
                return sorted(rows, key=lambda m: m["created_at"])[:limit]

            def urls_em_uso_recente(self, urls, cutoff):
                return {m["media_url"] for m in fake.msgs
                        if m["media_url"] in urls and m["created_at"] >= cutoff}

            def tamanho(self, url):
                return 1000

            def remover(self, bucket, paths):
                if fake.fail_remove:
                    raise RuntimeError("storage down")
                fake.removed.append((bucket, list(paths)))

            def marcar_expirada(self, row):
                md = dict(row["metadata"] or {})
                md["media_expired"] = True
                row["metadata"] = md
                fake.updated[row["id"]] = md

            def registrar(self, linhas):
                fake.logs.extend(linhas)

        return Store(), fake
    return make


def test_parse_storage_url():
    assert s.parse_storage_url(BASE + "whatsapp-media/outbound/1_a%20b.pdf") == ("whatsapp-media", "outbound/1_a b.pdf")
    assert s.parse_storage_url(BASE + "audio/123.ogg") == ("audio", "123.ogg")
    assert s.parse_storage_url("12345") is None


def test_prefixos_permitidos():
    assert s.is_allowed("audio", "123.ogg")
    assert s.is_allowed("whatsapp-media", "inbound/1.jpg")
    assert s.is_allowed("whatsapp-media", "outbound/1.jpg")
    assert not s.is_allowed("whatsapp-media", "valeria-botoes/cafe.png")
    assert not s.is_allowed("outro", "inbound/1.jpg")


def test_dry_run_e_padrao(monkeypatch):
    monkeypatch.delenv("MEDIA_RETENTION_DRY_RUN", raising=False)
    assert s.dry_run_enabled() is True
    monkeypatch.setenv("MEDIA_RETENTION_DRY_RUN", "false")
    assert s.dry_run_enabled() is False


def test_dias_configuravel(monkeypatch):
    monkeypatch.delenv("MEDIA_RETENTION_DAYS", raising=False)
    assert s.retention_days() == 180
    monkeypatch.setenv("MEDIA_RETENTION_DAYS", "90")
    assert s.retention_days() == 90


def test_apaga_so_o_velho_e_permitido(store_factory):
    store, fake = store_factory([
        msg(1, 200, BASE + "whatsapp-media/inbound/a.jpg"),
        msg(2, 200, BASE + "audio/b.ogg"),
        msg(3, 100, BASE + "whatsapp-media/inbound/novo.jpg"),          # novo demais
        msg(4, 200, BASE + "whatsapp-media/valeria-botoes/cafe.png"),   # protegido
        msg(5, 200, "1234567890"),                                       # media_id da Meta
    ])
    r = s.run_retention(store=store, now=NOW, dry_run=False, days=180, batch=500)
    removidos = {(b, p) for b, ps in fake.removed for p in ps}
    assert removidos == {("whatsapp-media", "inbound/a.jpg"), ("audio", "b.ogg")}
    assert set(fake.updated) == {"m1", "m2"}
    assert r["deleted"] == 2 and r["skipped"] == 1 and r["bytes"] == 2000
    assert all(l["dry_run"] is False and l["apagado_em"] for l in fake.logs)


def test_pula_url_usada_por_mensagem_recente(store_factory):
    url = BASE + "whatsapp-media/outbound/foto.jpg"
    store, fake = store_factory([msg(1, 200, url), msg(2, 10, url)])
    r = s.run_retention(store=store, now=NOW, dry_run=False, days=180, batch=500)
    assert fake.removed == [] and r["skipped"] == 1


def test_dry_run_nao_apaga_nem_marca(store_factory):
    store, fake = store_factory([msg(1, 200, BASE + "audio/b.ogg")])
    r = s.run_retention(store=store, now=NOW, dry_run=True, days=180, batch=500)
    assert fake.removed == [] and fake.updated == {}
    assert r["candidates"] == 1 and r["deleted"] == 0
    assert fake.logs[0]["dry_run"] is True and fake.logs[0]["apagado_em"] is None


def test_falha_no_remove_nao_marca(store_factory):
    store, fake = store_factory([msg(1, 200, BASE + "audio/b.ogg")])
    fake.fail_remove = True
    r = s.run_retention(store=store, now=NOW, dry_run=False, days=180, batch=500)
    assert fake.updated == {} and r["errors"] == 1


def test_lotes(store_factory):
    store, fake = store_factory([msg(i, 200 + i, BASE + f"audio/{i}.ogg") for i in range(7)])
    r = s.run_retention(store=store, now=NOW, dry_run=False, days=180, batch=3)
    assert r["deleted"] == 7
    assert all(len(ps) <= 3 for _, ps in fake.removed)


def test_mesma_url_em_duas_mensagens_velhas(store_factory):
    url = BASE + "audio/x.ogg"
    store, fake = store_factory([msg(1, 200, url), msg(2, 190, url)])
    r = s.run_retention(store=store, now=NOW, dry_run=False, days=180, batch=500)
    assert r["deleted"] == 1 and set(fake.updated) == {"m1", "m2"}
```

- [ ] **Step 3: Rodar e ver falhar** — `python -m pytest tests/test_media_retention_2026_10_27.py -q` → FAIL (módulo não existe).

- [ ] **Step 4: Implementar** `backend/app/media_retention/service.py`:

```python
"""Rotação de mídia do Storage (cartão da1f51a7, spec 2026-10-27-midia-cliente-permanente).

Parte das MENSAGENS, não do bucket: só apaga o objeto que é `media_url` de mensagem com mais
de MEDIA_RETENTION_DAYS (padrão 180), num prefixo permitido, e que nenhuma mensagem mais nova
usa. Arquivo sem mensagem nunca é apagado. Estreia em dry-run (MEDIA_RETENTION_DRY_RUN padrão
true): só registra em public.media_retention_log o que apagaria.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

logger = logging.getLogger(__name__)

_MARCA = "/storage/v1/object/public/"
_PERMITIDOS = {"audio": ("",), "whatsapp-media": ("inbound/", "outbound/")}
_MAX_LOTES_POR_RODADA = 40


def retention_days() -> int:
    try:
        return max(1, int(os.getenv("MEDIA_RETENTION_DAYS") or 180))
    except ValueError:
        return 180


def dry_run_enabled() -> bool:
    return (os.getenv("MEDIA_RETENTION_DRY_RUN") or "true").strip().lower() not in ("0", "false", "no", "off")


def parse_storage_url(url: str | None) -> tuple[str, str] | None:
    if not url or _MARCA not in url:
        return None
    resto = url.split(_MARCA, 1)[1].split("?", 1)[0]
    bucket, _, path = resto.partition("/")
    return (bucket, unquote(path)) if bucket and path else None


def is_allowed(bucket: str, path: str) -> bool:
    prefixos = _PERMITIDOS.get(bucket)
    return bool(prefixos) and any(path.startswith(p) for p in prefixos)


class _Store:
    """Acesso a banco e Storage. Os testes trocam por um fake em memória."""

    def __init__(self, sb=None):
        if sb is None:
            from app.db.supabase import get_supabase
            sb = get_supabase()
        self.sb = sb

    def candidatas(self, cutoff: str, after: str | None, limit: int) -> list[dict]:
        q = (self.sb.table("messages").select("id,media_url,metadata,created_at")
             .lt("created_at", cutoff).like("media_url", f"%{_MARCA}%")
             .is_("metadata->media_expired", "null"))
        if after:
            q = q.gt("created_at", after)
        return q.order("created_at").limit(limit).execute().data or []

    def urls_em_uso_recente(self, urls: list[str], cutoff: str) -> set[str]:
        if not urls:
            return set()
        rows = (self.sb.table("messages").select("media_url")
                .in_("media_url", urls).gte("created_at", cutoff).execute().data or [])
        return {r["media_url"] for r in rows}

    def tamanho(self, url: str) -> int | None:
        try:
            import httpx
            r = httpx.head(url, timeout=10.0)
            return int(r.headers["content-length"]) if r.status_code == 200 else None
        except Exception:  # noqa: BLE001
            return None

    def remover(self, bucket: str, paths: list[str]) -> None:
        self.sb.storage.from_(bucket).remove(paths)

    def marcar_expirada(self, row: dict) -> None:
        md = dict(row.get("metadata") or {})
        md["media_expired"] = True
        self.sb.table("messages").update({"metadata": md}).eq("id", row["id"]).execute()

    def registrar(self, linhas: list[dict]) -> None:
        if linhas:
            self.sb.table("media_retention_log").upsert(linhas, on_conflict="bucket,path").execute()


def run_retention(store: _Store | None = None, now: datetime | None = None,
                  dry_run: bool | None = None, days: int | None = None, batch: int = 500) -> dict:
    store = store or _Store()
    now = now or datetime.now(timezone.utc)
    dry_run = dry_run_enabled() if dry_run is None else dry_run
    days = days or retention_days()
    cutoff = (now - timedelta(days=days)).isoformat()
    r = {"dry_run": dry_run, "days": days, "candidates": 0, "deleted": 0,
         "skipped": 0, "errors": 0, "bytes": 0}
    after: str | None = None

    for _ in range(_MAX_LOTES_POR_RODADA):
        rows = store.candidatas(cutoff, after, batch)
        if not rows:
            break
        after = rows[-1]["created_at"]

        por_url: dict[str, list[dict]] = {}
        for row in rows:
            por_url.setdefault(row["media_url"], []).append(row)
        em_uso = store.urls_em_uso_recente(list(por_url), cutoff)

        alvos: dict[tuple[str, str], tuple[str, list[dict]]] = {}
        for url, msgs in por_url.items():
            alvo = parse_storage_url(url)
            if not alvo or not is_allowed(*alvo) or url in em_uso:
                r["skipped"] += 1
                continue
            alvos[alvo] = (url, msgs)

        por_bucket: dict[str, list[str]] = {}
        for bucket, path in alvos:
            por_bucket.setdefault(bucket, []).append(path)

        agora = datetime.now(timezone.utc).isoformat()
        linhas: list[dict] = []
        for bucket, paths in por_bucket.items():
            if not dry_run:
                try:
                    store.remover(bucket, paths)
                except Exception as e:  # noqa: BLE001
                    logger.error("[media-retention] remove falhou em %s (%d arquivos): %s", bucket, len(paths), e)
                    r["errors"] += 1
                    continue
            for path in paths:
                url, msgs = alvos[(bucket, path)]
                tamanho = store.tamanho(url) if dry_run else None
                if not dry_run:
                    for m in msgs:
                        store.marcar_expirada(m)
                    r["deleted"] += 1
                r["candidates"] += 1
                r["bytes"] += tamanho or 0
                linhas.append({"bucket": bucket, "path": path, "size_bytes": tamanho,
                               "message_count": len(msgs), "dry_run": dry_run,
                               "apagado_em": None if dry_run else agora})
        store.registrar(linhas)
        if len(rows) < batch:
            break

    logger.info("[media-retention] %s", r)
    return r
```

**Atenção ao tamanho:** o teste `test_apaga_so_o_velho_e_permitido` espera `bytes == 2000` com `dry_run=False`. Então meça o tamanho ANTES de apagar, nos dois modos: troque `tamanho = store.tamanho(url) if dry_run else None` por medir para todo path antes do `remover` (guarde num dict `tamanhos[(bucket, path)]`) e use esse valor na linha do log e no `r["bytes"]`. O código final precisa passar todos os testes do Step 2.

Em `backend/app/worker/main.py`:

```python
async def _media_retention_tick() -> None:
    from app.media_retention.service import run_retention
    await asyncio.to_thread(run_retention)
```

e em `TASK_SPECS`, depois de `bling-sync`:

```python
    # Rotação de mídia do Storage (cartão da1f51a7): 1x/dia, estreia em dry-run.
    ("media-retention", "periodic", _media_retention_tick, 86400),
```

- [ ] **Step 5: Rodar e ver passar** o teste novo, mais `tests/test_worker*` se existir (`ls tests | grep -i worker`), e a suíte inteira.
- [ ] **Step 6: Commit** — `feat(midia-cliente): rotacao diaria de midia com mais de 180 dias, em dry-run por padrao`

## Task 3: "Arquivo expirado" na bolha (frontend)

**Files:**
- Create: `frontend/src/lib/media-expired.ts`, `frontend/src/lib/media-expired.test.ts`
- Modify: `frontend/src/components/conversas/message-bubble.tsx`
- Modify (testes): `frontend/src/components/conversas/message-bubble.test.tsx`

- [ ] **Step 1: Teste que falha** `frontend/src/lib/media-expired.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { isMediaExpired } from "./media-expired";

const NOW = new Date("2026-10-27T12:00:00Z");
const dias = (n: number) => new Date(NOW.getTime() - n * 86400000).toISOString();

describe("isMediaExpired", () => {
  it("metadata.media_expired = true → expirado", () => {
    expect(isMediaExpired({ media_url: "https://x/a.jpg", metadata: { media_expired: true }, created_at: dias(1) }, NOW)).toBe(true);
  });
  it("media_id legado da Meta com mais de 7 dias → expirado", () => {
    expect(isMediaExpired({ media_url: "2302234720561889", created_at: dias(8) }, NOW)).toBe(true);
  });
  it("media_id recente → não expirado", () => {
    expect(isMediaExpired({ media_url: "2302234720561889", created_at: dias(2) }, NOW)).toBe(false);
  });
  it("URL do Storage antiga sem marca → não expirado", () => {
    expect(isMediaExpired({ media_url: "https://x/a.jpg", created_at: dias(300) }, NOW)).toBe(false);
  });
  it("blob: e sem media_url → não expirado", () => {
    expect(isMediaExpired({ media_url: "blob:abc", created_at: dias(30) }, NOW)).toBe(false);
    expect(isMediaExpired({ media_url: null, created_at: dias(30) }, NOW)).toBe(false);
  });
});
```

E em `message-bubble.test.tsx`, um `describe("MessageBubble — arquivo expirado")` novo (reusar `renderBubble`/`makeMessage` do arquivo):
- imagem com `metadata: { media_expired: true }` e `media_url` https → `screen.getByText("Arquivo expirado")` e nenhum `img`.
- documento com `media_url: "2302234720561889"` e `created_at` de 30 dias atrás → "Arquivo expirado" e sem link "Baixar".
- imagem https que dispara `fireEvent.error(img)` → "Arquivo expirado".
- imagem https normal recente → `img` presente, sem "Arquivo expirado".
- áudio com `media_expired` → "Arquivo expirado" e sem `<audio>`.

- [ ] **Step 2: Rodar e ver falhar** — `cd frontend && npx vitest run src/lib/media-expired.test.ts src/components/conversas/message-bubble.test.tsx`. (No worktree, se não houver `node_modules`, rodar `npm ci` antes.)

- [ ] **Step 3: Implementar** `frontend/src/lib/media-expired.ts`:

```ts
// Cartão da1f51a7 (27/10/2026). Mídia que não volta mais:
// - `metadata.media_expired`: apagada pela rotação de 180 dias (backend/app/media_retention);
// - media_id legado da Meta (sem cópia no Storage) com mais de 7 dias — a Meta apaga em
//   ~5-7 dias (medido em 27/10: 23-24/10 abriam, ≤19/10 davam 400).
export const META_MEDIA_TTL_DAYS = 7;

type MediaLike = {
  media_url?: string | null;
  metadata?: unknown;
  created_at?: string | null;
};

export function isMediaExpired(m: MediaLike, now: Date = new Date()): boolean {
  const md = m.metadata as { media_expired?: unknown } | null | undefined;
  if (md && md.media_expired === true) return true;
  const url = m.media_url;
  if (!url || url.startsWith("http") || url.startsWith("blob:")) return false;
  if (!m.created_at) return false;
  const idadeMs = now.getTime() - new Date(m.created_at).getTime();
  return idadeMs > META_MEDIA_TTL_DAYS * 86400000;
}
```

Em `message-bubble.tsx`:
1. `import { isMediaExpired } from "@/lib/media-expired";`
2. Componente pequeno no arquivo (perto de `ReplyGlyph`):

```tsx
/** Mídia que não volta mais: rotação de 180 dias, media_id vencido na Meta ou erro ao carregar. */
function ExpiredMedia() {
  return (
    <div className="flex items-center gap-2 py-1" title="O arquivo não está mais disponível">
      <svg className="w-4 h-4 opacity-60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="9" strokeWidth={2} />
        <path strokeLinecap="round" strokeWidth={2} d="M12 7v5l3 2" />
      </svg>
      <span className="text-[13px] opacity-60">Arquivo expirado</span>
    </div>
  );
}
```

3. Estado `const [audioError, setAudioError] = useState(false);` junto de `imgError`/`videoError`, e `const mediaExpired = isMediaExpired(message);` logo depois do cálculo de `mediaSrc`.
4. Nos ramos:
   - áudio: `mediaSrc ? (mediaExpired || audioError ? <ExpiredMedia /> : <audio ... onError={() => setAudioError(true)} />) : (placeholder atual)`
   - vídeo: `videoError` e `mediaExpired` → `<ExpiredMedia />` (substitui o bloco "Vídeo" do erro).
   - imagem: `imgError` e `mediaExpired` → `<ExpiredMedia />` (substitui o bloco "Imagem" do erro).
   - figurinha: `mediaExpired` → `<ExpiredMedia />`; `<img>` ganha `onError={() => setImgError(true)}` e com `imgError` mostra `<ExpiredMedia />`.
   - documento: mantém o nome do arquivo; se `mediaExpired`, no lugar do link "Baixar" mostra `<span className="text-[11px] opacity-60 mt-0.5">Arquivo expirado</span>`.
   - Os placeholders de quando NÃO há `mediaSrc` ficam como estão.
5. Testes existentes que esperavam o texto "Imagem"/"Vídeo" depois de erro de carga: atualizar para "Arquivo expirado" (é o comportamento novo pedido pela spec), sem mexer em outros.

- [ ] **Step 4: Rodar e ver passar** os dois arquivos, depois `npx vitest run` inteiro e `npx tsc --noEmit -p .`.
- [ ] **Step 5: Commit** — `feat(midia-cliente): bolha mostra "Arquivo expirado" no lugar da midia que nao volta`

## Task 4: Verificação em modo teste (controlador, sem subagente)

- [ ] Suítes: backend `python -m pytest -q` e frontend `npx vitest run` verdes; comparar falhas com a master se houver.
- [ ] Cópia real controlada: script local que chama `_copy_inbound_media` com um provider Meta real sobre uma mídia de cliente dos últimos 2 dias (media_id lido do banco por SELECT) e confere que a URL `.../whatsapp-media/inbound/...` abre com 200 e `content-type` de imagem/PDF. Efeito: um arquivo novo em `inbound/` (é o que o código fará em produção). Nenhuma mensagem é enviada.
- [ ] Dry-run da rotação contra produção, só leitura: `_Store` com `registrar` e `remover` desligados (subclasse), imprimir o resumo. Esperado hoje: ~0 candidatas (arquivo mais antigo é de maio/2026 → 180 dias só em novembro).
- [ ] Print da tela de Conversas rodando o frontend do worktree localmente (`npm run dev`), numa conversa com mídia antiga de cliente → "Arquivo expirado", e uma com mídia normal.

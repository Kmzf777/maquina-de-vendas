"""Rotação de mídia do Storage (cartão da1f51a7, spec 2026-10-27-midia-cliente-permanente).

Parte das MENSAGENS, não do bucket: só apaga o objeto que é `media_url` de mensagem com mais
de MEDIA_RETENTION_DAYS (padrão 180), num prefixo permitido, e que nenhuma mensagem mais nova
usa. Arquivo sem mensagem nunca é apagado. Estreia em dry-run (MEDIA_RETENTION_DRY_RUN padrão
true; só "0/false/no/off" desliga): só registra em public.media_retention_log o que apagaria.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

logger = logging.getLogger(__name__)

_MARCA = "/storage/v1/object/public/"
# bucket -> prefixos de path que podem ser apagados. Qualquer outro bucket/prefixo
# (ex.: whatsapp-media/valeria-botoes/, reusado pelo fluxo de botões) nunca é tocado.
_PERMITIDOS = {"audio": ("",), "whatsapp-media": ("inbound/", "outbound/")}
_MAX_LOTES_POR_RODADA = 40
_URLS_POR_CONSULTA = 40


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
    resto = url.split(_MARCA, 1)[1].split("?", 1)[0].split("#", 1)[0]
    bucket, _, path = resto.partition("/")
    return (bucket, unquote(path)) if bucket and path else None


def is_allowed(bucket: str, path: str) -> bool:
    prefixos = _PERMITIDOS.get(bucket)
    if not prefixos or not path or "\\" in path:
        return False
    partes = path.split("/")
    # Sem "..", "." nem segmento vazio: o path tem que ser literalmente o objeto do prefixo.
    if any(p in ("", ".", "..") for p in partes):
        return False
    return any(path.startswith(p) for p in prefixos)


def _padroes_like(origin: str | None) -> list[str]:
    """Padrões LIKE (wildcard `*` do PostgREST) dos prefixos permitidos no host do projeto.

    Sem origin (só em teste), aceita qualquer host; a checagem em Python continua valendo.
    """
    base = (origin.rstrip("/") if origin else "*") + _MARCA
    return [f"{base}{bucket}/{prefixo}*" for bucket, prefixos in _PERMITIDOS.items()
            for prefixo in prefixos]


def _filtro_or(origin: str | None) -> str:
    # Valor entre aspas duplas: a URL tem ',', '.', ':' (reservados na sintaxe do or= do PostgREST).
    return ",".join(f'media_url.like."{p}"' for p in _padroes_like(origin))


class _Store:
    """Acesso a banco e Storage. Os testes trocam por um fake em memória."""

    # Base do projeto Supabase (SUPABASE_URL). Com ela, URL de outro host é pulada.
    origin: str | None = None

    def __init__(self, sb=None):
        if sb is None:
            from app.config import settings
            from app.db.supabase import get_supabase
            sb = get_supabase()
            self.origin = (settings.supabase_url or "").rstrip("/") or None
        self.sb = sb

    def candidatas(self, cutoff: str, after: str | None, limit: int) -> list[dict]:
        # Filtra no banco só o que pode ser apagado: o que sempre seria pulado (valeria-botoes/,
        # host antigo) não volta na consulta e não trava a rotação atrás dele.
        q = (self.sb.table("messages").select("id,media_url,metadata,created_at")
             .lt("created_at", cutoff).or_(_filtro_or(self.origin))
             .is_("metadata->media_expired", "null"))
        if after:
            q = q.gt("created_at", after)
        return q.order("created_at").limit(limit).execute().data or []

    def urls_em_uso_recente(self, urls: list[str], cutoff: str) -> set[str]:
        # Em pedaços: 500 URLs num único in.() passariam do limite de tamanho da query string.
        achadas: set[str] = set()
        for i in range(0, len(urls), _URLS_POR_CONSULTA):
            rows = (self.sb.table("messages").select("media_url")
                    .in_("media_url", urls[i:i + _URLS_POR_CONSULTA])
                    .gte("created_at", cutoff).execute().data or [])
            achadas.update(r["media_url"] for r in rows)
        return achadas

    def tamanho(self, url: str) -> int | None:
        try:
            import httpx
            r = httpx.head(url, timeout=10.0, follow_redirects=True)
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


def _mesmo_projeto(url: str, origin: str | None) -> bool:
    return not origin or url.startswith(origin.rstrip("/") + _MARCA)


def run_retention(store: _Store | None = None, now: datetime | None = None,
                  dry_run: bool | None = None, days: int | None = None, batch: int = 500) -> dict:
    store = store or _Store()
    now = now or datetime.now(timezone.utc)
    dry_run = dry_run_enabled() if dry_run is None else bool(dry_run)
    days = days or retention_days()
    cutoff = (now - timedelta(days=days)).isoformat()
    origin = getattr(store, "origin", None)
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
            if row.get("media_url"):
                por_url.setdefault(row["media_url"], []).append(row)
        em_uso = store.urls_em_uso_recente(list(por_url), cutoff)

        alvos: dict[tuple[str, str], tuple[str, list[dict]]] = {}
        for url, msgs in por_url.items():
            alvo = parse_storage_url(url)
            if (not alvo or not is_allowed(*alvo) or not _mesmo_projeto(url, origin)
                    or url in em_uso):
                r["skipped"] += 1
                continue
            if alvo in alvos:  # mesma (bucket, path) por URLs diferentes (ex.: ?query)
                alvos[alvo][1].extend(msgs)
                continue
            alvos[alvo] = (url, msgs)

        por_bucket: dict[str, list[str]] = {}
        for bucket, path in alvos:
            por_bucket.setdefault(bucket, []).append(path)

        linhas: list[dict] = []
        for bucket, paths in por_bucket.items():
            # Mede ANTES de apagar (depois do remove o HEAD não acha mais o arquivo).
            tamanhos = {p: store.tamanho(alvos[(bucket, p)][0]) for p in paths}
            if not dry_run:
                # Rede de segurança: nunca manda ao remove nada fora do permitido.
                if not all(is_allowed(bucket, p) for p in paths):
                    logger.error("[media-retention] path fora do permitido em %s; lote ignorado", bucket)
                    r["errors"] += 1
                    continue
                try:
                    store.remover(bucket, paths)
                except Exception as e:  # noqa: BLE001
                    logger.error("[media-retention] remove falhou em %s (%d arquivos): %s",
                                 bucket, len(paths), e)
                    r["errors"] += 1
                    continue
            agora = None if dry_run else datetime.now(timezone.utc).isoformat()
            for path in paths:
                _url, msgs = alvos[(bucket, path)]
                if not dry_run:
                    for m in msgs:
                        try:
                            store.marcar_expirada(m)
                        except Exception as e:  # noqa: BLE001
                            logger.error("[media-retention] marcar %s falhou: %s", m.get("id"), e)
                            r["errors"] += 1
                    r["deleted"] += 1
                r["candidates"] += 1
                r["bytes"] += tamanhos[path] or 0
                linhas.append({"bucket": bucket, "path": path, "size_bytes": tamanhos[path],
                               "message_count": len(msgs), "dry_run": dry_run,
                               "apagado_em": agora})
        try:
            store.registrar(linhas)
        except Exception as e:  # noqa: BLE001
            logger.error("[media-retention] registrar log falhou (%d linhas): %s", len(linhas), e)
            r["errors"] += 1
        if len(rows) < batch:
            break

    logger.info("[media-retention] %s", r)
    return r

"""Orquestração da sincronização diária dos públicos PL/Atacado (cartão 4e0494e0).

Lock no Redis, segmento, enriquecimento pelo Bling e envio por público, cada um no seu `try`:
uma plataforma que cai não para as outras. Toda rodada grava uma linha por público em
`audience_sync_runs`, com sucesso ou erro.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.audiences import bling_details, diff, google, meta, segment
from app.audiences.types import AUDIENCES, Audience, Pessoa

logger = logging.getLogger(__name__)

TZ = ZoneInfo("America/Sao_Paulo")
LOCK_KEY = "audience_sync:lock"
LOCK_TTL = 3600
_ERRO_MAX = 1000


def enabled() -> bool:
    return (os.getenv("AUDIENCE_SYNC_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redis_default():
    import redis.asyncio as aioredis

    from app.config import settings
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def _do_segmento(pessoas: list[Pessoa], seg: str) -> list[Pessoa]:
    return [p for p in pessoas if (p.pl if seg == "pl" else p.atacado)]


async def _meta(aud: Audience, pessoas: list[Pessoa], dry_run: bool, meta_mod) -> dict[str, Any]:
    if dry_run:
        resp = await asyncio.to_thread(meta_mod.check_audience, aud.audience_id)
        return {"linhas_enviadas": len(meta_mod.build_rows(pessoas)), "removidos": 0,
                "api_response": resp}
    resp = await asyncio.to_thread(meta_mod.replace, aud.audience_id, pessoas)
    return {"linhas_enviadas": resp.get("linhas"), "removidos": 0, "api_response": resp}


async def _google(aud: Audience, pessoas: list[Pessoa], dry_run: bool, store, google_mod) -> dict[str, Any]:
    atuais: dict[str, tuple[dict, str]] = {}
    for p in pessoas:
        for ident in google_mod.identificadores(p):
            atuais[diff.ident_hash(ident)] = (ident, p.lead_id)
    ativos = await asyncio.to_thread(store.membros_ativos, aud.key)
    _, saem = diff.diff_identificadores(set(ativos), set(atuais))

    membros = [google_mod.build_member(p) for p in pessoas]
    resp_ingest: list = []
    if pessoas:
        resp_ingest = await asyncio.to_thread(google_mod.ingest, aud.audience_id, membros,
                                              validate_only=dry_run)
    resp_remove: list = []
    if saem:
        resp_remove = await asyncio.to_thread(
            google_mod.remove, aud.audience_id,
            [google_mod.remove_member(ativos[h]) for h in sorted(saem)], validate_only=dry_run)

    if not dry_run:
        quando = _agora_iso()
        if atuais:
            rows = [{"ident_hash": h, "ident": ident, "lead_id": lead_id, "ultimo_envio": quando}
                    for h, (ident, lead_id) in atuais.items()]
            await asyncio.to_thread(store.upsert_membros, aud.key, rows)
        if saem:
            await asyncio.to_thread(store.marcar_removidos, aud.key, sorted(saem), quando)
    return {"linhas_enviadas": len(membros) if pessoas else 0, "removidos": len(saem),
            "api_response": {"ingest": resp_ingest, "remove": resp_remove}}


async def run(*, trigger: str, dry_run: bool, store=None, redis=None, agora: datetime | None = None,
              meta_mod=meta, google_mod=google, bling=bling_details.atualizar_detalhes) -> dict:
    run_id = str(uuid.uuid4())
    proprio_redis = redis is None
    if redis is None:
        redis = _redis_default()
    try:
        if not await redis.set(LOCK_KEY, run_id, nx=True, ex=LOCK_TTL):
            logger.info("audiences: outra rodada em andamento (lock), pulando")
            return {"status": "lock"}
        try:
            return await _executar(run_id, trigger=trigger, dry_run=dry_run, store=store,
                                   agora=agora, meta_mod=meta_mod, google_mod=google_mod, bling=bling)
        finally:
            try:
                if await redis.get(LOCK_KEY) == run_id:
                    await redis.delete(LOCK_KEY)
            except Exception:  # noqa: BLE001 — o TTL libera de qualquer jeito
                logger.warning("audiences: falha ao liberar o lock", exc_info=True)
    finally:
        if proprio_redis:
            await (getattr(redis, "aclose", None) or redis.close)()


async def _executar(run_id: str, *, trigger, dry_run, store, agora, meta_mod, google_mod, bling) -> dict:
    if store is None:
        from app.audiences.source import Store
        store = await asyncio.to_thread(Store)
    agora = agora or datetime.now(timezone.utc)

    fatos = [f for f in await asyncio.to_thread(store.fatos) if segment.dentro_da_janela(f, agora)]
    contagem = {"total": len(fatos), "pl": 0, "atacado": 0, "dois": 0, "fora": 0, "cnpj_sem_classe": 0}
    selecionados = []
    for f in fatos:
        pl, at = segment.classificar(f)
        contagem["pl"] += pl
        contagem["atacado"] += at
        contagem["dois"] += pl and at
        if not pl and not at:
            contagem["fora"] += 1
            continue
        if at and not (pl or f.pipeline_atacado or f.tag_atacado or f.segmento == "atacado"):
            contagem["cnpj_sem_classe"] += 1
        selecionados.append(f)

    chaves = [c for f in selecionados for c in f.contatos_bling]
    detalhes = await bling(chaves, store, agora=agora)
    pessoas = [p for p in (segment.montar_pessoa(f, detalhes) for f in selecionados) if p]

    por_publico: dict[str, dict] = {}
    for aud in AUDIENCES:
        iniciado = _agora_iso()
        seg = _do_segmento(pessoas, aud.segment)
        info: dict[str, Any] = {"pessoas": len(seg),
                                "com_celular": sum(1 for p in seg if p.celulares),
                                "com_email": sum(1 for p in seg if p.emails),
                                "linhas_enviadas": None, "removidos": None,
                                "api_response": None, "erro": None}
        try:
            if aud.platform == "meta":
                info.update(await _meta(aud, seg, dry_run, meta_mod))
            else:
                info.update(await _google(aud, seg, dry_run, store, google_mod))
        except Exception as exc:  # noqa: BLE001 — uma plataforma não para as outras
            logger.warning("audiences: falha em %s: %s", aud.key, exc)
            info["erro"] = (str(exc) or type(exc).__name__)[:_ERRO_MAX]
        row = {"run_id": run_id, "trigger": trigger, "dry_run": dry_run, "audience_key": aud.key,
               "platform": aud.platform, "audience_id": aud.audience_id, **info,
               "iniciado_em": iniciado, "terminado_em": _agora_iso()}
        try:
            await asyncio.to_thread(store.registrar_run, row)
        except Exception:  # noqa: BLE001 — o registro não derruba a rodada
            logger.warning("audiences: falha ao registrar run de %s", aud.key, exc_info=True)
        por_publico[aud.key] = {k: info[k] for k in
                                ("pessoas", "com_celular", "com_email", "linhas_enviadas",
                                 "removidos", "erro")}

    resumo = {"run_id": run_id, "trigger": trigger, "dry_run": dry_run,
              "contagem": contagem, "por_publico": por_publico}
    logger.info("audiences: rodada %s concluída: %s", run_id, resumo)
    return resumo


async def tick(*, agora: datetime | None = None, store=None, runner=run) -> None:
    if not enabled():
        return
    agora_sp = (agora or datetime.now(timezone.utc)).astimezone(TZ)
    if agora_sp.hour < 1:
        return
    inicio = agora_sp.replace(hour=1, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    if store is None:
        from app.audiences.source import Store
        store = await asyncio.to_thread(Store)
    if await asyncio.to_thread(store.rodada_automatica_desde, inicio.isoformat()):
        return
    await runner(trigger="automatica", dry_run=False, store=store)

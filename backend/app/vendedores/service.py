"""Leitura do cadastro único `public.vendedores` (contrato da Onda 0, cartão b67f1c6b).

`resolver_vendedor` espelha `fn_vendedor_id` do banco: aceita uuid, e-mail ou
nome/apelido (sem acento, minúsculo, espaços colapsados; também o 1º token do nome).
0 ou mais de 1 vendedor casando -> None, nunca um palpite."""
from __future__ import annotations

import logging
import re
import time
import unicodedata

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_TTL_S = 60.0
_cache: dict = {"linhas": None, "em": 0.0}


def _carregar() -> list[dict]:
    """select * from vendedores. Erro -> [] (loga)."""
    try:
        return list(get_supabase().table("vendedores").select("*").execute().data or [])
    except Exception as exc:
        logger.error("vendedores: falha ao carregar o cadastro: %s", exc)
        return []


def _linhas() -> list[dict]:
    agora = time.monotonic()
    if _cache["linhas"] is not None and agora - _cache["em"] < _TTL_S:
        return _cache["linhas"]
    linhas = _carregar()
    if linhas:  # erro/vazio não fica 60 s em cache
        _cache["linhas"], _cache["em"] = linhas, agora
    return linhas


def limpar_cache() -> None:
    _cache["linhas"], _cache["em"] = None, 0.0


def _norm(v: str | None) -> str:
    if not v:
        return ""
    s = "".join(c for c in unicodedata.normalize("NFKD", v) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def listar(ativos: bool | None = None) -> list[dict]:
    linhas = _linhas()
    if ativos is None:
        return list(linhas)
    return [r for r in linhas if bool(r.get("ativo")) is ativos]


def por_id(vendedor_id: str | None) -> dict | None:
    if not vendedor_id:
        return None
    return next((r for r in _linhas() if r.get("id") == vendedor_id), None)


def _chaves(r: dict) -> set[str]:
    nome = _norm(r.get("nome"))
    chaves = {nome, *(_norm(a) for a in (r.get("apelidos") or []))}
    if nome:
        chaves.add(nome.split(" ")[0])
    chaves.discard("")
    return chaves


def resolver_vendedor(chave: str | None) -> str | None:
    """uuid | e-mail | nome/apelido -> id. Ambíguo ou nada -> None."""
    bruto = (chave or "").strip()
    if not bruto:
        return None
    linhas = _linhas()
    alvo_email = bruto.lower()
    alvo_nome = _norm(bruto)
    ids = {r["id"] for r in linhas if r.get("id") == bruto}
    if not ids:
        ids = {r["id"] for r in linhas if (r.get("email") or "").lower() == alvo_email}
    if not ids:
        ids = {r["id"] for r in linhas if alvo_nome in _chaves(r)}
    return next(iter(ids)) if len(ids) == 1 else None


def vendedor_do_segmento(segmento: str | None) -> dict | None:
    """1º vendedor ATIVO com `segmento` em `segmentos`; consumo/None -> None."""
    if not segmento or segmento == "consumo":
        return None
    return next((r for r in _linhas()
                 if r.get("ativo") and segmento in (r.get("segmentos") or [])), None)

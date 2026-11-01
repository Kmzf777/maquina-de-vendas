"""Acesso ao Supabase da sincronização de públicos (cartão 4e0494e0).

Todo o banco passa por `Store`; os testes trocam o `sb` (ou a classe inteira) por um fake.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.audiences.types import Detalhe, Fatos
from app.db.paginacao import paginar

_PEDACO = 200  # IDs por in.(): mais que isso passa do limite de tamanho da query string
_UPSERT_LOTE = 500


def _ts(v: Any) -> datetime:
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


class Store:
    def __init__(self, sb=None):
        if sb is None:
            from app.db.supabase import get_supabase
            sb = get_supabase()
        self.sb = sb

    # ---- fatos ----
    def fatos(self) -> list[Fatos]:
        data = self.sb.rpc("audience_sync_facts").execute().data
        if isinstance(data, (str, bytes)):
            data = json.loads(data)
        return [Fatos.from_row(r) for r in (data or [])]

    # ---- detalhes do Bling ----
    def detalhes(self, chaves: list[tuple[str, int]]) -> dict[tuple[str, int], tuple[Detalhe, datetime]]:
        por_conta: dict[str, list[int]] = {}
        for conta, cid in dict.fromkeys(chaves):
            por_conta.setdefault(conta, []).append(int(cid))
        out: dict[tuple[str, int], tuple[Detalhe, datetime]] = {}
        for conta, ids in por_conta.items():
            for i in range(0, len(ids), _PEDACO):
                rows = (self.sb.table("audience_contact_details")
                        .select("account,bling_contact_id,email,municipio,uf,cep,buscado_em")
                        .eq("account", conta).in_("bling_contact_id", ids[i:i + _PEDACO])
                        .execute().data or [])
                for r in rows:
                    d = Detalhe(email=r.get("email"), municipio=r.get("municipio"),
                                uf=r.get("uf"), cep=r.get("cep"))
                    out[(r["account"], int(r["bling_contact_id"]))] = (d, _ts(r["buscado_em"]))
        return out

    def salvar_detalhes(self, rows: list[dict]) -> None:
        for i in range(0, len(rows), _UPSERT_LOTE):
            (self.sb.table("audience_contact_details")
             .upsert(rows[i:i + _UPSERT_LOTE], on_conflict="account,bling_contact_id").execute())

    # ---- membros (Google) ----
    def membros_ativos(self, audience_key: str) -> dict[str, dict]:
        rows = paginar(lambda: (self.sb.table("audience_sync_members").select("ident_hash,ident")
                                .eq("audience_key", audience_key).is_("removido_em", "null")
                                .order("ident_hash")))
        out: dict[str, dict] = {}
        for r in rows:
            ident = r["ident"]
            out[r["ident_hash"]] = json.loads(ident) if isinstance(ident, str) else ident
        return out

    def upsert_membros(self, audience_key: str, rows: list[dict]) -> None:
        # `primeiro_envio` fica de fora: o default do banco vale na 1ª vez e o upsert não o toca.
        linhas = [{"audience_key": audience_key, "ident_hash": r["ident_hash"], "ident": r["ident"],
                   "lead_id": r.get("lead_id"), "ultimo_envio": r["ultimo_envio"],
                   "removido_em": None} for r in rows]
        for i in range(0, len(linhas), _UPSERT_LOTE):
            (self.sb.table("audience_sync_members")
             .upsert(linhas[i:i + _UPSERT_LOTE], on_conflict="audience_key,ident_hash").execute())

    def marcar_removidos(self, audience_key: str, hashes, quando_iso: str) -> None:
        hs = list(hashes)
        for i in range(0, len(hs), _PEDACO):
            (self.sb.table("audience_sync_members").update({"removido_em": quando_iso})
             .eq("audience_key", audience_key).in_("ident_hash", hs[i:i + _PEDACO]).execute())

    # ---- runs ----
    def registrar_run(self, row: dict) -> None:
        self.sb.table("audience_sync_runs").insert(row).execute()

    def rodada_automatica_desde(self, inicio_iso: str) -> bool:
        rows = (self.sb.table("audience_sync_runs").select("id")
                .eq("trigger", "automatica").eq("dry_run", False).gte("iniciado_em", inicio_iso)
                .limit(1).execute().data or [])
        return bool(rows)

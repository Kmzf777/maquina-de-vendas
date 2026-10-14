"""Backfill one-off: marca como Google Ads os leads antigos do botão WhatsApp do anúncio Google.

Quem clica no botão "Iniciar conversa" do anúncio Google chega com o texto pronto
"Olá, encontrei vocês pelo Google e gostaria de obter mais informações." — sem gclid nem UTM.
O carimbo automático (app.leads.google_message_asset) só vale para leads novos; este script
corrige os antigos: lead cuja PRIMEIRA mensagem do cliente é esse texto e que não tem nenhuma
atribuição (gclid, fbclid, ctwa_clid, meta_ad_id, utm_*) recebe utm_source=google,
utm_medium=cpc, utm_campaign="WhatsApp do Google" e traffic_type=paid.

Modos (rodar a partir de backend/):
  python -m scripts.backfill_google_message_asset
      DRY-RUN (padrão): lista quantos leads seriam marcados e até 10 exemplos. Nada é gravado.
  python -m scripts.backfill_google_message_asset --apply [--out-dir DIR]
      Grava os 4 campos (só onde utm_source ainda é nulo) e salva em DIR um JSON
      backfill_google_message_asset_<UTC>.json com os ids alterados (para reverter).
  python -m scripts.backfill_google_message_asset --revert ARQUIVO.json
      Desfaz: zera utm_source/utm_medium/utm_campaign/traffic_type dos ids do JSON que ainda estão google/cpc.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.leads.google_message_asset import (
    GOOGLE_ASSET_TRACKING,
    google_message_asset_tracking,
    has_attribution,
)

_PAGE_SIZE = 1000
_PATTERN = "%encontrei voc%pelo google%"
_LEAD_FIELDS = "id, phone, name, gclid, fbclid, ctwa_clid, meta_ad_id, utm_source, utm_medium, utm_campaign"


def _matching_lead_ids(sb) -> list[str]:
    ids: set[str] = set()
    start = 0
    while True:
        rows = (
            sb.table("messages")
            .select("lead_id")
            .eq("role", "user")
            .ilike("content", _PATTERN)
            .order("id")  # páginas estáveis entre chamadas
            .range(start, start + _PAGE_SIZE - 1)
            .execute()
            .data
            or []
        )
        ids.update(r["lead_id"] for r in rows if r.get("lead_id"))
        if len(rows) < _PAGE_SIZE:
            break
        start += _PAGE_SIZE
    return sorted(ids)


def find_candidates(sb) -> list[dict[str, Any]]:
    """Leads sem atribuição cuja 1a mensagem do cliente é o texto do botão Google."""
    candidates: list[dict[str, Any]] = []
    for lead_id in _matching_lead_ids(sb):
        first = (
            sb.table("messages")
            .select("content")
            .eq("lead_id", lead_id)
            .eq("role", "user")
            .order("created_at")
            .limit(1)
            .execute()
            .data
            or []
        )
        if not first or not google_message_asset_tracking(first[0].get("content")):
            continue
        rows = sb.table("leads").select(_LEAD_FIELDS).eq("id", lead_id).limit(1).execute().data or []
        if not rows or has_attribution(rows[0]):
            continue
        lead = rows[0]
        candidates.append({"id": lead["id"], "phone": lead.get("phone"), "name": lead.get("name")})
    return candidates


def apply(sb, candidates: list[dict[str, Any]], out_dir: Path) -> Path:
    """Grava o carimbo; o JSON lista SÓ os ids cujo update retornou linha (realmente gravados)."""
    payload = {**GOOGLE_ASSET_TRACKING, "traffic_type": "paid"}
    ids: list[str] = []
    for c in candidates:
        res = sb.table("leads").update(payload).eq("id", c["id"]).is_("utm_source", "null").execute()
        if res.data:
            ids.append(c["id"])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = out_dir / f"backfill_google_message_asset_{stamp}.json"
    path.write_text(json.dumps({"lead_ids": ids}, indent=2), encoding="utf-8")
    return path


def revert(sb, path: Path) -> int:
    ids = json.loads(Path(path).read_text(encoding="utf-8")).get("lead_ids") or []
    count = 0
    for lead_id in ids:
        res = (
            sb.table("leads")
            .update({"utm_source": None, "utm_medium": None, "utm_campaign": None, "traffic_type": None})
            .eq("id", lead_id)
            .eq("utm_source", "google")
            .eq("utm_medium", "cpc")
            .execute()
        )
        count += len(res.data or [])
    return count


def _mask_phone(phone: str | None) -> str:
    digits = str(phone or "")
    return ("*" * max(len(digits) - 4, 0)) + digits[-4:]


def main(argv: list[str] | None = None, sb=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="grava as alterações")
    mode.add_argument("--revert", metavar="PATH", help="desfaz um --apply a partir do JSON gerado")
    parser.add_argument("--out-dir", default=".", help="pasta do JSON de ids (--apply)")
    args = parser.parse_args(argv)

    if sb is None:
        from app.db.supabase import get_supabase

        sb = get_supabase()

    if args.revert:
        count = revert(sb, Path(args.revert))
        print(f"Revertidos: {count} leads")
        return

    candidates = find_candidates(sb)
    print(f"Candidatos: {len(candidates)} leads (botao WhatsApp Google, sem atribuicao)")
    if not args.apply:
        for c in candidates[:10]:
            print(f"  {c['id']}  {c.get('name') or '-'}  {_mask_phone(c.get('phone'))}")
        print("DRY-RUN: nada gravado")
        return

    path = apply(sb, candidates, Path(args.out_dir))
    gravados = len(json.loads(path.read_text(encoding="utf-8"))["lead_ids"])
    print(f"Aplicado em {gravados} leads (de {len(candidates)} candidatos). Ids salvos em: {path}")


if __name__ == "__main__":
    main()

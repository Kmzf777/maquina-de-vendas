"""Propõe o valor estimado por segmento x etapa para `ad_conversion_values`.

valor = receita das vendas em até 30 dias dos leads com clique que atingiram a etapa
        ÷ número desses leads (janela de 180 dias).

Só imprime a proposta. Grava SÓ com --aplicar, depois de aprovada: mudar valor reinicia o
aprendizado das campanhas.

Uso (de dentro do container da API, em /app):
    python -m scripts.conversoes.calcular_valores
    python -m scripts.conversoes.calcular_valores --aplicar --por "Rafael"
"""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

JANELA_VENDA = timedelta(days=30)
HISTORICO = timedelta(days=180)
N_MINIMO = 20


def propor_valores(marcos: list[dict[str, Any]], vendas: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """marcos: [{lead_id, segment, stage, at}]; vendas: [{lead_id, sold_at, value, kit}]."""
    por_lead = defaultdict(list)
    for v in vendas:
        por_lead[v["lead_id"]].append(v)
    cel: dict[tuple[str, str], dict[str, Any]] = {}
    grupos = defaultdict(list)
    for m in marcos:
        grupos[(m["segment"], m["stage"])].append(m)
    for chave, ms in grupos.items():
        kit = nao_kit = 0.0
        for m in ms:
            for v in por_lead.get(m["lead_id"], []):
                if m["at"] <= v["sold_at"] <= m["at"] + JANELA_VENDA:
                    if v["kit"]:
                        kit += float(v["value"] or 0)
                    else:
                        nao_kit += float(v["value"] or 0)
        n = len(ms)
        cel[chave] = {
            "n": n,
            "valor": round((kit + nao_kit) / n, 2) if n else 0.0,
            "receita_kit": round(kit, 2),
            "receita_nao_kit": round(nao_kit, 2),
            "pouco_dado": n < N_MINIMO,
        }
    return cel


def _carregar(sb, agora: datetime) -> tuple[list[dict], list[dict]]:
    """Marcos com as MESMAS regras da varredura (clique, repasse válido, já era cliente), mas
    sem a janela de envio — aqui é histórico de 180 dias."""
    from app.conversions.eligibility import (
        clicks_from_entradas, clicks_from_lead_fallback, parse_ts, qualified_handoff_ok,
        segment_for, stage_allowed,
    )
    desde = (agora - HISTORICO).isoformat()
    entradas: list[dict] = []
    i = 0
    while True:
        page = sb.table("lead_events").select("lead_id,occurred_at,metadata").eq("event_type", "entrada") \
            .gte("occurred_at", desde).range(i, i + 999).execute().data or []
        entradas += page
        if len(page) < 1000:
            break
        i += 1000
    ids = sorted({e["lead_id"] for e in entradas if e.get("lead_id")})
    marcos: list[dict] = []
    vendas: list[dict] = []
    for j in range(0, len(ids), 200):
        bloco = ids[j:j + 200]
        leads = sb.table("leads").select("id,stage,ja_era_cliente,metadata,created_at,ctwa_clid,gclid,gbraid,wbraid") \
            .in_("id", bloco).execute().data or []
        sales = sb.table("sales").select("id,lead_id,sold_at,value,status").in_("lead_id", bloco) \
            .gte("sold_at", desde).execute().data or []
        sale_ids = [s["id"] for s in sales]
        itens = sb.table("sale_items").select("sale_id,descricao").in_("sale_id", sale_ids).execute().data or [] \
            if sale_ids else []
        kits = {it["sale_id"] for it in itens if "kit degust" in (it.get("descricao") or "").lower()}
        for s in sales:
            at = parse_ts(s.get("sold_at"))
            if s.get("status") != "cancelada" and at:
                vendas.append({"lead_id": s["lead_id"], "sold_at": at, "value": s.get("value"), "kit": s["id"] in kits})
        for lead in leads:
            seg = segment_for(lead.get("stage"))
            ja = lead.get("ja_era_cliente")
            clicks = clicks_from_entradas([e for e in entradas if e["lead_id"] == lead["id"]])
            clicks += clicks_from_lead_fallback(lead, clicks)
            if clicks and stage_allowed("lead", ja):
                primeiro = min(c.click_at for c in clicks)
                marcos.append({"lead_id": lead["id"], "segment": seg, "stage": "lead", "at": primeiro})
            h = (lead.get("metadata") or {}).get("handoff")
            if clicks and qualified_handoff_ok(h) and stage_allowed("qualified", ja):
                marcos.append({"lead_id": lead["id"], "segment": seg, "stage": "qualified", "at": parse_ts(h["at"])})
    return marcos, vendas


def main() -> None:
    from app.db.supabase import get_supabase
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--por", default="script")
    args = ap.parse_args()
    sb = get_supabase()
    marcos, vendas = _carregar(sb, datetime.now(timezone.utc))
    prop = propor_valores(marcos, vendas)
    print(f"{'segmento':<15}{'etapa':<12}{'N':>6}{'valor R$':>12}{'kit R$':>12}{'não-kit R$':>14}  aviso")
    for (seg, st), c in sorted(prop.items()):
        aviso = "N<20: considere usar o valor de 'geral'" if c["pouco_dado"] else ""
        print(f"{seg:<15}{st:<12}{c['n']:>6}{c['valor']:>12.2f}{c['receita_kit']:>12.2f}{c['receita_nao_kit']:>14.2f}  {aviso}")
    if args.aplicar:
        rows = [{"segment": s, "stage": st, "value": c["valor"], "updated_by": args.por,
                 "updated_at": datetime.now(timezone.utc).isoformat()} for (s, st), c in prop.items()]
        sb.table("ad_conversion_values").upsert(rows, on_conflict="segment,stage").execute()
        print(f"gravado: {len(rows)} linhas")


if __name__ == "__main__":
    main()

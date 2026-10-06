"""Atribuição manual de campanha no /trafego (spec 2026-10-06, P2.2–P2.4).

O webhook do CTWA só passou a gravar o anúncio (meta_ad_id) em 21/08/2026, e há lead que chega
por caminho que o rastreio não vê. Um admin diz à mão de qual campanha o lead veio; o relatório
(traffic_report.manual_attribution) dá prioridade a essa resposta sobre anúncio e UTMs.

Contrato (migração 20261006_call_semanal_base.sql, P0): leads.campanha_manual_canal
('meta'|'google'), campanha_manual_id, campanha_manual_nome, campanha_manual_por (e-mail),
campanha_manual_em; lead_events tipo 'atribuicao_manual', source 'crm'.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.campaigns.traffic_report import _TZ, _fetch_all, _s
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

CANAIS = ("meta", "google")
JANELA_CAMPANHAS_DIAS = 120


class AtribuicaoInvalida(ValueError):
    """O corpo não descreve uma atribuição válida (vira 422)."""


class LeadNaoEncontrado(LookupError):
    """lead_id inexistente (vira 404)."""


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def campanhas_com_gasto(hoje: date | None = None) -> list[dict[str, Any]]:
    """Campanhas com gasto (ad_spend) nos últimos 120 dias, para o select do painel.

    Uma linha por (canal, campaign_id), nome mais recente (campanha renomeada), ordenadas por
    canal (Meta antes de Google) e investimento decrescente. Gasto zero fica de fora."""
    sb = get_supabase()
    hoje = hoje or datetime.now(_TZ).date()
    desde = (hoje - timedelta(days=JANELA_CAMPANHAS_DIAS)).isoformat()
    linhas = _fetch_all(lambda: sb.table("ad_spend")
                        .select("platform, campaign_id, campaign_name, cost, date")
                        .gte("date", desde))
    agregado: dict[tuple[str, str], dict[str, Any]] = {}
    for r in linhas:
        canal = _s(r.get("platform")).lower()
        cid = str(r.get("campaign_id") or "").strip()
        nome = _s(r.get("campaign_name"))
        if canal not in CANAIS or not cid or not nome:
            continue
        slot = agregado.setdefault((canal, cid), {"canal": canal, "campanha_id": cid,
                                                  "campanha_nome": nome, "investimento": 0.0,
                                                  "_dia": ""})
        try:
            slot["investimento"] += float(r.get("cost") or 0.0)
        except (TypeError, ValueError):
            pass
        dia = str(r.get("date") or "")
        if dia >= slot["_dia"]:
            slot["_dia"], slot["campanha_nome"] = dia, nome
    out: list[dict[str, Any]] = []
    for c in agregado.values():
        c.pop("_dia")
        c["investimento"] = round(c["investimento"], 2)
        if c["investimento"] > 0:
            out.append(c)
    out.sort(key=lambda c: (CANAIS.index(c["canal"]), -c["investimento"], c["campanha_nome"].lower()))
    return out


def _rotulo(canal: Any, cid: Any) -> str | None:
    canal, cid = _s(canal), _s(cid)
    return f"{canal}:{cid}" if canal and cid else None


def atribuir_campanha(lead_id: str, *, canal: str | None = None, campanha_id: str | None = None,
                      campanha_nome: str | None = None, remover: bool = False,
                      por: str | None = None) -> dict[str, Any]:
    """Grava (ou remove) a atribuição manual do lead e registra o evento na linha do tempo."""
    if not remover:
        canal = _s(canal).lower()
        campanha_id = _s(campanha_id)
        if canal not in CANAIS:
            raise AtribuicaoInvalida("canal deve ser 'meta' ou 'google'")
        if not campanha_id:
            raise AtribuicaoInvalida("campanha_id é obrigatório")
        campanha_nome = _s(campanha_nome) or campanha_id
    sb = get_supabase()
    achados = (sb.table("leads")
               .select("id, campanha_manual_canal, campanha_manual_id, campanha_manual_nome")
               .eq("id", lead_id).limit(1).execute().data or [])
    if not achados:
        raise LeadNaoEncontrado(lead_id)
    antes = achados[0]
    em = _agora().isoformat()
    por = _s(por) or None
    if remover:
        patch: dict[str, Any] = {"campanha_manual_canal": None, "campanha_manual_id": None,
                                 "campanha_manual_nome": None}
    else:
        patch = {"campanha_manual_canal": canal, "campanha_manual_id": campanha_id,
                 "campanha_manual_nome": campanha_nome}
    # por/em também na remoção: fica o rastro de quem desfez.
    patch.update({"campanha_manual_por": por, "campanha_manual_em": em})
    sb.table("leads").update(patch).eq("id", lead_id).execute()
    _registrar_evento(sb, lead_id, antes, patch, remover, por, em)
    return {"lead_id": lead_id, "atribuicao_manual": not remover, **patch}


def _registrar_evento(sb, lead_id: str, antes: dict[str, Any], patch: dict[str, Any],
                      remover: bool, por: str | None, em: str) -> None:
    """lead_events `atribuicao_manual` (a linha do tempo do P3 lê daqui).

    Fail-soft: a atribuição já foi gravada e é ela que o relatório usa; perder o evento só
    empobrece a linha do tempo, então loga e segue em vez de devolver erro ao admin."""
    evento = {
        "lead_id": lead_id,
        "event_type": "atribuicao_manual",
        "old_value": _rotulo(antes.get("campanha_manual_canal"), antes.get("campanha_manual_id")),
        "new_value": _rotulo(patch["campanha_manual_canal"], patch["campanha_manual_id"]),
        "metadata": {
            "canal": patch["campanha_manual_canal"],
            "campanha_id": patch["campanha_manual_id"],
            "campanha_nome": patch["campanha_manual_nome"],
            "remover": remover,
            "por": por,
            "anterior": {"canal": antes.get("campanha_manual_canal"),
                         "campanha_id": antes.get("campanha_manual_id"),
                         "campanha_nome": antes.get("campanha_manual_nome")},
        },
        "source": "crm",
        "occurred_at": em,
    }
    try:
        sb.table("lead_events").insert(evento).execute()
    except Exception as exc:
        logger.error("atribuicao_manual: evento do lead %s não gravado: %s", lead_id, exc)

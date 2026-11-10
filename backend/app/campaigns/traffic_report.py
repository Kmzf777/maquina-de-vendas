"""Relatório de campanhas (/trafego): agrega leads por canal+campanha cruzando com vendas.

Funções puras (derive_channel, build_campaign_report) isoladas do I/O p/ teste.
As funções que tocam o banco (traffic_report, campaign_leads) são fail-soft.
"""
import logging
import re
import time as _time
import unicodedata
from statistics import median
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.db.supabase import get_supabase
from app.leads.segmento import SEGMENTOS_B2B, normalizar_segmento
from app.utils.receita_venda import frete_da_venda, receita_da_venda, venda_cancelada

# Fuso de negócio: o dia do relatório é o dia de Brasília, do começo ao fim. A janela
# (_resolve_window), o gráfico (_local_day) e o recorte do gasto por data usam ESTE relógio —
# antes a janela era resolvida em UTC e só o gráfico era local, então a tabela virava o dia às
# 21h e o gráfico à meia-noite: 09/09/2026 saía com 30 leads na tabela e 27 no gráfico logo
# abaixo. Bate exatamente com a conta do Google Ads (America/Sao_Paulo); a conta do Meta fecha
# em America/Noronha e fica 1h adiantada — resíduo conhecido, era de 3h.
_TZ = ZoneInfo("America/Sao_Paulo")

# Tokens ignorados ao comparar utm_campaign com campaign_name do Google Ads.
# Extensões de anúncio (sitelink) são sufixos de variante, não identificam campanha.
_UTM_STOP_WORDS = frozenset({"sitelink"})


def _normalize_tokens(s: str) -> frozenset[str]:
    """Tokens significativos de uma string: sem acentos, sem números, sem separadores."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower()
    s = re.sub(r"[|.\-\s_/]+", " ", s)
    return frozenset(
        t for t in s.split()
        if t and not re.match(r"^\d+$", t) and t not in _UTM_STOP_WORDS
    )


def _campaign_tokens(name: str) -> frozenset[str]:
    return _normalize_tokens(name)


def resolve_campaign_id(utm_campaign: str, utm_medium: str,
                        campaigns: dict[str, dict[str, Any]]) -> str | None:
    """Resolve um slug de utm_campaign para o campaign_id da plataforma. None = não resolvido.

    `campaigns` é {campaign_id: {"name": str, "tokens": frozenset, "cost": float}}.

    Regras, da mais forte para a mais fraca — e SEM chute:
      1. nome idêntico (normalizado) → vence direto;
      2. todos os tokens do slug cabem no nome da campanha (ou vice-versa). Um só candidato → vence;
      3. vários candidatos → o utm_medium desempata (medium=pmax casa "PMAX | Atacado", e é o que
         separa a Search da PMAX quando as duas se chamam "atacado");
      4. ainda empatado → vence o nome com MENOS tokens sobrando (match mais específico), e só
         se esse mínimo for único.
    Nada disso batendo, devolve None: o lead cai na linha "(não atribuído)". Preferimos uma
    linha honesta a espalhar investimento na campanha errada."""
    slug = (utm_campaign or "").strip().lower()
    if not slug or not campaigns:
        return None
    for cid, c in campaigns.items():
        if c["name"].strip().lower() == slug:
            return cid
    utm_tokens = _normalize_tokens(slug)
    if not utm_tokens:
        return None
    candidates = [
        cid for cid, c in campaigns.items()
        if c["tokens"] and (utm_tokens <= c["tokens"] or c["tokens"] <= utm_tokens)
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    medium_tokens = _normalize_tokens(utm_medium or "")
    if medium_tokens:
        by_medium = [cid for cid in candidates if medium_tokens & campaigns[cid]["tokens"]]
        if len(by_medium) == 1:
            return by_medium[0]
        if by_medium:
            candidates = by_medium
    extras = {cid: len(campaigns[cid]["tokens"] ^ utm_tokens) for cid in candidates}
    best = min(extras.values())
    winners = [cid for cid, n in extras.items() if n == best]
    return winners[0] if len(winners) == 1 else None


logger = logging.getLogger(__name__)

_NO_CAMPAIGN = "(sem campanha)"


def _s(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _cancelada(sale: dict[str, Any]) -> bool:
    """Venda cancelada não é venda: não conta cliente, pedido, receita nem compra."""
    return venda_cancelada(sale)


# Origens (utm_source) de anúncio pago, por plataforma. A gestora de tráfego tagueia a Meta
# como 'metaads' e o Google como 'google'. Usadas quando NÃO há click-id — ex.: anúncio Meta
# que leva ao WhatsApp (sem fbclid) ou Google PMAX sem gclid. NÃO incluir 'instagram'/
# 'facebook' crus: esses são o tráfego ORGÂNICO (ex.: link da bio, utm_medium=bio).
_META_AD_SOURCES: frozenset[str] = frozenset(
    {"metaads", "meta_ads", "meta-ads", "meta", "facebook_ads", "facebookads", "fb_ads"}
)
_GOOGLE_AD_SOURCES: frozenset[str] = frozenset({"google", "googleads", "google_ads", "adwords"})
# Meios (utm_medium) pagos — desambiguam utm_source=google pago (cpc/pmax) do SEO orgânico.
_PAID_CHANNEL_MEDIUMS: frozenset[str] = frozenset(
    {"cpc", "ppc", "pmax", "performance_max", "paid", "paid_search", "paidsearch",
     "display", "cpm", "paid_social", "paidsocial"}
)
# leads.origem_cadastro de quem foi IMPORTADO (b67f1c6b): não é lead de marketing. Canal "Bling"
# (fn_lead_canal da 20261022c) e fora do "Leads" do relatório (D1).
_ORIGENS_IMPORTADAS: frozenset[str] = frozenset({"bling_import", "reativacao_import"})

# F5 (cartão C, 06/11/2026): canais com nome no lugar de "Sem rastreio". Em 15 a 21/10, 21 de 27
# vendas caíram em "Sem rastreio" porque o CRM sabia como o lead entrou e o relatório não olhava.
CANAL_SEM_RASTREIO = "Sem rastreio"
CANAL_WHATSAPP_DIRETO = "WhatsApp direto"
CANAL_MANUAL = "Cadastro manual / disparo"
CANAL_CSV = "Importado (CSV)"
CANAL_CLIENTE_ANTIGO = "Cliente antigo"
CANAL_NUMERO_ANTIGO = "Número antigo / outro número"
# leads.origem_cadastro -> canal, quando não há click-id nem UTM. Espelha fn_lead_canal (F5).
_CANAL_POR_ORIGEM: dict[str, str] = {
    "inbound": CANAL_WHATSAPP_DIRETO,
    "manual": CANAL_MANUAL,
    "csv_import": CANAL_CSV,
}
# Canais "sem sinal de anúncio": só eles recebem o contexto (cliente antigo, outro número…).
_CANAIS_SEM_SINAL: frozenset[str] = frozenset(
    {CANAL_WHATSAPP_DIRETO, CANAL_MANUAL, CANAL_CSV, CANAL_SEM_RASTREIO})
# leads.channel de quem foi criado sem nunca ter escrito (antes da origem_cadastro existir, todo
# lead ficou 'inbound' por padrão). Espelha fn_lead_canal_contexto.
_CANAL_POR_LEAD_CHANNEL: dict[str, str] = {
    "campaign": CANAL_MANUAL, "manual": CANAL_MANUAL, "broadcast": CANAL_MANUAL,
    "bling": "Bling", "csv": CANAL_CSV,
}


def derive_channel(lead: dict[str, Any]) -> str:
    """Canal do lead. Prioridade: click-id > anúncio do Meta > utm_source de anúncio >
    orgânico > como entrou no CRM (origem_cadastro) > sem rastreio.

    F5: sem click-id nem UTM, `origem_cadastro` dá o nome do canal — inbound vira "WhatsApp
    direto", manual "Cadastro manual / disparo" e csv_import "Importado (CSV)". Lead sem
    origem_cadastro no dict continua "Sem rastreio". O contexto que depende de outras tabelas
    (cliente antigo, outro número, nunca escreveu) vem depois, em `aplicar_contexto_canal`.

    `meta_ad_id` (referral.source_id do CTWA) conta como sinal de canal pago junto dos
    click-ids: nem todo referral do WhatsApp traz `ctwa_clid`, mas o id do anúncio vem
    sempre. Sem ele, 15 leads pagos da janela 01-16/09/2026 caíam em "Sem rastreio" com o
    anúncio que os trouxe já gravado na própria linha.

    Meta e Google são detectados TAMBÉM por utm_source (a gestora tagueia 'metaads'/'google'),
    porque nem todo lead pago traz click-id (Meta→WhatsApp sem fbclid, PMAX sem gclid). Google
    exige um meio pago (cpc/pmax/…) para não confundir com SEO orgânico; 'metaads' é inequívoco.
    Lead importado (origem_cadastro bling_import/reativacao_import) sem click-id é "Bling"
    (b67f1c6b): o UTM que ele tenha não diz de onde veio. Espelha fn_lead_canal (20261022c).
    Retorna Google Ads/Meta Ads/Bling/Orgânico/Sem rastreio.
    """
    # gbraid/wbraid: cliques de iOS do Google (sem gclid); mesma regra do gclid.
    if _s(lead.get("gclid")) or _s(lead.get("gbraid")) or _s(lead.get("wbraid")):
        return "Google Ads"
    if _s(lead.get("fbclid")) or _s(lead.get("ctwa_clid")) or _s(lead.get("meta_ad_id")):
        return "Meta Ads"
    if _s(lead.get("origem_cadastro")).lower() in _ORIGENS_IMPORTADAS:
        return "Bling"
    source = _s(lead.get("utm_source")).lower()
    medium = _s(lead.get("utm_medium")).lower()
    if source in _META_AD_SOURCES:
        return "Meta Ads"
    if source in _GOOGLE_AD_SOURCES and medium in _PAID_CHANNEL_MEDIUMS:
        return "Google Ads"
    if _s(lead.get("traffic_type")).lower() == "organic" or source:
        return "Orgânico"
    return _CANAL_POR_ORIGEM.get(_s(lead.get("origem_cadastro")).lower(), CANAL_SEM_RASTREIO)


def aplicar_contexto_canal(canal: str, *, cliente_antigo: bool | None = None,
                           numero_antigo: str | None = None, tem_inbound: bool | None = None,
                           lead_channel: str | None = None) -> str:
    """Refina um canal "sem sinal de anúncio" com o que o CRM sabe do lead. Puro.

    Espelha `public.fn_lead_canal_contexto` (migração 20261106_f5_jornada). Os sinais vêm de
    `vw_lead_contexto_canal`; `None` = não sei, e aí o canal não muda.
      1. cliente_antigo (já comprava antes do lead existir) -> "Cliente antigo";
      2. numero_antigo (nome do canal de WhatsApp da 1ª conversa, quando não é o dos anúncios)
         -> "Número antigo / outro número";
      3. "WhatsApp direto" cujo leads.channel diz que o lead foi CADASTRADO (manual, disparo,
         Bling, CSV): vale o cadastro, mesmo que ele tenha escrito depois. Diagnóstico de
         10/11/2026: 470 leads com channel 'manual' e origem 'inbound' (padrão de quem existia
         antes da coluna origem_cadastro);
      4. "WhatsApp direto" de quem NUNCA escreveu (tem_inbound = False) e sem cadastro
         conhecido: "Sem rastreio".
    Canal pago, Orgânico e Bling nunca mudam."""
    if canal not in _CANAIS_SEM_SINAL:
        return canal
    if cliente_antigo:
        return CANAL_CLIENTE_ANTIGO
    if _s(numero_antigo) and canal in (CANAL_WHATSAPP_DIRETO, CANAL_SEM_RASTREIO):
        return CANAL_NUMERO_ANTIGO
    if canal == CANAL_WHATSAPP_DIRETO:
        cadastro = _CANAL_POR_LEAD_CHANNEL.get(_s(lead_channel).lower())
        if cadastro:
            return cadastro
        if tem_inbound is False:
            return CANAL_SEM_RASTREIO
    return canal


def _contexto(lead: dict[str, Any], com_toque: bool = False) -> dict[str, Any]:
    """Sinais de contexto do lead. `com_toque`: o canal veio de uma entrada da linha do tempo, que
    já prova como o lead chegou — "nunca escreveu" (tem_inbound) só vale para o lead estimado."""
    return {"cliente_antigo": lead.get("cliente_antigo"),
            "numero_antigo": lead.get("numero_antigo"),
            "tem_inbound": None if com_toque else lead.get("tem_inbound"),
            "lead_channel": lead.get("channel")}


def motivo_sem_rastreio(lead: dict[str, Any]) -> str | None:
    """Por que o lead sobrou em "Sem rastreio" (detalhe do /trafego, cartão C item 4). Puro."""
    if lead_channel(lead) != CANAL_SEM_RASTREIO:
        return None
    origem = _s(lead.get("origem_cadastro")).lower()
    if not origem:
        return "Sem origem de cadastro"
    if lead.get("tem_inbound") is False and not lead.get("_canal_toque"):
        ch = _s(lead.get("channel")).lower()
        return "Nunca mandou mensagem" + (f" (cadastro '{ch}')" if ch and ch != "whatsapp" else "")
    if lead.get("tem_inbound") is None:
        return "Sem nenhum sinal (contexto indisponível)"
    return "Sem nenhum sinal"


# Atribuição manual (P0: leads.campanha_manual_*). Um admin diz no /trafego de qual campanha o
# lead veio quando o rastreio não diz — e essa resposta vence meta_ad_id, UTMs e tokens.
_MANUAL_CHANNEL = {"meta": "Meta Ads", "google": "Google Ads"}


def manual_attribution(lead: dict[str, Any]) -> tuple[str, str, str] | None:
    """(canal do relatório, campaign_id, nome) da atribuição manual, ou None."""
    channel = _MANUAL_CHANNEL.get(_s(lead.get("campanha_manual_canal")).lower())
    cid = _s(lead.get("campanha_manual_id"))
    if not channel or not cid:
        return None
    return channel, cid, _s(lead.get("campanha_manual_nome")) or cid


def lead_channel(lead: dict[str, Any]) -> str:
    """Canal do lead no relatório: a atribuição manual vence o rastreio.

    Sem manual: o canal do toque escolhido pela atribuição (`_canal_toque`, posto por
    `atribuir_lead`) ou, sem toque, o derive_channel das colunas — e, nos dois, o contexto."""
    manual = manual_attribution(lead)
    if manual:
        return manual[0]
    toque = lead.get("_canal_toque")
    return aplicar_contexto_canal(toque or derive_channel(lead), **_contexto(lead, bool(toque)))


# --- Jornada do lead (F5, cartão B) ------------------------------------------------------
# A linha do tempo (`lead_events` tipo `entrada`) guarda cada toque com data. A jornada é a lista
# desses toques; a atribuição escolhe UM deles (o primeiro ou o último antes do evento) e o
# relatório roda sobre o rastreio daquele toque. Espelho SQL: public.vw_lead_jornada.
ATRIBUICOES = ("ultima", "primeira")
_TRACK_KEYS = ("gclid", "gbraid", "wbraid", "fbclid", "ctwa_clid", "meta_ad_id",
               "utm_source", "utm_medium", "utm_campaign", "traffic_type")
_SETA = " → "


def canal_da_entrada(entrada: dict[str, Any]) -> str:
    """Canal de UM toque. Puro; espelha a coluna `canal` de vw_lead_jornada.

    O rastreio gravado no metadata manda (mesma regra do derive_channel, sem origem). Toque sem
    rastreio usa o rótulo gravado: a entrada automática "Orgânico" (sem_rastreio) é o "WhatsApp
    direto" (cartão C, unificado), e os toques novos já vêm com o nome ("WhatsApp direto",
    "Google Ads" do botão do Google)."""
    meta = entrada.get("metadata") or {}
    canal = derive_channel({k: meta.get(k) for k in _TRACK_KEYS})
    if canal != CANAL_SEM_RASTREIO:
        return canal
    rotulo = _s(meta.get("canal")) or _s(entrada.get("new_value"))
    if rotulo == "Orgânico" and meta.get("sem_rastreio") in (True, "true"):
        return CANAL_WHATSAPP_DIRETO
    return rotulo or CANAL_SEM_RASTREIO


def _toques(entradas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Entradas válidas em ordem cronológica, cada uma com o canal já resolvido."""
    out = []
    for e in entradas or []:
        em = _parse_iso(e.get("occurred_at"))
        if em is None:
            continue
        out.append({"em": em, "canal": canal_da_entrada(e), "entrada": e})
    out.sort(key=lambda t: t["em"])
    return out


def _sem_repetir(canais: list[str]) -> list[str]:
    out: list[str] = []
    for c in canais:
        if not out or out[-1] != c:
            out.append(c)
    return out


def jornada_do_lead(lead: dict[str, Any], entradas: list[dict[str, Any]],
                    ate: Any = None) -> dict[str, Any]:
    """Uma linha por lead, como vw_lead_jornada: primeira/última origem, origens na ordem (sem
    repetir seguidas), n_toques, multicanal. Puro.

    `ate` (venda, repasse) corta a ÚLTIMA origem: é o último toque com occurred_at <= ate. Sem
    toque até lá, vale o primeiro. Lead sem nenhuma entrada (antigo) cai no canal das colunas
    (derive_channel + contexto), marcado como `estimado`. A primeira e a última recebem o contexto
    (cliente antigo…); `origens` mostra os toques como foram gravados."""
    toques = _toques(entradas)
    if not toques:
        canal = aplicar_contexto_canal(derive_channel(lead), **_contexto(lead))
        return {"primeira_origem": canal, "primeira_em": None, "ultima_origem": canal,
                "ultima_em": None, "origens": [canal], "toques": [], "n_toques": 0,
                "multicanal": False, "estimado": True}
    limite = _parse_iso(ate) if isinstance(ate, str) else ate
    antes = [t for t in toques if limite is None or t["em"] <= limite] or toques[:1]
    primeiro, ultimo = toques[0], antes[-1]
    ctx = _contexto(lead, com_toque=True)
    canais = [t["canal"] for t in toques]
    return {
        "primeira_origem": aplicar_contexto_canal(primeiro["canal"], **ctx),
        "primeira_em": primeiro["em"].isoformat(),
        "ultima_origem": aplicar_contexto_canal(ultimo["canal"], **ctx),
        "ultima_em": ultimo["em"].isoformat(),
        "origens": _sem_repetir(canais),
        "toques": [{"canal": t["canal"], "em": t["em"].isoformat()} for t in toques],
        "n_toques": len(toques),
        "multicanal": len(set(canais)) >= 2,
        "estimado": False,
    }


def toque_atribuido(entradas: list[dict[str, Any]], atribuicao: str,
                    ate: Any = None) -> dict[str, Any] | None:
    """A entrada que leva o crédito: a primeira, ou a última com occurred_at <= `ate`. Puro."""
    toques = _toques(entradas)
    if not toques:
        return None
    if atribuicao == "primeira":
        return toques[0]["entrada"]
    limite = _parse_iso(ate) if isinstance(ate, str) else ate
    antes = [t for t in toques if limite is None or t["em"] <= limite] or toques[:1]
    return antes[-1]["entrada"]


def atribuir_lead(lead: dict[str, Any], entradas: list[dict[str, Any]], atribuicao: str,
                  ate: Any = None) -> dict[str, Any]:
    """Cópia do lead com o rastreio do toque atribuído no lugar das colunas. Puro.

    As colunas do lead guardam o ÚLTIMO valor de cada campo, misturando cliques (quem passou
    pelo Meta e pelo Google fica com ctwa_clid E gclid, e a prioridade fixa jogava todos no
    Google). Aqui o lead "vira" o toque escolhido: campanha, anúncio e UTM daquele clique. Sem
    entrada, o lead fica como está (estimado). A atribuição manual continua valendo por cima."""
    toque = toque_atribuido(entradas, atribuicao, ate)
    out = dict(lead)
    out["_jornada"] = jornada_do_lead(lead, entradas, ate)
    if toque is None:
        return out
    meta = toque.get("metadata") or {}
    for k in _TRACK_KEYS:
        out[k] = meta.get(k)
    out["_canal_toque"] = canal_da_entrada(toque)
    if _s(meta.get("campanha_id")):
        out["_campanha_id"] = _s(meta.get("campanha_id"))
    return out


def build_jornadas(leads: list[dict[str, Any]], sales_by_lead: dict[str, dict[str, Any]],
                   top: int = 5) -> dict[str, Any]:
    """Bloco "Jornadas com mais de um canal": quantos leads e vendas do período passaram por 2
    canais ou mais, e os `top` caminhos mais comuns. Puro; `leads` já têm `_jornada`."""
    caminhos: dict[str, dict[str, Any]] = {}
    tot = {"leads": 0, "clientes": 0, "pedidos": 0, "receita": 0.0}
    for l in leads:
        j = l.get("_jornada") or {}
        if not j.get("multicanal"):
            continue
        sale = sales_by_lead.get(l.get("id")) or {}
        caminho = _SETA.join(j.get("origens") or [])
        c = caminhos.setdefault(caminho, {"caminho": caminho, "leads": 0, "clientes": 0,
                                          "pedidos": 0, "receita": 0.0})
        for d in (c, tot):
            d["leads"] += 1
            if sale:
                d["clientes"] += 1
                d["pedidos"] += int(sale.get("count", 0) or 0)
                d["receita"] += float(sale.get("value", 0.0) or 0.0)
    ordem = sorted(caminhos.values(), key=lambda c: (-c["pedidos"], -c["receita"], -c["leads"],
                                                     c["caminho"]))
    for c in ordem:
        c["receita"] = round(c["receita"], 2)
    tot["receita"] = round(tot["receita"], 2)
    return {**tot, "total_leads": len(leads), "caminhos": ordem[:top]}


_UNATTRIBUTED = "(não atribuído)"


def _index_campaigns(spend):
    """Normaliza o gasto da plataforma em {campaign_id: {name, tokens, cost}}.

    A chave é o campaign_id porque é o que garante que o gasto de uma campanha entre no
    relatório UMA vez só, por mais utm_campaign diferentes que apontem para ela."""
    out = {}
    if not spend:
        return out
    # Compat: {campaign_name: cost} (formato antigo) -> sintetiza um id a partir do nome.
    items = (
        [{"campaign_id": "", "campaign_name": n, "cost": c} for n, c in spend.items()]
        if isinstance(spend, dict) else spend
    )
    for r in items:
        name = (r.get("campaign_name") or "").strip()
        if not name:
            continue
        cid = str(r.get("campaign_id") or "") or "name:" + name.lower()
        slot = out.setdefault(cid, {"name": name, "tokens": _normalize_tokens(name), "cost": 0.0})
        try:
            slot["cost"] += float(r.get("cost") or 0.0)
        except (TypeError, ValueError):
            pass
    return out


def _new_row(channel, campaign):
    return {"channel": channel, "campaign": campaign, "leads": 0, "conversas": 0, "closer": 0,
            "clientes": 0, "pedidos": 0, "receita": 0.0, "frete": 0.0, "investimento": 0.0}


def build_campaign_report(
    leads: list[dict[str, Any]],
    conversed_ids: set[str],
    closer_ids: set[str],
    sales_by_lead: dict[str, dict[str, Any]],
    mode: str,
    period: str,
    spend_by_channel: dict[str, Any] | None = None,
    campaign_id_by_lead: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Agrega os leads em linhas (canal, campanha). Puro — recebe coleções já buscadas.

    - conversed_ids / closer_ids: sets de lead_id que conversaram / chegaram ao closer.
    - sales_by_lead: lead_id -> {"count": int, "value": float, "frete": float} (já filtrado
      por modo). `value` é a receita SEM frete (D7, 1e6381fe); o frete vem à parte.
    - spend_by_channel: canal -> [{campaign_id, campaign_name, cost}] vindo de ad_spend.
    - campaign_id_by_lead: lead_id -> campaign_id quando a própria plataforma nos deu o
      vínculo (Meta CTWA via anuncio). Vence qualquer casamento por nome.

    O eixo do relatório é a CAMPANHA DA PLATAFORMA, não o slug de utm. Cada campanha vira uma
    linha e recebe seu gasto exatamente uma vez; os vários utm_campaign que apontam para ela
    (ex.: 'terceirizacao' e 'leads_search_terceirizacao') somam leads na MESMA linha. Antes o
    gasto era puxado do lado do lead, então cada variante de slug cobrava o custo cheio da
    campanha de novo — o investimento do Google aparecia 2,6x maior do que foi gasto.

    Funil CUMULATIVO (call de 01/10): quem comprou passou pelo closer, e quem chegou ao closer
    conversou — cliente ⊂ closer ⊂ conversa. Antes eram conjuntos independentes, e o pedido do
    Bling de quem já era cliente (lead criado já com venda, sem conversa nem deal) aparecia como
    "4 closer e 10 clientes". `entraram_ja_clientes` guarda quantos clientes NÃO eram closer pelo
    critério antigo: o que o Arthur percebeu continua visível em vez de sumir na soma.

    Invariante: para cada canal pago, soma(linhas.investimento) == gasto real da plataforma
    na janela. Campanha que gastou sem gerar lead entra com leads=0 em vez de sumir."""
    spend_by_channel = spend_by_channel or {}
    campaign_id_by_lead = campaign_id_by_lead or {}
    campaigns_by_channel = {ch: _index_campaigns(sp) for ch, sp in spend_by_channel.items()}

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    # (canal, campaign_id) -> linha, para pendurar o custo depois sem depender do rótulo.
    row_by_campaign: dict[tuple[str, str], dict[str, Any]] = {}
    resolved_cache: dict[tuple[str, str, str], str | None] = {}
    entraram_ja_clientes = 0

    for lead in leads:
        lead_id = lead.get("id")
        manual = manual_attribution(lead)
        channel = lead_channel(lead)
        raw_campaign = _s(lead.get("utm_campaign"))
        campaigns = campaigns_by_channel.get(channel)
        cid = None
        label = None
        if manual:
            # A resposta do admin vence anúncio e UTM. Campanha sem gasto na janela vira linha
            # própria com o nome gravado (investimento 0), sem se misturar com o "não atribuído".
            cid = manual[1]
            label = campaigns[cid]["name"] if campaigns and cid in campaigns else manual[2]
        elif campaigns:
            platform_cid = _s(lead.get("_campanha_id")) or campaign_id_by_lead.get(lead_id)
            if platform_cid and platform_cid in campaigns:
                cid = platform_cid
            else:
                medium = _s(lead.get("utm_medium"))
                ck = (channel, raw_campaign.lower(), medium.lower())
                if ck not in resolved_cache:
                    resolved_cache[ck] = resolve_campaign_id(raw_campaign, medium, campaigns)
                cid = resolved_cache[ck]
        if cid:
            key = (channel, "id:" + cid)
            if label is None:
                label = campaigns[cid]["name"]
        elif campaigns:
            # Canal pago sem campanha resolvida: não se mistura com uma campanha real, mas
            # mantém o slug no rótulo quando existe — é a pista p/ corrigir o tagueamento.
            key = (channel, "un:" + raw_campaign.lower())
            label = (_UNATTRIBUTED + " · " + raw_campaign) if raw_campaign else _UNATTRIBUTED
        else:
            key = (channel, raw_campaign.lower() or _NO_CAMPAIGN)
            label = raw_campaign or _NO_CAMPAIGN
        row = groups.get(key)
        if row is None:
            row = _new_row(channel, label)
            groups[key] = row
            if cid:
                row_by_campaign[(channel, cid)] = row
        row["leads"] += 1
        sale = sales_by_lead.get(lead_id)
        cliente = bool(sale)
        closer = cliente or lead_id in closer_ids
        if closer or lead_id in conversed_ids:
            row["conversas"] += 1
        if closer:
            row["closer"] += 1
        if cliente:
            row["clientes"] += 1  # leads distintos que compraram (base da conversão)
            row["pedidos"] += int(sale.get("count", 0) or 0)  # nº de vendas (recompra: pode ser >1)
            row["receita"] += float(sale.get("value", 0.0) or 0.0)
            row["frete"] += float(sale.get("frete", 0.0) or 0.0)
            if lead_id not in closer_ids:
                entraram_ja_clientes += 1

    # Investimento: percorre as CAMPANHAS (não os leads), então cada custo entra uma única vez.
    # Campanha que gastou e não gerou lead ganha uma linha zerada — sumir do relatório seria
    # subestimar o investimento do canal e inflar o ROAS.
    for channel, campaigns in campaigns_by_channel.items():
        for cid, c in campaigns.items():
            row = row_by_campaign.get((channel, cid))
            if row is None:
                row = _new_row(channel, c["name"])
                groups[(channel, "id:" + cid)] = row
                row_by_campaign[(channel, cid)] = row
            row["investimento"] = round(float(c["cost"]), 2)

    rows: list[dict[str, Any]] = []
    total = {"leads": 0, "conversas": 0, "closer": 0, "clientes": 0, "pedidos": 0,
             "receita": 0.0, "frete": 0.0, "investimento": 0.0}
    paid_receita = 0.0
    for row in groups.values():
        pedidos = row["pedidos"]
        row["ticket_medio"] = round(row["receita"] / pedidos, 2) if pedidos else 0.0
        row["conversao"] = round(row["clientes"] / row["leads"], 4) if row["leads"] else 0.0
        inv = row["investimento"]
        row["roas"] = round(row["receita"] / inv, 2) if inv else None
        if row["channel"] in campaigns_by_channel:
            paid_receita += row["receita"]
        for k in total:
            total[k] += row[k]
        rows.append(row)

    channel_subtotals: dict[str, dict[str, Any]] = {}
    for row in rows:
        sub = channel_subtotals.get(row["channel"])
        if sub is None:
            sub = {"leads": 0, "conversas": 0, "closer": 0, "clientes": 0, "pedidos": 0,
                   "receita": 0.0, "frete": 0.0, "investimento": 0.0}
            channel_subtotals[row["channel"]] = sub
        for k in sub:
            sub[k] += row[k]
    for sub in channel_subtotals.values():
        sub["receita"] = round(sub["receita"], 2)
        sub["frete"] = round(sub["frete"], 2)
        sub["investimento"] = round(sub["investimento"], 2)
        sub["roas"] = round(sub["receita"] / sub["investimento"], 2) if sub["investimento"] else None

    # Não atribuído por último dentro do canal: é sobra, não a leitura principal.
    rows.sort(key=lambda r: (r["channel"], r["campaign"].startswith(_UNATTRIBUTED),
                             -r["receita"], -r["investimento"], -r["leads"]))
    total["receita"] = round(total["receita"], 2)
    total["frete"] = round(total["frete"], 2)
    for row in rows:
        row["receita"] = round(row["receita"], 2)
        row["frete"] = round(row["frete"], 2)
    total["investimento"] = round(total["investimento"], 2)
    total["roas"] = round(paid_receita / total["investimento"], 2) if total["investimento"] else None
    return {"mode": mode, "period": period, "rows": rows, "total": total,
            "channel_subtotals": channel_subtotals, "entraram_ja_clientes": entraram_ja_clientes}


# --- Visão do período (padrão desde 12/11/2026) ------------------------------------------
# Cada coluna conta pela PRÓPRIA data: leads/conversas/closer = quem entrou no período (a coorte
# do modo lead); clientes/pedidos/receita = toda venda do período, de lead novo ou antigo (o modo
# venda). Antes o Rafael tinha de escolher: o "por lead" zerava as vendas (05–11/11: 1 cliente de
# 53 pedidos) e o "por venda" sumia com os leads (o Meta Atacado ficava com 0 leads de 64).
MODO_PERIODO = "periodo"
_TOPO = ("leads", "conversas", "closer")
_VENDA = ("clientes", "pedidos", "receita", "frete")


def _finalizar_linha_periodo(row: dict[str, Any]) -> None:
    """Ticket, ROAS e conversão. Conversão = pedidos ÷ leads DO PERÍODO: é taxa do período, não
    de coorte (os pedidos podem ser de quem entrou antes). Sem lead no período → None ("—")."""
    row["receita"] = round(row["receita"], 2)
    row["frete"] = round(row["frete"], 2)
    row["investimento"] = round(row["investimento"], 2)
    row["ticket_medio"] = round(row["receita"] / row["pedidos"], 2) if row["pedidos"] else 0.0
    row["conversao"] = round(row["pedidos"] / row["leads"], 4) if row["leads"] else None
    row["roas"] = round(row["receita"] / row["investimento"], 2) if row["investimento"] else None


def merge_period_report(lead_report: dict[str, Any], sale_report: dict[str, Any],
                        period: str) -> dict[str, Any]:
    """Funde o relatório por lead (topo do funil) com o por venda (vendas). Puro.

    As linhas casam por (canal, rótulo da campanha): os dois relatórios resolvem a campanha do
    mesmo jeito (anúncio → manual → UTM) com o mesmo gasto, então o rótulo é o mesmo. O
    investimento vem do relatório por lead (é o mesmo gasto nos dois)."""
    linhas: dict[tuple[str, str], dict[str, Any]] = {}

    def _slot(r: dict[str, Any]) -> dict[str, Any]:
        k = (r["channel"], r["campaign"])
        if k not in linhas:
            linhas[k] = _new_row(r["channel"], r["campaign"])
        return linhas[k]

    for r in lead_report.get("rows") or []:
        s = _slot(r)
        for k in _TOPO:
            s[k] += int(r.get(k, 0) or 0)
        s["investimento"] = max(s["investimento"], float(r.get("investimento", 0) or 0))
    for r in sale_report.get("rows") or []:
        s = _slot(r)
        for k in _VENDA:
            s[k] += r.get(k, 0) or 0
        s["investimento"] = max(s["investimento"], float(r.get("investimento", 0) or 0))

    rows = [r for r in linhas.values()
            if r["leads"] or r["pedidos"] or r["investimento"] or r["closer"]]
    paid_channels = set(_PAID_CHANNELS)
    subtotals: dict[str, dict[str, Any]] = {}
    total = {k: 0 for k in _TOPO + ("clientes", "pedidos")}
    total.update(receita=0.0, frete=0.0, investimento=0.0)
    paid_receita = 0.0
    for r in rows:
        _finalizar_linha_periodo(r)
        sub = subtotals.setdefault(r["channel"], {**{k: 0 for k in total}, "receita": 0.0,
                                                  "frete": 0.0, "investimento": 0.0})
        for k in total:
            total[k] += r[k]
            sub[k] += r[k]
        if r["channel"] in paid_channels:
            paid_receita += r["receita"]
    for sub in subtotals.values():
        for k in ("receita", "frete", "investimento"):
            sub[k] = round(sub[k], 2)
        sub["roas"] = round(sub["receita"] / sub["investimento"], 2) if sub["investimento"] else None
        sub["conversao"] = round(sub["pedidos"] / sub["leads"], 4) if sub["leads"] else None
    for k in ("receita", "frete", "investimento"):
        total[k] = round(total[k], 2)
    total["roas"] = round(paid_receita / total["investimento"], 2) if total["investimento"] else None
    total["conversao"] = round(total["pedidos"] / total["leads"], 4) if total["leads"] else None
    rows.sort(key=lambda r: (r["channel"], r["campaign"].startswith(_UNATTRIBUTED),
                             -r["receita"], -r["investimento"], -r["leads"]))
    return {"mode": MODO_PERIODO, "period": period, "rows": rows, "total": total,
            "channel_subtotals": subtotals,
            "entraram_ja_clientes": int(lead_report.get("entraram_ja_clientes", 0) or 0)}


# --- Relatório geral (bloco acima da tabela) -------------------------------------------
_PAID_CHANNELS = ("Google Ads", "Meta Ads")
_CHANNEL_ORDER = ("Google Ads", "Meta Ads", "Orgânico", CANAL_WHATSAPP_DIRETO, CANAL_CLIENTE_ANTIGO,
                  CANAL_NUMERO_ANTIGO, CANAL_MANUAL, CANAL_CSV, "Bling", CANAL_SEM_RASTREIO)
_FUNNEL_STAGES = ("conversa", "closer", "cliente")
_COUNT_KEYS = ("leads", "conversas", "closer", "clientes")


def _ratio(num: float, den: float, nd: int = 4) -> float | None:
    return round(num / den, nd) if den else None


def _parse_iso(v: Any) -> datetime | None:
    if not isinstance(v, str) or not v:
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _stage_rates(c: dict[str, int]) -> dict[str, float | None]:
    return {
        "taxa_conversa": _ratio(c["conversas"], c["leads"]),
        "taxa_closer": _ratio(c["closer"], c["conversas"]),
        "taxa_cliente": _ratio(c["clientes"], c["closer"]),
        "taxa_total": _ratio(c["clientes"], c["leads"]),
    }


def _counts(d: dict[str, Any]) -> dict[str, int]:
    return {k: int(d.get(k, 0) or 0) for k in _COUNT_KEYS}


def build_report_summary(report: dict[str, Any], leads: list[dict[str, Any]],
                         sales_by_lead: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Relatório geral do período — puro, deriva tudo do relatório já montado.

    Custo por etapa divide o gasto SÓ pelas contagens dos canais pagos: dividir pelo total
    (orgânico incluso) faria o CPL parecer mais barato do que é. Os dias até a 1ª compra
    descartam valores negativos — os 1.208 leads importados do Bling têm created_at = data
    da importação e compras anteriores a ela, e puxariam a mediana para baixo de zero.
    """
    total = report.get("total") or {}
    subtotals = report.get("channel_subtotals") or {}
    rows = report.get("rows") or []

    counts = _counts(total)
    rates = _stage_rates(counts)
    candidates = [(rates["taxa_" + s], i, s) for i, s in enumerate(_FUNNEL_STAGES)
                  if rates["taxa_" + s] is not None]
    funnel = {**counts, **rates, "gargalo": min(candidates)[2] if candidates else None,
              "entraram_ja_clientes": int(report.get("entraram_ja_clientes", 0) or 0),
              # as duas pontas reais do funil do período ("172 leads → 60 closer → 53 pedidos")
              "pedidos": int(total.get("pedidos", 0) or 0),
              "receita": round(float(total.get("receita", 0) or 0), 2)}

    paid = dict.fromkeys(_COUNT_KEYS, 0)
    inv = rec = fre = 0.0
    for ch in _PAID_CHANNELS:
        sub = subtotals.get(ch)
        if not sub:
            continue
        for k, v in _counts(sub).items():
            paid[k] += v
        inv += float(sub.get("investimento", 0) or 0)
        rec += float(sub.get("receita", 0) or 0)
        fre += float(sub.get("frete", 0) or 0)

    def _cost(den: int) -> float | None:
        return round(inv / den, 2) if inv and den else None

    # Receita sem frete (D7); o frete das mesmas vendas fica ao lado.
    cost = {"investimento": round(inv, 2), "receita": round(rec, 2), "frete": round(fre, 2),
            "roas": round(rec / inv, 2) if inv else None, **paid,
            "cpl": _cost(paid["leads"]), "custo_conversa": _cost(paid["conversas"]),
            "custo_closer": _cost(paid["closer"]), "cac": _cost(paid["clientes"])}

    order = [c for c in _CHANNEL_ORDER if c in subtotals]
    order += sorted(c for c in subtotals if c not in _CHANNEL_ORDER)
    channels: list[dict[str, Any]] = []
    for ch in order:
        sub = subtotals[ch]
        c = _counts(sub)
        inv_ch = round(float(sub.get("investimento", 0) or 0), 2)
        if c["leads"] == 0 and inv_ch == 0 and not int(sub.get("pedidos", 0) or 0):
            continue
        rec_ch = round(float(sub.get("receita", 0) or 0), 2)
        channels.append({"channel": ch, **c, "pedidos": int(sub.get("pedidos", 0) or 0), "receita": rec_ch,
                         "frete": round(float(sub.get("frete", 0) or 0), 2), "investimento": inv_ch,
                         "roas": round(rec_ch / inv_ch, 2) if inv_ch else None,
                         **_stage_rates(c)})

    dias: list[float] = []
    recompradores = 0
    for lead in leads:
        sale = sales_by_lead.get(lead.get("id"))
        if not sale:
            continue
        if int(sale.get("count", 0) or 0) > 1:
            recompradores += 1
        created = _parse_iso(lead.get("created_at"))
        first = _parse_iso(sale.get("first_sold_at"))
        if created is None or first is None:
            continue
        d = (first - created).total_seconds() / 86400
        if d >= 0:
            dias.append(d)

    clientes = counts["clientes"]
    pedidos = int(total.get("pedidos", 0) or 0)
    nao_atribuido = sum(int(r.get("leads", 0) or 0) for r in rows
                        if r.get("channel") in _PAID_CHANNELS
                        and str(r.get("campaign", "")).startswith(_UNATTRIBUTED))
    sem_rastreio = int((subtotals.get("Sem rastreio") or {}).get("leads", 0) or 0)
    timing_quality = {
        "dias_ate_compra_mediana": round(median(dias), 1) if dias else None,
        "amostra_dias": len(dias),
        "pedidos_por_cliente": _ratio(pedidos, clientes, 2),
        "recompra_pct": _ratio(recompradores, clientes),
        "sem_rastreio_pct": _ratio(sem_rastreio, counts["leads"]),
        "nao_atribuido_pct": _ratio(nao_atribuido, paid["leads"]),
    }
    return {"funnel": funnel, "cost": cost, "channels": channels,
            "timing_quality": timing_quality}


_PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90}
_LEAD_COLS = ("id, name, phone, created_at, gclid, gbraid, wbraid, fbclid, ctwa_clid, "
              "utm_source, utm_medium, utm_campaign, traffic_type, origem_cadastro, "
              # b67f1c6b: segmento do lead (leads.segmento; `stage` é a reserva do lead
              # ainda não migrado) — mesma migration-par de origem_cadastro.
              "segmento, stage, "
              # F5: leads.channel diz como o lead antigo (sem origem_cadastro de verdade) entrou.
              "channel")


class _MetaAdCol:
    """Flag de processo: leads.meta_ad_id existe? Desligada na primeira falha de select."""
    enabled = True


# Colunas do P0 (20261006_call_semanal_base.sql — migração manual). Até o Rafael aplicá-la, o
# PostgREST rejeita o select inteiro; o relatório degrada (perde só atribuição manual e "já
# era cliente") em vez de zerar.
_P0_LEAD_COLS = ("campanha_manual_canal, campanha_manual_id, campanha_manual_nome, "
                 "ja_era_cliente, ja_era_cliente_fonte")
_P0_COL_MARKERS = ("campanha_manual", "ja_era_cliente")


class _P0Col:
    """Flag de processo: colunas do P0 existem? Desligada só quando o erro CITA uma delas —
    um erro de rede não pode desligar a atribuição manual.

    Religa sozinha depois de TTL_S: o código sobe pelo deploy e a migração é aplicada à mão
    depois. Sem o TTL, um acesso ao /trafego antes da migração desligaria as colunas até o
    próximo restart, e o relatório ignoraria em silêncio a atribuição manual e o "já era
    cliente" já gravados. `relogio` é injetável para o teste andar o tempo."""
    TTL_S = 300.0
    falhou_em: float | None = None
    relogio = staticmethod(_time.monotonic)

    @classmethod
    def ativo(cls) -> bool:
        if cls.falhou_em is None:
            return True
        if cls.relogio() - cls.falhou_em >= cls.TTL_S:
            cls.falhou_em = None
            logger.info("traffic_report: tentando de novo as colunas do P0")
            return True
        return False

    @classmethod
    def desligar(cls) -> None:
        cls.falhou_em = cls.relogio()


def _lead_cols() -> str:
    cols = _LEAD_COLS + ", meta_ad_id" if _MetaAdCol.enabled else _LEAD_COLS
    return cols + ", " + _P0_LEAD_COLS if _P0Col.ativo() else cols


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _day_start(d: date) -> str:
    """Meia-noite de `d` no fuso de negócio, em ISO com offset."""
    return datetime.combine(d, time.min, tzinfo=_TZ).isoformat()


def _day_end(d: date) -> str:
    """Último instante de `d` no fuso de negócio, em ISO com offset."""
    return datetime.combine(d, time.max, tzinfo=_TZ).isoformat()


def _resolve_window(period: str, date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
    """Resolve a janela (lo, hi) em ISO no fuso de negócio (America/Sao_Paulo).

    `date_from`/`date_to` (YYYY-MM-DD) têm precedência sobre `period` e são lidos como o DIA
    de Brasília inteiro. Datas malformadas são ignoradas. Sem sinal → (None, None) = tudo."""
    df = (date_from or "").strip()
    dt = (date_to or "").strip()
    lo_explicit = df if _DATE_RE.match(df) else ""
    hi_explicit = dt if _DATE_RE.match(dt) else ""
    if lo_explicit or hi_explicit:
        lo = _day_start(date.fromisoformat(lo_explicit)) if lo_explicit else None
        hi = _day_end(date.fromisoformat(hi_explicit)) if hi_explicit else None
        return lo, hi
    days = _PERIOD_DAYS.get(period)
    if not days:
        return None, None
    # Dias-calendário fechados no fuso de negócio, não 24h corridas contadas de agora para
    # trás: "30d" é o que a plataforma chama de últimos 30 dias, com hoje incluído.
    return _day_start(datetime.now(_TZ).date() - timedelta(days=days - 1)), None


def _chunks(items: list, size: int = 200):
    for i in range(0, len(items), size):
        yield items[i:i + size]


_PAGE = 1000


def _fetch_all(build_query, page: int = _PAGE, ordem: str = "id") -> list[dict[str, Any]]:
    """Executa a query paginando com .range() ate a pagina vir incompleta.

    O PostgREST corta a resposta em 1.000 linhas por padrao e NAO avisa: a query volta
    "com sucesso", so que truncada. Sem isso o /trafego lia 1.000 dos 2.324 leads da janela
    de 30 dias e reportava leads, receita e ROAS sobre 43% da base.

    `ordem` e uma chave UNICA da tabela: sem ORDER BY o Postgres nao promete a mesma ordem
    entre duas consultas, e a pagina 2 pode repetir linhas da 1 e pular outras.

    `build_query` e chamado a cada pagina porque o postgrest-py acumula estado no builder."""
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        data = build_query().order(ordem).range(offset, offset + page - 1).execute().data or []
        out.extend(data)
        if len(data) < page:
            return out
        offset += page


def _select_leads(fetch) -> list[dict[str, Any]]:
    """Roda `fetch(cols)` degradando as colunas de migration ainda não aplicada."""
    cols = _lead_cols()
    try:
        return fetch(cols)
    except Exception as exc:
        if _P0_LEAD_COLS in cols and any(m in str(exc) for m in _P0_COL_MARKERS):
            logger.warning("traffic_report: colunas do P0 ausentes (%s) - migration 20261006 pendente?"
                           " Nova tentativa em %.0f s.", exc, _P0Col.TTL_S)
            _P0Col.desligar()
            return _select_leads(fetch)
        # A coluna meta_ad_id vem de migration; se ela ainda nao foi aplicada o PostgREST
        # rejeita o select inteiro. Degrada para o conjunto base (perde so a atribuicao de
        # campanha do Meta) em vez de zerar o relatorio.
        if _MetaAdCol.enabled:
            logger.warning("traffic_report: select com meta_ad_id falhou (%s) - migration pendente?", exc)
            _MetaAdCol.enabled = False
            return _select_leads(fetch)
        raise


def _fetch_leads(sb, mode: str, lo: str | None, hi: str | None, *,
                 incluir_clientes: bool = False) -> list[dict[str, Any]]:
    """Leads da janela (modo lead) ou compradores da janela (modo venda).

    Modo lead = D1 (b67f1c6b): sem importados e sem quem já era cliente. `incluir_clientes`
    mantém quem já era cliente (o drill-down mostra a coluna "já era cliente")."""
    if mode == "sale":
        def _sales_q():
            q = sb.table("sales").select("lead_id, status")
            if lo:
                q = q.gte("sold_at", lo)
            if hi:
                q = q.lte("sold_at", hi)
            return q
        sale_ids = sorted({r["lead_id"] for r in _fetch_all(_sales_q)
                           if r.get("lead_id") and not _cancelada(r)})

        def _por_venda(cols):
            leads: list[dict[str, Any]] = []
            for chunk in _chunks(sale_ids):
                leads.extend(_fetch_all(lambda c=chunk: sb.table("leads").select(cols).in_("id", c)))
            return leads
        return _select_leads(_por_venda)

    def _por_janela(cols):
        def _q():
            q = sb.table("leads").select(cols)
            if lo:
                q = q.gte("created_at", lo)
            if hi:
                q = q.lte("created_at", hi)
            return q
        return _fetch_all(_q)
    return [l for l in _select_leads(_por_janela) if _lead_de_marketing(l, incluir_clientes)]


def _lead_de_marketing(lead: dict[str, Any], incluir_clientes: bool = False) -> bool:
    """D1 (b67f1c6b): importado e quem já era cliente não são "Leads" do relatório. Só no modo
    lead — no modo venda a venda deles continua sendo venda."""
    if _s(lead.get("origem_cadastro")).lower() in _ORIGENS_IMPORTADAS:
        return False
    return incluir_clientes or lead.get("ja_era_cliente") is not True


def _conversed_ids(sb, lead_ids: list[str]) -> set[str]:
    out: set[str] = set()
    for chunk in _chunks(lead_ids):
        rows = _fetch_all(lambda c=chunk: sb.table("conversations")
                          .select("lead_id, last_customer_message_at").in_("lead_id", c))
        for r in rows:
            if r.get("last_customer_message_at") and r.get("lead_id"):
                out.add(r["lead_id"])
    return out


def _closer_ids(sb, lead_ids: list[str]) -> set[str]:
    """D3: closer = lead da coorte com evento lead_events 'repasse' (1º repasse ao closer).
    Não olha etapa de deal: 'perdido' não é closer e os funis do João (sem key
    'qualificado') contam normalmente."""
    out: set[str] = set()
    for chunk in _chunks(lead_ids):
        rows = _fetch_all(lambda c=chunk: sb.table("lead_events").select("id, lead_id")
                          .in_("lead_id", c).eq("event_type", "repasse"))
        out.update(r["lead_id"] for r in rows if r.get("lead_id"))
    return out


# D10 (cartão 1e6381fe): no modo lead, a venda só conta se o dia dela (Brasília) cair entre o
# dia de entrada do lead (created_at, a mesma data que põe o lead na janela) e entrada + 30 dias
# (B2C) ou + 90 dias (B2B). Limites inclusivos.
_JANELA_B2C_DIAS = 30
_JANELA_B2B_DIAS = 90


def _lead_b2b(sb, lead: dict[str, Any], cache: dict[str, bool]) -> bool:
    """D9: B2B = mesma regra de `public.fn_lead_b2b` (supabase/migrations/20261022b_segmento.sql):
    segmento atacado/private_label, OU deal em funil Atacado/Private Label, OU contato Bling com
    CNPJ. O segmento já vem no select dos leads; o resto é a própria rpc, chamada só para quem
    tem venda entre o dia 31 e o 90 (o único caso em que B2B muda o resultado).
    Fail-soft: erro na rpc vira B2C (janela menor) e loga."""
    lid = lead.get("id")
    if lid in cache:
        return cache[lid]
    if normalizar_segmento(lead.get("segmento")) in SEGMENTOS_B2B:
        cache[lid] = True
        return True
    try:
        b2b = bool(sb.rpc("fn_lead_b2b", {"p_lead": lid}).execute().data)
    except Exception as exc:
        logger.warning("traffic_report: rpc fn_lead_b2b falhou para o lead %s: %s", lid, exc)
        b2b = False
    cache[lid] = b2b
    return b2b


def _venda_na_janela_d10(sb, sale: dict[str, Any], lead: dict[str, Any] | None,
                         cache_b2b: dict[str, bool]) -> bool:
    if lead is None:
        return False
    entrada = _local_day(lead.get("created_at"))
    dia = _local_day(sale.get("sold_at"))
    if entrada is None or dia is None:
        return False
    dias = (dia - entrada).days
    if dias < 0:
        return False
    if dias <= _JANELA_B2C_DIAS:
        return True
    return dias <= _JANELA_B2B_DIAS and _lead_b2b(sb, lead, cache_b2b)


def _vendas_que_contam(sb, rows: list[dict[str, Any]], mode: str,
                       leads_por_id: dict[str, dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Tira as canceladas e, no modo lead com `leads_por_id`, as fora da janela D10."""
    cache_b2b: dict[str, bool] = {}
    out = []
    for r in rows:
        if _cancelada(r):
            continue
        if mode != "sale" and leads_por_id is not None and not _venda_na_janela_d10(
                sb, r, leads_por_id.get(r.get("lead_id")), cache_b2b):
            continue
        out.append(r)
    return out


def _sales_by_lead(sb, lead_ids: list[str], lo: str | None, hi: str | None, mode: str, *,
                   leads_por_id: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """lead_id -> {count, value (receita sem frete, D7), frete, first/last_sold_at}.

    Modo venda: recorta pela janela do relatório. Modo lead com `leads_por_id`: janela D10 a
    partir da entrada de cada lead. Sem `leads_por_id`: vida inteira (coluna "Compras")."""
    out: dict[str, dict[str, Any]] = {}
    for chunk in _chunks(lead_ids):
        def _q(c=chunk):
            q = sb.table("sales").select("lead_id, value, freight, sold_at, status").in_("lead_id", c)
            if mode == "sale" and lo:
                q = q.gte("sold_at", lo)
            if mode == "sale" and hi:
                q = q.lte("sold_at", hi)
            return q
        for r in _vendas_que_contam(sb, _fetch_all(_q), mode, leads_por_id):
            lid = r.get("lead_id")
            if not lid:
                continue
            agg = out.setdefault(lid, {"count": 0, "value": 0.0, "frete": 0.0,
                                        "last_sold_at": None, "first_sold_at": None})
            agg["count"] += 1
            agg["value"] = round(agg["value"] + receita_da_venda(r), 2)
            agg["frete"] = round(agg["frete"] + frete_da_venda(r), 2)
            # Track latest sale date via ISO string comparison (safe for ISO 8601 timestamps).
            sold_at = r.get("sold_at")
            if isinstance(sold_at, str) and sold_at:
                prev = agg["last_sold_at"]
                if prev is None or sold_at > prev:
                    agg["last_sold_at"] = sold_at
                first = agg["first_sold_at"]
                if first is None or sold_at < first:
                    agg["first_sold_at"] = sold_at
    return out


def _leads_por_id(leads: list[dict[str, Any]], mode: str) -> dict[str, dict[str, Any]] | None:
    """Mapa para a janela D10: só no modo lead (no modo venda a janela é a do relatório)."""
    if mode == "sale":
        return None
    return {l["id"]: l for l in leads if l.get("id")}


def _empty_report(mode: str, period: str, atribuicao: str = "ultima") -> dict[str, Any]:
    report = {"mode": mode, "period": period, "rows": [], "channel_subtotals": {},
              "total": {"leads": 0, "conversas": 0, "closer": 0, "clientes": 0, "pedidos": 0,
                        "receita": 0.0, "frete": 0.0, "investimento": 0.0, "roas": None}}
    report["summary"] = build_report_summary(report, [], {})
    vazio = {k: report[k] for k in _CHAVES_ATRIBUICAO if k in report}
    report["atribuicao"] = atribuicao
    report["por_atribuicao"] = {a: vazio for a in ATRIBUICOES}
    report["jornadas"] = build_jornadas([], {})
    report["sem_rastreio"] = {"leads": 0, "motivos": []}
    return report


# --- Jornada: I/O (fail-soft) -------------------------------------------------------------
_CHAVES_ATRIBUICAO = ("rows", "total", "channel_subtotals", "summary", "entraram_ja_clientes")
# Colunas de vw_lead_contexto_canal (migração 20261106_f5_jornada).
_CONTEXTO_COLS = ("tem_inbound", "cliente_antigo", "numero_antigo")


def _entradas_por_lead(sb, lead_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """lead_id -> entradas (toques) da linha do tempo. Fail-soft: {} = todo lead "estimado"."""
    out: dict[str, list[dict[str, Any]]] = {}
    try:
        for chunk in _chunks(lead_ids):
            rows = _fetch_all(lambda c=chunk: sb.table("lead_events")
                              .select("id, lead_id, occurred_at, new_value, source, metadata")
                              .in_("lead_id", c).eq("event_type", "entrada"))
            for r in rows:
                if r.get("lead_id"):
                    out.setdefault(r["lead_id"], []).append(r)
    except Exception as exc:
        logger.warning("traffic_report: entradas da linha do tempo indisponíveis: %s", exc)
        return {}
    return out


def _com_contexto(sb, leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cópias dos leads com tem_inbound/cliente_antigo/numero_antigo (vw_lead_contexto_canal).

    Fail-soft: sem a view (migração pendente) os leads voltam sem contexto e os canais ficam só
    pelas colunas (WhatsApp direto / Cadastro manual / Importado / Sem rastreio)."""
    ids = [l["id"] for l in leads if l.get("id")]
    ctx: dict[str, dict[str, Any]] = {}
    try:
        for chunk in _chunks(ids):
            rows = _fetch_all(lambda c=chunk: sb.table("vw_lead_contexto_canal")
                              .select("lead_id, " + ", ".join(_CONTEXTO_COLS))
                              .in_("lead_id", c), ordem="lead_id")
            for r in rows:
                if r.get("lead_id"):
                    ctx[r["lead_id"]] = {k: r.get(k) for k in _CONTEXTO_COLS}
    except Exception as exc:
        logger.warning("traffic_report: vw_lead_contexto_canal indisponível (migração F5 pendente?): %s", exc)
        ctx = {}
    return [{**l, **ctx.get(l.get("id"), {})} for l in leads]


def _repasse_em(sb, lead_ids: list[str]) -> dict[str, str]:
    """lead_id -> 1º repasse (ISO). Corte da última origem de quem não comprou. Fail-soft."""
    out: dict[str, str] = {}
    try:
        for chunk in _chunks(lead_ids):
            rows = _fetch_all(lambda c=chunk: sb.table("lead_events").select("id, lead_id, occurred_at")
                              .in_("lead_id", c).eq("event_type", "repasse"))
            for r in rows:
                lid, em = r.get("lead_id"), r.get("occurred_at")
                if lid and isinstance(em, str) and (lid not in out or em < out[lid]):
                    out[lid] = em
    except Exception as exc:
        logger.warning("traffic_report: repasses indisponíveis: %s", exc)
    return out


def _multicanal_ids(entradas: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Leads cujos toques têm mais de um canal: só neles o corte (venda/repasse) muda algo."""
    return sorted(lid for lid, es in entradas.items()
                  if len({canal_da_entrada(e) for e in es}) > 1)


def _atribuir_leads(sb, leads: list[dict[str, Any]], atribuicoes: tuple[str, ...], mode: str,
                    lo: str | None, hi: str | None,
                    sales: dict[str, dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    """{atribuicao: leads atribuídos}. `leads` já com contexto.

    O corte da última origem é a venda (a última do recorte), senão o 1º repasse, senão o fim da
    janela. Venda e repasse só são buscados para quem tem toques de mais de um canal."""
    ids = [l["id"] for l in leads if l.get("id")]
    entradas = _entradas_por_lead(sb, ids)
    multi = _multicanal_ids(entradas)
    if multi and sales is None:
        multi_set = set(multi)
        sel = [l for l in leads if l.get("id") in multi_set]
        sales = _sales_by_lead(sb, multi, lo, hi, mode, leads_por_id=_leads_por_id(sel, mode))
    sales = sales or {}
    repasse = _repasse_em(sb, multi) if multi else {}

    def _ate(l):
        sale = sales.get(l.get("id")) or {}
        return sale.get("last_sold_at") or repasse.get(l.get("id")) or hi

    return {a: [atribuir_lead(l, entradas.get(l.get("id"), []), a, _ate(l)) for l in leads]
            for a in atribuicoes}


def _atribuicao_valida(atribuicao: str | None) -> str:
    return atribuicao if atribuicao in ATRIBUICOES else "ultima"


def resumo_sem_rastreio(leads: list[dict[str, Any]]) -> dict[str, Any]:
    """Quantos sobraram em "Sem rastreio" e por quê (cartão C item 4). Puro."""
    motivos: dict[str, int] = {}
    for l in leads:
        m = motivo_sem_rastreio(l)
        if m:
            motivos[m] = motivos.get(m, 0) + 1
    lista = sorted(({"motivo": m, "leads": n} for m, n in motivos.items()),
                   key=lambda d: (-d["leads"], d["motivo"]))
    return {"leads": sum(motivos.values()), "motivos": lista}


def _spend_by_campaign(sb, lo: str | None, hi: str | None, platform: str = "google") -> list[dict[str, Any]]:
    """Gasto de ad_spend agregado por CAMPANHA (id), na janela. Fail-soft -> [].

    Devolve [{campaign_id, campaign_name, cost}] em vez de {nome: custo} porque o relatorio
    ancora as linhas no campaign_id: e o id que garante que o custo entre uma vez so."""
    try:
        def _q():
            q = sb.table("ad_spend").select("campaign_id, campaign_name, cost, date").eq("platform", platform)
            if lo:
                q = q.gte("date", lo[:10])
            if hi:
                q = q.lte("date", hi[:10])
            return q
        agg: dict[str, dict[str, Any]] = {}
        for r in _fetch_all(_q):
            name = (r.get("campaign_name") or "").strip()
            if not name:
                continue
            cid = str(r.get("campaign_id") or "") or "name:" + name.lower()
            slot = agg.setdefault(cid, {"campaign_id": cid, "campaign_name": name, "cost": 0.0})
            try:
                slot["cost"] += float(r.get("cost") or 0.0)
            except (TypeError, ValueError):
                pass
        return list(agg.values())
    except Exception as exc:
        logger.error("_spend_by_campaign falhou: %s", exc)
        return []


def _spend_by_channel(sb, lo: str | None, hi: str | None) -> dict[str, list[dict[str, Any]]]:
    return {
        "Google Ads": _spend_by_campaign(sb, lo, hi, "google"),
        "Meta Ads": _spend_by_campaign(sb, lo, hi, "meta"),
    }


def _meta_campaign_by_lead(sb, leads: list[dict[str, Any]]) -> dict[str, str]:
    """lead_id -> campaign_id do Meta, via o anuncio (meta_ad_id) que trouxe o lead.

    O webhook CTWA nao diz a campanha, so o anuncio (referral.source_id); o mapa
    anuncio->campanha vem do sync do Meta Ads. Sem esse elo os leads de CTWA nao tem
    utm_campaign nenhum e ficariam todos em "(nao atribuido)". Fail-soft -> {}."""
    ad_ids = sorted({_s(l.get("meta_ad_id")) for l in leads if _s(l.get("meta_ad_id"))})
    if not ad_ids:
        return {}
    try:
        camp_by_ad: dict[str, str] = {}
        for chunk in _chunks(ad_ids):
            rows = _fetch_all(lambda c=chunk: sb.table("meta_ad_campaigns")
                              .select("ad_id, campaign_id").in_("ad_id", c), ordem="ad_id")
            for r in rows:
                if r.get("ad_id") and r.get("campaign_id"):
                    camp_by_ad[str(r["ad_id"])] = str(r["campaign_id"])
        out: dict[str, str] = {}
        for l in leads:
            cid = camp_by_ad.get(_s(l.get("meta_ad_id")))
            if cid and l.get("id"):
                out[l["id"]] = cid
        return out
    except Exception as exc:
        logger.warning("_meta_campaign_by_lead falhou (migration pendente?): %s", exc)
        return {}


def select_campaign_leads(leads: list[dict[str, Any]], channel: str, campaign: str,
                         campaigns: dict[str, dict[str, Any]] | None = None,
                         campaign_id_by_lead: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Leads de UMA linha do relatorio. Puro.

    O rotulo da linha e o nome da campanha NA PLATAFORMA, nao o utm_campaign do lead (varios
    slugs caem na mesma campanha). Entao o drill-down precisa resolver o lead do mesmo jeito
    que o build_campaign_report resolveu — comparar com utm_campaign cru so acharia zero.
    A atribuicao manual vence, como em build_campaign_report."""
    campaigns = campaigns or {}
    campaign_id_by_lead = campaign_id_by_lead or {}
    in_channel = [l for l in leads if lead_channel(l) == channel]

    def _manual_label(l):
        _, cid, nome = manual_attribution(l)
        return campaigns[cid]["name"] if cid in campaigns else nome

    auto = [l for l in in_channel if manual_attribution(l) is None]
    auto_ids = {id(l) for l in _select_auto(auto, campaign, campaigns, campaign_id_by_lead)}
    return [l for l in in_channel
            if (_manual_label(l) == campaign if manual_attribution(l) else id(l) in auto_ids)]


def _select_auto(in_channel, campaign, campaigns, campaign_id_by_lead):
    """Leads SEM atribuição manual de uma linha — o casamento por anúncio/UTM de sempre."""
    if not campaigns:  # canal nao pago: a linha e o proprio utm_campaign
        return [l for l in in_channel if (_s(l.get("utm_campaign")) or _NO_CAMPAIGN) == campaign]

    def _resolve(l):
        cid = _s(l.get("_campanha_id")) or campaign_id_by_lead.get(l.get("id"))
        if cid and cid in campaigns:
            return cid
        return resolve_campaign_id(_s(l.get("utm_campaign")), _s(l.get("utm_medium")), campaigns)

    if campaign.startswith(_UNATTRIBUTED):
        # "(nao atribuido) - slug" ou "(nao atribuido)" puro: sobras daquele slug.
        sufixo = campaign[len(_UNATTRIBUTED):].lstrip(" \u00b7").strip().lower()
        return [l for l in in_channel
                if _resolve(l) is None and _s(l.get("utm_campaign")).lower() == sufixo]

    target = next((cid for cid, c in campaigns.items() if c["name"] == campaign), None)
    if target is None:
        # Linha antiga/rotulo desconhecido: cai no comportamento legado por utm_campaign.
        return [l for l in in_channel if (_s(l.get("utm_campaign")) or _NO_CAMPAIGN) == campaign]
    return [l for l in in_channel if _resolve(l) == target]


def _empty_summary(channel: str, campaign: str) -> dict[str, Any]:
    return {"channel": channel, "campaign": campaign, "leads": 0, "conversas": 0, "closer": 0,
            "clientes": 0, "pedidos": 0, "receita": 0.0, "frete": 0.0, "ticket_medio": 0.0, "conversao": 0.0,
            "investimento": 0.0, "roas": None}


def _local_day(iso: Any) -> "date | None":
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_TZ).date()
    except (ValueError, TypeError):
        return None


def _daterange_days(lo: str | None, hi: str | None, max_days: int = 92) -> list[date]:
    end = _local_day(hi) or datetime.now(_TZ).date()
    start = _local_day(lo) or (end - timedelta(days=29))
    if (end - start).days + 1 > max_days:
        start = end - timedelta(days=max_days - 1)
    days: list[date] = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    return days


def build_campaign_timeseries(days: list[date], leads: list[dict[str, Any]],
                              sales_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Série diária: leads por created_at, vendas/receita por sold_at. Dias sem evento = 0. Puro."""
    idx = {d.isoformat(): {"date": d.isoformat(), "leads": 0, "vendas": 0, "receita": 0.0} for d in days}
    for l in leads:
        d = _local_day(l.get("created_at"))
        if d is not None and d.isoformat() in idx:
            idx[d.isoformat()]["leads"] += 1
    for s in sales_rows:
        d = _local_day(s.get("sold_at"))
        if d is not None and d.isoformat() in idx:
            idx[d.isoformat()]["vendas"] += 1
            try:
                idx[d.isoformat()]["receita"] += receita_da_venda(s)
            except (TypeError, ValueError):
                pass
    for v in idx.values():
        v["receita"] = round(v["receita"], 2)
    return list(idx.values())


def _parte_da_campanha(sb, channel: str, campaign: str, mode: str, period: str,
                       lo: str | None, hi: str | None, spend, atribuicao: str = "ultima"):
    """(linha do relatório, leads selecionados, vendas que contam) de UMA campanha num modo puro.

    F5: os leads entram atribuídos pelo toque escolhido (`atribuicao`), como no relatório."""
    all_leads = _atribuir_leads(sb, _com_contexto(sb, _fetch_leads(sb, mode, lo, hi)),
                                (atribuicao,), mode, lo, hi)[atribuicao]
    camp_by_lead = _meta_campaign_by_lead(sb, all_leads)
    campaigns = _index_campaigns(spend.get(channel))
    selected = select_campaign_leads(all_leads, channel, campaign, campaigns, camp_by_lead)
    if not selected:
        return None, [], []
    lead_ids = [l["id"] for l in selected if l.get("id")]
    por_id = _leads_por_id(selected, mode)
    sales = _sales_by_lead(sb, lead_ids, lo, hi, mode, leads_por_id=por_id)
    report = build_campaign_report(selected, _conversed_ids(sb, lead_ids), _closer_ids(sb, lead_ids),
                                   sales, mode, period, spend_by_channel=spend,
                                   campaign_id_by_lead=camp_by_lead)
    with_leads = [r for r in report.get("rows") or [] if r["leads"] > 0]
    sales_rows: list[dict[str, Any]] = []
    for chunk in _chunks(lead_ids):
        def _sq(c=chunk):
            q = sb.table("sales").select("lead_id, value, freight, sold_at, status").in_("lead_id", c)
            if mode == "sale" and lo:
                q = q.gte("sold_at", lo)
            if mode == "sale" and hi:
                q = q.lte("sold_at", hi)
            return q
        sales_rows.extend(_vendas_que_contam(sb, _fetch_all(_sq), mode, por_id))
    return (with_leads[0] if with_leads else None), selected, sales_rows


def _campaign_detail_periodo(sb, channel: str, campaign: str, period: str, lo, hi,
                             date_from, date_to, atribuicao: str = "ultima") -> dict[str, Any]:
    """Detalhe no modo período: leads/closer da turma do período + vendas do período."""
    spend = _spend_by_channel(sb, lo, hi)
    linha_lead, sel_lead, _ = _parte_da_campanha(sb, channel, campaign, "lead", period, lo, hi,
                                                 spend, atribuicao)
    linha_venda, _, vendas = _parte_da_campanha(sb, channel, campaign, "sale", period, lo, hi,
                                                spend, atribuicao)
    inv = next((float(c["cost"]) for c in _index_campaigns(spend.get(channel)).values()
                if c["name"] == campaign), 0.0)
    fundida = merge_period_report(
        {"rows": [linha_lead] if linha_lead else []},
        {"rows": [linha_venda] if linha_venda else []}, period)
    summary = next((r for r in fundida["rows"] if r["channel"] == channel), None)
    if summary is None:
        summary = _empty_summary(channel, campaign)
        summary["investimento"] = round(inv, 2)
    elif not summary["investimento"] and inv:
        summary["investimento"] = round(inv, 2)
        _finalizar_linha_periodo(summary)
    summary["campaign"] = campaign
    leads = campaign_leads(channel, campaign, period, MODO_PERIODO, date_from, date_to, atribuicao)
    timeseries = build_campaign_timeseries(_daterange_days(lo, hi), sel_lead, vendas)
    return {"summary": summary, "leads": leads, "timeseries": timeseries}


def campaign_detail(channel: str, campaign: str, period: str = "30d", mode: str = MODO_PERIODO,
                    date_from: str | None = None, date_to: str | None = None,
                    atribuicao: str = "ultima") -> dict[str, Any]:
    """Detalhe de uma campanha: {summary, leads, timeseries}. Fail-soft.

    `atribuicao` (F5) escolhe o toque que põe o lead na linha, como no relatório."""
    atribuicao = _atribuicao_valida(atribuicao)
    try:
        sb = get_supabase()
        lo, hi = _resolve_window(period, date_from, date_to)
        if mode == MODO_PERIODO:
            return _campaign_detail_periodo(sb, channel, campaign, period, lo, hi, date_from,
                                            date_to, atribuicao)
        all_leads = _atribuir_leads(sb, _com_contexto(sb, _fetch_leads(sb, mode, lo, hi)),
                                    (atribuicao,), mode, lo, hi)[atribuicao]
        spend_by_channel = _spend_by_channel(sb, lo, hi)
        camp_by_lead = _meta_campaign_by_lead(sb, all_leads)
        campaigns = _index_campaigns(spend_by_channel.get(channel))
        selected = select_campaign_leads(all_leads, channel, campaign, campaigns, camp_by_lead)
        if not selected:
            return {"summary": _empty_summary(channel, campaign), "leads": [], "timeseries": []}
        lead_ids = [l["id"] for l in selected if l.get("id")]
        conversed = _conversed_ids(sb, lead_ids)
        closers = _closer_ids(sb, lead_ids)
        por_id = _leads_por_id(selected, mode)
        sales = _sales_by_lead(sb, lead_ids, lo, hi, mode, leads_por_id=por_id)
        report = build_campaign_report(
            selected, conversed, closers, sales, mode, period,
            spend_by_channel=spend_by_channel, campaign_id_by_lead=camp_by_lead,
        )
        # So a linha DESTA campanha interessa: as demais linhas vem das campanhas que
        # gastaram na janela sem lead selecionado (ver build_campaign_report).
        with_leads = [r for r in report.get("rows") or [] if r["leads"] > 0]
        summary = with_leads[0] if with_leads else _empty_summary(channel, campaign)
        leads = campaign_leads(channel, campaign, period, mode, date_from, date_to, atribuicao)
        sales_rows: list[dict[str, Any]] = []
        for chunk in _chunks(lead_ids):
            def _sq(c=chunk):
                q = sb.table("sales").select("lead_id, value, freight, sold_at, status").in_("lead_id", c)
                if mode == "sale" and lo:
                    q = q.gte("sold_at", lo)
                if mode == "sale" and hi:
                    q = q.lte("sold_at", hi)
                return q
            sales_rows.extend(_vendas_que_contam(sb, _fetch_all(_sq), mode, por_id))
        timeseries = build_campaign_timeseries(_daterange_days(lo, hi), selected, sales_rows)
        return {"summary": summary, "leads": leads, "timeseries": timeseries}
    except Exception as exc:
        logger.error("campaign_detail(%s,%s) falhou: %s", channel, campaign, exc, exc_info=True)
        return {"summary": _empty_summary(channel, campaign), "leads": [], "timeseries": []}


def _report_do_modo(sb, mode: str, period: str, lo: str | None, hi: str | None,
                    spend: dict[str, list[dict[str, Any]]]):
    """({atribuição: relatório}, {atribuição: leads atribuídos}, vendas por lead) de um modo puro
    ("lead" ou "sale"). F5: o mesmo conjunto de leads, atribuído pela última e pela primeira origem."""
    leads = _fetch_leads(sb, mode, lo, hi)
    lead_ids = [l["id"] for l in leads if l.get("id")]
    conversed = _conversed_ids(sb, lead_ids) if lead_ids else set()
    closers = _closer_ids(sb, lead_ids) if lead_ids else set()
    sales = (_sales_by_lead(sb, lead_ids, lo, hi, mode, leads_por_id=_leads_por_id(leads, mode))
             if lead_ids else {})
    por = (_atribuir_leads(sb, _com_contexto(sb, leads), ATRIBUICOES, mode, lo, hi, sales=sales)
           if lead_ids else {a: [] for a in ATRIBUICOES})
    reps = {a: build_campaign_report(ls, conversed, closers, sales, mode, period,
                                     spend_by_channel=spend,
                                     campaign_id_by_lead=_meta_campaign_by_lead(sb, ls))
            for a, ls in por.items()}
    return reps, por, sales


def _juntar_atribuicoes(partes: dict[str, dict[str, Any]],
                        leads_por_atribuicao: dict[str, list[dict[str, Any]]],
                        sales: dict[str, dict[str, Any]], atribuicao: str) -> dict[str, Any]:
    """Topo na atribuição pedida + `por_atribuicao` + `jornadas` + `sem_rastreio`. Puro."""
    report = dict(partes[atribuicao])
    report["atribuicao"] = atribuicao
    report["por_atribuicao"] = {a: {k: r[k] for k in _CHAVES_ATRIBUICAO if k in r}
                                for a, r in partes.items()}
    base = leads_por_atribuicao.get("ultima") or next(iter(leads_por_atribuicao.values()), [])
    report["jornadas"] = build_jornadas(base, sales)
    report["sem_rastreio"] = resumo_sem_rastreio(leads_por_atribuicao.get(atribuicao) or base)
    return report


def montar_relatorio_atribuido(por_atribuicao: dict[str, list[dict[str, Any]]],
                               conversed: set[str], closers: set[str],
                               sales: dict[str, dict[str, Any]], mode: str, period: str,
                               atribuicao: str = "ultima",
                               spend_by_channel: dict[str, Any] | None = None,
                               campaign_id_by_lead: dict[str, dict[str, str]] | None = None,
                               ) -> dict[str, Any]:
    """Relatório de um modo puro nas duas atribuições + jornadas + "Sem rastreio". Puro.

    `por_atribuicao` = {"ultima": leads atribuídos, "primeira": ...} (mesmos leads, rastreio do
    toque escolhido). As linhas e subtotais mudam; os totais de leads, vendas e receita não,
    porque cada lead cai em exatamente uma linha nas duas. O topo do relatório é a atribuição
    pedida (padrão: última, como a Tati trabalha)."""
    campaign_id_by_lead = campaign_id_by_lead or {}
    partes: dict[str, dict[str, Any]] = {}
    for a, leads_a in por_atribuicao.items():
        rep = build_campaign_report(leads_a, conversed, closers, sales, mode, period,
                                    spend_by_channel=spend_by_channel,
                                    campaign_id_by_lead=campaign_id_by_lead.get(a))
        rep["summary"] = build_report_summary(rep, leads_a, sales)
        partes[a] = rep
    return _juntar_atribuicoes(partes, por_atribuicao, sales, atribuicao)


def montar_relatorio_periodo(lead_reps: dict[str, dict[str, Any]],
                             lead_por: dict[str, list[dict[str, Any]]],
                             sale_reps: dict[str, dict[str, Any]],
                             sale_por: dict[str, list[dict[str, Any]]],
                             vendas: dict[str, dict[str, Any]], period: str,
                             atribuicao: str = "ultima") -> dict[str, Any]:
    """Modo período nas duas atribuições. Puro.

    Em cada atribuição funde a turma do período (por lead) com as vendas do período (por venda),
    como merge_period_report. Jornadas e "Sem rastreio" olham os dois grupos sem repetir lead."""
    partes: dict[str, dict[str, Any]] = {}
    juntos: dict[str, list[dict[str, Any]]] = {}
    for a in ATRIBUICOES:
        rep = merge_period_report(lead_reps.get(a) or {}, sale_reps.get(a) or {}, period)
        # Tempo até a compra e recompra: sobre quem comprou no período.
        rep["summary"] = build_report_summary(rep, sale_por.get(a) or [], vendas)
        partes[a] = rep
        vistos: set = set()
        juntos[a] = []
        for l in (lead_por.get(a) or []) + (sale_por.get(a) or []):
            if l.get("id") not in vistos:
                vistos.add(l.get("id"))
                juntos[a].append(l)
    return _juntar_atribuicoes(partes, juntos, vendas, atribuicao)


def traffic_report(period: str = "30d", mode: str = MODO_PERIODO,
                   date_from: str | None = None, date_to: str | None = None,
                   atribuicao: str = "ultima") -> dict[str, Any]:
    """Relatório agregado por canal+campanha. Fail-soft: qualquer erro → relatório vazio.

    F5: devolve as duas atribuições (`por_atribuicao`), para a tela trocar sem nova consulta, o
    bloco `jornadas` e o detalhe `sem_rastreio`."""
    atribuicao = _atribuicao_valida(atribuicao)
    try:
        sb = get_supabase()
        lo, hi = _resolve_window(period, date_from, date_to)
        spend = _spend_by_channel(sb, lo, hi)
        if mode == MODO_PERIODO:
            lead_reps, lead_por, _ = _report_do_modo(sb, "lead", period, lo, hi, spend)
            sale_reps, sale_por, vendas = _report_do_modo(sb, "sale", period, lo, hi, spend)
            return montar_relatorio_periodo(lead_reps, lead_por, sale_reps, sale_por, vendas,
                                            period, atribuicao)
        reps, por, sales = _report_do_modo(sb, mode, period, lo, hi, spend)
        if not por.get("ultima"):
            return _empty_report(mode, period, atribuicao)
        for a, rep in reps.items():
            rep["summary"] = build_report_summary(rep, por[a], sales)
        return _juntar_atribuicoes(reps, por, sales, atribuicao)
    except Exception as exc:
        logger.error("traffic_report(%s,%s) falhou: %s", period, mode, exc, exc_info=True)
        return _empty_report(mode, period, atribuicao)


def _primeira_origem(sb, lead_ids: list[str]) -> dict[str, dict[str, Any]]:
    """lead_id -> primeira entrada registrada (view lead_primeira_origem do P0, enchida pelo P3).

    Fail-soft: sem a migração a view não existe e a coluna cai no canal atual na tela."""
    try:
        out: dict[str, dict[str, Any]] = {}
        for chunk in _chunks(lead_ids):
            rows = _fetch_all(lambda c=chunk: sb.table("lead_primeira_origem")
                              .select("lead_id, canal, campanha_id, campanha_nome, occurred_at")
                              .in_("lead_id", c), ordem="lead_id")  # view: 1 linha por lead
            for r in rows:
                if r.get("lead_id"):
                    out[r["lead_id"]] = {k: r.get(k) for k in
                                         ("canal", "campanha_id", "campanha_nome", "occurred_at")}
        return out
    except Exception as exc:
        logger.warning("lead_primeira_origem indisponível (migration 20261006 pendente?): %s", exc)
        return {}


def _jornada_publica(j: dict[str, Any] | None) -> dict[str, Any] | None:
    """A jornada sem os objetos internos, pronta para o JSON do drill-down."""
    if not j:
        return None
    return {k: j.get(k) for k in ("primeira_origem", "primeira_em", "ultima_origem", "ultima_em",
                                  "origens", "toques", "n_toques", "multicanal", "estimado")}


def _stage_info_map(sb) -> dict[str, dict[str, Any]]:
    stages = _fetch_all(lambda: sb.table("pipeline_stages").select("id, key, order_index"))
    return {s["id"]: {"key": s.get("key"), "order_index": s.get("order_index")} for s in stages}


def campaign_leads(channel: str, campaign: str, period: str = "30d", mode: str = "lead",
                   date_from: str | None = None, date_to: str | None = None,
                   atribuicao: str = "ultima") -> list[dict[str, Any]]:
    """Leads de uma campanha (canal+utm_campaign) p/ o drill-down. Fail-soft: [] em erro.

    F5: cada lead traz a `jornada` ("Passou por", com as datas) e, em "Sem rastreio", o
    `motivo_sem_rastreio`."""
    atribuicao = _atribuicao_valida(atribuicao)
    try:
        sb = get_supabase()
        lo, hi = _resolve_window(period, date_from, date_to)
        campaigns = _index_campaigns(_spend_by_channel(sb, lo, hi).get(channel))

        def _sel(m: str) -> list[dict[str, Any]]:
            ls = _fetch_leads(sb, m, lo, hi, incluir_clientes=True)
            # F5: o lead entra atribuído pelo toque escolhido, como no relatório.
            ls = _atribuir_leads(sb, _com_contexto(sb, ls), (atribuicao,), m, lo, hi)[atribuicao]
            return select_campaign_leads(ls, channel, campaign, campaigns, _meta_campaign_by_lead(sb, ls))

        if mode == MODO_PERIODO:
            # Quem entrou no período + quem comprou no período (lead novo ou antigo), sem repetir.
            entraram = _sel("lead")
            ids_entraram = {l.get("id") for l in entraram}
            selected = entraram + [l for l in _sel("sale") if l.get("id") not in ids_entraram]
        else:
            ids_entraram = None
            selected = _sel(mode)
        if not selected:
            return []
        lead_ids = [l["id"] for l in selected if l.get("id")]
        conversed = _conversed_ids(sb, lead_ids)
        # No período, "comprou" = comprou DENTRO do período (venda pela data da venda).
        modo_venda = "sale" if mode == MODO_PERIODO else mode
        sales = _sales_by_lead(sb, lead_ids, lo, hi, modo_venda,
                               leads_por_id=_leads_por_id(selected, modo_venda))
        # "Compras" é a vida inteira do lead: `sales` vem recortado (janela do modo venda ou D10).
        compras = _sales_by_lead(sb, lead_ids, None, None, "lead")
        origem = _primeira_origem(sb, lead_ids)
        stage_info = _stage_info_map(sb)
        deals = []
        for chunk in _chunks(lead_ids):
            deals.extend(_fetch_all(lambda c=chunk: sb.table("deals")
                                    .select("lead_id, stage_id, created_at").in_("lead_id", c)))
        # Estágio mais avançado (maior order_index) por lead — consistente com a lógica do closer.
        best_idx: dict[str, int] = {}
        furthest_stage: dict[str, str] = {}
        for d in deals:
            lid = d.get("lead_id")
            if not lid:
                continue
            info = stage_info.get(d.get("stage_id"))
            if not info:
                continue
            oi = info.get("order_index")
            oi_val = oi if isinstance(oi, int) else -1  # None/ausente => menor prioridade
            if lid not in best_idx or oi_val > best_idx[lid]:
                best_idx[lid] = oi_val
                furthest_stage[lid] = info.get("key")
        out: list[dict[str, Any]] = []
        for l in selected:
            lid = l["id"]
            sale = sales.get(lid)
            manual = manual_attribution(l)
            out.append({
                "lead_id": lid, "name": l.get("name"), "phone": l.get("phone"),
                "created_at": l.get("created_at"), "utm_source": l.get("utm_source"),
                "utm_medium": l.get("utm_medium"), "utm_campaign": l.get("utm_campaign"),
                "traffic_type": l.get("traffic_type"), "conversou": lid in conversed,
                "stage": furthest_stage.get(lid),
                # mesma regra de leads.service.segmento_do_lead: segmento, senão o stage antigo
                "segmento": normalizar_segmento(l.get("segmento")) or normalizar_segmento(l.get("stage")),
                "comprou": bool(sale), "valor": float(sale["value"]) if sale else 0.0,
                "sold_at": sale.get("last_sold_at") if sale else None,
                "canal": lead_channel(l),
                "atribuicao_manual": manual is not None,
                "campanha_manual_canal": _s(l.get("campanha_manual_canal")).lower() if manual else None,
                "campanha_manual_id": manual[1] if manual else None,
                "campanha_manual_nome": manual[2] if manual else None,
                "ja_era_cliente": l.get("ja_era_cliente"),
                "ja_era_cliente_fonte": l.get("ja_era_cliente_fonte"),
                "compras": int((compras.get(lid) or {}).get("count", 0) or 0),
                "primeira_origem": origem.get(lid),
                # None fora do modo período; False = lead antigo que só comprou no período
                "entrou_no_periodo": (lid in ids_entraram) if ids_entraram is not None else None,
                "jornada": _jornada_publica(l.get("_jornada")),
                "motivo_sem_rastreio": motivo_sem_rastreio(l),
            })
        out.sort(key=lambda r: (not r["comprou"], r.get("created_at") or ""), reverse=False)
        return out
    except Exception as exc:
        logger.error("campaign_leads(%s,%s) falhou: %s", channel, campaign, exc, exc_info=True)
        return []

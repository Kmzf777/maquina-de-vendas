"""Detalhe de campanha do /trafego pela PRIMEIRA ou pela ÚLTIMA origem do lead (F5, cartão B).

O relatório geral (`GET /api/traffic/report`) já devolve as duas atribuições em `por_atribuicao`,
e a tela troca sem nova consulta. O detalhe de uma linha precisa saber qual atribuição pôs o lead
ali; como o traffic_router é de outra frente (F1: login e modo padrão), este router separado
recebe o `atribuicao`. Exige o JWT de admin desde o primeiro dia (o detalhe traz nome e telefone).
"""
from fastapi import APIRouter, Depends

from app.campaigns.traffic_report import ATRIBUICOES, campaign_detail
from app.campaigns.traffic_router import MODO_PADRAO, _modo, exigir_admin

router = APIRouter(prefix="/api/traffic/jornada", tags=["traffic"])


@router.get("/campaign")
def jornada_campaign_endpoint(channel: str, campaign: str, period: str = "30d", mode: str = MODO_PADRAO,
                              date_from: str | None = None, date_to: str | None = None,
                              atribuicao: str = "ultima", _admin: str = Depends(exigir_admin)):
    """KPIs + leads (com "Passou por") + série de uma linha do relatório na atribuição pedida."""
    mode = _modo(mode)  # mesmo padrão e validação do traffic_router ("periodo")
    atribuicao = atribuicao if atribuicao in ATRIBUICOES else "ultima"
    return campaign_detail(channel=channel, campaign=campaign, period=period, mode=mode,
                           date_from=date_from, date_to=date_to, atribuicao=atribuicao)

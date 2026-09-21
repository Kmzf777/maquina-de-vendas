import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone

from app.campaigns.service import (
    list_campaigns, get_campaign, create_campaign, update_campaign, delete_campaign,
    list_nodes, create_node, update_node, delete_node,
    list_enrollments, create_enrollment, update_enrollment, cancel_enrollment, pause_enrollment,
    is_already_enrolled,
)
from app.campaigns.execution_log import list_execution_log
# Critério canônico do bloqueio (leads.opt_out OU card no funil Blacklist), direto da
# origem — o mesmo que o worker da esteira usa antes de cada envio.
from app.leads.service import is_lead_blacklisted

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


def _reject_system_campaign(campaign_id: str, action: str) -> None:
    """A campanha-espelho do motor de follow-up (system_cadence) é somente-leitura:
    ativá-la faria o automation engine DUPLICAR os toques que o worker de follow-up
    já envia; enroll/delete corrompem o espelho (re-sincronizado a cada deploy)."""
    from app.campaigns.system_cadence import VALERIA_CADENCE_CAMPAIGN_ID
    if campaign_id == VALERIA_CADENCE_CAMPAIGN_ID:
        raise HTTPException(
            409,
            f"Campanha de sistema (espelho do motor de follow-up) — {action} não permitido. "
            "A execução real é do worker de follow-up.",
        )


class CampaignCreate(BaseModel):
    name: str
    description: str | None = None


class NodeCreate(BaseModel):
    type: str
    config: dict = {}
    position_x: int = 0
    position_y: int = 0


class EnrollRequest(BaseModel):
    lead_id: str
    deal_id: str | None = None


# ─── Campaign CRUD ────────────────────────────────────────────────────────────

@router.get("")
async def api_list_campaigns():
    return {"data": list_campaigns()}


@router.post("")
async def api_create_campaign(body: CampaignCreate):
    return create_campaign(body.name, body.description)


# CUIDADO COM A ORDEM: esta rota estatica precisa vir ANTES de "/{campaign_id}"
# abaixo. Declarada depois, o FastAPI casaria "node-schema" como campaign_id e
# a rota nunca seria alcancada (ver test_node_schema_endpoint_2026_09_16.py::
# test_rota_estatica_vence_a_parametrizada_campaign_id).
@router.get("/node-schema")
async def api_node_schema():
    """Contrato dos nos de cadencia, para a tela renderizar os campos.

    A tela NAO mantem copia desta lista: o vocabulario de cada campo decide qual
    lista de opcoes o <select> recebe. Foi a copia hard-coded que fez o inspector
    gravar rotulo de coluna onde o motor lia segmento de lead (ver
    app/campaigns/node_registry.py).
    """
    from app.campaigns import node_registry

    return {
        "tipos": node_registry.para_json(),
        # VALORES_FIXOS e dict[str, tuple[tuple[str, str], ...]] — tupla e JSON
        # valido, mas convertida para lista aqui na fronteira do endpoint para a
        # resposta ficar em JSON puro (sem depender do jsonable_encoder do FastAPI
        # para isso). node_registry.py nao e alterado.
        "valores_fixos": {
            chave: [list(par) for par in valores]
            for chave, valores in node_registry.VALORES_FIXOS.items()
        },
    }


@router.get("/{campaign_id}")
async def api_get_campaign(campaign_id: str):
    camp = get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign não encontrada")
    nodes = list_nodes(campaign_id)
    return {**camp, "nodes": nodes}


@router.patch("/{campaign_id}")
async def api_update_campaign(campaign_id: str, body: dict):
    return update_campaign(campaign_id, **body)


@router.delete("/{campaign_id}")
async def api_delete_campaign(campaign_id: str):
    _reject_system_campaign(campaign_id, "delete")
    camp = get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign não encontrada")
    if camp["status"] not in ("draft", "archived"):
        raise HTTPException(400, "Apenas campaigns em rascunho ou arquivadas podem ser excluídas")
    delete_campaign(campaign_id)
    return {"ok": True}


@router.post("/{campaign_id}/activate")
async def api_activate_campaign(campaign_id: str):
    """Liga a campanha — e é a ÚNICA hora em que dá para pegar o fluxo quebrado.

    Até esta leva a rota conferia duas coisas (existe gatilho, o gatilho tem
    `next_node_id`). Todo o resto — template não aprovado, ciclo, condição com um ramo
    só, campo obrigatório vazio — passava, e todas essas falhas são SILENCIOSAS no
    motor: a campanha fica verde na tela e o lead não recebe nada. Quem carregava as
    outras guardas era a aba Esteiras, que só sabia validar as 4 esteiras do seed e vai
    ser aposentada. `campaigns/validation.py` generaliza aquelas regras para topologia
    qualquer; aqui a rota só busca o que a função pura não busca (campanha, nós e o
    status dos templates) e traduz o resultado em HTTP.
    """
    import logging
    from dataclasses import asdict

    from app.campaigns.validation import validar
    from app.db.supabase import get_supabase

    _reject_system_campaign(campaign_id, "activate")
    camp = get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign não encontrada")

    nodes = list_nodes(campaign_id)

    # Só os nós `send` usam template (o `send_text` manda texto livre) — consultar nome
    # de outro tipo de nó travaria a ativação por um template que nem vai ser usado.
    nomes: set[str] = set()
    for node in nodes:
        if node.get("type") != "send":
            continue
        nome = str((node.get("config") or {}).get("template_name") or "").strip()
        if nome:
            nomes.add(nome)

    # `{}` E `None` SÃO ESTADOS OPOSTOS AQUI — e confundi-los é a pior coisa que este
    # trecho pode fazer:
    #   {}   = "consultei `message_templates` e a Meta não conhece nenhum desses nomes"
    #          → a validação REPROVA (é o estado inicial deste projeto: os templates
    #            `esteira_*` que o seed referencia nunca foram submetidos);
    #   None = "não deu para consultar" (timeout/rede) → fail-open, pula SÓ a regra de
    #          template e mantém as outras 11 valendo.
    # Um `if not templates: templates = None` transformaria oscilação do Supabase em
    # ATIVAÇÃO APROVADA em silêncio — exatamente a falha que esta camada existe para
    # impedir, e a mais cara delas: template não aprovado não bloqueia a INSCRIÇÃO, só o
    # envio, então a campanha inscreve o lead, não manda nada e mesmo assim caminha até
    # a ação final, registrando "não teve resposta" para quem nunca foi contatado.
    # Por isso `None` é atribuído SOMENTE dentro do `except`, nunca a partir do tamanho
    # do mapa; e sem nome nenhum a conferir não há consulta, o que é `{}` (nada a
    # conferir) e não falha de consulta.
    templates: dict[str, str] | None = {}
    if nomes:
        try:
            linhas = (
                get_supabase().table("message_templates")
                .select("name, status").in_("name", sorted(nomes)).execute().data
            ) or []
            templates = {}
            for linha in linhas:
                nome = str(linha.get("name") or "")
                if not nome:
                    continue
                # Cada template tem uma linha-espelho POR CANAL (os canais compartilham
                # a mesma WABA) e o sync tem buracos: entre dois espelhos do mesmo nome
                # vale o APROVADO, senão um espelho desatualizado reprovaria template
                # que a Meta aprovou. Mesmo critério do `esteiras_router._nao_aprovados`.
                anterior = templates.get(nome)
                if anterior is not None and anterior.strip().lower() == "approved":
                    continue
                templates[nome] = str(linha.get("status") or "")
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "[CAMPANHAS] ativação de %s: não deu para conferir os templates %s em "
                "message_templates (%s) — regra de template PULADA (fail-open); as "
                "demais continuam valendo.",
                campaign_id, sorted(nomes), exc,
            )
            templates = None

    problemas = validar(camp, nodes, templates)
    if problemas:
        # `no_id` e `codigo` viajam junto com a mensagem porque a tela destaca o nó
        # culpado no canvas e agrupa por código — um 400 com string solta obrigaria o
        # frontend a adivinhar de qual nó se trata.
        raise HTTPException(400, detail={"problemas": [asdict(p) for p in problemas]})

    # Escrever SÓ depois de validar: ativação recusada não pode deixar a campanha meio
    # ligada (status `active` no banco com a tela mostrando erro faria o motor começar a
    # matricular).
    update_campaign(campaign_id, status="active")
    return {"status": "active"}


@router.post("/{campaign_id}/pause")
async def api_pause_campaign(campaign_id: str):
    update_campaign(campaign_id, status="paused")
    return {"status": "paused"}


# ─── Nodes ────────────────────────────────────────────────────────────────────

@router.post("/{campaign_id}/nodes")
async def api_create_node(campaign_id: str, body: NodeCreate):
    return create_node(campaign_id, body.type, body.config, body.position_x, body.position_y)


@router.patch("/{campaign_id}/nodes/{node_id}")
async def api_update_node(campaign_id: str, node_id: str, body: dict):
    return update_node(node_id, **body)


@router.delete("/{campaign_id}/nodes/{node_id}")
async def api_delete_node(campaign_id: str, node_id: str):
    delete_node(node_id)
    return {"ok": True}


# ─── Enrollments ──────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/enrollments")
async def api_list_enrollments(campaign_id: str, status: str | None = None):
    return {"data": list_enrollments(campaign_id, status)}


@router.post("/{campaign_id}/enrollments")
async def api_enroll_lead(campaign_id: str, body: EnrollRequest):
    _reject_system_campaign(campaign_id, "enroll")
    if is_already_enrolled(campaign_id, body.lead_id):
        raise HTTPException(400, "Lead já está nesta campanha")
    # BLOQUEIO — camada 1 da esteira, que a matrícula manual não tinha. O worker
    # (`campaigns/worker.py:55`) já barra o envio, mas SÓ na hora de enviar: sem este 409
    # o operador recebia "matriculado com sucesso", o enrollment ficava vivo no banco e
    # nenhum toque saía nunca. Silêncio confuso — melhor recusar na cara.
    if is_lead_blacklisted(body.lead_id):
        logger.info(
            "[CAMPAIGNS][BLACKLIST] matrícula manual recusada — lead %s na blacklist (campanha %s)",
            body.lead_id, campaign_id,
        )
        raise HTTPException(409, "Lead bloqueado (opt-out ou funil Blacklist) — não pode ser matriculado.")
    camp = get_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign não encontrada")
    nodes = list_nodes(campaign_id)
    trigger = next((n for n in nodes if n["type"] == "trigger"), None)
    if not trigger or not trigger.get("next_node_id"):
        raise HTTPException(400, "Campaign sem fluxo configurado")
    enrollment = create_enrollment(
        campaign_id=campaign_id,
        lead_id=body.lead_id,
        deal_id=body.deal_id,
        current_node_id=trigger["next_node_id"],
        next_execute_at=datetime.now(timezone.utc),
    )
    return enrollment


@router.patch("/{campaign_id}/enrollments/{enrollment_id}")
async def api_update_enrollment(campaign_id: str, enrollment_id: str, body: dict):
    action = body.get("action")
    if action == "pause":
        pause_enrollment(enrollment_id)
        return {"status": "paused"}
    if action == "cancel":
        cancel_enrollment(enrollment_id)
        return {"status": "cancelled"}
    return update_enrollment(enrollment_id, **{k: v for k, v in body.items() if k != "action"})


# ─── Execution Log ────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/execution-log")
async def api_list_execution_log(campaign_id: str, limit: int = 50):
    return {"data": list_execution_log(campaign_id, limit=limit)}

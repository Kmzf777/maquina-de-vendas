"""Efeitos do bot de botões no CRM.

Toda regra de negócio aqui já existe em outro lugar — este módulo só a chama na
ordem certa. Nada é reimplementado: opt-out é o mesmo `apply_optout_side_effects`
usado pela tool do LLM e pelo endpoint manual, tag é o mesmo `add_tags_to_lead`,
movimento de card é o mesmo `move_deal_to_stage_key` das tools da IA.

Fail-soft por padrão: um erro de CRM loga e segue, porque o lead já recebeu a
resposta e não pode ficar preso. A ÚNICA exceção é o opt-out — ver `aplicar`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.agent.handoff import handoff_system_marker
from app.agent.tools import SUPERVISOR_NAME
from app.button_flow.engine import Efeitos
from app.leads.service import (
    add_tags_to_lead,
    append_lead_observation,
    apply_optout_side_effects,
    get_open_deal,
    move_deal_to_stage_key,
    save_message,
    update_lead,
)

logger = logging.getLogger(__name__)

# Motivo do handoff em um lugar só: ele vai para o carimbo `metadata.handoff` E para
# o marcador de sistema, e os dois divergirem tornaria a auditoria confusa.
#
# Genérico de propósito. O texto antigo citava o rótulo "Quero comprar agora", que
# deixou de existir no relabel de 09/09 (flows.py) — e o handoff hoje tem TRÊS
# origens: o botão "Preciso repor"/"Retomar o pedido", a classe QUENTE da camada 2
# (texto livre: "me manda a tabela") e o botão "Atualizar dados" da trilha C, que
# não é venda nenhuma. Citar um rótulo específico voltaria a mentir na auditoria no
# dia seguinte ao próximo relabel.
_MOTIVO_HANDOFF = "bot de recuperação: lead pediu atendimento do vendedor"

# ── Funil "Reativação Bling" e suas 3 etapas de DESFECHO ────────────────────
# Mesmo uuid de scripts/reativacao/lote_completo.py:32 (onde os 1.208 cards
# nasceram) e da migration 20260909_recuperacao_stages_optout.sql, que criou as
# etapas abaixo com order_index 8, 9 e 10.
PIPELINE_RECUPERACAO = "b2f9c31d-8a47-4e26-95c0-3d7a1f6e8b09"

# (key, label). O label é só fallback de resolução: `stage_id_by_key`
# (leads/service.py:1197) casa por `key` e, se não achar, por `label` exato.
STAGE_QUER_REPOR = ("quer_repor", "Quer repor")
STAGE_RECONTATO = ("recontato_agendado", "Recontato agendado")
STAGE_DESCADASTRADO = ("descadastrado", "Descadastrado")

# Vocabulário de `leads.opt_out_channel` (COMMENT da coluna na migration
# 20260909_recuperacao_stages_optout.sql:108): minúsculo, sem acento. O bot só
# produz estes dois — 'manual_crm'/'email'/'telefone' são de outros chamadores.
CANAL_BOTAO = "whatsapp_button"
CANAL_TEXTO = "whatsapp_texto"


def aplicar(
    efeitos: Efeitos, *, lead: dict, conversation_id: str,
    evidencia: dict | None = None,
) -> bool:
    """Aplica os efeitos da decisão. Retorna False se o fluxo NÃO deve avançar.

    Só o opt-out bloqueia: se não conseguimos gravar `opt_out=true`, avançar o nó
    encerraria o fluxo com o lead ainda elegível a disparos — exatamente o que ele
    acabou de pedir para não acontecer. O nó fica onde está e o próximo clique retenta.

    `evidencia` é o registro cru do turno que originou o opt-out (só é lida quando
    `efeitos.optout`); o contrato está em `_campos_de_evidencia`. Ela alimenta
    `leads.opt_out_at/opt_out_channel/opt_out_evidence` — sem isso o opt-out nasce
    como o "booleano nu" que a própria migration declara indefensável na ANPD.

    ORDEM DE DEGRADAÇÃO, deliberada: o fail-CLOSED vale para o `opt_out` em si, NUNCA
    para a evidência. Se a gravação com evidência falhar (típico: migration ainda não
    aplicada → PostgREST responde PGRST204 "column not found"), o update degrada para
    `ai_enabled=false, opt_out=true` e o opt-out É honrado do mesmo jeito. Só quando
    ESSE segundo update também falha é que devolvemos False.
    """
    lead_id = lead["id"]

    if efeitos.tags:
        try:
            add_tags_to_lead(lead_id, list(efeitos.tags))
        except Exception as exc:
            logger.warning("[BUTTON FLOW] tags %s falharam p/ lead %s: %s",
                           efeitos.tags, lead_id, exc)

    if efeitos.optout and not _aplicar_optout(lead, conversation_id, evidencia):
        return False

    # ANTES do handoff de propósito: os dois escrevem `leads.metadata` a partir da
    # cópia que o chamador trouxe. Quem escreve por último com uma cópia velha apaga
    # o carimbo do outro — e o carimbo perdido seria justamente o `metadata.handoff`,
    # que `follow_up.should_proactive_handoff` lê para não reentregar o lead sozinho.
    # Cada gravação atualiza o dict do lead em memória (ver atualizar_metadata) para
    # que a seguinte parta do estado já gravado.
    if efeitos.pretexto_contestado:
        _marcar_pretexto_contestado(lead, conversation_id)

    if efeitos.silenciar_ia:
        _silenciar_ia(lead, conversation_id)

    if efeitos.handoff:
        _aplicar_handoff(lead, conversation_id)

    if efeitos.recontato_dias:
        _agendar_recontato(lead, efeitos.recontato_dias, conversation_id)

    return True


def _aplicar_optout(lead: dict, conversation_id: str, evidencia: dict | None = None) -> bool:
    """Honra o opt-out e registra a PROVA de que ele foi pedido. Ver `aplicar`.

    Duas gravações, em ordem: a completa (booleano + evidência) e, se ela falhar, a
    nua (só o booleano). Nunca o contrário — perder a evidência é um problema de
    auditoria, perder o `opt_out` é continuar disparando para quem pediu para sair.
    """
    lead_id = lead["id"]
    obrigatorio = {"ai_enabled": False, "opt_out": True}
    try:
        update_lead(lead_id, **obrigatorio, **_campos_de_evidencia(
            evidencia, conversation_id=conversation_id, lead_id=lead_id))
    except Exception as exc:
        # Caminho esperado enquanto 20260909_recuperacao_stages_optout.sql não estiver
        # aplicada: as colunas de evidência não existem e o PostgREST devolve PGRST204
        # para o UPDATE inteiro. Degradar aqui é o que impede que a falta de uma
        # migration vire opt-out não honrado — o incidente dos 52 cliques em
        # "Nao tenho interesse" com opt_out=false (scripts/recuperacao/
        # honrar_optouts_pendentes.sql) já custou caro uma vez.
        logger.warning(
            "[BUTTON FLOW] evidência de opt-out não gravada p/ lead %s (migration "
            "20260909 aplicada?) — regravando só o booleano: %s", lead_id, exc,
        )
        try:
            update_lead(lead_id, **obrigatorio)
        except Exception as exc2:
            logger.error(
                "[BUTTON FLOW] FALHA ao gravar opt-out do lead %s — fluxo NÃO avança: %s",
                lead_id, exc2, exc_info=True,
            )
            return False

    # ANTES de `apply_optout_side_effects`, e a ordem é o ponto: ele chama
    # `move_lead_deals_to_blacklist` (leads/service.py:1458), que joga TODOS os deals
    # do lead para o funil Blacklist. Rodando depois, a guarda de funil de
    # `_mover_deal` não reconheceria mais o card (já estaria na Blacklist) e
    # "Descadastrado" nunca receberia ninguém — a etapa da migration seguiria morta,
    # que é exatamente o defeito consertado aqui.
    # O card TERMINA na Blacklist de qualquer forma (é o tratamento universal de
    # opt-out no CRM, o mesmo que honrar_optouts_pendentes.sql:166 aplicou aos 48
    # retroativos); o que sobrevive de `descadastrado` é o texto em `deals.stage`, ou
    # seja, o MOTIVO de o card estar na Blacklist, legível ao lado dos outros. E se a
    # Blacklist falhar (ela é fail-soft), o card fica em "Descadastrado" no funil da
    # Reativação — que é o desfecho correto para o operador ver.
    _mover_deal(lead_id, *STAGE_DESCADASTRADO)
    apply_optout_side_effects(lead_id, lead.get("phone") or "", reason="optout")
    # Sem citar rótulo: o mesmo efeito vem do botão "Parar mensagens" E da classe SAIR
    # da camada 2 (texto livre "me tira da lista"). Os 52 opt-outs não honrados que
    # existem hoje em produção nasceram de um clique que ninguém registrou — a nota
    # tem que ser a evidência legível de que este foi registrado.
    anotar(lead_id, conversation_id,
           "🚫 [OPT-OUT] Lead pediu para parar de receber mensagens no bot de recuperação.")
    return True


def _campos_de_evidencia(
    evidencia: dict | None, *, conversation_id: str, lead_id: str,
) -> dict:
    """Traduz o registro cru do turno nas 3 colunas de prova do opt-out.

    Contrato de `evidencia` (todas as chaves opcionais, todas cruas do turno):
        origem          'clique' (botão) | 'classe' (texto livre classificado)
        button_payload  payload do botão, '<flow>|<botao_id>|<trilha>|t<toque>'
        button_label    título do botão exatamente como o lead o viu
        texto           texto livre que a camada 2 classificou como SAIR
        classe          classe devolvida pela camada 2 (engine.CLASSE_SAIR)
        wamid           id Meta da mensagem do lead — a única parte da prova que a
                        Meta consegue confirmar de forma independente
        canal           força `opt_out_channel` (para chamadores que não são o bot:
                        'manual_crm' | 'email' | 'telefone')
    Chaves desconhecidas são preservadas dentro de `opt_out_evidence`: prova extra
    nunca atrapalha, e o formato do jsonb é de propósito aberto (COMMENT da coluna).

    `opt_out_channel` fica de FORA quando não dá para deduzir a origem. Escrever um
    canal chutado seria pior que a lacuna: o valor existe para ser mostrado à ANPD.
    """
    dados = {k: v for k, v in (evidencia or {}).items() if v not in (None, "", {}, [])}
    agora = datetime.now(timezone.utc)
    canal = str(dados.pop("canal", "") or "") or _canal_do_optout(dados)

    prova = {
        "source": "button_flow",
        "registrado_em": agora.isoformat(),
        "conversation_id": conversation_id,
        "lead_id": lead_id,
        **dados,
    }
    campos: dict = {"opt_out_at": agora.isoformat(), "opt_out_evidence": prova}
    if canal:
        prova["canal"] = canal
        campos["opt_out_channel"] = canal
    else:
        logger.warning(
            "[BUTTON FLOW] opt-out do lead %s sem origem na evidência (conv %s) — "
            "opt_out_channel fica NULL; quem chamar `aplicar` precisa passar "
            "`evidencia={'origem': 'clique'|'classe', ...}`", lead_id, conversation_id,
        )
    return campos


def _canal_do_optout(dados: dict) -> str | None:
    """Deduz `opt_out_channel` do que veio no turno. None = não deduzível."""
    origem = str(dados.get("origem") or "").strip().lower()
    if origem == "clique" or dados.get("button_payload") or dados.get("button_label"):
        return CANAL_BOTAO
    if origem in ("classe", "texto") or dados.get("classe") or dados.get("texto"):
        return CANAL_TEXTO
    return None


def _mover_deal(lead_id: str, key: str, label: str) -> bool:
    """Move o card do lead para uma das 3 etapas de DESFECHO da Reativação Bling.

    Só no DESFECHO, nunca no envio: as 8 etapas originais do funil são buckets de
    RECÊNCIA — registram há quanto tempo o lead não compra, ou seja, qual onda ele
    pegou — e mover na saída destruiria a segmentação com que o operador monta a onda
    seguinte (migration 20260909_recuperacao_stages_optout.sql:22-27).

    Guarda de funil, e não é zelo: um lead da coorte pode ter card em OUTRO funil (o
    do João, a Blacklist), e mover o card errado é pior do que não mover nenhum.
    `move_deal_to_stage_key` sozinho não protege disso — quando a `key` não existe no
    funil do card ele cai em fallback por LABEL exato (leads/service.py:1217), e
    "Descadastrado" é um rótulo que qualquer funil pode ganhar amanhã pela UI.

    Fail-soft em tudo: o desfecho (opt-out, handoff, recontato) já foi honrado nas
    colunas do lead; um card fora do lugar não pode desfazê-lo nem travar o turno.
    """
    try:
        deal = get_open_deal(lead_id)
        if not deal:
            return False
        if str(deal.get("pipeline_id") or "") != PIPELINE_RECUPERACAO:
            logger.info(
                "[BUTTON FLOW] card do lead %s está no funil %s (não é a Reativação "
                "Bling) — desfecho '%s' não move card de outro funil",
                lead_id, deal.get("pipeline_id"), key,
            )
            return False
        movido = move_deal_to_stage_key(lead_id, key, label)
        if not movido:
            # Caminho esperado enquanto a migration 20260909 não estiver aplicada: a
            # etapa não existe no funil e `stage_id_by_key` devolve None.
            logger.warning("[BUTTON FLOW] card do lead %s não foi para '%s' "
                           "(etapa existe no funil?)", lead_id, key)
        return movido
    except Exception as exc:
        logger.warning("[BUTTON FLOW] falha ao mover card do lead %s p/ '%s': %s",
                       lead_id, key, exc)
        return False


def _marcar_pretexto_contestado(lead: dict, conversation_id: str) -> None:
    """Carimba que o lead negou o pretexto do template ("não fiz pedido nenhum").

    Não é cosmético: é o que impede a onda seguinte de reenviar a MESMA afirmação
    falsa para a mesma pessoa. O template `rabubens` ("seu pedido já está sendo
    preparado") teve 44,2% de negação/confusão em 104 respostas, com pânico de
    cliente legítimo no meio — insistir depois disso é o caminho mais curto para um
    report na Meta, que derruba a qualidade dos três números da WABA compartilhada.

    Fail-soft: o cliente já recebeu o pedido de desculpas do fluxo; perder o carimbo
    não pode travar o turno.
    """
    if not atualizar_metadata(lead, {"pretexto_contestado": True},
                              rotulo="pretexto_contestado"):
        return
    anotar(lead["id"], conversation_id,
           "⚠️ [PRETEXTO CONTESTADO] Lead negou o motivo do disparo (diz não ter feito "
           "pedido / não conhecer a compra). NÃO reenviar campanha para este contato.")


def _silenciar_ia(lead: dict, conversation_id: str) -> None:
    """Entrega a conversa ao vendedor sem carimbar handoff.

    Encerrar o nó só tira o BOT do caminho — no número da ValerIA o LLM assumiria em
    seguida. Aqui NÃO usamos o carimbo de handoff de propósito: ele marcaria como lead
    qualificado alguém que só escreveu texto livre duas vezes, sujando a cascata de
    Qualificados/Aceites.
    """
    lead_id = lead["id"]
    try:
        update_lead(lead_id, ai_enabled=False)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] falha ao silenciar IA do lead %s: %s", lead_id, exc)
        return
    anotar(lead_id, conversation_id,
           "🙋 [ATENDIMENTO HUMANO] Lead insistiu em texto livre no bot de recuperação; "
           "IA desligada, conversa entregue ao vendedor.")


def _aplicar_handoff(lead: dict, conversation_id: str) -> None:
    """Handoff enxuto: sem resumo por LLM (não houve conversa) e sem rescue job.

    Dois registros do MESMO handoff, porque quem os lê é diferente:
    - a mensagem de sistema `[encaminhar_humano] ...` é o que o dashboard conta
      (KPI de handoffs, conversão do funil, SLA do vendedor) e o que o CRM usa
      para desenhar o divisor de transbordo na conversa;
    - o carimbo `metadata.handoff` é o que `follow_up.should_proactive_handoff` lê
      para não entregar de novo, sozinho, um lead que já foi entregue.
    Gravar só um dos dois deixa metade dos consumidores cego.

    E um TERCEIRO registro, para um leitor diferente dos dois: o card vai para "Quer
    repor" no Kanban. É A conversão do agente — a etapa nasceu com
    `conversion_event='qualified'`, então cada entrada nela vira uma linha
    deduplicada em `conversion_events` (automation/triggers.py), que é a métrica do
    agente sem escrever uma linha de código para isso.
    """
    lead_id = lead["id"]
    try:
        update_lead(lead_id, ai_enabled=False)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] falha ao desligar IA no handoff do lead %s: %s",
                       lead_id, exc)
    try:
        # Marcador de sistema idêntico ao que `encaminhar_humano` grava. É ELE que o
        # dashboard conta — dashboard_kpis.handoff_msgs e
        # dashboard_funnel_conversion.with_handoff casam
        # `content LIKE '[encaminhar\_humano] Lead encaminhado%'` em role='system',
        # e não `metadata.handoff`. Sem esta linha o lead é entregue de verdade ao
        # vendedor e mesmo assim some do KPI: um disparo de 1.208 leads mostraria
        # dezenas de quentes com zero transbordos.
        save_message(lead_id, "system",
                     handoff_system_marker(SUPERVISOR_NAME, _MOTIVO_HANDOFF),
                     conversation_id=conversation_id)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] marcador de handoff não gravado p/ conv %s: %s",
                       conversation_id, exc)
    atualizar_metadata(lead, {
        "handoff": {
            "vendedor": SUPERVISOR_NAME,
            "motivo": _MOTIVO_HANDOFF,
            "at": datetime.now(timezone.utc).isoformat(),
            "origem": "button_flow",
        },
    }, rotulo="metadata.handoff")
    _mover_deal(lead_id, *STAGE_QUER_REPOR)
    anotar(lead_id, conversation_id,
           f"➡️ [TRANSBORDO p/ {SUPERVISOR_NAME}] {_MOTIVO_HANDOFF}. "
           f"Nenhuma qualificação por conversa — abordar direto.")


def _agendar_recontato(lead: dict, dias: int, conversation_id: str) -> None:
    """Agenda o recontato em DIAS corridos.

    Era em meses e multiplicava por 30. Virou dias no relabel de 09/09 porque o nível
    2 passou a oferecer 30/60/90 DIAS: o intervalo médio entre compras desta coorte é
    de 78-122 dias, então 90 é o ciclo natural e "3 meses" era um rótulo pior para o
    mesmo número. Converter mês↔dia no meio do caminho só criava uma casa decimal a
    mais para errar.
    """
    lead_id = lead["id"]
    quando = datetime.now(timezone.utc) + timedelta(days=dias)
    if not atualizar_metadata(lead, {"recontatar_em": quando.isoformat()},
                              rotulo="recontatar_em"):
        return
    # Depois da data, e só se a data gravou: "Recontato agendado" no Kanban promete
    # uma fila com data, e o worker de re-disparo (fase 2 da spec) vai ler
    # `metadata.recontatar_em`, não a etapa. Card na coluna sem data seria um lead
    # esquecido parecendo agendado.
    _mover_deal(lead_id, *STAGE_RECONTATO)
    anotar(lead_id, conversation_id,
           f"⏰ [RECONTATO] Lead pediu contato em ~{dias} dias "
           f"({quando.date().isoformat()}), via bot de recuperação.")


def atualizar_metadata(lead: dict, campos: dict, *, rotulo: str) -> bool:
    """Faz merge de `campos` em `leads.metadata` e devolve se gravou. Fail-soft.

    Cópia antes do merge: o metadata do lead carrega marcadores de outros fluxos
    (catalog_shown, rastreio, id_bling) que precisam sobreviver ao update, e o dict
    do chamador não é nosso.

    Depois de gravar, o dict do lead em memória é atualizado de propósito: um mesmo
    `aplicar` pode gravar metadata duas vezes (pretexto_contestado + handoff), e a
    segunda gravação partindo da cópia original apagaria a primeira — silenciosamente,
    porque as duas retornam sucesso.
    """
    try:
        meta = dict(lead.get("metadata") or {})
        meta.update(campos)
        update_lead(lead["id"], metadata=meta)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] falha ao gravar %s do lead %s: %s",
                       rotulo, lead.get("id"), exc)
        return False
    lead["metadata"] = meta
    return True


def anotar(lead_id: str, conversation_id: str, texto: str) -> None:
    """Observação no lead + mensagem de sistema na conversa. Fail-soft nos dois."""
    try:
        append_lead_observation(lead_id, texto)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] observação não gravada p/ lead %s: %s", lead_id, exc)
    try:
        save_message(lead_id, "system", f"[button_flow] {texto}",
                     conversation_id=conversation_id)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] mensagem de sistema não gravada p/ conv %s: %s",
                       conversation_id, exc)

"""Orquestração do agente de recuperação: o único módulo do fluxo com I/O.

`engine.decidir` é puro e `flows` é só dado; aqui ficam o relógio, o banco, a rede e
as duas camadas que não cabem numa função pura (detector de autoresponder e
classificador). A ordem é sempre a mesma: guardas → evento → decisão → efeitos →
envio → estado.

Fail-soft em tudo, com UMA exceção: quando `effects.aplicar` devolve False (só o
opt-out faz isso), o nó NÃO avança e nada é enviado. Confirmar "não te mando mais
nada" sem ter conseguido gravar `opt_out=true` é pior do que o silêncio: o lead
perde o motivo para tocar no botão de novo e a única chance de retentar a gravação
morre junto. Hoje existem 52 pessoas em produção que clicaram opt-out, seguem
`opt_out=false` e continuam elegíveis à próxima campanha — foi exatamente esse
buraco que este módulo existe para não repetir.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from app.agent.tools import SUPERVISOR_NAME, SUPERVISOR_PHONE
from app.agent_profiles.service import get_agent_profile
from app.button_flow import config, effects, engine, flows
from app.conversations.service import (
    get_conversation,
    get_history,
    save_message,
    update_conversation,
)
from app.leads.service import get_open_deal, resolve_send_target
from app.whatsapp.meta import extract_wamid

logger = logging.getLogger(__name__)

# Idade a partir da qual o clique deixou de ser "o turno seguinte" e passa a ser um
# reencontro. Não muda o comportamento (o nó é retomado igual), só o log: serve para
# medir os 30% de cliques que chegam fora da janela de 24h da Meta.
_HORAS_JANELA_META = 24

# Quantas linhas de histórico o classificador recebe. Curto de propósito: a camada 2
# classifica UMA mensagem, não conduz conversa — e o custo alvo do turno de exceção
# é ~300 tokens, contra os 35.565 de input médios de um turno da ValerIA.
_LINHAS_HISTORICO = 6

# Cache de `agent_profiles.kind` por id. O gate roda em TODO inbound do backend, e
# resolver o perfil da conversa é uma consulta a mais por mensagem — com o kill
# switch ligado, sem cache, seria uma ida ao banco por turno de conversa de qualquer
# número, não só dos do fluxo. TTL curto porque o operador pode trocar o perfil da
# conversa no meio de um lote.
_KIND_TTL_SEGUNDOS = 300.0
_kind_cache: dict[str, tuple[float, str]] = {}

# Setor de `products` do qual este fluxo pode cotar preço, já normalizado por
# `app.agent.catalog._normalize` (sem acento, minúsculo, espaço -> underscore; hoje
# a coluna vale literalmente "Atacado" e "Private Label" em produção).
#
# A coorte é 97,2% B2B — 1.174 dos 1.208 leads têm CNPJ, e são revendedores que
# compravam do Bling no atacado (ticket médio R$ 1.506,48). Cotar do setor de
# consumo para eles é cotar o preço errado com o SKU certo. Não existe, no
# `lead.metadata` dos 1.208 (só 10 chaves fixas: origem, lote, id_bling, segmento,
# total_gasto, ultima_compra, whatsapp_tipo, vendedor_anterior, phone_raw), nenhum
# critério confiável para dizer que um lead é de varejo — e na dúvida a regra da
# spec é NÃO cotar, nunca cotar errado.
_SETOR_DA_COORTE = "atacado"


def limpar_cache_de_perfis() -> None:
    """Esvazia o cache de `kind` (uso em teste e em troca manual de perfil)."""
    _kind_cache.clear()


# ── O gate ──────────────────────────────────────────────────────────────────
def _kind_do_perfil(profile_id: str) -> str:
    agora = time.monotonic()
    em_cache = _kind_cache.get(profile_id)
    if em_cache and (agora - em_cache[0]) < _KIND_TTL_SEGUNDOS:
        return em_cache[1]
    perfil = get_agent_profile(profile_id) or {}
    # Perfil sem `kind` é perfil anterior à migration 20260820: 'llm' é o default da
    # coluna e o default seguro aqui.
    kind = perfil.get("kind") or "llm"
    _kind_cache[profile_id] = (agora, kind)
    return kind


def is_button_flow_conversation(conversation: dict, channel: dict) -> bool:
    """True quando esta conversa é atendida pelo fluxo de botões, não pela ValerIA.

    A conversa tem precedência sobre o canal, e isso não é detalhe: o canal do João
    (`a3a607b1`) já aponta para o MESMO `agent_profile_id` do canal da ValerIA
    (`674beb13`, verificado em produção 09/09). Se decidíssemos pelo canal, o bot
    atenderia todas as conversas do número do João — inclusive as que o vendedor
    conduz à mão. Quem marca a conversa é o disparo, via
    `get_or_create_conversation(..., agent_profile_id=...)`.

    Fail-OPEN em qualquer erro (perfil ausente, coluna `kind` ainda não migrada,
    banco fora): devolve False e o inbound segue o fluxo normal do processor. O
    contrário — fail-closed — sequestraria conversas humanas num erro de leitura.
    """
    if not config.enabled():
        return False
    try:
        profile_id = (conversation or {}).get("agent_profile_id")
        if profile_id:
            return _kind_do_perfil(profile_id) == "button_flow"
        perfil_do_canal = (channel or {}).get("agent_profiles") or {}
        return (perfil_do_canal.get("kind") or "llm") == "button_flow"
    except Exception as exc:
        logger.warning(
            "[BUTTON FLOW] falha ao resolver o perfil da conv %s — segue fluxo normal: %s",
            (conversation or {}).get("id"), exc,
        )
        return False


# ── Montagem do evento ──────────────────────────────────────────────────────
def e_clique_de_botao(message_type: str | None, metadata: dict | None) -> bool:
    """True quando este inbound é um TOQUE em botão, não texto digitado.

    O que prova o clique é a presença de `payload` no metadata, NÃO o `message_type`:
    quando o lead toca no botão e manda uma foto na mesma janela de buffer, o único
    slot de `message_type` fica com a mídia e o clique sobrevive só no metadata
    (`buffer/processor.py`, decodificação do marcador `button` em `_resolve_media`).
    Nenhum outro tipo de metadado escreve a chave `payload` — location grava
    latitude/longitude, contact grava contacts, reaction grava emoji —, então a
    presença dela é prova suficiente e exclusiva.

    Pública porque o gate do `buffer/processor.py` precisa da MESMA regra para
    decidir se pode descartar um turno no re-coalescing (clique nunca é descartado).
    Duas cópias da regra divergiriam no primeiro webhook fora do padrão.
    """
    meta = metadata if isinstance(metadata, dict) else {}
    return bool(meta.get("payload")) or message_type == "button"


def _montar_evento(texto: str, message_type: str | None, metadata: dict | None) -> engine.Evento:
    """Clique ou texto livre."""
    meta = metadata if isinstance(metadata, dict) else {}
    payload = meta.get("payload")
    if payload:
        titulo = meta.get("title") or texto or ""
        return engine.Clique(payload=str(payload), titulo=str(titulo))
    if message_type == "button":
        # Clique sem payload não deveria existir (o parser sempre preenche, caindo no
        # texto do botão), mas se acontecer o título ainda identifica o botão.
        return engine.Clique(payload=texto or "", titulo=texto or "")
    return engine.Texto(texto or "")


# Teto do texto livre guardado como prova. O jsonb é aberto de propósito, mas a
# evidência de um opt-out é a frase em que o lead pede para sair — não o buffer
# inteiro de um turno colado do WhatsApp.
_MAX_TEXTO_EVIDENCIA = 500


def _evidencia_do_turno(
    evento: engine.Evento, texto: str, wamid: str | None,
) -> dict:
    """Registro CRU do turno, no contrato de `effects._campos_de_evidencia`.

    Sem isto o opt-out nasce como o "booleano nu": `_campos_de_evidencia` não
    consegue deduzir a origem, `opt_out_channel` fica NULL e `opt_out_evidence`
    guarda só conversation_id/lead_id — nada que prove à ANPD QUE o lead pediu para
    sair, nem COMO. É exatamente a lacuna dos 52 opt-outs de produção que
    `scripts/recuperacao/honrar_optouts_pendentes.sql` teve que reparar à mão.

    O `texto` vem do parâmetro do turno, e não de `evento`, de propósito: quando a
    camada 2 classifica a frase como SAIR, o runner SUBSTITUI o `engine.Texto` por
    um `engine.Classificado`, que carrega só a classe. A frase original — a prova —
    só sobrevive aqui.
    """
    dados: dict = {"wamid": wamid}
    if isinstance(evento, engine.Clique):
        dados["origem"] = "clique"
        dados["button_payload"] = evento.payload
        dados["button_label"] = evento.titulo
    else:
        # Classificado (texto livre que virou SAIR) e Texto caem juntos: nos dois a
        # prova é a frase do lead. `classe` só existe no primeiro.
        dados["origem"] = "classe"
        dados["texto"] = (texto or "")[:_MAX_TEXTO_EVIDENCIA]
        if isinstance(evento, engine.Classificado):
            dados["classe"] = evento.classe
    return dados


# ── Guardas de não-rodar ────────────────────────────────────────────────────
def _motivo_para_nao_rodar(lead: dict, estado: dict | None, deal: dict | None) -> str | None:
    """Razão para o bot sair de cena neste turno, ou None para seguir.

    Duas situações, as duas significando a mesma coisa — um humano já assumiu:
    `human_control=true` (o carimbo formal do handoff) e o card já movido de etapa.
    O bot rodando por cima disso responderia por cima do vendedor na MESMA thread,
    no número dele, que é o pior efeito colateral possível deste desenho.

    O stage de referência é o que o próprio runner gravou no turno anterior
    (`flow_state.deal_stage_id`); sem referência não há como afirmar que mudou, e a
    ausência NÃO bloqueia — no primeiro turno o bot precisa poder rodar.

    Compara `stage_id`, e isso é o conserto de um guarda que era CÓDIGO MORTO:
    `get_open_deal` (`app/leads/service.py:1074`) projeta
    `select("id, title, pipeline_id, stage_id, category")` e nunca traz a coluna
    `stage`. Lendo `deal["stage"]` o valor era sempre None, `deal_stage` nunca era
    gravado no flow_state e esta comparação nunca disparava — sobrava só
    `human_control` como guarda, e o bot respondia POR CIMA do vendedor na mesma
    thread do número dele, que é o pior efeito colateral possível deste desenho.
    Todos os outros consumidores de `get_open_deal` no repo usam `stage_id`.

    A chave do estado mudou junto (`deal_stage` -> `deal_stage_id`) de propósito: um
    estado antigo com rótulo humano em `deal_stage` comparado contra um UUID de
    `stage_id` daria diferente SEMPRE e tiraria o bot de cena para sempre.
    """
    if lead.get("human_control") is True:
        return "human_control=true (handoff formal já registrado)"
    stage_gravado = (estado or {}).get("deal_stage_id") if isinstance(estado, dict) else None
    stage_atual = (deal or {}).get("stage_id")
    if stage_gravado and stage_atual and stage_atual != stage_gravado:
        return f"deal mudou de etapa ({stage_gravado} -> {stage_atual})"
    return None


# ── Idade do estado ─────────────────────────────────────────────────────────
def _parse_iso(valor) -> datetime | None:
    if not isinstance(valor, str) or not valor:
        return None
    try:
        quando = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    return quando if quando.tzinfo else quando.replace(tzinfo=timezone.utc)


def _envelhecer(estado, agora: datetime) -> tuple[dict | None, bool, float | None]:
    """Aplica a regra de idade e devolve (estado, reiniciado, idade_em_horas).

    30% dos cliques da base chegam fora da janela de 24h e o máximo observado foi
    **43 dias**. Retomar `aguardando_prazo` 43 dias depois é responder a uma pergunta
    que o lead não lembra de ter recebido — e responder "combinado, em 30 dias" a
    quem tocou no botão errado por engano um mês depois.

    - até 24h: o turno seguinte, nada muda;
    - 24h até `RECUPERACAO_JANELA_RETOMA_DIAS`: retoma o nó de onde parou;
    - acima disso: recomeça limpo em `aguardando_interesse`, com o nudge zerado.

    Estado que não é dict é corrompido e vai intacto para o motor, que devolve o
    lead ao humano — reiniciar aqui apagaria a prova do problema.
    """
    if not isinstance(estado, dict) or not estado:
        return estado, False, None
    atualizado = _parse_iso(estado.get("updated_at"))
    if atualizado is None:
        return estado, False, None
    horas = (agora - atualizado).total_seconds() / 3600.0
    if horas <= config.janela_retoma_dias() * 24:
        return estado, False, horas
    # Reinício preserva o que identifica a onda (campaign_id, sent_at, trilha) e zera
    # só o que é conversa: nó e nudge.
    novo = dict(estado)
    novo["node"] = flows.NO_INTERESSE
    novo["nudged"] = False
    return novo, True, horas


# ── Contexto do lead ────────────────────────────────────────────────────────
def _primeiro_nome(lead: dict) -> str:
    nome = (lead.get("name") or "").strip()
    return nome.split()[0] if nome else ""


def _preco_de_tabela(produto: str) -> str:
    """Preço ATACADO do SKU ativo que casa com `produto`, ou "" quando não dá para afirmar.

    Devolve preço só com match ÚNICO: dois candidatos significam que não sabemos qual
    o lead comprava, e chutar por adjacência textual é como se perderam as 500
    unidades da Ritz (o agente cotou drip a R$ 27,70 misturando com o Microlote,
    quando o drip real sai R$ 2,49/sachê — "éramos metade do preço e perdemos por
    parecer 5x mais caros").

    141 leads da coorte compravam outras marcas, 123 cápsula e 47 drip; o Bling tem
    444 produtos e o agente conhece 32. O caso "não casa" é o caso COMUM, e o texto
    sem preço já existe em flows.MSG_QUENTE_SEM_PRECO.

    O FILTRO DE SETOR não é detalhe: a tabela `products` é particionada por `sector`
    e o MESMO nome de SKU existe em setores diferentes com preços diferentes.
    `match_products` só olha `name`, então casar sobre o catálogo inteiro produzia
    duas falhas, as duas silenciosas — dois candidatos derrubavam a maior alavanca da
    spec para o texto sem preço, e um catálogo com o SKU só no varejo fazia o bot
    COTAR PREÇO DE VAREJO para um cliente de atacado com ticket médio R$ 1.506,48.
    É o incidente Ritz por outra rota: SKU certo, setor errado. O único outro
    consumidor de `match_products` no repo já filtra assim antes de casar
    (`app/agent/tools.py:1271-1274`, calcular_orcamento).
    """
    if not produto:
        return ""
    try:
        from app.agent.catalog import _fetch_active_products
        from app.agent.catalog import _normalize as _normalizar_setor
        from app.agent.pricing import match_products
        do_setor = [
            p for p in _fetch_active_products()
            if _normalizar_setor(p.get("sector")) == _SETOR_DA_COORTE
        ]
        candidatos = match_products(produto, do_setor)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] catálogo indisponível p/ %r — sem preço: %s", produto, exc)
        return ""
    if not do_setor:
        # Catálogo sem nenhum SKU ativo no setor da coorte: preferimos entregar sem
        # preço a cotar de outro setor. Vale um WARNING porque é problema de dado.
        logger.warning(
            "[BUTTON FLOW] nenhum SKU ativo no setor %r — entrega SEM preço", _SETOR_DA_COORTE,
        )
        return ""
    if len(candidatos) != 1:
        logger.info(
            "[BUTTON FLOW] produto %r casou com %d SKUs ativos — entrega SEM preço",
            produto, len(candidatos),
        )
        return ""
    return (candidatos[0].get("price_formatted") or "").strip()


def _montar_contexto(lead: dict) -> engine.Contexto:
    """Bloqueante (lê o catálogo). Chamado via asyncio.to_thread."""
    meta = lead.get("metadata") or {}
    produto = str(meta.get("produto_top1") or "").strip()
    return engine.Contexto(
        primeiro_nome=_primeiro_nome(lead),
        produto=produto,
        preco=_preco_de_tabela(produto),
    )


# ── Camadas 1.5 e 2 (entregues por outras frentes; ausência não derruba nada) ─
def _historico(conversation_id: str) -> list[dict]:
    try:
        return get_history(conversation_id, limit=_LINHAS_HISTORICO,
                           roles=("user", "assistant"))
    except Exception as exc:
        logger.warning("[BUTTON FLOW] histórico indisponível p/ conv %s: %s",
                       conversation_id, exc)
        return []


def _segundos_desde_nosso_envio(historico: list[dict], agora: datetime) -> float | None:
    """Lag entre a nossa última saída e agora — o sinal mais forte do autoresponder.

    Robô de saudação responde em segundos; gente responde em minutos ou horas.
    """
    for linha in reversed(historico):
        if linha.get("role") != "assistant":
            continue
        quando = _parse_iso(linha.get("created_at"))
        if quando is None:
            return None
        return (agora - quando).total_seconds()
    return None


async def _e_autoresponder(texto: str, historico: list[dict], agora: datetime) -> bool:
    try:
        from app.button_flow.autoreply import parece_autoresponder
    except ImportError:
        logger.debug("[BUTTON FLOW] detector de autoresponder ainda não disponível")
        return False
    try:
        return bool(parece_autoresponder(
            texto, segundos_desde_nosso_envio=_segundos_desde_nosso_envio(historico, agora),
        ))
    except Exception as exc:
        logger.warning("[BUTTON FLOW] detector de autoresponder falhou: %s", exc)
        return False


def _historico_curto(historico: list[dict]) -> str:
    linhas = []
    for row in historico:
        quem = "cliente" if row.get("role") == "user" else "nós"
        conteudo = (row.get("content") or "").strip().replace("\n", " ")
        if conteudo:
            linhas.append(f"{quem}: {conteudo}")
    return "\n".join(linhas)


async def _classificar(texto: str, historico: list[dict]) -> str | None:
    """Classe da camada 2, ou None para cair na regra de nudge do motor.

    Qualquer falha (módulo ainda inexistente, LLM fora, classe desconhecida) vira
    None de propósito: sem classificador o fluxo continua funcionando como máquina de
    estados pura — reoferece os botões uma vez e depois entrega ao João. Um turno sem
    classificação é degradação; uma exceção aqui seria um lead sem resposta nenhuma.
    """
    try:
        from app.button_flow.classifier import classificar
    except ImportError:
        logger.debug("[BUTTON FLOW] classificador ainda não disponível")
        return None
    try:
        classe = await classificar(texto, historico_curto=_historico_curto(historico))
    except Exception as exc:
        logger.warning("[BUTTON FLOW] classificador falhou (cai no nudge): %s", exc)
        return None
    if classe not in engine.CLASSES:
        logger.warning("[BUTTON FLOW] classe desconhecida %r (cai no nudge)", classe)
        return None
    return classe


# ── Envio ───────────────────────────────────────────────────────────────────
async def _enviar(
    decisao: engine.Decisao, *, lead: dict, conversation: dict, provider,
) -> None:
    mensagem = decisao.mensagem
    if mensagem is None:
        return
    destino = resolve_send_target(lead, lead.get("phone"))
    conversation_id = conversation.get("id")
    lead_id = lead.get("id")
    try:
        if mensagem.botoes:
            resultado = await provider.send_interactive_buttons(
                destino, mensagem.corpo,
                [(b.id, b.titulo) for b in mensagem.botoes],
            )
        else:
            resultado = await provider.send_text(destino, mensagem.corpo)
    except Exception as exc:
        logger.error("[BUTTON FLOW] falha ao enviar p/ conv %s: %s",
                     conversation_id, exc, exc_info=True)
        return
    try:
        await asyncio.to_thread(
            save_message, conversation_id, lead_id, "assistant", mensagem.corpo,
            conversation.get("stage"), sent_by="button_flow",
            wamid=extract_wamid(resultado),
        )
    except Exception as exc:
        logger.warning("[BUTTON FLOW] mensagem enviada mas não persistida conv=%s: %s",
                       conversation_id, exc)

    if not mensagem.enviar_cartao_vendedor:
        return
    # Só no número da ValerIA. No número do próprio João o cartão seria absurdo — e é
    # justamente esse degrau de troca de número que custa 26% dos leads (131 de 500).
    try:
        await provider.send_contact(
            destino, contact_name=SUPERVISOR_NAME, contact_phone=SUPERVISOR_PHONE,
        )
        await asyncio.to_thread(
            save_message, conversation_id, lead_id, "system",
            f"[button_flow] cartão de contato de {SUPERVISOR_NAME} enviado",
            conversation.get("stage"), sent_by="button_flow",
        )
    except Exception as exc:
        logger.warning("[BUTTON FLOW] cartão do vendedor não enviado conv=%s: %s",
                       conversation_id, exc)


# ── Estado ──────────────────────────────────────────────────────────────────
def _reler_estado(conversation: dict):
    """Relê `flow_state` do banco. O dict em memória foi lido ANTES do lock.

    Sem isto o `lead_run_lock` que o gate adquire seria decorativo para este fluxo:
    ele serializa dois toques do mesmo lead, mas o segundo worker carrega um
    `conversation` capturado por `get_or_create_conversation` **antes** de entrar na
    fila do lock. Com o estado velho na mão, o segundo toque reexecuta a MESMA
    transição — segundo handoff, segunda tag, segunda mensagem — que é exatamente a
    duplicação de efeito de CRM que o lock existe para impedir (a race documentada
    do lead 5544991611703, `buffer/lead_lock.py`). Relido, o motor vê `encerrado` e
    devolve `ignorar`.

    Fail-soft: qualquer erro de leitura (ou conversa apagada) cai no estado em
    memória — um turno com estado levemente velho é melhor que um turno perdido.
    """
    conversation_id = conversation.get("id")
    try:
        atual = get_conversation(conversation_id)
    except Exception as exc:
        logger.warning(
            "[BUTTON FLOW] flow_state não relido p/ conv %s — usando o da memória: %s",
            conversation_id, exc,
        )
        return conversation.get("flow_state")
    if not isinstance(atual, dict):
        return conversation.get("flow_state")
    estado = atual.get("flow_state")
    conversation["flow_state"] = estado
    return estado


async def _persistir_estado(conversation: dict, estado_atual, campos: dict) -> None:
    """Merge em `conversations.flow_state`, preservando o que já estava lá.

    Preservar importa: `campaign_id` e `sent_at` são gravados pelo disparo e são o
    único vínculo entre o clique e a onda que o produziu — 122 de 1.200 mensagens de
    broadcast foram persistidas com `wamid=NULL`, então a atribuição por
    `quoted_wamid` acerta só 62%. Sobrescrever o estado inteiro aqui destruiria a
    métrica por botão, que é *a* métrica deste projeto.
    """
    base = dict(estado_atual) if isinstance(estado_atual, dict) else {}
    base.update(campos)
    base["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        await asyncio.to_thread(update_conversation, conversation["id"], flow_state=base)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] flow_state não gravado p/ conv %s: %s",
                       conversation.get("id"), exc)
    conversation["flow_state"] = base


# ── Ponto de entrada ────────────────────────────────────────────────────────
async def run_button_flow(
    *, lead: dict, conversation: dict, channel: dict, provider,
    texto: str, message_type: str | None = None, metadata: dict | None = None,
    wamid: str | None = None,
) -> None:
    """Roda um turno do fluxo de botões. Nunca levanta.

    Chamado pelo gate de `buffer/processor.py`, que já persistiu o inbound. Daqui
    para a frente nenhum outro gate roda para esta conversa neste turno.
    """
    conversation_id = conversation.get("id")
    lead_id = lead.get("id")
    try:
        await _executar_turno(
            lead=lead, conversation=conversation, channel=channel, provider=provider,
            texto=texto, message_type=message_type, metadata=metadata, wamid=wamid,
        )
    except Exception as exc:
        # Fail-soft final: o lead está no número do vendedor, que vê a thread. Uma
        # exceção subindo daqui abortaria o worker do buffer e deixaria o turno sem
        # nenhum registro.
        logger.error(
            "[BUTTON FLOW] turno falhou conv=%s lead=%s wamid=%s: %s",
            conversation_id, lead_id, wamid, exc, exc_info=True,
        )


async def _executar_turno(
    *, lead: dict, conversation: dict, channel: dict, provider,
    texto: str, message_type: str | None, metadata: dict | None, wamid: str | None,
) -> None:
    conversation_id = conversation.get("id")
    lead_id = lead.get("id")

    if not config.enabled():
        # Redundante com o gate (que já checa o kill switch antes de tocar o banco),
        # de propósito: o runner é público e um chamador novo — worker de recontato,
        # script de rehearsal — não pode ligar o bot sem querer.
        logger.info("[BUTTON FLOW] kill switch OFF — nada a fazer conv=%s", conversation_id)
        return

    agora = datetime.now(timezone.utc)
    # Relê o estado do banco: o `conversation` chegou aqui lido antes do lead_run_lock
    # que o gate segura (`buffer/processor.py`, caminho do bot). Ver _reler_estado.
    estado_bruto = await asyncio.to_thread(_reler_estado, conversation)
    deal = await asyncio.to_thread(get_open_deal, lead_id)

    motivo = _motivo_para_nao_rodar(lead, estado_bruto, deal)
    if motivo:
        await _notificar_sem_rodar(lead, conversation, estado_bruto, motivo)
        return

    evento = _montar_evento(texto, message_type, metadata)
    estado, reiniciado, idade_horas = _envelhecer(estado_bruto, agora)
    if reiniciado:
        logger.info(
            "[BUTTON FLOW] estado com %.1f dias — reiniciando limpo conv=%s",
            (idade_horas or 0) / 24.0, conversation_id,
        )
    elif idade_horas is not None and idade_horas > _HORAS_JANELA_META:
        logger.info("[BUTTON FLOW] clique tardio (%.1fh) — retomando o nó conv=%s",
                    idade_horas, conversation_id)

    historico: list[dict] = []
    if isinstance(evento, engine.Texto):
        historico = await asyncio.to_thread(_historico, conversation_id)
        if await _e_autoresponder(evento.conteudo, historico, agora):
            # ~28% de todas as "respostas" da base são o robô de saudação do WhatsApp
            # Business do PRÓPRIO cliente. Responder isso é robô conversando com robô,
            # e gastar o nudge aqui queimaria a única reoferta de botões que o lead
            # tem direito — sem que nenhum humano tenha lido nada.
            logger.info("[BUTTON FLOW] autoresponder detectado — sem resposta conv=%s",
                        conversation_id)
            await asyncio.to_thread(
                effects.atualizar_metadata, lead,
                {"auto_reply": {"at": agora.isoformat(), "origem": "button_flow"}},
                rotulo="auto_reply",
            )
            return
        if config.classifier_enabled():
            classe = await _classificar(evento.conteudo, historico)
            if classe:
                logger.info("[BUTTON FLOW] texto classificado como %s conv=%s",
                            classe, conversation_id)
                evento = engine.Classificado(classe)

    contexto = await asyncio.to_thread(_montar_contexto, lead)
    decisao = engine.decidir(
        estado, evento,
        canal_do_vendedor=(channel or {}).get("mode") == "human",
        contexto=contexto,
    )

    if decisao.ignorar and reiniciado:
        # Clique de nível 2 ("Em 60 dias") chegando num estado que acabou de reiniciar
        # no nível 1: o motor o ignora — corretamente, porque no nó de interesse ele
        # não significa nada. Mas ignorar em silêncio deixaria sem resposta alguém que
        # acabou de tocar num botão nosso. Reoferece o menu, que é o que a regra de
        # ">7 dias recomeça limpo" pede. Dado, não lógica: os textos continuam em flows.
        trilha = engine.trilha_de(estado)
        decisao = engine.Decisao(
            proximo_no=flows.NO_INTERESSE,
            mensagem=engine.Mensagem(
                corpo=flows.CORPO_NUDGE_POR_NO[flows.NO_INTERESSE],
                botoes=flows.BOTOES_POR_TRILHA[trilha],
            ),
            # Consome o nudge como qualquer reoferta: "fallback ≤ 2, sempre". Sem isto
            # o lead teria direito a uma reoferta a mais que os outros, e nenhum nó
            # pode ficar sem saída para humano.
            marcar_nudge=True,
        )
    elif decisao.ignorar:
        logger.info("[BUTTON FLOW] evento ignorado (nó=%s) conv=%s wamid=%s",
                    decisao.proximo_no, conversation_id, wamid)
        return

    avancar = await asyncio.to_thread(
        effects.aplicar, decisao.efeitos, lead=lead, conversation_id=conversation_id,
        # Só é lida quando `efeitos.optout`, mas montada sempre: o custo é um dict e
        # a alternativa é o chamador ter que adivinhar aqui qual decisão o motor tomou.
        evidencia=_evidencia_do_turno(evento, texto, wamid),
    )
    if not avancar:
        logger.error(
            "[BUTTON FLOW] efeitos bloquearam o turno (opt-out não gravado) — sem envio "
            "e sem avanço de nó conv=%s lead=%s", conversation_id, lead_id,
        )
        return

    await _enviar(decisao, lead=lead, conversation=conversation, provider=provider)

    trilha = decisao.trilha_inferida or engine.trilha_de(estado)
    nudged = bool((estado or {}).get("nudged")) if isinstance(estado, dict) else False
    campos = {
        "flow": flows.FLOW_ID,
        "node": decisao.proximo_no,
        "nudged": nudged or decisao.marcar_nudge,
        "trilha": trilha,
    }
    if deal and deal.get("stage_id"):
        # Referência do guarda "o João já mexeu no card" no próximo turno. `stage_id`
        # é a ÚNICA coluna de etapa que `get_open_deal` projeta
        # (`app/leads/service.py:1074`); gravar `deal["stage"]` deixava o guarda de
        # `_motivo_para_nao_rodar` sem referência nenhuma, ou seja, morto.
        campos["deal_stage_id"] = deal["stage_id"]
    await _persistir_estado(conversation, estado, campos)
    logger.info(
        "[BUTTON FLOW] turno aplicado conv=%s nó=%s trilha=%s nudged=%s",
        conversation_id, decisao.proximo_no, trilha, campos["nudged"],
    )


async def _notificar_sem_rodar(
    lead: dict, conversation: dict, estado, motivo: str,
) -> None:
    """Sai de cena e avisa. Uma anotação por conversa, não por mensagem.

    Sem o guard de repetição, um lead conversando com o João depois do transbordo
    encheria o histórico de notas idênticas do bot — ruído em cima justamente da
    conversa mais valiosa.
    """
    conversation_id = conversation.get("id")
    logger.info("[BUTTON FLOW] não roda conv=%s: %s", conversation_id, motivo)
    if isinstance(estado, dict) and estado.get("notificado_humano"):
        return
    await asyncio.to_thread(
        effects.anotar, lead.get("id"), conversation_id,
        f"🤖 [RECUPERAÇÃO] Bot de botões saiu de cena nesta conversa: {motivo}.",
    )
    campos = {"notificado_humano": True}
    if not (isinstance(estado, dict) and estado.get("flow")):
        # Gravar só o marcador deixaria um flow_state sem `flow`/`node`, que o motor
        # lê como incompatível. Carimba o equivalente ao estado ausente (é o que
        # `_estado_valido` assume para `{}`), para o dia em que o humano devolver a
        # conversa não começar por um estado corrompido.
        campos.update({"flow": flows.FLOW_ID, "node": flows.NO_INTERESSE, "nudged": False})
    await _persistir_estado(conversation, estado, campos)

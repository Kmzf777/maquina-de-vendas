import asyncio
import base64
import logging
import re as _re_dedup
import unicodedata as _unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from app.leads.service import (
    update_lead, save_message, create_deal, get_lead, get_history,
    apply_optout_side_effects, append_lead_observation, move_lead_deals_to_perdido,
    move_open_deal_for_handoff, resolve_send_target, lead_has_active_relationship,
    add_tags_to_lead, move_deal_to_vendor_pipeline, vendor_user_id_for_segment,
    ensure_segment_deal, mark_deal_qualificado,
    get_relationship_summary,
)
from pydantic import ValidationError as _PydanticValidationError
from app.agent.catalog import _fetch_active_products, _normalize as _normalize_catalog
from app.agent.pricing import (
    MAX_DISAMBIGUATION, OrcamentoInput, LineQuote, match_products, parse_brl,
    resolve_region, compute_quote, format_quote, fmt_brl,
)

# Vocabulário CONTROLADO de tags que a IA pode aplicar (allowlist). Deve espelhar o seed
# da tabela `tags` (2026-06-22). 2ª trava (além do enum no schema): o executor descarta
# qualquer valor fora desta lista, e add_tags_to_lead nunca cria tags novas.
_TAG_ALLOWLIST: frozenset[str] = frozenset({
    "B2B", "B2C", "Revenda", "Marca Própria", "Exportação",
    "Urgente", "Já é Cliente", "Pediu Humano", "Objeção: Preço", "Objeção: Prazo",
})
# Tags de ENCERRAMENTO: sinalizam que o lead não deve mais ser auto-prospectado
# (já é cliente / já pediu para falar com um humano). Aplicá-las cancela os follow-ups
# standard pendentes — é o gancho de código para o "equivalente da Regra 27".
_CLOSE_TAGS: frozenset[str] = frozenset({"Já é Cliente", "Pediu Humano"})
from app.conversations.service import update_conversation, get_conversation, get_history as get_conversation_history
from app.whatsapp.registry import get_provider
from app.whatsapp.meta import extract_wamid
from app.channels.service import get_channel_for_lead
from app.follow_up.service import (
    schedule_handoff_rescue, cancel_followups_by_phone, schedule_ai_return,
    find_pending_ai_return,
)

logger = logging.getLogger(__name__)

_TZ_BR = timezone(timedelta(hours=-3))

# Per-conversation deferred media queue: photos queued during tool execution that
# should be dispatched by the processor AFTER the text response is sent.
# Keyed by conversation_id to avoid cross-contamination between concurrent calls.
_deferred_media: dict[str, list[dict]] = {}


def pop_deferred_media(conversation_id: str) -> list[dict]:
    """Return and clear deferred media for a conversation.

    Each entry: {"b64": str, "mimetype": str, "caption": str, "marker": str,
    "catalog": bool}. Called by processor.py after text bubbles are sent.
    """
    return _deferred_media.pop(conversation_id, [])


def record_deferred_media_delivery(lead_id: str, conversation_id: str | None, groups: list[dict]) -> None:
    """Persiste o marcador de entrega de mídia APÓS o envio real (verdade-no-marcador).

    Auditoria Wander (5567999295671, 08/07): o marcador "[enviar_fotos] ... enviadas"
    nascia no ENFILEIRAMENTO; quando o turno era superseded/handoff a fila era drenada
    sem enviar, mas o marcador ficava — o dedup da tool recusava reenvio para sempre e
    o modelo negava a realidade do lead ("as fotos já foram enviadas"). O marcador (e o
    carimbo metadata.catalog_shown do backstop de follow-up) agora só existem com
    entrega confirmada, com contagem honesta (k/n). Grupo com sent=0 não deixa rastro,
    então a tool pode reenviar no turno seguinte.

    Fail-soft: telemetria/carimbo nunca derrubam o turno que já entregou a mídia.
    """
    delivered_catalog = False
    for g in groups:
        if not g.get("marker") or not g.get("sent"):
            continue
        try:
            save_message(
                lead_id, "system",
                f"{g['marker']} ({g['sent']}/{g['total']})",
                conversation_id=conversation_id,
            )
        except Exception as exc:
            logger.error(
                "record_deferred_media_delivery: falha ao gravar marcador p/ lead %s: %s",
                lead_id, exc,
            )
        delivered_catalog = delivered_catalog or bool(g.get("catalog"))
    if not delivered_catalog:
        return
    # Item 3 (backstop): marca que o catálogo foi APRESENTADO DE FATO. A rede de
    # segurança de follow-up usa essa flag p/ entregar ao João o lead qualificado que
    # viu catálogo e ficou inativo (caso Joabe).
    try:
        _cf_meta = dict((get_lead(lead_id) or {}).get("metadata") or {})
        if not _cf_meta.get("catalog_shown"):
            _cf_meta["catalog_shown"] = True
            _cf_meta["catalog_shown_at"] = datetime.now(_TZ_BR).isoformat()
            update_lead(lead_id, metadata=_cf_meta)
    except Exception as _cf_exc:
        logger.error("record_deferred_media_delivery: falha ao marcar catalog_shown p/ lead %s: %s", lead_id, _cf_exc)


# Per-conversation flag: set when the LLM calls marcar_interesse during this turn.
# Popped by the processor to decide whether to (re)schedule follow-ups.
_interest_marked: dict[str, dict] = {}


def pop_interest_marked(conversation_id: str) -> dict | None:
    """Return and clear the interest signal for a conversation (None if not set)."""
    return _interest_marked.pop(conversation_id, None)


# Sinal determinístico "este turno cotou preço" (Frente B3 — casos Samuel/Angelo 01-02/07:
# leads receberam preço, sumiram e NENHUM follow-up foi agendado porque o gatilho dependia
# do LLM chamar marcar_interesse). Setado quando calcular_orcamento resolve valores;
# consumido pelo processor no bloco de agendamento.
_quote_executed: dict[str, bool] = {}


def pop_quote_executed(conversation_id: str) -> bool:
    """Return and clear the quote-executed signal for a conversation (False if not set)."""
    return _quote_executed.pop(conversation_id, False)


PHOTO_CAPTIONS: dict[str, dict[str, str]] = {
    "atacado": {
        "foto_1": "Classico — torra media-escura, notas achocolatadas",
        "foto_2": "Suave — torra media, notas de melaco e frutas amarelas",
        "foto_3": "Canela — caramelizado com toque de canela",
        "foto_4": "Microlote — notas de mel, caramelo e cacau",
        "foto_5": "Drip Coffee e Capsulas Nespresso",
    },
    "private_label": {
        "foto_1": "Embalagem personalizada com sua marca",
        "foto_2": "Modelo de embalagem standup",
        "foto_3": "Exemplo de silk com logo do cliente",
        "foto_4": "Produto final pronto para comercializacao",
    },
}

PRODUTO_PHOTO_MAP: dict[str, dict[str, dict[str, str]]] = {
    "atacado": {
        "classico": {"file": "foto_1.jpg", "caption": "Classico — torra media-escura, notas achocolatadas"},
        "suave": {"file": "foto_2.jpg", "caption": "Suave — torra media, notas de melaco e frutas amarelas"},
        "canela": {"file": "foto_3.png", "caption": "Canela — caramelizado com toque de canela"},
        "microlote": {"file": "foto_4.jpg", "caption": "Microlote — notas de mel, caramelo e cacau"},
        "drip": {"file": "foto_5.jpg", "caption": "Drip Coffee e Capsulas Nespresso"},
        "capsulas": {"file": "foto_5.jpg", "caption": "Drip Coffee e Capsulas Nespresso"},
    },
    "private_label": {
        "embalagem": {"file": "foto_1.jpg", "caption": "Embalagem personalizada com sua marca"},
        "standup": {"file": "foto_2.jpg", "caption": "Modelo de embalagem standup"},
        "silk": {"file": "foto_3.jpg", "caption": "Exemplo de silk com logo do cliente"},
        "final": {"file": "foto_4.jpg", "caption": "Produto final pronto para comercializacao"},
    },
}

# Voz da persona também no fallback (auditoria 08/07: no outage do LLM, leads
# receberam "Perfeito! Seu atendimento agora será continuado..." — maiúsculas,
# "!", emoji e ponto final quebraram a máscara no momento mais frágil).
_HANDOFF_MSG = (
    "seu atendimento agora segue com o João, um dos nossos especialistas\n\n"
    "toca no link aqui embaixo e manda um oi pra ele agora, que ele já te atende "
    "com prioridade\n"
    "http://wa.me/553491461669\n\n"
    "assim que você chamar, ele já recebe seu contato e segue contigo"
)

# Marcador de handoff no RETORNO da tool (fix S1, caso Prof. Sebastião 11/07): o
# sentinel do orchestrator detecta handoff também quando ele acontece em CASCATA
# (qualificar_lead com âncoras completas chama encaminhar_humano por dentro e propaga
# este retorno verbatim) — o nome da tool não aparece nos function_calls do turno.
# A string final ("Lead encaminhado para <vendedor>") deve permanecer IDÊNTICA: o
# watchdog/telemetria de QA casa com 'Lead encaminhado%' em system messages.
HANDOFF_RESULT_PREFIX = "Lead encaminhado para "

# Supervisor para quem o atendimento é transbordado — o cartão de contato (vCard) é
# enviado automaticamente logo após a mensagem de despedida no encaminhar_humano.
# Públicas (Frente B1): a ponte pós-handoff do buffer/processor.py também consome estas
# constantes (reenvio do cartão do João). Aliases privados mantidos por retrocompatibilidade
# (ex.: test_encaminhar_humano_pipeline.py importa _SUPERVISOR_NAME/_SUPERVISOR_PHONE).
SUPERVISOR_NAME = "João - Café Canastra"
SUPERVISOR_PHONE = "553491461669"
_SUPERVISOR_NAME = SUPERVISOR_NAME
_SUPERVISOR_PHONE = SUPERVISOR_PHONE
# Teto de segurança para a mensagem de despedida escrita pela IA (usabilidade WhatsApp).
_MAX_DESPEDIDA_LEN = 600

# Despedidas default dos DESCARTES — enviadas pela PRÓPRIA tool (forense 11/07):
# as tools desligam ai_enabled no meio do turno e a trava B2 do processor
# (_ai_still_enabled) aborta as bolhas do próprio turno, então a despedida escrita
# no texto do turno NUNCA sai. Paridade com o handoff (_HANDOFF_MSG): a tool envia
# antes de desligar a flag. Voz da persona: minúsculas, sem ponto final.
_SEM_INTERESSE_MSG = (
    "tranquilo, sem problema\n\n"
    "fico por aqui à disposição — quando fizer sentido, é só me chamar"
)
_OPTOUT_MSG = (
    "sem problema, não te mando mais mensagem por aqui\n\n"
    "qualquer coisa, é só chamar"
)

TOOL_DECLARATIONS: list[dict] = [
    {
        "name": "salvar_nome",
        "description": "Salva o nome do lead quando descoberto durante a conversa",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do lead"}
            },
            "required": ["name"],
        },
    },
    {
        "name": "mudar_stage",
        "description": (
            "Transfere o lead para outro stage de forma silenciosa — nunca avise o cliente. "
            "Gatilhos: "
            "atacado — revenda, distribuidora, cafeteria, restaurante ou negocio querendo cafe em volume; "
            "private_label — marca propria, embalagem personalizada ou identidade visual propria; "
            "exportacao — mercado externo ou pais de destino; "
            "consumo — pessoa fisica para uso proprio. "
            "Execute ao identificar o gatilho, sem perguntar. "
            "Mude SOMENTE com declaracao EXPLICITA do lead sobre a propria necessidade; "
            "fala ambigua, social ou audio truncado NAO e gatilho. Voltar a um stage "
            "anterior exige correcao explicita do lead ('na verdade eu quero X')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "enum": ["secretaria", "atacado", "private_label", "exportacao", "consumo"],
                    "description": "Stage de destino",
                }
            },
            "required": ["stage"],
        },
    },
    {
        "name": "encaminhar_humano",
        "description": (
            "Registra o encerramento da interacao e transfere o controle para o supervisor Joao. "
            "USE quando: "
            "(1) lead qualificado e pronto para avancar — SOMENTE com finalidade concreta declarada "
            "(o que quer fazer com o cafe/marca) E sinal ativo de avanco (pergunta de "
            "preco/prazo/pedido, confirmacao verbal explicita). Emojis, monossilabos ('sim', 'ok') "
            "e simpatia social NAO qualificam sozinhos — continue a descoberta ou use qualificar_lead; "
            "(2) lead REJEITOU explicitamente o modelo de negocio — passe motivo='Cliente nao aceitou o modelo de negocio'; "
            "(3) circuit breaker: 6+ turnos no stage atacado sem handoff, ou 8+ no private_label — chame imediatamente. "
            "NAO use para despedida amigavel ('obrigado', 'vou pensar') — nao e rejeicao. "
            "Passe no argumento `mensagem_despedida` uma despedida/transbordo curta (2-3 frases) baseada no contexto. "
            "SE a ultima mensagem do lead tem pergunta que voce sabe responder (preco, lote minimo, prazo), "
            "a `mensagem_despedida` COMECA respondendo-a e SO depois faz o transbordo — NUNCA deixe a pergunta sem "
            "resposta (o lead nao pode receber o cartao no lugar da resposta). "
            "O sistema envia a mensagem e, em seguida, o cartao do Joao — NAO cole telefone, link ou wa.me. "
            "Esta ferramenta ENCERRA a conversa automatica: apos chama-la, NAO envie mais nenhuma mensagem."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mensagem_despedida": {
                    "type": "string",
                    "description": (
                        "Despedida/transbordo curta e personalizada, enviada como texto seguida do cartao do Joao. "
                        "Se o lead acabou de perguntar preco/lote/prazo, a resposta vem PRIMEIRO, na propria mensagem. "
                        "DIRECIONE A ACAO PRO LEAD: e o LEAD que toca no cartao pra chamar — convide-o a isso. "
                        "NAO use 'vou te conectar'/'ja te transfiro' (falsa impressao de que voce faz a ponte). "
                        "NAO inclua telefone, link nem wa.me."
                    ),
                },
                "vendedor": {"type": "string", "description": "Nome do vendedor (opcional — omita em casos de rejeicao)"},
                "motivo": {"type": "string", "description": "Motivo do encaminhamento ou encerramento"},
            },
            "required": ["mensagem_despedida"],
        },
    },
    {
        "name": "qualificar_lead",
        "description": (
            "Registra as ÂNCORAS de qualificação do lead à medida que voce as descobre na "
            "conversa. Chame assim que captar cada uma — NAO espere o lead pedir pra comprar. "
            "Âncoras: finalidade (para que o lead quer o cafe: revenda, cafeteria, restaurante, "
            "marca propria, etc.), volume (quanto pretende: kg, pacotes, fardos, pedido mensal), "
            "urgencia (quando pretende comprar/decidir). Passe apenas as que ja souber; pode "
            "chamar de novo depois pra completar. Quando finalidade E volume ja estiverem "
            "definidos, o sistema transfere o lead pro vendedor automaticamente — voce NAO "
            "precisa chamar encaminhar_humano nesse caso."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "finalidade": {"type": "string", "description": "Para que o lead quer o cafe (revenda, cafeteria, restaurante, marca propria, etc.)"},
                "volume": {"type": "string", "description": "Volume/quantidade pretendida (kg, pacotes, fardos, pedido mensal)"},
                "urgencia": {"type": "string", "description": "Prazo/urgencia da compra ou decisao (opcional)"},
            },
            "required": [],
        },
    },
    {
        "name": "registrar_optout",
        "description": (
            "HARD OPT-OUT (descarte definitivo). Use SOMENTE quando o lead PROIBIR explicitamente o contato: "
            "pedir para parar de receber mensagens, 'me tira da lista', ameacar processar/denunciar, "
            "ou clicar no botao 'Parar mensagens'. "
            "Efeito: opt_out=true, IA desativada, lead na Blacklist. "
            "NAO confunda com falta de interesse no momento ('to sem grana', 'ja fechei com outro') — isso NAO e "
            "opt-out: use registrar_sem_interesse_atual. "
            "A despedida vai no parametro mensagem_despedida — a PROPRIA tool envia por voce. "
            "NAO a escreva no texto do turno (seria descartada) e, apos chamar, NAO envie mais nenhuma mensagem."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "motivo": {
                    "type": "string",
                    "description": (
                        "O que o lead disse, com o maximo de detalhe: pedido/ameaca exata e contexto "
                        "(ex: 'clicou parar mensagens', 'pediu para sair da lista — disse que recebe spam demais'). "
                        "Evite generico; capture as palavras reais do lead."
                    ),
                },
                "mensagem_despedida": {
                    "type": "string",
                    "description": (
                        "UMA mensagem de despedida respeitosa e breve, na sua voz (minuscula, sem ponto "
                        "final). Ex: 'sem problema, nao te mando mais mensagem por aqui\\n\\nqualquer "
                        "coisa, e so chamar'. A tool envia este texto ao lead antes de encerrar."
                    ),
                },
            },
            "required": ["motivo"],
        },
    },
    {
        "name": "registrar_sem_interesse_atual",
        "description": (
            "SOFT REJECTION (perda, NAO e opt-out). Use quando o lead nao quer avancar a compra AGORA mas NAO "
            "proibiu o contato: 'to sem grana', 'ja fechei com outro fornecedor', 'agora nao da', "
            "ou objecao de preco/momento nao contornada. "
            "Efeito: tira o lead do funil (stage=perdido, IA desativada, deal movido para Perdido), MAS mantem "
            "o lead na base para reativacao futura — opt_out continua FALSE, SEM blacklist. "
            "NUNCA use se o lead proibiu o contato — nesse caso use registrar_optout. "
            "NUNCA use para ADIAMENTO MORNO — lead que pede tempo e PROMETE voltar ('vou analisar e te "
            "chamo', 'te dou um retorno', 'vou ver com meu socio') NAO e rejeicao: "
            "responda curto e cordial e, se houver prazo, use agendar_retorno; sem prazo, encerre o "
            "turno SEM tool (o follow-up automatico cuida). So registre quando o lead "
            "REAFIRMAR a negativa ou ela for definitiva. "
            "A despedida vai no parametro mensagem_despedida — a PROPRIA tool envia por voce. "
            "NAO a escreva no texto do turno (seria descartada) e, apos chamar, NAO envie mais nenhuma mensagem."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "motivo": {
                    "type": "string",
                    "description": (
                        "Motivo DETALHADO e analitico da perda — nunca generico ('nao quis'). Capture: objecao real "
                        "nao superada, concorrente citado, volume/ticket discutido e o contexto por tras "
                        "(ex: 'objecao de preco vs fornecedor a R$18/kg; ~30kg/mes pra cafeteria; reavalia no proximo trimestre')."
                    ),
                },
                "mensagem_despedida": {
                    "type": "string",
                    "description": (
                        "UMA mensagem de despedida cordial deixando a PORTA ABERTA, na sua voz (minuscula, "
                        "sem ponto final). Ex: 'sem problema, fico a disposicao\\n\\nquando fizer sentido, "
                        "e so me chamar aqui'. A tool envia este texto ao lead antes de encerrar."
                    ),
                },
            },
            "required": ["motivo"],
        },
    },
    {
        "name": "registrar_numero_errado",
        "description": (
            "NUMERO POSSIVELMENTE ERRADO (higiene, NAO e opt-out). Use quando quem responde NEGA ser a pessoa "
            "do cadastro SEM se identificar ('nao sou eu', 'numero errado', 'nao conheco', 'esse celular nao e "
            "mais da/do X'). Efeito: marca o numero para higiene automatica — se NINGUEM responder em 72h, o "
            "sistema registra opt-out sozinho e o numero nunca mais recebe disparo. NAO desativa a IA nem "
            "encerra a conversa: continue o arco normal (desculpa leve + UMA pergunta de re-engajamento). "
            "Se a pessoa se identificar depois, o marcador e limpo automaticamente. "
            "NAO use quando a pessoa AFIRMA o proprio nome (isso e correcao de cadastro — use salvar_nome)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "contexto": {
                    "type": "string",
                    "description": (
                        "O que a pessoa disse, literal (ex.: \"clicou Nao e escreveu 'nao conheco'\", "
                        "\"disse que esse celular nao e mais da Magda\")."
                    ),
                }
            },
            "required": ["contexto"],
        },
    },
    {
        "name": "registrar_indicacao",
        "description": (
            "INDICACAO / REFERRAL. Use quando o lead indicar OUTRA pessoa como o contato certo para o negocio: "
            "vendeu/fechou a loja e diz quem ficou com ela, 'quem cuida disso agora e o Fulano', 'fala com meu "
            "socio', ou oferece repassar seu contato ao sucessor. Efeito: grava a indicacao no CRM (nota + tag) "
            "para o time humano acionar o indicado — a tool NAO cria lead novo nem dispara mensagem a terceiro. "
            "Chame UMA vez por indicacao, assim que o lead der a informacao; capture nome/telefone se ele der, "
            "mas o contexto sozinho ja vale o registro. Depois de chamar, agradeca com naturalidade."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "contexto": {
                    "type": "string",
                    "description": (
                        "A historia da indicacao com as palavras do lead (ex.: 'vendeu a Divina Terra em maio; "
                        "quem assumiu foi o antigo gerente, vai continuar com cafe especial')."
                    ),
                },
                "nome": {
                    "type": "string",
                    "description": "Nome do indicado, se o lead informou. Vazio se nao deu.",
                },
                "telefone": {
                    "type": "string",
                    "description": "Telefone/WhatsApp do indicado, se o lead informou. Vazio se nao deu.",
                },
            },
            "required": ["contexto"],
        },
    },
    {
        "name": "enviar_fotos",
        "description": "Envia catalogo de fotos dos produtos ao lead",
        "parameters": {
            "type": "object",
            "properties": {
                "categoria": {
                    "type": "string",
                    "enum": ["atacado", "private_label"],
                    "description": "Categoria do catalogo",
                }
            },
            "required": ["categoria"],
        },
    },
    {
        "name": "enviar_foto_produto",
        "description": "Envia a foto de UM produto especifico ao lead com descricao. Use para intercalar texto e foto na conversa.",
        "parameters": {
            "type": "object",
            "properties": {
                "categoria": {
                    "type": "string",
                    "enum": ["atacado", "private_label"],
                    "description": "Categoria do produto",
                },
                "produto": {
                    "type": "string",
                    "description": "Nome do produto (ex: classico, suave, canela, microlote, drip, capsulas, embalagem, standup, silk, final)",
                },
            },
            "required": ["categoria", "produto"],
        },
    },
    {
        "name": "marcar_interesse",
        "description": (
            "Marca que o lead demonstrou INTERESSE COMERCIAL CLARO nesta conversa "
            "(ex: perguntou preço/condições, pediu detalhes para comprar, demonstrou intenção real de avançar). "
            "NÃO use para resposta educada, 'ok', 'obrigado', 'vou pensar', saudação, ou curiosidade vaga. "
            "Só o interesse genuíno habilita o follow-up automático."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "nivel": {
                    "type": "string",
                    "enum": ["morno", "quente"],
                    "description": "Nivel de interesse do lead",
                },
                "motivo": {
                    "type": "string",
                    "description": "Breve descricao do sinal de interesse observado",
                },
            },
            "required": [],
        },
    },
    {
        "name": "adicionar_tag_lead",
        "description": (
            "Etiqueta o lead com uma ou mais tags do CRM ao identificar perfil, intencao "
            "ou objecao durante a conversa. Use SOMENTE tags da lista permitida (enum abaixo) "
            "— nunca invente variacoes (ex.: 'b2b', 'cliente novo'). Pode chamar mais de uma "
            "vez na conversa; tags repetidas sao ignoradas. Aplicacao silenciosa: nao avise "
            "o cliente sobre a marcacao."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "B2B", "B2C", "Revenda", "Marca Própria", "Exportação",
                            "Urgente", "Já é Cliente", "Pediu Humano",
                            "Objeção: Preço", "Objeção: Prazo",
                        ],
                    },
                    "description": "Tags a aplicar (apenas valores do enum).",
                }
            },
            "required": ["tags"],
        },
    },
    {
        "name": "retomar_contato_vendedor",
        "description": (
            "Reconecta ao vendedor Joao Bras um lead que JA teve atendimento com ele e esfriou "
            "(reativacao). USE somente apos as 3 etapas: "
            "(1) investigou por que o atendimento anterior nao avancou e contornou a objecao; "
            "(2) o lead demonstrou que quer retomar; "
            "(3) perguntou EXPLICITAMENTE se pode encaminha-lo ao Joao e o lead respondeu SIM. "
            "Dispara mensagem pelo numero do Joao — AGORA se em horario comercial "
            "(09h-16h, dias uteis), senao AGENDA para o proximo dia util — e ENCERRA a conversa automatica (desativa a IA). "
            "O retorno informa se foi AGORA ou AGENDADO: use isso na despedida "
            "('o Joao acabou de te chamar' vs 'o Joao vai te chamar amanha de manha'). "
            "Apos chama-la, escreva APENAS a despedida e NAO envie mais nada. "
            "NAO use sem o SIM explicito. Para lead novo/qualificado, use encaminhar_humano."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "motivo": {
                    "type": "string",
                    "description": "Breve resumo do que esfriou o atendimento anterior e do que o lead quer retomar",
                }
            },
            "required": [],
        },
    },
    {
        "name": "agendar_retorno",
        "description": (
            "Agenda VOCE MESMA um retorno futuro a este lead quando ele pede para falar "
            "depois (ex.: 'me chama sexta', 'daqui a 2 horas'). "
            "No horario combinado voce reabre a conversa automaticamente — NAO dependa do "
            "follow-up generico nem de humano. "
            "Passe `data_hora` em ISO 8601 COM fuso (-03:00), calculada a partir de hoje "
            "(2026) — nunca data vaga. Horarios fora do comercial (09h-16h, dias uteis) sao "
            "ajustados para o proximo valido. "
            "Apos agendar, confirme ao lead com naturalidade e siga a conversa (NAO encerra "
            "o atendimento nem desativa a IA)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "data_hora": {
                    "type": "string",
                    "description": (
                        "Data e hora do retorno em ISO 8601 com fuso de Brasilia (-03:00). "
                        "Ex.: '2026-06-27T14:00:00-03:00'. Calcule a partir da data de hoje."
                    ),
                },
                "motivo": {
                    "type": "string",
                    "description": (
                        "O que ficou combinado / por que retornar (ex.: 'lead pediu retorno "
                        "na sexta para fechar pedido de 30kg')."
                    ),
                },
                "contexto": {
                    "type": "string",
                    "description": (
                        "Opcional: contexto extra para voce usar na volta (objecao pendente, "
                        "produto de interesse, volume discutido)."
                    ),
                },
            },
            "required": ["data_hora", "motivo"],
        },
    },
    {
        "name": "consultar_relacionamento",
        "description": (
            "Consulta o histórico de relacionamento do lead no CRM: se já é cliente ativo, "
            "última compra e produto. "
            "CHAME ANTES de qualificar quando: o <crm_data> ou <lead_memory> sugerir cliente "
            "antigo; o lead usar termos de recompra ('repor', 'novo pedido', 'sempre compro'); "
            "ou houver QUALQUER suspeita. Retorna string descritiva — decida entre "
            "reabastecimento/upsell (NÃO rode funil de lead novo com cliente ativo) ou prospecto frio."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "calcular_orcamento",
        "description": (
            "Calcula o orçamento determinístico do pedido a partir de um carrinho de produtos do setor atacado. "
            "É OBRIGATÓRIO chamar esta ferramenta para QUALQUER pergunta de preço, valor de pedido, frete, "
            "total ou pedido mínimo — é PROIBIDO somar, multiplicar, estimar ou inventar qualquer valor de "
            "cabeça. "
            "Se faltar a quantidade ou o estado, pergunte antes de calcular. "
            "Recebe um carrinho (`itens`: lista de objetos com `produto` e `quantidade`), "
            "`estado` (sigla UF, ex.: SP) e `cidade` opcionais. "
            "Retorna orçamento com breakdown item a item, subtotal global, frete e total."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "itens": {
                    "type": "array",
                    "description": "Lista de produtos do carrinho com nome e quantidade",
                    "items": {
                        "type": "object",
                        "properties": {
                            "produto": {
                                "type": "string",
                                "description": "Nome ou parte do nome do produto desejado",
                            },
                            "quantidade": {
                                "type": "integer",
                                "description": "Quantidade do produto (deve ser > 0)",
                            },
                        },
                        "required": ["produto", "quantidade"],
                    },
                },
                "estado": {
                    "type": "string",
                    "description": (
                        "Sigla do estado (UF), ex.: SP, MG, BA. "
                        "Opcional — pergunte ao lead se não souber."
                    ),
                },
                "cidade": {
                    "type": "string",
                    "description": (
                        "Cidade do lead. Opcional — necessário apenas para cidades com "
                        "frete especial (ex.: Uberlândia, frete flat R$15)."
                    ),
                },
            },
            "required": ["itens"],
        },
    },
]


def get_tools_for_stage(stage: str) -> list[dict]:
    """Return tools available for a given stage."""
    stage_tools = {
        "secretaria":    ["salvar_nome", "mudar_stage", "encaminhar_humano", "registrar_optout", "registrar_sem_interesse_atual", "registrar_numero_errado", "registrar_indicacao", "marcar_interesse", "retomar_contato_vendedor", "adicionar_tag_lead", "agendar_retorno", "consultar_relacionamento"],
        "atacado":       ["salvar_nome", "mudar_stage", "encaminhar_humano", "qualificar_lead", "registrar_optout", "registrar_sem_interesse_atual", "registrar_indicacao", "enviar_fotos", "enviar_foto_produto", "marcar_interesse", "retomar_contato_vendedor", "adicionar_tag_lead", "agendar_retorno", "consultar_relacionamento", "calcular_orcamento"],
        "private_label": ["salvar_nome", "mudar_stage", "encaminhar_humano", "qualificar_lead", "registrar_optout", "registrar_sem_interesse_atual", "registrar_indicacao", "enviar_fotos", "enviar_foto_produto", "marcar_interesse", "retomar_contato_vendedor", "adicionar_tag_lead", "agendar_retorno", "consultar_relacionamento", "calcular_orcamento"],
        "exportacao":    ["salvar_nome", "mudar_stage", "encaminhar_humano", "qualificar_lead", "registrar_optout", "registrar_sem_interesse_atual", "marcar_interesse", "retomar_contato_vendedor", "adicionar_tag_lead", "agendar_retorno", "consultar_relacionamento"],
        # Varejo B2C NÃO é "lead perdido": consumo NUNCA auto-descarta (sem
        # registrar_sem_interesse_atual). A saída legítima continua sendo opt-out (lead pede
        # pra parar) — handoff não se aplica ao self-service. (Auditoria lead 5551991295543.)
        "consumo":       ["salvar_nome", "mudar_stage", "registrar_optout", "marcar_interesse", "adicionar_tag_lead", "agendar_retorno", "consultar_relacionamento"],
    }
    allowed = stage_tools.get(stage, ["salvar_nome"])
    return [t for t in TOOL_DECLARATIONS if t["name"] in allowed]


def _normalize_text(s: str | None) -> str:
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", (s or "").lower())
        if unicodedata.category(c) != "Mn"
    )


# Sinais de PROIBICAO explicita de contato (HARD opt-out → Blacklist legítima).
_HARD_OPTOUT_SIGNALS = (
    "parar", "para de me", "nao quero mais mensagem", "nao quero mais contato",
    "nao me mande", "nao manda mais", "sair da lista", "tira da lista", "tirar da lista",
    "descadastr", "remover", "remova", "bloquear", "denunciar", "processar", "spam", "stop",
)
# Sinais de SOFT rejection (falta de momento de compra → Perdido, NUNCA Blacklist).
_SOFT_REJECTION_SIGNALS = (
    "interesse no momento", "sem interesse agora", "sem interesse no", "sem disponibilidade",
    "agora nao", "mais pra frente", "mais para frente", "sem tempo", "ja sou cliente",
    "ja compro", "ja fechei", "sem grana", "vou pensar", "talvez", "futuramente",
    "depois eu", "nao da agora", "deixa pra depois",
)


# Sinais, no motivo passado pelo LLM, de que o lead JÁ é cliente ativo (não um lead frio).
# Complementa lead_has_active_relationship: pega o caso em que o CRM ainda não marca o
# cliente (deal "novo"), mas o lead afirmou na conversa que já compra (ex.: Kadi Guth — motivo
# "Lead ja e cliente e nao tem demanda no momento").
_CLIENTE_ATIVO_SIGNALS = (
    "ja e cliente", "ja sou cliente", "ja e nosso cliente", "ja compra", "ja comprou",
    "ja trabalha com", "ja trabalho com", "cliente ativo", "cliente atual", "ja e parceir",
    "ja revende", "ja fechei com voces", "ja fechou com a gente",
)


def _motivo_indica_cliente(motivo: str | None) -> bool:
    """True se o motivo do descarte indica que o lead JÁ é cliente (não lead frio perdido)."""
    n = _normalize_text(motivo)
    return any(s in n for s in _CLIENTE_ATIVO_SIGNALS)


def _looks_like_soft_rejection(motivo: str | None) -> bool:
    """True se o motivo de opt-out tem cara de SOFT rejection sem proibição explícita.

    Defesa em profundidade contra falso positivo de Blacklist (auditoria 2026-06-22):
    "não tenho interesse no momento"/"sem disponibilidade" NÃO são opt-out.
    """
    n = _normalize_text(motivo)
    if any(h in n for h in _HARD_OPTOUT_SIGNALS):
        return False
    return any(s in n for s in _SOFT_REJECTION_SIGNALS)


def _normalize_for_dedup(text: str) -> str:
    """Normaliza p/ comparação de duplicata: minúsculas, sem acentos/pontuação, espaços colapsados."""
    t = (text or "").lower()
    t = _unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if not _unicodedata.combining(c))  # remove diacríticos (ã→a, ã→a)
    t = _re_dedup.sub(r"[^\w\s]", " ", t)        # remove pontuação/acentos-vizinhos de símbolo
    t = _re_dedup.sub(r"\s+", " ", t).strip()
    return t


def _recent_assistant_texts(conversation_id: str, limit: int = 4) -> list[str]:
    """Últimas bolhas 'assistant' já enviadas nesta conversa (para dedup do handoff). Fail-open: []."""
    try:
        history = get_conversation_history(conversation_id, limit=limit * 3) or []
        return [m.get("content") or "" for m in history if m.get("role") == "assistant"][-limit:]
    except Exception:
        return []


def _despedida_ja_enviada(conversation_id: str, despedida: str) -> bool:
    """True se a despedida do handoff é ~idêntica a uma bolha assistant já enviada (evita reenvio).

    Caso real (lead 5531999844461): a IA verbalizou o pitch de handoff num turno e, no turno seguinte,
    chamou encaminhar_humano com o MESMO texto → a tool reenviou (sent_by='handoff') = duplicata.
    Compara o início normalizado (primeiros ~60 chars) — robusto a reticências/truncamento.
    """
    target = _normalize_for_dedup(despedida)
    if not target:
        return False
    head = target[:60]
    for prev in _recent_assistant_texts(conversation_id):
        prev_n = _normalize_for_dedup(prev)
        if head and (head in prev_n or prev_n[:60] == head):
            return True
    return False


async def _send_despedida_descarte(
    lead_id: str, phone: str, conversation_id: str | None, args: dict, default_msg: str,
) -> None:
    """Envia a despedida do turno de descarte PELA PRÓPRIA TOOL, ANTES de desligar a IA.

    Forense 11/07 (leads 'Sim' e Anderson): as tools de descarte setam
    ai_enabled=False no meio do turno e a trava B2 do processor (_ai_still_enabled)
    aborta as bolhas do PRÓPRIO turno — a despedida pedida ao LLM no prompt nunca
    saía e o lead educado recebia silêncio. Paridade com encaminhar_humano:
    despedida do LLM via `mensagem_despedida` (fallback estático), teto de tamanho,
    dedup contra bolha ~idêntica já enviada. Fail-soft TOTAL: nenhuma falha aqui
    pode impedir o descarte em si.
    """
    try:
        channel = get_channel_for_lead(lead_id)
        if not channel:
            logger.warning(
                "_send_despedida_descarte: nenhum canal ativo p/ lead %s — sem despedida",
                lead_id,
            )
            return
        despedida = (args.get("mensagem_despedida") or "").strip() or default_msg
        if len(despedida) > _MAX_DESPEDIDA_LEN:
            despedida = despedida[:_MAX_DESPEDIDA_LEN].rstrip() + "…"
        if _despedida_ja_enviada(conversation_id, despedida):
            logger.info(
                "[DESCARTE DEDUP] despedida ~idêntica a bolha já enviada — pulando send "
                "(conv=%s)", conversation_id,
            )
            return
        lead = get_lead(lead_id) or {}
        provider = get_provider(channel)
        send_to = resolve_send_target(lead, phone)
        send_result = await provider.send_text(send_to, despedida)
        save_message(
            lead_id, "assistant", despedida, sent_by="agent",
            conversation_id=conversation_id, wamid=extract_wamid(send_result),
        )
        logger.info("_send_despedida_descarte: despedida enviada p/ lead %s", lead_id)
    except Exception as exc:
        logger.error(
            "_send_despedida_descarte: falha ao enviar despedida p/ lead %s (descarte segue): %s",
            lead_id, exc, exc_info=True,
        )


def apply_stage_transition(lead_id: str, conversation_id: str, new_stage: str) -> bool:
    """Efeito CANÔNICO de uma troca de stage — extraído do executor `mudar_stage` para ser
    reusado pelo gatilho determinístico de prefill (Trilha B, auditoria 10/07). Retorna True
    quando a transição foi aplicada, False no no-op idempotente.

    Idempotência (auditoria 10/07, caso Marisete): só é no-op quando lead E conversa já estão
    no stage pedido — divergência ainda re-sincroniza. O marcador system duplicado
    realimentaria o prompt e geraria writes redundantes. Fail-open: erro no fetch segue o
    caminho normal (aplica). `ensure_segment_deal` é fail-soft: nunca derruba a troca de stage.
    """
    try:
        _lead_stage = (get_lead(lead_id) or {}).get("stage")
        _conv_stage = (
            (get_conversation(conversation_id) or {}).get("stage")
            if conversation_id else _lead_stage
        )
        if _lead_stage == new_stage and _conv_stage == new_stage:
            return False
    except Exception:
        pass
    if conversation_id:
        update_conversation(conversation_id, stage=new_stage)
    update_lead(lead_id, stage=new_stage)
    # CRIAÇÃO ADIADA: ao classificar o segmento, o lead inbound (que não tinha card) ganha um
    # no funil correspondente. No-op p/ stage não-segmento ('pending'/'secretaria') ou se já
    # houver card. Fail-soft: nunca derruba a troca de stage.
    try:
        ensure_segment_deal(lead_id, new_stage)
    except Exception as exc:
        logger.error(
            "apply_stage_transition: falha ao garantir card de segmento (lead %s, stage %s): %s",
            lead_id, new_stage, exc, exc_info=True,
        )
    save_message(lead_id, "system", f"stage alterado para: {new_stage}", conversation_id=conversation_id)
    return True


def _recent_stage_marker_exists(conversation_id: str, stage: str, minutes: int = 15) -> bool:
    """True se há um marcador system `stage alterado para: <stage>` nos últimos `minutes` desta
    conversa — ou seja, o lead JÁ passou por esse stage recentemente (sinal de flapping quando
    a próxima mudança volta para ele). Telemetria pura (B2); fail-open=False: sem
    conversation_id ou erro de leitura, não sinaliza nada. NUNCA bloqueia a transição.
    """
    if not conversation_id:
        return False
    try:
        from app.db.supabase import get_supabase
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        res = (
            get_supabase().table("messages").select("id")
            .eq("conversation_id", conversation_id)
            .eq("role", "system")
            .eq("content", f"stage alterado para: {stage}")
            .gte("created_at", cutoff)
            .limit(1)
            .execute()
        )
        return bool(res.data)
    except Exception as exc:
        logger.debug("[STAGE FLAP] falha ao checar marcador recente p/ conv %s: %s", conversation_id, exc)
        return False


async def execute_tool(
    tool_name: str,
    args: dict[str, Any],
    lead_id: str,
    phone: str,
    conversation_id: str = "",
) -> str:
    """Execute a tool call and return a result string for the AI."""
    logger.info(f"Executing tool {tool_name} with args {args} for lead {lead_id}")

    if tool_name == "salvar_nome":
        update_lead(lead_id, name=args["name"])
        return f"Nome salvo: {args['name']}"

    elif tool_name == "adicionar_tag_lead":
        pedidas = args.get("tags") or []
        # 2ª trava (além do enum no schema): descarta qualquer tag fora da allowlist —
        # impede o modelo de inventar variações ("b2b", "Cliente_Novo").
        validas = [t for t in pedidas if t in _TAG_ALLOWLIST]
        descartadas = [t for t in pedidas if t not in _TAG_ALLOWLIST]
        if descartadas:
            logger.warning(
                "adicionar_tag_lead: tags fora da allowlist descartadas p/ lead %s: %s",
                lead_id, descartadas,
            )
        if not validas:
            return "Nenhuma tag válida — use apenas as tags permitidas."
        aplicadas = add_tags_to_lead(lead_id, validas)
        # Tags de ENCERRAMENTO (equivalente da Regra 27 — cliente já conectado ao time):
        # "Já é Cliente" / "Pediu Humano" significam "não auto-prospectar mais este lead".
        # A Valéria encerra sem chamar ferramenta de descarte, então é AQUI que matamos os
        # follow-ups standard pendentes (auditoria lead 5561984336980 — Daniel recebeu um
        # follow-up automático depois de dizer que já falava com um humano do time).
        # Não desativa IA nem marca perdido; só cancela os jobs (handoff_rescue preservado).
        if any(t in _CLOSE_TAGS for t in (aplicadas or validas)):
            try:
                cancel_followups_by_phone(phone, reason="lead_already_served")
            except Exception as exc:
                logger.error(
                    "adicionar_tag_lead: falha ao cancelar follow-ups para lead %s (phone %s): %s",
                    lead_id, phone, exc,
                )
        if aplicadas:
            return f"Tags aplicadas: {', '.join(aplicadas)}"
        return "Tags já estavam aplicadas (nenhuma nova)."

    elif tool_name == "mudar_stage":
        new_stage = args["stage"]
        # Telemetria de FLAPPING (B2, auditoria 10/07 — caso Nilson: private_label → atacado →
        # private_label em ~3 min reagindo a áudios ambíguos). SEM bloqueio: se já existe um
        # marcador recente "stage alterado para: <new_stage>" nesta conversa, esta chamada está
        # REVERTENDO para um stage por onde já passamos há pouco — só logamos para medir a
        # frequência. A transição SEMPRE prossegue (diretriz do usuário: precisão sem engessar).
        if _recent_stage_marker_exists(conversation_id, new_stage):
            logger.warning(
                "[STAGE FLAP] mudar_stage revertendo p/ stage recente '%s' (lead=%s, conv=%s) — "
                "possível flapping por sinal ambíguo; transição mantida (sem bloqueio).",
                new_stage, lead_id, conversation_id,
            )
        # Efeito canônico (idempotente, fail-soft) — compartilhado com o gatilho de prefill.
        if apply_stage_transition(lead_id, conversation_id, new_stage):
            return f"Stage alterado para: {new_stage}"
        return f"Lead já está no stage {new_stage} — nenhuma alteração necessária"

    elif tool_name == "qualificar_lead":
        # Item 3: persiste as âncoras de qualificação e, quando finalidade E volume já estão
        # definidos, dispara o handoff PROATIVAMENTE — a decisão sai do julgamento do modelo e
        # passa pro código (o modelo só relata âncoras). Rescata o "caso Joabe".
        _q_in = {
            "finalidade": (args.get("finalidade") or "").strip(),
            "volume": (args.get("volume") or "").strip(),
            "urgencia": (args.get("urgencia") or "").strip(),
        }
        try:
            _cur = get_lead(lead_id) or {}
            _meta = dict(_cur.get("metadata") or {})
            _anchors = dict(_meta.get("qualificacao") or {})
            for _k, _v in _q_in.items():
                if _v:
                    _anchors[_k] = _v
            _meta["qualificacao"] = _anchors
            update_lead(lead_id, metadata=_meta)
        except Exception as _q_exc:
            logger.error("qualificar_lead: falha ao persistir âncoras p/ lead %s: %s", lead_id, _q_exc)
            _anchors = {k: v for k, v in _q_in.items() if v}
        save_message(
            lead_id, "system",
            f"[qualificar_lead] finalidade={_anchors.get('finalidade')} "
            f"volume={_anchors.get('volume')} urgencia={_anchors.get('urgencia')}",
            conversation_id=conversation_id,
        )
        if _anchors.get("finalidade") and _anchors.get("volume"):
            logger.info("qualificar_lead: âncoras completas → handoff proativo (lead %s)", lead_id)
            return await execute_tool(
                "encaminhar_humano",
                {
                    "vendedor": "João Brás",
                    "motivo": (
                        f"handoff proativo — âncoras: finalidade={_anchors.get('finalidade')} / "
                        f"volume={_anchors.get('volume')}"
                    ),
                },
                lead_id=lead_id,
                phone=phone,
                conversation_id=conversation_id,
            )
        return "Âncoras de qualificação registradas."

    elif tool_name == "encaminhar_humano":
        motivo = args.get("motivo", "lead qualificado")
        vendedor = args.get("vendedor", "Vendedor")
        # Item 1: resolve o responsável ANTES de desligar a IA, para gravar assigned_to no
        # mesmo update — o lead nunca fica órfão. Fonte de verdade = owner do pipeline do
        # segmento (consumo/secretaria → None, self-service). Fail-soft.
        try:
            _seg = (get_lead(lead_id) or {}).get("stage")
            _assigned_to = vendor_user_id_for_segment(_seg)
        except Exception:
            _assigned_to = None
        _disable_fields = {"status": "converted", "human_control": True, "ai_enabled": False}
        if _assigned_to:
            _disable_fields["assigned_to"] = _assigned_to
        try:
            update_lead(lead_id, **_disable_fields)
        except Exception as exc:
            logger.error(
                "CRITICAL: encaminhar_humano failed to set ai_enabled=False for lead %s: %s",
                lead_id, exc, exc_info=True,
            )
            try:
                save_message(
                    lead_id, "system",
                    f"[encaminhar_humano][ERRO] nao foi possivel desativar AI: {exc}",
                    conversation_id=conversation_id,
                )
            except Exception:
                pass
            return f"CRITICAL: erro ao encaminhar para {vendedor} — humano precisa verificar lead manualmente"
        # Handoff encerra o bot: cancela follow-ups standard pendentes para o lead não
        # receber uma mensagem automática da Valéria depois de já ter sido passado pro
        # vendedor (o handoff_rescue é preservado — cancel_followups_by_phone o exclui).
        try:
            cancel_followups_by_phone(phone, reason="handoff")
        except Exception as exc:
            logger.error(
                "encaminhar_humano: falha ao cancelar follow-ups para lead %s (phone %s): %s",
                lead_id, phone, exc,
            )
        try:
            lead = get_lead(lead_id)
            lead_stage = lead.get("stage") if lead else None
            deal_title = f"{vendedor} - {motivo}"
            # P2 (auditoria 2026-06-22): roteia o card para o pipeline do VENDEDOR por SEGMENTO
            # (lead.stage), independente da origem — corrige broadcast-qualificados que ficavam
            # presos em 'Valeria - Importação Leads Frios'. Fallback preserva o comportamento
            # anterior: LP (move_open_deal_for_handoff) e, por fim, create_deal por categoria.
            # 'consumo'/'secretaria' não têm pipeline de vendedor → caem no fallback (self-service).
            if not move_deal_to_vendor_pipeline(lead_id, lead_stage, title=deal_title):
                if not move_open_deal_for_handoff(lead_id, title=deal_title):
                    create_deal(lead_id, title=deal_title, category=lead_stage, dedupe_open=True)
        except Exception as exc:
            logger.error(
                "encaminhar_humano failed to create deal for lead %s: %s",
                lead_id, exc, exc_info=True,
            )
        save_message(lead_id, "system", f"[encaminhar_humano] Lead encaminhado para {vendedor}: {motivo}", conversation_id=conversation_id)
        # Item 2: carimbo ESTRUTURADO do handoff (legível por máquina), independente do LLM de
        # resumo. Torna a cascata Qualificados/Aceites contável por evento real de handoff, sem
        # depender do estágio do kanban (contaminado por desqualificações suaves).
        try:
            _cur_meta = dict((get_lead(lead_id) or {}).get("metadata") or {})
            _cur_meta["handoff"] = {
                "vendedor_id": _assigned_to,
                "vendedor": vendedor,
                "segmento": _seg,
                "motivo": motivo,
                "at": datetime.now(_TZ_BR).isoformat(),
            }
            update_lead(lead_id, metadata=_cur_meta)
        except Exception as _stamp_exc:
            logger.error(
                "encaminhar_humano: falha ao gravar carimbo metadata.handoff p/ lead %s: %s",
                lead_id, _stamp_exc,
            )
        # Gera e armazena resumo estruturado da qualificação
        try:
            from app.agent.summary import generate_qualification_summary
            from app.config import settings
            from app.db.supabase import get_supabase
            conv_history = get_conversation_history(conversation_id, limit=100)
            fresh_lead = get_lead(lead_id) or {}
            # Briefing de handoff é extração mecânica — flash-lite (FinOps P2, 12/07);
            # env SUMMARY_MODEL reverte sem deploy (mesmo padrão MEMORY/TRANSCRIPTION_MODEL).
            _model = settings.summary_model
            _handoff_at = datetime.now(_TZ_BR).strftime("%d/%m/%Y %H:%M")
            summary_text = await generate_qualification_summary(
                conv_history, fresh_lead, _model,
                motivo=motivo,
                handoff_at=_handoff_at,
            )
            _sb = get_supabase()
            _sb.table("lead_notes").insert({
                "lead_id": lead_id,
                "author": "qualificação-ia",
                "content": summary_text,
            }).execute()
            existing_meta = dict(fresh_lead.get("metadata") or {})
            existing_meta["handoff_summary"] = summary_text
            update_lead(lead_id, metadata=existing_meta)
            logger.info("encaminhar_humano: resumo de qualificação salvo para lead %s", lead_id)
        except Exception as _exc:
            logger.error(
                "encaminhar_humano: falha ao gerar/salvar resumo para lead %s: %s",
                lead_id, _exc, exc_info=True,
            )
            # Fallback: SEMPRE registrar uma nota de transbordo no lead_notes, mesmo se a
            # geração do resumo pela IA falhar — o vendedor (João) reclamou de não receber
            # nada nesses casos (auditoria 2026-06-22). Garante data/hora + motivo no mínimo.
            try:
                _ts_fb = datetime.now(_TZ_BR).strftime("%d/%m/%Y %H:%M")
                append_lead_observation(
                    lead_id,
                    f"➡️ [TRANSBORDO p/ {vendedor}] {_ts_fb} — Motivo: {motivo}. "
                    f"Resumo automático indisponível; ver histórico da conversa com a Valéria.",
                )
            except Exception:
                logger.error("encaminhar_humano: fallback de nota de transbordo também falhou para lead %s", lead_id)
        channel = get_channel_for_lead(lead_id)
        if channel:
            # Destino entregável: wa_id real do lead quando houver, senão phone (evita 131026).
            send_to = resolve_send_target(lead, phone)
            provider = get_provider(channel)
            # Mensagem de despedida escrita pela IA (fallback para a estática se ausente),
            # com teto de tamanho por usabilidade no WhatsApp.
            despedida = (args.get("mensagem_despedida") or "").strip() or _HANDOFF_MSG
            if len(despedida) > _MAX_DESPEDIDA_LEN:
                despedida = despedida[:_MAX_DESPEDIDA_LEN].rstrip() + "…"
            if _despedida_ja_enviada(conversation_id, despedida):
                logger.info(
                    "[HANDOFF DEDUP] despedida ~idêntica a bolha já enviada — pulando send_text "
                    "(conv=%s); cartão de contato segue normalmente.", conversation_id,
                )
            else:
                try:
                    send_result = await provider.send_text(send_to, despedida)
                    save_message(lead_id, "assistant", despedida, sent_by="handoff", conversation_id=conversation_id, wamid=extract_wamid(send_result))
                except Exception as exc:
                    logger.error(
                        "encaminhar_humano: falha ao enviar mensagem de handoff para lead %s: %s",
                        lead_id, exc, exc_info=True,
                    )
            # Logo após o texto, envia o cartão de contato do João (agrupamento visual).
            try:
                await provider.send_contact(
                    send_to, contact_name=SUPERVISOR_NAME, contact_phone=SUPERVISOR_PHONE
                )
                save_message(
                    lead_id, "system",
                    f"[encaminhar_humano] cartão de contato de {SUPERVISOR_NAME} enviado",
                    conversation_id=conversation_id,
                )
            except Exception as exc:
                logger.error(
                    "encaminhar_humano: falha ao enviar cartão de contato do supervisor para lead %s: %s",
                    lead_id, exc, exc_info=True,
                )
            try:
                schedule_handoff_rescue(
                    lead_id=lead_id,
                    lead_phone=phone,
                    conversation_id=conversation_id,
                    channel_id=channel["id"],
                    lead_name=(lead.get("name") or "") if lead else "",
                )
            except Exception as exc:
                logger.error(
                    "encaminhar_humano: falha ao agendar rescue job para lead %s: %s",
                    lead_id, exc, exc_info=True,
                )
        else:
            logger.warning(
                "encaminhar_humano: nenhum canal ativo para lead %s — mensagem de handoff e rescue job ignorados",
                lead_id,
            )
        return f"{HANDOFF_RESULT_PREFIX}{vendedor}"

    elif tool_name == "registrar_optout":
        motivo = args.get("motivo", "opt-out solicitado pelo lead")
        # Guardrail anti-falso-positivo de Blacklist (auditoria 2026-06-22): se o motivo é
        # claramente SOFT rejection (sem proibição explícita de contato), rebaixa para
        # registrar_sem_interesse_atual (Perdido, opt_out=False, sem blacklist). Defesa em
        # profundidade por cima da regra 18 do prompt — o LLM às vezes erra a classificação.
        if _looks_like_soft_rejection(motivo):
            logger.warning(
                "[BLACKLIST GUARDRAIL] registrar_optout rebaixado para sem_interesse — "
                "lead %s, motivo=%r (sem sinal de proibição explícita de contato)",
                lead_id, motivo,
            )
            return await execute_tool(
                "registrar_sem_interesse_atual",
                {"motivo": f"[rebaixado de opt-out pelo guardrail] {motivo}",
                 "mensagem_despedida": args.get("mensagem_despedida", "")},
                lead_id, phone, conversation_id,
            )
        # Despedida ANTES de desligar a IA — depois disso a trava B2 do processor
        # aborta qualquer bolha deste turno (forense 11/07).
        await _send_despedida_descarte(lead_id, phone, conversation_id, args, _OPTOUT_MSG)
        try:
            update_lead(lead_id, ai_enabled=False, opt_out=True)
        except Exception as exc:
            logger.error("registrar_optout: falha ao desativar AI para lead %s: %s", lead_id, exc, exc_info=True)
            return f"ERRO ao registrar opt-out: {exc}"
        apply_optout_side_effects(lead_id, phone, reason="optout")
        _ts = datetime.now(_TZ_BR).strftime("%d/%m/%Y %H:%M")
        append_lead_observation(lead_id, f"🚫 [OPT-OUT DEFINITIVO] Registado em {_ts}. Motivo: {motivo}")
        save_message(
            lead_id, "system",
            f"[registrar_optout] lead solicitou opt-out: {motivo}",
            conversation_id=conversation_id,
        )
        logger.info("registrar_optout: ai_enabled=False opt_out=True para lead %s — motivo: %s", lead_id, motivo)
        return "Opt-out registrado."

    elif tool_name == "registrar_sem_interesse_atual":
        motivo = args.get("motivo", "lead sem interesse no momento")

        # GUARDRAIL (item 2, auditoria 2026-06-22): CLIENTE ATIVO não vira "perdido".
        # Se o lead já tem relacionamento ativo (deal pós-handoff/closed-won) OU o próprio
        # motivo indica que já é cliente, ele NÃO é um lead frio perdido — é um cliente sem
        # demanda agora. Encerra cordialmente e mantém o deal no estágio atual: NÃO seta
        # stage=perdido, NÃO move o deal p/ Perdido, NÃO fecha o negócio (caso Kadi Guth).
        if lead_has_active_relationship(lead_id) or _motivo_indica_cliente(motivo):
            logger.info(
                "[CLIENTE ATIVO GUARDRAIL] registrar_sem_interesse_atual em cliente ativo %s — "
                "encerrando sem marcar perdido (motivo=%r)", lead_id, motivo,
            )
            # Despedida ANTES de desligar a IA (trava B2 engole bolhas pós-flag).
            await _send_despedida_descarte(
                lead_id, phone, conversation_id, args, _SEM_INTERESSE_MSG,
            )
            try:
                # Encerra o bot desta abordagem, mas NÃO mexe no stage nem no human_control
                # (não é lead perdido nem precisa de resgate de vendedor).
                update_lead(lead_id, ai_enabled=False, opt_out=False)
            except Exception as exc:
                logger.error(
                    "registrar_sem_interesse_atual (cliente ativo): falha ao atualizar lead %s: %s",
                    lead_id, exc, exc_info=True,
                )
                return f"ERRO ao registrar sem interesse: {exc}"
            try:
                cancel_followups_by_phone(phone, reason="cliente_ativo_sem_demanda")
            except Exception as exc:
                logger.error(
                    "registrar_sem_interesse_atual (cliente ativo): falha ao cancelar follow-ups p/ %s: %s",
                    lead_id, exc, exc_info=True,
                )
            _ts = datetime.now(_TZ_BR).strftime("%d/%m/%Y %H:%M")
            append_lead_observation(
                lead_id,
                f"⏸️ [CLIENTE ATIVO — SEM DEMANDA NO MOMENTO] Registado em {_ts}. "
                f"Mantido no funil (não marcado perdido). Motivo: {motivo}",
            )
            save_message(
                lead_id, "system",
                f"[registrar_sem_interesse_atual] cliente ativo sem demanda — mantido no funil: {motivo}",
                conversation_id=conversation_id,
            )
            return (
                "Cliente ativo sem demanda no momento — conversa encerrada cordialmente e "
                "mantida no funil atual (NÃO marcado como perdido)."
            )

        # Soft rejection (lead frio): tira do funil mas mantem opt_out=False (lead reativavel, sem blacklist).
        # Despedida ANTES de desligar a IA — depois disso a trava B2 do processor
        # aborta qualquer bolha deste turno (forense 11/07: leads 'Sim' e Anderson
        # se despediram educadamente e receberam silêncio).
        await _send_despedida_descarte(lead_id, phone, conversation_id, args, _SEM_INTERESSE_MSG)
        try:
            update_lead(lead_id, stage="perdido", ai_enabled=False, human_control=True, opt_out=False)
        except Exception as exc:
            logger.error(
                "registrar_sem_interesse_atual: falha ao atualizar lead %s: %s", lead_id, exc, exc_info=True
            )
            return f"ERRO ao registrar sem interesse: {exc}"
        move_lead_deals_to_perdido(lead_id, reason=motivo)
        try:
            cancel_followups_by_phone(phone, reason="sem_interesse_atual")
        except Exception as exc:
            logger.error(
                "registrar_sem_interesse_atual: falha ao cancelar follow-ups para lead %s: %s",
                lead_id, exc, exc_info=True,
            )
        _ts = datetime.now(_TZ_BR).strftime("%d/%m/%Y %H:%M")
        append_lead_observation(lead_id, f"⏸️ [SEM INTERESSE ATUAL] Registado em {_ts}. Motivo: {motivo}")
        save_message(
            lead_id, "system",
            f"[registrar_sem_interesse_atual] lead sem interesse no momento: {motivo}",
            conversation_id=conversation_id,
        )
        logger.info(
            "registrar_sem_interesse_atual: stage=perdido ai_enabled=False opt_out=False para lead %s — motivo: %s",
            lead_id, motivo,
        )
        return "Lead marcado como sem interesse atual."

    elif tool_name == "registrar_numero_errado":
        contexto = args.get("contexto", "")
        # Idempotência (incidente 09/07: retry do agente re-executou a tool 4x no mesmo
        # lead): já marcado → no-op, sem novo marcador nem system message duplicada.
        _wn_meta = dict((get_lead(lead_id) or {}).get("metadata") or {})
        if _wn_meta.get("wrong_number_at"):
            return "numero ja marcado como possivel engano — higiene automatica ja armada, siga o arco normal"
        try:
            _wn_meta["wrong_number_at"] = datetime.now(timezone.utc).isoformat()
            _wn_meta["wrong_number_context"] = contexto
            update_lead(lead_id, metadata=_wn_meta)
        except Exception as _wn_exc:
            logger.error("registrar_numero_errado: falha ao marcar lead %s: %s", lead_id, _wn_exc)
        save_message(
            lead_id, "system",
            f"[registrar_numero_errado] possivel numero errado: {contexto}",
            conversation_id=conversation_id,
        )
        logger.info("registrar_numero_errado: lead %s marcado — %s", lead_id, contexto)
        return (
            "numero marcado como possivel engano — se ninguem responder em 72h o sistema "
            "faz a higiene (opt-out) sozinho; siga o arco normal de re-engajamento"
        )

    elif tool_name == "registrar_indicacao":
        contexto = args.get("contexto", "")
        nome = (args.get("nome") or "").strip()
        telefone = (args.get("telefone") or "").strip()
        _ts = datetime.now(_TZ_BR).strftime("%d/%m/%Y %H:%M")
        detalhe = f"🤝 [INDICAÇÃO] {_ts}: {contexto}"
        if nome:
            detalhe += f" — indicado: {nome}"
        if telefone:
            detalhe += f" ({telefone})"
        append_lead_observation(lead_id, detalhe)
        try:
            _ref_meta = dict((get_lead(lead_id) or {}).get("metadata") or {})
            _ref_meta["referral"] = {
                "nome": nome, "telefone": telefone, "contexto": contexto,
                "at": datetime.now(timezone.utc).isoformat(),
            }
            update_lead(lead_id, metadata=_ref_meta)
        except Exception as _ref_exc:
            logger.error("registrar_indicacao: falha ao gravar metadata p/ lead %s: %s", lead_id, _ref_exc)
        # Tag opcional (add_tags_to_lead ignora nomes inexistentes — fail-soft por design).
        add_tags_to_lead(lead_id, ["indicacao"])
        save_message(
            lead_id, "system",
            f"[registrar_indicacao] {contexto}"
            + (f" — indicado: {nome}" if nome else "")
            + (f" ({telefone})" if telefone else ""),
            conversation_id=conversation_id,
        )
        logger.info("registrar_indicacao: lead %s — nome=%r tel=%r", lead_id, nome, telefone)
        return "indicacao registrada no CRM — agradeca com naturalidade e siga a conversa"

    elif tool_name == "enviar_fotos":
        history = get_history(lead_id, limit=100)
        system_messages = [m for m in history if m.get("role") == "system"]
        if any("[enviar_fotos]" in m.get("content", "") for m in system_messages):
            logger.info(
                "enviar_fotos: fotos de %s ja enviadas para lead %s — nao reenviar",
                args.get("categoria"), lead_id,
            )
            return "fotos ja enviadas nesta conversa — nao reenviar"
        # Dedup intra-turno pela FILA (o marcador de histórico agora só nasce após a
        # entrega real): segunda chamada no mesmo turno não duplica o lote.
        if any(
            str(item.get("marker", "")).startswith("[enviar_fotos]")
            for item in _deferred_media.get(conversation_id, [])
        ):
            return "fotos ja enfileiradas neste turno — nao reenviar"

        categoria = args["categoria"]
        photos_dir = Path(__file__).parent.parent / "photos" / categoria
        if not photos_dir.exists():
            return f"Categoria {categoria} nao encontrada"

        photos = sorted(photos_dir.glob("foto_*.*"))
        if not photos:
            return f"Nenhuma foto encontrada para {categoria}"

        captions = PHOTO_CAPTIONS.get(categoria, {})

        # Queue photos for deferred dispatch: processor sends them AFTER the text
        # response so the chronological order in WhatsApp is: text first, photos second.
        queue = _deferred_media.setdefault(conversation_id, [])
        for photo in photos:
            b64 = base64.b64encode(photo.read_bytes()).decode()
            mimetype = "image/png" if photo.suffix == ".png" else "image/jpeg"
            stem = photo.stem
            caption = captions.get(stem, "")
            queue.append({
                "b64": b64, "mimetype": mimetype, "caption": caption,
                # Verdade-no-marcador (caso Wander): o marcador de entrega e o carimbo
                # catalog_shown são persistidos pelo PROCESSOR após o envio real
                # (record_deferred_media_delivery) — fila drenada por supersede/handoff
                # não deixa rastro e o reenvio continua possível.
                "marker": f"[enviar_fotos] Fotos de {categoria} enviadas",
                "catalog": True,
            })

        return f"{len(photos)} fotos de {categoria} enfileiradas para envio após o texto"

    elif tool_name == "enviar_foto_produto":
        categoria = args["categoria"]
        produto = args["produto"].lower().strip()

        history = get_history(lead_id, limit=100)
        marker = f"[enviar_foto_produto] Foto de {produto}"
        if any(marker in m.get("content", "") for m in history if m.get("role") == "system"):
            return f"foto de {produto} ja enviada nesta conversa — nao reenviar"
        # Dedup intra-turno pela fila (marcador de histórico só nasce pós-entrega).
        if any(
            str(item.get("marker", "")).startswith(marker)
            for item in _deferred_media.get(conversation_id, [])
        ):
            return f"foto de {produto} ja enfileirada neste turno — nao reenviar"

        cat_map = PRODUTO_PHOTO_MAP.get(categoria, {})
        entry = cat_map.get(produto)
        if not entry:
            return f"produto '{produto}' nao encontrado na categoria {categoria}"

        photos_dir = Path(__file__).parent.parent / "photos" / categoria
        stem = Path(entry["file"]).stem  # e.g. "foto_1"
        matches = list(photos_dir.glob(f"{stem}.*"))
        if not matches:
            return f"foto do produto '{produto}' nao encontrada"
        photo_path = matches[0]

        b64 = base64.b64encode(photo_path.read_bytes()).decode()
        mimetype = "image/png" if photo_path.suffix == ".png" else "image/jpeg"

        # Queue for deferred dispatch so text explanation arrives before the photo.
        # Marcador de entrega persistido pós-envio real (record_deferred_media_delivery).
        _deferred_media.setdefault(conversation_id, []).append(
            {"b64": b64, "mimetype": mimetype, "caption": entry["caption"],
             "marker": f"[enviar_foto_produto] Foto de {produto} enviada",
             "catalog": False}
        )
        return f"foto de {produto} enfileirada para envio após o texto"

    elif tool_name == "marcar_interesse":
        nivel = args.get("nivel", "morno")
        motivo = args.get("motivo", "")
        if conversation_id:
            _interest_marked[conversation_id] = {"nivel": nivel, "motivo": motivo}
        # Autonomia de pipeline (CREATE-OR-MOVE): interesse comercial claro = lead QUALIFICADO.
        # Se o lead inbound ainda não tem card, cria um no funil do seu segmento e o move para
        # 'Qualificado'; se já tem, apenas move. No-op gracioso sem segmento conhecido nem card.
        # Fail-soft: nunca derruba o flag de follow-up.
        try:
            lead = get_lead(lead_id)
            segment = lead.get("stage") if lead else None
            mark_deal_qualificado(lead_id, segment)
        except Exception as exc:
            logger.error(
                "marcar_interesse: falha ao qualificar card (lead %s): %s",
                lead_id, exc, exc_info=True,
            )
        logger.info(
            "marcar_interesse: nivel=%s motivo=%r lead=%s conv=%s",
            nivel, motivo, lead_id, conversation_id,
        )
        return f"Interesse registrado: {nivel}"

    elif tool_name == "retomar_contato_vendedor":
        return await _retomar_contato_vendedor(args, lead_id, phone, conversation_id)

    elif tool_name == "agendar_retorno":
        return await _agendar_retorno(args, lead_id, phone, conversation_id)

    elif tool_name == "consultar_relacionamento":
        try:
            return get_relationship_summary(lead_id)
        except Exception as exc:
            logger.error(
                "consultar_relacionamento: erro inesperado p/ lead %s: %s",
                lead_id, exc, exc_info=True,
            )
            return "Não foi possível consultar o relacionamento agora."

    elif tool_name == "calcular_orcamento":
        try:
            # 1. Validate args via Pydantic
            try:
                orcamento = OrcamentoInput(**args)
            except _PydanticValidationError as exc:
                return (
                    f"Não consegui ler os itens do pedido "
                    f"({exc.error_count()} erro(s) de validação). "
                    "Verifique os itens informados (produto e quantidade > 0)."
                )

            # 2. Fetch active atacado products once (P1: parse_brl só nos matches)
            try:
                all_products = _fetch_active_products()
            except Exception as exc:
                logger.error(
                    "calcular_orcamento: falha ao buscar produtos p/ lead %s: %s",
                    lead_id, exc, exc_info=True,
                )
                return (
                    "Não consegui acessar o catálogo de produtos agora. "
                    "Encaminhe para o João para calcular manualmente."
                )
            products = [
                p for p in all_products
                if _normalize_catalog(p.get("sector")) == "atacado"
            ]

            # 3. Resolve each item — abort on first irresolvable item
            lines: list[LineQuote] = []
            for item in orcamento.itens:
                matches = match_products(item.produto, products)
                if len(matches) == 0:
                    # Frente C3 (caso real Edgar, 02/07 17:14): 0 matches agora LISTA as
                    # opções reais do catálogo. Antes devolvia só "confirme o nome" e a
                    # Valéria improvisava ("o sistema não achou o Suave em grãos de 500g"
                    # — produto ERRADO, 2x) e chegou a substituir item em silêncio no
                    # orçamento. Nomes em ordem ESTÁVEL (ordem do catálogo), cap P2.
                    nomes = [p["name"] for p in products if p.get("name")]
                    if nomes:
                        return (
                            f"Produto '{item.produto}' não encontrado no catálogo de "
                            f"atacado. Disponíveis: {', '.join(nomes[:MAX_DISAMBIGUATION])}. "
                            "Confirme com o cliente qual ele quer."
                        )
                    return (
                        f"Produto '{item.produto}' não encontrado no catálogo de atacado. "
                        "Confirme o nome."
                    )
                if len(matches) > 1:
                    top_names = ", ".join(m["name"] for m in matches)
                    return f"Para '{item.produto}', especifique qual: {top_names}"
                # Exactly 1 match — parse_brl ONLY on this match (P1)
                match = matches[0]
                # Guard: price_formatted None/empty → AttributeError in parse_brl escapes
                # the (ValueError, KeyError, TypeError) inner handler. Return a precise
                # message here rather than falling to the generic outer catch.
                if not match.get("price_formatted"):
                    logger.error(
                        "calcular_orcamento: price_formatted ausente p/ produto '%s' (lead %s)",
                        match.get("name", item.produto), lead_id,
                    )
                    return (
                        f"Não consegui ler o preço do produto '{match.get('name', item.produto)}' "
                        "— encaminhe para o João Brás."
                    )
                try:
                    preco = parse_brl(match["price_formatted"])
                except (ValueError, KeyError, TypeError) as exc:
                    logger.error(
                        "calcular_orcamento: parse_brl falhou p/ produto '%s' (lead %s): %s",
                        match.get("name", item.produto), lead_id, exc,
                    )
                    return (
                        f"Não consegui ler o preço do produto '{match.get('name', item.produto)}'. "
                        "Encaminhe para o João para calcular manualmente."
                    )
                lines.append(LineQuote(
                    produto=match["name"],
                    quantidade=item.quantidade,
                    preco_unitario=preco,
                    subtotal_linha=round(preco * item.quantidade, 2),
                ))

            # 4. Resolve region (B2: Uberlândia proceeds even without estado)
            region_key, is_uberlandia = resolve_region(orcamento.estado, orcamento.cidade)

            # 5. No region AND not Uberlândia override → return subtotal + ask for estado
            if region_key is None and not is_uberlandia:
                subtotal = round(sum(line.subtotal_linha for line in lines), 2)
                # Frente B3: valores já foram resolvidos (subtotal real) mesmo faltando UF —
                # sinaliza "cotou preço" para o gatilho de follow-up do processor.
                if conversation_id:
                    _quote_executed[conversation_id] = True
                return (
                    f"Subtotal dos produtos: {fmt_brl(subtotal)}. "
                    "Para calcular o frete e verificar o pedido mínimo, "
                    "me confirme o estado (sigla UF, ex.: SP)."
                )

            # 6. Full quote with freight
            quote = compute_quote(lines, region_key, is_uberlandia)
            # Frente B3: orçamento completo resolvido — idem acima.
            if conversation_id:
                _quote_executed[conversation_id] = True
            return format_quote(quote)

        except Exception as exc:
            logger.error(
                "calcular_orcamento: erro inesperado p/ lead %s: %s",
                lead_id, exc, exc_info=True,
            )
            return (
                "Ocorreu um problema ao calcular o orçamento. "
                "Por favor, encaminhe para o João para calcular manualmente."
            )

    return f"Tool {tool_name} nao reconhecida"


# Horizonte máximo de agendamento autônomo (rede de segurança contra datas absurdas).
_MAX_RETORNO_HORIZON_DAYS = 30


def _format_retorno_when(fire_at: datetime) -> str:
    """Frase natural (pt-BR) do horário do retorno agendado (já clampado)."""
    local = fire_at.astimezone(_TZ_BR)
    today = datetime.now(_TZ_BR).date()
    delta = (local.date() - today).days
    hora = local.strftime("%Hh%M") if local.minute else local.strftime("%Hh")
    if delta <= 0:
        return f"hoje por volta das {hora}"
    if delta == 1:
        return f"amanha por volta das {hora}"
    return f"em {local.strftime('%d/%m')} por volta das {hora}"


async def _agendar_retorno(
    args: dict[str, Any], lead_id: str, phone: str, conversation_id: str
) -> str:
    """Agenda um retorno autônomo da Valéria (job ai_scheduled_return) no horário pedido.

    Valida/parseia a data, rejeita passado e horizonte > 30 dias, resolve o canal e insere o
    job (clampado p/ janela comercial em schedule_ai_return). NÃO desativa a IA — o lead segue
    conversando. Retorna a string que a Valéria usa para confirmar o retorno ao lead.
    """
    data_hora_raw = (args.get("data_hora") or "").strip()
    motivo = (args.get("motivo") or "").strip() or "retomar o contato combinado"
    contexto = (args.get("contexto") or "").strip()

    if not data_hora_raw:
        return "ERRO: data_hora e obrigatoria (ISO 8601 com fuso, ex.: 2026-06-27T14:00:00-03:00)."
    try:
        dt = datetime.fromisoformat(data_hora_raw)
    except ValueError:
        return (
            f"ERRO: data_hora invalida ({data_hora_raw!r}). Use ISO 8601 com fuso, "
            "ex.: 2026-06-27T14:00:00-03:00."
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ_BR)  # naïve → assume horário de Brasília
    fire_at = dt.astimezone(timezone.utc)

    now = datetime.now(timezone.utc)
    if fire_at <= now:
        return "ERRO: data_hora no passado. Escolha um horario futuro."
    if fire_at > now + timedelta(days=_MAX_RETORNO_HORIZON_DAYS):
        return f"ERRO: horizonte maximo de {_MAX_RETORNO_HORIZON_DAYS} dias para agendamento."

    channel = get_channel_for_lead(lead_id)
    if not channel:
        return "ERRO: nenhum canal ativo para agendar o retorno."

    # Idempotência (Eixo 3A): se já há um retorno agendado p/ esta conversa, NÃO crie outro.
    # Mata o loop em que a IA reagenda o mesmo retorno a cada despedida do lead (bug Walter).
    existing = find_pending_ai_return(conversation_id)
    if existing:
        try:
            existing_at = datetime.fromisoformat(
                str(existing.get("fire_at")).replace("Z", "+00:00")
            )
            when_existing = _format_retorno_when(existing_at)
        except Exception:
            when_existing = "o horario ja combinado"
        return (
            f"Voce JA tem um retorno agendado para {when_existing}. NAO chame agendar_retorno "
            "de novo — apenas confirme ao lead de forma natural e siga a conversa."
        )

    lead = get_lead(lead_id) or {}
    lead_name = lead.get("name") or ""
    try:
        scheduled_at = schedule_ai_return(
            conversation_id=conversation_id,
            lead_id=lead_id,
            channel_id=channel["id"],
            fire_at=fire_at,
            metadata={
                "motivo": motivo,
                "contexto": contexto,
                "lead_name": lead_name,
                "scheduled_by": "agendar_retorno",
            },
        )
    except Exception as exc:
        logger.error(
            "agendar_retorno: falha ao agendar retorno p/ lead %s: %s", lead_id, exc, exc_info=True
        )
        return f"ERRO ao agendar retorno: {exc}"

    when_label = _format_retorno_when(scheduled_at)
    try:
        save_message(
            lead_id, "system",
            f"[agendar_retorno] retorno agendado p/ {scheduled_at.isoformat()} — {motivo}",
            conversation_id=conversation_id,
        )
    except Exception:
        pass
    logger.info(
        "agendar_retorno: lead %s agendado p/ %s (motivo=%r)", lead_id, scheduled_at.isoformat(), motivo
    )
    return (
        f"Retorno agendado para {when_label}. Confirme ao lead de forma natural que voce "
        "volta a falar com ele nesse momento e siga a conversa normalmente."
    )


def _format_next_dispatch(fire_at: datetime | None) -> str:
    """Frase natural (pt-BR) para quando o João vai chamar o lead, a partir do fire_at agendado.

    O período do dia é derivado da HORA real do fire_at (fix review B2): antes era
    "de manha" HARDCODED, válido só sob a invariante antiga de o clamp devolver
    sempre 09h — se a janela mudar de novo, um fire_at vespertino diria "de manha
    (por volta das 17h22)". Output idêntico ao anterior para os casos atuais
    (clamp comercial devolve 09h → "de manha").
    """
    if fire_at is None:
        return "o proximo horario comercial"
    local = fire_at.astimezone(_TZ_BR)
    today_local = datetime.now(_TZ_BR).date()
    delta_days = (local.date() - today_local).days
    hora = local.strftime("%Hh%M") if local.minute else local.strftime("%Hh")
    # Período pela hora real, nunca hardcode: manhã < 12h; tarde 12h-17h59; >= 18h fim do dia.
    if local.hour < 12:
        periodo = "de manha"
    elif local.hour < 18:
        periodo = "a tarde"
    else:
        periodo = "no fim do dia"
    if delta_days <= 0:
        return f"hoje {periodo} (por volta das {hora})"
    if delta_days == 1:
        return f"amanha {periodo} (por volta das {hora})"
    return f"no proximo dia util ({local.strftime('%d/%m')} {periodo}, por volta das {hora})"


def _lead_had_prior_handoff(lead_id: str, lead: dict | None = None) -> bool:
    """True se o lead JÁ passou por handoff/retomada com o vendedor (cenário de reativação).

    Sinais (qualquer um): handoff_summary/prior_handoff_joao no metadata; deal em estágio
    pós-handoff (ja_chamado); ou evento de sistema [encaminhar_humano]/[retomar_contato_vendedor]
    no histórico do lead. Conservador (na dúvida → False): retomar_contato_vendedor só é
    legítima na reativação; para lead novo/frio o caminho seguro é encaminhar_humano.
    """
    lead = lead if lead is not None else (get_lead(lead_id) or {})
    meta = lead.get("metadata") or {}
    if meta.get("handoff_summary") or meta.get("prior_handoff_joao"):
        return True
    try:
        from app.db.supabase import get_supabase
        sb = get_supabase()
        deal = (
            sb.table("deals").select("id")
            .eq("lead_id", lead_id).eq("stage", "ja_chamado").limit(1).execute()
        )
        if deal.data:
            return True
        ev = (
            sb.table("messages").select("id")
            .eq("lead_id", lead_id)
            .or_("content.ilike.%[encaminhar_humano]%,content.ilike.%[retomar_contato_vendedor]%")
            .limit(1).execute()
        )
        return bool(ev.data)
    except Exception as exc:
        logger.warning("_lead_had_prior_handoff: falha ao checar histórico p/ %s: %s", lead_id, exc)
        return False


async def _retomar_contato_vendedor(
    args: dict[str, Any], lead_id: str, phone: str, conversation_id: str
) -> str:
    """Reabordagem de lead que esfriou apos handoff anterior com o Joao Bras.

    Efeitos (na ordem):
      (c) Desativa a IA imediatamente (ai_enabled=False, human_control=True) — a Valeria para de responder.
      (a) Dispara o template do Joao para o lead AGORA se dentro do horario comercial
          (09h-16h, dias uteis, America/Sao_Paulo); caso contrario, agenda para o
          proximo horario comercial valido (job handoff_rescue).
      (b) Retorna uma string instruindo a Valeria a se despedir conforme o disparo
          tenha sido imediato ou agendado.
    """
    from app.follow_up.service import is_within_business_window
    from app.follow_up.scheduler import send_joao_handoff_template

    motivo = args.get("motivo", "lead pediu para retomar o contato com o vendedor")
    lead = get_lead(lead_id) or {}
    lead_name = lead.get("name") or ""

    # GUARDRAIL (B): retomar_contato_vendedor é EXCLUSIVA de reativação pós-handoff.
    # Se o lead NÃO tem histórico real de handoff, a IA escolheu a tool errada para um lead
    # novo/frio (auditoria 2026-06-22: lead 5511946741676 — outbound novo, metadata vazio,
    # ainda assim "retomado"). Rebaixa para o fluxo padrão encaminhar_humano, que é o correto
    # para lead novo/qualificado (envia o cartão do João e gera o resumo de qualificação).
    if not _lead_had_prior_handoff(lead_id, lead):
        logger.warning(
            "[RETOMADA GUARDRAIL] retomar_contato_vendedor sem histórico de handoff p/ lead %s "
            "— rebaixando para encaminhar_humano (motivo=%r)", lead_id, motivo,
        )
        return await execute_tool(
            "encaminhar_humano",
            {
                "vendedor": "Joao Bras",
                "motivo": f"[rebaixado de retomada — lead sem handoff prévio] {motivo}",
            },
            lead_id, phone, conversation_id,
        )
    # Destino entregável (wa_id real quando houver) para o disparo do João — evita 131026.
    send_to = resolve_send_target(lead, phone)

    # (c) Desativa a IA imediatamente — a partir daqui a Valeria nao responde mais.
    try:
        update_lead(lead_id, ai_enabled=False, human_control=True, status="converted")
    except Exception as exc:
        logger.error(
            "CRITICAL: retomar_contato_vendedor falhou ao desativar IA para lead %s: %s",
            lead_id, exc, exc_info=True,
        )
        return (
            "CRITICAL: erro ao processar a retomada — nao foi possivel desativar a IA. "
            "Peca desculpas brevemente e diga que um vendedor vai assumir; um humano precisa verificar manualmente."
        )

    # Visibilidade para o time comercial: registra o retorno do lead como deal.
    try:
        deal_title = f"Joao (retomada) - {motivo}"
        # Lead de LP: MOVE o card do funil de ENTRADA da Valéria para o de FECHAMENTO do João
        # (mesma lógica do encaminhar_humano). Sem card de LP → cria (dedupe p/ não duplicar).
        if not move_open_deal_for_handoff(lead_id, title=deal_title):
            create_deal(lead_id, title=deal_title, category=lead.get("stage"), dedupe_open=True)
    except Exception as exc:
        logger.error(
            "retomar_contato_vendedor: falha ao criar deal para lead %s: %s", lead_id, exc, exc_info=True
        )

    now = datetime.now(timezone.utc)

    # (a) Dentro do horario comercial: dispara AGORA, sincrono.
    if is_within_business_window(now):
        sent = await send_joao_handoff_template(send_to, lead_name, lead_id=lead_id)
        if sent:
            save_message(
                lead_id, "system",
                f"[retomar_contato_vendedor] Joao disparou AGORA para o lead — {motivo}",
                conversation_id=conversation_id,
            )
            return (
                "DISPARO REALIZADO AGORA. O Joao acabou de enviar uma mensagem para o lead aqui no WhatsApp. "
                "Despeca-se em UMA mensagem avisando que o Joao ACABOU DE CHAMAR o lead e que e so responder a ele por aqui. "
                "NAO envie mais nenhuma mensagem depois desta."
            )
        # Falha no disparo imediato → reagenda como rede de seguranca (proximo tick do worker).
        fire_at = _safe_schedule_reengage(lead_id, send_to, conversation_id, lead_name)
        save_message(
            lead_id, "system",
            f"[retomar_contato_vendedor] disparo imediato falhou — reagendado — {motivo}",
            conversation_id=conversation_id,
        )
        return (
            "DISPARO AGENDADO. Houve um contratempo no envio imediato, mas o Joao vai chamar o lead em instantes. "
            "Despeca-se em UMA mensagem avisando que o Joao vai chamar o lead em breve aqui no WhatsApp. "
            "NAO envie mais nenhuma mensagem depois desta."
        )

    # (a) Fora do horario comercial: agenda para o proximo dia util as 09h.
    fire_at = _safe_schedule_reengage(lead_id, phone, conversation_id, lead_name)
    save_message(
        lead_id, "system",
        f"[retomar_contato_vendedor] disparo agendado fora do horario comercial — {motivo}",
        conversation_id=conversation_id,
    )
    when_label = _format_next_dispatch(fire_at)
    return (
        f"DISPARO AGENDADO para {when_label}. Estamos fora do horario comercial (09h-16h em dias uteis). "
        f"Despeca-se em UMA mensagem avisando que o Joao vai chamar o lead {when_label}, "
        "pedindo pra ele ficar de olho no WhatsApp. "
        "NAO envie mais nenhuma mensagem depois desta."
    )


def _safe_schedule_reengage(
    lead_id: str, phone: str, conversation_id: str, lead_name: str
) -> "datetime | None":
    """Agenda o disparo do Joao via job handoff_rescue (delay 0 → clampa p/ janela comercial).

    Retorna o fire_at agendado, ou None se nao houver canal ativo ou o agendamento falhar.
    """
    from app.follow_up.service import schedule_handoff_rescue

    channel = get_channel_for_lead(lead_id)
    if not channel:
        logger.warning(
            "retomar_contato_vendedor: nenhum canal ativo para lead %s — agendamento ignorado", lead_id
        )
        return None
    try:
        return schedule_handoff_rescue(
            lead_id=lead_id,
            lead_phone=phone,
            conversation_id=conversation_id,
            channel_id=channel["id"],
            delay_minutes=0,
            lead_name=lead_name,
            # Janela COMERCIAL (09h-16h), NAO a ampliada do rescue (fix review B2):
            # este caminho e o fallback de retomar_contato_vendedor, onde a Valeria
            # PROMETE verbalmente ao lead quando o Joao vai chamar — a Global
            # Constraint do plano manda o retomar continuar em 09h-16h. Sem isto, a
            # janela de 20h vazava transitivamente e as 17:22 o lead ouvia "o Joao
            # vai te chamar hoje de manha (por volta das 17h22)".
            use_rescue_window=False,
        )
    except Exception as exc:
        logger.error(
            "retomar_contato_vendedor: falha ao agendar disparo para lead %s: %s",
            lead_id, exc, exc_info=True,
        )
        return None

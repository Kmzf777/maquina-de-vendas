"""Pesquisa de perda do atacado (frente F4): botão → `lost_reason_code` / `lost_competitor`.

ESTE MÓDULO NÃO ESTÁ LIGADO A NADA. Nenhum runner, registro de fluxo, disparo ou template
o importa: é o mapeamento pronto para quando o Rafael aprovar o texto e a lista. O texto e
os botões são os do §6 de `Canastra-Content-Creator/relatorios/atacado-funil-completo-2026-11.md`
(NÃO aprovados). Ligar = (1) template aprovado na Meta com os rótulos de `BOTOES_MOTIVO`,
enviado pelo número do João; (2) o roteamento de cliques chamar `decidir` + `aplicar` quando
o estado da conversa tiver `flow == FLOW_ID`.

Mesmo desenho da Recuperação (`flows.py` + `engine.py`): dados puros e uma decisão pura
(`decidir`), testável sem banco; o único I/O é `aplicar`.

Rótulos: template aceita 25 caracteres por botão; a mensagem interativa (2ª pergunta, já
dentro da janela de 24 h) aceita 20 no botão e 24 na linha de lista. Por isso a 2ª pergunta
vai como LISTA quando tem mais de 3 opções, e dois rótulos do relatório foram encurtados:
"Preço no Mercado Livre/site" (27) → "Preço no ML/site" e "Não dava minha margem" (21) →
"Não dava a margem".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.button_flow.engine import normalizar
from app.leads import motivo_perda as mp

logger = logging.getLogger(__name__)

FLOW_ID = "pesquisa_perda_v1"

# ── Nós ─────────────────────────────────────────────────────────────────────
NO_MOTIVO = "aguardando_motivo"
NO_CONCORRENTE = "aguardando_concorrente"
NO_CONCORRENTE_TEXTO = "aguardando_concorrente_texto"
NO_PRECO = "aguardando_preco"
NO_AVISAR = "aguardando_avisar"
NO_RECONTATO = "aguardando_recontato"
NO_ENCERRADO = "encerrado"


@dataclass(frozen=True)
class Opcao:
    """Um botão. `id` é o contrato estável (vai no payload `pesquisa_perda_v1|<id>`)."""
    id: str
    titulo: str
    codigo: str | None = None        # lost_reason_code que o clique grava (None = não muda)
    concorrente: str | None = None   # lost_competitor que o clique grava
    observacao: str | None = None    # complemento para deals.lost_reason


# ── Mensagem 1 (template, fora da janela) ───────────────────────────────────
TEMPLATE_CORPO = (
    "Oi, {{1}}! Aqui é o João, do Café Canastra ☕\n\n"
    "Há algumas semanas você conversou com a gente sobre café para revenda e acabou não "
    "seguindo. Tudo bem, de verdade.\n\n"
    "Posso te pedir uma ajuda rápida? Saber o motivo ajuda a gente a melhorar. "
    "É só tocar numa opção:"
)

BOTOES_MOTIVO: tuple[Opcao, ...] = (
    Opcao("preco", "Preço não fechou", "preco_margem"),
    Opcao("frete", "Frete", "frete"),
    Opcao("pedido_minimo", "Pedido mínimo alto", "pedido_minimo"),
    Opcao("condicao", "Faltou condição/bônus", "condicao_bonificacao"),
    Opcao("comprou_outro", "Comprei de outro", "comprou_outro"),
    Opcao("ainda_vendo", "Ainda estou vendo", "ainda_pesquisando"),
    Opcao("uso_proprio", "Era para uso próprio", "consumidor_final"),
)

# ── Mensagem 2, conforme o botão ────────────────────────────────────────────
PERGUNTA_CONCORRENTE = "Obrigado por contar! De qual marca você comprou?"
BOTOES_CONCORRENTE: tuple[Opcao, ...] = (
    Opcao("conc_orfeu", "Orfeu", "comprou_outro", concorrente="Orfeu"),
    Opcao("conc_torrefacao", "Torrefação da região", "comprou_outro", concorrente="Torrefação da região"),
    Opcao("conc_distribuidor", "Distribuidor/atacadista", "comprou_outro",
          concorrente="Distribuidor/atacadista"),
    Opcao("conc_outra", "Outra (vou escrever)", "comprou_outro"),
    Opcao("conc_nao_dizer", "Prefiro não dizer", "comprou_outro", observacao="preferiu não dizer a marca"),
)
PERGUNTA_CONCORRENTE_TEXTO = "Pode escrever o nome, por favor?"

PERGUNTA_PRECO = "Entendi. Você comparou com o quê?"
BOTOES_PRECO: tuple[Opcao, ...] = (
    Opcao("preco_fornecedor", "Outro fornecedor", "preco_margem", observacao="comparou com outro fornecedor"),
    Opcao("preco_ml_site", "Preço no ML/site", "preco_margem",
          observacao="comparou com o nosso preço no Mercado Livre/site"),
    Opcao("preco_margem", "Não dava a margem", "preco_margem", observacao="não dava a margem dele"),
)

PERGUNTA_AVISAR = "Obrigado! Isso ajuda muito. Se a gente mudar essa condição, posso te avisar?"
BOTOES_AVISAR: tuple[Opcao, ...] = (
    Opcao("avisar_sim", "Pode avisar", observacao="pode avisar se a condição mudar"),
    Opcao("avisar_nao", "Não precisa"),
)

PERGUNTA_RECONTATO = "Sem pressa! Quer que eu te mande as condições de novo daqui a 15 dias?"
BOTOES_RECONTATO: tuple[Opcao, ...] = (
    Opcao("recontato_sim", "Pode mandar", observacao="pediu as condições de novo em 15 dias"),
    Opcao("recontato_nao", "Não precisa"),
)
RECONTATO_DIAS = 15

MSG_USO_PROPRIO = "Ah, que bom saber! Nosso café para casa está na loja: loja.cafecanastra.com 🙂"
MSG_FECHAMENTO = "Muito obrigado pela sinceridade, {nome}. Qualquer coisa, é só chamar."

# Nó → (opções aceitas). O REGISTRO é o que um runner usaria; hoje ninguém o lê.
REGISTRO: dict[str, tuple[Opcao, ...]] = {
    NO_MOTIVO: BOTOES_MOTIVO,
    NO_CONCORRENTE: BOTOES_CONCORRENTE,
    NO_PRECO: BOTOES_PRECO,
    NO_AVISAR: BOTOES_AVISAR,
    NO_RECONTATO: BOTOES_RECONTATO,
}

# Depois do 1º clique, qual pergunta vem.
_SEGUINTE: dict[str, tuple[str, str]] = {
    "comprou_outro": (NO_CONCORRENTE, PERGUNTA_CONCORRENTE),
    "preco": (NO_PRECO, PERGUNTA_PRECO),
    "frete": (NO_AVISAR, PERGUNTA_AVISAR),
    "pedido_minimo": (NO_AVISAR, PERGUNTA_AVISAR),
    "condicao": (NO_AVISAR, PERGUNTA_AVISAR),
    "ainda_vendo": (NO_RECONTATO, PERGUNTA_RECONTATO),
}

_PAYLOAD_SEP = "|"


@dataclass(frozen=True)
class Decisao:
    """O que fazer com um evento. `codigo`/`concorrente` None = não mexer nesse campo."""
    proximo_no: str
    mensagens: tuple[str, ...] = ()
    botoes: tuple[Opcao, ...] = ()
    codigo: str | None = None
    concorrente: str | None = None
    observacao: str | None = None
    recontato_dias: int | None = None
    avisar_se_mudar: bool = False
    marcar_consumidor_final: bool = False
    # True = evento não casou com nada do nó: o runner entrega ao humano (João).
    ao_humano: bool = False


def _id_do_payload(payload: str | None) -> str | None:
    if not payload or _PAYLOAD_SEP not in payload:
        return None
    partes = payload.split(_PAYLOAD_SEP)
    if len(partes) < 2 or partes[0] != FLOW_ID:
        return None
    return partes[1] or None


def casar(no: str, payload: str | None, titulo: str | None = None) -> Opcao | None:
    """A opção do nó que o clique representa: por payload custom, id cru ou rótulo
    (sem acento/caixa, porque quick reply de template devolve o TEXTO do botão)."""
    opcoes = REGISTRO.get(no, ())
    por_id = {o.id: o for o in opcoes}
    for chave in (_id_do_payload(payload), payload):
        if chave and chave in por_id:
            return por_id[chave]
    por_titulo = {normalizar(o.titulo): o for o in opcoes}
    return por_titulo.get(normalizar(payload)) or por_titulo.get(normalizar(titulo))


def _fechamento(nome: str) -> str:
    nome = (nome or "").strip()
    if not nome:
        return MSG_FECHAMENTO.replace(", {nome}", "")
    return MSG_FECHAMENTO.format(nome=nome)


def decidir(no: str, *, payload: str | None = None, titulo: str | None = None,
            texto: str | None = None, nome: str = "") -> Decisao:
    """Função pura: estado + evento → Decisao. Nunca levanta."""
    if no == NO_CONCORRENTE_TEXTO:
        marca = mp.normalizar_concorrente(texto)
        if not marca:
            return Decisao(proximo_no=no, ao_humano=True)
        return Decisao(proximo_no=NO_ENCERRADO, mensagens=(_fechamento(nome),),
                       codigo=mp.COMPROU_OUTRO, concorrente=marca)

    opcao = casar(no, payload, titulo)
    if opcao is None:
        return Decisao(proximo_no=no, ao_humano=True)

    if no == NO_MOTIVO:
        if opcao.id == "uso_proprio":
            return Decisao(proximo_no=NO_ENCERRADO, mensagens=(MSG_USO_PROPRIO, _fechamento(nome)),
                           codigo=opcao.codigo, marcar_consumidor_final=True)
        seguinte, pergunta = _SEGUINTE[opcao.id]
        return Decisao(proximo_no=seguinte, mensagens=(pergunta,), botoes=REGISTRO[seguinte],
                       codigo=opcao.codigo)

    if opcao.id == "conc_outra":
        return Decisao(proximo_no=NO_CONCORRENTE_TEXTO, mensagens=(PERGUNTA_CONCORRENTE_TEXTO,),
                       codigo=opcao.codigo)

    return Decisao(
        proximo_no=NO_ENCERRADO,
        mensagens=(_fechamento(nome),),
        codigo=opcao.codigo,
        concorrente=opcao.concorrente,
        observacao=opcao.observacao,
        recontato_dias=RECONTATO_DIAS if opcao.id == "recontato_sim" else None,
        avisar_se_mudar=opcao.id == "avisar_sim",
    )


def aplicar(lead_id: str, decisao: Decisao, *, deal_id: str | None = None, sb=None) -> str | None:
    """Grava a resposta no card. Devolve o deal_id gravado (None = nada gravado). Fail-soft.

    Card = `deal_id` (o da lista `scripts/pesquisa_perda/atacados_sem_compra_60d.sql`) ou o
    mais recente do lead. NÃO move o card de etapa: quem decide se o lead está perdido é o
    João. Grava só o motivo estruturado e a observação, e deixa nota no lead.
    """
    if decisao.codigo is None and decisao.observacao is None:
        return None
    try:
        if sb is None:
            from app.db.supabase import get_supabase
            sb = get_supabase()
        if not deal_id:
            rows = (sb.table("deals").select("id").eq("lead_id", lead_id)
                    .order("updated_at", desc=True).limit(1).execute().data) or []
            deal_id = rows[0]["id"] if rows else None
        if not deal_id:
            logger.warning("pesquisa_perda.aplicar: lead %s sem card", lead_id)
            return None
        update: dict[str, Any] = {}
        if decisao.codigo is not None:
            update["lost_reason_code"] = mp.codigo_ou_padrao(decisao.codigo)
            # Concorrente só acompanha comprou_outro; um clique que só confirma o código
            # (ex.: "Outra (vou escrever)") não apaga o nome já gravado.
            if update["lost_reason_code"] != mp.COMPROU_OUTRO:
                update["lost_competitor"] = None
            elif decisao.concorrente:
                update["lost_competitor"] = mp.normalizar_concorrente(decisao.concorrente)
        if decisao.observacao:
            update["lost_reason"] = f"pesquisa de perda: {decisao.observacao}"
        sb.table("deals").update(update).eq("id", deal_id).execute()
        partes = [mp.ROTULOS.get(update.get("lost_reason_code", ""), "")]
        if update.get("lost_competitor"):
            partes.append(f"comprou de {update['lost_competitor']}")
        if decisao.observacao:
            partes.append(decisao.observacao)
        sb.table("lead_notes").insert({
            "lead_id": lead_id,
            "content": "[pesquisa de perda] " + " — ".join(p for p in partes if p),
        }).execute()
        return deal_id
    except Exception as exc:
        logger.error("pesquisa_perda.aplicar: lead %s deal %s: %s", lead_id, deal_id, exc)
        return None

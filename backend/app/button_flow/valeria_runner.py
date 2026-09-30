"""Orquestração da ValerIA de botões: o único módulo do fluxo com I/O.

Irmão de `button_flow/runner.py` (o runner da Recuperação) e com a mesma divisão:
guardas -> evento -> decisão -> efeitos -> envio -> estado. `valeria_engine.decidir`
é puro e `valeria_registry` é só dado; aqui ficam o banco, a Meta e o CRM.

O que é REUSADO do irmão, e por quê: `_montar_evento`, `_reler_estado` e
`_motivo_para_nao_rodar` não têm nada de Recuperação dentro — são,
respectivamente, "clique ou texto?", "relê `flow_state` depois do lock" e "um
humano já assumiu?". Duas cópias divergiriam no primeiro webhook fora do padrão,
que é a classe de bug que `campaigns/node_registry.py` documenta. O que NÃO é
reusado é `_envelhecer` (amarrado a `flows.NO_INTERESSE` e à janela de retomada da
Recuperação) nem `_notificar_sem_rodar` (o texto diz "[RECUPERAÇÃO]").

Zero IA, e isso é contrato: nenhuma linha aqui chama classificador, orchestrator
ou LLM. O fluxo inteiro é máquina de estados sobre `valeria_registry`.

── Três decisões que o plano não fixava ─────────────────────────────────────
1. A FOTO. `No.foto` é caminho de arquivo dentro do container
   (`backend/app/photos/...`) e a Meta só aceita `header.image.link` com URL
   pública (`whatsapp/meta.py:345`). Não existe servidor de estático no app
   (nenhum `StaticFiles`), nem base pública em env: o caminho local NÃO é uma
   URL, e o único caminho de foto em produção hoje sobe BYTES para a Meta
   (`agent/tools.py` -> `send_image_base64` -> `upload_media` -> `image.id`),
   que este header não aceita. A saída é `url_publica_da_foto`: sobe a foto UMA
   vez para o bucket público que o repo já usa para imagem outbound
   (`buffer/processor.py:_upload_image_to_storage`, bucket `whatsapp-media`) num
   caminho DETERMINÍSTICO com `x-upsert`, e cacheia a URL no processo. Subimos
   nós mesmos em vez de montar a URL na mão porque `get_public_url` de um objeto
   que não existe dá 404 na Meta — e a Meta recusa a mensagem INTEIRA quando não
   consegue buscar o header, o que deixaria o lead sem a tela de encaminhamento.
   Falha de publicação degrada para tela SEM foto, nunca para turno sem resposta.
2. COM CARTÃO DE CONTATO — e a decisão ANTERIOR (não mandar) estava errada. Ela
   dizia que "o handoff é na MESMA thread da ValerIA, então o vendedor responde
   nela". Não responde: o João atende em 553491461669 e o Arthur em outro número,
   os dois FORA do número da ValerIA. A auditoria do funil mediu que essa troca
   de número perde 26% dos leads (131 de 500) e o cartão é o único degrau que o
   lead tem para alcançar a pessoa — `agent/tools.py:2012` declara isso como
   contrato de produção ("O sistema envia a mensagem e, em seguida, o cartão do
   João — NÃO cole telefone, link ou wa.me"). Sem o cartão o corpo promete "ele
   te responde em instantes" e não entrega caminho nenhum. Quem manda é o runner
   (não o motor, que é puro): cartão é I/O e depende do CANAL.
3. SEM REGRA DE IDADE. O irmão reinicia estado com mais de N dias porque lá o
   estado nasce de um DISPARO (30% dos cliques chegam fora da janela de 24h).
   Aqui o estado nasce do próprio lead falando, e a spec não declara janela
   nenhuma: inventar uma seria comportamento não especificado. Um clique muito
   antigo retoma o nó, como o registry declara.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from app.agent.tools import (
    EXPORTACAO_NAME,
    EXPORTACAO_PHONE,
    SUPERVISOR_NAME,
    SUPERVISOR_PHONE,
)
from app.button_flow import config, effects, valeria_content, valeria_registry as reg
from app.button_flow import valeria_engine as motor
from app.button_flow import flows
from app.button_flow.engine import Clique, Mensagem, Texto, normalizar
from app.button_flow.runner import (
    _montar_evento,
    _motivo_para_nao_rodar,
    _reler_estado,
)
from app.conversations.service import save_message, update_conversation
from app.db.supabase import get_supabase
from app.lead_score.repository import save_score_evidence
from app.leads.service import get_open_deal, resolve_send_target
from app.whatsapp.meta import extract_wamid

logger = logging.getLogger(__name__)

_LOG = "[VALERIA BOTOES]"

# ── O cartão de contato (ver decisão 2 no cabeçalho) ────────────────────────
# (nome do vCard, telefone) por vendedor. A chave é o identificador do registry
# (`reg.VENDEDOR_*`) e o valor sai de `agent/tools.py`, onde os números dos
# vendedores já moram e de onde `encaminhar_humano` e a ponte do
# `buffer/processor.py` já os leem. Reusa, não redeclara: um segundo lugar com o
# telefone do João é um segundo lugar para ele ficar velho.
#
# O nome do cartão NÃO é `reg.VENDEDOR_*`: aqueles são identificadores sem acento
# ("Joao Bras"), porque vão no argumento `vendedor=` de `encaminhar_humano`. Aqui
# é o texto que o lead vê na agenda do telefone dele.
CARTOES: dict[str, tuple[str, str]] = {
    reg.VENDEDOR_ATACADO: (SUPERVISOR_NAME, SUPERVISOR_PHONE),
    reg.VENDEDOR_EXPORTACAO: (EXPORTACAO_NAME, EXPORTACAO_PHONE),
}

# ── A foto (ver decisão 1 no cabeçalho) ─────────────────────────────────────
_DIR_FOTOS = Path(__file__).resolve().parent.parent / "photos"
# Mesmo bucket de `buffer/processor.py:_upload_image_to_storage` — ele já é
# público (`get_public_url`) e é dele que a bolha do CRM carrega imagem outbound.
# Um bucket novo seria um segundo lugar para alguém esquecer de tornar público.
_BUCKET_FOTOS = "whatsapp-media"
# Prefixo próprio e caminho DETERMINÍSTICO (o do registry): com `x-upsert` o
# mesmo arquivo reescreve o mesmo objeto, então reiniciar o processo não acumula
# lixo — ao contrário do `outbound/agent_<uuid>` do processor, que é único por
# chamada e não daria URL estável para cachear.
_PREFIXO_FOTOS = "valeria-botoes"
_urls_de_foto: dict[str, str] = {}

# Marcador de corpo não resolvido. Qualquer `{chave}` que sobre depois do render
# leva a LINHA inteira embora — ver `_resolver`.
_MARCADOR = re.compile(r"\{[a-z_]+\}")


def limpar_cache_de_fotos() -> None:
    """Esvazia o cache de URLs de foto (uso em teste e troca de arquivo)."""
    _urls_de_foto.clear()


def url_publica_da_foto(caminho: str | None) -> str | None:
    """URL pública da foto declarada no nó, ou None quando não dá para publicar.

    Bloqueante (sobe o arquivo). Cacheia só SUCESSO: cachear a falha faria uma
    indisponibilidade momentânea do Storage desligar a foto para o resto da vida
    do processo.
    """
    if not caminho:
        return None
    em_cache = _urls_de_foto.get(caminho)
    if em_cache:
        return em_cache
    url = _publicar_foto(caminho)
    if url:
        _urls_de_foto[caminho] = url
    return url


def _publicar_foto(caminho: str) -> str | None:
    try:
        arquivo = _DIR_FOTOS / caminho
        if not arquivo.is_file():
            # Erro de DADO, não de rede: o registry declara um arquivo que não
            # existe no container. Vale ERROR porque só um deploy conserta.
            logger.error("%s foto declarada e inexistente: %s", _LOG, arquivo)
            return None
        mimetype = "image/png" if arquivo.suffix.lower() == ".png" else "image/jpeg"
        destino = f"{_PREFIXO_FOTOS}/{caminho}"
        sb = get_supabase()
        sb.storage.from_(_BUCKET_FOTOS).upload(
            destino, arquivo.read_bytes(),
            file_options={"content-type": mimetype, "x-upsert": "true"},
        )
        return sb.storage.from_(_BUCKET_FOTOS).get_public_url(destino)
    except Exception as exc:
        logger.warning("%s foto %r não publicada — tela sai sem header: %s",
                       _LOG, caminho, exc)
        return None


# ── O corpo ─────────────────────────────────────────────────────────────────
def _resolver(corpo: str, contexto: dict | None) -> str:
    """Resolve os marcadores do corpo e CORTA a linha do que não resolveu.

    `flows.render` deixa a chave ausente como está de propósito (não é
    `str.format`, que estouraria) — então sem este corte o lead leria
    literalmente "gira em torno de {preco} a unidade". Cortar a LINHA, e não
    trocar por vazio, é o que espelha `flows.MSG_QUENTE_SEM_PRECO`: sem preço no
    catálogo a frase de preço não existe. Cotar de memória foi o que perdeu as
    500 unidades da Ritz.

    O corte é genérico (qualquer `{chave}`) e não só `{preco}`: a garantia que
    interessa é "nenhum marcador chega ao lead", e uma lista de marcadores
    conhecidos envelheceria junto com o registry.
    """
    dados = {k: str(v) for k, v in (contexto or {}).items() if v}
    texto = flows.render(corpo or "", dados)
    limpas: list[str] = []
    for linha in texto.splitlines():
        if _MARCADOR.search(linha):
            continue
        # Colapsa a linha vazia que o corte deixou para trás: sem isto o corpo
        # sai com um buraco de duas linhas em branco no meio.
        if not linha.strip() and (not limpas or not limpas[-1].strip()):
            continue
        limpas.append(linha)
    return "\n".join(limpas).strip()


def preco_do_no(no: reg.No) -> str:
    """Preço do SKU ativo declarado pelo nó, ou "" quando não dá para afirmar.

    Match ÚNICO e DENTRO DO SETOR do ramo, as duas regras do irmão
    (`runner._preco_de_tabela`) pelos mesmos dois motivos: dois candidatos
    significam que não sabemos qual SKU é (incidente Ritz — drip cotado a R$
    27,70 misturando com Microlote), e `products` é particionada por `sector`
    com o MESMO nome de SKU em setores diferentes a preços diferentes, então
    casar no catálogo inteiro cotaria varejo para cliente de atacado.

    `no.ramo` JÁ é a forma normalizada do `products.sector` de produção
    ("Atacado" -> "atacado", "Private Label" -> "private_label", via
    `catalog._normalize`), então o ramo do registry é o filtro de setor sem
    tabela de tradução no meio — uma tabela a mais seria uma a mais para
    divergir.
    """
    if not no.produto:
        return ""
    try:
        from app.agent.catalog import _fetch_active_products
        from app.agent.catalog import _normalize as _normalizar
        from app.agent.pricing import match_products
        do_setor = [p for p in _fetch_active_products()
                    if _normalizar(p.get("sector")) == no.ramo]
        candidatos = match_products(no.produto, do_setor)
    except Exception as exc:
        logger.warning("%s catálogo indisponível p/ %r — sem preço: %s",
                       _LOG, no.produto, exc)
        return ""
    if not do_setor:
        logger.warning("%s nenhum SKU ativo no setor %r — entrega SEM preço",
                       _LOG, no.ramo)
        return ""
    if len(candidatos) != 1:
        logger.info("%s produto %r casou com %d SKUs ativos — entrega SEM preço",
                    _LOG, no.produto, len(candidatos))
        return ""
    return (candidatos[0].get("price_formatted") or "").strip()


def _prazo_humano(dias: int | None) -> str:
    """"em 30 dias" a partir dos dias que o motor pôs em `recontato_dias`.

    Casa por DIAS porque a `Decisao` não carrega o id do botão clicado, e
    `flows.PRAZOS` é a dona do par (dias, rótulo humano) nos dois fluxos.
    """
    if not dias:
        return ""
    return next((p.rotulo_humano for p in flows.PRAZOS if p.dias == dias), "")


# ── Envio ───────────────────────────────────────────────────────────────────
def _pares(botoes) -> list[tuple[str, str]]:
    """(id, rótulo) — o id é o contrato que a Meta devolve no webhook."""
    return [(b.id, b.titulo) for b in botoes]


async def enviar_no(provider, telefone: str, no: reg.No, contexto: dict | None,
                    *, corpo: str | None = None,
                    rotulo_lista: str | None = None) -> dict | None:
    """Envia a tela de um nó. UMA mensagem, sempre.

    `corpo` sobrescreve `no.corpo` e é por onde o reoferecimento passa: o motor
    devolve o corpo do nudge com os MESMOS botões do nó, então o nudge de um nó
    de foto sai como a mesma tela com outro texto — e continua sendo uma
    mensagem só.

    `rotulo_lista` é o override da chave reservada `reg.CHAVE_ROTULO_LISTA` — o
    texto do botão que abre a folha de opções. Ausente = o default do registry.
    """
    texto = _resolver(corpo if corpo is not None else no.corpo, contexto)
    if no.tela == "lista":
        linhas = [(b.id, b.titulo, b.descricao) for b in no.botoes]
        return await provider.send_interactive_list(
            telefone, texto, rotulo_lista or reg.ROTULO_BOTAO_LISTA, linhas,
        )
    if not no.botoes:
        # Nó sem botão não existe no registry hoje (o teste de alcançabilidade
        # garante), mas um override de tela não pode virar exceção no inbound.
        return await provider.send_text(telefone, texto)
    imagem = None
    if no.tela == "foto_botoes":
        # `to_thread`: publicar a foto é I/O bloqueante. Sem URL a tela sai sem
        # header — o corpo já descreve o produto, e mensagem nenhuma seria pior.
        imagem = await asyncio.to_thread(url_publica_da_foto, no.foto)
    return await provider.send_interactive_buttons(
        telefone, texto, _pares(no.botoes), image_url=imagem,
    )


async def enviar_terminal(provider, telefone: str, terminal: reg.Terminal,
                          contexto: dict | None, *,
                          corpo: str | None = None) -> dict | None:
    """Envia o desfecho. Corpo vazio = NÃO envia nada, e isso é o contrato.

    `T_HUMANO` e `T_FIM` nascem com `corpo=""` justamente para não gastar
    mensagem faturada; mandar qualquer coisa aqui quebraria o "0 mensagens" que
    o registry declara nos dois.
    """
    bruto = corpo if corpo is not None else terminal.corpo
    texto = _resolver(bruto, contexto)
    if not texto:
        return None
    if terminal.prazos:
        # `T_ADIAR` PERGUNTA: a folha 30/60/90 é declarada no registry.
        return await provider.send_interactive_buttons(
            telefone, texto, _pares(reg.BOTOES_PRAZO), image_url=None,
        )
    return await provider.send_text(telefone, texto)


# ── Estado ──────────────────────────────────────────────────────────────────
def estado_inicial() -> dict:
    """O estado de quem ainda não viu tela nenhuma."""
    return {"flow": reg.FLOW_ID, "node": reg.NO_ENTRADA, "nudges": 0}


def no_atual(estado) -> str | None:
    """Nó em que o lead está, ou None quando o estado não é deste fluxo.

    None significa "comece limpo", e os três casos que levam a ele são
    deliberados:
      • estado ausente — primeiro contato;
      • estado de OUTRO fluxo — o `flow_state` da Recuperação tem `node`
        ('aguardando_prazo') que não existe aqui, e lê-lo como se fosse daqui
        entregaria o lead ao humano na primeira mensagem;
      • estado corrompido — `jsonb` aceita escalar, array e tipo errado em
        qualquer campo, e NADA no caminho do inbound pode estourar por isso.
    """
    if not isinstance(estado, dict):
        return None
    if estado.get("flow") != reg.FLOW_ID:
        return None
    node = estado.get("node")
    return node if isinstance(node, str) and node else None


def _nudges(estado) -> int:
    if not isinstance(estado, dict):
        return 0
    gastos = estado.get("nudges", 0)
    return gastos if isinstance(gastos, int) and not isinstance(gastos, bool) else 0


def proximo_estado(estado, node: str, marcar_nudge: bool = False) -> dict:
    """Estado do turno seguinte. Pura — o `updated_at` é do persistidor.

    Merge, e não substituição: o `flow_state` pode carregar chaves de outro dono
    (`rotulos_antigos`, que o motor usa para casar clique em tela editada) e
    sobrescrever o estado inteiro aqui as apagaria em silêncio.

    O nudge conta por ATENDIMENTO, não por nó: por nó, 17 nós dariam 51
    reofertas, e o desperdício máximo por lead passaria de 3 para 51 mensagens
    faturadas.
    """
    base = dict(estado) if isinstance(estado, dict) else {}
    base["flow"] = reg.FLOW_ID
    base["node"] = node
    base["nudges"] = _nudges(estado) + (1 if marcar_nudge else 0)
    return base


async def _persistir_estado(conversation: dict, estado, campos: dict) -> None:
    base = dict(campos)
    base["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        await asyncio.to_thread(update_conversation, conversation["id"], flow_state=base)
    except Exception as exc:
        logger.warning("%s flow_state não gravado p/ conv %s: %s",
                       _LOG, conversation.get("id"), exc)
    conversation["flow_state"] = base


# ── O score (o objetivo do ramo de atacado) ─────────────────────────────────
async def aplicar_criterios(lead_id: str, criterios: dict,
                            *, rotulo: str = "") -> None:
    """Grava o snapshot de score que o clique revelou. Fail-soft.

    Sem isto o ramo de atacado roda inteiro e não qualifica ninguém — que é
    exatamente o que o fluxo existe para consertar. E com isto ele qualifica sem
    uma única chamada de LLM: os 5 critérios de `lead_score/model.py` são
    justamente os 5 nós do ramo A.

    Critério vazio não toca o banco: a maioria dos nós não declara `grava` (só o
    ramo de atacado declara), e uma escrita por turno para gravar `{}` seria
    custo puro.

    `rotulo` é o texto que o lead TOCOU e vira a evidência do critério — a prova
    legível de onde o ponto veio. Rótulo vazio vira `evidence=None` de
    propósito: `repository._validate_evidence_shape` recusa texto vazio com
    ValueError, e a recusa levaria o critério inteiro embora.

    Fail-soft, inclusive para `ScoreWriteConflictError`: perder um ponto de score
    é menos grave que deixar o lead sem a próxima tela.
    """
    if not criterios or not lead_id:
        return
    evidencia = None
    if rotulo and rotulo.strip():
        evidencia = {campo: {"text": rotulo} for campo in criterios}
    try:
        await asyncio.to_thread(
            lambda: save_score_evidence(
                lead_id=lead_id, updates=dict(criterios),
                evidence=evidencia, source="live",
            )
        )
    except Exception as exc:
        logger.warning("%s score não gravado p/ lead %s (%s): %s",
                       _LOG, lead_id, criterios, exc)


# ── Ponto de entrada ────────────────────────────────────────────────────────
async def processar_inbound(
    *, lead: dict, conversation: dict, channel: dict, provider,
    texto: str, message_type: str | None = None, metadata: dict | None = None,
    wamid: str | None = None,
) -> None:
    """Roda um turno da ValerIA de botões. Nunca levanta.

    Chamado pelo despacho de `buffer/processor.py`, que já persistiu o inbound.
    """
    try:
        await _executar_turno(
            lead=lead, conversation=conversation, channel=channel,
            provider=provider, texto=texto, message_type=message_type,
            metadata=metadata, wamid=wamid,
        )
    except Exception as exc:
        # Fail-soft final: uma exceção subindo daqui abortaria o worker do buffer
        # e deixaria o turno sem nenhum registro.
        logger.error("%s turno falhou conv=%s lead=%s wamid=%s: %s", _LOG,
                     conversation.get("id"), lead.get("id"), wamid, exc,
                     exc_info=True)


def _carregar_conteudo() -> tuple[dict, dict, str | None, str | None]:
    """(nós, terminais, corpo do nudge, rótulo da lista) com os overrides da tela.

    `valeria_content.carregar` é fail-open (devolve `{}` em qualquer erro), então
    migration pendente ou PostgREST fora produz exatamente os defaults do
    registry — e não uma ValerIA muda.

    Os TERMINAIS passam por `aplicar_terminais`, e não por `aplicar`: `Terminal`
    não tem `botoes`. Sem essa segunda chamada o operador editava o texto do
    handoff na tela, salvava, e o lead continuava recebendo o do registry —
    override morto e invisível justamente no turno que a auditoria 08/07 chama de
    "momento mais frágil" da conversa.

    As duas chaves RESERVADAS (nudge e rótulo da lista) saem à parte porque não
    são nó: `valeria_flow_content` é chaveada por `node_id` e elas não têm nó
    nenhum a que pertencer.
    """
    try:
        overrides = valeria_content.carregar(reg.FLOW_ID)
    except Exception as exc:
        logger.warning("%s overrides não lidos — defaults do registry: %s", _LOG, exc)
        overrides = {}
    nudge = (overrides.get(reg.CHAVE_NUDGE) or {}).get("corpo")
    rotulo_lista = (overrides.get(reg.CHAVE_ROTULO_LISTA) or {}).get("corpo")
    return (
        valeria_content.aplicar(reg.NOS, overrides),
        valeria_content.aplicar_terminais(reg.TERMINAIS, overrides),
        nudge or None,
        rotulo_lista or None,
    )


def _e_pedido_de_saida(evento) -> bool:
    """Texto livre que é pedido de saída, pela MESMA lista do motor.

    Existe porque o primeiro contato não passa pelo motor (ver
    `_decidir`): sem esta checagem, o lead cujo primeiro "oi" fosse "pare"
    receberia a tela de entrada — a Meta EXIGE honrar o pedido de parar, e
    ignorá-lo no primeiro turno é o pior lugar possível para ignorá-lo.
    """
    return (isinstance(evento, Texto)
            and normalizar(evento.conteudo) in motor.FRASES_OPTOUT)


def _decidir(no: str | None, evento, estado, nos: dict, terminais: dict,
             corpo_nudge: str | None) -> motor.Decisao:
    """Decisão do turno, com a exceção do PRIMEIRO CONTATO.

    Quem ainda não viu tela nenhuma não está respondendo a botão: rodar o motor
    aqui devolveria o corpo do NUDGE ("é só tocar numa das opções") para alguém
    que nunca recebeu opção nenhuma — e gastaria um dos 3 nudges no turno de
    abertura. Então o primeiro contato recebe a tela de entrada.

    A ÚNICA coisa que vence a tela de entrada é o pedido de saída, e por isso
    esse caso volta para o motor: quem chega dizendo "pare" sai por `T_OPTOUT`,
    com o efeito gravado, sem gastar nudge.
    """
    if no is not None:
        return motor.decidir(no, evento, estado, nos, terminais,
                             corpo_nudge=corpo_nudge)
    if _e_pedido_de_saida(evento):
        return motor.decidir(reg.NO_ENTRADA, evento, {}, nos, terminais,
                             corpo_nudge=corpo_nudge)
    entrada = nos.get(reg.NO_ENTRADA)
    if entrada is None:
        # Registry sem nó de entrada é impossível pelo teste de estrutura, mas o
        # caminho seguro de todo erro deste fluxo é o humano.
        return motor.decidir(reg.NO_ENTRADA, evento, {}, nos, terminais,
                             corpo_nudge=corpo_nudge)
    return motor.Decisao(
        proximo_no=reg.NO_ENTRADA,
        mensagem=Mensagem(corpo=entrada.corpo, botoes=entrada.botoes),
    )


def _contexto_de_envio(destino: reg.No | None, decisao: motor.Decisao) -> dict:
    """Os marcadores que o corpo do destino pode pedir.

    Montado a partir do DESTINO, não do nó de origem: o `{preco}` é do produto
    que a próxima tela mostra, e o `{prazo}` sai dos dias que o motor acabou de
    agendar.
    """
    contexto: dict = {}
    if destino is not None and destino.produto:
        contexto["preco"] = preco_do_no(destino)
    prazo = _prazo_humano(decisao.efeitos.recontato_dias)
    if prazo:
        contexto["prazo"] = prazo
    return contexto


async def _enviar(decisao: motor.Decisao, *, lead: dict, conversation: dict,
                  channel: dict | None, provider, nos: dict, terminais: dict,
                  rotulo_lista: str | None = None) -> None:
    """Manda a tela do destino, o cartão do vendedor e persiste. Fail-soft.

    O corpo vem SEMPRE de `decisao.mensagem`, e não do registry: é o motor que
    sabe se este turno é a tela do nó ou o reoferecimento dele. A ESTRUTURA
    (lista/botões/foto) vem do nó, porque `Mensagem` não a carrega.
    """
    mensagem = decisao.mensagem
    if mensagem is None:
        # Contrato declarado de `T_HUMANO`/`T_FIM`: 0 mensagens faturadas.
        return
    destino = resolve_send_target(lead, lead.get("phone"))
    no = nos.get(decisao.proximo_no)
    terminal = terminais.get(decisao.proximo_no)
    contexto = await asyncio.to_thread(_contexto_de_envio, no, decisao)
    try:
        if no is not None:
            resultado = await enviar_no(provider, destino, no, contexto,
                                        corpo=mensagem.corpo,
                                        rotulo_lista=rotulo_lista)
        elif terminal is not None:
            resultado = await enviar_terminal(provider, destino, terminal,
                                              contexto, corpo=mensagem.corpo)
        else:
            # Destino fora do registry (override de tela apontando para nó
            # removido). Texto puro é a degradação: o lead ainda é respondido.
            resultado = await provider.send_text(
                destino, _resolver(mensagem.corpo, contexto))
    except Exception as exc:
        logger.error("%s falha ao enviar p/ conv %s: %s", _LOG,
                     conversation.get("id"), exc, exc_info=True)
        return
    if resultado is None:
        return
    await _persistir_mensagem(conversation, lead, mensagem, contexto, no, resultado)
    await _enviar_cartao(provider, destino, terminal, channel,
                         conversation=conversation, lead=lead)


def _cartao_do_terminal(terminal: reg.Terminal | None,
                        channel: dict | None) -> tuple[str, str] | None:
    """(nome, telefone) do cartão a enviar neste desfecho, ou None.

    Três motivos para não haver cartão, e os três são desfechos normais:
      • o destino não entrega ninguém (`handoff=False`: adiamento, opt-out, fim);
      • o terminal não declara vendedor — nada a apresentar;
      • CANAL DO VENDEDOR: a conversa JÁ está no número dele. Mandar o cartão de
        quem está do outro lado da conversa é absurdo, e é o mesmo raciocínio que
        `engine.py:317` implementa para a Recuperação (que roda no número do João).

    A regra do canal é por NÚMERO, não por `mode == "human"` como no irmão, e a
    diferença importa porque aqui existem DOIS vendedores: no número do João, o
    cartão do Arthur continua sendo exatamente o que o lead de exportação precisa
    para alcançá-lo. Comparar o número é o que distingue "o vendedor deste cartão
    já está aqui" de "algum humano está aqui".

    Quando o canal é humano e não sabemos o número dele, cai na regra do irmão:
    sem poder provar que não é o número deste vendedor, não manda. É o único caso
    em que o silêncio é a escolha — e ele nunca acontece no número da ValerIA, que
    é onde 100% deste fluxo roda hoje.
    """
    if terminal is None or not terminal.handoff:
        return None
    cartao = CARTOES.get(terminal.vendedor or "")
    if cartao is None:
        if terminal.vendedor:
            # Vendedor declarado no registry sem cartão aqui: erro de DADO, só um
            # deploy conserta, e o lead fica sem caminho até a pessoa.
            logger.error("%s terminal %s entrega a %r e não há cartão declarado",
                         _LOG, terminal.id, terminal.vendedor)
        return None
    do_canal = _so_digitos((channel or {}).get("phone"))
    if do_canal and do_canal == _so_digitos(cartao[1]):
        return None
    if not do_canal and (channel or {}).get("mode") == "human":
        logger.info("%s canal humano sem telefone conhecido — cartão de %s omitido",
                    _LOG, cartao[0])
        return None
    return cartao


def _so_digitos(valor: str | None) -> str:
    """Só os dígitos: `channels.phone` e o número do cartão podem vir formatados."""
    return re.sub(r"\D", "", valor or "")


async def _enviar_cartao(provider, destino: str, terminal: reg.Terminal | None,
                         channel: dict | None, *, conversation: dict,
                         lead: dict) -> None:
    """Manda o vCard do vendedor logo depois do corpo do handoff. Fail-soft.

    Depois, e não antes: o corpo é que explica o cartão ("já chamei o João Brás
    aqui"), e a ordem inversa entregaria um contato sem contexto. Mesma ordem de
    `agent/tools.py:944` e de `runner.py:513`, os dois caminhos de handoff que já
    rodam em produção.

    Fail-soft e por último no turno de propósito: os efeitos de CRM já foram
    aplicados e o corpo já saiu. Uma exceção aqui desfaria o turno inteiro — o
    estado não avançaria e o lead receberia o mesmo handoff de novo no próximo
    toque, com segundo carimbo e segundo movimento de card.
    """
    cartao = _cartao_do_terminal(terminal, channel)
    if cartao is None:
        return
    nome, telefone = cartao
    try:
        await provider.send_contact(destino, contact_name=nome, contact_phone=telefone)
    except Exception as exc:
        # WARNING, não ERROR: o handoff aconteceu e está registrado no CRM; o que
        # se perdeu é o atalho até o vendedor.
        logger.warning("%s cartão de %s não enviado conv=%s: %s", _LOG, nome,
                       conversation.get("id"), exc)
        return
    try:
        await asyncio.to_thread(
            save_message, conversation.get("id"), lead.get("id"), "system",
            f"[valeria_botoes] cartão de contato de {nome} enviado",
            conversation.get("stage"), sent_by="valeria_botoes",
        )
    except Exception as exc:
        logger.warning("%s cartão enviado mas não registrado conv=%s: %s", _LOG,
                       conversation.get("id"), exc)


async def _persistir_mensagem(conversation: dict, lead: dict, mensagem, contexto,
                              no, resultado) -> None:
    """Grava a saída em `messages`. Fail-soft: a mídia JÁ foi entregue.

    `media_url` só sai do CACHE (`_urls_de_foto`), nunca de uma publicação nova:
    a foto acabou de ser publicada por `enviar_no`, e um segundo `_publicar_foto`
    aqui faria I/O de novo dentro do loop para um campo cosmético do CRM.
    """
    media = _urls_de_foto.get(no.foto) if (no is not None and no.foto) else None
    try:
        await asyncio.to_thread(
            save_message, conversation.get("id"), lead.get("id"), "assistant",
            _resolver(mensagem.corpo, contexto), conversation.get("stage"),
            sent_by="valeria_botoes", media_url=media,
            message_type="image" if media else None,
            wamid=extract_wamid(resultado),
        )
    except Exception as exc:
        logger.warning("%s mensagem enviada mas não persistida conv=%s: %s",
                       _LOG, conversation.get("id"), exc)


async def _executar_turno(
    *, lead: dict, conversation: dict, channel: dict, provider,
    texto: str, message_type: str | None, metadata: dict | None,
    wamid: str | None,
) -> None:
    conversation_id = conversation.get("id")
    lead_id = lead.get("id")

    if not config.enabled(reg.FLOW_ID):
        # `reg.FLOW_ID` explícito: ligar a ValerIA não pode ligar a Recuperação
        # (que roda no número pessoal de um vendedor e tem 3 bloqueantes).
        # Redundante com o gate de propósito — este runner é público, e um
        # chamador novo não pode ligar o bot sem querer.
        logger.info("%s kill switch OFF — nada a fazer conv=%s", _LOG, conversation_id)
        return

    # Relê o estado: o `conversation` chegou aqui lido ANTES do lead_run_lock que
    # o gate segura, e com o estado velho o segundo toque do mesmo lead
    # reexecutaria a MESMA transição — segundo handoff, segunda tag, segunda
    # mensagem. Ver `runner._reler_estado`.
    estado = await asyncio.to_thread(_reler_estado, conversation)
    deal = await asyncio.to_thread(get_open_deal, lead_id)

    motivo = _motivo_para_nao_rodar(lead, estado, deal)
    if motivo:
        await _notificar_sem_rodar(lead, conversation, estado, motivo)
        return

    evento = _montar_evento(texto, message_type, metadata)
    nos, terminais, corpo_nudge, rotulo_lista = await asyncio.to_thread(
        _carregar_conteudo)
    no = no_atual(estado)
    decisao = _decidir(no, evento, estado, nos, terminais, corpo_nudge)

    if decisao.ignorar:
        logger.info("%s evento ignorado (nó=%s) conv=%s wamid=%s", _LOG,
                    decisao.proximo_no, conversation_id, wamid)
        return

    avancar = await asyncio.to_thread(
        effects.aplicar, decisao.efeitos, lead=lead,
        conversation_id=conversation_id,
        evidencia=_evidencia_do_turno(evento, texto, wamid),
        # Quem lê as notas que `effects` escreve é o vendedor, antes de abordar o
        # lead. O default de `aplicar` é a Recuperação, e deixá-lo passar aqui
        # carimbaria "bot de recuperação" num lead que nunca esteve numa onda de
        # recuperação — mentira de auditoria no card mais valioso do funil.
        fluxo=effects.FLUXO_VALERIA,
    )
    if not avancar:
        # Só o opt-out devolve False. Confirmar "não te mando mais nada" sem ter
        # gravado `opt_out=true` é pior que o silêncio: o lead perde o motivo
        # para tocar no botão de novo e a retentativa morre junto.
        logger.error("%s efeitos bloquearam o turno (opt-out não gravado) — sem "
                     "envio e sem avanço conv=%s lead=%s", _LOG,
                     conversation_id, lead_id)
        return

    await _enviar(decisao, lead=lead, conversation=conversation, channel=channel,
                  provider=provider, nos=nos, terminais=terminais,
                  rotulo_lista=rotulo_lista)
    await aplicar_criterios(lead_id, decisao.criterios,
                            rotulo=_rotulo_clicado(evento))

    campos = proximo_estado(estado, decisao.proximo_no,
                            marcar_nudge=decisao.marcar_nudge)
    if deal and deal.get("stage_id"):
        # Referência do guarda "o vendedor já mexeu no card" no próximo turno.
        # `stage_id` é a ÚNICA coluna de etapa que `get_open_deal` projeta.
        campos["deal_stage_id"] = deal["stage_id"]
    await _persistir_estado(conversation, estado, campos)
    logger.info("%s turno aplicado conv=%s nó=%s nudges=%s", _LOG,
                conversation_id, decisao.proximo_no, campos["nudges"])


def _rotulo_clicado(evento) -> str:
    """Texto que o lead tocou — a evidência do critério de score."""
    if isinstance(evento, Clique):
        return (evento.titulo or evento.payload or "").strip()
    return ""


def _evidencia_do_turno(evento, texto: str, wamid: str | None) -> dict:
    """Registro cru do turno, no contrato de `effects._campos_de_evidencia`.

    Sem isto o opt-out nasce como o "booleano nu": `opt_out_channel` fica NULL e
    não há como provar à ANPD QUE o lead pediu para sair nem COMO. É a lacuna
    dos 52 opt-outs de produção que um SQL corretivo teve que reparar à mão.
    """
    dados: dict = {"wamid": wamid}
    if isinstance(evento, Clique):
        dados["origem"] = "clique"
        dados["button_payload"] = evento.payload
        dados["button_label"] = evento.titulo
    else:
        dados["origem"] = "classe"
        dados["texto"] = (texto or "")[:500]
    return dados


# A nota "Lead encaminhado a <vendedor>, não ao vendedor padrão" que existia aqui
# FOI REMOVIDA, e não por limpeza: ela era o remendo de um defeito que agora tem
# conserto de raiz. `Efeitos.vendedor` (engine.py) leva o vendedor do terminal até
# `effects._aplicar_handoff`, que já grava o nome certo nos TRÊS registros do
# handoff (marcador do dashboard, `metadata.handoff` e a própria nota de
# transbordo). Mantê-la escreveria uma segunda nota e uma segunda system message
# dizendo o que a primeira já diz — ruído em cima da conversa mais valiosa do
# funil, que é exatamente o que `_notificar_sem_rodar` documenta não querer.


async def _notificar_sem_rodar(lead: dict, conversation: dict, estado,
                               motivo: str) -> None:
    """Sai de cena e avisa. UMA anotação por conversa, não por mensagem.

    Sem o guarda de repetição, o lead que segue conversando com o vendedor
    depois do transbordo encheria o histórico de notas idênticas do bot — ruído
    em cima justamente da conversa mais valiosa.
    """
    conversation_id = conversation.get("id")
    logger.info("%s não roda conv=%s: %s", _LOG, conversation_id, motivo)
    if isinstance(estado, dict) and estado.get("notificado_humano"):
        return
    await asyncio.to_thread(
        effects.anotar, lead.get("id"), conversation_id,
        f"🤖 [VALERIA BOTÕES] Bot saiu de cena nesta conversa: {motivo}.",
    )
    campos = dict(estado) if isinstance(estado, dict) else {}
    campos["notificado_humano"] = True
    if not campos.get("flow"):
        # Gravar só o marcador deixaria um flow_state sem `flow`/`node`, que o
        # motor lê como incompatível. Carimba o equivalente ao estado ausente,
        # para o dia em que o humano devolver a conversa não começar por um
        # estado corrompido. E NÃO sobrescreve um `flow` que já existe: um
        # `flow_state` da Recuperação nesta conversa é problema de roteamento, e
        # apagar o nó do outro fluxo aqui destruiria a prova disso.
        campos.update(estado_inicial())
    await _persistir_estado(conversation, estado, campos)

"""Núcleo puro do bot de botões: declaração do fluxo + motor de decisão.

Sem I/O: tudo aqui opera sobre dicts e dataclasses, no mesmo espírito de
app/agent/persona.py. É a camada onde a matriz de comportamento tem que estar
100% coberta, porque é a única que roda igual em produção e no teste.

── Reescrito em 09/09/2026, junto com o relabel do commit 31ccb5ce ───────────
O trio original ("Quero comprar agora" / "Talvez em alguns meses" /
"Não quero mais receber") foi medido em ~1.300 envios reais e trocado pelo trio de
ESTADO ("Preciso repor" / "Ainda tenho estoque" / "Parar mensagens"); o nível 2
virou dias (30/60/90, o ciclo real de recompra da coorte é 78-122 dias); e o
mesmo motor passou a servir três trilhas de template — pedido, estoque, cadastro.

Os invariantes de segurança abaixo NÃO mudaram de conteúdo, só de rótulo. São eles
que impedem que um botão novo desligue lead da base sozinho, que um flow_state
corrompido reinicie quem já foi entregue ao vendedor, e que tocar duas vezes no
mesmo botão gaste o único reoferecimento que o lead tem direito.
"""
import dataclasses

import pytest

from app.button_flow import engine, flows
from app.button_flow.engine import Classificado, Clique, Contexto, Texto

# Contexto típico do caminho feliz: nome + produto que casou com um dos 32 SKUs
# ativos, portanto com preço.
CTX = Contexto(primeiro_nome="Ana", produto="Microlote 1kg", preco="R$ 49,90")


def estado(no: str = flows.NO_INTERESSE, nudged: bool = False,
           trilha: str | None = None) -> dict:
    est = {"flow": flows.FLOW_ID, "node": no, "nudged": nudged}
    if trilha is not None:
        est["trilha"] = trilha
    return est


# ── Declaração do fluxo ─────────────────────────────────────────────────────
def test_limites_da_meta_nos_botoes():
    """3 botões no máximo, título de até 20 chars na interativa, ids únicos.

    Vale para cada trilha E para o menu de prazo: todos saem como mensagem
    interativa no reoferecimento, onde a Meta corta em 3 botões e 20 chars.
    """
    menus = {**flows.BOTOES_POR_TRILHA, "prazo": flows.BOTOES_PRAZO}
    for menu, botoes in menus.items():
        assert 1 <= len(botoes) <= 3, f"{menu}: a Meta aceita no máximo 3 botões"
        ids = [b.id for b in botoes]
        assert len(ids) == len(set(ids)), f"{menu}: ids duplicados"
        for b in botoes:
            assert len(b.titulo) <= 20, f"{menu}/{b.id}: título > 20 chars na interativa"


def test_rotulo_de_cada_trilha_casa_de_volta_no_mesmo_id():
    """O rótulo que o lead VÊ tem que casar no botão que ele representa.

    Cada trilha exibe rótulos próprios — "Retomar o pedido" na A, "Preciso repor" na
    B — mas o motor casa num índice único montado sobre TODOS_BOTOES_NIVEL1. Um
    rótulo de trilha que não esteja nos `rotulos_extras` do botão canônico não casa
    em lugar nenhum: o lead responde ao template aprovado e o clique dele cai na
    regra de texto livre, gastando o nudge em vez de virar intenção.
    """
    for trilha, botoes in flows.BOTOES_POR_TRILHA.items():
        for b in botoes:
            casado = engine._casar_nivel1(Clique(b.titulo, b.titulo))
            assert casado is not None, f"{trilha}/{b.titulo!r} não casa em botão nenhum"
            assert casado.id == b.id, f"{trilha}/{b.titulo!r} casou em {casado.id}"


def test_todo_botao_de_trilha_tem_id_conhecido_pelo_motor():
    """O reoferecimento sai como interativa com o ID no payload, não o rótulo.

    Um id exibido numa trilha e ausente de TODOS_BOTOES_NIVEL1 volta como clique
    órfão: o lead toca no botão que a gente mesmo desenhou e o motor não o reconhece.
    """
    conhecidos = {b.id for b in flows.TODOS_BOTOES_NIVEL1}
    for trilha, botoes in flows.BOTOES_POR_TRILHA.items():
        for b in botoes:
            assert b.id in conhecidos, f"{trilha}/{b.id} não existe em TODOS_BOTOES_NIVEL1"


def test_contrato_de_rotulos_do_template_espelha_os_botoes_da_trilha():
    """ROTULOS_TEMPLATE_POR_TRILHA é o que o preflight do disparo compara com o
    template aprovado na Meta (risco 6 da spec: rótulo divergente ⇒ 400 no start).

    Se ele parar de espelhar os botões da trilha, o preflight passa a aprovar um
    template cujos cliques o motor não entende — e o disparo sai assim mesmo.
    """
    assert set(flows.ROTULOS_TEMPLATE_POR_TRILHA) == set(flows.BOTOES_POR_TRILHA)
    for trilha, botoes in flows.BOTOES_POR_TRILHA.items():
        assert flows.ROTULOS_TEMPLATE_POR_TRILHA[trilha] == tuple(b.titulo for b in botoes)


def test_rotulos_do_template_cabem_no_limite_de_template():
    """A Meta permite 25 chars no botão de template e 20 na interativa. Os nossos
    cabem nos dois de propósito, para que o mesmo texto sirva nas duas superfícies."""
    for trilha, rotulos in flows.ROTULOS_TEMPLATE_POR_TRILHA.items():
        for rotulo in rotulos:
            assert len(rotulo) <= 25, f"{trilha}/{rotulo!r}: > 25 chars no template"


def test_nenhum_rotulo_aceito_e_ambiguo():
    """Dois botões que aceitam o mesmo texto tornariam o clique indecidível.

    Usa a MESMA normalização do motor (engine.normalizar, que também tira acento):
    checar só com .lower() deixaria passar dois rótulos que diferem apenas por
    acento — eles colidiriam em _NIVEL1_POR_TITULO sem erro nenhum, e um dos botões
    passaria a rotear para o efeito do outro.

    Nível 1 e nível 2 entram na MESMA varredura de propósito: _casar_nivel1 roda
    antes de _casar_prazo no nó de interesse, então um rótulo repetido entre os dois
    níveis não daria erro — engoliria o clique no nível errado.
    """
    aceitos = [(f"nivel1/{b.id}", t)
               for b in flows.TODOS_BOTOES_NIVEL1 for t in b.titulos_aceitos]
    aceitos += [(f"prazo/{p.id}", p.titulo) for p in flows.PRAZOS]

    vistos: dict[str, str] = {}
    for dono, titulo in aceitos:
        chave = engine.normalizar(titulo)
        assert chave not in vistos, f"{titulo!r} já é aceito por {vistos[chave]}"
        vistos[chave] = dono


def test_ids_de_botao_sao_unicos_entre_os_dois_niveis():
    """O motor indexa cliques por id em dois dicts achatados (_NIVEL1_POR_ID e
    _PRAZO_POR_ID) e consulta o de nível 1 primeiro.

    Uma colisão não daria erro: o dict comprehension sobrescreve em silêncio e o
    clique passaria a cair no efeito errado. A unicidade dentro de cada menu
    (test_limites_da_meta_nos_botoes) não cobre isso — o mesmo id aparece de
    propósito em trilhas diferentes.
    """
    nivel1 = [b.id for b in flows.TODOS_BOTOES_NIVEL1]
    prazos = [p.id for p in flows.PRAZOS]
    assert len(nivel1) == len(set(nivel1)), f"ids repetidos no nível 1: {nivel1}"
    assert len(prazos) == len(set(prazos)), f"ids repetidos no nível 2: {prazos}"
    assert not set(nivel1) & set(prazos), "id compartilhado entre os dois níveis"


def test_todo_prazo_tem_tag_e_dias():
    """Dias, não meses: o intervalo médio entre compras da coorte é 78-122 dias."""
    for prazo in flows.PRAZOS:
        assert prazo.dias > 0
        assert prazo.tag.startswith("Recuperação: ")
        assert prazo.rotulo_humano
        assert str(prazo.dias) in prazo.titulo, "o rótulo tem que dizer o mesmo prazo da tag"


def test_todo_no_que_reoferece_botoes_tem_corpo_de_nudge():
    """O reoferecimento lê o corpo pelo nó (CORPO_NUDGE_POR_NO[no]) e os botões pela
    trilha; qualquer buraco nos dois mapas seria KeyError no meio do turno do lead."""
    nao_terminais = {flows.NO_INTERESSE, flows.NO_PRAZO}
    assert set(flows.CORPO_NUDGE_POR_NO) == nao_terminais
    for no in nao_terminais:
        for trilha in flows.BOTOES_POR_TRILHA:
            assert engine._botoes_do_no(no, trilha)


def test_trilha_do_estado_nunca_escapa_do_mapa_de_botoes():
    """`trilha` vem de um jsonb: pode ser qualquer coisa, inclusive de outra campanha.

    _botoes_do_no indexa BOTOES_POR_TRILHA direto, então um valor estranho viraria
    KeyError no turno — e o lead ficaria sem resposta nenhuma.
    """
    assert flows.TRILHA_PADRAO in flows.BOTOES_POR_TRILHA
    for lixo in (None, {}, {"trilha": None}, {"trilha": "campanha_de_natal"},
                 {"trilha": 7}, [], "aguardando_interesse"):
        assert engine.trilha_de(lixo) in flows.BOTOES_POR_TRILHA, lixo
    for trilha in flows.BOTOES_POR_TRILHA:
        assert engine.trilha_de({"trilha": trilha}) == trilha


# ── Nível 1 · o clique que decide o projeto ─────────────────────────────────
def test_clique_repor_no_numero_da_valeria_manda_cartao():
    d = engine.decidir(estado(), Clique(flows.ID_REPOR, "Preciso repor"),
                       canal_do_vendedor=False, contexto=CTX)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.mensagem.enviar_cartao_vendedor is True
    assert d.mensagem.botoes == ()
    assert d.efeitos.handoff is True
    assert d.efeitos.tags == (flows.TAG_QUENTE,)
    assert d.efeitos.optout is False


def test_clique_repor_no_numero_do_vendedor_nao_manda_cartao():
    """O bot roda no número do próprio João (D2 da spec). Mandar o cartão de contato
    dele para o número dele é exatamente o degrau que custa 26% dos leads."""
    d = engine.decidir(estado(), Clique(flows.ID_REPOR, "Preciso repor"),
                       canal_do_vendedor=True, contexto=CTX)
    assert d.mensagem.enviar_cartao_vendedor is False
    assert d.efeitos.handoff is True


def test_entrega_quente_com_produto_e_preco():
    """Quem recebe algo concreto chega ao vendedor em 73-75%, contra 56,5% de quem
    não recebe nada — e 69,5% dos leads da base nunca viram preço nem foto."""
    d = engine.decidir(estado(), Clique(flows.ID_REPOR, "Preciso repor"),
                       canal_do_vendedor=True, contexto=CTX)
    corpo = d.mensagem.corpo
    assert "Ana" in corpo and "Microlote 1kg" in corpo and "R$ 49,90" in corpo
    assert "{" not in corpo
    assert "?" not in corpo, (
        "ZERO perguntas depois do clique quente: a autópsia dos 14 leads mortos mostrou "
        "que abrir com ack + pergunta dobra a chance de matar a thread (39% vs 18%)"
    )


def test_entrega_quente_sem_sku_ativo_reconhece_o_item_e_nao_cota():
    """141 leads da coorte compravam outras marcas, 123 cápsula e 47 drip — nada
    disso está nos 32 SKUs que o agente conhece. Cotar de memória foi o que perdeu as
    500 unidades da Ritz (drip cotado a R$ 27,70 quando o real era R$ 2,49/sachê)."""
    d = engine.decidir(estado(), Clique(flows.ID_REPOR, "Preciso repor"),
                       canal_do_vendedor=True,
                       contexto=Contexto(primeiro_nome="Ana", produto="cápsula compatível"))
    corpo = d.mensagem.corpo
    assert "cápsula compatível" in corpo, "o item é reconhecido pelo nome"
    assert "R$" not in corpo and "a unidade" not in corpo, "mas o preço NÃO é inventado"
    assert "{" not in corpo
    assert d.efeitos.handoff is True


def test_entrega_quente_sem_produto_no_cadastro():
    """Terceira forma: cadastro sem histórico de item. Nem produto, nem preço."""
    d = engine.decidir(estado(), Clique(flows.ID_REPOR, "Preciso repor"),
                       canal_do_vendedor=True, contexto=Contexto(primeiro_nome="Ana"))
    corpo = d.mensagem.corpo
    assert corpo == flows.render(flows.MSG_QUENTE_SEM_PRODUTO, {"vocativo": ", Ana"})
    assert "você levava" not in corpo
    assert "{" not in corpo


def test_clique_adiar_abre_o_nivel_2():
    d = engine.decidir(estado(), Clique(flows.ID_ADIAR, "Ainda tenho estoque"),
                       canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_PRAZO
    assert d.mensagem.corpo == flows.CORPO_PRAZO
    assert d.mensagem.botoes == flows.BOTOES_PRAZO
    assert d.efeitos.tags == ()
    assert d.efeitos.handoff is False
    assert d.efeitos.optout is False, (
        "adiamento NUNCA é recusa: 41% de quem clicava 'Nao tenho interesse' continuou "
        "conversando e 2 compraram depois"
    )


def test_clique_optout_faz_optout():
    d = engine.decidir(estado(), Clique(flows.ID_OPTOUT, "Parar mensagens"),
                       canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.mensagem.corpo == flows.MSG_OPTOUT
    assert d.mensagem.botoes == ()
    assert d.efeitos.optout is True
    assert d.efeitos.tags == (flows.TAG_RECUSOU,)


def test_clique_manter_registra_optin_sem_vender():
    """Trilha C (665 leads de 36m+) NÃO vende (Q7 da spec): "Manter cadastro" é
    opt-in prospectivo registrado, e a abordagem comercial fica para uma SEGUNDA
    campanha, com consentimento na mão. Encerrar aqui é o desfecho correto."""
    d = engine.decidir(estado(trilha=flows.TRILHA_CADASTRO),
                       Clique(flows.ID_MANTER, "Manter cadastro"),
                       canal_do_vendedor=True, contexto=CTX)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.efeitos.tags == (flows.TAG_CADASTRO_MANTIDO,)
    assert d.efeitos.handoff is False, "higienização não gera lead qualificado"
    assert d.efeitos.optout is False
    assert "Ana" in d.mensagem.corpo
    assert d.mensagem.botoes == ()
    assert d.trilha_inferida == flows.TRILHA_CADASTRO


def test_clique_atualizar_entrega_ao_vendedor():
    """"Atualizar dados" é a única porta comercial da trilha C — e ela vai para o
    João, não para um formulário."""
    d = engine.decidir(estado(trilha=flows.TRILHA_CADASTRO),
                       Clique(flows.ID_ATUALIZAR, "Atualizar dados"),
                       canal_do_vendedor=True, contexto=CTX)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.mensagem.corpo == flows.MSG_ATUALIZAR_DADOS
    assert d.efeitos.handoff is True
    assert d.efeitos.tags == (flows.TAG_HUMANO,)
    assert d.efeitos.optout is False
    assert d.trilha_inferida == flows.TRILHA_CADASTRO


# ── Casamento do clique ─────────────────────────────────────────────────────
def test_clique_casa_pelo_rotulo_da_outra_trilha():
    """O mesmo id atendido por rótulos diferentes: quem responde ao template da
    trilha A manda "Retomar o pedido" e quem responde ao da B manda "Preciso repor".
    Os dois são o botão `repor`. Sem os `rotulos_extras`, uma trilha inteira cairia
    no vazio — o clique viraria texto livre."""
    d = engine.decidir(estado(), Clique("Retomar o pedido", "Retomar o pedido"),
                       canal_do_vendedor=True, contexto=CTX)
    assert d.efeitos.handoff is True
    assert d.efeitos.tags == (flows.TAG_QUENTE,)

    d = engine.decidir(estado(), Clique("Quero outro item", "Quero outro item"),
                       canal_do_vendedor=True, contexto=CTX)
    assert d.proximo_no == flows.NO_PRAZO


def test_clique_do_nudge_casa_por_id():
    """O reoferecimento sai como interativa com ids nossos — tem que casar igual."""
    d = engine.decidir(estado(nudged=True), Clique(flows.ID_OPTOUT, "Parar mensagens"),
                       canal_do_vendedor=False)
    assert d.efeitos.optout is True


def test_casamento_de_titulo_ignora_caixa_e_acento():
    """Prova de produção: há 64 cliques gravados em "Nao tenho interesse" e ZERO em
    "Não tenho interesse" — o quick reply de template devolve o TEXTO do botão, e o
    teclado do lead (ou o próprio WhatsApp) pode devolvê-lo sem acento.

    Nenhum rótulo do menu novo tem acento, mas o casamento é o mesmo código; o
    próximo relabel pode ter, e é tarde demais para descobrir isso no disparo.
    """
    d = engine.decidir(estado(), Clique("PRECISO REPÓR", "PRECISO REPÓR"),
                       canal_do_vendedor=True, contexto=CTX)
    assert d.efeitos.handoff is True

    d = engine.decidir(estado(), Clique("  parar mensagens  ", ""), canal_do_vendedor=False)
    assert d.efeitos.optout is True


# ── Payload custom do disparo ───────────────────────────────────────────────
# `<flow>|<botao_id>|<trilha>|t<toque>`, montado em broadcast/worker.py:322 e lido
# em engine._desmontar_payload. Ele existe para o casamento NÃO depender do texto do
# rótulo: até 09/09/2026 o payload era emitido e nunca lido, e bastava a Meta
# reaprovar o botão com uma vírgula a mais ("Preciso repor!") para o clique do lead
# virar texto livre e gastar o único nudge que ele tem direito.
def test_desmontar_payload_le_botao_e_trilha_da_versao_corrente():
    assert engine._desmontar_payload("recuperacao_v1|repor|pedido|t1") == ("repor", "pedido")
    assert engine._desmontar_payload("recuperacao_v1|optout|cadastro|t2") == ("optout",
                                                                             "cadastro")
    # O toque é opcional na leitura: quem lê só precisa de versão, botão e trilha.
    assert engine._desmontar_payload("recuperacao_v1|adiar|estoque") == ("adiar", "estoque")


def test_desmontar_payload_recusa_o_que_nao_e_payload_nosso():
    """Nada além do formato exato vira casamento — o fallback por id/rótulo assume.

    `reativacao_v1` é o fluxo APOSENTADO em 09/09/2026: um payload dele significa que
    o lead está com o menu velho na tela, e casá-lo com os efeitos do menu novo seria
    responder à pergunta errada. Recusar aqui empurra o clique para o caminho de
    estado incompatível, que devolve ao João.
    """
    for lixo in (None, "", "repor", "Preciso repor", "recuperacao_v1",
                 "recuperacao_v1|repor", "reativacao_v1|repor|estoque|t1",
                 "recuperacao_v0|repor|estoque|t1", "|repor|estoque|t1"):
        assert engine._desmontar_payload(lixo) == (None, None), lixo
    # Versão certa, mas partes inválidas: cada campo é descartado por conta própria.
    assert engine._desmontar_payload("recuperacao_v1||pedido|t1") == (None, "pedido")
    assert engine._desmontar_payload(
        "recuperacao_v1|repor|campanha_de_natal|t1") == ("repor", None)


def test_payload_custom_casa_mesmo_com_o_rotulo_editado():
    """O caso que o payload existe para resolver: a Meta reaprovou o template com o
    rótulo mexido, e o texto que volta no clique não casa em botão nenhum.

    Com o payload lido, o clique continua sendo `repor` — e a trilha vem do payload,
    não do texto, então o nudge seguinte ainda ecoa o template certo.
    """
    d = engine.decidir(estado(), Clique("recuperacao_v1|repor|pedido|t1", "Rotulo Qualquer!!"),
                       canal_do_vendedor=False, contexto=CTX)
    assert d.efeitos.handoff is True
    assert d.efeitos.tags == (flows.TAG_QUENTE,)
    assert d.trilha_inferida == flows.TRILHA_PEDIDO
    assert d.marcar_nudge is False

    d = engine.decidir(estado(), Clique("recuperacao_v1|optout|cadastro|t2",
                                        "Rotulo Qualquer!!"), canal_do_vendedor=False)
    assert d.efeitos.optout is True
    assert d.mensagem.corpo == flows.MSG_OPTOUT


def test_payload_custom_tem_precedencia_sobre_o_rotulo():
    """Payload e rótulo em desacordo: vence o payload, nos dois campos.

    Em produção os dois vêm do mesmo botão e concordam; o desacordo só aparece quando
    o rótulo foi editado ou quando o WhatsApp devolve o título de outra trilha. Nesse
    empate o payload é a fonte confiável — ele foi montado por nós, no disparo, com a
    trilha que o lead de fato recebeu.
    """
    # Botão: payload diz `adiar`, título diz "Preciso repor" (que casaria em `repor`).
    d = engine.decidir(estado(), Clique("recuperacao_v1|adiar|pedido|t1", "Preciso repor"),
                       canal_do_vendedor=False, contexto=CTX)
    assert d.proximo_no == flows.NO_PRAZO
    assert d.efeitos.handoff is False

    # Trilha: payload diz `cadastro`, título "Retomar o pedido" inferiria `pedido`.
    d = engine.decidir(estado(), Clique("recuperacao_v1|repor|cadastro|t1",
                                        "Retomar o pedido"),
                       canal_do_vendedor=False, contexto=CTX)
    assert d.trilha_inferida == flows.TRILHA_CADASTRO


def test_payload_custom_de_outra_versao_nao_casa_e_cai_no_nudge():
    """`reativacao_v1` é o fluxo aposentado: o payload dele não pode acionar efeito.

    Sem título reconhecível para o fallback, o clique cai na regra de texto livre —
    reoferecimento uma vez, entrega ao João na segunda. Nenhum efeito destrutivo, que
    é o desfecho certo para um menu que não é mais o nosso.
    """
    velho = Clique("reativacao_v1|repor|estoque|t1", "Rotulo Qualquer!!")
    d = engine.decidir(estado(), velho, canal_do_vendedor=False, contexto=CTX)
    assert d.marcar_nudge is True
    assert d.mensagem.botoes == flows.BOTOES_POR_TRILHA[flows.TRILHA_PADRAO]
    assert d.efeitos == engine.Efeitos()
    assert d.trilha_inferida is None

    d = engine.decidir(estado(nudged=True), velho, canal_do_vendedor=False, contexto=CTX)
    assert d is engine._ENTREGAR_AO_HUMANO


def test_payload_sem_separador_continua_casando_por_id_e_por_rotulo():
    """O fallback antigo é preservado de propósito: nem todo clique traz payload
    custom.

    A interativa do reoferecimento sai com o id cru (`optout`), e o quick reply de
    template devolve o TEXTO do botão. Os dois têm que continuar casando — o payload
    custom só chega no clique do PRIMEIRO toque, o do template do disparo.
    """
    for b in flows.TODOS_BOTOES_NIVEL1:
        assert engine._casar_nivel1(Clique(b.id, "")).id == b.id, b.id
        for titulo in b.titulos_aceitos:
            assert engine._casar_nivel1(Clique(titulo, titulo)).id == b.id, titulo
            assert engine._casar_nivel1(Clique("", titulo)).id == b.id, titulo


def test_payload_custom_tambem_casa_no_nivel_2():
    """O menu de prazo é interativo hoje, mas se um dia virar template ele sai com o
    mesmo payload — e o casamento tem que ser o mesmo, senão o nível 2 é o único
    lugar do fluxo que quebra com um rótulo reaprovado."""
    assert engine._casar_prazo(Clique("recuperacao_v1|snooze60|estoque|t1", "")).dias == 60
    d = engine.decidir(estado(flows.NO_PRAZO),
                       Clique("recuperacao_v1|snooze90|pedido|t1", "Rotulo Qualquer!!"),
                       canal_do_vendedor=False)
    assert d.efeitos.recontato_dias == 90
    assert d.efeitos.tags == ("Recuperação: 90 dias",)


# ── Inferência de trilha ────────────────────────────────────────────────────
def test_clique_revela_a_trilha_do_template_que_o_lead_recebeu():
    """O disparo pode não ter semeado a trilha no estado; o clique conta qual
    template o lead tem na tela, e é ele que decide os rótulos do nudge seguinte."""
    casos = {
        "Retomar o pedido": flows.TRILHA_PEDIDO,
        "Quero outro item": flows.TRILHA_PEDIDO,
        "Preciso repor": flows.TRILHA_ESTOQUE,
        "Ainda tenho estoque": flows.TRILHA_ESTOQUE,
        "Manter cadastro": flows.TRILHA_CADASTRO,
        "Atualizar dados": flows.TRILHA_CADASTRO,
    }
    for rotulo, esperada in casos.items():
        d = engine.decidir(estado(), Clique(rotulo, rotulo),
                           canal_do_vendedor=True, contexto=CTX)
        assert d.trilha_inferida == esperada, rotulo


def test_parar_mensagens_nao_infere_trilha():
    """"Parar mensagens" é o único rótulo comum às três trilhas. Inferir qualquer uma
    a partir dele gravaria trilha errada no estado — e o runner grava a inferência
    antes de olhar o desfecho."""
    d = engine.decidir(estado(), Clique("Parar mensagens", "Parar mensagens"),
                       canal_do_vendedor=False)
    assert d.trilha_inferida is None
    assert d.efeitos.optout is True


def test_rotulo_extra_nao_sequestra_a_trilha_do_dono():
    """"Retomar o pedido" é `rotulos_extras` de BTN_REPOR (trilha B) e título de
    BTN_REPOR_PEDIDO (trilha A).

    Se os extras entrassem em _TRILHA_POR_TITULO, a última trilha iterada venceria e
    o clique da trilha A passaria a inferir `estoque`: o lead do pedido não faturado
    receberia de volta o nudge com "Preciso repor" / "Ainda tenho estoque", que não é
    o menu do template dele.
    """
    d = engine.decidir(estado(), Clique("Retomar o pedido", "Retomar o pedido"),
                       canal_do_vendedor=True, contexto=CTX)
    assert d.trilha_inferida == flows.TRILHA_PEDIDO


def test_inferencia_vem_do_rotulo_e_nao_do_id():
    """O id é comum às trilhas (`repor` atende A e B); só o rótulo distingue.
    Um clique da interativa traz id no payload e rótulo no título — a inferência tem
    que sair do título, e sumir de vez quando não há título."""
    d = engine.decidir(estado(), Clique(flows.ID_REPOR, "Retomar o pedido"),
                       canal_do_vendedor=True, contexto=CTX)
    assert d.trilha_inferida == flows.TRILHA_PEDIDO

    d = engine.decidir(estado(), Clique(flows.ID_REPOR, ""),
                       canal_do_vendedor=True, contexto=CTX)
    assert d.trilha_inferida is None


# ── Nível 2 ─────────────────────────────────────────────────────────────────
def test_cada_prazo_grava_tag_e_dias():
    for prazo in flows.PRAZOS:
        d = engine.decidir(estado(flows.NO_PRAZO), Clique(prazo.id, prazo.titulo),
                           canal_do_vendedor=False)
        assert d.proximo_no == flows.NO_ENCERRADO
        assert d.efeitos.tags == (prazo.tag,)
        assert d.efeitos.recontato_dias == prazo.dias
        assert prazo.rotulo_humano in d.mensagem.corpo
        assert "{" not in d.mensagem.corpo
        assert d.mensagem.botoes == ()
        assert d.efeitos.optout is False, "pedir tempo não é pedir para sair"
        assert d.efeitos.handoff is False


def test_prazo_casa_pelo_rotulo_alem_do_id():
    """O menu de prazo também pode chegar como texto do botão, se um dia ele virar
    template — o mesmo casamento duplo do nível 1."""
    d = engine.decidir(estado(flows.NO_PRAZO), Clique("Em 60 dias", "Em 60 dias"),
                       canal_do_vendedor=False)
    assert d.efeitos.recontato_dias == 60


# ── Texto livre e reoferecimento ────────────────────────────────────────────
def test_texto_livre_reoferece_os_botoes_uma_vez():
    d = engine.decidir(estado(), Texto("oi, quanto custa?"), canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_INTERESSE
    assert d.mensagem.botoes == flows.BOTOES_POR_TRILHA[flows.TRILHA_PADRAO]
    assert d.mensagem.corpo == flows.CORPO_NUDGE
    assert d.marcar_nudge is True
    assert d.efeitos.tags == ()


def test_nudge_usa_os_rotulos_da_trilha_do_lead():
    """O reoferecimento tem que ecoar o template que o lead recebeu: quem viu
    "Manter cadastro" e digitou texto não pode receber de volta "Preciso repor" — a
    trilha C não vende, e trocar o menu no meio da conversa é oferta não autorizada."""
    for trilha, botoes in flows.BOTOES_POR_TRILHA.items():
        d = engine.decidir(estado(trilha=trilha), Texto("como assim?"),
                           canal_do_vendedor=False)
        assert d.mensagem.botoes == botoes, trilha
        assert d.marcar_nudge is True


def test_trilha_desconhecida_no_estado_cai_no_padrao():
    d = engine.decidir(estado(trilha="campanha_de_natal"), Texto("oi"),
                       canal_do_vendedor=False)
    assert d.mensagem.botoes == flows.BOTOES_POR_TRILHA[flows.TRILHA_PADRAO]


def test_texto_livre_no_nivel_2_reoferece_os_botoes_de_prazo():
    d = engine.decidir(estado(flows.NO_PRAZO), Texto("sei lá"), canal_do_vendedor=False)
    assert d.mensagem.botoes == flows.BOTOES_PRAZO
    assert flows.CORPO_PRAZO in d.mensagem.corpo, (
        "no nível 2 a pergunta é NOSSA (não veio no template), então o nudge tem que "
        "repeti-la inteira — só o convite deixaria o lead sem saber o que responder"
    )
    assert d.marcar_nudge is True


def test_nudge_do_nivel_2_independe_da_trilha():
    """O menu de prazo é nosso, não do template: as três trilhas veem o mesmo."""
    for trilha in flows.BOTOES_POR_TRILHA:
        d = engine.decidir(estado(flows.NO_PRAZO, trilha=trilha), Texto("hm"),
                           canal_do_vendedor=False)
        assert d.mensagem.botoes == flows.BOTOES_PRAZO, trilha


def test_segundo_texto_livre_entrega_ao_humano():
    """Fallback ≤ 2, sempre: duas incompreensões seguidas devolvem ao João."""
    d = engine.decidir(estado(nudged=True), Texto("me liga"), canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.mensagem is None
    assert d.efeitos.tags == (flows.TAG_HUMANO,)


# ── Camada 2: classes do classificador ──────────────────────────────────────
def test_classe_sair_faz_optout_em_qualquer_no():
    """Hoje há 52 pessoas em produção que clicaram opt-out e seguem com
    `opt_out = false`, elegíveis para a próxima campanha (risco 1 da spec). É essa
    dívida que a classe SAIR existe para não repetir — inclusive no nó de prazo,
    onde o menu na tela não tem botão de saída."""
    for no in (flows.NO_INTERESSE, flows.NO_PRAZO):
        d = engine.decidir(estado(no), Classificado(engine.CLASSE_SAIR),
                           canal_do_vendedor=False)
        assert d.efeitos.optout is True, no
        assert d.proximo_no == flows.NO_ENCERRADO, no
        assert d.mensagem.corpo == flows.MSG_OPTOUT, no
        assert d.efeitos.tags == (flows.TAG_RECUSOU,), no


def test_classe_quente_produz_a_mesma_decisao_do_botao_repor():
    """A classe não gera texto novo: ela cai na MESMA Decisao do botão equivalente.
    Toda mensagem continua vindo de flows.py — o classificador nunca escreve para o
    cliente."""
    por_botao = engine.decidir(estado(), Clique(flows.ID_REPOR, ""),
                               canal_do_vendedor=False, contexto=CTX)
    por_classe = engine.decidir(estado(), Classificado(engine.CLASSE_QUENTE),
                                canal_do_vendedor=False, contexto=CTX)
    assert por_classe == por_botao


def test_classe_adiar_abre_o_nivel_2():
    d = engine.decidir(estado(), Classificado(engine.CLASSE_ADIAR), canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_PRAZO
    assert d.mensagem.botoes == flows.BOTOES_PRAZO
    assert d.efeitos.optout is False, (
        "empate entre SAIR e ADIAR resolve em ADIAR: Rafael Monteiro clicou opt-out e "
        "comprou R$ 2.490 depois"
    )


def test_classe_adiar_no_no_de_prazo_nao_repete_a_pergunta():
    """No nó de prazo o lead JÁ está sendo perguntado; reabrir o nível 2 seria loop.
    Cai na regra de nudge, que ali já é a própria pergunta de prazo."""
    d = engine.decidir(estado(flows.NO_PRAZO), Classificado(engine.CLASSE_ADIAR),
                       canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_PRAZO
    assert d.marcar_nudge is True
    assert d.mensagem.botoes == flows.BOTOES_PRAZO


def test_classe_adiar_no_no_de_prazo_ja_nudgeado_entrega_ao_humano():
    d = engine.decidir(estado(flows.NO_PRAZO, nudged=True),
                       Classificado(engine.CLASSE_ADIAR), canal_do_vendedor=False)
    assert d is engine._ENTREGAR_AO_HUMANO


def test_classe_engano_aborta_o_script_comercial():
    """O template `rabubens` ("seu pedido já está sendo preparado") teve 44,2% de
    negação/confusão em 104 respostas, incluindo pânico de cliente legítimo. Quem
    contesta o pretexto não pode receber oferta nenhuma — é o caminho mais curto para
    um report na Meta."""
    d = engine.decidir(estado(), Classificado(engine.CLASSE_ENGANO),
                       canal_do_vendedor=False, contexto=CTX)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.mensagem.corpo == flows.MSG_ENGANO
    assert d.mensagem.botoes == (flows.BTN_OPTOUT,)
    assert flows.BTN_OPTOUT.titulo in d.mensagem.corpo, (
        "o texto convida a tocar no botão: se o rótulo mudar e o texto não, o lead "
        "procura um botão que não existe"
    )
    assert d.efeitos.pretexto_contestado is True
    assert d.efeitos.silenciar_ia is True
    assert d.efeitos.tags == (flows.TAG_ENGANO,)
    assert d.efeitos.handoff is False
    assert d.efeitos.optout is False, (
        "contestar o pretexto não é pedir para sair; o opt-out fica na mão do lead"
    )


def test_classe_pergunta_vai_para_o_joao_sem_carimbar_quente():
    """O bot não responde preço nem frete — há três versões incompatíveis de política
    de frete em circulação (Q2 da spec). Pergunta comercial de verdade é do João."""
    d = engine.decidir(estado(), Classificado(engine.CLASSE_PERGUNTA),
                       canal_do_vendedor=False)
    assert d is engine._ENTREGAR_AO_HUMANO
    assert d.efeitos.silenciar_ia is True
    assert d.efeitos.handoff is False
    assert d.efeitos.tags == (flows.TAG_HUMANO,)


def test_classe_ruido_reoferece_uma_vez_e_depois_entrega():
    d = engine.decidir(estado(), Classificado(engine.CLASSE_RUIDO), canal_do_vendedor=False)
    assert d.marcar_nudge is True
    assert d.mensagem.botoes == flows.BOTOES_POR_TRILHA[flows.TRILHA_PADRAO]

    d = engine.decidir(estado(nudged=True), Classificado(engine.CLASSE_RUIDO),
                       canal_do_vendedor=False)
    assert d is engine._ENTREGAR_AO_HUMANO


def test_classe_desconhecida_nao_faz_nada_destrutivo():
    """Quem produz a classe é um LLM: ele pode devolver "INTERESSADO", vazio, ou a
    palavra certa em caixa errada. Nada disso pode virar opt-out — no máximo nudge.

    O casamento é exato de propósito (`classe == CLASSE_SAIR`), então normalizar a
    saída do modelo é responsabilidade de quem chama o classificador.
    """
    for lixo in ("INTERESSADO", "", "sair", "SAIR ", "None", "QUENTE?"):
        d = engine.decidir(estado(), Classificado(lixo), canal_do_vendedor=False)
        assert d.efeitos.optout is False, lixo
        assert d.efeitos.handoff is False, lixo
        assert d.marcar_nudge is True, lixo


def test_matriz_classe_x_no_nunca_produz_efeito_nao_pedido():
    """Varredura completa: nenhuma classe inventa opt-out ou handoff fora do seu par,
    em nenhum nó, com ou sem nudge gasto — e nenhuma combinação fica sem saída.

    É o teste que sobrevive ao próximo relabel: uma classe nova sem tratamento
    aparece aqui como efeito destrutivo, como silêncio, ou como beco sem saída.
    """
    permite_optout = {engine.CLASSE_SAIR}
    permite_handoff = {engine.CLASSE_QUENTE}
    for classe in engine.CLASSES:
        for no in (flows.NO_INTERESSE, flows.NO_PRAZO):
            for nudged in (False, True):
                caso = (classe, no, nudged)
                d = engine.decidir(estado(no, nudged=nudged), Classificado(classe),
                                   canal_do_vendedor=False, contexto=CTX)
                assert d.efeitos.optout is (classe in permite_optout), caso
                assert d.efeitos.handoff is (classe in permite_handoff), caso
                # Nenhum nó existe sem saída para humano ou para opt-out.
                assert d.mensagem is not None or d.efeitos.silenciar_ia, caso


# ── Cliques fora do nó ──────────────────────────────────────────────────────
def test_clique_de_nivel_2_no_no_de_interesse_e_ignorado_sem_gastar_nudge():
    """Tocar num botão que já foi respondido (o lead rolou a conversa e clicou de
    novo) não é recusa a usar botões — e reprocessar o efeito duplicaria CRM."""
    d = engine.decidir(estado(), Clique("snooze90", "Em 90 dias"), canal_do_vendedor=False)
    assert d.ignorar is True
    assert d.mensagem is None
    assert d.efeitos == engine.Efeitos()
    assert d.proximo_no == flows.NO_INTERESSE
    assert d.marcar_nudge is False


def test_clique_de_nivel_1_no_no_de_prazo_e_ignorado_sem_gastar_nudge():
    d = engine.decidir(estado(flows.NO_PRAZO), Clique(flows.ID_ADIAR, "Ainda tenho estoque"),
                       canal_do_vendedor=False)
    assert d.ignorar is True
    assert d.mensagem is None
    assert d.efeitos == engine.Efeitos()
    assert d.proximo_no == flows.NO_PRAZO
    assert d.marcar_nudge is False


def test_optout_clicado_no_no_de_prazo_e_honrado():
    """O botão de saída do template continua clicável depois que o lead avançou.

    Cenário real: o lead toca "Ainda tenho estoque" (vai para AGUARDANDO_PRAZO),
    recebe 30/60/90 — que não tem botão de saída — se irrita, rola a conversa de
    volta até o template e toca "Parar mensagens". O WhatsApp não desativa os botões
    de um template já respondido, então esse clique chega normalmente.

    Até 09/09/2026 ele era ENGOLIDO: `_casar_prazo` não casava, `_casar_nivel1`
    casava, e o ramo de "clique de outro nó" (hoje engine.py:433) devolvia
    ignorar=True. O lead seguia com `opt_out = false` e elegível para a próxima onda
    — exatamente a dívida dos 52 casos que o risco 1 da spec manda não repetir.
    Corrigido em engine.py:356-359, resolvendo o opt-out no TOPO de decidir(), antes
    de qualquer leitura de nó. Este teste era um xfail; virou asserção positiva.
    """
    d = engine.decidir(estado(flows.NO_PRAZO), Clique(flows.ID_OPTOUT, "Parar mensagens"),
                       canal_do_vendedor=False)
    assert d.efeitos.optout is True
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.ignorar is False
    assert d.mensagem.corpo == flows.MSG_OPTOUT
    assert d.mensagem.botoes == ()
    assert d.efeitos.tags == (flows.TAG_RECUSOU,)


# Estados que o opt-out tem que atravessar. Cobrem os três nós E as quatro formas
# de flow_state que existem no jsonb de produção — ausente, vazio, corrompido
# (array/escalar) e semeado por uma versão antiga do fluxo.
_ESTADOS_QUE_O_OPTOUT_ATRAVESSA: dict[str, object] = {
    "no de interesse": {"flow": flows.FLOW_ID, "node": flows.NO_INTERESSE},
    "no de interesse ja nudgeado": {"flow": flows.FLOW_ID, "node": flows.NO_INTERESSE,
                                    "nudged": True},
    "no de prazo": {"flow": flows.FLOW_ID, "node": flows.NO_PRAZO},
    "encerrado (pos-handoff)": {"flow": flows.FLOW_ID, "node": flows.NO_ENCERRADO},
    "estado ausente (None)": None,
    "estado vazio ({})": {},
    "jsonb array ([])": [],
    "jsonb string": "aguardando_interesse",
    "flow da versao antiga": {"flow": "reativacao_v1", "node": flows.NO_PRAZO},
    "flow sem versao": {"node": 42},
    "no que nao existe": {"flow": flows.FLOW_ID, "node": "aguardando_orcamento"},
}


def test_optout_vence_tudo_qualquer_no_qualquer_estado():
    """Invariante novo de 09/09/2026 (engine.py:346-359): o opt-out é decidido ANTES
    do nó, da versão do fluxo e da validação do estado.

    Cada linha desta matriz era um jeito de PERDER um opt-out, e todos terminavam no
    mesmo lugar: `opt_out = false`, lead elegível ao toque D+4 e à próxima campanha.
      - nó de prazo e encerrado caíam no ramo de "clique de outro nó"/`ignorar`;
      - `[]`, string e `flow` de outra versão caíam em _ENTREGAR_AO_HUMANO, que
        silencia a IA mas NÃO desliga o lead da base.
    Reaplicar opt-out é idempotente e barato; perdê-lo é o risco #1 da spec (LGPD +
    queda de qualidade do número). As quatro formas de clique cobrem as superfícies
    reais: interativa (id no payload), template (texto no payload), payload vazio com
    só o título, e o payload custom do disparo (broadcast/worker.py:322).
    """
    cliques = (
        Clique(flows.ID_OPTOUT, "Parar mensagens"),
        Clique("Parar mensagens", "Parar mensagens"),
        Clique("", "PARAR MENSAGENS"),
        Clique("recuperacao_v1|optout|cadastro|t2", "Rotulo Qualquer!!"),
    )
    for nome, est in _ESTADOS_QUE_O_OPTOUT_ATRAVESSA.items():
        for clique in cliques:
            d = engine.decidir(est, clique, canal_do_vendedor=False, contexto=CTX)
            caso = (nome, clique.payload)
            assert d.efeitos.optout is True, caso
            assert d.efeitos.tags == (flows.TAG_RECUSOU,), caso
            assert d.proximo_no == flows.NO_ENCERRADO, caso
            assert d.ignorar is False, caso
            assert d.marcar_nudge is False, caso
            assert d.mensagem is not None and d.mensagem.corpo == flows.MSG_OPTOUT, caso
            assert d.mensagem.botoes == (), caso
            assert d.efeitos.handoff is False, caso


def test_classe_sair_vence_tudo_igual_ao_botao():
    """A classe SAIR atravessa a MESMA matriz que o botão.

    O texto livre "me tira dessa lista" é tão inequívoco quanto o toque no botão, e o
    lead que digita isso costuma ser justamente o que já não vê botão nenhum na tela
    (nó de prazo) ou cujo estado foi semeado por outra versão. Tratar a classe depois
    da validação de estado devolveria ao humano — silêncio para o bot, mas
    `opt_out = false` no CRM.
    """
    for nome, est in _ESTADOS_QUE_O_OPTOUT_ATRAVESSA.items():
        d = engine.decidir(est, Classificado(engine.CLASSE_SAIR),
                           canal_do_vendedor=False, contexto=CTX)
        assert d.efeitos.optout is True, nome
        assert d.efeitos.tags == (flows.TAG_RECUSOU,), nome
        assert d.proximo_no == flows.NO_ENCERRADO, nome
        assert d.ignorar is False, nome
        assert d.mensagem is not None and d.mensagem.corpo == flows.MSG_OPTOUT, nome


def test_repor_clicado_no_no_de_prazo_faz_handoff():
    """"Ainda tenho estoque" seguido de "Preciso repor" é o lead conferindo o estoque
    e voltando — mudança de ideia PARA CIMA.

    O mesmo ramo de "clique de outro nó" que engolia o opt-out (engine.py:433)
    engolia isto: o lead tocava no botão de compra e recebia silêncio. Custa uma
    venda, não LGPD, mas é a única intenção de compra explícita que o fluxo consegue
    capturar — o clique positivo converteu 35,7% em venda, o melhor sinal do CRM
    inteiro. Corrigido em engine.py:431-432.
    """
    d = engine.decidir(estado(flows.NO_PRAZO), Clique(flows.ID_REPOR, "Preciso repor"),
                       canal_do_vendedor=False, contexto=CTX)
    assert d.efeitos.handoff is True
    assert d.efeitos.tags == (flows.TAG_QUENTE,)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.ignorar is False
    assert d.mensagem.enviar_cartao_vendedor is True
    assert "Microlote 1kg" in d.mensagem.corpo
    assert d.efeitos.optout is False

    # E o rótulo da outra trilha ("Retomar o pedido", trilha A) chega ao mesmo lugar.
    d = engine.decidir(estado(flows.NO_PRAZO), Clique("Retomar o pedido", "Retomar o pedido"),
                       canal_do_vendedor=True, contexto=CTX)
    assert d.efeitos.handoff is True
    assert d.mensagem.enviar_cartao_vendedor is False


def test_adiar_clicado_no_no_de_prazo_continua_ignorado():
    """O contraponto: só `repor` e `optout` escapam do ramo de "clique de outro nó".

    "Ainda tenho estoque" tocado DE NOVO já dentro do nó de prazo é o lead rolando a
    conversa, não uma decisão nova — reabrir o nível 2 devolveria a mesma pergunta
    que já está na tela dele, e gastaria o nudge por isso.
    """
    d = engine.decidir(estado(flows.NO_PRAZO), Clique(flows.ID_ADIAR, "Ainda tenho estoque"),
                       canal_do_vendedor=False)
    assert d.ignorar is True
    assert d.efeitos == engine.Efeitos()
    assert d.marcar_nudge is False


def test_clique_desconhecido_cai_na_regra_de_texto_livre():
    """Botão que não pertence a nenhum nível do fluxo é tratado como texto."""
    d = engine.decidir(estado(), Clique("botao_de_outro_bot", "Sei lá"),
                       canal_do_vendedor=False)
    assert d.ignorar is False
    assert d.mensagem.botoes == flows.BOTOES_POR_TRILHA[flows.TRILHA_PADRAO]


def test_clique_desconhecido_ja_nudgeado_entrega_ao_humano():
    """Botão de fora do fluxo conta como texto livre também na segunda vez."""
    d = engine.decidir(estado(nudged=True), Clique("botao_de_outro_bot", "Sei lá"),
                       canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.efeitos.tags == (flows.TAG_HUMANO,)


# ── Estados terminais e inválidos ───────────────────────────────────────────
def test_no_encerrado_ignora_tudo():
    for evento in (Texto("oi"), Clique(flows.ID_REPOR, "Preciso repor"),
                   Classificado(engine.CLASSE_QUENTE)):
        d = engine.decidir(estado(flows.NO_ENCERRADO), evento,
                           canal_do_vendedor=False, contexto=CTX)
        assert d.ignorar is True, evento
        assert d.mensagem is None, evento
        assert d.efeitos == engine.Efeitos(), evento


def test_flow_de_outra_versao_devolve_ao_humano():
    """Inclui o id do fluxo ANTERIOR ("reativacao_v1"), aposentado em 09/09/2026: uma
    conversa semeada antes do relabel tem o menu velho na tela, e responder a ela com
    o menu novo (ou reiniciá-la do zero) é pior do que entregar ao João."""
    for antigo in ("reativacao_v1", "recuperacao_v0", "", None):
        d = engine.decidir({"flow": antigo, "node": flows.NO_INTERESSE},
                           Texto("oi"), canal_do_vendedor=False)
        assert d.proximo_no == flows.NO_ENCERRADO, antigo
        assert d.mensagem is None, antigo
        assert d.efeitos.tags == (flows.TAG_HUMANO,), antigo


def test_estado_vazio_comeca_no_no_inicial():
    """Primeiro inbound de uma conversa semeada por disparo: flow_state ainda é NULL."""
    d = engine.decidir(None, Clique(flows.ID_REPOR, "Preciso repor"),
                       canal_do_vendedor=False, contexto=CTX)
    assert d.efeitos.handoff is True


def test_estado_dict_vazio_comeca_no_no_inicial():
    """`{}` e None são o mesmo caso: disparo semeou a conversa, bot ainda não agiu."""
    d = engine.decidir({}, Clique(flows.ID_REPOR, "Preciso repor"),
                       canal_do_vendedor=False, contexto=CTX)
    assert d.efeitos.handoff is True


def test_estado_sem_flow_devolve_ao_humano():
    """Dict sem a chave `flow`: sai já na checagem de versão, antes de olhar o nó."""
    d = engine.decidir({"node": 42}, Texto("oi"), canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.efeitos.tags == (flows.TAG_HUMANO,)


def test_estado_com_no_desconhecido_devolve_ao_humano():
    """Versão certa, nó que não existe: o fluxo mudou debaixo do lead.

    Distinto dos casos acima de propósito: `{"node": 42}` sem `flow` nunca chega na
    whitelist de nós, então só este teste cobre esse ramo do _estado_valido.
    """
    d = engine.decidir({"flow": flows.FLOW_ID, "node": "aguardando_orcamento"},
                       Texto("oi"), canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.efeitos.tags == (flows.TAG_HUMANO,)


def test_flow_state_que_nao_e_objeto_devolve_ao_humano():
    """jsonb aceita escalar e array; nenhum dos dois é "conversa não iniciada".

    A string quebraria no .get(); a lista vazia é falsy e reiniciaria o lead no nó
    inicial, renudgeando quem já tinha sido entregue ao vendedor.
    """
    for corrompido in ("aguardando_interesse", [], 0, 42, True, [{"node": "x"}]):
        d = engine.decidir(corrompido, Texto("oi"), canal_do_vendedor=False)
        assert d.proximo_no == flows.NO_ENCERRADO, corrompido
        assert d.efeitos.tags == (flows.TAG_HUMANO,), corrompido
        assert d.mensagem is None, corrompido
        assert d.marcar_nudge is False, corrompido


# ── Defesa contra fall-through ──────────────────────────────────────────────
def test_botao_de_nivel_1_sem_tratamento_nao_faz_optout():
    """Fall-through nunca pode virar opt-out — é o efeito mais destrutivo do fluxo.

    Chama a função privada de propósito: por construção o caso é inalcançável pela
    API pública (só existem os cinco botões declarados, e um id de fora não casa em
    _casar_nivel1), e o objetivo é pinar o ramo defensivo. Antes o opt-out ERA o
    fall-through: um botão novo desligaria o lead da base sem ninguém pedir.
    """
    botao_novo = flows.Botao("interesse_desconhecido", "Outra coisa")
    d = engine._efeito_nivel1(botao_novo, flows.TRILHA_ESTOQUE,
                              canal_do_vendedor=False, contexto=Contexto())
    assert d.ignorar is True
    assert d.efeitos.optout is False
    assert d.efeitos.handoff is False
    assert d.mensagem is None


def test_no_sem_tratamento_no_clique_e_inerte():
    """Mesma defesa, agora para um NÓ novo: antes caía num next() sem default.

    Também privada pelo mesmo motivo: _estado_valido barra nó desconhecido antes de
    chegar aqui, então o ramo só é alcançável se o fluxo ganhar um nó novo. O
    contrato é devolver None (o chamador reoferece), nunca um efeito.
    """
    assert engine._decidir_clique(
        "aguardando_orcamento", flows.TRILHA_ESTOQUE,
        Clique(flows.ID_OPTOUT, "Parar mensagens"),
        canal_do_vendedor=False, contexto=Contexto(),
    ) is None


def test_nenhum_clique_alem_do_optout_desliga_o_lead():
    """Varredura sobre TODOS os botões das três trilhas, por id e por rótulo.

    Só "Parar mensagens" produz opt-out; só `repor` e `atualizar` produzem handoff.
    Uma troca de ordem nos ifs de _efeito_nivel1, ou um id reaproveitado num relabel
    futuro, aparece aqui — e não no disparo de 900 leads.
    """
    desliga = {flows.ID_OPTOUT}
    transborda = {flows.ID_REPOR, flows.ID_ATUALIZAR}
    for trilha, botoes in flows.BOTOES_POR_TRILHA.items():
        for b in botoes:
            for clique in (Clique(b.id, b.titulo), Clique(b.titulo, b.titulo)):
                d = engine.decidir(estado(trilha=trilha), clique,
                                   canal_do_vendedor=False, contexto=CTX)
                caso = (trilha, b.id, clique.payload)
                assert d.efeitos.optout is (b.id in desliga), caso
                assert d.efeitos.handoff is (b.id in transborda), caso
    for prazo in flows.PRAZOS:
        d = engine.decidir(estado(flows.NO_PRAZO), Clique(prazo.id, prazo.titulo),
                           canal_do_vendedor=False)
        assert d.efeitos.optout is False and d.efeitos.handoff is False, prazo.id


def test_nenhuma_mensagem_do_fluxo_vaza_placeholder():
    """render() não é str.format: chave ausente fica no texto em vez de estourar.

    Isso protege o processo (nada quebra em produção) e não protege o lead, que veria
    "{produto}" na tela. A varredura fecha essa ponta para todos os desfechos, com
    contexto completo, parcial e vazio.
    """
    eventos = [Clique(b.id, b.titulo) for b in flows.TODOS_BOTOES_NIVEL1]
    eventos += [Clique(p.id, p.titulo) for p in flows.PRAZOS]
    eventos += [Classificado(c) for c in engine.CLASSES]
    eventos += [Texto("oi")]
    contextos = (CTX, Contexto(primeiro_nome="Ana", produto="cápsula"),
                 Contexto(primeiro_nome="Ana"), Contexto())
    for no in (flows.NO_INTERESSE, flows.NO_PRAZO):
        for evento in eventos:
            for ctx in contextos:
                d = engine.decidir(estado(no), evento, canal_do_vendedor=False,
                                   contexto=ctx)
                if d.mensagem is None:
                    continue
                assert "{" not in d.mensagem.corpo, (no, evento, ctx)
                assert "}" not in d.mensagem.corpo, (no, evento, ctx)


def test_lead_sem_primeiro_nome_nao_recebe_pontuacao_orfa():
    """Nome vazio não pode deixar vírgula órfã no texto que vai para o cliente.

    Era um xfail: os textos traziam a vírgula colada no placeholder
    ("obrigado, {primeiro_nome}!") e um cadastro sem nome produzia literalmente
    "obrigado, ! deixei seu cadastro ativo" e "perfeito,\\njá chamei o João aqui" —
    a primeira coisa que o cliente lê depois de até 7 anos sem contato.

    Não é hipótese: na coorte do Bling `leads.name` vem da razão social e às vezes é
    handle ou CPF ("RD Recepção", "@neimaraoliveirapsicotera", "ANA PAULA GAMA
    PEZZOT 40250877821"). A correção move a pontuação para `engine._vocativo`, de
    modo que texto novo em flows.py só precise escrever "{vocativo}".
    """
    cadastro = engine.decidir(estado(trilha=flows.TRILHA_CADASTRO),
                              Clique(flows.ID_MANTER, "Manter cadastro"),
                              canal_do_vendedor=True, contexto=Contexto())
    assert "obrigado, !" not in cadastro.mensagem.corpo
    assert cadastro.mensagem.corpo.startswith("obrigado!")

    quente = engine.decidir(estado(), Clique(flows.ID_REPOR, "Preciso repor"),
                            canal_do_vendedor=True, contexto=Contexto())
    assert not quente.mensagem.corpo.startswith("perfeito, \n")
    assert quente.mensagem.corpo.startswith("perfeito\n")

    # Só espaço em branco também conta como sem nome.
    branco = engine.decidir(estado(), Clique(flows.ID_REPOR, "Preciso repor"),
                            canal_do_vendedor=True, contexto=Contexto("   "))
    assert branco.mensagem.corpo.startswith("perfeito\n")

    # E com nome a vírgula continua lá, que é o caso normal.
    com_nome = engine.decidir(estado(), Clique(flows.ID_REPOR, "Preciso repor"),
                              canal_do_vendedor=True, contexto=Contexto("Rafael"))
    assert com_nome.mensagem.corpo.startswith("perfeito, Rafael\n")


# ── Entrega ao humano ───────────────────────────────────────────────────────
def test_entrega_ao_humano_silencia_a_ia_sem_carimbar_handoff():
    """Encerrar o nó só tira o BOT do caminho — no número da ValerIA o LLM assumiria
    em seguida. silenciar_ia é o que entrega de fato ao vendedor; handoff=True seria
    errado aqui (carimbaria lead qualificado que nunca foi)."""
    d = engine.decidir(estado(nudged=True), Texto("me liga"), canal_do_vendedor=False)
    assert d.efeitos.silenciar_ia is True
    assert d.efeitos.handoff is False
    assert d.efeitos.tags == (flows.TAG_HUMANO,)


def test_texto_livre_no_nivel_2_ja_nudgeado_entrega_ao_humano():
    d = engine.decidir(estado(flows.NO_PRAZO, nudged=True), Texto("sei lá"),
                       canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.efeitos.tags == (flows.TAG_HUMANO,)
    assert d.efeitos.silenciar_ia is True


# ── normalizar ──────────────────────────────────────────────────────────────
def test_normalizar_aceita_none_e_vazio():
    """O payload do webhook é opcional em vários formatos da Meta."""
    assert engine.normalizar(None) == ""
    assert engine.normalizar("") == ""


def test_normalizar_tira_caixa_acento_e_espaco_invisivel():
    assert engine.normalizar("  NÃO QUERO MAIS RECEBER  ") == "nao quero mais receber"
    # NBSP (\xa0), NÃO espaço comum: é o que o nome do teste promete e o único caso
    # que só o NFKD resolve — .strip() sozinho já daria conta do espaço normal.
    # Escrito como escape de propósito: no relabel de 09/09/2026 os três NBSP viraram
    # espaços comuns na reescrita e ninguém viu, porque um NBSP literal é invisível
    # no diff. O do meio é o que importa: prova que a conversão vale DENTRO do texto,
    # onde o strip não alcança.
    assert engine.normalizar("\xa0Parar\xa0mensagens\xa0") == "parar mensagens"
    # E o rótulo com espaço duro casa de fato no botão, não só na normalização.
    assert engine._casar_nivel1(Clique("", "\xa0Parar\xa0mensagens\xa0")).id == flows.ID_OPTOUT


def test_normalizar_nao_remove_emoji_nem_largura_zero():
    """Limite conhecido: emoji e ZWSP atravessam a normalização.

    Um rótulo aprovado com emoji só casa se o template tiver exatamente o mesmo
    emoji. Isso é seguro porque o preflight do disparo compara os rótulos do template
    com ESTA função e recusa o disparo se divergirem — o desencontro aparece antes do
    envio, não no clique do lead.
    """
    assert engine.normalizar("Parar mensagens 👍") == "parar mensagens 👍"
    assert engine.normalizar("Parar​mensagens") == "parar​mensagens"


# ── Imutabilidade ───────────────────────────────────────────────────────────
def test_decisoes_sao_congeladas():
    """_ENTREGAR_AO_HUMANO é um singleton de módulo compartilhado entre turnos.

    Só é seguro compartilhar enquanto as dataclasses forem frozen: um efeito escrito
    por engano num turno vazaria para todos os leads seguintes do processo.
    """
    d = engine.decidir(estado(nudged=True), Texto("me liga"), canal_do_vendedor=False)
    assert d is engine._ENTREGAR_AO_HUMANO
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.proximo_no = flows.NO_INTERESSE
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.efeitos.optout = True


def test_contexto_e_mensagem_tambem_sao_congelados():
    """O runner monta um Contexto por turno e o motor devolve Mensagem que atravessa
    envio e persistência; mutar qualquer um deles no meio do caminho seria invisível."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        CTX.preco = "R$ 1,00"
    d = engine.decidir(estado(), Clique(flows.ID_OPTOUT, "Parar mensagens"),
                       canal_do_vendedor=False)
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.mensagem.corpo = "outra coisa"

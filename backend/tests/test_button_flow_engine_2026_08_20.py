"""Núcleo puro do bot de botões: declaração do fluxo + motor de decisão.

Sem I/O: tudo aqui opera sobre dicts e dataclasses, no mesmo espírito de
app/agent/persona.py. É a camada onde a matriz de comportamento tem que estar
100% coberta, porque é a única que roda igual em produção e no teste.
"""
from app.button_flow import flows


def test_limites_da_meta_nos_botoes():
    """3 botões no máximo, título de até 20 chars na interativa, ids únicos."""
    for no, botoes in flows.BOTOES_POR_NO.items():
        assert 1 <= len(botoes) <= 3, f"{no}: a Meta aceita no máximo 3 botões"
        ids = [b.id for b in botoes]
        assert len(ids) == len(set(ids)), f"{no}: ids duplicados"
        for b in botoes:
            assert len(b.titulo) <= 20, f"{no}/{b.id}: título > 20 chars na interativa"


def test_rotulo_do_template_e_aceito_pelo_botao_correspondente():
    """Nível 1 tem DOIS rótulos por botão: o do template e o da interativa.

    A Meta permite 25 chars no botão de template e só 20 no de mensagem interativa,
    e dois dos rótulos aprovados têm 22 — não cabem na interativa. O template mantém
    a copy aprovada; o reoferecimento usa a versão curta. Os dois têm que casar o
    mesmo clique, senão o lead que responde ao template cai no vazio.
    """
    for botao, rotulo in zip(flows.BOTOES_INTERESSE, flows.ROTULOS_TEMPLATE_NIVEL1):
        assert rotulo in botao.titulos_aceitos
        assert botao.titulo in botao.titulos_aceitos


def test_rotulos_do_template_cabem_no_limite_de_template():
    for rotulo in flows.ROTULOS_TEMPLATE_NIVEL1:
        assert len(rotulo) <= 25, f"{rotulo!r}: título > 25 chars no template"


def test_nenhum_rotulo_aceito_e_ambiguo():
    """Dois botões que aceitam o mesmo texto tornariam o clique indecidível."""
    vistos: dict[str, str] = {}
    for no, botoes in flows.BOTOES_POR_NO.items():
        for b in botoes:
            for titulo in b.titulos_aceitos:
                chave = titulo.strip().lower()
                assert chave not in vistos, f"{titulo!r} já é aceito por {vistos[chave]}"
                vistos[chave] = f"{no}/{b.id}"


def test_todo_prazo_tem_tag_e_meses():
    for prazo in flows.PRAZOS:
        assert prazo.meses > 0
        assert prazo.tag.startswith("Reativação: ")
        assert prazo.rotulo_humano


def test_ids_de_botao_sao_unicos_em_todo_o_fluxo():
    """O motor indexa cliques por id num dict achatado sobre TODOS os nós.

    Uma colisão de id não daria erro: o dict comprehension sobrescreve em
    silêncio e o clique passaria a cair no nó errado. A unicidade por nó
    (test_limites_da_meta_nos_botoes) não cobre isso.
    """
    ids = [b.id for botoes in flows.BOTOES_POR_NO.values() for b in botoes]
    assert len(ids) == len(set(ids)), f"ids repetidos entre nós: {ids}"


def test_todo_no_com_botoes_tem_corpo_de_nudge():
    """O reoferecimento lê o corpo pelo nó; um nó sem corpo seria KeyError."""
    assert set(flows.CORPO_NUDGE_POR_NO) == set(flows.BOTOES_POR_NO)


from app.button_flow import engine
from app.button_flow.engine import Clique, Decisao, Texto


def estado(no: str = flows.NO_INTERESSE, nudged: bool = False) -> dict:
    return {"flow": flows.FLOW_ID, "node": no, "nudged": nudged}


# ── Nível 1 ─────────────────────────────────────────────────────────────────
def test_clique_quente_no_numero_da_valeria_manda_cartao():
    d = engine.decidir(estado(), Clique("Quero comprar agora", "Quero comprar agora"),
                       canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.mensagem.corpo == flows.MSG_QUENTE_VALERIA
    assert d.mensagem.enviar_cartao_vendedor is True
    assert d.mensagem.botoes == ()
    assert d.efeitos.handoff is True
    assert d.efeitos.tags == (flows.TAG_QUENTE,)
    assert d.efeitos.optout is False


def test_clique_quente_no_numero_do_vendedor_nao_manda_cartao():
    d = engine.decidir(estado(), Clique("Quero comprar agora", "Quero comprar agora"),
                       canal_do_vendedor=True)
    assert d.mensagem.corpo == flows.MSG_QUENTE_VENDEDOR
    assert d.mensagem.enviar_cartao_vendedor is False
    assert d.efeitos.handoff is True


def test_clique_talvez_abre_o_nivel_2():
    d = engine.decidir(estado(), Clique("Talvez em alguns meses", "Talvez em alguns meses"),
                       canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_PRAZO
    assert d.mensagem.corpo == flows.CORPO_PRAZO
    assert d.mensagem.botoes == flows.BOTOES_PRAZO
    assert d.efeitos.tags == ()
    assert d.efeitos.handoff is False


def test_clique_sair_faz_optout():
    d = engine.decidir(estado(), Clique("Não quero mais receber", "Não quero mais receber"),
                       canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.mensagem.corpo == flows.MSG_OPTOUT
    assert d.efeitos.optout is True
    assert d.efeitos.tags == (flows.TAG_RECUSOU,)


def test_clique_casa_pelo_rotulo_curto_da_interativa():
    """O nudge sai com o rótulo curto; o clique nele tem que valer o mesmo."""
    d = engine.decidir(estado(nudged=True), Clique("Sair da lista", "Sair da lista"),
                       canal_do_vendedor=False)
    assert d.efeitos.optout is True


def test_clique_do_nudge_casa_por_id():
    """O reoferecimento sai como interativa com ids nossos — tem que casar igual."""
    d = engine.decidir(estado(nudged=True), Clique("interesse_sair", "Não quero mais receber"),
                       canal_do_vendedor=False)
    assert d.efeitos.optout is True


def test_casamento_de_titulo_ignora_caixa_e_acento():
    d = engine.decidir(estado(), Clique("NAO QUERO MAIS RECEBER", "NAO QUERO MAIS RECEBER"),
                       canal_do_vendedor=False)
    assert d.efeitos.optout is True


# ── Nível 2 ─────────────────────────────────────────────────────────────────
def test_cada_prazo_grava_tag_e_meses():
    for prazo in flows.PRAZOS:
        d = engine.decidir(estado(flows.NO_PRAZO), Clique(prazo.id, prazo.titulo),
                           canal_do_vendedor=False)
        assert d.proximo_no == flows.NO_ENCERRADO
        assert d.efeitos.tags == (prazo.tag,)
        assert d.efeitos.recontato_meses == prazo.meses
        assert prazo.rotulo_humano in d.mensagem.corpo
        assert d.mensagem.botoes == ()


# ── Texto livre ─────────────────────────────────────────────────────────────
def test_texto_livre_reoferece_os_botoes_uma_vez():
    d = engine.decidir(estado(), Texto("oi, quanto custa?"), canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_INTERESSE
    assert d.mensagem.botoes == flows.BOTOES_INTERESSE
    assert d.mensagem.corpo == flows.CORPO_NUDGE
    assert d.marcar_nudge is True
    assert d.efeitos.tags == ()


def test_texto_livre_no_nivel_2_reoferece_os_botoes_de_prazo():
    d = engine.decidir(estado(flows.NO_PRAZO), Texto("sei lá"), canal_do_vendedor=False)
    assert d.mensagem.botoes == flows.BOTOES_PRAZO
    assert d.marcar_nudge is True


def test_segundo_texto_livre_entrega_ao_humano():
    d = engine.decidir(estado(nudged=True), Texto("me liga"), canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.mensagem is None
    assert d.efeitos.tags == (flows.TAG_HUMANO,)


# ── Cliques fora do nó ──────────────────────────────────────────────────────
def test_clique_de_outro_no_e_ignorado_sem_nudge():
    """Tocar de novo no botão do nível 1 já respondido não é recusa a usar botões."""
    d = engine.decidir(estado(flows.NO_PRAZO),
                       Clique("Talvez em alguns meses", "Talvez em alguns meses"),
                       canal_do_vendedor=False)
    assert d.ignorar is True
    assert d.mensagem is None
    assert d.efeitos.tags == ()
    assert d.proximo_no == flows.NO_PRAZO
    assert d.marcar_nudge is False


def test_clique_desconhecido_cai_na_regra_de_texto_livre():
    """Botão que não pertence a nenhum nó do fluxo é tratado como texto."""
    d = engine.decidir(estado(), Clique("botao_de_outro_bot", "Sei lá"),
                       canal_do_vendedor=False)
    assert d.ignorar is False
    assert d.mensagem.botoes == flows.BOTOES_INTERESSE


# ── Estados terminais e inválidos ───────────────────────────────────────────
def test_no_encerrado_ignora_tudo():
    d = engine.decidir(estado(flows.NO_ENCERRADO), Texto("oi"), canal_do_vendedor=False)
    assert d.ignorar is True
    assert d.mensagem is None


def test_flow_de_outra_versao_devolve_ao_humano():
    d = engine.decidir({"flow": "reativacao_v0", "node": flows.NO_INTERESSE},
                       Texto("oi"), canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.mensagem is None
    assert d.efeitos.tags == (flows.TAG_HUMANO,)


def test_estado_vazio_comeca_no_no_inicial():
    """Primeiro inbound de uma conversa semeada por disparo: flow_state ainda é NULL."""
    d = engine.decidir(None, Clique("Quero comprar agora", "Quero comprar agora"),
                       canal_do_vendedor=False)
    assert d.efeitos.handoff is True


def test_estado_corrompido_devolve_ao_humano():
    d = engine.decidir({"node": 42}, Texto("oi"), canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.efeitos.tags == (flows.TAG_HUMANO,)

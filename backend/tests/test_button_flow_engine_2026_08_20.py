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

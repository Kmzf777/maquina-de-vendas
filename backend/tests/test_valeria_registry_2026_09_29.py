"""O registry da ValerIA de botões é o contrato entre a tela e o motor.

Espelha tests/test_node_registry.py: o teste cruza a declaração com as regras
que a Meta e o score impõem, para que um nó novo não entre sem destino nem um
rótulo longo demais chegue à produção (rótulo > 20 chars = a Meta recusa o
envio e a ValerIA fica MUDA naquele nó).
"""
from app.button_flow import valeria_registry as reg
from app.lead_score.model import CRITERIA_FIELDS


def test_flow_id_declarado():
    assert reg.FLOW_ID == "valeria_botoes_v1"


def test_todo_destino_existe():
    """Botão apontando para nó inexistente = lead parado para sempre."""
    conhecidos = set(reg.NOS) | set(reg.TERMINAIS)
    for no in reg.NOS.values():
        for botao in no.botoes:
            assert botao.destino in conhecidos, (
                f"{no.id}/{botao.id} aponta para {botao.destino!r}, que não existe"
            )


def test_todo_no_alcancavel_da_entrada():
    """Nó órfão é trabalho morto que a tela ainda oferece para editar."""
    vistos, fila = {reg.NO_ENTRADA}, [reg.NO_ENTRADA]
    while fila:
        atual = fila.pop()
        for botao in reg.NOS[atual].botoes:
            if botao.destino in reg.NOS and botao.destino not in vistos:
                vistos.add(botao.destino)
                fila.append(botao.destino)
    assert vistos == set(reg.NOS), f"órfãos: {sorted(set(reg.NOS) - vistos)}"


def test_limite_de_botoes_da_meta():
    """meta.py:326 levanta acima de 3; lista aceita até 10."""
    for no in reg.NOS.values():
        teto = reg.MAX_LINHAS_LISTA if no.tela == "lista" else reg.MAX_BOTOES
        assert 1 <= len(no.botoes) <= teto, f"{no.id} tem {len(no.botoes)} botões"


def test_rotulos_default_cabem_no_limite():
    for no in reg.NOS.values():
        limite = reg.LIMITE_TITULO_LISTA if no.tela == "lista" else reg.LIMITE_ROTULO_BOTAO
        for botao in no.botoes:
            assert len(botao.rotulo) <= limite, (
                f"{no.id}/{botao.id}: {len(botao.rotulo)} chars, limite {limite}"
            )


def test_ids_de_botao_unicos_dentro_do_no():
    """O motor casa o clique por id dentro do nó; id repetido é rota ambígua."""
    for no in reg.NOS.values():
        ids = [b.id for b in no.botoes]
        assert len(ids) == len(set(ids)), f"{no.id} tem id repetido: {ids}"


def test_grava_usa_campo_valido_do_score():
    for no in reg.NOS.values():
        for botao in no.botoes:
            for campo, _valor in botao.grava:
                assert campo in CRITERIA_FIELDS, f"{no.id}/{botao.id}: {campo!r}"


def test_corpo_nunca_vazio():
    for no in reg.NOS.values():
        assert no.corpo.strip(), f"{no.id} tem corpo vazio"


def test_foto_declarada_quando_a_tela_e_de_foto():
    for no in reg.NOS.values():
        if no.tela == "foto_botoes":
            assert no.foto, f"{no.id} é foto_botoes e não declara foto"


def test_n5b_nao_tem_o_botao_de_ver_outras():
    """'Uma vez só' é garantido pela TOPOLOGIA, não por contador no estado."""
    assert "ver_outras" not in {b.id for b in reg.NOS["N5b"].botoes}
    assert "ver_outras" not in {b.id for b in reg.NOS["P4b"].botoes}

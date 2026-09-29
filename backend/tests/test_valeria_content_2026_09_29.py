"""Overrides de conteúdo: o banco sobrescreve o registry, e a ausência dele não quebra.

O fluxo TEM que rodar com a tabela vazia ou inexistente. Migration pendente é um
modo de falha recorrente neste repo, e aqui ele emudeceria a ValerIA.
"""
from app.button_flow import valeria_content as conteudo
from app.button_flow import valeria_registry as reg


def test_sem_override_devolve_o_default_do_registry():
    nos = conteudo.aplicar(reg.NOS, {})
    assert nos["N1"].corpo == reg.NOS["N1"].corpo
    assert nos["N1"].botoes[0].rotulo == reg.NOS["N1"].botoes[0].rotulo


def test_override_de_corpo():
    nos = conteudo.aplicar(reg.NOS, {"N1": {"corpo": "qual seu segmento?"}})
    assert nos["N1"].corpo == "qual seu segmento?"
    assert nos["N2"].corpo == reg.NOS["N2"].corpo, "não vaza para outro nó"


def test_override_de_rotulo_por_id_e_parcial():
    nos = conteudo.aplicar(reg.NOS, {"N1": {"rotulos": {"cafeteria": "Sou cafeteria"}}})
    por_id = {b.id: b.rotulo for b in nos["N1"].botoes}
    assert por_id["cafeteria"] == "Sou cafeteria"
    assert por_id["loja"] == reg.NOS["N1"].botoes[1].rotulo, "id ausente mantém o default"


def test_override_nunca_muda_o_destino():
    """A tela edita texto. Rota é estrutura, e estrutura é código."""
    nos = conteudo.aplicar(reg.NOS, {"N1": {"rotulos": {"cafeteria": "X"},
                                            "destino": "T_OPTOUT"}})
    assert nos["N1"].botoes[0].destino == reg.NOS["N1"].botoes[0].destino


def test_override_nunca_muda_o_grava():
    """Nem o campo do score: trocar `grava` pela tela falsificaria a qualificação."""
    nos = conteudo.aplicar(reg.NOS, {"N1": {"grava": (("segment", "hotel"),)}})
    assert nos["N1"].botoes[0].grava == reg.NOS["N1"].botoes[0].grava


def test_no_desconhecido_no_override_e_ignorado():
    nos = conteudo.aplicar(reg.NOS, {"NAO_EXISTE": {"corpo": "x"}})
    assert set(nos) == set(reg.NOS)


def test_aplicar_nao_muta_o_registry():
    """O registry é frozen, mas o dict que o contém não é."""
    antes = reg.NOS["N1"].corpo
    conteudo.aplicar(reg.NOS, {"N1": {"corpo": "outro"}})
    assert reg.NOS["N1"].corpo == antes


def test_carregar_devolve_vazio_quando_o_banco_falha(monkeypatch):
    def explode():
        raise RuntimeError("relation valeria_flow_content does not exist")
    monkeypatch.setattr(conteudo, "get_supabase", explode)
    assert conteudo.carregar(reg.FLOW_ID) == {}


# ── Validação, que é o que impede a ValerIA de emudecer ───────────────────
def test_rotulo_acima_do_limite_e_rejeitado():
    erro = conteudo.validar("N1", {"rotulos": {"cafeteria": "U" * 21}})
    assert erro and "20" in erro


def test_rotulo_no_limite_passa():
    assert conteudo.validar("N1", {"rotulos": {"cafeteria": "U" * 20}}) is None


def test_corpo_vazio_e_rejeitado():
    assert conteudo.validar("N1", {"corpo": "   "})


def test_titulo_de_lista_usa_o_limite_de_24():
    assert conteudo.validar("N0", {"rotulos": {"negocio": "U" * 25}})
    assert conteudo.validar("N0", {"rotulos": {"negocio": "U" * 24}}) is None


def test_rotulo_de_botao_que_nao_existe_e_rejeitado():
    """Chave errada gravaria override morto, invisível na tela."""
    assert conteudo.validar("N1", {"rotulos": {"nao_existe": "X"}})


def test_validar_no_desconhecido():
    assert conteudo.validar("NAO_EXISTE", {"corpo": "x"})


def test_nudge_e_editavel_pela_chave_reservada():
    """O corpo do nudge é editável na tela, mas o nudge NÃO é um nó."""
    assert conteudo.validar(reg.CHAVE_NUDGE, {"corpo": "toque numa opção"}) is None
    assert conteudo.validar(reg.CHAVE_NUDGE, {"corpo": "  "})

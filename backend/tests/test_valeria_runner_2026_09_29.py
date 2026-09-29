"""O runner da ValerIA: monta o evento, aplica a decisão, envia e persiste.

Testado com dublês de provedor, como test_button_flow_runner_2026_09_09.py já faz.
O que importa aqui é o CONTRATO de envio — que método do provedor é chamado para
cada tipo de tela — e a persistência do contador de nudges.

── Duas adaptações em relação ao rascunho do plano, com o motivo ─────────────
1. Os testes que tocam um nó `foto_botoes` dublam `runner.url_publica_da_foto`.
   `No.foto` é caminho de ARQUIVO local (`backend/app/photos/...`) e não existe
   servidor de estático nem base pública no repo: transformar o caminho numa URL
   que a Meta consiga buscar é I/O (upload para o bucket público), e o rascunho
   chamava `enviar_no` sem dublê nenhum. O comportamento verificado é o MESMO —
   UMA mensagem, com header de imagem — e ganhou um teste a mais: foto
   indisponível não pode custar a tela.
2. `save_score_evidence` recebe `updates`, não `criteria`
   (`app/lead_score/repository.py:63`). A asserção de conteúdo dos critérios
   voltou com o nome real do parâmetro.
"""
import pytest

from app.button_flow import valeria_registry as reg
from app.button_flow import valeria_runner as runner


class ProvedorFalso:
    def __init__(self):
        self.chamadas = []

    async def send_interactive_buttons(self, to, body, buttons, image_url=None):
        self.chamadas.append(("botoes", body, buttons, image_url))
        return {"messages": [{"id": "wamid.1"}]}

    async def send_interactive_list(self, to, body, button, rows, header=None):
        self.chamadas.append(("lista", body, rows))
        return {"messages": [{"id": "wamid.2"}]}

    async def send_text(self, to, text):
        self.chamadas.append(("texto", text))
        return {"messages": [{"id": "wamid.3"}]}


@pytest.fixture
def foto_publicada(monkeypatch):
    """Publica a foto sem tocar a rede. Ver adaptação 1 no docstring do módulo."""
    monkeypatch.setattr(runner, "url_publica_da_foto",
                        lambda caminho: f"https://storage.exemplo/{caminho}")


@pytest.mark.asyncio
async def test_no_de_lista_usa_send_interactive_list():
    p = ProvedorFalso()
    await runner.enviar_no(p, "5534988861441", reg.NOS["N0"], {})
    assert p.chamadas[0][0] == "lista"
    assert len(p.chamadas[0][2]) == 4, "a tela de entrada tem 4 linhas"


@pytest.mark.asyncio
async def test_no_de_botoes_usa_send_interactive_buttons_sem_imagem():
    p = ProvedorFalso()
    await runner.enviar_no(p, "5534988861441", reg.NOS["N1"], {})
    tipo, _body, botoes, image_url = p.chamadas[0]
    assert tipo == "botoes"
    assert len(botoes) == 3
    assert image_url is None


@pytest.mark.asyncio
async def test_no_de_foto_manda_UMA_mensagem_com_header(foto_publicada):
    """Foto + preço + botões numa mensagem é o que corta 2 msgs faturadas/lead."""
    p = ProvedorFalso()
    await runner.enviar_no(p, "5534988861441", reg.NOS["N5"], {"preco": "R$28,70"})
    assert len(p.chamadas) == 1, "não pode ser foto e depois texto"
    assert p.chamadas[0][3], "image_url não foi montado"


@pytest.mark.asyncio
async def test_foto_indisponivel_nao_custa_a_tela(monkeypatch):
    """Sem URL pública a tela sai SEM header — nunca sem mensagem.

    O contrário (não enviar) deixaria o lead sem a pergunta de encaminhamento,
    que é o turno que decide o ramo mais caro do fluxo.
    """
    monkeypatch.setattr(runner, "url_publica_da_foto", lambda _caminho: None)
    p = ProvedorFalso()
    await runner.enviar_no(p, "5534988861441", reg.NOS["N5"], {"preco": "R$28,70"})
    assert len(p.chamadas) == 1
    assert p.chamadas[0][0] == "botoes"
    assert p.chamadas[0][3] is None


@pytest.mark.asyncio
async def test_sem_preco_no_catalogo_o_corpo_sai_sem_a_linha_de_preco(monkeypatch):
    """Cotar de memória foi o que perdeu as 500 unidades da Ritz."""
    monkeypatch.setattr(runner, "url_publica_da_foto", lambda _caminho: None)
    p = ProvedorFalso()
    await runner.enviar_no(p, "5534988861441", reg.NOS["N5"], {})
    corpo = p.chamadas[0][1]
    assert "{preco}" not in corpo, "marcador vazou para o lead"
    assert "R$" not in corpo, "cotou sem catálogo"
    assert "gostaria de ser encaminhado ao vendedor?" in corpo, "cortou o turno todo"


@pytest.mark.asyncio
async def test_prazo_e_renderizado_no_fechamento_do_adiamento():
    """T_ADIADO guarda o molde com {prazo}; o runner resolve."""
    p = ProvedorFalso()
    await runner.enviar_terminal(p, "5534988861441", reg.TERMINAIS["T_ADIADO"],
                                 {"prazo": "em 60 dias"})
    corpo = p.chamadas[0][1]
    assert "{prazo}" not in corpo, "marcador vazou para o lead"
    assert "em 60 dias" in corpo


@pytest.mark.asyncio
async def test_terminal_de_corpo_vazio_nao_envia_nada():
    """corpo vazio é o contrato de 'não gasta mensagem faturada'."""
    p = ProvedorFalso()
    await runner.enviar_terminal(p, "5534988861441", reg.TERMINAIS["T_HUMANO"], {})
    assert p.chamadas == []


@pytest.mark.asyncio
async def test_terminal_de_adiamento_oferece_a_folha_de_prazos():
    """`T_ADIAR` pergunta: os 30/60/90 saem como botões, não como texto solto."""
    p = ProvedorFalso()
    await runner.enviar_terminal(p, "5534988861441", reg.TERMINAIS["T_ADIAR"], {})
    assert p.chamadas[0][0] == "botoes"
    assert [b[0] for b in p.chamadas[0][2]] == [b.id for b in reg.BOTOES_PRAZO]


def test_estado_novo_comeca_na_entrada_com_zero_nudges():
    assert runner.estado_inicial() == {
        "flow": reg.FLOW_ID, "node": reg.NO_ENTRADA, "nudges": 0,
    }


def test_nudge_incrementa_e_clique_nao():
    assert runner.proximo_estado({"nudges": 1}, "N1", marcar_nudge=True)["nudges"] == 2
    assert runner.proximo_estado({"nudges": 1}, "N2", marcar_nudge=False)["nudges"] == 1


def test_estado_de_outro_fluxo_e_tratado_como_incompativel():
    """flow_state da recuperação não pode ser lido como se fosse da ValerIA."""
    assert runner.no_atual({"flow": "recuperacao_v1", "node": "aguardando_prazo"}) is None


def test_estado_corrompido_nao_estoura():
    for lixo in (None, [], "lixo", 0, {"nudges": "tres"}):
        runner.no_atual(lixo)


def test_proximo_estado_de_lixo_nao_estoura():
    """jsonb aceita escalar e array: o merge não pode presumir dict."""
    for lixo in (None, [], "lixo", 0, {"nudges": "tres"}):
        estado = runner.proximo_estado(lixo, "N1", marcar_nudge=True)
        assert estado["node"] == "N1"
        assert estado["nudges"] == 1


# ── O score, que é o objetivo do ramo de atacado ──────────────────────────
@pytest.mark.asyncio
async def test_criterios_do_clique_viram_snapshot_de_score(monkeypatch):
    """Sem isto o ramo de atacado roda inteiro e não qualifica ninguém — que é
    exatamente o que o fluxo existe para consertar."""
    gravados = []
    monkeypatch.setattr(runner, "save_score_evidence",
                        lambda **kw: gravados.append(kw))
    await runner.aplicar_criterios("lead-1", {"segment": "cafeteria"})
    assert gravados, "save_score_evidence não foi chamado"
    assert gravados[0]["lead_id"] == "lead-1"
    assert gravados[0]["updates"] == {"segment": "cafeteria"}
    assert gravados[0]["source"] == "live", "'live' é o snapshot da conversa ao vivo"


@pytest.mark.asyncio
async def test_criterios_vazios_nao_chamam_o_banco(monkeypatch):
    """Nó sem `grava` não pode gerar escrita por turno."""
    gravados = []
    monkeypatch.setattr(runner, "save_score_evidence",
                        lambda **kw: gravados.append(kw))
    await runner.aplicar_criterios("lead-1", {})
    assert gravados == []


@pytest.mark.asyncio
async def test_falha_do_score_nao_derruba_o_turno(monkeypatch):
    """O lead recebe a próxima tela mesmo que o snapshot falhe. Perder um ponto
    de score é menos grave que deixar o lead sem resposta."""
    def explode(**_kw):
        raise RuntimeError("conflito de CAS")
    monkeypatch.setattr(runner, "save_score_evidence", explode)
    await runner.aplicar_criterios("lead-1", {"segment": "cafeteria"})


@pytest.mark.asyncio
async def test_rotulo_do_clique_vira_evidencia_do_criterio(monkeypatch):
    """A prova do critério é o texto que o lead tocou, não um campo inventado."""
    gravados = []
    monkeypatch.setattr(runner, "save_score_evidence",
                        lambda **kw: gravados.append(kw))
    await runner.aplicar_criterios("lead-1", {"segment": "cafeteria"},
                                   rotulo="Cafeteria")
    assert gravados[0]["evidence"] == {"segment": {"text": "Cafeteria"}}


@pytest.mark.asyncio
async def test_sem_rotulo_grava_o_criterio_sem_evidencia(monkeypatch):
    """`_validate_evidence_shape` recusa texto vazio — e recusar levaria o
    critério inteiro embora, que é o oposto do objetivo."""
    gravados = []
    monkeypatch.setattr(runner, "save_score_evidence",
                        lambda **kw: gravados.append(kw))
    await runner.aplicar_criterios("lead-1", {"segment": "cafeteria"}, rotulo="")
    assert gravados[0]["evidence"] is None
    assert gravados[0]["updates"] == {"segment": "cafeteria"}


# ── O ponto de entrada (acrescentado: o rascunho não cobria `processar_inbound`,
#    que é onde as 8 peças se encontram e onde uma troca de ordem passa em
#    silêncio por todos os testes unitários acima) ───────────────────────────
@pytest.fixture
def turno(monkeypatch):
    """Dirige `processar_inbound` com o banco e o CRM dublados."""
    from app.button_flow import effects, valeria_content

    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    estado = {"valor": None}
    registro = {"efeitos": [], "score": [], "mensagens": [], "notas": []}
    conversa = {"id": "C1", "stage": "atacado", "flow_state": None}
    lead = {"id": "L1", "phone": "5534988861441", "wa_id": "5534988861441",
            "name": "Roner", "human_control": False, "metadata": {}}

    def _gravar_estado(_cid, **kw):
        estado["valor"] = kw["flow_state"]
        conversa["flow_state"] = kw["flow_state"]

    monkeypatch.setattr(runner, "_reler_estado", lambda c: c.get("flow_state"))
    monkeypatch.setattr(runner, "get_open_deal", lambda _l: None)
    monkeypatch.setattr(runner, "update_conversation", _gravar_estado)
    monkeypatch.setattr(runner, "save_message",
                        lambda *a, **k: registro["mensagens"].append(a[3]))
    monkeypatch.setattr(runner, "url_publica_da_foto", lambda _c: None)
    monkeypatch.setattr(runner, "preco_do_no", lambda _no: "R$ 28,70")
    monkeypatch.setattr(runner, "save_score_evidence",
                        lambda **kw: registro["score"].append(kw))
    monkeypatch.setattr(valeria_content, "carregar", lambda _f: {})
    monkeypatch.setattr(effects, "anotar",
                        lambda *a: registro["notas"].append(a[2]))

    def _aplicar(efeitos, **_kw):
        registro["efeitos"].append(efeitos)
        return True
    monkeypatch.setattr(effects, "aplicar", _aplicar)

    provedor = ProvedorFalso()

    async def _rodar(texto, *, payload=None, titulo=""):
        meta = {"payload": payload, "title": titulo} if payload else None
        await runner.processar_inbound(
            lead=lead, conversation=conversa, channel={"mode": "ai"},
            provider=provedor, texto=texto, metadata=meta, wamid="wamid.in",
        )
        return estado["valor"]

    _rodar.provedor = provedor
    _rodar.registro = registro
    return _rodar


@pytest.mark.asyncio
async def test_primeiro_contato_recebe_a_tela_de_entrada(turno):
    """O lead abre a conversa com texto: a resposta é a tela de setor, NÃO o
    nudge. Rodar o motor num estado vazio devolveria "é só tocar numa das
    opções" a quem nunca recebeu opção nenhuma — e gastaria 1 dos 3 nudges no
    turno de abertura."""
    estado = await turno("oi, queria saber sobre café")
    assert turno.provedor.chamadas[0][0] == "lista"
    assert estado["node"] == reg.NO_ENTRADA
    assert estado["nudges"] == 0


@pytest.mark.asyncio
async def test_clique_avanca_o_no_e_grava_o_score(turno):
    await turno("oi")
    await turno("Pro meu negócio", payload="negocio", titulo="Pro meu negócio")
    estado = await turno("Cafeteria", payload="cafeteria", titulo="Cafeteria")
    assert estado["node"] == "N2"
    assert estado["nudges"] == 0
    assert turno.registro["score"][0]["updates"] == {"segment": "cafeteria"}
    assert turno.registro["score"][0]["evidence"] == {"segment": {"text": "Cafeteria"}}


@pytest.mark.asyncio
async def test_texto_livre_reoferece_o_mesmo_no_e_gasta_nudge(turno):
    await turno("oi")
    estado = await turno("e quanto custa?")
    assert estado["node"] == reg.NO_ENTRADA, "o nudge não avança o fluxo"
    assert estado["nudges"] == 1
    assert reg.CORPO_NUDGE in turno.provedor.chamadas[-1][1]


@pytest.mark.asyncio
async def test_pedido_de_saida_no_primeiro_turno_vence_a_tela_de_entrada(turno):
    """A Meta EXIGE honrar o pedido de parar, e o primeiro turno é o pior lugar
    possível para ignorá-lo."""
    estado = await turno("pare")
    assert estado["node"] == "T_OPTOUT"
    assert turno.registro["efeitos"][0].optout is True
    assert turno.provedor.chamadas[0][0] == "texto"


@pytest.mark.asyncio
async def test_kill_switch_desligado_nao_envia_nem_grava(turno, monkeypatch):
    monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)
    assert await turno("oi") is None
    assert turno.provedor.chamadas == []
    assert turno.registro["efeitos"] == []


@pytest.mark.asyncio
async def test_falha_do_provedor_nao_impede_o_avanco_do_estado(turno):
    """O clique aconteceu: perder o envio não pode fazer o lead reviver o nó
    anterior no turno seguinte."""
    async def explode(*_a, **_k):
        raise RuntimeError("Meta 131047")
    turno.provedor.send_interactive_list = explode
    estado = await turno("oi")
    assert estado["node"] == reg.NO_ENTRADA

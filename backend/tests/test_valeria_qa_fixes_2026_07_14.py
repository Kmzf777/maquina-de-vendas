"""Guardas da auditoria Valéria 14/07 — funções puras.

Casos reais que motivaram cada guarda (ver
docs/superpowers/reports/auditoria_valeria_2026-07-14.md):

- strip_kitchen_leak: Thiago Romanini (2c2f0ea4) recebeu 2× "opa, o sistema não encontrou
  o 'Café Canastra 250g — embalagem do cliente' no catálogo de atacado…" — a saída BRUTA
  de calcular_orcamento vazou pro cliente (o prompt de atacado proíbe: "o cliente NUNCA vê
  a cozinha").
- media_result_is_no_send: Marcelo Dummel (67e8b921) — "to te mandando aqui as fotos" sem
  foto nenhuma; o modelo chamou enviar_foto_produto p/ produto inexistente ("foto do
  produto '…' nao encontrada"), marcando media_tool_used sem enviar nada.
- contains_open_question: Gilberto Medeiros (790906f4) perguntou "Tenho que investir?" e
  foi descartado com registrar_sem_interesse_atual sem resposta.
"""

from app.agent.adherence import (
    contains_open_question,
    media_result_is_no_send,
    strip_kitchen_leak,
)


# ---------------------------------------------------------------------------
# #1 strip_kitchen_leak
# ---------------------------------------------------------------------------
class TestStripKitchenLeak:
    def test_caso_thiago_remove_leak_preserva_util(self):
        raw = (
            "opa, o sistema não encontrou o 'Café Canastra 250g — embalagem do cliente' "
            "no catálogo de atacado, ele tem as opções de moído ou em grãos, e os tamanhos "
            "de 250g, 500g ou 1kg"
        )
        out = strip_kitchen_leak(raw)
        assert "sistema" not in out.lower()
        assert "catálogo" not in out.lower() and "catalogo" not in out.lower()
        assert "não encontrou" not in out.lower() and "nao encontrou" not in out.lower()
        # trecho útil preservado
        assert "moído ou em grãos" in out or "moido ou em graos" in out.lower()

    def test_deu_erro_aqui(self):
        out = strip_kitchen_leak("opa, deu um erro aqui, me confirma o produto?")
        assert "erro" not in out.lower()
        assert "confirma o produto" in out.lower()

    def test_sistema_travou(self):
        out = strip_kitchen_leak("o sistema travou, mas já te ajudo")
        assert "sistema" not in out.lower()

    def test_frase_legitima_com_sistema_nespresso_intacta(self):
        raw = "as cápsulas são compatíveis com o sistema Nespresso, quer que eu te mostre?"
        assert strip_kitchen_leak(raw) == raw

    def test_sistema_de_torra_intacto(self):
        raw = "o nosso sistema de torra é sob demanda, garante frescor"
        assert strip_kitchen_leak(raw) == raw

    def test_mensagem_toda_leak_fail_open(self):
        raw = "o sistema não encontrou o produto no catálogo"
        # se remover esvazia, devolve original (camada 1 é a rede primária)
        assert strip_kitchen_leak(raw) == raw

    def test_texto_normal_inalterado(self):
        raw = "boa, o 250g fica R$26,70 a unidade, faz sentido pra você?"
        assert strip_kitchen_leak(raw) == raw

    def test_vazio(self):
        assert strip_kitchen_leak("") == ""


# ---------------------------------------------------------------------------
# #2 media_result_is_no_send
# ---------------------------------------------------------------------------
class TestMediaResultIsNoSend:
    def test_produto_nao_encontrado(self):
        assert media_result_is_no_send("foto do produto 'standup' nao encontrada") is True

    def test_categoria_nao_encontrada(self):
        assert media_result_is_no_send("Categoria xyz nao encontrada") is True

    def test_nenhuma_foto(self):
        assert media_result_is_no_send("Nenhuma foto encontrada para atacado") is True

    def test_sucesso_enfileiradas_nao_e_falha(self):
        assert media_result_is_no_send(
            "4 fotos de private_label enfileiradas para envio após o texto"
        ) is False

    def test_sucesso_foto_produto_nao_e_falha(self):
        assert media_result_is_no_send(
            "foto de standup enfileirada para envio após o texto"
        ) is False

    def test_ja_enviada_nao_e_falha(self):
        # idempotência: fotos já existem na conversa → claim satisfeito
        assert media_result_is_no_send("fotos ja enviadas nesta conversa — nao reenviar") is False
        assert media_result_is_no_send("foto de standup ja enviada nesta conversa — nao reenviar") is False

    def test_none_e_vazio(self):
        assert media_result_is_no_send(None) is False
        assert media_result_is_no_send("") is False


# ---------------------------------------------------------------------------
# #3 contains_open_question
# ---------------------------------------------------------------------------
class TestContainsOpenQuestion:
    def test_caso_gilberto_tenho_que_investir(self):
        assert contains_open_question(
            "Estou pensando em começar do zero \nTenho que investir? \nSe sim não tenho como fazer isso"
        ) is True

    def test_qual_o_valor(self):
        assert contains_open_question("qual o valor?") is True

    def test_como_funciona(self):
        assert contains_open_question("como funciona a parte da embalagem?") is True

    def test_tem_pedido_minimo(self):
        assert contains_open_question("tem pedido mínimo?") is True

    def test_rejeicao_sem_pergunta_nao_casa(self):
        assert contains_open_question("não quero, muito caro pra mim") is False

    def test_cortesia_tudo_bem_nao_casa(self):
        assert contains_open_question("tudo bem?") is False

    def test_ok_nao_casa(self):
        assert contains_open_question("ok?") is False
        assert contains_open_question("certo, obrigado") is False

    def test_sem_interrogacao_nao_casa(self):
        assert contains_open_question("vou pensar e te falo depois") is False

    def test_none_e_vazio(self):
        assert contains_open_question(None) is False
        assert contains_open_question("") is False


# ===========================================================================
# Integração (run_agent) — wiring dos guards #2 e #3
# ===========================================================================
import pytest
from unittest.mock import AsyncMock, patch

from tests.gemini_fakes import fake_text, fake_tool_call


def _conv(stage: str = "private_label") -> dict:
    return {
        "id": "conv-qa-1407",
        "stage": stage,
        "leads": {
            "id": "lead-qa-1407", "name": "Teste", "phone": "5511900000077",
            "ai_enabled": True,
        },
    }


def _hist() -> list:
    return [{
        "role": "user", "content": "oi", "stage": "private_label",
        "created_at": "2026-07-14T10:00:00Z", "wamid": "wamid-qa-1",
        "quoted_wamid": None, "message_type": "text", "metadata": None,
    }]


def _patches(exec_mock, gen):
    return (
        patch("app.agent.orchestrator.get_history", return_value=_hist()),
        patch("app.agent.orchestrator.get_lead", return_value={
            "id": "lead-qa-1407", "phone": "5511900000077", "ai_enabled": True}),
        patch("app.agent.orchestrator.execute_tool", exec_mock),
        patch("app.agent.orchestrator.track_token_usage"),
        patch("app.agent.orchestrator.generate", gen),
    )


# --- #3: descarte abortado quando o lead fez pergunta -----------------------
@pytest.mark.asyncio
async def test_descarte_abortado_quando_lead_perguntou():
    from app.agent.orchestrator import run_agent
    exec_mock = AsyncMock(return_value="ok")
    gen = AsyncMock(side_effect=[
        fake_tool_call("registrar_sem_interesse_atual",
                       {"motivo": "lead disse que nao tem como investir"}),
        fake_text("boa pergunta! o investimento inicial e enxuto, comeca com 50 unidades"),
    ])
    with _patches(exec_mock, gen)[0], _patches(exec_mock, gen)[1], \
         _patches(exec_mock, gen)[2], _patches(exec_mock, gen)[3], _patches(exec_mock, gen)[4]:
        await run_agent(_conv("private_label"), "Tenho que investir?")
    nomes = [c.args[0] for c in exec_mock.call_args_list]
    assert "registrar_sem_interesse_atual" not in nomes, (
        f"descarte NAO deveria executar com pergunta aberta; chamadas={nomes}")


@pytest.mark.asyncio
async def test_descarte_prossegue_sem_pergunta():
    from app.agent.orchestrator import run_agent
    exec_mock = AsyncMock(return_value="ok")
    gen = AsyncMock(side_effect=[
        fake_tool_call("registrar_sem_interesse_atual", {"motivo": "sem interesse, muito caro"}),
        fake_text("sem problema, fico a disposicao"),
    ])
    with _patches(exec_mock, gen)[0], _patches(exec_mock, gen)[1], \
         _patches(exec_mock, gen)[2], _patches(exec_mock, gen)[3], _patches(exec_mock, gen)[4]:
        await run_agent(_conv("private_label"), "nao quero, muito caro pra mim")
    nomes = [c.args[0] for c in exec_mock.call_args_list]
    assert "registrar_sem_interesse_atual" in nomes, (
        f"descarte legitimo deveria executar; chamadas={nomes}")


# --- #2: guarda de fotos verbalizadas dispara quando a midia nao enviou ------
def _exec_media(no_send: bool):
    def _side(name, *a, **k):
        if name == "enviar_foto_produto":
            return ("foto do produto 'standup' nao encontrada" if no_send
                    else "foto de standup enfileirada para envio após o texto")
        return "ok"
    return AsyncMock(side_effect=_side)


@pytest.mark.asyncio
async def test_fotos_guard_dispara_no_send():
    from app.agent.orchestrator import run_agent
    exec_mock = _exec_media(no_send=True)
    gen = AsyncMock(side_effect=[
        fake_tool_call("enviar_foto_produto", {"produto": "standup"}),
        fake_text("to te mandando aqui as fotos do nosso portfolio"),
    ])
    with _patches(exec_mock, gen)[0], _patches(exec_mock, gen)[1], \
         _patches(exec_mock, gen)[2], _patches(exec_mock, gen)[3], _patches(exec_mock, gen)[4]:
        await run_agent(_conv("private_label"), "quero ver imagens")
    nomes = [c.args[0] for c in exec_mock.call_args_list]
    assert "enviar_fotos" in nomes, (
        f"guarda deveria forcar enviar_fotos apos midia sem envio; chamadas={nomes}")


@pytest.mark.asyncio
async def test_fotos_guard_silencioso_quando_enviou():
    from app.agent.orchestrator import run_agent
    exec_mock = _exec_media(no_send=False)
    gen = AsyncMock(side_effect=[
        fake_tool_call("enviar_foto_produto", {"produto": "standup"}),
        fake_text("to te mandando aqui as fotos do nosso portfolio"),
    ])
    with _patches(exec_mock, gen)[0], _patches(exec_mock, gen)[1], \
         _patches(exec_mock, gen)[2], _patches(exec_mock, gen)[3], _patches(exec_mock, gen)[4]:
        await run_agent(_conv("private_label"), "quero ver imagens")
    nomes = [c.args[0] for c in exec_mock.call_args_list]
    assert "enviar_fotos" not in nomes, (
        f"guarda NAO deveria forcar enviar_fotos quando a foto foi enviada; chamadas={nomes}")

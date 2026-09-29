"""send_interactive_list e o header de imagem do send_interactive_buttons.

O payload é conferido campo a campo porque a Meta recusa em silêncio (HTTP 200 com
`messages` ausente) quando a forma está errada — e recusa silenciosa aqui significa
lead sem resposta.
"""
import pytest

from app.whatsapp.meta import MetaCloudClient


class _Espiao(MetaCloudClient):
    """Captura o payload em vez de chamar a Meta."""
    def __init__(self):
        self.enviado = None

    async def _post(self, payload, request_type=""):
        self.enviado = payload
        return {"messages": [{"id": "wamid.TESTE"}]}


@pytest.mark.asyncio
async def test_lista_monta_sections_com_rows():
    cliente = _Espiao()
    await cliente.send_interactive_list(
        to="5534988861441", body="o café é pra qual caso?", button="Ver as opções",
        rows=[("negocio", "Pro meu negócio", "revenda, cafeteria"),
              ("marca", "Com a minha marca", "")],
    )
    interativo = cliente.enviado["interactive"]
    assert interativo["type"] == "list"
    assert interativo["body"]["text"] == "o café é pra qual caso?"
    assert interativo["action"]["button"] == "Ver as opções"
    linhas = interativo["action"]["sections"][0]["rows"]
    assert linhas[0] == {"id": "negocio", "title": "Pro meu negócio",
                         "description": "revenda, cafeteria"}
    # Descrição vazia sai FORA do payload: a Meta rejeita description="".
    assert linhas[1] == {"id": "marca", "title": "Com a minha marca"}


@pytest.mark.asyncio
async def test_lista_recusa_acima_de_10_linhas():
    cliente = _Espiao()
    with pytest.raises(ValueError, match="1 a 10"):
        await cliente.send_interactive_list(
            to="5534988861441", body="x", button="ver",
            rows=[(f"id{i}", f"t{i}", "") for i in range(11)],
        )


@pytest.mark.asyncio
async def test_botoes_com_image_url_viram_header():
    cliente = _Espiao()
    await cliente.send_interactive_buttons(
        to="5534988861441", body="gira em torno de R$28,70",
        buttons=[("sim", "Sim, quero falar")],
        image_url="https://exemplo/classico.jpg",
    )
    interativo = cliente.enviado["interactive"]
    assert interativo["header"] == {
        "type": "image", "image": {"link": "https://exemplo/classico.jpg"}
    }


@pytest.mark.asyncio
async def test_botoes_sem_image_url_nao_tem_header():
    """Regressão da recuperação: o fluxo existente não manda header."""
    cliente = _Espiao()
    await cliente.send_interactive_buttons(
        to="5534988861441", body="x", buttons=[("a", "A")],
    )
    assert "header" not in cliente.enviado["interactive"]

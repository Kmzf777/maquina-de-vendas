"""Criação da proposta no Bling: o `numero` vem de um GET, e ele é best-effort.

O POST /propostas-comerciais responde `201 {"data":{"id":N}}` — SÓ o id. O
`numero`, que é o que sai impresso no PDF e o que o cliente cita ao responder,
só existe depois de um `GET /propostas-comerciais/{id}`.

Esse GET é a parte frágil do fluxo, e a regra que este arquivo tranca é
contraintuitiva: **falhar o GET não pode derrubar a criação**. No instante em
que o POST volta 201 a proposta JÁ EXISTE no ERP. Se uma exceção subisse daqui,
o vendedor veria erro, tentaria de novo, e o segundo POST criaria uma SEGUNDA
proposta para o mesmo orçamento — e ao contrário do pedido de venda, que tem
`numeroLoja` como chave de idempotência, a proposta comercial não tem campo
nenhum onde ancorar uma retentativa segura. Duplicata aqui é definitiva.
"""
from decimal import Decimal

import pytest

from app.bling.errors import BlingServerError, BlingValidationError
from app.quotes import proposals

ITENS = [{
    "bling_product_id": 777,
    "codigo": "CAF250",
    "descricao": "Cafe Classico 250g",
    "unidade": "UN",
    "quantidade": 1,
    "valor_unitario": "100.00",
    "desconto_percentual": 0,
}]

ARGS = dict(
    contact_id=555,
    quoted_at="2026-08-25",
    itens=ITENS,
    discount_value=Decimal("0"),
    freight=Decimal("0"),
    freight_mode=None,
    method_id=45,
    terms=[0],
    seller_id=None,
    store_id=None,
    notes="",
    internal_notes="",
    aos_cuidados_de="",
)


class FakeClient:
    """Dublê do BlingClient. Registra as chamadas na ORDEM em que aconteceram —
    é a ordem que os testes de idempotência precisam inspecionar."""

    def __init__(self, *, post=None, get=None, get_erro=None, patch_erro=None):
        self.calls: list[tuple] = []
        self._post = post if post is not None else {"data": {"id": 987654}}
        self._get = get if get is not None else {"data": {"id": 987654, "numero": 13}}
        self._get_erro = get_erro
        self._patch_erro = patch_erro

    async def post(self, path, json=None):
        self.calls.append(("POST", path, json))
        if isinstance(self._post, Exception):
            raise self._post
        return self._post

    async def get(self, path, params=None):
        self.calls.append(("GET", path, params))
        if self._get_erro:
            raise self._get_erro
        return self._get

    async def put(self, path, json=None):
        self.calls.append(("PUT", path, json))
        return {}

    async def request(self, method, path, *, params=None, json=None):
        self.calls.append((method, path, json))
        if self._patch_erro:
            raise self._patch_erro
        return {}

    def metodos(self) -> list[str]:
        return [c[0] for c in self.calls]


# ---------------------------------------------------------------------------
# create_proposal
# ---------------------------------------------------------------------------
async def test_post_devolve_so_o_id_e_o_numero_vem_do_get_seguinte():
    client = FakeClient(post={"data": {"id": 987654}},
                        get={"data": {"id": 987654, "numero": 13}})

    out = await proposals.create_proposal(client, **ARGS)

    assert out["bling_proposal_id"] == 987654
    assert out["bling_proposal_number"] == 13
    assert client.metodos() == ["POST", "GET"]
    assert client.calls[0][1] == "/propostas-comerciais"
    assert client.calls[1][1] == "/propostas-comerciais/987654"


async def test_get_que_falha_nao_derruba_a_criacao():
    """O caso central: a proposta existe, o número não. Grava `None` e segue."""
    client = FakeClient(get_erro=BlingServerError("bling fora do ar"))

    out = await proposals.create_proposal(client, **ARGS)

    assert out["bling_proposal_id"] == 987654
    assert out["bling_proposal_number"] is None
    assert client.metodos().count("POST") == 1, (
        "um POST e só um: repetir criaria uma segunda proposta no ERP")


async def test_get_com_429_tambem_e_engolido():
    """Rate limit é o erro mais provável logo depois de um POST (o orçamento de
    3 req/s é por conta), e é justamente o que mais tentaria virar retentativa."""
    from app.bling.errors import BlingRateLimitError

    client = FakeClient(get_erro=BlingRateLimitError("429"))
    out = await proposals.create_proposal(client, **ARGS)
    assert out["bling_proposal_number"] is None


async def test_get_sem_numero_no_corpo_devolve_none():
    """Resposta 200 mas magra (proxy, mudança de contrato) não pode virar
    KeyError depois do POST aceito."""
    client = FakeClient(get={"data": {"id": 987654}})
    out = await proposals.create_proposal(client, **ARGS)
    assert out["bling_proposal_number"] is None


async def test_get_com_corpo_vazio_devolve_none():
    client = FakeClient(get={})
    out = await proposals.create_proposal(client, **ARGS)
    assert out["bling_proposal_number"] is None


async def test_recusa_do_post_sobe_e_nao_ha_get():
    """Antes do 201 não há nada no ERP — aqui a exceção TEM que subir, para o
    router devolver 422 e o vendedor corrigir o payload."""
    client = FakeClient(post=BlingValidationError("itens invalidos"))

    with pytest.raises(BlingValidationError):
        await proposals.create_proposal(client, **ARGS)

    assert client.metodos() == ["POST"]


async def test_post_sem_id_no_corpo_e_erro():
    """201 sem `data.id` é contrato quebrado: sem id não há como editar, mudar
    situação ou converter a proposta depois. Falhar alto é melhor do que gravar
    um orçamento órfão que ninguém consegue mais tocar."""
    client = FakeClient(post={"data": {}})
    with pytest.raises(Exception):
        await proposals.create_proposal(client, **ARGS)


async def test_corpo_enviado_e_o_mesmo_do_build_proposal_payload():
    """`create_proposal` não monta corpo por conta própria — o formato mora num
    lugar só, que é onde os testes de payload apontam."""
    client = FakeClient()
    await proposals.create_proposal(client, **ARGS)

    esperado = proposals.build_proposal_payload(
        situacao=proposals.SITUACAO_INICIAL, **ARGS)
    assert client.calls[0][2] == esperado


# ---------------------------------------------------------------------------
# update_proposal
# ---------------------------------------------------------------------------
async def test_update_usa_put_no_id_da_proposta():
    client = FakeClient()

    await proposals.update_proposal(client, proposal_id=987654,
                                    situacao="Pendente", **ARGS)

    assert client.metodos() == ["PUT"]
    assert client.calls[0][1] == "/propostas-comerciais/987654"
    assert client.calls[0][2]["situacao"] == "Pendente"


async def test_update_nao_reenvia_campos_readonly():
    client = FakeClient()
    await proposals.update_proposal(client, proposal_id=987654,
                                    situacao="Rascunho", **ARGS)
    corpo = client.calls[0][2]
    for campo in ("id", "total", "totalProdutos"):
        assert campo not in corpo


# ---------------------------------------------------------------------------
# set_situacao
# ---------------------------------------------------------------------------
async def test_set_situacao_usa_patch_no_sub_recurso_situacoes():
    """PATCH, e não PUT: o PUT substituiria a proposta inteira pelo corpo
    enviado — mandar só `{"situacao": ...}` apagaria itens e parcelas.

    O verbo vai por `client.request` porque o `BlingClient` expõe atalhos só
    para GET/POST/PUT; `request` é público e aplica o mesmo rate limit e a
    mesma política de retry.
    """
    client = FakeClient()

    await proposals.set_situacao(client, proposal_id=987654, situacao="Aprovado")

    assert client.calls == [("PATCH", "/propostas-comerciais/987654/situacoes",
                             {"situacao": "Aprovado"})]


@pytest.mark.parametrize("situacao", [
    "Pendente", "Aguardando", "Não aprovado", "Aprovado", "Concluído", "Rascunho",
])
async def test_todas_as_situacoes_do_enum_sao_aceitas(situacao):
    """O enum é literal, COM acento e COM a caixa exata da spec. 'Nao aprovado'
    sem til é recusado pelo Bling."""
    client = FakeClient()
    await proposals.set_situacao(client, proposal_id=1, situacao=situacao)
    assert client.calls[0][2] == {"situacao": situacao}


async def test_situacao_fora_do_enum_e_recusada_antes_da_chamada():
    """Erro local em vez de 400 do Bling: gastar uma requisição do orçamento de
    3 req/s para descobrir um typo nosso é desperdício, e a rajada de erro conta
    para o bloqueio de IP."""
    client = FakeClient()

    with pytest.raises(BlingValidationError):
        await proposals.set_situacao(client, proposal_id=1, situacao="aprovado")

    assert client.calls == []


def test_mapa_de_status_cobre_todo_o_vocabulario_local():
    """`quotes.status` é vocabulário NOSSO (sem acento, caixa baixa); a situação
    do Bling é outra coisa. Todo status precisa de tradução — um status sem
    entrada no mapa viraria KeyError no meio do PATCH."""
    assert proposals.STATUS_SITUACAO == {
        "rascunho": "Rascunho",
        "enviado": "Pendente",
        "aprovado": "Aprovado",
        "nao_aprovado": "Não aprovado",
        "convertido": "Aprovado",
        "cancelado": "Não aprovado",
    }
    assert set(proposals.STATUS_SITUACAO.values()) <= set(proposals.SITUACOES)

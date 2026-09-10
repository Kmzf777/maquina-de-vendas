"""Auditoria 09/09 — o portao do handoff proativo do `qualificar_lead`.

`_t_qualificar_lead` nunca foi so uma tool de anotacao: quando `finalidade` E `volume`
estao preenchidos ela cascateia para `encaminhar_humano`, desliga a IA e manda o cartao
do Joao. O portao era apenas "as duas strings sao truthy" — sem nenhuma nocao de
qualidade do dado nem de preco.

Medicao em producao (09/09/2026):
- 28 dos 30 handoffs proativos do historico (93%) sairam com ZERO preco na conversa.
- Das 71 chamadas com volume preenchido, 38 nao tinham numero nenhum: "a definir" (20x),
  "pesquisando", "pouco", "vender muito", "atacado", "sem referencia", "inicial"...
- Caso 5527981570476 (09/09 17:28): o lead disse "Sim" e colou a legenda de uma foto;
  o modelo registrou volume="a ser definido" e o lead foi transbordado sem ver preco.

O modelo nao estava desobedecendo — a descricao da tool manda "chame assim que captar
cada uma, NAO espere o lead pedir pra comprar", e o prompt manda registrar ancoras
justamente quando o lead NAO qualificou. Registrar cedo + ambos preenchidos = handoff.

Decisao (usuario, 09/09): o portao passa a exigir volume CONCRETO **e** preco ja
mostrado. Faltando preco, a tool devolve uma instrucao pra Valeria apresentar o preco
no mesmo turno — o transbordo fica pro turno seguinte.
"""
import pytest
from unittest.mock import patch

from app.agent import tools
from app.agent.tools import _t_qualificar_lead, _volume_concreto
from app.agent.tool_registry import ToolContext


# ---------------------------------------------------------------------------
# 1. Volume concreto vs vago
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("vago", [
    # Frases reais colhidas em producao que abriram o portao indevidamente.
    "a definir", "a ser definido", "inicial", "pesquisando", "sem referencia",
    "quantidade para testar", "atacado", "pequeno", "pouco", "ainda no planejamento",
    "vender muito", "iniciando experiência", "amostra para teste",
    "pequenas quantidades", "consumo interno da empresa",
    "minimo possivel para teste e baixo investimento",
    "", "   ", None,
])
def test_volume_vago_nao_e_concreto(vago):
    assert _volume_concreto(vago) is False


@pytest.mark.parametrize("real", [
    "100 unidades", "3kg mensais", "60kg/mes", "5kg/mês", "10kg/mês",
    "saca de 60kg", "400 a 500 kg por mes", "50kg/mês", "10 pacotes",
    "100 pacotes de 250g", "20 a 30kg/mês", "600kg mensais",
])
def test_volume_com_quantidade_e_concreto(real):
    assert _volume_concreto(real) is True


def test_numero_nao_salva_frase_vaga():
    """"a definir a partir de 10" continua vago — a palavra-chave vence o numero."""
    assert _volume_concreto("a definir a partir de 10 pacotes") is False
    assert _volume_concreto("pesquisando, talvez 5kg") is False


# ---------------------------------------------------------------------------
# 2. O portao da cascata
# ---------------------------------------------------------------------------

def _ctx(args: dict, invoke=None) -> ToolContext:
    """ToolContext e frozen — `invoke` entra na construcao, nao por atribuicao."""
    return ToolContext(
        args=args, lead_id="lead-q1", phone="5511999990001", conversation_id="conv-q1",
        invoke=invoke,
    )


class _Spy:
    """Captura a cascata: registra se encaminhar_humano foi invocado."""
    def __init__(self):
        self.invoked = []

    async def invoke(self, name, args):
        self.invoked.append((name, args))
        return f"cascata:{name}"


@pytest.fixture
def ambiente(monkeypatch):
    """Isola a tool do banco: lead sem ancoras previas, saves no vazio."""
    monkeypatch.setattr(tools, "get_lead", lambda _id: {"metadata": {}})
    monkeypatch.setattr(tools, "update_lead", lambda *a, **k: None)
    monkeypatch.setattr(tools, "save_message", lambda *a, **k: None)


@pytest.mark.asyncio
async def test_volume_vago_nao_dispara_handoff(ambiente, monkeypatch):
    """O caso 5527981570476: volume='a ser definido' nao pode transbordar."""
    monkeypatch.setattr(tools, "_preco_ja_mostrado", lambda _c: True)
    spy = _Spy()
    ctx = _ctx({"finalidade": "revenda", "volume": "a ser definido"}, spy.invoke)
    out = await _t_qualificar_lead(ctx)
    assert spy.invoked == [], "handoff proativo disparou com volume vago"
    assert "registrada" in out.lower() or "ancora" in out.lower()


@pytest.mark.asyncio
async def test_sem_preco_nao_dispara_handoff_e_pede_preco(ambiente, monkeypatch):
    """Volume concreto mas lead nunca viu preco: apresenta preco, transborda depois."""
    monkeypatch.setattr(tools, "_preco_ja_mostrado", lambda _c: False)
    spy = _Spy()
    ctx = _ctx({"finalidade": "revenda", "volume": "100 unidades"}, spy.invoke)
    out = await _t_qualificar_lead(ctx)
    assert spy.invoked == [], "transbordou sem o lead ter visto preco"
    # A tool precisa INSTRUIR a Valeria a mostrar o preco neste turno e adiar o handoff.
    assert "apresente agora o preço" in out.lower()
    assert "próximo turno" in out.lower()


@pytest.mark.asyncio
async def test_volume_concreto_com_preco_dispara_handoff(ambiente, monkeypatch):
    """Caminho feliz preservado: o 'caso Joabe' continua sendo resgatado."""
    monkeypatch.setattr(tools, "_preco_ja_mostrado", lambda _c: True)
    spy = _Spy()
    ctx = _ctx({"finalidade": "revenda", "volume": "100 unidades"}, spy.invoke)
    out = await _t_qualificar_lead(ctx)
    assert [n for n, _ in spy.invoked] == ["encaminhar_humano"]
    assert "100 unidades" in spy.invoked[0][1]["motivo"]


@pytest.mark.asyncio
async def test_sem_volume_continua_sem_handoff(ambiente, monkeypatch):
    """Comportamento antigo preservado: volume ausente nunca transbordou."""
    monkeypatch.setattr(tools, "_preco_ja_mostrado", lambda _c: True)
    spy = _Spy()
    ctx = _ctx({"finalidade": "revenda"}, spy.invoke)
    await _t_qualificar_lead(ctx)
    assert spy.invoked == []


# ---------------------------------------------------------------------------
# 3. Deteccao de preco na conversa
# ---------------------------------------------------------------------------

def test_preco_ja_mostrado_reconhece_cifrao(monkeypatch):
    monkeypatch.setattr(
        tools, "get_conversation_history",
        lambda _c, limit=None: [
            {"role": "user", "content": "quanto custa?"},
            {"role": "assistant", "content": "o Suave moido 250g gira em torno de R$28,70"},
        ],
    )
    assert tools._preco_ja_mostrado("conv-x") is True


def test_preco_ja_mostrado_ignora_preco_dito_pelo_LEAD(monkeypatch):
    """"consigo por R$12" dito pelo lead nao e preco APRESENTADO pela Valeria."""
    monkeypatch.setattr(
        tools, "get_conversation_history",
        lambda _c, limit=None: [
            {"role": "user", "content": "meu fornecedor faz por R$12"},
            {"role": "assistant", "content": "entendi, o nosso e cafe especial"},
        ],
    )
    assert tools._preco_ja_mostrado("conv-x") is False


def test_preco_ja_mostrado_fail_open_em_erro(monkeypatch):
    """Falha de banco nao pode travar o funil — na duvida, deixa passar."""
    def _boom(*a, **k):
        raise RuntimeError("db fora do ar")
    monkeypatch.setattr(tools, "get_conversation_history", _boom)
    assert tools._preco_ja_mostrado("conv-x") is True


# ---------------------------------------------------------------------------
# 4. A descricao da tool nao pode mais mentir pro modelo
# ---------------------------------------------------------------------------

def test_descricao_declara_as_duas_condicoes():
    decl = next(d for d in tools.TOOL_DECLARATIONS if d["name"] == "qualificar_lead")
    desc = decl["description"].lower()
    assert "quantidade real" in desc
    assert "preco ja apresentado" in desc


def test_descricao_orienta_volume_vago():
    decl = next(d for d in tools.TOOL_DECLARATIONS if d["name"] == "qualificar_lead")
    vol = decl["parameters"]["properties"]["volume"]["description"]
    assert "a definir" in vol.lower()

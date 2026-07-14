"""Card 3 da revisão de arquitetura (12/07): registry de tools.

Antes: três estruturas paralelas em tools.py sincronizadas só pelo nome-string
(TOOL_DECLARATIONS · escada de 16 elifs em execute_tool · dict inline de allowlist
por stage), mais um canal oculto — os efeitos diferidos (mídia/interesse/orçamento)
atravessavam o seam tool→processor por dicts globais mutados DE DENTRO do corpo das
tools (classe do bug Wander: fila drenada e marcador mentiroso).

Depois: uma declaração `Tool` por ferramenta co-locando schema, executor, stages e
efeitos; declarações, dispatch e allowlist são VIEWS derivadas do registry; os efeitos
viajam no valor de retorno (`ToolResult.effects`) e `execute_tool` é o único escritor.

Estes testes são a rede da refatoração: travam a paridade de contrato (nomes, schemas,
allowlist por stage) e o novo invariante (nenhum corpo de tool escreve em global).
"""
import inspect
import re

import pytest

from app.agent import tools as T
from app.agent.tool_registry import Tool, ToolEffects, ToolResult, TurnEffects


# Contrato congelado: os 16 nomes que existiam na escada de elifs antes da refatoração.
EXPECTED_TOOLS = {
    "salvar_nome", "mudar_stage", "encaminhar_humano", "qualificar_lead",
    "registrar_optout", "registrar_sem_interesse_atual", "registrar_numero_errado",
    "registrar_indicacao", "enviar_fotos", "enviar_foto_produto", "marcar_interesse",
    "adicionar_tag_lead", "retomar_contato_vendedor", "agendar_retorno",
    "consultar_relacionamento", "calcular_orcamento",
}

# Allowlist por stage exatamente como estava no dict inline de get_tools_for_stage.
EXPECTED_STAGE_TOOLS = {
    "secretaria": {
        "salvar_nome", "mudar_stage", "encaminhar_humano", "registrar_optout",
        "registrar_sem_interesse_atual", "registrar_numero_errado", "registrar_indicacao",
        "marcar_interesse", "retomar_contato_vendedor", "adicionar_tag_lead",
        "agendar_retorno", "consultar_relacionamento",
    },
    "atacado": {
        "salvar_nome", "mudar_stage", "encaminhar_humano", "qualificar_lead",
        "registrar_optout", "registrar_sem_interesse_atual", "registrar_indicacao",
        "enviar_fotos", "enviar_foto_produto", "marcar_interesse",
        "retomar_contato_vendedor", "adicionar_tag_lead", "agendar_retorno",
        "consultar_relacionamento", "calcular_orcamento",
    },
    "private_label": {
        "salvar_nome", "mudar_stage", "encaminhar_humano", "qualificar_lead",
        "registrar_optout", "registrar_sem_interesse_atual", "registrar_indicacao",
        "enviar_fotos", "enviar_foto_produto", "marcar_interesse",
        "retomar_contato_vendedor", "adicionar_tag_lead", "agendar_retorno",
        "consultar_relacionamento", "calcular_orcamento",
    },
    "exportacao": {
        "salvar_nome", "mudar_stage", "encaminhar_humano", "qualificar_lead",
        "registrar_optout", "registrar_sem_interesse_atual", "marcar_interesse",
        "retomar_contato_vendedor", "adicionar_tag_lead", "agendar_retorno",
        "consultar_relacionamento",
    },
    # Varejo B2C NÃO auto-descarta: sem registrar_sem_interesse_atual, sem handoff.
    "consumo": {
        "salvar_nome", "mudar_stage", "registrar_optout", "marcar_interesse",
        "adicionar_tag_lead", "agendar_retorno", "consultar_relacionamento",
    },
}


# ---------------------------------------------------------------- o registry existe
def test_registry_conhece_exatamente_as_16_tools():
    assert set(T.REGISTRY.names()) == EXPECTED_TOOLS


def test_toda_tool_declarada_tem_executor_e_schema():
    """O acoplamento nome-string entre 3 estruturas morre: a declaração É o executor."""
    for name in T.REGISTRY.names():
        tool = T.REGISTRY.get(name)
        assert isinstance(tool, Tool)
        assert callable(tool.handler), f"{name} sem executor"
        assert inspect.iscoroutinefunction(tool.handler), f"{name}: handler deve ser async"
        assert tool.description, f"{name} sem description"
        assert tool.parameters.get("type") == "object", f"{name} sem schema de parâmetros"


# ------------------------------------------------- declarações e allowlist são views
def test_tool_declarations_e_view_derivada_do_registry():
    decls = T.TOOL_DECLARATIONS
    assert {d["name"] for d in decls} == EXPECTED_TOOLS
    for d in decls:
        assert set(d.keys()) == {"name", "description", "parameters"}, (
            "a declaração enviada ao Gemini não pode carregar campos internos do registry"
        )


@pytest.mark.parametrize("stage,expected", sorted(EXPECTED_STAGE_TOOLS.items()))
def test_allowlist_por_stage_derivada_do_registry(stage, expected):
    names = {t["name"] for t in T.get_tools_for_stage(stage)}
    assert names == expected


def test_stage_desconhecido_cai_no_minimo_seguro():
    assert [t["name"] for t in T.get_tools_for_stage("stage-que-nao-existe")] == ["salvar_nome"]


# --------------------------------------------------- efeitos declarados na interface
def test_efeitos_fazem_parte_do_contrato_da_tool():
    """O call site enxerga o efeito sem ler o corpo da tool."""
    assert T.REGISTRY.get("enviar_fotos").effects.defers_media is True
    assert T.REGISTRY.get("enviar_foto_produto").effects.defers_media is True
    assert T.REGISTRY.get("marcar_interesse").effects.marks_interest is True
    assert T.REGISTRY.get("calcular_orcamento").effects.quotes_price is True
    assert T.REGISTRY.get("encaminhar_humano").effects.disables_ai is True
    assert T.REGISTRY.get("registrar_optout").effects.disables_ai is True
    assert T.REGISTRY.get("registrar_sem_interesse_atual").effects.disables_ai is True
    # Cascata declarada (fix S1: qualificar_lead pode virar handoff).
    assert "encaminhar_humano" in T.REGISTRY.get("qualificar_lead").effects.may_cascade_to
    # Tool sem efeito colateral no turno declara ausência de efeitos.
    assert T.REGISTRY.get("salvar_nome").effects == ToolEffects()


# ----------------------------------- efeitos viajam pelo retorno, não por global
@pytest.mark.asyncio
async def test_midia_diferida_viaja_no_retorno_sem_tocar_global(monkeypatch):
    """enviar_fotos com sink explícito: fila chega pelo valor de retorno e o global fica limpo."""
    monkeypatch.setattr(T, "get_history", lambda *a, **k: [])
    conv_id = "conv-registry-media"
    T._deferred_media.pop(conv_id, None)
    sink = TurnEffects()

    result = await T.execute_tool(
        "enviar_fotos", {"categoria": "atacado"},
        lead_id="lead-1", phone="5511999999999", conversation_id=conv_id,
        effects=sink,
    )

    assert "enfileiradas" in result
    assert sink.deferred_media, "a mídia deve chegar pelo sink de efeitos do turno"
    assert all(item["marker"].startswith("[enviar_fotos]") for item in sink.deferred_media)
    assert T._deferred_media.get(conv_id) in (None, []), (
        "com sink explícito nada pode ser escrito no buffer global"
    )


@pytest.mark.asyncio
async def test_interesse_e_orcamento_viajam_no_retorno(monkeypatch):
    monkeypatch.setattr(T, "get_lead", lambda *a, **k: {"stage": "atacado"})
    monkeypatch.setattr(T, "mark_deal_qualificado", lambda *a, **k: None)
    conv_id = "conv-registry-interesse"
    T._interest_marked.pop(conv_id, None)
    sink = TurnEffects()

    await T.execute_tool(
        "marcar_interesse", {"nivel": "quente", "motivo": "pediu preço"},
        lead_id="lead-1", phone="5511999999999", conversation_id=conv_id,
        effects=sink,
    )

    assert sink.interest == {"nivel": "quente", "motivo": "pediu preço"}
    assert T._interest_marked.get(conv_id) is None


@pytest.mark.asyncio
async def test_dedup_intra_turno_le_a_fila_do_sink(monkeypatch):
    """Segunda chamada no mesmo turno não duplica o lote — a fila do turno é a autoridade."""
    monkeypatch.setattr(T, "get_history", lambda *a, **k: [])
    sink = TurnEffects()
    kwargs = dict(lead_id="lead-1", phone="5511999999999", conversation_id="conv-dedup-sink", effects=sink)

    await T.execute_tool("enviar_fotos", {"categoria": "atacado"}, **kwargs)
    n_primeiro = len(sink.deferred_media)
    segundo = await T.execute_tool("enviar_fotos", {"categoria": "atacado"}, **kwargs)

    assert "ja enfileiradas neste turno" in segundo
    assert len(sink.deferred_media) == n_primeiro


@pytest.mark.asyncio
async def test_sem_sink_os_efeitos_caem_no_buffer_por_conversa(monkeypatch):
    """Retrocompat: o processor continua drenando por pop_deferred_media."""
    monkeypatch.setattr(T, "get_history", lambda *a, **k: [])
    conv_id = "conv-registry-legacy"
    T._deferred_media.pop(conv_id, None)

    await T.execute_tool(
        "enviar_fotos", {"categoria": "atacado"},
        lead_id="lead-1", phone="5511999999999", conversation_id=conv_id,
    )

    queued = T.pop_deferred_media(conv_id)
    assert queued and all(i["marker"].startswith("[enviar_fotos]") for i in queued)
    assert T.pop_deferred_media(conv_id) == []


# ------------------------------------------------- o canal global some do corpo das tools
def test_nenhum_handler_escreve_no_buffer_global():
    """Guard estrutural: só o publicador de efeitos pode escrever nos dicts por conversa.

    Um corpo de tool que volte a mutar _deferred_media/_interest_marked/_quote_executed
    reabre a classe do bug Wander (efeito invisível ao call site). Se este teste falhar,
    o efeito novo deve entrar em TurnEffects, não num global.
    """
    proibidos = ("_deferred_media", "_interest_marked", "_quote_executed")
    for name in T.REGISTRY.names():
        src = inspect.getsource(T.REGISTRY.get(name).handler)
        # Só o CÓDIGO conta: comentários podem citar os nomes (ex.: a explicação do caso
        # Wander menciona record_deferred_media_delivery, que roda no processor).
        codigo = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
        for global_name in proibidos:
            assert not re.search(rf"\b{global_name}\b", codigo), (
                f"handler de {name} toca no global {global_name} — "
                "use ToolResult(effects=...) para publicar o efeito"
            )


@pytest.mark.asyncio
async def test_tool_desconhecida_mantem_a_mensagem_de_contrato():
    out = await T.execute_tool("tool_inexistente", {}, "lead-1", "5511999999999", "conv-x")
    assert out == "Tool tool_inexistente nao reconhecida"


# ----------------------------------------------------------------- tipos do registry
def test_tool_result_aceita_str_puro_e_efeitos():
    assert ToolResult("ok").message == "ok"
    assert ToolResult("ok").effects == TurnEffects()

    eff = TurnEffects(quote_executed=True)
    assert ToolResult("ok", effects=eff).effects.quote_executed is True


def test_turn_effects_merge_acumula_midia_e_flags():
    a = TurnEffects(deferred_media=[{"marker": "m1"}])
    b = TurnEffects(deferred_media=[{"marker": "m2"}], quote_executed=True, interest={"nivel": "quente"})

    a.merge(b)

    assert [m["marker"] for m in a.deferred_media] == ["m1", "m2"]
    assert a.quote_executed is True
    assert a.interest == {"nivel": "quente"}
